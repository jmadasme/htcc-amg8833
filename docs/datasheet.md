# Datasheet — HTCC_AB02A + AMG8833 Nodo LoRaWAN (v2.1)

Documentación de usuario detallada del nodo termográfico LoRaWAN basado en
Heltec CubeCell HTCC-AB02A con control remoto por downlink.

---

## 1. Descripción general

El dispositivo es un **termógrafo de bajo consumo** que mide la temperatura de un
plano mediante una matriz termopila **AMG8833 (8×8 = 64 píxeles)** y reporta los
resultados a un gateway LoRaWAN **Milesight UG56** (con Network Server embebido).

Está diseñado para instalaciones alimentadas por **una sola pila de litio
Li-SOCl₂ 14250 (1/2AA, 3.6 V)** durante largos periodos, gracias al **deep sleep
real** del MCU y a la **desenergización total del sensor** entre mediciones.

### 1.1 Características clave

- Medición térmica de 64 píxeles + termistor interno (temperatura de placa).
- Uplink LoRaWAN **Clase A, OTAA, AU915 sub-banda 2, puerto 1**.
- **Control remoto por downlink**: cambio de SF (7..9), de ciclo de reporte
  (1..1440 min) y **consulta de RSSI** (comando `0x03`), ambos parámetros de
  configuración **persistidos en EEPROM**.
- **Telemetría de enlace (v2.1)**: cada uplink incluye **SF actual, intervalo
  (min) y RSSI del último downlink** (`0x8000` = no disponible).
- **Payload adaptativo**: 138 B (imagen completa + telemetría) en SF7; 16 B
  compacto (MIN/MAX/PROMEDIO + telemetría) en SF8/SF9.
- Deep sleep real por RTC (`lowPowerHandler()`), consumo ~0 µA del sensor en
  reposo.
- Re-join automático y *soft-reset* (`NVIC_SystemReset`) ante fallos de init.

### 1.2 Aplicaciones típicas

- Monitorización de temperatura de equipos, cuadros eléctricos o superficies.
- Detección de presencia/cambio térmico en una zona (sin imagen completa).
- Registro remoto de perfil térmico en ubicaciones sin alimentación de red.

---

## 2. Especificaciones técnicas

### 2.1 Placa (Heltec CubeCell HTCC-AB02A)

| Parámetro | Valor |
|---|---|
| Modelo | HTCC-AB02A ("CubeCell 1/2AA Node") |
| MCU | ASR6502 (SiP) — ARM Cortex-M0+ |
| Radio | SX1262 (integrada en el SiP) |
| Bandas soportadas | LoRa 470–510 / 863–928 MHz (AU915 en este proyecto) |
| SRAM | 16 KB (retenida en deep sleep) |
| Flash | 128 KB (EEPROM emulada para persistencia) |
| Interfaz PC | CP210x USB-UART |
| Alimentación | Pila 1/2AA (Li-SOCl₂ 14250, 3.6 V nominal) |
| Core Arduino | CubeCell 1.4.0 |
| FQBN | `CubeCell:CubeCell:CubeCell_AB02A` |

### 2.2 Radio y LoRaWAN

| Parámetro | Valor |
|---|---|
| Stack | RadioLib 7.7.1 |
| Región / sub-banda | AU915 / sub-banda 2 |
| Activación | OTAA |
| Clase | A |
| Puerto | 1 (uplink y downlink) |
| Confirmación | Unconfirmed |
| ADR | OFF (control explícito de DR) |
| SF admitido (downlink) | 7..9 (DR5..DR3) |
| Dwell time AU915 | 400 ms (motivo del límite SF≤9) |

### 2.3 Sensor AMG8833

| Parámetro | Valor |
|---|---|
| Modelo | Panasonic Grid-EYE AMG8833 |
| Resolución | 8×8 = 64 píxeles |
| Rango de temperatura | −20 a +100 °C (objetos) |
| Precisión | ±2.5 °C (típica) |
| Interface | I2C (Fast mode 100 kHz) |
| Dirección | `0x69` (default) / `0x68` (puente ADDR soldado) |
| Termistor interno | reg `0x0E`, 12-bit signed, 0.0625 °C/LSB |
| Píxeles | reg `0x80`–`0xFF`, 12-bit signed, 0.25 °C/LSB |
| Frame rate configurado | 10 fps |

