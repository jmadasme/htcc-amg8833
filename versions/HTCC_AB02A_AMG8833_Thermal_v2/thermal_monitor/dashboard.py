# -*- coding: utf-8 -*-
"""
dashboard.py

Servidor web (aiohttp) + broker MQTT (amqtt) para visualizar en tiempo
real la termocÃ¡mara LoRaWAN AMG8833.

- Levanta un broker MQTT en 0.0.0.0:1883 (el gateway UG56 publica aquÃ­).
- Sirve una pÃ¡gina web en http://0.0.0.0:8080 con el heatmap 8x8.
- ReenvÃ­a los uplinks al navegador por WebSocket (/ws).
- AdemÃ¡s del MQTT, acepta la data del gateway por HTTP: POST /ingest.
- Recibe comandos de downlink por WebSocket y los publica al UG56 en
  command/{DevEUI} (p. ej. consultar RSSI del nodo con '03 00').

Uso:
    python dashboard.py            # web en 8080, broker en 1883
    python dashboard.py 8081 1884  # web en 8081, broker en 1884

En entorno PaaS (Render/Railway/...) el puerto web se toma de la variable
de entorno PORT si no se pasa por argumento.
"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path
import re

from amqtt.broker import Broker
from amqtt.client import MQTTClient
from amqtt.errors import ClientError
from amqtt.contexts import BrokerConfig, ListenerConfig

from aiohttp import web, WSMsgType

from decoder import decode_uplink_data, PayloadDecodeError

HOST = "0.0.0.0"
BROKER_BIND = f"{HOST}:1883"
WEB_PORT = 8080
MQTT_TOPICS = ["data/#", "#"]

# TÃ³pico de downlink del UG56 (comandos gateway -> nodo, FPort 1).
# Por defecto se publica a command/{DevEUI}; si el UG56 usa topic fijo
# "command/", define la variable de entorno DOWNLINK_TOPIC="command/".
DOWNLINK_TOPIC = os.environ.get("DOWNLINK_TOPIC", "command/")

# DevEUI por defecto: se asigna a frames vÃ¡lidos sin DevEUI en payload ni topic
# (p. ej. el nodo real publicando al topic plano "data/").
DEFAULT_DEV_EUI = os.environ.get("DEFAULT_DEV_EUI", "70b3d56f27cee98b")

# Comandos de downlink disponibles (bytes, formato documentado v2.1)
CMD_FIELDS = {
    "sf":      {"code": 0x01, "arg": (7, 8, 9),           "desc": "Cambiar SF (7..9)"},
    "interval": {"code": 0x02, "arg": (1, 1440),          "desc": "Cambiar ciclo (min)"},
    "rssi":    {"code": 0x03, "arg": (0, 0),              "desc": "Consultar RSSI (03 00)"},
}

# Directorio del proyecto (para rutas relativas, desplegable en PaaS)
BASE_DIR = Path(__file__).resolve().parent

# Clientes WebSocket conectados
WS_CLIENTS: set = set()

# Ãšltimo frame por dispositivo (devEUI -> frame), para multi-nodo
LAST_FRAMES = {}

# Nombres opcionales por DevEUI, desde el fichero devices.json
DEVICE_NAMES = {}


def _load_device_names():
    global DEVICE_NAMES
    p = BASE_DIR / "devices.json"
    if p.exists():
        try:
            DEVICE_NAMES = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            DEVICE_NAMES = {}


_load_device_names()

# Cliente MQTT publicador (downlinks). Se conecta al broker local en main().
PUB_CLIENT = None
BROKER_PORT = 1883


def build_command_payload(command):
    """Construye el payload MQTT de un comando de downlink. Devuelve dict o None."""
    cmd = command.get("cmd")
    spec = CMD_FIELDS.get(cmd)
    if not spec:
        return None
    code = spec["code"]

    if cmd == "rssi":
        payload_bytes = bytes([0x03, 0x00])
    elif cmd == "sf":
        payload_bytes = bytes([0x01, int(command.get("value", 7))])
    elif cmd == "interval":
        val = int(command.get("value", 1))
        payload_bytes = bytes([0x02, (val >> 8) & 0xFF, val & 0xFF])
    else:
        return None

    dev_eui = (command.get("dev_eui")
               or (next(iter(LAST_FRAMES)) if LAST_FRAMES else None)
               or "70b3d56f27cee98b")

    # Si DOWNLINK_TOPIC es un prefijo (termina en '/') se concatena el DevEUI;
    # si es un topic completo ("command/mi-gateway"), se usa tal cual.
    if DOWNLINK_TOPIC.endswith("/"):
        topic = f"{DOWNLINK_TOPIC}{dev_eui}"
    else:
        topic = DOWNLINK_TOPIC

    return {
        "topic": topic,
        "payload": json.dumps({
            "confirmed": False,
            "fPort": 1,
            "data": payload_bytes.hex().upper(),
            "devEUI": dev_eui,
        }).encode(),
    }


async def publish_command(command):
    """Publica un comando de downlink al nodo por MQTT. Devuelve bool."""
    global PUB_CLIENT
    if PUB_CLIENT is None:
        return False
    built = build_command_payload(command)
    if built is None:
        return False
    try:
        await PUB_CLIENT.publish(built["topic"], built["payload"])
        print(f"[DL] comando '{command.get('cmd')}' publicado en {built['topic']}")
        return True
    except Exception as e:
        print(f"[DL] error publicando: {e}")
        return False


def build_broker_config(port):
    cfg = BrokerConfig()
    cfg.listeners = {
        "default": ListenerConfig(type="tcp", bind=f"{HOST}:{port}")
    }
    return cfg


def _dev_from_topic(topic):
    """Extrae el DevEUI del topic MQTT cuando el payload no lo trae.

    Acepta tÃ³picos tipo 'data/{EUI}', '{app}/device/{EUI}/event/up', etc.
    Devuelve None si no encuentra un DevEUI de 16 hex en el topic.
    """
    if not topic:
        return None
    m = re.search(r"(?:device|data)/([0-9a-fA-F]{16})", topic)
    return m.group(1) if m else None


def _process_payload(raw, topic=None):
    """Convierte un payload del UG56 en un diccionario Ãºtil (frame).

    Acepta:
      - bytes (crudo del MQTT): puede ser un JSON ya decodificado por el
        gateway (fields 'object' o a nivel raÃ­z), o bien un payload LoRaWAN
        en base64 (campo 'data') que se decodifica con decoder.py.
      - dict ya parseado (HTTP /ingest).

    Devuelve un frame normalizado o None si no es un frame tÃ©rmico vÃ¡lido.
    """
    if isinstance(raw, dict):
        data = raw
    else:
        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception:
            return None
    if not isinstance(data, dict):
        return None

    obj = data.get("object") if isinstance(data.get("object"), dict) else data

    # --- Caso A: gateway ya decodificÃ³. Acepta frame con pixels_C (64),
    # o un frame COMPACTO (SF8/9) con kind + estadÃ­sticas pero sin mapa.
    pixels = obj.get("pixels_C")
    if isinstance(pixels, list) and len(pixels) == 64:
        try:
            pixels = [float(v) for v in pixels]
        except Exception:
            return None
    else:
        kind = obj.get("kind")
        has_stats = ("pixel_min_C" in obj or "pixel_max_C" in obj or
                     "thermistor_C" in obj or "battery_mV" in obj)
        if not (kind in ("compact", "full", "legacy") and has_stats):
            return None
        pixels = None
    if pixels is None:
        pmin = obj.get("pixel_min_C")
        pmax = obj.get("pixel_max_C")
        pavg = obj.get("pixel_avg_C")
    else:
        pmin = obj.get("pixel_min_C", min(pixels))
        pmax = obj.get("pixel_max_C", max(pixels))
        pavg = obj.get("pixel_avg_C", round(sum(pixels) / len(pixels), 2))
    batt_v = obj.get("battery_V")
    return {
        "kind": obj.get("kind", "full"),
        "pixels_C": pixels,
        "pixel_min_C": pmin,
        "pixel_max_C": pmax,
        "pixel_avg_C": pavg,
        "thermistor_C": obj.get("thermistor_C"),
        "battery_mV": obj.get("battery_mV"),
        "battery_V": batt_v if batt_v is not None
        else (round(obj["battery_mV"] / 1000, 2) if obj.get("battery_mV") else None),
        "sensor_ok": bool(obj.get("sensor_ok", True)),
        "sf": obj.get("sf"),
        "interval_min": obj.get("interval_min"),
        "rssi_dBm": obj.get("rssi_dBm"),
        "rssi": data.get("rssi") or obj.get("rssi"),
        "snr": data.get("snr") or obj.get("snr"),
        "dev_eui": (data.get("devEUI") or data.get("devEui") or data.get("deveui")
                    or _dev_from_topic(topic) or DEFAULT_DEV_EUI),
        "f_port": data.get("fPort") or data.get("fport") or data.get("f_port"),
    }

    # --- Caso B: payload LoRaWAN crudo en base64 (campo 'data') ---
    b64 = data.get("data")
    if b64:
        try:
            dec = decode_uplink_data(b64)
        except PayloadDecodeError:
            return None
        batt_v = dec.get("battery_V")
        return {
            "kind": dec.get("kind", "legacy"),
            "pixels_C": dec.get("pixels_C"),
            "pixel_min_C": dec.get("pixel_min_C"),
            "pixel_max_C": dec.get("pixel_max_C"),
            "pixel_avg_C": dec.get("pixel_avg_C"),
            "thermistor_C": dec.get("thermistor_C"),
            "battery_mV": dec.get("battery_mV"),
            "battery_V": batt_v if batt_v is not None
            else (round(dec["battery_mV"] / 1000, 2) if dec.get("battery_mV") else None),
            "sensor_ok": bool(dec.get("sensor_ok", True)),
            "sf": dec.get("sf"),
            "interval_min": dec.get("interval_min"),
            "rssi_dBm": dec.get("rssi_dBm"),
            "rssi": data.get("rssi"),
            "snr": data.get("snr"),
"dev_eui": (data.get("devEUI") or data.get("devEui") or data.get("deveui")
                    or _dev_from_topic(topic) or DEFAULT_DEV_EUI),
        "f_port": data.get("fPort") or data.get("fport") or data.get("f_port"),
    }

    return None


async def broadcast_frame(frame):
    """Guarda el Ãºltimo frame por dispositivo y lo reenvÃ­a a los WebSockets."""
    global LAST_FRAMES
    if "ts" not in frame:
        frame["ts"] = time.time()
    dev = frame.get("dev_eui") or "unknown"
    LAST_FRAMES[dev] = frame
    text = json.dumps(frame)
    for ws in list(WS_CLIENTS):
        try:
            await ws.send_str(text)
        except Exception:
            WS_CLIENTS.discard(ws)


async def mqtt_loop(broker_port):
    """Se suscribe al broker y reenvÃ­a los frames tÃ©rmicos a los websockets."""
    client = MQTTClient(client_id="dashboard")
    while True:
        try:
            await client.connect(f"mqtt://127.0.0.1:{broker_port}/")
            for t in MQTT_TOPICS:
                await client.subscribe([(t, 1)])
            print(f"[MQTT] conectado al broker local, escuchando {MQTT_TOPICS}")
            break
        except ClientError as e:
            print(f"[MQTT] no se pudo conectar ({e}); reintentando en 2s...")
            await asyncio.sleep(2)

    try:
        while True:
            message = await client.deliver_message()
            if message is None:
                continue
            frame = _process_payload(message.data, message.topic)
            if frame is None:
                continue
            await broadcast_frame(frame)
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass


async def ws_handler(request):
    ws = web.WebSocketResponse(heartbeat=30)
    await ws.prepare(request)
    WS_CLIENTS.add(ws)
    print(f"[WS] cliente conectado ({len(WS_CLIENTS)} total)")
    # Enviar la lista de dispositivos conocidos al conectarse
    devices = [
        {
            "dev_eui": eui,
            "nickname": DEVICE_NAMES.get(eui, ""),
            "last_frame": fr,
        }
        for eui, fr in sorted(LAST_FRAMES.items())
    ]
    try:
        await ws.send_str(json.dumps({
            "type": "device_list",
            "devices": devices,
        }))
    except Exception:
        pass
    try:
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                try:
                    cmd = json.loads(msg.data)
                except Exception:
                    continue
                if isinstance(cmd, dict) and cmd.get("type") == "command":
                    ok = await publish_command(cmd)
                    await ws.send_str(json.dumps({
                        "type": "command_ack",
                        "cmd": cmd.get("cmd"),
                        "ok": ok,
                    }))
            elif msg.type == WSMsgType.ERROR:
                break
    finally:
        WS_CLIENTS.discard(ws)
        print(f"[WS] cliente desconectado ({len(WS_CLIENTS)} total)")
    return ws


async def ingest_handler(request):
    """Ingesta por HTTP: el UG56 (o un relay) hace POST de un JSON
    y el frame se reenvÃ­a por WebSocket igual que por MQTT."""
    try:
        body = await request.read()
    except Exception:
        return web.json_response({"ok": False, "error": "read_error"}, status=400)

    try:
        data = json.loads(body.decode("utf-8"))
    except Exception:
        return web.json_response({"ok": False, "error": "invalid_json"}, status=400)

    frame = _process_payload(data)
    if frame is None:
        return web.json_response({"ok": True, "accepted": False,
                                  "reason": "not_thermal_frame"}, status=200)

    await broadcast_frame(frame)
    print(f"[INGEST] frame HTTP recibido max={frame['pixel_max_C']} "
          f"min={frame['pixel_min_C']} ws={len(WS_CLIENTS)}")
    return web.json_response({"ok": True, "accepted": True}, status=202)


async def index_handler(request):
    return web.FileResponse(BASE_DIR / "index.html")


async def fondo_handler(request):
    return web.FileResponse(BASE_DIR / "fondo2.jpg")


async def health_handler(request):
    return web.json_response({"ok": True, "ws_clients": len(WS_CLIENTS)})


async def main():
    broker_port = int(sys.argv[2]) if len(sys.argv) > 2 else 1883
    try:
        if len(sys.argv) > 1:
            web_port = int(sys.argv[1])
        else:
            web_port = int(os.environ.get("PORT", WEB_PORT))
    except ValueError:
        web_port = WEB_PORT

    # 1) Broker MQTT
    broker = Broker(config=build_broker_config(broker_port))
    await broker.start()
    print(f"[BROKER] MQTT escuchando en {HOST}:{broker_port}")

    # 2) Consumidor MQTT -> WebSocket
    asyncio.create_task(mqtt_loop(broker_port))

    # 3) Cliente publicador de downlinks (comandos del navegador -> UG56)
    global PUB_CLIENT, BROKER_PORT
    BROKER_PORT = broker_port
    PUB_CLIENT = MQTTClient(client_id="dashboard_cmd")
    try:
        await PUB_CLIENT.connect(f"mqtt://127.0.0.1:{broker_port}/", cleansession=True)
        print(f"[DL] publicador de comandos conectado al broker (topic {DOWNLINK_TOPIC}...)")
    except Exception as e:
        print(f"[DL] no se pudo conectar publicador de comandos: {e}")
        PUB_CLIENT = None

    # 4) Servidor web
    app = web.Application()
    app.router.add_get("/", index_handler)
    app.router.add_get("/ws", ws_handler)
    app.router.add_post("/ingest", ingest_handler)
    app.router.add_get("/fondo.jpg", fondo_handler)
    app.router.add_get("/fondo2.jpg", fondo_handler)
    app.router.add_get("/health", health_handler)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, HOST, web_port)
    await site.start()
    print(f"[WEB] dashboard en http://{HOST}:{web_port}  (y http://192.168.2.30:{web_port} en la red)")

    # Mantener vivo hasta Ctrl+C
    stop = asyncio.Event()
    try:
        await stop.wait()
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        await runner.cleanup()
        await broker.shutdown()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[DASHBOARD] detenido.")

