# Documentación de desarrollador — Nodo LoRaWAN HTCC-AB02A + AMG8833 + ADXL335 (v2.0)

> Guía técnica del firmware `HTCC_AB02A_AMG8833_Thermal_Acelerometro.ino` (v2.0).
>
> Orientada a mantener, modificar y extender el nodo: arquitectura, funciones, flujo de estados y guías de cambio.

---

## 1. Arquitectura del firmware

El sketch es un **programa secuencial con un bucle de ciclo fijo**, no una máquina de estados explícita compleja. Se apoya en la infraestructura low-power nativa del core CubeCell (`TimerEvent_t` + `lowPowerHandler()`) y en **RadioLib 7.7.1** para el stack LoRaWAN.

```
┌──────────────────────────────────────────────────────────────────┐
│                        Includes / Config                          │
│  RadioLib.h · Wire.h · credentials.h · Arduino.h                 │
│  Objetos: Module mod(35,38,47,39) → SX1262 radio → LoRaWANNode   │
│  Región AU915 · sub-banda 2                                       │
├──────────────────────────────────────────────────────────────────┤
│  setup()                                                          │
│   · Serial, VEXT OFF, radio.begin(), node.beginOTAA()             │
│   · node.scanGuard=200 (workaround timers)                        │
│   · node.activateOTAA() → setADR(false) → applyDrSettings()       │
│   · drProbePending = true                                         │
├──────────────────────────────────────────────────────────────────┤
│  loop()                                                           │
│   1. ensureJoined()               (re-join si se pierde la sesión)│
│   2. sendProbeUplink()            (si drProbePending → fijar DR5) │
│   3. vextSensorOn()               (enciende sensores)             │
│   4. sampleAccel()                (acelerómetro, 50 muestras)     │
│   5. readAmg8833()                (termistor + 64 píxeles)        │
│   6. vextSensorOff()              (apaga sensores → 0 µA)         │
│   7. sendReport()                 (uplink 138 B, port 1)          │
│   8. deepSleepMillis(60000)       (deep sleep 60 s)               │
└──────────────────────────────────────────────────────────────────┘
```

### Decisiones de diseño clave

1. **Un solo ciclo bloqueante** en `loop()`: se despierta, mide todo y vuelve a dormir. Sencillo de razonar y de bajo consumo.
2. **ADR OFF + DR5 fija**: el payload de 138 B no cabe en la DR inicial (51–115 B), así que se fuerza `setDatarate(5)` y se envía un uplink sonda para que el NS aplique la DR vía `LinkADRReq/Ans`.
3. **Desenergización total**: VEXT conmuta ambos sensores; en deep sleep no hay consumo residual.
4. **Normalización ADC a 10 bits**: `analogRead() >> 2` para conservar los umbrales de vibración calibrados del nodo de referencia.

---

## 2. Diagrama de flujo de la lógica principal

```
        ┌──────────────┐
        │   setup()    │
        └──────┬───────┘
               ▼
        ┌──────────────┐   no
  ┌────►│ node.isActivated()? │────► ensureJoined()
  │     └──────┬───────┘              │
  │            │ sí                   │ fallo → deepSleep(10 s) → vuelve
  │            ▼                      │ ok
  │     ┌──────────────┐              │
  │     │ drProbePending? │──sí──► sendProbeUplink() → ¿DR5 confirmada?
  │     └──────┬───────┘                                  │
  │            │ (no/sí ya aplicado)                      ▼
  │            ▼                                    drProbePending=false
  │     ┌──────────────┐
  │     │ vextSensorOn() │   VEXT HIGH + delay(250)
  │     └──────┬───────┘
  │            ▼
  │     ┌──────────────┐
  │     │ sampleAccel() │   50 muestras ADC → accel_x, vib_range, vib_level
  │     └──────┬───────┘
  │            ▼
  │     ┌──────────────┐
  │     │ readAmg8833() │   termistor + 64 píxeles (con fix Wire.end/begin)
  │     └──────┬───────┘
  │            ▼
  │     ┌──────────────┐
  │     │ vextSensorOff()│  Wire.end() + VEXT LOW
  │     └──────┬───────┘
  │            ▼
  │     ┌──────────────┐
  │     │ sendReport() │   uplink 138 B (port 1) + captura downlink
  │     └──────┬───────┘
  │            ▼
  │     ┌──────────────┐
  │     │ deepSleep(60s)│
  │     └──────┬───────┘
  └────────────┘ (RTC expira → wake)
```

