# Termocámara LoRaWAN AMG8833 — Monitor de escritorio / Dashboard web

Aplicación para visualizar **en tiempo real** los datos del nodo LoRaWAN
**HTCC-AB02A + AMG8833** (matriz infrarroja 8×8), recibidos a través de
**MQTT** desde un gateway **Milesight UG56**.

> Este directorio (`thermal_monitor/`) es la **parte cliente/servidor** del
> proyecto. El firmware del nodo (`.ino`, `decoder.js`, `credentials.h`, etc.)
> vive en la raíz del repositorio, un nivel por encima.

---

## 1. Qué es este componente

El nodo envía por LoRaWAN la imagen térmica (64 píxeles) al gateway UG56, que la
publica en un **broker MQTT**. Este componente se suscribe a esos tópicos y la
representa gráficamente de dos formas posibles:

| Componente | Tipo | Descripción |
|---|---|---|
| `app.py` | **GUI de escritorio** (Tkinter) | Ventana con heatmap, KPIs e historial. Requiere un broker MQTT externo (p. ej. Mosquitto) o el propio `dashboard.py`. |
| `dashboard.py` | **Servidor web** (aiohttp) + **broker MQTT embebido** (amqtt) | Levanta un broker en `0.0.0.0:1883` y sirve la web en `0.0.0.0:8080`. Es la solución "todo en uno". |

### Arquitectura del flujo de datos

```
[CubeCell HTCC-AB02A]
        │  LoRaWAN (AU915 SB2, SF7/8/9)
        ▼
[Milesight UG56]  (NS embebido)
        │  MQTT publish  (topic application/.../event/up)
        ▼
[Broker MQTT]  ←  dashboard.py (broker amqtt embebido)  o  Mosquitto externo
        │
        ├──► [dashboard.py (web, puerto 8080)]  → navegador
        └──► [app.py (GUI Tkinter)]             → ventana escritorio
```

---

## 2. Modos de operación

### 2.1 Modo web "todo en uno" (recomendado)

`dashboard.py` levanta **a la vez** un broker MQTT y un servidor web, sin
dependencias externas:

```bash
pip install -r requirements.txt      # una sola vez

python dashboard.py                  # web en :8080, broker MQTT en :1883
python dashboard.py 8081 1884        # puertos personalizados
```

- **Broker MQTT** en `0.0.0.0:1883`: aquí publica el gateway UG56.
- **Web** en `http://<ip>:8080`: heatmap 8×8, KPIs y actualización en vivo por
  **WebSocket** (`/ws`).
- Acepta además ingesta por **HTTP** en `POST /ingest`.
- Permite enviar **comandos downlink** (p. ej. consulta RSSI `03 00`) desde la
  web, publicándolos en `command/{DevEUI}`.

> En un entorno PaaS (Render/Railway), el puerto web se toma de la variable de
> entorno `PORT` si no se pasa por argumento.

### 2.2 Modo escritorio (GUI Tkinter)

```bash
python app.py
```

Requiere un broker MQTT corriendo (puede ser el de `dashboard.py` o un
Mosquitto externo). Configura la conexión en `config.json`.

---

## 3. Requisitos e instalación

- **Python 3.9+**
- Dependencias (`requirements.txt`):

| Paquete | Uso |
|---|---|
| `paho-mqtt>=1.6` | cliente MQTT (GUI y diagnóstico) |
| `numpy>=1.24` | interpolación del heatmap |
| `Pillow>=9.0` | render de imagen ↔ Tkinter |

```bash
pip install -r requirements.txt
```

---

## 4. Configuración (`config.json`)

> **Credenciales**: `config.json` puede contener usuario/contraseña del broker.
> **NO se versiona** (está en `.gitignore`). Usa la plantilla
> **`config.example.json`** como base y renómbrala a `config.json` con tus datos.