### 2.4 Consumo y autonomía

| Estado | Consumo |
|---|---|
| Reposo (deep sleep + sensor OFF) | Mínimo (solo RTC + retención SRAM) |
| Medición (sensor ON ~450 ms) | Pico breve (I2C + sensor activo) |
| Uplink (TX LoRa) | Pico de corriente de transmisión |

La autonomía depende del intervalo configurado; intervalos largos (p. ej. 5–15
min) maximizan la vida de la pila.

---

## 3. Configuración LoRaWAN

### 3.1 Credenciales OTAA

Las credenciales reales están en `credentials.h` (no versionado). Campos:

| Campo | Tipo | RadioLib |
|---|---|---|
| DevEUI | uint64 (big-endian) | `devEui` |
| JoinEUI / AppEUI | uint64 (big-endian) | `joinEui` |
| AppKey | 16 bytes (big-endian) | `appKey[]` |
| NwkKey | 16 bytes (big-endian) | `nwkKey[]` |

> Para crear tu archivo, copia `credentials.example.h` → `credentials.h` y rellena
> los valores. **No versiones `credentials.h`.**

### 3.2 Registro en Milesight UG56 (NS embebido)

1. Entra a la web de administración del UG56.
2. **Network Server → Devices → Add**.
3. Selecciona **OTAA** (Clase A).
4. Rellena DevEUI, JoinEUI y AppKey (coinciden con `credentials.h`).
5. Región **AU915**, sub-banda **2**.
6. Pega el **Payload Codec** (`decoder.js`) en el campo correspondiente.
7. Guarda. El join se produce cuando el nodo arranca.

### 3.3 Registro en otros Network Servers

El proyecto también funciona con otros NS compatibles (TTN/The Things Stack,
ChirpStack, Helium — respetando la región y sub-banda):

- **TTN (The Things Stack)**: crea una aplicación y un dispositivo OTAA; pega el
  `decoder.js` adaptado al formato de TTS (devuelve `{data, errors}` si el
  codec lo requiere) y configura la región **AU915**.
- **ChirpStack v3/v4**: formato de codec igual que Milesight (objeto directo en
  `Decode`, array en `Encode`).
- **Helium**: usa un *Console* con integración de decodificador equivalente.

> Consulta §7.4 para las equivalencias de código del decodificador.

---

## 4. Guía de usuario

### 4.1 Instalación física

1. Fija el módulo AMG8833 con SDA/SCL/GND/VDD conectados según el pinout.
2. Inserta la pila **14250** respetando la polaridad del portapilas.
3. Para depuración, conecta USB y abre el monitor a 115200 baud.

### 4.2 Operación diaria

- El nodo **no requiere interacción local**: mide, envía y duerme.
- Para cambiar el comportamiento, usa los **comandos downlink** (§5).
- Para comprobar la configuración activa, mira la línea `[CFG] EEPROM: sf=… interval=… min` tras un reset, o los `[DL] …` al recibir comandos.

### 4.3 Lectura de los datos

En el NS, cada uplink se decodifica a JSON. Ejemplo (payload completo):

```json
{
  "kind": "full",
  "version": 1,
  "sensor_ok": true,
  "thermistor_C": 26.06,
  "pixels_C": [25.0, 25.25, ..., 30.5],
  "pixel_min_C": 24.0,
  "pixel_max_C": 31.75,
  "battery_mV": 3580,
  "battery_V": 3.58,
  "battery_percent": 85,
  "sf": 7,
  "interval_min": 1,
  "rssi_dBm": -68
}
```

Ejemplo (payload compacto):

```json
{
  "kind": "compact",
  "version": 17,
  "sensor_ok": true,
  "thermistor_C": 26.06,
  "pixel_min_C": 24.0,
  "pixel_max_C": 31.75,
  "pixel_avg_C": 27.5,
  "battery_mV": 3580,
  "battery_V": 3.58,
  "battery_percent": 85,
  "sf": 8,
  "interval_min": 5,
  "rssi_dBm": -70
}
```

