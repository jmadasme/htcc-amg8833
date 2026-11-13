# Nodo LoRaWAN Low-Power — Termocámara AMG8833 + Acelerómetro ADXL335 (v2.0)

> **Heltec CubeCell HTCC-AB02A** · LoRaWAN **AU915 sub-banda 2** · **OTAA** · **Clase A** · RadioLib 7.7.1
>
> Nodo de ultra-bajo consumo que combina una **termocámara infrarroja 8×8 (AMG8833)** y un **acelerómetro analógico (ADXL335)** con **clasificación de movimiento/vibración**, reportando todo por LoRaWAN cada 60 segundos al gateway **Milesight UG56**.

---

## Tabla de contenidos

1. [¿Qué es este nodo?](#qué-es-este-nodo)
2. [Placa objetivo y especificaciones](#placa-objetivo-y-especificaciones)
3. [Principio de funcionamiento](#principio-de-funcionamiento)
4. [Estado actual del proyecto (v2.0)](#estado-actual-del-proyecto-v20)
5. [Forma de operar](#forma-de-operar)
6. [Tabla de pines (pinout)](#tabla-de-pines-pinout)
7. [Diagrama de conexión](#diagrama-de-conexión)
8. [Configuración LoRaWAN](#configuración-lorawan)
9. [Formato de payload](#formato-de-payload)
10. [Clasificación de movimiento](#clasificación-de-movimiento)
11. [Compilación y carga](#compilación-y-carga)
12. [Ejemplos de uso (salida serial)](#ejemplos-de-uso-salida-serial)
13. [Advertencias y precauciones](#advertencias-y-precauciones)
14. [Punto de decisión de diseño (A vs B)](#punto-de-decisión-de-diseño-a-vs-b)

---

## ¿Qué es este nodo?

Es la **v2.0** del nodo LoRaWAN de termografía. Sobre la v1.0 (que ya publicaba una matriz térmica AMG8833 de 8×8 = 64 píxeles cada 60 s) añade un **acelerómetro analógico GY-61 (ADXL335)** que:

- Muestrea **solo el eje X** durante la fase activa de cada ciclo (50 muestras a ~100 Hz).
- Calcula tres métricas: `accel_x` (promedio), `vib_range` (max − min) y `vib_level` (clasificación en 4 niveles).
- Clasifica el movimiento en **reposo / baja / media / alta** usando los mismos umbrales calibrados en campo del nodo ESP8266 de referencia.

Ambos sensores se alimentan del **mismo pad VEXT (P3_2)**, de modo que quedan **totalmente desenergizados (0 µA) durante el deep sleep**, maximizando la vida útil de la pila.

### Datos que reporta (por cada ciclo)

| Dato | Origen |
|---|---|
| Temperatura del termistor del AMG8833 | registro I2C `0x0E` |
| Mapa térmico 8×8 (64 píxeles) | registros I2C `0x80`–`0xFF` |
| Tensión de batería (mV) | `getBatteryVoltage()` |
| `accel_x` (promedio eje X, 10-bit) | ADC1 (P2_0) |
| `vib_level` (0–3) | clasificación de `vib_range` |
| `vib_range` (max−min, 10-bit) | ADC1 (P2_0) |

---

## Placa objetivo y especificaciones

| Característica | Valor |
|---|---|
| **Placa** | Heltec CubeCell **HTCC-AB02A** ("CubeCell 1/2AA Node") |
| **MCU** | **ASR6502** — ARM Cortex-M0+ @ **48 MHz** con radio **SX1262** integrada (SiP) |
| **RAM** | **16 KB** (16 384 B) |
| **Flash** | **128 KB** (131 072 B) |
| **Deep sleep** | **3,5 µA** (típico, con radio apagada) |
| **Alimentación** | Pila 1/2AA **Li-SOCl₂ ER14250** (3,6 V · 1200 mAh · **no recargable**) |
| **USB** | CP210x (puerto serie) |
| **Antena** | SMA (LoRa) |
| **FQBN** | `CubeCell:CubeCell:CubeCell_AB02A` |
| **Core** | CubeCell 1.4.0 (`ASR650x-Arduino-1.4.0`) |

### Sensores

| Sensor | Detalle |
|---|---|
| **Termocámara AMG8833** | Matriz IR 8×8 (64 píxeles), I2C `0x69` (alt. `0x68`), termistor en `0x0E`, píxeles en `0x80`–`0xFF`. Conversión: termistor ×0,0625 °C/LSB, píxeles ×0,25 °C/LSB (12-bit con signo, complemento a 2). |
| **Acelerómetro GY-61 (ADXL335)** | MEMS analógico de 3 ejes (±3 g), ~300 mV/g. Se usa **solo el eje X** en `ADC1` (P2_0). Y_OUT / Z_OUT sin conectar. Consumo ~350–400 µA. |

### ADC de la CubeCell

- **Resolución**: 12 bits → `analogRead()` retorna **0–4095**.
- **Fondo de escala**: ~2,4 V (no 3,3 V).
- En el código, las lecturas se **normalizan a 10 bits** (`v >> 2`) para conservar los umbrales de vibración calibrados en el ESP8266 de referencia (12/40/100).

---

## Principio de funcionamiento

El nodo ejecuta un **ciclo fijo de 60 segundos**:

```
┌─────────────────────────── deep sleep 60 s ───────────────────────────┐
│  radio.sleep() · TimerEvent_t (RTC) · lowPowerHandler() (CySysPmDeepSleep) │
│  VEXT LOW → AMG8833 + ADXL335 desenergizados (0 µA)                   │
└───────────────────────────────────────────────────────────────────────┘
        │  Timer RTC expira → wake up
        ▼
┌── radio.standby() ───────────────────────────────────────────────────┐
│  vextSensorOn(): pinMode(Vext,OUTPUT) + digitalWrite(Vext,HIGH)       │
│  → enciende AMG8833 + ADXL335 · delay(250 ms) cold-start              │
└──────────────────────────────────────────────────────────────────────┘
        ▼
┌── sampleAccel(): 50 muestras del eje X cada 10 ms (~100 Hz, 500 ms) ──┐
│  → accel_x (promedio) · vib_range (max−min) · vib_level (0–3)         │
│  (solapa con la espera del primer frame del AMG8833 @10 fps)          │
└──────────────────────────────────────────────────────────────────────┘
        ▼
┌── readAmg8833(): termistor (0x0E) + 64 píxeles (0x80–0xFF) ──────────┐
│  Wire.end() → Wire.begin() (fix bug I2C + deep sleep)                 │
└──────────────────────────────────────────────────────────────────────┘
        ▼
┌── vextSensorOff(): Wire.end() + digitalWrite(Vext,LOW) → 0 µA ───────┘
        ▼
┌── sendReport(): payload 138 B · batería · sendReceive (port 1) ───────┐
│  (captura downlink en ventana RX de Clase A)                          │
└──────────────────────────────────────────────────────────────────────┘
        ▼
   radio.sleep() → deep sleep 60 s (repite)
```

### Detalles clave del flujo

1. **Join OTAA**: el nodo se une con `activateOTAA()`. Tras el join, `setADR(false)` y `applyDrSettings()` fijan **DR5 (SF7)** — necesaria para admitir los 138 B de payload (en AU915, DR4 solo admite ~125 B).
2. **Uplink sonda (`sendProbeUplink`)**: tras el join se envía un uplink corto (6 B) que lleva el `LinkADRReq` en los FOpts; al recibir el `LinkADRAns` el NS confirma DR5 y habilita el payload grande. Se reintenta hasta 5 veces.
3. **Desenergización total**: `VEXT` (P3_2) alimenta AMG8833 + ADXL335 juntos. Al bajar a LOW, ambos quedan a 0 µA durante el deep sleep.
4. **Re-join automático**: `ensureJoined()` reintenta el OTAA con *backoff* de 10 s si se pierde la sesión.

---

## Estado actual del proyecto (v2.0)

| Elemento | Estado |
|---|---|
| Firmware v2.0 (`.ino`, 138 B) | ✅ **Listo, compilado y grabado** en la placa |
| Join OTAA en UG56 | ✅ Verificado |
| Termocámara AMG8833 | ✅ **Cableada y funcionando** |
| Decoder v2.0 (`decoder.js`) | ✅ Creado y probado (Node.js) |
| Acelerómetro GY-61 | ⏸️ **NO cableado aún** (pruebas detenidas por decisión de diseño) |
| Clasificación de movimiento en campo | ⏸️ Pendiente (requiere cablear el GY-61) |
| Periodo de reporte | 60 s (pendiente alargar a **3 h** tras estabilizar) |

> **Nota**: el firmware está grabado y transmitiendo, pero con el pin `ADC1` **flotando**, por lo que los valores de `accel_x`/`vib_level`/`vib_range` **no son reales** hasta cablear el GY-61.

---

## Forma de operar

1. **Alimenta** la placa con la pila ER14250 (3,6 V) o por USB para desarrollo.
2. **Observa el arranque** por el monitor serial (115200 baud): verás el banner `[INIT]`, el `[JOIN] +++ JOINED +++` y luego el ciclo `[ACC]` → `[AMG]` → `[UPLINK]` → `[SLEEP]`.
3. **Verifica en el gateway** (UG56) que llegan los uplinks de 138 B en el puerto 1, decodificados con `decoder.js`.
4. El nodo **no requiere intervención**: se despierta, mide y duerme automáticamente cada 60 s.
5. Para detenerlo, desconecta la alimentación.

### Herramientas necesarias

- **arduino-cli** con el core CubeCell 1.4.0 instalado.
- **RadioLib 7.7.1** en `~/Arduino/libraries/RadioLib`.
- Un cable USB (CP210x) y un monitor serial (`arduino-cli monitor` o similar).

---

## Tabla de pines (pinout)

### Termocámara AMG8833

| Pin AMG8833 | Pad CubeCell | Nota |
|---|---|---|
| **VIN** | **VEXT** (`P3_2`) | Alimentación conmutada 3,3 V (**HIGH=ON / LOW=OFF**) |
| **GND** | **GND** | Común |
| **SCL** | **SCL0** (`P0_0`, pin 39) | I2C0 |
| **SDA** | **SDA0** (`P0_1`, pin 40) | I2C0 |

### Acelerómetro GY-61 (ADXL335)

| Pin GY-61 | Pad CubeCell | Nota |
|---|---|---|
| **VCC** | **VEXT** (`P3_2`) | Mismo rail conmutado que AMG8833 → 0 µA en sleep |
| **GND** | **GND** | Común |
| **X_OUT** | **ADC1** (`P2_0`) | Entrada analógica eje X (único eje usado) |
| **Y_OUT** | — | **SIN CONECTAR** |
| **Z_OUT** | — | **SIN CONECTAR** |

### Pines internos (SiP ASR6502 — no reasignables)

| Señal SX1262 | Pad (GPIO) | Nota |
|---|---|---|
| NSS | `P4_3` = 35 | SPI |
| DIO1 | `P4_6` = 38 | DIO |
| RST | `P5_7` = 47 | GPIO |
| BUSY | `P4_7` = 39 | GPIO |

### Otros pads relevantes

| Pad | Uso |
|---|---|
| `P3_3` (`VBAT_ADC_CTL`) | Lectura de batería (`getBatteryVoltage()`) |
| `P3_0` / `P3_1` | Serial USB (CP210x) — monitor serial |
| `P2_1` / `P2_2` | ADC2 / ADC3 (libres, para ejes Y/Z si se ampliara) |

---

## Diagrama de conexión

```
                      Heltec CubeCell HTCC-AB02A
     ┌──────────────────────────────────────────────────────────────┐
     │                                                              │
     │   VEXT (P3_2) ──────────────┬───────────────► AMG8833 VIN    │
     │        (HIGH=ON/LOW=OFF)    │                                  │
     │                             └───────────────► GY-61 VCC       │
     │                                                              │
     │   GND  ─────────────────────┬───────────────► AMG8833 GND    │
     │                             └───────────────► GY-61 GND       │
     │                                                              │
     │   SCL0 (P0_0) ────────────────────────────────► AMG8833 SCL   │
     │   SDA0 (P0_1) ────────────────────────────────► AMG8833 SDA   │
     │                                                              │
     │   ADC1 (P2_0) ────────────────────────────────► GY-61 X_OUT   │
     │                                                              │
     │   (GY-61 Y_OUT y Z_OUT  →  SIN CONECTAR)                     │
     │                                                              │
     └──────────────────────────────────────────────────────────────┘

   Termocámara AMG8833            Acelerómetro GY-61 (ADXL335)
   ┌──────────────────┐          ┌────────────────────────┐
   │ VIN ← VEXT       │          │ VCC      ← VEXT        │
   │ GND ← GND        │          │ GND      ← GND         │
   │ SCL ← SCL0(P0_0) │          │ X_OUT    ← ADC1(P2_0)  │
   │ SDA ← SDA0(P0_1) │          │ Y_OUT    ← (libre)     │
   └──────────────────┘          │ Z_OUT    ← (libre)     │
                                 └────────────────────────┘
```

**Descripción textual del cableado:**

1. El pad **VEXT** (P3_2) es un rail conmutado de 3,3 V. Se conecta **en paralelo** a `VIN` del AMG8833 y a `VCC` del GY-61. Como la polaridad en esta placa está **invertida**, `HIGH = encendido` y `LOW = apagado`.
2. El **GND** común une la placa, el AMG8833 y el GY-61.
3. El bus **I2C0** conecta `SCL0` (P0_0) → `SCL` del AMG8833 y `SDA0` (P0_1) → `SDA` del AMG8833.
4. La salida analógica **X_OUT** del GY-61 se conecta a **ADC1** (P2_0), que es la entrada ADC leída por `analogRead()`.
5. **Y_OUT** y **Z_OUT** del GY-61 quedan **sin conectar** (solo se monitoriza el eje X).

> **Consumo conjunto**: AMG8833 (~4,5 mA) + ADXL335 (~0,4 mA) ≈ **5 mA**, muy por debajo del límite del pad VEXT (~350 mA). No se necesita MOSFET externo.

---

## Configuración LoRaWAN

### 1. Parámetros de red

| Parámetro | Valor |
|---|---|
| Región / sub-banda | **AU915, sub-banda 2** |
| Activación | **OTAA** |
| Clase | **A** |
| Stack | RadioLib 7.7.1 |
| Gateway / NS | **Milesight UG56** (Network Server embebido) |
| Puerto uplink | **1** |
| Confirmación | **Unconfirmed** |
| ADR | **OFF** — DR fijada en código con `node.setDatarate(5)` |
| Data rate | **DR5 (SF7 / 125 kHz)** — máx ~238 B en AU915 |
| Intervalo | **60 000 ms** |

### 2. Registro del dispositivo en el Network Server (UG56)

El gateway **Milesight UG56** incorpora un Network Server embebido. Para registrar el dispositivo:

1. Accede a la interfaz web del UG56 (`http://<IP_del_gateway>`).
2. Ve a **LoRaWAN → Network Server → Applications / Devices**.
3. Crea o selecciona la aplicación destino.
4. Añade un **nuevo dispositivo** en modo **OTAA** con:
   - **DevEUI**: `70B3D56F27CEE98B`
   - **JoinEUI / AppEUI**: `24E124C0002ADD01`
   - **AppKey / NwkKey**: las que tengas en `credentials.h` (LoRaWAN 1.0.x: AppKey == NwkKey).
5. Configura la **clase A** y el puerto de aplicación `1`.
6. Guarda. El dispositivo se unirá con un **Join Request** en la sub-banda 2.

> En **TTN (The Things Stack)** o **ChirpStack** el procedimiento es análogo: crear *end device* con OTAA, clase A, región **AU915**, y el *sub-band* configurado en el **gateway** (canales 8–15 para la sub-banda 2). En el caso del UG56, el sub-banda se configura en la página del gateway (LoRa → Channel Plan → AU915 → Sub-band 2).

### 3. Credenciales OTAA (importante)

Las credenciales se gestionan en el archivo **`credentials.h`** (que **no se versiona**, está en `.gitignore`). La plantilla pública es **`credentials.example.h`**:

```c
/* credentials.example.h — PLANTILLA PÚBLICA */
static const uint64_t joinEui = 0x0000000000000000ULL;   /* JoinEUI / AppEUI (BE) */
static const uint64_t devEui  = 0x0000000000000000ULL;   /* DevEUI (BE)           */
static const uint8_t appKey[] = { /* 16 bytes BE */ };
static const uint8_t nwkKey[] = { /* 16 bytes BE */ };
```

> ⚠️ **Nunca publiques ni versiones `credentials.h`** (contiene las claves reales). Para reproducir el nodo:
> 1. Copia `credentials.example.h` a `credentials.h`.
> 2. Rellena `joinEui`, `devEui`, `appKey` y `nwkKey` con **tus** valores reales.
> 3. RadioLib espera las credenciales en **big-endian** (orden over-the-air).

| Identificador | Visibilidad | Valor (referencia) |
|---|---|---|
| DevEUI | público (identificador) | `70B3D56F27CEE98B` |
| JoinEUI / AppEUI | público (identificador) | `24E124C0002ADD01` |
| AppKey / NwkKey | **secreto** | en `credentials.h` (no documentado) |

### 4. Pegar el `decoder.js` en el Network Server

1. Abre el archivo **`decoder.js`** de este proyecto.
2. En el UG56: **LoRaWAN → Application → Payload Codec (o Payload Decoder)**.
3. Pega el contenido completo del `decoder.js` en el campo **Payload Decoder**.
4. Guarda. A partir de ese momento, cada uplink de 138 B se decodificará a un objeto JSON con:
   - `version`, `sensor_ok`, `thermistor_raw`, `thermistor_C`
   - `pixels_raw`, `pixels_C` (64 valores), `pixel_min_C`, `pixel_max_C`
   - `battery_mV`, `battery_V`, `battery_percent`
   - `accel_x`, `vib_level`, `vib_label`, `vib_range`
   - `rssi`, `snr` (si el gateway expone `LoRaObject`)

> El `decoder.js` está escrito en **JavaScript ES5** (sin `let`/`const`/arrow functions), compatible con Milesight UG56/UG65/UG67 y ChirpStack v3. Es **retrocompatible** con tramas v1.0 de 133 B.

---

## Formato de payload

### Uplink (fPort 1, 138 bytes)

| Byte(s) | Campo | Contenido | Endianidad |
|---|---|---|---|
| `[0]` | `version/estado` | `0x01` = OK · `0x81` = fallo de lectura I2C | — |
| `[1:2]` | `thermistor` | termistor crudo AMG8833 (12-bit con signo) | **LE** |
| `[3:130]` | `pixels[64]` | 64 píxeles crudos (128 B, 12-bit con signo) | **LE** |
| `[131:132]` | `battery_mV` | voltaje de batería `uint16` | **BE** |
| `[133:134]` | `accel_x` | promedio eje X (ventana), dominio 10-bit (≤1023) | **BE** |
| `[135]` | `vib_level` | 0=reposo · 1=baja · 2=media · 3=alta | — |
| `[136:137]` | `vib_range` | max−min de la ventana, dominio 10-bit (≤1023) | **BE** |

**Longitud total: 138 bytes.** En AU915 DR5 (SF7) caben ~238 B → cabe holgadamente.

### Conversión a °C (resoluciones distintas por registro)

| Registro | Resolución | Fórmula |
|---|---|---|
| Termistor (`0x0E`) | 0,0625 °C/LSB | `temp_C = valor12bit_signed * 0.0625` |
| Píxeles (`0x80`–`0xFF`) | 0,25 °C/LSB | `temp_C = valor12bit_signed * 0.25` |

> Ambos son enteros de 12 bits **con signo** (complemento a 2, 2 bytes little-endian). El `decoder.js` aplica `sign12()` antes de la conversión.

### Downlink

- Clase A: la ventana de recepción se abre tras cada uplink.
- **v2.0 no implementa comandos de downlink** — `handleDownlink()` solo registra por serial el primer byte recibido (`[RX] comando 0xXX (v2.0: sin acciones)`).
- El `Encode(fPort, obj)` del decoder devuelve un array vacío.

---

## Clasificación de movimiento

El acelerómetro muestrea **50 muestras del eje X cada 10 ms** (~100 Hz) → ventana de **500 ms**. Con esas muestras se calcula el rango (max − min) y se clasifica:

| Condición (`range` = max − min) | Nivel | Etiqueta |
|---|---|---|
| `range < 12` | 0 | reposo |
| `12 ≤ range < 40` | 1 | baja |
| `40 ≤ range < 100` | 2 | media |
| `range ≥ 100` | 3 | alta |

- Los umbrales **12 / 40 / 100** están calibrados en campo en el nodo ESP8266 de referencia.
- El ADC de la CubeCell es de **12 bits** (0–4095); las lecturas se **normalizan a 10 bits** (`v >> 2`) para conservar esos umbrales sin reescalar.
- Los `#define` de los umbrales (`VIB_TH_REST`, `VIB_TH_LOW`, `VIB_TH_MED`) son fácilmente ajustables en el `.ino`.

---

## Compilación y carga

> Requisitos: `arduino-cli` + core **CubeCell 1.4.0** + **RadioLib 7.7.1** instalados.

```bash
# 1. Compilar (desde el directorio del proyecto)
arduino-cli compile --fqbn CubeCell:CubeCell:CubeCell_AB02A .

# 2. Transferir a la placa (ajusta el puerto si no es /dev/ttyUSB0)
arduino-cli upload -p /dev/ttyUSB0 --fqbn CubeCell:CubeCell:CubeCell_AB02A .

# 3. (Opcional) Monitor serial a 115200 baud
arduino-cli monitor -p /dev/ttyUSB0 -c baudrate=115200
```

> **Nota de FQBN**: en este entorno se usa `CubeCell:CubeCell:CubeCell_AB02A` (el alias `CubeCell-1/2AA` no es parseable por arduino-cli aquí).
>
> **Compilación de referencia**: ~90 KB de flash (≈68 %), compila sin errores.

### Si el upload falla con "Timed out waiting for Bootloader response"

1. Desconecta y reconecta **físicamente** el cable USB de la CubeCell.
2. Reintenta el `arduino-cli upload`.

---

## Ejemplos de uso (salida serial)

### Arranque y join

```
[INIT] HTCC-AB02A + AMG8833 + ADXL335 nodo v2.0 (RadioLib) — AU915 SB2
[INIT] DevEUI=70B3D56F27CEE98B JoinEUI=24E124C0002ADD01
[INIT] Radio OK
[INIT] Node OK
[INIT] scanGuard=200 ms
[JOIN] Iniciando OTAA (AU915 SB2)...
[JOIN] +++ JOINED +++
[DR] setDatarate(5)=0 maxPayload=238 B
[INIT] Ciclo de 60000 ms (60 s). Listo.
```

### Ciclo normal (tras la sonda DR5)

```
[PROBE] uplink sonda port=1 payload=020E02000000 (6 B)
[DR] tras sonda maxPayload=238 B
[DR] DR5 confirmada, payload de 138 B habilitado
[ACC] x=710 rango=1 nivel=0 (50 muestras)
[AMG] Wire.begin=OK
[AMG] init OK addr=0x69
[AMG] OK therm=0x05A3 pixels[0]=0x0667
[BATT] 3620 mV
[UPLINK] port=1 payload=010A5... (138 B)
[UPLINK] OK (sin downlink)
[SLEEP] Durmiendo 60000 ms...
```

### Acelerómetro con movimiento (tras cablear el GY-61)

```
[ACC] x=703 rango=15 nivel=1 (50 muestras)   ← vibración baja
[ACC] x=698 rango=55 nivel=2 (50 muestras)   ← vibración media
[ACC] x=705 rango=132 nivel=3 (50 muestras)  ← vibración alta
```

### Ejemplo de objeto decodificado en el gateway

```json
{
  "version": 1,
  "sensor_ok": true,
  "thermistor_raw": "0xA305",
  "thermistor_C": 23.25,
  "pixels_raw": "0x6706...",
  "pixels_C": [24.25, 24.5, ...],
  "pixel_min_C": 21.0,
  "pixel_max_C": 29.75,
  "battery_mV": 3620,
  "battery_V": 3.62,
  "battery_percent": 95,
  "accel_x": 710,
  "vib_level": 0,
  "vib_label": "reposo",
  "vib_range": 1,
  "rssi": -105,
  "snr": 8.5
}
```

---

## Advertencias y precauciones

1. **Credenciales**: `credentials.h` contiene las claves reales y **nunca** debe versionarse ni publicarse. Usa `credentials.example.h` como plantilla.
2. **Pila no recargable**: la ER14250 (Li-SOCl₂) **no es recargable**. No conectes alimentación USB con la pila puesta si el hardware no lo soporta, y no intentes cargarla.
3. **Polaridad de VEXT invertida**: en el HTCC-AB02A, `HIGH = encendido` y `LOW = apagado` (contrario al pinout oficial). Verificado en campo: el AMG8833 solo responde con Vext en HIGH.
4. **Bug del core CubeCell (I2C + deep sleep)**: `Wire.begin()` no reinicializa el I2C tras el deep sleep (`I2C_initVar` queda en 1 en SRAM). El código aplica **`Wire.end()` antes de `Wire.begin()`** en cada lectura. Sin esto, el sensor solo responde el primer ciclo.
5. **`pinMode(Vext, OUTPUT)` se re-aplica** en `vextSensorOn()` porque el core puede reconfigurar pines tras el deep sleep.
6. **Cold-start del sensor**: el AMG8833 necesita ≥50 ms para estabilizar su oscilador; se usa `delay(250)` de margen. Los 20 ms de la v1.0 causaban fallos intermitentes (`sensor_ok=false`, payload `0x81`).
7. **Duty cycle / tiempo de aire**: con DR5 (SF7) el tiempo de aire del uplink de 138 B es ~80 ms. A 60 s de intervalo se cumple holgadamente el *duty cycle* de AU915. Al alargar a 3 h, aún más margen.
8. **`accel_x` en reposo ≈ 710** (no 512): el punto de 0 g del ADXL335 queda desplazado por la diferencia de escala ADC. Para la clasificación importa el **rango**, no el valor absoluto.
9. **`ADC1` flotante**: mientras el GY-61 no esté cableado, los valores del acelerómetro no son reales.
10. **No conectar Y_OUT / Z_OUT**: solo se monitoriza el eje X.

---

## Punto de decisión de diseño (A vs B)

El proyecto está en una **encrucijada de diseño** (documentada en `BITACORA.md`). No se continúa con las pruebas físicas hasta decidir el camino:

| Opción | Descripción | Estado |
|---|---|---|
| **A. Un solo nodo (integrado)** | Termocámara + acelerómetro en **una** misma CubeCell (v2.0 tal como está) | Firmware v2.0 listo, compilado y grabado; falta cablear el GY-61 y probar la clasificación |
| **B. Dos nodos separados** | Tarjeta 1: termocámara (v1.0 ya publicada). Tarjeta 2: acelerómetro (nuevo, con otra identidad LoRaWAN) | Requiere crear un firmware dedicado y **otro DevEUI/AppKey** (no pueden coexistir dos dispositivos con el mismo DevEUI) |

### Implicaciones de cada opción

- **Opción A (integrado)**: continuar donde quedó — cablear el GY-61 (`VCC→VEXT`, `GND→GND`, `X_OUT→ADC1`), probar la clasificación, verificar el payload decodificado en el gateway y alargar el periodo a 3 h.
- **Opción B (separado)**: este firmware v2.0 sirve de **base técnica** (ya tiene el acelerómetro implementado y el decoder con `vib_label`); habría que extraer solo la parte del acelerómetro en un proyecto nuevo, con payload reducido y nueva identidad LoRaWAN.

> **Estado físico actual**: la termocámara AMG8833 está cableada y funcionando; el acelerómetro GY-61 **no está cableado** (pendiente de decisión).

---

## Estructura del proyecto

```
HTCC_AB02A_AMG8833_Thermal_Acelerometro/
├── HTCC_AB02A_AMG8833_Thermal_Acelerometro.ino  # Firmware v2.0 (138 B)
├── credentials.h                                  # Credenciales reales (NO versionar)
├── credentials.example.h                          # Plantilla pública
├── decoder.js                                     # Payload decoder (UG56)
├── .gitignore                                     # Exclusiones (credentials.h, PLAN.md, etc.)
├── BITACORA.md                                    # Bitácora de desarrollo
├── PLAN.md                                        # Plan de implementación (no versionar)
└── docs/
    ├── datasheet.md                               # Documentación de usuario
    └── developer.md                               # Documentación de desarrollador
```

---

*Documentación generada para la versión v2.0. Consulta `docs/datasheet.md` (usuario final) y `docs/developer.md` (desarrollador) para más detalle.*