```json
{
  "broker": {
    "host": "127.0.0.1",
    "port": 1883,
    "username": "TU_USUARIO",
    "password": "TU_PASSWORD",
    "keepalive": 60,
    "reconnect_delay_min": 2,
    "reconnect_delay_max": 30
  },
  "topics": [
    "data/#",
    "command/#",
    "application/+/device/+/event/up",
    "#"
  ],
  "qos": 1,
  "device_eui_filter": "70b3d56f27cee98b",
  "default_frame_period_s": 60,
  "colormap": "turbo",
  "heatmap_size": 720,
  "window": { "title": "Termocámara LoRaWAN AMG8833", "width": 1200, "height": 820 }
}
```

Campos principales:

| Campo | Descripción |
|---|---|
| `broker.host/port` | Dirección del broker MQTT (Mosquitto o el de `dashboard.py`). |
| `broker.username/password` | Credenciales del broker (déjalas vacías si no hay autenticación). |
| `topics` | Tópicos suscritos. Incluye `application/+/device/+/event/up` (formato Milesight/ChirpStack) y `data/#` (formato propio). |
| `device_eui_filter` | DevEUI (minúsculas) para mostrar un solo nodo; `""` para mostrar todos. |
| `colormap` | Paleta del heatmap (`turbo`, `jet`, `inferno`…). |
| `heatmap_size` | Tamaño (px) de la imagen térmica interpolada. |

---

## 5. Funcionalidades

- **Diseño fullscreen**: la interfaz ocupa **el 100% de la ventana** (alto
  `100vh`, sin scroll) con un layout fluido en base a flexbox/grid que adapta
  automáticamente el mapa térmico y las tarjetas al espacio disponible. El mapa
  escala dentro de su contenedor (`max-width/max-height: 100%`), las tarjetas y
  la sidebar ocupan el alto completo, y el footer queda fijado al pie. En
  pantallas altas-bajas (móvil/portrait) o ventanas por debajo de 640 px de alto
  se activa el scroll para no cortar contenido.
- **Tipografía optimizada para pantalla grande**: títulos de tarjeta (18 px),
  valores KPI (28 px, y hasta 44 px en min/max de matriz), etiquetas (15 px),
  estado del sensor (20 px), DevEUI (24 px, fuente monoespaciada) y cabecera
  renombrada a **"Device View"**. La columna lateral se ensancha (480→640 px en
  la vista por defecto; 280→460 px en multi-nodo) para aprovechar pantallas
  grandes sin desperdiciar espacio.
- **Mapa térmico interpolado** (8×8 → imagen suave de alta resolución) con
  **colorbar** en °C.
- **Tarjetas KPI**: temp mín, temp máx, termistor, batería (V y %), RSSI y SNR.
- **Semáforo de señal**: cada tarjeta de señal LoRa (RSSI del nodo, RSSI del
  gateway y SNR) lleva un mini punto de color en su esquina superior derecha que
  resume de un vistazo la calidad del enlace:
  - 🟢 **Verde** = señal buena · 🟡 **Amarillo** = media · 🔴 **Rojo** = débil ·
    ⚪ **Gris** = sin dato.
  - Umbrales: **RSSI** (dBm) ≥ −80 verde, −100..−80 amarillo, < −100 rojo;
    **SNR** (dB) ≥ 8 verde, 0..8 amarillo, < 0 rojo.
- **Telemetría v2.1**: muestra `sf`, `interval_min` y `rssi_dBm` que el nodo
  envía en cada reporte.
- **Estado del sensor** (OK / FALLO), última actualización, contador de frames y
  método de decodificación (gateway o local).
- **Historial** de temperatura máx/mín a lo largo del tiempo.
- **Escala automática/fija** del mapa térmico.
- **Reconexión automática** al broker y manejo robusto de mensajes inválidos.
- **Comandos downlink** desde la web (`command/{DevEUI}`) — p. ej. consulta RSSI.

---

## 6. Estructura de archivos

