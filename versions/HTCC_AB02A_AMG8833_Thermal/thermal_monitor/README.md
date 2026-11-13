# Termocámara LoRaWAN AMG8833 — Monitor de escritorio

Aplicación de escritorio para visualizar en **tiempo real** los datos de un
nodo LoRaWAN con termocámara **AMG8833** (matriz infrarroja 8x8), recibidos
a través de MQTT desde un gateway **Milesight UG56**.

## Requisitos

- Python 3.9+
- Las dependencias del archivo `requirements.txt`

## Instalación

```bash
pip install -r requirements.txt
```

## Configuración

Edita el archivo `config.json` con los datos de tu broker MQTT:

```json
{
  "broker": {
    "host": "IP_DEL_BROKER",
    "port": 1883,
    "username": "",
    "password": ""
  },
  "topic": "application/+/device/+/event/up",
  "device_eui_filter": "70b3d56f27cee98b"
}
```

- `host` / `port`: dirección del broker MQTT (p. ej. Mosquitto).
- `topic`: tópico de uplinks del gateway. Puede ser algo como
  `application/#` o `/milesight/uplink/#`.
- `device_eui_filter`: si quieres mostrar sólo un nodo concreto, pon su
  DevEUI. Déjalo vacío (`""`) para mostrar todos.

## Ejecución

```bash
python app.py
```

## Funcionalidades

- **Mapa térmico** interpolado (8x8 → imagen suave grande) con colorbar en °C.
- **Tarjetas KPI**: temp mín, temp máx, termistor, batería (V y %),
  RSSI y SNR.
- **Estado** del sensor (OK / FALLO), última actualización, contador de
  frames y método de decodificación (gateway o local).
- **Historial** de temperatura máx/mín a lo largo del tiempo.
- Botón de **escala automática/fija** para el mapa térmico.
- **Reconexión automática** y manejo robusto de mensajes no válidos.

## Notas de arquitectura MQTT

El flujo de datos es:

```
[CubeCell] --LoRaWAN--> [UG56] --MQTT--> [Broker MQTT] <--MQTT-- [app.py]
```

El UG56 es un cliente MQTT que publica; se necesita un broker (p. ej.
Mosquitto). Si no recibes datos, verifica en el UG56:
**Network Server > Application > Data Transmission > MQTT**.

## Estructura

```
app.py            # GUI y bucle principal
mqtt_client.py    # conexión MQTT y parseo del JSON
decoder.py        # decodificación del payload crudo (fallback)
thermal_render.py # matriz 8x8 -> imagen térmica coloreada
config.json       # host, puerto, credenciales, tópico
requirements.txt  # dependencias
```
