# Termocámara LoRaWAN AMG8833 — Documentación para desarrollador

Sistema de **visualización en tiempo real** de un nodo LoRaWAN con termocámara
AMG8833 (matriz infrarroja 8×8). Compuesto por un **dashboard web** + un
**broker MQTT embebido** que recibe los uplinks del gateway Milesight UG56.

```
┌────────────┐   LoRaWAN   ┌────────────┐   MQTT (JSON)   ┌─────────────────────┐
│ Nodo Cub   │◄───────────►│ UG56       │────────────────►│ dashboard.py        │
│ AMG8833    │              │ (gateway)  │  topic: data/  │  broker 1883 + web  │
└────────────┘              └────────────┘                │  8080               │
                                                          │   │  WebSocket /ws   │
                                                          └───▼─────────────────┘
                                                                  │
                                                          ┌──────▼──────┐
                                                          │ Navegador   │
                                                          │ index.html  │
                                                          └─────────────┘
```

---

## 1. Arquitectura

| Capa | Tecnología | Puerto | Responsabilidad |
|------|-----------|--------|-----------------|
| Broker MQTT | `amqtt` (puro Python, asíncrono) | `1883` | Recibe los uplinks JSON del gateway UG56. Permite auth (usuario/contraseña) o anónimo. |
| Servidor web | `aiohttp` | `8080` | Sirve `index.html`, la fotografía de fondo y el endpoint WebSocket `/ws`. |
| Puente MQTT→WS | `dashboard.py` (`mqtt_loop`) | interno | Se suscribe al broker local, parsea los frames térmicos y los reenvía por WebSocket a los navegadores. |
| Frontend | HTML/CSS/JS plano | — | Canvas 8×8 coloreado, 3 vistas (óptica/térmica/combinada), tarjetas de telemetría. |

Todo vive en un **único proceso** (`dashboard.py`) que levanta las tres partes
(broker, consumidor y servidor web) mediante un único event loop `asyncio`.

---

## 2. Verificación rápida de requisitos

- **Python 3.12** (probado): `C:\Users\Cliente Preferido\AppData\Local\Programs\Python\Python312\python.exe`
- Dependencias (instaladas):
  - `amqtt==0.11.3` — broker/ cliente MQTT asíncrono.
  - `aiohttp==3.14.3` — servidor web + WebSocket.
- Dependencias de los scripts heredados de la app de escritorio (`requirements.txt`):
  - `paho-mqtt`, `numpy`, `Pillow` — usados por `mqtt_client.py`, `decoder.py`,
    `thermal_render.py` y `convertir_fondo_png.py` (no necesarias para `dashboard.py`).

Para reinstalar lo mínimo del dashboard:

```powershell
& "C:\Users\Cliente Preferido\AppData\Local\Programs\Python\Python312\python.exe" -m pip install amqtt==0.11.3 aiohttp
```

---

## 3. Diagrama de datos

Flujo de datos de punta a punta:

```
LoRaWAN radio     Uplink fPort 1 (payload AMG8833 v2.1)
      ▼
UG56 (Network Server embebido + Payload Codec)
      │  JSON decodificado → topic MQTT "data/"
      ▼
Broker local (dashboard.py: broker 1883)
      ▼
mqtt_loop()  —  _process_payload()  →  {"pixels_C": [64 floats], ...}
      ▼
WebSocket "/ws" → JSON
      ▼
index.html → render() → canvas 8×8 + stats

Comandos (downlink):  navegador → WS → /ws → dashboard.py → MQTT "command/{DevEUI}"
                          → UG56 (cola clase A) → nodo → responde en el siguiente uplink
```

### 3.1 Payload de entrada (broker → dashboard)

El gateway publica en `data/` un JSON con los campos en la **raíz** o en
`object` (formato ChirpStack/Milesight). Se acepta también el fallback con
`data` en base64 (payload LoRaWAN **crudo**), decodificado por `decoder.py`.

**Formatos de payload LoRaWAN (firmware v2.1, FPort 1):**

