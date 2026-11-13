# Documentación para Desarrolladores — Nodo LoRaWAN + AMG8833

> **Explicación del código fuente** · `HTCC_AB02A_AMG8833_Thermal.ino` (465 líneas, RadioLib 7.7.1)

---

## 1. Arquitectura general

El firmware sigue un patrón **single-file, sin FreeRTOS ni OS**: un bucle `setup()` + `loop()` con
*deep sleep* cooperativo basado en el RTC nativo del ASR6502.

```
┌─────────────────────────────────────────────────────────────────┐
│ includes (RadioLib, Wire, credentials, Arduino)                  │
│ radio (SX1262) → LoRaWANNode (AU915 SB2)                        │
│ AMG8833 por I2C (0x69/0x68) + alimentación VEXT                 │
├─────────────────────────────────────────────────────────────────┤
│ setup()   : Serial, VEXT=OFF, radio.begin(), node.beginOTAA(),  │
│             scanGuard=200, activateOTAA(), applyDrSettings()    │
├─────────────────────────────────────────────────────────────────┤
│ loop()    : re-join si falta → sonda DR → medir → enviar → dormir│
│             └── deepSleepMillis(60000)  (TimerEvent_t RTC)      │
└─────────────────────────────────────────────────────────────────┘
```

### Máquina de estados (implícita)

```
setup()
  └─► [BOOT] radio + node init
        └─► [JOIN] activateOTAA()
              ├─ OK ──► setADR(false) + applyDrSettings() + drProbePending=true
              └─ FAIL ─► loop() reintenta vía ensureJoined()

loop() (cada ciclo)
  ├─ !isActivated() ─► ensureJoined() (re-join) | deepSleep(10 s) si falla
  ├─ drProbePending ─► sendProbeUplink() hasta maxPayload >= 133 B (o 5 intentos)
  ├─ vextSensorOn() → readAmg8833() → vextSensorOff()
  ├─ sendReport() (uplink 133 B + captura downlink)
  └─ deepSleepMillis(SLEEP_INTERVAL_MS)
```

---

## 2. Diagrama de flujo (texto)

```
[RESET / BOOT]
      │
      ▼
┌──────────────────────────┐
│ setup(): Serial 115200    │
│ VEXT=LOW (sensor off)     │
│ radio.begin()             │
│ node.beginOTAA(keys)      │
│ node.scanGuard = 200      │
└────────────┬─────────────┘
             ▼
┌──────────────────────────┐
│ node.activateOTAA()      │
└────────────┬─────────────┘
      JOIN?  │
   ┌────┬────┴────┐
   OK   │        FAIL
   ▼    │         ▼
 applyDrSettings()   (loop reintentará)
 drProbePending=true
   │
   ▼
┌──────────── loop() ────────────┐
│ 1. isActivated()?             │
│    NO → ensureJoined()        │
│         (fallo → sleep 10 s)  │
│ 2. drProbePending?            │
│    SÍ → sendProbeUplink()     │
│ 3. vextSensorOn()             │
│ 4. readAmg8833(therm,pixels)  │
│ 5. vextSensorOff()            │
│ 6. sendReport()               │
│ 7. deepSleepMillis(60000)     │
└───────────────────────────────┘
        │ (TimerEvent_t RTC)
        ▼
   [deep sleep 60 s]
        │ expira
        └────► radio.standby() → vuelve a loop()
```

---

## 3. Explicación por secciones

### 3.1 Cabecera y constantes (líneas 1–80)

Define el banner del sketch, los `#include` y las constantes principales:

- **Pines SX1262** (`Module mod(35, 38, 47, 39)`): `NSS, DIO1, RST, BUSY`, internos del SiP ASR6502.
- **Región**: `Region = AU915`, `subBand = 2`.
- **`SENSOR_PWR_PIN`** = `Vext` (macro de la placa que mapea a `P3_2`).
- **`SLEEP_INTERVAL_MS`** = `60000UL` — intervalo de reporte.
- **`PAYLOAD_LEN`** = 133.
- Registros AMG8833: `PCTL=0x00`, `RESET=0x01` (valor `0x3F`), `FPSC=0x04` (valor `0x05` = 10 fps),
  `THERM=0x0E`, `PIXELS=0x80`.
- Flags de estado: `drProbePending`, `drProbeRetries`.