> **Telemetría v2.1**: `sf`, `interval_min` y `rssi_dBm` viajan en **todos** los
> uplinks. Si el nodo aún no ha recibido ningún downlink, `rssi_dBm` vale `null`
> (el payload lleva `0x8000`). El campo `rssi_dBm` es el **RSSI del último
> downlink recibido por el nodo** (no confundir con el `rssi` del gateway que
> también añade `addRadioInfo`).

### 4.4 Formato de payload (resumen v2.1)

Tres formatos según el contexto. Consulta el **README §8** para el detalle byte a
byte con endianidad de cada campo.

| Formato | Tamaño | Cuándo se envía | Contenido |
|---|---|---|---|
| **Completo** | 138 B | Solo SF7 (DR5) | Versión + termistor + 64 píxeles + batería + **SF + intervalo + RSSI** |
| **Compacto** | 16 B | SF8 / SF9 (DR4/DR3) | Versión + termistor + MIN/MAX/PROM + batería + **SF + intervalo + RSSI** |
| **Sonda** | 6 B | Tras el join | Versión `0x02` + batería + SF + intervalo |

Campos de telemetría (presentes en completo y compacto):

| Campo | Bytes | Formato |
|---|---|---|
| SF actual | 1 | uint8 (7..9) |
| Intervalo | 2 | uint16 **big-endian** (minutos) |
| RSSI | 2 | int16 **big-endian** (dBm); `0x8000` = no disponible |

> **Nota sobre RSSI**: el nodo lee el RSSI con `radio.getRSSI()` al recibir un
> downlink (valor **negativo** en dBm). Si no ha habido downlink previo, el campo
> vale `0x8000` (−32768) y el decodificador lo expone como `rssi_dBm: null`.

### 4.5 Conversión de temperatura

| Registro | Resolución |
|---|---|
| Termistor (0x0E) | `T_C = valor12bit × 0.0625 °C` |
| Píxeles (0x80–0xFF) | `T_C = valor12bit × 0.25 °C` |

---

## 5. Comandos downlink (guía rápida)

| Objetivo | JSON (Encode) | Bytes hex |
|---|---|---|
| SF a 7 | `{ "set_sf": 7 }` | `01 07` |
| SF a 8 | `{ "set_sf": 8 }` | `01 08` |
| SF a 9 | `{ "set_sf": 9 }` | `01 09` |
| Intervalo 5 min | `{ "interval_min": 5 }` | `02 00 05` |
| Intervalo 60 min | `{ "interval_min": 60 }` | `02 00 3C` |
| Intervalo 24 h | `{ "interval_min": 1440 }` | `02 05 A0` |
| Consulta RSSI | `{ "query_rssi": true }` | `03 00` |
| SF 7 + 60 min | `{ "set_sf": 7, "interval_min": 60 }` | `01 07 02 00 3C` |

> El intervalo se codifica como **uint16 big-endian**. Rango: 1–1440 minutos.
>
> El comando `query_rssi` (v2.1) no modifica configuración: pide al nodo reportar
> el RSSI del último downlink en el próximo uplink. Como la v2.1 ya envía RSSI en
> cada reporte, es una confirmación explícita bajo demanda.

---

## 6. Solución de problemas comunes