| Longitud | `kind` | Contenido | Cuándo |
|----------|--------|-----------|--------|
| **138 B** | `full` | 64 píxeles + termistor + batería + SF + intervalo + rssi_dBm | SF7 |
| **16 B** | `compact` | min/max/prom + termistor + batería + SF + intervalo + rssi_dBm | SF8/SF9 |
| **133 B** | `legacy` | 64 píxeles + termistor + batería (sin sf/intervalo/rssi) | v1 |

**Campos nuevos (v2.1):** `sf` (7/8/9), `interval_min` (ciclo en min),
`rssi_dBm` (señal que mide el **nodo** del último downlink del gateway;
`null` = centinela 0x8000, aún sin downlink), `rssi` (siempre presente, lo
mide el **gateway**), `snr`, `kind` (`full`/`compact`/`legacy`). El formato
compacto trae `pixels_C: null` (no hay mapa térmico, solo estadísticas).

Ejemplo real capturado (decodificado, completo):

```json
{
  "battery_V": 3.33,
  "battery_mV": 3330,
  "pixel_max_C": 28,
  "pixel_min_C": 21.75,
  "pixels_C": [25, 24.5, 24.5, 24.75, "... 64 valores ..."],
  "sensor_ok": true,
  "thermistor_C": 23.75,
  "version": 1
}
```

### 3.2 Frame normalizado (dashboard → WebSocket)

`_process_payload()` devuelve el diccionario `frame` que se envía al navegador:

| Campo | Tipo | Notas |
|-------|------|-------|
| `pixels_C` | `[float × 64] \| null` | Matriz 8×8, orden fila-principal (y·8+x). `null` en formato compacto. |
| `pixel_min_C` / `pixel_max_C` / `pixel_avg_C` | `float` | Mín/máx/promedio. |
| `thermistor_C` | `float \| None` | Termistor de la placa. |
| `battery_mV`, `battery_V` | `float \| None` | Tensión de batería. |
| `sensor_ok` | `bool` | Estado de lectura del sensor. |
| `sf` | `int \| None` | Spreading Factor actual (7/8/9). |
| `interval_min` | `int \| None` | Ciclo de reporte del nodo (minutos). |
| `rssi_dBm` | `int \| None` | RSSI que mide el **nodo** del gateway (0x8000 → `null`). |
| `rssi`, `snr` | `float \| None` | Señal/SNR que mide el **gateway** del uplink. |
| `kind` | `str` | `full` (SF7), `compact` (SF8/9) o `legacy` (v1). |
| `dev_eui` | `str \| None` | Normaliza `devEUI`/`devEui`/`deveui`/…; si no viene en payload, se intenta extraer del topic MQTT (`data/{EUI}`, `device/{EUI}/event/up`, …); como último recurso usa `DEFAULT_DEV_EUI` (env, por defecto el nodo real). **Clave de multi-nodo**. |
| `f_port` | `int \| None` | Puerto LoRaWAN. |
| `ts` | `float` | Epoch Unix (seg.) en el que llegó al dashboard (lo añade `broadcast_frame`). |

**Multi-nodo:** el servidor mantiene `LAST_FRAMES: dict[dev_eui → frame]`. Al
conectar, cada WebSocket recibe un mensaje bootstrap:

```json
{"type": "device_list", "devices": [{"dev_eui": "…", "nickname": "…", "last_frame": {…}}]}
```

Después, cada uplink llega como un frame plano (sin `type`) con su `dev_eui`;
el frontend los agrupa por nodo en el árbol de dispositivos (columna izquierda)
y dibuja solo el seleccionado (derecha). Los nombres opcionales viven en
`devices.json` (mapeo `DevEUI → nombre`).

### 3.3 Downlink (comandos gateway → nodo)

El navegador puede enviar comandos al nodo (clase A → el UG56 los encola y
entrega en la siguiente ventana RX tras un uplink):

- **Topic MQTT**: `command/{DevEUI}` (o `DOWNLINK_TOPIC` si está definido).
- **Payload**: JSON estilo ChirpStack con los bytes del comando en hex,
  p. ej. `{"confirmed": false, "fPort": 1, "data": "0300", "devEUI": "..."}`.
- **Comandos** (todos FPort 1, persisten en flash):

