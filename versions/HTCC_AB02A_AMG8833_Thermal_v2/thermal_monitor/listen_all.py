# -*- coding: utf-8 -*-
"""
Escucha TODOS los topicos (#) del broker MQTT local para diagnosticar
si el gateway UG56 esta publicando y con que formato de topicos.
"""
import sys
import time
import paho.mqtt.client as mqtt

HOST = "127.0.0.1"
PORT = 1883

print(f"Suscribiendose a '#' en {HOST}:{PORT} ...")
print("(Dispara un uplink del nodo / presiona el boton del sensor ahora)")
print("Ctrl+C para salir")
print()

count = [0]


def on_connect(client, userdata, flags, rc, properties=None):
    print(f"Conectado, rc={rc}. Escuchando...")
    client.subscribe("#", qos=1)


def on_message(client, userdata, msg):
    count[0] += 1
    print("=" * 70)
    print(f"[{count[0]}] TOPIC: {msg.topic}")
    try:
        print(f"      PAYLOAD: {msg.payload.decode('utf-8')}")
    except Exception:
        print(f"      PAYLOAD (binario): {msg.payload!r}")
    print()


client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.on_connect = on_connect
client.on_message = on_message
client.connect(HOST, PORT, 60)
client.loop_forever()