---

## 3. API de funciones

### Configuración y estado

| Símbolo | Valor | Descripción |
|---|---|---|
| `SLEEP_INTERVAL_MS` | `60000UL` | Periodo entre reportes (ms) |
| `PAYLOAD_LEN` | `138` | Tamaño del payload uplink |
| `SENSOR_PWR_PIN` | `Vext` (P3_2) | Alimentación conmutada de sensores |
| `AMG8833_ADDR` | `0x69` | Dirección I2C primaria |
| `AMG8833_ADDR_ALT` | `0x68` | Dirección alternativa |
| `ACCEL_ADC_PIN` | `ADC1` (P2_0) | Entrada ADC del eje X |
| `ACCEL_N_SAMPLES` | `50` | Muestras de la ventana |
| `ACCEL_SAMPLE_MS` | `10` | Intervalo de muestreo (~100 Hz) |
| `VIB_TH_REST` / `VIB_TH_LOW` / `VIB_TH_MED` | `12` / `40` / `100` | Umbrales de vibración (10-bit) |

### Funciones

| Función | Firma | Propósito |
|---|---|---|
| `vextSensorOn()` | `void` | `pinMode(Vext,OUTPUT)` + `digitalWrite(Vext,HIGH)` + `delay(250)` (cold-start) |
| `vextSensorOff()` | `void` | `Wire.end()` + `digitalWrite(Vext,LOW)` |
| `sampleAccel()` | `void (uint16_t*, uint16_t*, uint8_t*)` | Muestrea 50× el ADC, calcula promedio, rango y nivel |
| `categorizeVibration()` | `uint8_t (uint16_t range)` | Clasifica el rango en 0–3 |
| `readAmg8833()` | `bool (uint8_t* therm, uint8_t* pixels)` | Lee termistor + 64 píxeles (con fix I2C) |
| `amgWriteRegAt()` | `bool (addr, reg, val)` | Escritura I2C de un registro |
| `amgReadAt()` | `int (addr, reg, buf, len)` | Lectura I2C de un bloque |
| `readBatteryMv()` | `uint16_t` | `getBatteryVoltage()` en mV |
| `sendReport()` | `int (…)` | Construye y envía el uplink de 138 B |
| `sendProbeUplink()` | `void` | Uplink sonda (6 B) para fijar DR5 |
| `applyDrSettings()` | `void` | `node.setDatarate(5)` |
| `ensureJoined()` | `bool` | Re-join OTAA con backoff |
| `handleDownlink()` | `void (data, len)` | Loguea downlink (sin acciones) |
| `deepSleepMillis()` | `void (uint32_t ms)` | Deep sleep con timer RTC |
| `stateDecode()` | `const char*` | Traduce códigos de error RadioLib |
| `debug()` | `Serial.printf` | Macro de log serial |

---

## 4. Explicación del código por secciones

### 4.1 Cabecera y objetos RadioLib

```c
Module mod(35, 38, 47, 39);   // NSS=P4_3, DIO1=P4_6, RST=P5_7, BUSY=P4_7
SX1262 radio(&mod);
const LoRaWANBand_t Region = AU915;
const uint8_t subBand = 2;
LoRaWANNode node(&radio, &Region, subBand);
```

- `Module` define los pines internos del SiP ASR6502 (no reasignables).
- `LoRaWANNode` es el objeto de alto nivel de RadioLib para LoRaWAN Clase A.

### 4.2 `setup()`