| Comando | Bytes | Acción |
|---------|-------|--------|
| `01 <sf>` | `01 07/08/09` | Cambiar SF (7..9) |
| `02 <hi> <lo>` | `02 00 05` | Cambiar ciclo de reporte (1..1440 min) |
| `03 00` | `03 00` | Consultar RSSI: el siguiente uplink responde `rssi_dBm` |

**Protocolo WebSocket:** el frontend envía
`{"type":"command","cmd":"rssi","dev_eui":"..."}` (o `"sf"`/`"interval"`
con `value`); el servidor responde
`{"type":"command_ack","cmd":"rssi","ok":bool}`. Con multi-nodo, el
`dev_eui` debe indicar el nodo destino (se toma del seleccionado en la UI).

---

## 4. Endpoints HTTP

| Ruta | Método | Descripción |
|------|--------|-------------|
| `/` | GET | Página `index.html`. |
| `/ws` | WebSocket | Bidireccional: envía cada `frame`; recibe comandos `{"type":"command",...}` y responde `command_ack`. |
| `/ingest` | POST | Ingesta HTTP alternativa al MQTT: recibe el JSON del UG56 y lo reenvía por WS (útil en PaaS/con hosting sin broker). Devuelve 202 si es frame térmico, 200 si no, 400 si JSON inválido. |
| `/fondo.jpg` | GET | Fotografía real (compat). |
| `/fondo2.jpg` | GET | Fotografía real con fondo negro (usada en el dashboard). |
| `/health` | GET | JSON `{"ok": true, "ws_clients": N}` (healthcheck). |

---

## 5. Componentes del proyecto

### 5.1 `dashboard.py` — proceso principal

Levanta y orquesta todo:

1. **Broker MQTT** (`Broker`/`BrokerConfig`/`ListenerConfig` de `amqtt`) en
   `0.0.0.0:1883`. Acepta conexiones anónimas **y** autenticadas.
   El gateway UG56 publica aquí con usuario/contraseña definidos en
   `config.json` si el broker exige autenticación.
2. **`mqtt_loop()`** — consumidor interno: `MQTTClient` se conecta al broker
   local, se suscribe a `MQTT_TOPICS = ["data/#", "#"]`, parsea cada mensaje
   con `_process_payload()` y empuja el `frame` a todos los WebSockets.
3. **`ws_handler()`** — al conectar, envía el último `LAST_FRAME` guardado
   (para que el navegador no arranque en blanco).
4. **Servidor web** `aiohttp` en `0.0.0.0:8080`.

Configuración de puertos por argumentos de línea de comandos:

```powershell
python dashboard.py            # web 8080, broker 1883
python dashboard.py 8081 1884  # web 8081, broker 1884
```

Notas de implementación:
- `amqtt 0.11.3` no acepta `listen=`; se usa `BrokerConfig()` con
  `cfg.listeners = {"default": ListenerConfig(type="tcp", bind=...)` en el
  **host**:`puerto` completo.
- Para los clientes, `amqtt` expone la API asíncrona:
  `connect()`, `subscribe([(topic, qos)])`,
  `deliver_message(timeout_duration=None)` y `publish()` con payload en
  `bytes`.
- El cliente PUBLICADOR externo (UG56) debe escribir el payload como `bytes`.

### 5.2 `index.html` — frontend (sin build tooling)

Todo el frontend es **un solo archivo HTML** con CSS y JS integrados.

**Layout fullscreen (CSS, sin build tooling):**

El contenedor raíz usa `html { height: 100% }` y `body { height: 100vh;
overflow: hidden; display: flex; flex-direction: column }` para que la UI
ocupe **el 100% del viewport** sin scroll. Los bloques interiores son fluidos:

- `body` → columna flex con `padding` reducido (12px 16px); el header y el
  footer llevan `flex-shrink: 0`.
- `.grid` (vista por defecto) y `.layout` (vista multi-nodo) → `flex: 1;
  min-height: 0` con `grid-template-columns` fluidos (`minmax(0,1fr) 640px` /
  `460px 1fr`), en lugar del antiguo `max-width` centrado con scroll.
