# Developer Guide — HTCC_AB02A + AMG8833 (v2.1)

Explicación técnica del código fuente (`HTCC_AB02A_AMG8833_Thermal_v2.ino`) para
desarrolladores que quieran entender, modificar o extender el nodo.

Esta guía describe la **v2.1**, que añade telemetría de radio (SF + intervalo +
RSSI) a todo reporte y un tercer comando downlink (`0x03` = consulta RSSI).

---

## 1. Arquitectura general

El firmware sigue un modelo **secuencial con máquina de estados ligera** dentro de
`loop()`, sin RTOS ni interrupciones complejas (salvo el timer de sueño):

```
setup()
  ├─ Serial + identidad + loadConfig()
  ├─ VEXT OFF (sensor apagado)
  ├─ radio.begin()          (si falla -> NVIC_SystemReset)
  ├─ node.beginOTAA(...)    (si falla -> NVIC_SystemReset)
  ├─ node.scanGuard = 200   (workaround de timers)
  ├─ node.activateOTAA()    (join inicial)
  └─ (estado de sesión guardado en el objeto node)

loop()
  ├─ ensureJoined()          si !node.isActivated()
  ├─ sendProbeUplink()       si drProbePending
  ├─ vextSensorOn() -> readAmg8833() -> vextSensorOff()
  ├─ sendReport()            (uplink + posible downlink)
  └─ deepSleepMillis(intervalMin * 60000)
```

### 1.1 Componentes y responsabilidades

| Módulo | Funciones clave | Responsabilidad |
|---|---|---|
| **Config persistida** | `loadConfig()`, `saveConfig()` | SF e intervalo en EEPROM emulada |
| **Radio/LoRaWAN** | `ensureJoined()`, `sendReport()`, `sendProbeUplink()` | Join, uplink, captura de downlink y de RSSI |
| **Downlink** | `handleDownlink()` | Whitelist de comandos 0x01/0x02/0x03 |
| **Sensor** | `vextSensorOn/Off()`, `readAmg8833()` | Alimentación e I2C del AMG8833 |
| **Payload** | `buildPayload()` | Adaptativo 138 B / 16 B (con telemetría) |
| **Low-power** | `deepSleepMillis()` | Deep sleep RTC |
| **Utilidades** | `drFromSf()`, `stateDecode()`, `readBatteryMv()` | Mapeo DR, diagnóstico, batería |

---

## 2. Configuración y constantes relevantes

### 2.1 Pines (ver README §4 para la tabla completa)

```cpp
Module mod(35, 38, 47, 39);   // NSS=P4_3, DIO1=P4_6, RST=P5_7, BUSY=P4_7
SX1262 radio(&mod);

const LoRaWANBand_t Region = AU915;
const uint8_t subBand = 2;
LoRaWANNode node(&radio, &Region, subBand);
```

### 2.2 Constantes de payload y comandos

```cpp
#define PAYLOAD_LEN_FULL     133       /* térmicos (solo SF7) */
#define PAYLOAD_LEN_COMPACT  14        /* térmicos (SF8..SF9) */
#define DL_CMD_SF            0x01      /* downlink: <sf> 7..9 */
#define DL_CMD_INTERVAL      0x02      /* downlink: <min_hi> <min_lo> BE */
#define DL_CMD_QUERY_RSSI    0x03      /* downlink: <0x00> consulta RSSI */

/* Telemetría v2.1 (SIEMPRE en todo payload): SF + intervalo + RSSI */
#define ADDON_SF_IDX_FULL     133     /* completo: SF en [133] */
#define ADDON_INT_IDX_FULL    134     /* completo: intervalo en [134:135] */
#define ADDON_RSSI_IDX_FULL   136     /* completo: RSSI en [136:137] */
#define PAYLOAD_LEN_FULL2     138     /* 133 + 5 (sf + intervalo + rssi) */
#define ADDON_RSSI_IDX_COMPACT 14    /* compacto: RSSI en [14:15] */
#define PAYLOAD_LEN_COMPACT2  16      /* 14 + 2 (rssi) */

#define RSSI_UNAVAILABLE      ((int16_t)0x8000)

#define INTERVAL_MIN_MIN     1
#define INTERVAL_MIN_MAX     1440
#define SF_MIN               7
#define SF_MAX               9
```