> ⚠️ **Nota para desarrolladores**: la cabecera (líneas 23–26) aún dice "DR4 (SF8)", pero el código
> real usa **DR5 (SF7)** (`node.setDatarate(5)`). La cabecera está desactualizada; el comportamiento
> correcto y verificado es DR5/SF7.

### 3.2 Low-power nativo (líneas 90–120)

- `TimerEvent_t sleepTimer` + flag volátil `sleepExpired`.
- `onSleepTimerExpired()`: callback del RTC que pone `sleepExpired = true`.
- **`deepSleepMillis(uint32_t ms)`**:
  1. Reinicia el flag y configura el timer RTC.
  2. `radio.sleep()` (radio a bajo consumo).
  3. Bucle `while (!sleepExpired) lowPowerHandler();` → **CySysPmDeepSleep()** hasta la IRQ del RTC.
  4. `TimerStop` y `radio.standby()` al despertar.

### 3.3 Diagnóstico (líneas 122–140)

- Macro `debug(fmt, ...)` → `Serial.printf`.
- **`stateDecode(int16_t)`**: traduce los códigos de RadioLib a texto legible (`OK`, `CHIP_NOT_FOUND`,
  `PACKET_TOO_LONG`, `RX_TIMEOUT`, `MIC_MISMATCH`, `NOT_JOINED`, `NO_JOIN_ACCEPT`, etc.).

### 3.4 Alimentación del sensor — VEXT (líneas 142–154)

- **`vextSensorOn()`**: `pinMode(Vext, OUTPUT)` + `digitalWrite(Vext, HIGH)` + `delay(250)`.
  - El `pinMode` se re-aplica aquí (no se confía en el de `setup()`), porque el core puede
    reconfigurar otros pines tras el deep sleep.
  - `delay(250)`: margen cómodo de *cold-start* del AMG8833 (antes era 20 ms, insuficiente).
- **`vextSensorOff()`**: `Wire.end()` + `digitalWrite(Vext, LOW)`. El `Wire.end()` libera el bus
  I2C antes del deep sleep (resetea el flag de init y reduce fuga en reposo).

> ⚠️ **Polaridad invertida (verificada en campo)**: en el HTCC-AB02A, `HIGH` = sensor **encendido**,
> `LOW` = sensor **apagado**. Esto es lo contrario del pinout oficial ("LOW-ON, HIGH-OFF"). Se
> verificó con escáner I2C: el AMG8833 responde en `0x69` solo con VEXT en `HIGH`.

### 3.5 I2C — lectura del AMG8833 (líneas 156–229)

- **`amgWriteRegAt(addr, reg, val)`**: escritura de 1 byte a un registro. Devuelve `true` si ACK.
- **`amgReadAt(addr, reg, buf, len)`**: escritura del registro + *repeated start* + lectura de `len`
  bytes. Devuelve `0` (OK), `-1` (sin ACK) o `-2` (menos bytes de los esperados).
- **`readAmg8833(therm, pixels)`**:
  1. **`Wire.end()`** → luego `Wire.begin(SDA, SCL, 100000)`.
     - ⚠️ **Fix crítico (bug del core CubeCell)**: tras el deep sleep, `Wire.begin()` NO
       re-inicializa el periférico SCB del I2C porque la variable `I2C_initVar` queda en `1`
       (la SRAM se retiene en deep sleep, pero los registros del SCB se pierden). Sin el
       `Wire.end()` previo, el sensor solo responde en el **1er ciclo tras reset** y falla
       (sin ACK) en todos los ciclos siguientes. `Wire.end()` resetea `I2C_initVar` y obliga
       al siguiente `begin()` a ejecutar `I2C_Init()` completo.
  2. Inicializa probando **0x69 y luego 0x68**: escribe `PCTL=0x00` (modo normal), `RESET=0x3F`
     (*initial reset*) y `FPSC=0x05` (10 fps).
  3. `delay(200)` (espera del primer frame a 10 fps + margen).
  4. Lee termistor (2 B desde `0x0E`).
  5. Lee píxeles en **dos tramos de 64 B** (`0x80` y `0x80+64`) — el buffer I2C del core es de 128 B.
  6. Devuelve `true` si todo correcto.

### 3.6 Batería (líneas 231–239)