- `#heatWrap` → `flex: 1; min-height: 0; display:flex; center` y el canvas del
  mapa escala con `width:auto; height:100%; max-width/max-height:100%` (antes
  `width:24%`).
- `.card` → `display:flex; flex-direction:column; min-height:0` para que las
  tarjetas estiren su contenido al alto disponible; `.card-spaced` ahora es
  `margin-top:0`.
- Responsive: `@media (max-width:900px)` y `@media (max-height:640px)`
  reactivan el scroll (`body { overflow: auto }`) y apilan columnas a 1fr para
  pantallas pequeñas/portrait sin cortar contenido.

**Tipografía (mejora estética para pantalla grande):**

Se subieron los tamaños de fuente en toda la UI para legibilidad en pantallas
grandes, y se ensancharon las columnas laterales:

- Títulos de tarjeta `.card h2`: 13 → **18 px**.
- Valores KPI `.stat .value`: 21 → **28 px** (`.small`: 13 → **17 px**).
- Min/max de matriz `.stat.temp .value`: 34 → **44 px** (`.small`: 17 → 22 px).
- Etiquetas `.stat .label`: 12 → **15 px**; en `.card-spaced`: **17 px**.
- Estado del sensor `#sensorStatus`: 14 → **20 px**; DevEUI `#devEui`: añade
  `font-size: 24px` (mantiene monoespaciado).
- Panel de dispositivos: `#devEui`/`.dev-name` 24 px, `.dev-eui`/`.dev-meta`
  18 px, `.dev-empty` 18 px, `.dev-dot` 9→**16 px**, padding de fila mayor.
- Cabecera `<h1>` renombrada de "Termocámara AMG8833 · LoRaWAN" a **"Device View"**.
- Columnas: `.grid` lateral 480→**640 px**, `.layout` lateral 280→**460 px**.

**Constantes clave:**

```js
const S = 8;                 // resolución de la matriz térmica
const BUF_W = 560;           // ancho del buffer de dibujo (nítido)
const BUF_H = 980;           // alto del buffer (proporción 9:16 = 768×1366)
const WARM = [ [...] ];      // paleta de color (ver sección 5.4)
```

**Vistas (`view`):**

| `view` | Comportamiento |
|--------|----------------|
| `optical` | Dibuja la fotografía real (`/fondo2.jpg`) a tamaño completo. Sin datos térmicos. |
| `thermal` | Rellena los píxeles 8×8 >= umbral con colores cálidos; los fríos quedan **transparentes** (sin color). |
| `combined` | Fotografía de fondo + capa térmica caliente encima (opacidad 0.85). |

**Umbral:** un slider `threshold` (0–100%) define `tCut = min + (threshold/100)*(max−min)`.
Solo los píxeles con `t >= tCut` se colorean. El slider se muestra en las
vistas `thermal` y `combined`.

**Paleta de color:** arreglo `WARM` de 6 colores
(amarillo → naranja → rojo brillante). `colorFor(t, tCut, max)` interpola
linealmente sobre el rango `[tCut, max]` y devuelve `null` (transparente)
para valores fríos.

**Flash de nueva data (glow):** el elemento `#glow` rodea el canvas. En
`ws.onmessage` se agrega la clase `flash`, que ejecuta la animación CSS
`glowPulse` (un halo menta que aparece y se desvanece en ~0.7s). Es la
indicación visual sutil de que llegó un uplink nuevo.

**Tarjetas de telemetría:** min/máx (números coloreados: **máx rojo**,
**mín azul**), termistor, batería y estado del sensor. La tarjeta
"Información" (DevEUI + última actualización) está separada de "Datos del
sensor" (`card-spaced`) por estética.

**Semáforo de señal (`sig-dot`):** las tres tarjetas de enlace LoRa
(`rssi_dBm`, `rssi`, `snr`) llevan un `<span class="sig-dot">` en la esquina
superior derecha (CSS `.sig-dot`, posicionado con `position: relative` en
`.stat`). En `render()` se llama a `setSignalDot(id, value, isSnr)` para cada
una. Lógica de color en `setSignalDot`:

