# -*- coding: utf-8 -*-
"""
dashboard.py

Servidor web (aiohttp) + broker MQTT (amqtt) para visualizar en tiempo
real la termocámara LoRaWAN AMG8833.

- Levanta un broker MQTT en 0.0.0.0:1883 (el gateway UG56 publica aquí).
- Sirve una página web en http://0.0.0.0:8080 con el heatmap 8x8.
- Reenvía los uplinks al navegador por WebSocket (/ws).

Uso:
    python dashboard.py            # web en 8080, broker en 1883
    python dashboard.py 8081 1884  # web en 8081, broker en 1884
"""

import asyncio
import json
import sys

from amqtt.broker import Broker
from amqtt.client import MQTTClient
from amqtt.errors import ClientError
from amqtt.contexts import BrokerConfig, ListenerConfig

from aiohttp import web, WSMsgType

HOST = "0.0.0.0"
BROKER_BIND = f"{HOST}:1883"
WEB_PORT = 8080
MQTT_TOPICS = ["data/#", "#"]

# Clientes WebSocket conectados
WS_CLIENTS: set = set()

# Último dato térmico (para los que se conecten después)
LAST_FRAME = None


def build_broker_config(port):
    cfg = BrokerConfig()
    cfg.listeners = {
        "default": ListenerConfig(type="tcp", bind=f"{HOST}:{port}")
    }
    return cfg


def _process_payload(raw):
    """Convierte un payload crudo del UG56 en un diccionario útil.

    Acepta tanto el formato decodificado por el gateway (fields en la
    raíz: pixels_C, thermistor_C, ...) como el formato con 'object'.
    Devuelve None si el payload no es un frame térmico válido.
    """
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None

    obj = data.get("object") if isinstance(data.get("object"), dict) else data
    pixels = obj.get("pixels_C")
    if not isinstance(pixels, list) or len(pixels) != 64:
        return None
    try:
        pixels = [float(v) for v in pixels]
    except Exception:
        return None

    batt_v = obj.get("battery_V")
    return {
        "pixels_C": pixels,
        "pixel_min_C": obj.get("pixel_min_C", min(pixels)),
        "pixel_max_C": obj.get("pixel_max_C", max(pixels)),
        "thermistor_C": obj.get("thermistor_C"),
        "battery_mV": obj.get("battery_mV"),
        "battery_V": batt_v if batt_v is not None
        else (round(obj["battery_mV"] / 1000, 2) if obj.get("battery_mV") else None),
        "sensor_ok": bool(obj.get("sensor_ok", True)),
        "dev_eui": data.get("devEUI") or data.get("devEui") or data.get("deveui"),
        "f_port": data.get("fPort") or data.get("fport") or data.get("f_port"),
    }


async def mqtt_loop(broker_port):
    """Se suscribe al broker y reenvía los frames térmicos a los websockets."""
    global LAST_FRAME
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
            frame = _process_payload(message.data)
            if frame is None:
                continue
            LAST_FRAME = frame
            text = json.dumps(frame)
            for ws in list(WS_CLIENTS):
                try:
                    await ws.send_str(text)
                except Exception:
                    WS_CLIENTS.discard(ws)
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
    # Enviar el último frame guardado al conectarse
    if LAST_FRAME is not None:
        try:
            await ws.send_str(json.dumps(LAST_FRAME))
        except Exception:
            pass
    try:
        async for msg in ws:
            if msg.type == WSMsgType.ERROR:
                break
    finally:
        WS_CLIENTS.discard(ws)
        print(f"[WS] cliente desconectado ({len(WS_CLIENTS)} total)")
    return ws


async def index_handler(request):
    return web.FileResponse(r"C:\Users\Cliente Preferido\Documents\Default Project\thermal_monitor\index.html")


async def health_handler(request):
    return web.json_response({"ok": True, "ws_clients": len(WS_CLIENTS)})


async def main():
    broker_port = int(sys.argv[2]) if len(sys.argv) > 2 else 1883
    try:
        web_port = int(sys.argv[1]) if len(sys.argv) > 1 else WEB_PORT
    except ValueError:
        web_port = WEB_PORT

    # 1) Broker MQTT
    broker = Broker(config=build_broker_config(broker_port))
    await broker.start()
    print(f"[BROKER] MQTT escuchando en {HOST}:{broker_port}")

    # 2) Consumidor MQTT -> WebSocket
    asyncio.create_task(mqtt_loop(broker_port))

    # 3) Servidor web
    app = web.Application()
    app.router.add_get("/", index_handler)
    app.router.add_get("/ws", ws_handler)
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