1. Inicializa el serial (115200) y deja un `delay(3000)` para que el usuario abra el monitor.
2. Apaga VEXT desde el inicio (`LOW = OFF`).
3. `radio.begin()` y `node.beginOTAA(joinEui, devEui, nwkKey, appKey)`.
4. `node.scanGuard = 200` — workaround de un bug de timers en las esperas de radio.
5. `node.activateOTAA()` — join inicial; si tiene éxito, `setADR(false)` y `applyDrSettings()`.
6. Marca `drProbePending = true` para enviar la sonda en el primer `loop()`.

### 4.3 `loop()`

- **Re-join**: `if (!node.isActivated())` → `ensureJoined()`; si falla, `deepSleepMillis(10000)` y reintenta.
- **Sonda DR5**: si `drProbePending`, llama `sendProbeUplink()`. Si `getMaxPayloadLen() >= PAYLOAD_LEN`, la DR5 quedó aplicada y se limpia el flag. Tras 5 intentos sin confirmación, continúa igualmente.
- **Medición**: `vextSensorOn()` → `sampleAccel()` → `readAmg8833()` → `vextSensorOff()`.
- **Envío**: `sendReport(...)`.
- **Sleep**: `deepSleepMillis(SLEEP_INTERVAL_MS)`.

### 4.4 Acelerómetro (`sampleAccel`)

```c
for (uint8_t i = 0; i < ACCEL_N_SAMPLES; i++) {
    accelBuf[i] = (uint16_t)(analogRead(ACCEL_ADC_PIN) >> 2);  // 12→10 bits
    delay(ACCEL_SAMPLE_MS);
}
// ... cálculo de mn, mx, sum ...
*avgOut   = sum / ACCEL_N_SAMPLES;   // promedio
*rangeOut = mx - mn;                 // rango (max-min)
*levelOut = categorizeVibration(*rangeOut);
```

- `analogRead()` devuelve 0–4095 (12 bits). `>> 2` normaliza a 0–1023 (10 bits).
- `accelBuf` es estático (50 × `uint16_t` = 100 B de RAM).

### 4.5 I2C y el fix del bug de deep sleep (`readAmg8833`)

El **bug del core CubeCell**: tras el deep sleep, `Wire.begin()` no reinicializa el periférico SCB porque `I2C_initVar` queda en `1` en SRAM (que se retiene). La solución es:

```c
Wire.end();                              // resetea I2C_initVar
bool wireOk = Wire.begin(SDA, SCL, 100000);  // fuerza I2C_Init() completo
```

Secuencia de lectura del AMG8833:

1. `Wire.end()` + `Wire.begin(SDA, SCL, 100000)`.
2. Inicialización (intenta `0x69` y luego `0x68`): `PCTL(0x00)=0x00` → `RESET(0x01)=0x3F` → `FPSC(0x04)=0x05` (10 fps).
3. `delay(200)` — espera el primer frame (100 ms @10 fps) + margen.
4. Lee termistor (2 B desde `0x0E`) y píxeles (128 B desde `0x80`, en 2 tramos de 64 B por el límite del buffer I2C del core).

### 4.6 Uplink y DR (`sendReport`, `sendProbeUplink`, `applyDrSettings`)

- `applyDrSettings()` llama `node.setDatarate(5)` (DR5/SF7), que encola un `LinkADRReq` que viaja en los FOpts del próximo uplink.
- `sendProbeUplink()` envía un payload corto de 6 B (`0x02` + batería + 3 bytes 0) que transporta el `LinkADRReq`; cuando el NS responde con `LinkADRAns`, `getMaxPayloadLen()` sube a ~238 B y se habilitan los 138 B.
- `sendReport()` construye el payload de 138 B y llama `node.sendReceive(...)` en el puerto 1 (no confirmado), capturando el downlink.

### 4.7 Deep sleep (`deepSleepMillis`)

```c
sleepExpired = false;
TimerInit(&sleepTimer, onSleepTimerExpired);
TimerSetValue(&sleepTimer, ms);
TimerStart(&sleepTimer);
radio.sleep();
while (!sleepExpired) {
    lowPowerHandler();   // CySysPmDeepSleep() hasta IRQ del RTC
}
TimerStop(&sleepTimer);
radio.standby();
```