| Valor | Umbral | Clase |
|-------|--------|-------|
| RSSI (dBm) | `>= -80` | `grn` (verde) |
| RSSI (dBm) | `-100 .. -80` | `yel` (amarillo) |
| RSSI (dBm) | `< -100` | `red` (rojo) |
| SNR (dB) | `>= 8` | `grn` |
| SNR (dB) | `0 .. 8` | `yel` |
| SNR (dB) | `< 0` | `red` |
| cualquier, si `null` | — | sin clase (gris por defecto) |

El punto usa `transition: background/box-shadow .3s` y un `box-shadow` con el
mismo color para un "glow" sutil. Si el valor es `null` (sin dato), el punto
queda gris estático (`#4a4a4a`).

### 5.3 `broker_consola.py` — broker MQTT de consola (herramienta)

Broker MQTT **independiente** + visor de tópicos para depurar sin abrir el
dashboard:

```powershell
python broker_consola.py       # broker en 1883
python broker_consola.py 1884  # broker en otro puerto
```

- Levanta el broker y, además, un cliente visor suscrito a `#` que imprime
  topic + payload en consola en tiempo real.
- Útil para verificar que el UG56 publica correctamente antes de arrancar el
  dashboard (evita colisiones de puerto: `dashboard.py` es el broker oficial).

### 5.4 `mqtt_client.py` — cliente MQTT (paho) para la app de escritorio

Puente MQTT con `paho-mqtt` en un hilo. **Nota:** esta es la pieza heredada de
la primera versión (app de escritorio `app.py`) — el dashboard web actual usa
`dashboard.py` con `amqtt`. Se mantiene en el repo como referencia/utilitaria
y para pruebas.

Maneja:
- Conexión/reconexión automática con backoff.
- Suscripción a múltiples tópicos (de `config.json`).
- Parseo en `MQTTBridge._parse_message`:
  1. `object.pixels_C` (ChirpStack) — prioridad 1.
  2. `pixels_C` a nivel raíz (Milesight UG56) — prioridad 2.
  3. `data` base64 (payload crudo) → `decoder.decode_uplink_data()` — fallback.
- Filtro por DevEUI (`device_eui_filter`).
- Entrega a la GUI via `queue.Queue` thread-safe.

### 5.5 `decoder.py` — decodificador del payload AMG8833

Decodifica el **payload LoRaWAN crudo** (base64) cuando el gateway no lo
decodifica. Soporta los tres formatos del firmware v2.1 según la longitud:
**138 B** (`full`, mapa 8×8 + `sf`/`interval_min`/`rssi_dBm`), **16 B**
(`compact`, solo min/max/prom + telemetría) y **133 B** (`legacy`, formato
v1). Recordar: `rssi_dBm` usa el centinela `0x8000` para "sin dato" → `null`.
Lanza `PayloadDecodeError` si el payload no calza. Resoluciones: termistor
0.0625 °C/LSB, píxeles 0.25 °C/LSB, ambos 12-bit signed LE.

### 5.6 `config.json` — configuración compartida

```json
{
  "broker": { "host": "127.0.0.1", "port": 1883,
              "username": "<usuario>", "password": "<password>", "...": "..." },
  "topics": ["data/#", "command/#", "application/+/device/+/event/up", "#"],
  "qos": 1,
  "device_eui_filter": "70b3d56f27cee98b",
  "default_frame_period_s": 60,
  "colormap": "turbo",
  "heatmap_size": 720,
  "window": { "title": "...", "width": 1200, "height": 820 }
}
```

Lo usan sobre todo `mqtt_client.py` (broker del *escritorio*) y el visor.
El `dashboard.py` conoce los tópicos vía `MQTT_TOPICS` en código.

### 5.6b `devices.json` — nombres de dispositivos (multi-nodo)

Mapeo opcional `DevEUI → nombre` que usa el dashboard para etiquetar cada nodo
en el árbol (columna izquierda). Se carga al arrancar y se propaga al frontend
vía `device_list`:

```json
{
  "70b3d56f27cee98b": "Termocámara 01",
  "70b3d56f27cee1234": "Termocámara 02"
}
```

Si el DevEUI no está listado, el frontend muestra el sufijo del DevEUI.

### 5.7 Scripts auxiliares

