#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
thermal_viewer.py — Visor térmico para nodo LoRaWAN HTCC-AB02A + AMG8833
=========================================================================
Lee los 64 píxeles de temperatura (matriz 8x8) que la CubeCell envía cada
60 s al gateway Milesight UG56, y los convierte en una imagen térmica
(azul = frío, rojo = calor) superpuesta sobre una imagen PNG de fondo.

FLUJO:
  1. Se conecta al broker MQTT donde el UG56 (embedded NS) publica los uplinks.
  2. Por cada uplink (fPort 1) extrae los 64 valores de temperatura en °C:
       - Si el gateway ya aplicó el payload decoder (decoder.js), usa el
         campo "object" (object.pixels_C, object.thermistor_C, ...).
       - Si no, decodifica él mismo los 133 bytes crudos (campo "data" en
         base64 o "payload" en hex), con las resoluciones correctas del
         AMG8833 (termistor ×0.0625 °C/LSB, píxeles ×0.25 °C/LSB).
  3. Interpola la matriz 8x8 a una imagen grande (PIL bicubic).
  4. Aplica un colormap azul->rojo y lo superpone (alpha) sobre una PNG.
  5. Muestra la imagen en vivo y/o guarda cada frame como PNG.

USO:
  python3 thermal_viewer.py [--config config.json] [--no-window] [--once]

Requisitos: paho-mqtt, numpy, matplotlib, Pillow
            (pip install paho-mqtt numpy matplotlib Pillow)