| Síntoma | Causa probable | Solución |
|---|---|---|
| `[JOIN] Fallo: -1116 (NO_JOIN_ACCEPT)` | Credenciales mal registradas o sub-banda incorrecta | Verifica DevEUI/JoinEUI/AppKey en el NS; asegura AU915 **sub-banda 2** en gateway y NS |
| No hay uplink en el NS | El nodo duerme largo tiempo o sub-banda no coincide | Revisa intervalo configurado; verifica sub-banda del gateway |
| Downlink no llega / no se aplica | Clase A: downlink solo tras uplink; o intervalo muy largo | Envía el comando justo tras un uplink; reduce el intervalo temporalmente |
| `[DL] SF X fuera de rango (7..9); ignorado` | Se intentó SF≥10 (prohibido por dwell time) | Usa solo SF 7..9 |
| `[DL] SF X sin uplink ... NO persistido` | El `maxPayload` resultante es insuficiente | No fuerces SF≥10; mantén 7..9 |
| `[AMG] init FAIL (sin ACK en 0x69/0x68)` | Cableado I2C o VEXT apagado | Revisa SDA/SCL; confirma que VEXT se activa (HIGH=ON) |
| `[INIT] Radio FAILED ... Auto-reset` | Radio no responde | Revisa alimentación; el nodo se reinicia solo |
| Lectura con valores extraños | Píxeles con signo mal interpretado | Usa el `decoder.js` oficial (aplica `sign12`) |
| Pila se agota rápido | Sensor siempre encendido (VEXT invertido) | Confirma `LOW=OFF` en reposo |
| Tras corte de luz, NS rechaza join | DevNonce reutilizado (sin persistencia) | Asegura que el NS acepte DevNonce reutilizado (comportamiento v1) |
| `rssi_dBm` = null en todos los uplinks | El nodo aún no ha recibido ningún downlink | Es normal hasta el primer downlink; envía `{ "query_rssi": true }` (`03 00`) tras un uplink |
| `rssi_dBm` positivo (~+30) en vez de negativo | Firmware anterior usaba `evtDown.power` (bug I-101) | Regraba el firmware v2.1 (usa `radio.getRSSI()`) |

### Código de error de join −1116

`RADIOLIB_ERR_NO_JOIN_ACCEPT` (−1116) indica que el **join request** llegó al
gateway pero el NS **no emitió el join accept**. Causas más frecuentes:

1. DevEUI/JoinEUI/AppKey no coinciden entre `credentials.h` y el NS.
2. Sub-banda del gateway distinta a la del nodo.
3. El NS requiere configurar explícitamente la región/frecuencias.

---

## 7. Compatibilidad y equivalencias

### 7.1 Tabla de compatibilidad con otras placas LoRaWAN

| Placa | Radio | MCU | ¿Compatible con este firmware? | Notas |
|---|---|---|---|---|
| Heltec CubeCell HTCC-AB02A | SX1262 (SiP) | ASR6502 | ✅ Objetivo | |
| Heltec CubeCell AB01/AB02 (sin AA) | SX1262 (SiP) | ASR650x | ✅ (ajustar pinout VEXT) | Mismo core CubeCell |
| Heltec CubeCell HTCC-AB02S | SX1262 | ASR6502 | ✅ (mismo SiP) | Distinta antena/forma |
| Heltec Wireless Stick Lite | SX1276 | ESP32 | ⚠️ Parcial | Requiere re-mapeo de pines y SX127x |
| Heltec WiFi LoRa 32 (V2/V3) | SX127x | ESP32 | ⚠️ Parcial | ESP32 (no low-power igual) |
| LilyGO T-Beam (v1.x) | SX1276 | ESP32 | ⚠️ Parcial | GPS incluido, SX127x |
| LilyGO T-Beam Supreme | SX1262 | ESP32-S3 | ⚠️ Parcial | SX1262 sí, pero MCU distinto |
| RAK3172 / RAK4631 | SX1262 | nRF52/STM32 | ❌ (re-escritura) | Otra plataforma/stack |

> Este firmware está ligado al **core CubeCell** (API `Vext`, `getBatteryVoltage()`,
> `lowPowerHandler()`, `TimerEvent_t`, `EEPROM` estilo ESP8266). Portar a otras
> familias exige adaptar esos servicios.

### 7.2 Equivalencia de APIs del core CubeCell

| Servicio | API usada |
|---|---|
| Alimentación sensor | `Vext` (pin P3_2) |
| Voltaje de batería | `getBatteryVoltage()` (mV) |
| Deep sleep | `TimerEvent_t` + `lowPowerHandler()` |
| Reset por soft | `NVIC_SystemReset()` (CMSIS) |
| EEPROM | `EEPROM.begin/put/get/commit()` (API ESP8266) |