> **Nota v2.1**: en el payload **completo**, los 5 bytes de telemetría (SF +
> intervalo 2 B + RSSI 2 B) se añaden al final (índices 133..137). En el
> **compacto**, SF e intervalo ya ocupaban [11] y [12:13] desde v1, así que solo
> se añade el RSSI en [14:15] (total 16 B, sin duplicar SF/intervalo).

### 2.3 Estructura persistida (EEPROM emulada)

```cpp
struct NodeConfig {
    uint8_t  magic0;      // 0xC0 (validez)
    uint8_t  magic1;      // 0xC1 (validez)
    uint8_t  sf;          // 7..9
    uint16_t intervalMin; // 1..1440
};
```

> **Nota**: `sizeof(NodeConfig)` es **6 bytes** (no 5) por el padding de alineación
> del `uint16_t`. Sin efecto funcional: `EEPROM.put`/`get` usan `sizeof`
> consistente.

### 2.4 Estado de RSSI (volátil, v2.1)

```cpp
static int16_t gLastRssi = (int16_t)0x8000;   /* RSSI del último downlink */
```

`gLastRssi` guarda el **RSSI (dBm) del último downlink recibido**. Se inicializa en
`RSSI_UNAVAILABLE` (`0x8000`) y se refresca en `sendReport()` con
`radio.getRSSI()` cada vez que se recibe un downlink. No es persistente (no se
guarda en EEPROM); tras un power-cycle real vuelve a `0x8000`.

---

## 3. Descripción de cada función

### 3.1 Persistencia

#### `loadConfig()`
Lee la estructura desde `CFG_EEPROM_ADDR` (0). Si el `magic` no coincide (primer
arranque o EEPROM vacía), inicializa con los defaults de v1 (`sf=7`,
`intervalMin=1`) y guarda. Después **sanea** el rango: si `sf` o `intervalMin`
están fuera de límites, los corrige a los defaults.

#### `saveConfig()`
Escribe la estructura con `EEPROM.put()` y hace `EEPROM.commit()` (flush a flash).
Se llama inmediatamente tras un comando downlink válido.

### 3.2 Mapeo y DR

#### `drFromSf(uint8_t sf)`
Convierte SF a Data Rate de AU915 (BW125):

| SF | 12 | 11 | 10 | 9 | 8 | 7 |
|---|---|---|---|---|---|---|
| DR | 0 | 1 | 2 | 3 | 4 | 5 |

> Los casos 10..12 se mantienen solo como defensa documental; son inalcanzables
> porque el whitelist y `loadConfig()` limitan a 7..9.

#### `applyDrFromConfig()`
Aplica la DR correspondiente al SF configurado con `node.setDatarate()`, imprimiendo
el `maxPayload` resultante.

#### `requiredPayloadLen()`
Devuelve `138` si `gCfg.sf == 7`, o `16` en caso contrario (longitudes con
telemetría v2.1 incluidas).

### 3.3 Low-power

#### `deepSleepMillis(uint32_t ms)`
- Configura un `TimerEvent_t` (RTC) con la duración indicada.
- Pone la radio en `radio.sleep()`.
- Bucle `while (!sleepExpired) lowPowerHandler();` (deep sleep real).
- Al despertar, `radio.standby()`.
- No retorna hasta completar el periodo.

#### `onSleepTimerExpired()`
ISR del timer RTC; marca `sleepExpired = true`.

### 3.4 Alimentación e I2C del sensor

#### `vextSensorOn()`
`pinMode(Vext, OUTPUT)` + `digitalWrite(Vext, HIGH)` (enciende el sensor, polaridad
invertida) + `delay(250)`.

#### `vextSensorOff()`
`Wire.end()` + `digitalWrite(Vext, LOW)` (apaga el sensor → 0 µA).

#### `amgWriteRegAt(addr, reg, val)` / `amgReadAt(addr, reg, buf, len)`
Helpers I2C de escritura/lectura de registros.

#### `readAmg8833(therm, pixels)`
- Llama a `Wire.end()` antes de `Wire.begin(SDA, SCL, 100000)` (bug del core
  CubeCell: `I2C_initVar` queda retenido en SRAM tras deep sleep).
- Inicializa el sensor: `PCTL=0x00` (normal) → `RESET=0x3F` (initial reset) →
  `FPSC=10fps`. Prueba `0x69` y luego `0x68`.