- **`readBatteryMv()`**: `getBatteryVoltage()` (API del core CubeCell) en mV.

### 3.7 Uplink y downlink (líneas 241–290)

- **`sendReport(therm, pixels, sensorOk)`**:
  1. `readBatteryMv()`.
  2. Construye `payload[133]`: `[0]=version`, `[1:2]=termistor`, `[3:130]=pixels` (`memcpy`),
     `[131:132]=batt` (big-endian).
  3. `node.sendReceive(payload, 133, 1, downlinkData, &downlinkLen, false, NULL, NULL)`.
     - Puerto **1**, **no confirmado** (`false`).
  4. Si `state == 0` (sin downlink) → OK; si `state > 0` → hay downlink → `handleDownlink()`; si
     `state < 0` → error.
- **`handleDownlink(data, len)`**: v1.0 solo loguea el primer byte (`comando 0x%02X`). Sin acciones.

### 3.8 Uplink sonda para fijar la DR (líneas 292–331)

- **`sendProbeUplink()`**: envía un uplink de 6 bytes (`0x02` + batería + 3 bytes 0) tras el join.
  Este uplink transporta en los **FOpts** el `LinkADRReq` encolado por `setDatarate()`. Al recibir el
  `LinkADRAns` (downlink), el NS aplica la DR y `node.getMaxPayloadLen()` sube a 238 B.

### 3.9 Re-join y configuración de DR (líneas 333–364)

- **`applyDrSettings()`**: `node.setDatarate(5)` (DR5/SF7) y loguea `getMaxPayloadLen()`.
- **`ensureJoined()`**:
  1. Si `node.isActivated()` → `true`.
  2. Si no, `node.activateOTAA()` (re-join).
  3. Si `NEW_SESSION`/`SESSION_RESTORED` → `setADR(false)`, `applyDrSettings()`,
     `drProbePending=true`, `drProbeRetries=0`.
  4. Si falla → `false`.

### 3.10 `setup()` (líneas 367–418)

1. `Serial.begin(115200)` + `delay(3000)`.
2. Banner y credenciales.
3. `pinMode(Vext, OUTPUT)` + `digitalWrite(Vext, LOW)` (sensor apagado).
4. `radio.begin()` (error → bucle infinito).
5. `node.beginOTAA(joinEui, devEui, nwkKey, appKey)`.
6. `node.scanGuard = 200` (workaround de bug de timers en esperas de radio).
7. `node.activateOTAA()` + si OK → `setADR(false)` + `applyDrSettings()` + `drProbePending=true`.

### 3.11 `loop()` (líneas 421–465)

1. Re-join si no hay sesión (con backoff de 10 s si falla).
2. Si `drProbePending` → `sendProbeUplink()`; si `maxPayloadLen >= 133` → `drProbePending=false`;
   si 5 reintentos sin confirmar → se continúa igualmente.
3. `vextSensorOn()` → `readAmg8833()` → `vextSensorOff()`.
4. `sendReport()`.
5. `deepSleepMillis(SLEEP_INTERVAL_MS)`.

---

## 4. API de funciones

| Función | Firma | Propósito |
|---|---|---|
| `deepSleepMillis` | `static void (uint32_t ms)` | Deep sleep real del MCU vía RTC |
| `onSleepTimerExpired` | `static void (void)` | Callback del timer RTC |
| `stateDecode` | `static const char* (int16_t s)` | Traduce códigos RadioLib a texto |
| `vextSensorOn` | `static void (void)` | Enciende el AMG8833 (VEXT HIGH) |
| `vextSensorOff` | `static void (void)` | Apaga el AMG8833 (VEXT LOW) |
| `amgWriteRegAt` | `static bool (uint8_t addr, uint8_t reg, uint8_t val)` | Escribe 1 byte I2C |
| `amgReadAt` | `static int (uint8_t addr, uint8_t reg, uint8_t* buf, uint8_t len)` | Lee `len` bytes I2C |
| `readAmg8833` | `static bool (uint8_t* therm, uint8_t* pixels)` | Inicializa y lee termistor + 64 píxeles |
| `readBatteryMv` | `static uint16_t (void)` | Voltaje de batería en mV |
| `sendReport` | `static int (const uint8_t* therm, const uint8_t* pixels, bool sensorOk)` | Construye y envía el uplink de 133 B |
| `handleDownlink` | `static void (const uint8_t* data, size_t len)` | Procesa downlink (v1.0: log) |
| `sendProbeUplink` | `static void (void)` | Uplink sonda para fijar la DR |
| `applyDrSettings` | `static void (void)` | Fija DR5/SF7 (ADR off) |
| `ensureJoined` | `static bool (void)` | Re-join OTAA si se perdió la sesión |