- Usa el **timer RTC** (`TimerEvent_t`) del core para despertar al MCU.
- `radio.sleep()` apaga el SX1262; `radio.standby()` lo reactiva al despertar.

---

## 5. Guía de modificación y extensión

### 5.1 Cambiar el periodo de reporte (de 1 min a 3 h)

Edita el `#define` en la cabecera:

```c
#define SLEEP_INTERVAL_MS    60000UL   /* 1 minuto */
```

Para 3 horas:

```c
#define SLEEP_INTERVAL_MS    10800000UL  /* 3 h = 3 * 60 * 60 * 1000 */
```

> No hay otros cambios necesarios: el deep sleep usa `uint32_t` (admite hasta ~49 días). Tras estabilizar el sistema, este es el único ajuste para alargar la vida de la pila.

### 5.2 Ajustar los umbrales de vibración

Los umbrales son `#define`s en la cabecera:

```c
#define VIB_TH_REST  12
#define VIB_TH_LOW   40
#define VIB_TH_MED   100
```

Re-calíbralos si la sensibilidad física difiere (la CubeCell mapea 0–4095 sobre ~2,4 V, distinto al ESP8266). La función `categorizeVibration()` los usa directamente.

### 5.3 Agregar sensores

1. **Definir pines/constantes** en la cabecera.
2. **Añadir la lectura** en `loop()`, dentro de la ventana activa (entre `vextSensorOn()` y `vextSensorOff()`).
3. **Ampliar el payload**: aumenta `PAYLOAD_LEN`, añade los bytes en `sendReport()` y **actualiza `decoder.js`** en los mismos offsets.
4. Verifica que el payload total siga cabiendo en DR5 (~238 B en AU915).

### 5.4 Cambiar el payload

- Modifica la construcción en `sendReport()` (offsets fijos, endianidad correcta).
- Actualiza `PAYLOAD_LEN`.
- Actualiza `decoder.js` con los mismos offsets y endianidad.
- Si superas ~238 B, cambia a una DR mayor o divide en múltiples uplinks.

### 5.5 Cambiar la región LoRaWAN

1. Cambia `const LoRaWANBand_t Region = AU915;` y `subBand` por la región objetivo (p. ej. `EU868`, `US915`).
2. Revisa el `setDatarate(5)` y el `getMaxPayloadLen()`: el mapeo de DR y los límites de payload varían por región.
3. Reconfigura el gateway a la misma región/sub-banda.

### 5.6 Agregar comandos de downlink

Actualmente `handleDownlink()` solo loguea el primer byte. Para añadir comandos:

1. Define un protocolo (p. ej. `0x01` = cambiar periodo).
2. Procesa en `handleDownlink()`.
3. Implementa `Encode(fPort, obj)` en `decoder.js` para enviar el comando desde el NS.

### 5.7 Cambiar la dirección I2C del AMG8833

Si sueldas el puente `Addr` del AMG8833 (dirección 0x68), cambia:

```c
#define AMG8833_ADDR         0x68
```

El código ya intenta `0x69` y `0x68` automáticamente en `readAmg8833()`.

---

## 6. Restricciones de memoria

| Recurso | Uso estimado |
|---|---|
| Flash | RadioLib ~33 KB + I2C + accel ≈ **< 41 KB** (de 128 KB) |
| RAM | Payload 138 B + downlink 242 B + buffer accel 100 B ≈ **< 5,5 KB** (de 16 KB) |

Margen amplio en ambos casos.

---

## 7. Compilación y carga

```bash
arduino-cli compile --fqbn CubeCell:CubeCell:CubeCell_AB02A .
arduino-cli upload -p /dev/ttyUSB0 --fqbn CubeCell:CubeCell:CubeCell_AB02A .
arduino-cli monitor -p /dev/ttyUSB0 -c baudrate=115200
```

---

*Fin de la documentación de desarrollador. Consulta `README.md` (visión general) y `docs/datasheet.md` (usuario final).*