- Lee termistor (2 B) y píxeles en dos lecturas de 64 B (regs `0x80` y `0xC0`).

### 3.5 Batería

#### `readBatteryMv()`
Devuelve `getBatteryVoltage()` (mV) del core CubeCell.

### 3.6 Payload

#### `buildPayload(payload, therm, pixels, sensorOk)`
Construye el payload adaptativo (devuelve la longitud):

- **Si `gCfg.sf == 7` y `getMaxPayloadLen() >= 138`**: formato **completo 138 B**
  (versión `0x01`/`0x81` + termistor + 128 B de píxeles + batería BE). Añade la
  telemetría v2.1 al final: SF `[133]`, intervalo `[134:135]` (BE) y RSSI
  `[136:137]` (int16 BE, desde `gLastRssi`).
- **En caso contrario**: formato **compacto 16 B**. Calcula MIN/MAX/PROMEDIO de
  los 64 píxeles (máscara 12-bit `0x0FFF`), versión `0x11`/`0x91`, termistor,
  min/max/avg (LE), batería (BE), eco SF `[11]`, eco intervalo `[12:13]` (BE) y
  RSSI `[14:15]` (int16 BE, desde `gLastRssi`).

> La rama completa **no copia** el valor `gLastRssi` si es `RSSI_UNAVAILABLE`
> distinto de cero; simplemente serializa el `uint16_t` de `gLastRssi` en
> big-endian (por eso `0x8000` aparece literal como `80 00` cuando no hay
> downlink).

### 3.7 Uplink y downlink

#### `sendReport(therm, pixels, sensorOk)`
- `buildPayload()` → imprime hex → `node.sendReceive(payload, len, 1, downlinkData, &downlinkLen, false, &evtUp, &evtDown)`.
- Interpreta el retorno:
  - `RADIOLIB_ERR_NONE` → uplink OK sin downlink.
  - `> 0` → downlink recibido → **captura RSSI con `radio.getRSSI()`** antes de
    procesarlo, y luego `handleDownlink()`.
  - `< 0` → error → imprime `stateDecode()`.

> **Importante (I-101, v2.1)**: el RSSI **NO** se lee de `evtDown.power`. En
> RadioLib 7.7.1 `LoRaWANEvent_t.power` contiene `txPowerMax - txPowerSteps*2`
> (una constante ≈ +30 dBm), no el RSSI. El RSSI real se obtiene de la capa PHY
> con `radio.getRSSI()` **antes** de que el radio entre en sleep (es decir, justo
> tras `sendReceive`).

#### `handleDownlink(data, len)`
**Whitelist estricta** (núcleo de la v2/v2.1):

1. `data[0] == DL_CMD_SF` (0x01) y `len >= 2`:
   - Si `sf` en `[7..9]`: `gCfg.sf = sf`, `setADR(false)`, `applyDrFromConfig()`,
     y **guard-check** `getMaxPayloadLen() >= PAYLOAD_LEN_COMPACT` antes de
     `saveConfig()`.
   - Si fuera de rango: ignorado con log.
2. `data[0] == DL_CMD_INTERVAL` (0x02) y `len >= 3`:
   - `minutes = (data[1] << 8) | data[2]` (uint16 BE).
   - Si en `[1..1440]`: `gCfg.intervalMin = minutes` + `saveConfig()`.
3. `data[0] == DL_CMD_QUERY_RSSI` (0x03):
   - **No requiere acción**: el RSSI del downlink que se acaba de recibir ya quedó
     capturado en `gLastRssi` (en `sendReport`). Solo imprime el valor por serial;
     el siguiente uplink lo reportará en el campo RSSI.
4. Cualquier otro comando: ignorado con log `[DL] Comando 0xXX desconocido`.

#### `sendProbeUplink()`
Envía la **sonda de 6 B** (versión `0x02` + batería + SF + intervalo) para que el
NS aplique la DR vía `LinkADRReq/Ans`. También procesa un posible downlink.

### 3.8 Join y control de sesión

#### `ensureJoined()`
Si `node.isActivated()` es falso, ejecuta `node.activateOTAA()`. En éxito:
`setADR(false)`, `setDwellTime(false)`, `applyDrFromConfig()`, y marca
`drProbePending = true`. En fallo devuelve `false` (el `loop` hace backoff de 10 s).

### 3.9 `setup()` y `loop()`

