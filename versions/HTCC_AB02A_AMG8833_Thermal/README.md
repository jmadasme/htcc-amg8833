# Nodo LoRaWAN de Bajo Consumo + Termocámara AMG8833

> **Heltec CubeCell HTCC-AB02A · AMG8833 (8×8) · AU915 sub-banda 2 · Clase A · RadioLib 7.7.1**

Firmware y documentación de un **nodo LoRaWAN Clase A de ultra bajo consumo** que captura una
**imagen térmica de 64 píxeles (matriz infrarroja 8×8)** mediante una termocámara **AMG8833
(Panasonic)**, la desenergiza por completo entre mediciones y la transmite al **gateway Milesight
UG56** (con *Network Server* embebido) cada 60 segundos.

| | |
|---|---|
| **Placa** | Heltec CubeCell HTCC-AB02A ("CubeCell 1/2AA Node") |
| **MCU + Radio** | ASR6502 (ARM Cortex-M0+ @ 48 MHz) con SX1262 integrada (SiP) |
| **RAM / Flash** | 16 KB / 128 KB |
| **Sensor** | Termocámara AMG8833 (Panasonic) — matriz IR 8×8 = 64 píxeles, I2C `0x69` |
| **Red** | LoRaWAN AU915 sub-banda 2, OTAA, Clase A |
| **Stack** | RadioLib 7.7.1 |
| **Gateway** | Milesight UG56 (Network Server embebido) |
| **Payload** | fPort 1, 133 bytes (termistor + 64 píxeles crudos + batería) |
| **Intervalo** | 60 s (60000 ms) |
| **Consumo en reposo** | ~3.5 µA (deep sleep) + sensor a **0 µA** (VEXT OFF) |

---

## Índice