Autor: pipeline LoRaWAN (nodo HTCC-AB02A + AMG8833)
"""

import argparse
import base64
import json
import os
import sys
import time

# ----------------------------------------------------------------------
# Configuración por defecto (se puede sobreescribir con config.json)
# ----------------------------------------------------------------------
DEFAULT_CONFIG = {
    # Broker MQTT al que el UG56 publica los datos (editar según tu red)
    "mqtt_host": "192.168.1.1",        # IP del gateway/broker
    "mqtt_port": 1883,
    "mqtt_username": None,             # None = sin credenciales
    "mqtt_password": None,
    # Tópico de uplink. En Milesight se configura en:
    #   Network Server > Application > Data Transmission > MQTT > Topic
    # Admite comodines, p.ej. "/milesight/uplink/#" o "application/#"
    "mqtt_topic": "/milesight/uplink/#",

    # Ruta de la imagen PNG de fondo (opcional). Si no existe, fondo negro.
    "background_png": "background.png",

    # Rango de temperatura del colormap (grados C).
    #   "auto" -> usa min/max de cada frame (máximo contraste)
    #   [min, max] -> rango fijo, p.ej. [15, 40]
    "temp_range": "auto",

    # Colormap: 'jet', 'turbo', 'inferno', 'plasma', 'coolwarm', 'magma'
    "colormap": "jet",

    # Resolución de la imagen térmica generada (px). La matriz 8x8 se
    # interpola a esta resolución cuadrada.
    "output_size": 320,

    # Opacidad del mapa térmico sobre el fondo (0.0 = invisible, 1.0 = opaco)
    "overlay_alpha": 0.65,

    # Carpeta donde se guardan los frames PNG (None = no guardar)
    "save_dir": "frames",

    # Prefijo de los archivos PNG guardados
    "save_prefix": "thermal",
}


# ----------------------------------------------------------------------
# Decodificación del payload crudo (misma lógica que decoder.js)
# ----------------------------------------------------------------------
def sign12(v):
    s = v & 0x0FFF
    if s & 0x0800:
        s -= 0x1000
    return s


def decode_payload_bytes(b):
    """
    Decodifica los 133 bytes del payload (puerto 1) a un diccionario.
    Devuelve None si el tamaño no es válido.
    """
    if b is None or len(b) < 133:
        return None

    version = b[0]
    therm_raw = (b[2] << 8) | b[1]
    pixels_raw = []
    for i in range(64):
        lo = b[3 + i * 2]
        hi = b[3 + i * 2 + 1]
        pixels_raw.append((hi << 8) | lo)

    batt = (b[131] << 8) | b[132]

    pixels_c = [round(sign12(v) * 0.25, 2) for v in pixels_raw]

    return {
        "version": version,
        "sensor_ok": (version == 0x01),
        "thermistor_C": round(sign12(therm_raw) * 0.0625, 2),
        "pixels_C": pixels_c,
        "pixel_min_C": round(min(pixels_c), 2),
        "pixel_max_C": round(max(pixels_c), 2),
        "battery_mV": batt,
        "battery_V": round(batt / 1000.0, 3),
    }


# ----------------------------------------------------------------------
# Extracción de valores desde un mensaje MQTT JSON
# ----------------------------------------------------------------------
def extract_pixels_c_from_json(msg):
    """
    Intenta extraer la lista de 64 temperaturas (pixels_C) de un mensaje
    MQTT JSON del Milesight UG56. Estrategias, en orden:
      1. msg["object"]["pixels_C"]  (gateway ya aplicó decoder.js)
      2. msg["object"]["pixels"]    (array crudo de 64 enteros)
      3. msg["data"] (base64) -> decode_payload_bytes
      4. msg["payload"] (hex string) -> decode_payload_bytes
    Devuelve (pixels_c, meta) o (None, None).
    """
    if not isinstance(msg, dict):
        return None, None

    # 1. object decodificado por el codec del gateway
    obj = msg.get("object")
    if isinstance(obj, dict):
        if isinstance(obj.get("pixels_C"), list) and len(obj["pixels_C"]) == 64:
            meta = {
                "thermistor_C": obj.get("thermistor_C"),
                "battery_mV": obj.get("battery_mV"),
                "battery_V": obj.get("battery_V"),
            }
            return [float(x) for x in obj["pixels_C"]], meta
        if isinstance(obj.get("pixels"), list) and len(obj["pixels"]) == 64:
            pixels_c = [round(sign12(int(v)) * 0.25, 2) for v in obj["pixels"]]
            return pixels_c, {}

    # 2. data en base64 (formato ChirpStack/embedded NS de Milesight)
    data = msg.get("data")
    if isinstance(data, str) and data:
        try:
            raw = base64.b64decode(data)
        except Exception:
            raw = b""
        decoded = decode_payload_bytes(raw)
        if decoded:
            return decoded["pixels_C"], decoded

    # 3. payload en hex string
    payload = msg.get("payload")
    if isinstance(payload, str) and payload:
        try:
            raw = bytes.fromhex(payload)
        except Exception:
            raw = b""
        decoded = decode_payload_bytes(raw)
        if decoded:
            return decoded["pixels_C"], decoded

    return None, None


# ----------------------------------------------------------------------
# Renderizado de la imagen térmica
# ----------------------------------------------------------------------
import numpy as np
from PIL import Image, ImageFilter
import matplotlib
matplotlib.use("Agg")  # backend sin ventana para guardar; se abre si hace falta
import matplotlib.cm as cm


def render_thermal(pixels_c, config):
    """
    Convierte la lista de 64 temperaturas en un array RGBA (numpy)
    del mapa térmico ya superpuesto sobre el fondo PNG.
    """
    # 1. Matriz 8x8
    grid = np.array(pixels_c, dtype=np.float64).reshape(8, 8)

    # 2. Normalización al rango [0,1]
    trange = config["temp_range"]
    if trange == "auto":
        vmin = float(grid.min())
        vmax = float(grid.max())
        if vmax - vmin < 0.5:  # evitar división por ~0 en escenas uniformes
            vmax = vmin + 0.5
    else:
        vmin, vmax = float(trange[0]), float(trange[1])

    norm = (grid - vmin) / (vmax - vmin)
    norm = np.clip(norm, 0.0, 1.0)

    # 3. Interpolar 8x8 -> NxN con PIL (bicubic)
    size = int(config["output_size"])
    img8 = (norm * 255.0).astype(np.uint8)
    pil8 = Image.fromarray(img8, mode="L")
    pil_big = pil8.resize((size, size), Image.BICUBIC)

    # 4. Colormap azul->rojo
    cmap = cm.get_cmap(config["colormap"])
    norm_big = np.asarray(pil_big, dtype=np.float64) / 255.0
    rgba = cmap(norm_big)               # (N, N, 4) float 0..1
    rgba = (rgba * 255.0).astype(np.uint8)

    # 5. Superponer sobre fondo PNG
    bg_path = config["background_png"]
    if bg_path and os.path.isfile(bg_path):
        bg = Image.open(bg_path).convert("RGBA").resize((size, size), Image.LANCZOS)
        bg_arr = np.asarray(bg, dtype=np.uint8).copy()
    else:
        bg_arr = np.zeros((size, size, 4), dtype=np.uint8)
        bg_arr[:, :, 3] = 255  # fondo negro opaco

    alpha = float(config["overlay_alpha"])
    heat_rgb = rgba[:, :, :3]
    heat_alpha = (rgba[:, :, 3].astype(np.float64) * alpha).astype(np.uint8)

    # blend: out = heat * a + bg * (1 - a)
    heat_alpha_f = (heat_alpha.astype(np.float64) / 255.0)[:, :, None]
    blended = (heat_rgb.astype(np.float64) * heat_alpha_f +
               bg_arr[:, :, :3].astype(np.float64) * (1.0 - heat_alpha_f))
    out = np.zeros_like(bg_arr)
    out[:, :, :3] = blended.astype(np.uint8)
    out[:, :, 3] = 255

    return out, vmin, vmax


# ----------------------------------------------------------------------
# Cliente MQTT
# ----------------------------------------------------------------------
def build_client(config, on_message):
    import paho.mqtt.client as mqtt

    client = mqtt.Client()
    if config.get("mqtt_username"):
        client.username_pw_set(config["mqtt_username"], config["mqtt_password"])
    client.on_message = on_message
    client.on_connect = lambda c, u, f, rc: (
        print(f"[MQTT] conectado rc={rc}, suscribiendo a {config['mqtt_topic']}"),
        c.subscribe(config["mqtt_topic"]),
    )
    return client


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Visor térmico AMG8833 vía MQTT")
    parser.add_argument("--config", default=None, help="Ruta a config.json")
    parser.add_argument("--no-window", action="store_true",
                        help="No abrir ventana (solo guardar PNG)")
    parser.add_argument("--once", action="store_true",
                        help="Salir tras el primer frame recibido")
    args = parser.parse_args()

    config = dict(DEFAULT_CONFIG)
    if args.config and os.path.isfile(args.config):
        with open(args.config, "r", encoding="utf-8") as f:
            user_cfg = json.load(f)
        config.update(user_cfg)

    # Preparar carpeta de guardado
    if config.get("save_dir"):
        os.makedirs(config["save_dir"], exist_ok=True)

    state = {"frames": 0, "latest": None, "done": False}
    window = None

    def on_message(client, userdata, msg):
        try:
            payload = msg.payload.decode("utf-8", "replace")
            try:
                obj = json.loads(payload)
            except json.JSONDecodeError:
                print(f"[MQTT] mensaje no-JSON en {msg.topic}: {payload[:80]}...")
                return

            pixels_c, meta = extract_pixels_c_from_json(obj)
            if pixels_c is None:
                # No es un uplink de nuestro nodo (join, status, etc.)
                return

            state["frames"] += 1
            print(f"\n[MQTT] Frame #{state['frames']} en {msg.topic}")
            print(f"        thermistor={meta.get('thermistor_C')} C  "
                  f"min={min(pixels_c):.2f} C  max={max(pixels_c):.2f} C  "
                  f"batt={meta.get('battery_V')} V")

            out, vmin, vmax = render_thermal(pixels_c, config)
            state["latest"] = out

            # Guardar PNG
            if config.get("save_dir"):
                fname = f"{config['save_prefix']}_{state['frames']:04d}.png"
                fpath = os.path.join(config["save_dir"], fname)
                Image.fromarray(out, mode="RGBA").save(fpath)
                print(f"        guardado -> {fpath}")

            # Actualizar ventana
            if window is not None:
                window.set_data(out)
                window.figure.canvas.draw_idle()
                window.figure.canvas.flush_events()

            if args.once:
                state["done"] = True
                client.disconnect()
        except Exception as e:
            print(f"[ERROR] procesando mensaje: {e}")

    import paho.mqtt.client as mqtt
    client = build_client(config, on_message)

    # Ventana en vivo (matplotlib)
    if not args.no_window and not args.once:
        import matplotlib.pyplot as plt
        plt.ion()
        fig, ax = plt.subplots()
        window = ax.imshow(np.zeros((config["output_size"], config["output_size"], 4),
                                    dtype=np.uint8))
        ax.set_title("AMG8833 Thermal — LoRaWAN")
        ax.axis("off")
        fig.canvas.draw()
        fig.canvas.flush_events()

    print(f"[MQTT] Conectando a {config['mqtt_host']}:{config['mqtt_port']} ...")
    client.connect(config["mqtt_host"], int(config["mqtt_port"]), 60)

    try:
        while not state["done"]:
            client.loop(timeout=1.0)
            if window is not None:
                import matplotlib.pyplot as plt
                plt.pause(0.05)
    except KeyboardInterrupt:
        print("\n[INFO] Interrumpido por el usuario.")
    finally:
        client.disconnect()
        print(f"[INFO] Frames procesados: {state['frames']}")


if __name__ == "__main__":
    main()