| Archivo | Función |
|---------|---------|
| `iniciar_dashboard.bat` | Arranca `dashboard.py` (web+b) y abre el navegador; comprueba el puerto 1883 libre y espera a `/health`. |
| `iniciar_app.bat` | Arranca la app de escritorio legada (`app.py`). |
| `convertir_fondo_png.py` | Convierte `fondo.jpg` → `fondo.png` transparente (flood-fill). El dashboard usa `fondo2.jpg` (fondo negro), que se ve mejor para superposición. |
| `instalar_ssh_admin.ps1` / `corregir_backup_admin.ps1` | Instalación del servidor OpenSSH y cuenta `backup` (acceso remoto del portátil de respaldo). |
| `simular_nodos.py` | **Demostración multi-nodo**: publica en MQTT uplinks sintéticos de 3 nodos ficticios con escenas térmicas distintas (Bodega SF9 compact, Motor SF7 full, Sala SF8 compact), cada ~4 s. `python simular_nodos.py 10` cambia el intervalo; `0` para un solo ciclo. Ver nombres en `devices.json`. |
| `listen_all.py` | Utilidad de prueba para escuchar tópicos MQTT. |

---

## 6. Cómo arrancar

### Opción A — GUI (recomendada para el usuario)

Doble clic en `iniciar_dashboard.bat`. Levanta broker en 1883 + web en 8080
y abre `http://127.0.0.1:8080/`.

### Opción B — Línea de comandos

```powershell
cd "C:\Users\Cliente Preferido\Documents\Default Project\thermal_monitor"
& "C:\Users\Cliente Preferido\AppData\Local\Programs\Python\Python312\python.exe" dashboard.py
```

Accede desde la red en `http://<IP_DEL_PC>:8080/` (IP del gateway/PC por
Ethernet o Wi-Fi).

### Opción C — Depurar el broker solo (sin web)

```powershell
& "C:\Users\Cliente Preferido\AppData\Local\Programs\Python\Python312\python.exe" broker_consola.py
```

---

## 7. Guía de desarrollo / mantenimiento

### 7.1 Agregar un campo nuevo a la telemetría

1. En **`dashboard.py`** → `_process_payload()`: añade el campo al dict
   devuelto (p. ej. `"battery_V": ...`).
2. En **`index.html`**: añade una tarjeta HTML con un `id`, y en
   `updateStats()` escribe `document.getElementById('id').innerHTML = ...`.

### 7.2 Cambiar la paleta de colores

Edita el arreglo `WARM` en `index.html`. Cada entrada es `[R, G, B]`. El
primer elemento = justo en el umbral (amarillo), el último = máximo (rojo).
`colorFor()` interpola linealmente. La barra `#scale` (CSS) debe coincidir
con la paleta (actualízala manualmente con los mismos `rgb(...)`).

### 7.3 Cambiar las vistas / umbral

- Vistas: botones `.views button[data-view]`. La lógica está en `render()`
  y `thermalLayer()`. El modo `'full'` y `'hot'` usan la misma regla ahora:
  solo colores cálidos para `t >= tCut`.
- Umbral: `threshold` (%) global + slider `#thRange`.

### 7.4 Modificar el tema CSS

El diseño usa variables CSS en `:root` (`--bg`, `--panel`, `--accent`, etc.).
Cámbialas ahí para un re-tema global.

### 7.5 Cambiar la fotografía de fondo

- Coloca el archivo en la carpeta (p. ej. `fondo2.jpg`).
- En `dashboard.py`, `fondo_handler` apunta la ruta; y en el frontend,
  `photoImg.src` en `index.html`.

### 7.6 Probando el flujo sin el nodo físico

El broker local recibe cualquier tópico (incluido `test/`). Para inyectar un
frame térmico manual, publica un JSON a `data/` con `pixels_C` (64 valores)
usando cualquier cliente MQTT. Ejemplo verificado con `amqtt` (PowerShell
pasa el script por stdin a Python):

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"; @"
import asyncio, json, random
from amqtt.client import MQTTClient