---

## 5. Guía de modificación y extensión

### 5.1 Cambiar el intervalo de reporte

Edita la constante `SLEEP_INTERVAL_MS` (línea 76):

```cpp
#define SLEEP_INTERVAL_MS    60000UL   /* 60 s entre reportes */
```

### 5.2 Escenario de batería: de 1 min a 15 min

Para pasar de 60 s a **15 minutos** (900 000 ms):

```cpp
#define SLEEP_INTERVAL_MS    900000UL  /* 15 min entre reportes */
```

Consideraciones:

- El temporizador RTC del ASR6502 admite rangos largos sin problema.
- Con 15 min el consumo medio se reduce ~15× (más autonomía).
- La batería y la lectura se mantienen idénticas; solo cambia la cadencia de envío.
- Verifica el *duty cycle* y las políticas del NS si el intervalo fuera menor que 60 s.

### 5.3 Añadir un sensor externo (I2C adicional)

1. Asegúrate de que no colisione con `0x69`/`0x68` (AMG8833).
2. Aliméntalo desde VEXT (si debe apagarse) o VDD (si siempre encendido).
3. En `loop()`, tras `readAmg8833()`, añade la lectura del nuevo sensor.
4. Amplía el `PAYLOAD_LEN` y actualiza `sendReport()` + `decoder.js` para el nuevo campo.
5. Si el payload supera 238 B (DR5/SF7), reduce el intervalo o habilita ADR/sub-banda superior.

### 5.4 Cambiar la región LoRaWAN

Modifica la constante `Region` (línea 48) y, si procede, la sub-banda:

```cpp
const LoRaWANBand_t Region = AU915;   // o EU868, US915, AS923, IN865...
const uint8_t subBand = 2;
```

> Para regiones de 64 canales (US915/AU915) revisa la sub-banda correcta en el gateway.

### 5.5 Cambiar el payload (campos / formato)

1. Edita `sendReport()` para construir el nuevo `payload[]`.
2. Ajusta `PAYLOAD_LEN`.
3. Actualiza el **layout** documentado en el README y en `decoder.js` (`Decode`).
4. Si cambias endianidad o resoluciones, refleja la conversión en `decoder.js` y `thermal_viewer.py`.

### 5.6 Añadir comandos downlink

1. Define un protocolo (p. ej. byte 0 = comando, bytes 1..N = argumentos).
2. En `handleDownlink()`, interpreta `data[0]` y ejecuta acciones (cambiar intervalo, forzar envío,
   reiniciar, etc.).
3. Implementa `Encode(fPort, obj)` en `decoder.js` para construir esos downlinks desde el NS.

### 5.7 Cambiar la dirección I2C del sensor

Si sueldas el puente `Addr` del AMG8833, cambia a `0x68`:

```cpp
#define AMG8833_ADDR         0x68
```

El firmware ya prueba automáticamente `0x69` y `0x68`, por lo que normalmente no hace falta.

---

## 6. Restricciones y notas técnicas

- **Memoria**: payload 133 B estático + buffer downlink de 242 B (`RADIOLIB_LORAWAN_MAX_PAYLOAD_SIZE`).
  Flash estimado < 40 KB, RAM < 5 KB (amplio margen sobre 128 KB/16 KB).
- **Buffer I2C**: el core CubeCell usa ~128 B; por eso los 128 B de píxeles se leen en dos tramos.
- **ADR OFF + DR5 fijo**: necesario para que el payload de 133 B quepa en un solo envío (AU915 DR5
  permite ~238 B). Si se activara ADR, el NS podría bajar la DR y truncar el envío.
- **`scanGuard = 200`**: workaround de un bug de timers que afectaba a las esperas de la radio en el
  proyecto de referencia; conservarlo salvo que verifiques otra cosa.
- **Credenciales**: `credentials.h` nunca se versiona (`.gitignore`). La plantilla
  `credentials.example.h` usa placeholders a cero.