- **`setup()`**: inicializa serial, configuración, radio y nodo. Ante fallo de
  `radio.begin()` o `node.beginOTAA()` ejecuta `NVIC_SystemReset()` (soft-reset
  CMSIS) con `while(true) delay(1)` de respaldo inalcanzable. Luego join inicial.
- **`loop()`**: re-join si es necesario → sonda si pendiente → medición →
  `sendReport()` → deep sleep `intervalMin * 60000` ms.

---

## 4. Diagrama de flujo de la lógica principal

```
              ┌────────────────────────────┐
              │           loop()           │
              └─────────────┬──────────────┘
                            ▼
                 ┌──────────────────────┐
                 │  ¿Sesión activa?     │── no ──► ensureJoined()
                 └──────────┬───────────┘            │
                            │ sí                     │¿éxito?
                            ▼                        ▼ no
                 ┌──────────────────────┐    deepSleep(10s) → return
                 │  ¿drProbePending?    │
                 └──────────┬───────────┘
                            │ sí
                            ▼
                 ┌──────────────────────┐
                 │   sendProbeUplink()  │  (6 B)
                 │  ¿maxPayload >= req? │── sí ──► drProbePending=false
                 │  ¿reintentos >= 5?   │── sí ──► drProbePending=false
                 └──────────┬───────────┘
                            ▼
                 ┌──────────────────────┐
                 │   vextSensorOn()     │
                 │   readAmg8833()      │
                 │   vextSensorOff()    │
                 └──────────┬───────────┘
                            ▼
                  ┌──────────────────────┐
                  │    sendReport()      │
                  │  buildPayload()      │
                  │  sendReceive()       │
                  │    ¿downlink?        │── sí ──► gLastRssi=radio.getRSSI()
                  └──────────┬───────────┘            │
                             ▼                        ▼
                  ┌──────────────────────┐   handleDownlink()  (0x01/0x02/0x03)
                  │ deepSleepMillis(     │
                  │  intervalMin*60000 ) │
                  └──────────────────────┘
                            │
                            └────► (despierta por RTC) ──► loop()
```

---

## 5. Guía de modificación y extensión

### 5.1 Cambiar la región LoRaWAN

En el archivo principal:

```cpp
const LoRaWANBand_t Region = AU915;   // cambiar por p. ej. EU868, US915...
const uint8_t subBand = 2;
```

> Recuerda actualizar el mapeo `drFromSf()` y el rango SF permitido si la nueva
> región tiene otras DR/dwell-time.

### 5.2 Cambiar el rango de SF permitido

```cpp
#define SF_MIN  7
#define SF_MAX  9
```

> **Precaución**: ampliar a SF≥10 en AU915 provoca que el nodo quede sin uplink
> por el dwell time de 400 ms y, al persistirse, "brickea" el nodo (ver I-001).

### 5.3 Cambiar el payload (agregar campos)

Modifica `buildPayload()` y `PAYLOAD_LEN_FULL`/`PAYLOAD_LEN_COMPACT` (y sus
versiones `*2` con telemetría), y actualiza `decoder.js` (función `Decode`) en
consecuencia. Recuerda que:

- El payload completo solo cabe en SF7 (138 B ≈ límite DR5).
- El compacto debe caber en cualquier DR (≤ 59 B en DR0); hoy son 16 B.
- La telemetría v2.1 (SF + intervalo + RSSI) va al final en ambos formatos;
  mantenla si no quieres romper el `decoder.js`.

### 5.4 Agregar un sensor I2C adicional

1. Añade su dirección y registros como constantes.
2. En `loop()`, dentro del bloque encendido del sensor, lee el nuevo sensor con
   helpers tipo `amgReadAt()`.
3. Añade sus bytes al payload en `buildPayload()` y ajusta longitudes.
4. Actualiza el `decoder.js`.

> Ten en cuenta la limitación de SRAM (16 KB) y el presupuesto de `maxPayload`.

### 5.5 Agregar un nuevo comando downlink

1. Define la constante, p. ej. `#define DL_CMD_X 0x04` (0x01..0x03 ya están en uso).
2. Añade una rama en `handleDownlink()` con su validación de rango y persistencia.
3. Añade la generación del comando en `Encode()` de `decoder.js`.
4. Documenta el nuevo comando en README y datasheet.

### 5.6 Persistir otros parámetros