```
thermal_monitor/
├── app.py                 # GUI de escritorio (Tkinter) — bucle principal
├── dashboard.py           # Servidor web (aiohttp) + broker MQTT embebido (amqtt)
├── mqtt_client.py         # Conexión MQTT (paho) y parseo del JSON
├── decoder.py             # Decodificación del payload crudo (fallback local)
├── thermal_render.py      # Matriz 8×8 → imagen térmica coloreada
├── broker_consola.py      # Broker MQTT de consola (amqtt) + visor de tópicos
├── listen_all.py          # Diagnóstico: escucha '#' y muestra todo
├── simular_nodos.py       # Generador de uplinks sintéticos (pruebas multi-nodo)
├── convertir_fondo_png.py # Utilidad: convierte fondo a formato compatible
├── config.json            # Config real (NO versionado — credenciales)
├── config.example.json    # Plantilla de configuración (SIN secretos)
├── requirements.txt       # Dependencias Python
├── devices.json           # Mapa DevEUI → nombre legible de nodo
├── index.html             # Interfaz web del dashboard
├── fondo.jpg / fondo2.jpg / fondo.png  # Fondos del dashboard (assets)
├── iniciar_app.bat        # Lanzador Windows: la GUI
├── iniciar_dashboard.bat  # Lanzador Windows: el dashboard web
├── DEVELOPER.md           # Documentación de desarrollador
└── README.md              # Este documento
```

---

## 7. Puesta en marcha rápida (Windows / Linux)

```bash
# 1. Crea el entorno e instala dependencias
python -m venv .venv && source .venv/bin/activate    # Linux
# python -m venv .venv && .venv\Scripts\activate      # Windows
pip install -r requirements.txt

# 2. Configura las credenciales
cp config.example.json config.json      # y edita config.json

# 3. Arranca (elige un modo)
python dashboard.py      # web + broker (recomendado), o
python app.py            # GUI escritorio
```

En Windows también hay lanzadores listos: `iniciar_dashboard.bat` y
`iniciar_app.bat`.

---

## 8. Integración con el nodo LoRaWAN

1. El nodo (`HTCC_AB02A_AMG8833_Thermal_v2.ino`) envía el payload por el puerto 1:
   - **SF7 → 138 B** (mapa completo de 64 píxeles + telemetría).
   - **SF8/9 → 16 B** (min/max/prom + telemetría).
2. El gateway UG56 publica el uplink al broker MQTT en el tópico
   `application/{AppEUI}/device/{DevEUI}/event/up` (formato Milesight/ChirpStack).
3. El `decoder.js` del NS decodifica el payload; además, este componente incluye
   un **`decoder.py` local** como fallback si el payload llega crudo.
4. El dashboard interpreta los campos (`kind`, `sf`, `interval_min`, `rssi_dBm`,
   `pixels_C`, batería…) y los dibuja.

> Para el formato byte a byte del payload y de los comandos downlink, consulta
> el `README.md` raíz y `decoder_completo.txt` del proyecto.

---

## 9. Diagnóstico y solución de problemas

| Síntoma | Causa probable | Solución |
|---|---|---|
| No llegan datos | Broker caído o gateway sin MQTT configurado | Verifica en UG56: **Network Server → Application → Data Transmission → MQTT**; arranca `dashboard.py` o Mosquitto. |
| Datos llegan pero no se ven | Tópico/filtro incorrecto | Revisa `topics` y `device_eui_filter` en `config.json`. |
| Heatmap en blanco | Payload no decodificado | Comprueba que el NS tiene el `decoder.js`; usa `listen_all.py` para inspeccionar tópicos crudos. |
| Campo `rssi_dBm` en `null` | Nodo aún sin downlink previo | Es normal; envía un comando (`03 00`) y el siguiente uplink lo reportará. |

- **`listen_all.py`** escucha el tópico `#` y vuelca todo: ideal para ver el
  formato exacto de tópicos y payload que publica el UG56.
- **`simular_nodos.py`** genera uplinks sintéticos para probar el dashboard
  sin nodos físicos.

---

## 10. Advertencias

- **No versiones `config.json`** si contiene credenciales reales. Está en
  `.gitignore`; publica solo `config.example.json`.
- Los scripts `.ps1` (`instalar_ssh_admin.ps1`, `corregir_backup_admin.ps1`)
  son utilidades específicas de la máquina de despliegue para configurar acceso
  SSH; no forman parte del funcionamiento del dashboard.
- El `dashboard.py` usa el **broker embebido amqtt** en `0.0.0.0:1883`; si ya
  tienes otra cosa en ese puerto, pasa un puerto alternativo por argumento.