async def go():
    c = MQTTClient()
    await c.connect("mqtt://127.0.0.1:1883/")
    await c.publish("data/test", json.dumps({
        "pixels_C": [round(random.uniform(20, 40), 2) for _ in range(64)],
        "battery_mV": 3300,
        "battery_V": 3.3,
        "sensor_ok": True,
    }).encode())
    await c.disconnect()

asyncio.run(go())
"@ | & $py -
```

También puedes publicar a `data/` desde `mosquitto_pub` o supervisar con
`broker_consola.py`. El navegador lo mostrará al instante por WebSocket
(mín/máx y destello incluidos).

---

## 8. Seguridad y red

- El broker escucha en `0.0.0.0:1883` **sin TLS** y **sin autorización por
  defecto** (acepta anónimo) para simplificar el flujo con el UG56. Si el
  UG56 exige credenciales, se definen en `config.json` (ver §5.6).
- El dashboard web se sirve en HTTP plano (sin TLS). Para exponerlo fuera de
  la LAN, ponlo detrás de un proxy/TLS (p. ej. Caddy/nginx) o de un túnel VPN.
- **Acceso SSH:** se instaló OpenSSH Server en la PC y la cuenta `backup`
  (grupo Administradores) para que un segundo portátil haga el respaldo por
  `ssh`/`scp` y publique en GitHub. El servicio `sshd` está en `Automatic`.
  - IP: `<IP_Ethernet>` / `<IP_Wi-Fi>`, puerto 22.
  - Credenciales: `<usuario_ssh>` / `<password_ssh>` (cámbialas si no se usan).

---

## 9. Problemas conocidos y soluciones

| Síntoma | Causa probable | Solución |
|---------|----------------|----------|
| La vista térmica no muestra nada | El nodo no transmite (p. ej. cambio de firmware, batería) o el gateway no publica al broker (`<IP_DEL_PC>:1883`). | Verifica `broker_consola.py` para ver si llegan uplinks; comprueba el nodo (batería 3.3 V ya es baja) y la integración MQTT del UG56. |
| No se ve el "destello" al llegar data | No llegan frames, o el navegador no refrescó. | Espera el siguiente ciclo (~1 min) o recarga con Ctrl+Shift+R. |
| El RSSI/SNR no aparece | El JSON del gateway no incluye `rssi`/`snr` o vienen como `null`. | Con el firmware v2.1 los envía el nodo en el payload; si el gateway ya pone `decoded.rssi = LoRaObject.rxInfo[0].rssi` se completan. |
| `rssi_dBm` queda en `null` | El nodo aún no recibió ningún downlink desde su arranque (centinela 0x8000). | Envía el comando `03 00` desde el botón "Consultar RSSI"; el siguiente uplink ya trae valor. |
| El comando `03 00` no llega al nodo | Topic o formato de downlink distinto en el UG56. | Verifica en `Integrations → MQTT` del UG56 el "command topic"; si es topic fijo, define `DOWNLINK_TOPIC`. |
| El formato compacto no muestra el mapa | El nodo está en SF8/SF9 (paquete de 16 B, sin píxeles). | Espera a SF7 para mapa completo, o bájalo con el comando `01 07` (no expuesto aún en la UI). |
| `ChildProcess.kill` al lanzar con `Start-Process` + redirección | Limitación del wrapper de shell en Windows. | El proceso igualmente queda corriendo; verifícalo con `Get-NetTCPConnection -LocalPort 8080,1883`. |
| DoS/ruido en el broker | `MQTT_TOPICS` incluye `"#"`. | Afinar a solo `["data/#", "command/#"]` en producción. |

---

## 10. Stack tecnológico

- **Python 3.12** · `asyncio`
- **amqtt 0.11.3** — broker/ cliente MQTT (pure Python)
- **aiohttp 3.14.3** — servidor web + WebSocket
- **HTML5 / CSS3 / Vanilla JS** — frontend sin frameworks
- **Canvas API** — renderizado del heatmap 8×8
- (Legado de la app de escritorio: `paho-mqtt`, `numpy`, `Pillow`)
- **Milesight UG56** — gateway LoRaWAN con Network Server embebido
- **Linked panel** del nodo: CubeCell (HTCC-AB02) + sensor AMG8833