### 7.3 Librerías requeridas

| Librería | Versión | Instalación |
|---|---|---|
| **RadioLib** | 7.7.1 | `arduino-cli lib install RadioLib` (o `~/Arduino/libraries/RadioLib`) |
| Wire | core | Incluida en el core CubeCell |
| EEPROM | core | Incluida en el core CubeCell (API ESP8266) |

Instalación del core CubeCell (si no está):

```bash
arduino-cli config add board_manager.additional_urls \
  https://github.com/HelTecAutomation/CubeCell-Arduino/releases/download/V1.4.0/package_CubeCell_index.json
arduino-cli core update-index
arduino-cli core install CubeCell
```

### 7.4 Formato del Payload Codec según NS

| NS | `Decode` devuelve | `Encode` recibe/devuelve |
|---|---|---|
| Milesight UG56 | objeto JSON directo | `(fPort, obj)` → array de bytes |
| ChirpStack v3/v4 | objeto JSON directo | `(fPort, obj)` → array de bytes |
| TTN/TTS v3 | `{ data: {...}, errors: [...] }` | `(input)` con `input.data` |
| Helium Console | objeto JSON directo | similar a ChirpStack |

> El `decoder.js` de este proyecto sigue el formato **Milesight/ChirpStack v3**.
> Para TTN/TTS, envuelve el objeto en `{ data: decoded }` y ajusta `Encode`.

---

## 8. Notas de seguridad y mantenimiento

- **No manipules la pila con el nodo conectado a USB** si hay riesgo de
  cortocircuito (el portapilas 1/2AA es compacto).
- **Reemplazo de pila**: al retirar la pila, la SRAM se pierde; el nodo
  re-joinea al volver a encender (DevNonce=0).
- **Recuperación de un nodo "bloqueado"**: si por error se persiste una
  configuración inválida, reflashea el firmware; el código ya limita SF a 7..9
  para evitarlo.
- **Firmware de referencia**: no modifiques la secuencia `Wire.end()` antes de
  `Wire.begin()` (mitiga un bug del core CubeCell tras deep sleep).

---

## 9. Interpretación de paquetes (telemetría v2.1)

Cada uplink incluye al final **tres campos de telemetría** que permiten diagnosticar
el enlace sin tocar el firmware:

| Campo JSON | Significado | Ejemplo |
|---|---|---|
| `sf` | Spreading Factor actual (7..9) | `7` |
| `interval_min` | Ciclo de reporte en minutos (1..1440) | `1` |
| `rssi_dBm` | RSSI que el **nodo** midió del último downlink (dBm negativo); `null` si aún no hubo downlink | `-20` |

### 9.1 Los dos RSSI (importante)

| Campo | Quién mide | Significado |
|---|---|---|
| `rssi` | El **gateway** | Señal con la que el UG56 recibió al nodo. Siempre presente. |
| `rssi_dBm` | El **nodo** | Señal con la que el nodo recibió el último downlink. `null` hasta el primer downlink. |

### 9.2 Ejemplo real en producción

Uplink completo (SF7, 138 B) capturado del gateway, **tras** enviar `03 00`:

```json
{
  "kind": "full",
  "sf": 7,
  "interval_min": 1,
  "rssi_dBm": -20,   // el nodo "oye" al gateway con -20 dBm (excelente)
  "battery_mV": 3328,
  "thermistor_C": 22.44,
  "pixel_min_C": 15.5,
  "pixel_max_C": 20.25,
  "rssi": -44,        // el gateway "oye" al nodo con -44 dBm
  "snr": 10.0
}
```

> Un `rssi_dBm` de `-20 dBm` indica un enlace extraordinariamente fuerte (nodo muy
> cerca del gateway). Valores típicos en campo van de `-70` a `-110 dBm`.

Para el desglose **byte a byte** completo (uplink de 138/16/6 bytes, secuencia de
eventos y más ejemplos reales), consulta el documento
**`INTERPRETACION_PAQUETES.md`** en la raíz del proyecto.