Amplía `struct NodeConfig`, mantén los `magic` al inicio y usa
`EEPROM.put`/`EEPROM.commit()`. Si cambias el layout, actualiza los `magic` para
invalidar datos viejos (o versiona la estructura).

---

## 6. API de funciones (referencia rápida)

| Función | Firma | Retorno | Descripción |
|---|---|---|---|
| `loadConfig` | `void loadConfig(void)` | — | Carga y sanea config de EEPROM |
| `saveConfig` | `void saveConfig(void)` | — | Persiste config en EEPROM |
| `drFromSf` | `uint8_t drFromSf(uint8_t sf)` | DR | SF → Data Rate AU915 |
| `applyDrFromConfig` | `void applyDrFromConfig(void)` | — | Aplica DR según config |
| `requiredPayloadLen` | `size_t requiredPayloadLen(void)` | bytes | 138 (SF7) / 16 (SF>7) |
| `deepSleepMillis` | `void deepSleepMillis(uint32_t ms)` | — | Deep sleep RTC |
| `onSleepTimerExpired` | `void onSleepTimerExpired(void)` | — | ISR timer RTC |
| `vextSensorOn` | `void vextSensorOn(void)` | — | Enciende sensor (VEXT HIGH) |
| `vextSensorOff` | `void vextSensorOff(void)` | — | Apaga sensor (VEXT LOW) |
| `amgWriteRegAt` | `bool amgWriteRegAt(uint8_t, uint8_t, uint8_t)` | ack | Escribe registro I2C |
| `amgReadAt` | `int amgReadAt(uint8_t, uint8_t, uint8_t*, uint8_t)` | 0/−1/−2 | Lee registro I2C |
| `readAmg8833` | `bool readAmg8833(uint8_t*, uint8_t*)` | ok | Init + lectura termistor/píxeles |
| `readBatteryMv` | `uint16_t readBatteryMv(void)` | mV | Voltaje de batería |
| `buildPayload` | `size_t buildPayload(uint8_t*, const uint8_t*, const uint8_t*, bool)` | bytes | Payload adaptativo (138/16 B) |
| `sendReport` | `int sendReport(const uint8_t*, const uint8_t*, bool)` | estado | Uplink + captura downlink y RSSI |
| `handleDownlink` | `void handleDownlink(const uint8_t*, size_t)` | — | Whitelist comandos (0x01/0x02/0x03) |
| `sendProbeUplink` | `void sendProbeUplink(void)` | — | Sonda DR tras join |
| `ensureJoined` | `bool ensureJoined(void)` | ok | Re-join OTAA |
| `stateDecode` | `const char* stateDecode(int16_t)` | texto | Decodifica estado RadioLib |

---

## 7. Notas técnicas y limitaciones conocidas

- **`scanGuard = 200`**: workaround de un bug de timers del core CubeCell que
  afecta a las esperas de radio.
- **`Wire.end()` antes de `Wire.begin()`**: obligatorio tras deep sleep por un bug
  del core (flag `I2C_initVar` retenido en SRAM). No lo elimines.
- **ADR OFF**: el nodo controla la DR explícitamente; el NS no adapta la DR.
- **DevNonce = 0 tras power-cycle real**: no hay persistencia de `DevNonce`/sesión
  no volátil. Tras un corte de alimentación (no deep sleep) el nodo re-joinea con
  `DevNonce = 0`. Verificado en campo (v1); depende de que el NS lo acepte.
- **`handleDownlink` sin filtro de fPort**: la sobrecarga de `sendReceive` usada no
  expone el fPort del downlink; la defensa es el whitelist por byte de comando.
- **RSSI (I-101, v2.1)**: el RSSI se lee con `radio.getRSSI()` **inmediatamente
  después** de un `sendReceive` que devuelve downlink, y **antes** de que el radio
  entre en sleep. No usar `evtDown.power`: en RadioLib 7.7.1 contiene
  `txPowerMax - txPowerSteps*2 ≈ +30 dBm`, no el RSSI. Si no se captura a tiempo,
  `radio.getRSSI()` devuelve 0 (el SX1262 pierde el RSSI del último paquete al
  dormir).
- **Comentarios residuales "7..12"**: quedan restos documentales en comentarios del
  firmware (sin efecto funcional, la lógica está limitada a 7..9 por
  `SF_MIN`/`SF_MAX`). Se recomienda alinearlos en una futura pasada de limpieza.
