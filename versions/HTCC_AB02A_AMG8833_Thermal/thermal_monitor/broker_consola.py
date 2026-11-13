# -*- coding: utf-8 -*-
"""
broker_consola.py

Broker MQTT de consola (Pure-Python con amqtt) + visor de tópicos.

- Levanta un broker MQTT en 0.0.0.0:<puerto>, accesible desde cualquier
  dispositivo de la red (incluido el gateway Milesight UG56).
- Se suscribe a los tópicos y muestra en consola, en tiempo real, qué
  mensajes llegan (tópico + payload).
- Queda corriendo como visor mientras la app se conecta y consume.

Uso:
    python broker_consola.py            # broker en 1883 (default)
    python broker_consola.py 1884       # broker en otro puerto
"""

import asyncio
import sys

from amqtt.broker import Broker
from amqtt.client import MQTTClient
from amqtt.errors import ClientError
from amqtt.contexts import BrokerConfig, ListenerConfig


def build_config(port):
    cfg = BrokerConfig()
    cfg.listeners = {
        "default": ListenerConfig(type="tcp", bind=f"0.0.0.0:{port}")
    }
    return cfg


def _fmt(payload):
    try:
        return payload.decode("utf-8")
    except Exception:
        return repr(payload)


async def broker_coro(port):
    broker = Broker(config=build_config(port))
    await broker.start()
    print(f"[BROKER MQTT] escuchando en 0.0.0.0:{port}")
    return broker


async def monitor_coro(port, subscribe_topics):
    client = MQTTClient(client_id="visor")
    try:
        await client.connect(f"mqtt://127.0.0.1:{port}/")
    except ClientError as e:
        print(f"[ERROR] No se pudo conectar el visor al broker local: {e}")
        return
    print(f"[VISOR] conectado al broker local. Suscribiendose a: {subscribe_topics}")
    for t in subscribe_topics:
        try:
            await client.subscribe([(t, 1)])
        except Exception as e:
            print(f"[VISOR] fallo al suscribir a '{t}': {e}")
    print("[VISOR] Mostrando los mensajes que lleguen... (Ctrl+C para salir)")
    try:
        while True:
            message = await client.deliver_message()
            if message is None:
                break
            print("=" * 70)
            print(f"  TOPIC   : {message.topic}")
            print("  PAYLOAD :")
            print(_fmt(message.data))
            print("=" * 70)
    except asyncio.CancelledError:
        pass
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 1883
    # Tópicos que muestra el visor; '#' captura cualquier formato
    # (util si el UG56 usa data/ o application/... por ejemplo).
    topics = ["#"]

    async def supervisor():
        broker = await broker_coro(port)
        monitor_task = asyncio.create_task(monitor_coro(port, topics))
        await monitor_task
        await broker.shutdown()

    try:
        asyncio.run(supervisor())
    except KeyboardInterrupt:
        print("\n[VISOR] detenido por el usuario.")


if __name__ == "__main__":
    main()