1. [Qué es y para qué sirve](#qué-es-y-para-qué-sirve)
2. [Especificaciones de la placa](#especificaciones-de-la-placa)
3. [Principio de funcionamiento](#principio-de-funcionamiento)
4. [Forma de operar](#forma-de-operar)
5. [Tabla de pines (pinout)](#tabla-de-pines-pinout)
6. [Diagrama de conexión](#diagrama-de-conexión)
7. [Configuración LoRaWAN](#configuración-lorawan)
8. [Formato de payload](#formato-de-payload)
9. [Payload decoder (`decoder.js`)](#payload-decoder-decoderjs)
10. [Ejemplos de uso](#ejemplos-de-uso)
11. [Compilación y carga](#compilación-y-carga)
12. [Visor térmico opcional (Python)](#visor-térmico-opcional-python)
13. [Advertencias y precauciones](#advertencias-y-precauciones)

---

## Qué es y para qué sirve

Este proyecto convierte la tarjeta **Heltec CubeCell HTCC-AB02A** en un **sensor térmico remoto
autónomo alimentado por pila**:

- Cada 60 segundos **despierta**, enciende la termocámara, lee los **64 píxeles** de temperatura
  más el **termistor** interno del AMG8833, apaga el sensor y transmite todo por LoRaWAN.
- En el *Network Server* (Milesight UG56), el `decoder.js` convierte los valores crudos a **°C**,
  calcula el **% de batería** (curva de pila Li-SOCl₂) y añade **RSSI/SNR** de la señal.
- Un **visor térmico opcional en Python** (`thermal_viewer.py`) se suscribe por MQTT a los
  *uplinks* y renderiza cada lectura como una **imagen de calor 8×8 interpolada**.

Aplicaciones típicas: monitorización de temperatura superficial a distancia, detección de puntos
calientes (motores, cuadros eléctricos), presencia humana, control de procesos, etc., con **años de
autonomía** gracias al bajo consumo.

---

## Especificaciones de la placa

| Característica | Valor |
|---|---|
| Placa | Heltec CubeCell HTCC-AB02A ("CubeCell 1/2AA Node") |
| MCU | ASR6502 — ARM Cortex-M0+ @ 48 MHz |
| Radio LoRa | SX1262 integrada en el SiP (LoRa + FSK) |
| RAM | 16 KB |
| Flash | 128 KB |
| Voltaje | 3.3 V (USB o pila) |
| USB | Micro-USB (CP2102) para programación y monitor serie |
| Antena | SMA (antena externa) |
| Deep sleep | ~3.5 µA |
| OLED | **No** (a diferencia de AB01/AB02) |
| FQBN (Arduino) | `CubeCell:CubeCell:CubeCell_AB02A` |

### Batería

- **Tipo**: pila de litio **Li-SOCl₂ no recargable** `ER14250` (1/2AA, 3.6 V nominal, 1200 mAh).
- La placa **conmuta automáticamente** entre USB y batería.
- ⚠️ **La placa NO carga la pila**: nunca conectes un cargador ni una pila recargable a los pads de
  batería. Usar una pila recargable o aplicar tensión de carga puede dañarla o causar fugas/explosión.

---

## Principio de funcionamiento

El nodo opera en un **ciclo periódico de 60 segundos** gobernado por un temporizador RTC en deep
sleep real:

```
[ deep sleep 60 s ]  (MCU CySysPmDeepSleep + radio en sleep + sensor apagado = ~3.5 µA)
        │  TimerEvent_t (RTC) expira
        ▼
radio.standby()
VEXT = HIGH  ───►  enciende el AMG8833 (polaridad invertida en esta placa)
        │  espera de estabilización (~200–300 ms, primer frame @10 fps)
        ▼
Wire.begin(SDA, SCL, 100 kHz)
inicializa AMG8833 (PCTL=0x00, RESET=0x3F, FPSC=10 fps)
        ▼
lee termistor (0x0E, 2 B) + 64 píxeles (0x80–0xFF, 128 B)  por I2C
        ▼
VEXT = LOW  ────►  apaga el AMG8833 (0 µA en el sensor)
        ▼
construye payload de 133 B + lee batería (getBatteryVoltage)
        ▼
envía uplink (fPort 1, no confirmado) — sendReceive con captura de downlink
        ▼
radio.sleep()  ─►  [ deep sleep 60 s ]
```

### Eficiencia energética (objetivo central)

| Componente | Estrategia |
|---|---|
| **MCU** | Deep sleep real vía `TimerEvent_t` (RTC) + `lowPowerHandler()` (CySysPmDeepSleep) |
| **Radio SX1262** | `radio.sleep()` durante el reposo; `radio.standby()` al despertar |
| **Sensor AMG8833** | Desenergizado por completo entre mediciones mediante el pad **VEXT** → **0 µA** |
| **I2C** | Pines en alta impedancia durante el deep sleep (sin consumo) |

> **Sobre el join / data rate**: el nodo usa **ADR OFF** y fija **DR5 (SF7/125 kHz)** tras el join.
> Esto permite transmitir el payload de 133 bytes en un único uplink (máx. ~238 B en AU915 DR5).
> Tras el *join*, el firmware envía un **uplink sonda** para que el *Network Server* confirme la DR
> mediante un `LinkADRReq/Ans` (viaja en los FOpts) antes de enviar el payload grande.

---

## Forma de operar

1. **Cargar credenciales** (ver [Configuración LoRaWAN](#configuración-lorawan)) y **compilar/cargar**
   el firmware (ver [Compilación y carga](#compilación-y-carga)).
2. **Encender**: conectar la pila ER14250 (respetando polaridad) **o** el cable USB. La placa
   conmuta automáticamente.
3. **Join**: al arrancar, el nodo muestra el banner `[INIT]`, ejecuta el **join OTAA** y espera
   `[JOIN] +++ JOINED +++`.
4. **Ciclos de reporte**: cada 60 s el nodo mide y envía. Por el monitor serie (115200 baudios) se
   observa `[AMG]`, `[BATT]`, `[UPLINK]` y `[SLEEP]`.
5. **Verificación en el gateway**: en el Milesight UG56, en *Network Server → Incoming Packets*,
   deben aparecer **uplinks de 133 bytes** en el puerto 1 con el DevEUI configurado.
6. **Decodificación**: aplicar `decoder.js` (Payload Codec) para ver `thermistor_C`, `pixels_C`,
   `battery_percent`, `rssi` y `snr`.
7. **Visualización opcional**: lanzar `thermal_viewer.py` para ver la imagen térmica en vivo por MQTT.

---

## Tabla de pines (pinout)

### Pines de la CubeCell usados por este proyecto

| Función | Pad CubeCell | GPIO (ASR650x) | Pin físico | Uso |
|---|---|---|---|---|
| **Alimentación conmutada del sensor** | `VEXT` | `P3_2` | — | Salida 3.3 V conmutada por GPIO → `VIN` del AMG8833 |
| **GND** | `GND` | — | — | Referencia común → `GND` del AMG8833 |
| **I2C SCL** | `SCL0` | `P0_0` | 39 | Reloj I2C → `SCL` del AMG8833 |
| **I2C SDA** | `SDA0` | `P0_1` | 40 | Datos I2C → `SDA` del AMG8833 |
| Batería (interno) | `P3_3` | `VBAT_ADC_CTL` | — | Usado internamente por `getBatteryVoltage()` |
| Serial USB | `P3_0`/`P3_1` | — | — | Monitor serie (CP2102) |

### Cableado AMG8833 ↔ CubeCell

| AMG8833 | CubeCell | Nota |
|---|---|---|
| `VIN` | `VEXT` (`P3_2`) | Alimentación conmutada. **Polaridad invertida: HIGH = ON / LOW = OFF** |
| `GND` | `GND` | Referencia común |
| `SCL` | `SCL0` (`P0_0`, pin 39) | I2C reloj |
| `SDA` | `SDA0` (`P0_1`, pin 40) | I2C datos |

### Pines SX1262 (internos del SiP, no reasignables)

| Señal SX1262 | GPIO |
|---|---|
| `NSS` | `P4_3` = 35 |
| `DIO1` | `P4_6` = 38 |
| `RST` | `P5_7` = 47 |
| `BUSY` | `P4_7` = 39 |

> La macro `Module mod(35, 38, 47, 39)` en el `.ino` mapea `NSS, DIO1, RST, BUSY`.

### Pinout oficial HTCC-AB02A (referencia)

- `VDD` = 3.3 V siempre encendido · `VIN` = 5 V · `GND`
- **`VEXT`** = 3.3 V conmutada por GPIO (documentada oficialmente como LOW-ON/HIGH-OFF; **en esta
  placa se verificó invertida: HIGH-ON/LOW-OFF**). Control = `P3_2` (macro Arduino `Vext`).
- I2C0: `SCL0` = `P0_0` (pin 39), `SDA0` = `P0_1` (pin 40) — libre (no hay OLED).
- I2C1: `SCL1` = `GPIO8`/`P7_0` (pin 36), `SDA1` = `GPIO9`/`P7_1` (pin 37).
- GPIO libres: `GPIO3`/`P6_2` (PWM1), `GPIO4`/`P6_4` (PWM2), `GPIO11`/`P0_2`, `GPIO12`/`P0_3`,
  `GPIO14`/`P0_7`.
- `P3_3` = `VBAT_ADC_CTL`/`USER_KEY` (usado por `getBatteryVoltage()`).
- UART USB: `P3_0`/`P3_1` (reservado para monitor serie).

---

## Diagrama de conexión

```
        Heltec CubeCell HTCC-AB02A                 Termocámara AMG8833
       ┌───────────────────────────┐              ┌────────────────────┐
       │                           │              │                    │
       │  VEXT  (P3_2)  ───────────┼──────────────┼──▶  VIN            │
       │                           │              │                    │
       │  GND            ──────────┼──────────────┼──▶  GND            │
       │                           │              │                    │
       │  SCL0 (P0_0, p39)─────────┼──────────────┼──▶  SCL            │
       │                           │              │                    │
       │  SDA0 (P0_1, p40)─────────┼──────────────┼──▶  SDA            │
       │                           │              │                    │
       │  (SX1262 interna SiP)     │              │  (matriz IR 8×8)   │
       └───────────────────────────┘              └────────────────────┘
              ▲ USB / pila ER14250
              │ (conmutación automática, NO carga la pila)

   Notas:
   • VEXT alimenta el sensor solo durante la medición (HIGH=ON / LOW=OFF).
   • El AMG8833 trae pull-ups onboard en SDA/SCL → no se añaden resistencias externas.
   • Dirección I2C: 0x69 por defecto (0x68 si se suelda el puente "Addr" del módulo).
```

---

## Configuración LoRaWAN

### Parámetros de red

| Parámetro | Valor |
|---|---|
| Región | **AU915, sub-banda 2** |
| Activación | **OTAA** (Clase A) |
| DevEUI | `70B3D56F27CEE98B` |
| JoinEUI / AppEUI | `24E124C0002ADD01` |
| AppKey / NwkKey | ⚠️ **secreto** — definido en `credentials.h` (no versionado) |
| Stack | RadioLib 7.7.1 |
| Puerto | 1 |
| Confirmación | Unconfirmed (no confirmado) |
| ADR | **OFF** |
| Data rate | **DR5 (SF7/125 kHz)** fijado tras el join |
| Intervalo | 60000 ms (60 s) |

> **Endianidad**: RadioLib espera las credenciales en **big-endian** (orden *over-the-air*):
> `uint64_t` para DevEUI/JoinEUI y arrays de 16 bytes para AppKey/NwkKey. No invertir el orden como
> en el stack nativo de CubeCell.

### 1. Credenciales OTAA

1. Copia la plantilla pública:
   ```bash
   cp credentials.example.h credentials.h
   ```
2. Rellena en `credentials.h`:
   - `joinEui` y `devEui` (big-endian, como `uint64_t`).
   - `appKey` y `nwkKey` (big-endian, 16 bytes cada uno).

> El archivo `credentials.h` **no se sube al repositorio** (está en `.gitignore`). La plantilla
> `credentials.example.h` solo contiene placeholders a cero.

### 2. Registro del dispositivo en el Network Server (Milesight UG56)

El Milesight UG56 incorpora un *Network Server* embebido. Pasos:

1. Accede a la interfaz web del UG56 y entra en **Network Server**.
2. Crea (o reutiliza) la **Application** donde se agrupará el nodo.
3. **Añade el dispositivo** con activación **OTAA**:
   - `DevEUI`: `70B3D56F27CEE98B`
   - `AppEUI`/`JoinEUI`: `24E124C0002ADD01`
   - `AppKey`: la de `credentials.h` (mismo valor para AppKey y NwkKey, salvo que uses claves Nwk/App
     separadas).
   - Clase A, región AU915, sub-banda 2.
4. Ajusta el **payload codec** (ver siguiente punto).
5. Verifica que el **gateway** (UG56) tenga habilitada la **sub-banda 2** de AU915 en su
   configuración de radio y el **canal de join** correspondiente.

> ⚠️ **Re-join al recrear el dispositivo**: si borras y vuelves a crear el dispositivo en el NS, el
> nodo **no podrá reutilizar la sesión anterior** y deberá re-negociar. Asegúrate de que las
> credenciales en `credentials.h` coincidan exactamente con las registradas, o el join fallará.

### 3. Aplicar el `decoder.js` (Payload Codec)

1. Abre el contenido de [`decoder.js`](decoder.js).
2. En el UG56: **Network Server → Application → (tu app) → Payload Codec** (o "Payload Decoder").
3. Pega el contenido de `decoder.js` en el campo correspondiente.
4. Guarda. A partir de ahora, cada uplink del puerto 1 se decodificará a JSON con `thermistor_C`,
   `pixels_C`, `battery_mV`, `battery_percent`, `rssi` y `snr`.

> El `decoder.js` está escrito en **JavaScript ES5** (sin `let`/`const`, sin *arrow functions*), con
> `Decode(fPort, bytes)` que retorna el objeto JSON **directo** (formato Milesight/ChirpStack v3) y
> `Encode(fPort, obj)` que retorna `[]` (v1.0 sin comandos downlink).

### 4. Configurar el gateway

- Región: **AU915**, **sub-banda 2** habilitada.
- El join y los uplinks del nodo ocurren en los canales de la sub-banda 2 (CH 8–15, 917.2–917.8 MHz).
- Ajusta la potencia y la antena del gateway según la distancia al nodo.

---

## Formato de payload

**Uplink en fPort 1, longitud fija de 133 bytes.**

| Byte(s) | Campo | Descripción | Endianidad |
|---|---|---|---|
| `0` | `version` | `0x01` = lectura OK · `0x81` = fallo de lectura I2C | — |
| `1–2` | `thermistor` | Termistor crudo (registro 0x0E), 12-bit con signo | little-endian |
| `3–130` | `pixels[64]` | 64 píxeles crudos (registros 0x80–0xFF), 12-bit con signo | little-endian |
| `131–132` | `battery_mV` | Voltaje de batería `uint16` | **big-endian** |

### Conversión a °C (¡DOS resoluciones distintas!)

La resolución **NO es la misma** para todos los registros del AMG8833:

| Registro | Resolución | Fórmula |
|---|---|---|
| **Termistor** (`0x0E`) | 0.0625 °C/LSB | `temp_C = valor12bit * 0.0625` |
| **Píxeles** (`0x80–0xFF`) | 0.25 °C/LSB | `temp_C = valor12bit * 0.25` |

**Función de signo (complemento a 2, 12 bits):**

```
s = v & 0x0FFF
if s & 0x0800:  s = s - 0x1000
```

Ejemplo: termistor crudo `0x0196` = 406 → `406 × 0.0625 = 25.375 ≈ 25.38 °C`.

### Comandos de downlink

En **v1.0 no existen comandos de downlink**: el nodo captura la ventana de recepción Clase A y
solo **loguea** los bytes recibidos (`[RX]`). El `Encode()` del decoder devuelve `[]`. Si se
requiere control remoto en el futuro, se añadirá una *whitelist* de comandos en `handleDownlink()`.

---

## Payload decoder (`decoder.js`)

El [`decoder.js`](decoder.js) entrega, por cada uplink del puerto 1, un objeto JSON con:

| Campo | Tipo | Descripción |
|---|---|---|
| `version` | int | `0x01` o `0x81` |
| `sensor_ok` | bool | `true` si `version === 0x01` |
| `thermistor_raw` | string | Hex del termistor crudo (2 bytes) |
| `thermistor_C` | float | Termistor en °C (`× 0.0625`) |
| `pixels_raw` | string | Hex de los 128 bytes de píxeles |
| `pixels_C` | array[64] | 64 temperaturas en °C (`× 0.25`) |
| `pixel_min_C` / `pixel_max_C` | float | Mínimo y máximo de `pixels_C` |
| `battery_mV` | int | Voltaje en mV |
| `battery_V` | float | Voltaje en V |
| `battery_percent` | int | % estimado según curva Li-SOCl₂ |
| `rssi` | float | RSSI en dBm (metadato del gateway) |
| `snr` | float | SNR en dB (metadato del gateway) |

### Curva de batería (Li-SOCl₂)

La pila Li-SOCl₂ tiene una descarga **muy plana**: se mantiene ≈3.6 V casi toda su vida y cae en
picado al final. La curva orientativa usada en `batteryPercent(mV)`:

| Voltaje (mV) | ≥3650 | ≥3600 | ≥3550 | ≥3500 | ≥3450 | ≥3400 | ≥3350 | ≥3300 | ≥3200 | ≥3100 | ≥3000 | <3000 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| % | 100 | 95 | 85 | 75 | 65 | 50 | 40 | 30 | 20 | 10 | 5 | 0 |

---

## Ejemplos de uso

### 1. Salida esperada del monitor serie (115200 baudios)

```
[INIT] HTCC-AB02A + AMG8833 nodo v1.0 (RadioLib) — AU915 SB2
[INIT] DevEUI=70B3D56F27CEE98B JoinEUI=24E124C0002ADD01
[INIT] Radio OK
[INIT] Node OK
[INIT] scanGuard=200 ms
[JOIN] Iniciando OTAA (AU915 SB2)...
[JOIN] +++ JOINED +++
[DR] setDatarate(5)=0 maxPayload=238 B
[INIT] Ciclo de 60000 ms (60 s). Listo.
[PROBE] uplink sonda port=1 payload=020E10000000 (6 B)
[DR] tras sonda maxPayload=238 B
[DR] DR4 confirmada, payload de 133 B habilitado
[AMG] Wire.begin=OK
[AMG] init OK addr=0x69
[AMG] OK therm=0x9601 pixels[0]=0x6400
[BATT] 3600 mV
[UPLINK] port=1 payload=0196016400... (133 B)
[UPLINK] OK (sin downlink)
[SLEEP] Durmiendo 60000 ms...
```

### 2. Ejemplo de payload (ilustrativo) y decodificación

Supongamos: `version = 0x01`, termistor `0x0196`, primer píxel `0x0064` (25 °C), segundo `0x0FD8`
(−10 °C), batería 3600 mV (`0x0E10` BE):

```
payload (133 B) = 01 96 01 64 00 D8 0F ... <128 bytes de píxeles> ... 0E 10
```

Salida del `decoder.js` (JSON):

```json
{
  "version": 1,
  "sensor_ok": true,
  "thermistor_raw": "0x9601",
  "thermistor_C": 25.38,
  "pixels_raw": "0x6400D80F...",
  "pixels_C": [25.0, -10.0, ...],
  "pixel_min_C": -10.0,
  "pixel_max_C": 25.0,
  "battery_mV": 3600,
  "battery_V": 3.6,
  "battery_percent": 95,
  "rssi": -85,
  "snr": 9.5
}
```

> Cálculo de comprobación: `0x0196 = 406 → 406 × 0.0625 = 25.375 ≈ 25.38 °C`;
> `0x0064 = 100 → 100 × 0.25 = 25.0 °C`; `0x0FD8 → −40 → −10.0 °C`.

---

## Compilación y carga

Requisitos previos:

- **arduino-cli** instalado.
- Core **CubeCell 1.4.0** instalado (`arduino-cli core install CubeCell:CubeCell`).
- Librería **RadioLib 7.7.1** instalada (`arduino-cli lib install RadioLib`).
- `credentials.h` creado con las credenciales reales.

```bash
# Compilar (dentro del directorio del proyecto)
arduino-cli compile --fqbn CubeCell:CubeCell:CubeCell_AB02A .

# Transferir a la placa (ajusta el puerto si es necesario)
arduino-cli upload -p /dev/ttyUSB0 --fqbn CubeCell:CubeCell:CubeCell_AB02A .
```

### Monitor serie

```bash
arduino-cli monitor -p /dev/ttyUSB0 -c baudrate=115200
```

> **Nota sobre el FQBN**: el alias local instalado es `CubeCell:CubeCell:CubeCell_AB02A` (sin `/`).
> Si tu instalación usa la notación con subdirectorio, prueba
> `CubeCell:CubeCell:CubeCell_AB02A` (el alias oficial suele ser
> `Heltec CubeCell:CubeCell:CubeCell_AB02A`). Consulta `arduino-cli board listall | grep -i cubecell`.

### Librerías requeridas

| Librería | Versión | Propósito |
|---|---|---|
| **RadioLib** | 7.7.1 | LoRaWAN + SX1262 |
| **Wire** | core CubeCell 1.4.0 | I2C hacia el AMG8833 |
| **CubeCell core** | 1.4.0 | GPIO, deep sleep, `getBatteryVoltage()` |

> No se usa `Adafruit_AMG88xx`: la lectura cruda por registros es más eficiente (menos RAM/Flash) y
> proporciona exactamente los bytes que se envían.

---

## Visor térmico opcional (Python)

El proyecto incluye `thermal_viewer.py` (+ `config.json` + `requirements.txt`), que se suscribe por
**MQTT** a los *uplinks* publicados por el UG56 y renderiza la matriz 8×8 como imagen de calor.

```bash
pip install -r requirements.txt

# Editar config.json (IP del broker MQTT / topic / rango / colormap)
python3 thermal_viewer.py --config config.json
```

Opciones útiles:

| Flag | Efecto |
|---|---|
| `--no-window` | Solo guarda PNG (sin ventana gráfica) |
| `--once` | Sale tras el primer frame recibido |
| `--config <ruta>` | Usa un `config.json` distinto |

El visor decodifica los 133 bytes tanto si el gateway ya aplicó el `decoder.js` (campo `object`) como
si no (campos `data` en base64 o `payload` en hex).

---

## Advertencias y precauciones

- ⚠️ **Credenciales**: nunca publiques `credentials.h` ni el `AppKey`/`NwkKey` reales. Usa la plantilla
  `credentials.example.h` para compartir el proyecto.
- ⚠️ **Pila no recargable**: el HTCC-AB02A **NO carga la batería**. Usa únicamente pila Li-SOCl₂
  `ER14250` (3.6 V). Respeta la **polaridad** (+ / −) al insertarla.
- ⚠️ **Polaridad de VEXT invertida**: en esta placa el pad `VEXT` resultó **HIGH = ON / LOW = OFF**
  (verificado en campo con escáner I2C). El firmware ya usa `HIGH` para encender y `LOW` para apagar.
  Si usas otra revisión de placa, verifica la polaridad antes de confiar en el consumo 0 µA.
- ⚠️ **Bug del core CubeCell (I2C + deep sleep)**: tras el deep sleep, `Wire.begin()` no re-inicializa
  el periférico I2C (la variable `I2C_initVar` queda en `1` en SRAM, que sí se retiene en sleep). Sin
  `Wire.end()` previo, el sensor solo responde en el **1er ciclo tras reset** y falla en los siguientes.
  El firmware ya aplica `Wire.end()` antes de `Wire.begin()` en cada lectura. Si portas este código a
  otro proyecto, conserva ese patrón (`Wire.end(); Wire.begin();` alrededor de cada acceso I2C).
- ⚠️ **Re-join al recrear dispositivo**: si recreas el dispositivo en el NS con las mismas claves,
  el nodo debe re-negociar la sesión. Asegúrate de que las credenciales coincidan o el join fallará.
- ⚠️ **Duty cycle / sub-banda**: el nodo está configurado para **AU915 sub-banda 2**. El gateway debe
  tener esa sub-banda habilitada, o no se recibirán los uplinks.
- ⚠️ **ADR OFF + DR5 fijo**: es deliberado para garantizar el payload de 133 B en un único envío. Si
  el enlace es marginal, puede haber pérdidas; reducir el intervalo o el payload son los *trade-offs*.
- ⚠️ **Temperatura ambiente**: el AMG8833 mide radiación infrarroja; asegúrate de que la lente esté
  limpia y sin obstrucciones para lecturas fiables.
- ⚠️ **Antena**: conecta siempre una antena SMA antes de transmitir para no dañar la etapa de RF.

---

## Estructura del proyecto

```
HTCC_AB02A_AMG8833_Thermal/
├── HTCC_AB02A_AMG8833_Thermal.ino   # Firmware principal (RadioLib, 465 líneas)
├── credentials.h                    # Credenciales reales OTAA (NO versionar)
├── credentials.example.h            # Plantilla pública con placeholders
├── decoder.js                       # Payload decoder para el NS (Milesight UG56)
├── thermal_viewer.py                # Visor térmico opcional (MQTT → imagen de calor)
├── config.json                      # Configuración del visor
├── requirements.txt                 # Dependencias Python del visor
├── .gitignore                       # Excluye credentials.h, PLAN.md, build/, etc.
├── README.md                        # Este documento
└── docs/
    ├── datasheet.md                 # Documentación de usuario (datasheet)
    └── developer.md                 # Documentación para desarrolladores
```

---

## Documentación adicional

- [`docs/datasheet.md`](docs/datasheet.md) — Datasheet orientado al usuario final.
- [`docs/developer.md`](docs/developer.md) — Explicación del código fuente y guía de modificación.
