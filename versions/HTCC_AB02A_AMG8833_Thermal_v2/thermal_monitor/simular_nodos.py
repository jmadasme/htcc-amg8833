# -*- coding: utf-8 -*-
"""
simular_nodos.py

Generador de uplinks LoRaWAN SINTÉTICOS para varios nodos ficticios.
Publica a MQTT (topic data/) frames térmicos 8x8 con una "escena" distinta
por nodo, de modo que al cambiar de nodo en el dashboard se aprecie una
huella térmica y estadísticas diferentes.

Utilidad: ver y probar el comportamiento multi-nodo sin nodos físicos.

Uso:
    python simular_nodos.py             # publica cada 4 s
    python simular_nodos.py 10          # publica cada 10 s
    python simular_nodos.py 0           # un solo ciclo por nodo (para pruebas)

Requiere el dashboard corriendo (broker en 127.0.0.1:1883).
"""

import asyncio
import json
import math
import random
import sys
import time

from amqtt.client import MQTTClient

BROKER = "mqtt://127.0.0.1:1883/"

# Cada nodo demo tiene su propia "personalidad": escena térmica, SF y telemetría.
NODES = [
    {
        "devEUI": "70b3d56f27cee0001",
        "nombre": "Nodo demo — Bodega",
        "base": 18.0,
        "sf": 9,          # SF9 -> paquete compacto (sin mapa)
        "interval_min": 2,
        "battery_mV": 3328,
        "rssi": -45, "snr": 11.0, "rssi_dBm": -38,
        "spots": [
            {"x": 2.0, "y": 2.0, "peak": 4.0, "sigma": 1.1},
        ],
    },
    {
        "devEUI": "70b3d56f27cee0002",
        "nombre": "Nodo demo — Motor",
        "base": 32.0,
        "sf": 7,          # SF7 -> mapa completo
        "interval_min": 1,
        "battery_mV": 2800,
        "rssi": -48, "snr": 8.5, "rssi_dBm": -52,
        "spots": [
            {"x": 3.5, "y": 3.5, "peak": 9.0, "sigma": 2.2},   # foco central grande
            {"x": 6.5, "y": 1.2, "peak": 5.0, "sigma": 0.8},   # foco secundario
        ],
    },
    {
        "devEUI": "70b3d56f27cee0003",
        "nombre": "Nodo demo — Sala",
        "base": 24.0,
        "sf": 8,          # SF8 -> compacto
        "interval_min": 3,
        "battery_mV": 3150,
        "rssi": -42, "snr": 12.5, "rssi_dBm": -25,
        "spots": [
            {"x": 1.5, "y": 1.5, "peak": 3.5, "sigma": 1.0},
            {"x": 5.5, "y": 6.0, "peak": 2.5, "sigma": 1.4},
        ],
    },
]


def scene(nod, t):
    """Calcula los 64 píxeles (float °C) de la escena en el tiempo t.

    base + suma de gaussianos (hotspots) que derivan lentamente, + ruido.
    Resolución de 0.25 °C como el sensor real (redondeo a cuartos).
    """
    fase = t / 30.0
    px = []
    for y in range(8):
        for x in range(8):
            v = nod["base"]
            for s in nod["spots"]:
                cx = s["x"] + math.sin(fase * 0.7 + s["x"]) * 0.35
                cy = s["y"] + math.cos(fase * 0.5 + s["y"]) * 0.35
                d2 = (x - cx) ** 2 + (y - cy) ** 2
                v += s["peak"] * math.exp(-d2 / (2 * s["sigma"] ** 2))
            v += random.uniform(-0.35, 0.35)
            px.append(round(v * 4.0) / 4.0)
    return px


def build_payload(nod, t):
    """Construye el JSON (objeto decodificado estilo gateway) y el topic."""
    px = scene(nod, t)
    lo = min(px)
    hi = max(px)
    compact = nod["sf"] in (8, 9)
    obj = {
        "kind": "compact" if compact else "full",
        "sf": nod["sf"],
        "interval_min": nod["interval_min"],
        "rssi_dBm": nod["rssi_dBm"] if int(t) % 5 else None,
        "pixel_min_C": lo,
        "pixel_max_C": hi,
        "pixel_avg_C": round(sum(px) / 64, 2),
        "thermistor_C": round(nod["base"] - 1.2, 2),
        "battery_mV": nod["battery_mV"],
        "sensor_ok": True,
    }
    if not compact:
        obj["pixels_C"] = px
    payload = {
        "devEUI": nod["devEUI"],
        "fPort": 1,
        "rssi": nod["rssi"],
        "snr": nod["snr"],
        "object": obj,
    }
    return "data/" + nod["devEUI"], json.dumps(payload).encode(), hi


async def main(interval):
    client = MQTTClient(client_id="simular_nodos")
    await client.connect(BROKER)
    print(f"[SIM] Simulando {len(NODES)} nodos hacia {BROKER} cada {interval}s. "
          f"Ctrl+C para salir.")
    t0 = time.time()
    try:
        while True:
            t = time.time() - t0
            for nod in NODES:
                topic, payload, hi = build_payload(nod, t)
                await client.publish(topic, payload)
                print(f"[SIM] {nod['devEUI']} SF{nod['sf']} max={hi:.1f}°C")
            if interval <= 0:
                break
            await asyncio.sleep(interval)
    finally:
        await client.disconnect()
        print("[SIM] desconectado.")


if __name__ == "__main__":
    intervalo = float(sys.argv[1]) if len(sys.argv) > 1 else 4.0
    try:
        asyncio.run(main(intervalo))
    except KeyboardInterrupt:
        print("\n[SIM] detenido por el usuario.")