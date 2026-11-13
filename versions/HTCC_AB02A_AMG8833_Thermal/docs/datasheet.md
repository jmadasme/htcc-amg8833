# Datasheet — Nodo LoRaWAN + Termocámara AMG8833

> **Documentación de usuario** · Heltec CubeCell HTCC-AB02A · AMG8833 (8×8) · AU915 SB2 · Clase A

---

## 1. Descripción general

El dispositivo es un **sensor térmico remoto autónomo** que:

1. Despierta cada **60 segundos** desde *deep sleep*.
2. Enciende una **termocámara AMG8833** (matriz infrarroja de 8×8 = 64 píxeles).
3. Lee la temperatura de los 64 píxeles y del termistor interno.
4. Apaga el sensor (consumo 0 µA) y envía los datos por **LoRaWAN** (fPort 1, 133 bytes).
5. Vuelve a dormir.

El objetivo es **monitorizar temperaturas superficiales a distancia** (detección de puntos
calientes, presencia, control de procesos) con **autonomía de años** sobre una pila de litio.

---

## 2. Especificaciones técnicas

### Placa

| Parámetro | Valor |
|---|---|
| Modelo | Heltec CubeCell HTCC-AB02A |
| MCU | ASR6502 — ARM Cortex-M0+ @ 48 MHz |
| Radio | SX1262 integrada (SiP) |
| RAM | 16 KB |
| Flash | 128 KB |
| Alimentación | 3.3 V (USB o pila ER14250) |
| Interfaz | USB Micro (CP2102) + antena SMA |
| Deep sleep | ~3.5 µA |

### Sensor AMG8833

| Parámetro | Valor |
|---|---|
| Fabricante | Panasonic |
| Tipo | Matriz infrarroja (termopila) 8×8 = 64 píxeles |
| Interfaz | I2C |
| Dirección | `0x69` (0x68 si se suelda el puente `Addr`) |
| Rango de medida | 0–80 °C (por píxel, típico) |
| Registro termistor | `0x0E` (2 bytes, 12-bit con signo) |
| Registros píxeles | `0x80–0xFF` (128 bytes, 64 × 12-bit con signo) |
| Resolución termistor | 0.0625 °C/LSB |
| Resolución píxeles | 0.25 °C/LSB |
| Frame rate configurado | 10 fps |

### Radio LoRaWAN

| Parámetro | Valor |
|---|---|
| Región | AU915, sub-banda 2 |
| Activación | OTAA, Clase A |
| Stack | RadioLib 7.7.1 |
| Puerto | 1 |
| Confirmación | Unconfirmed |
| ADR | OFF (DR5/SF7 fijo) |
| Intervalo de reporte | 60 s |
| Tamaño de payload | 133 bytes |

### Batería

| Parámetro | Valor |
|---|---|
| Química | Litio Li-SOCl₂ (no recargable) |
| Modelo | ER14250 / LS14250 (1/2AA) |
| Voltaje nominal | 3.6 V |
| Capacidad | 1200 mAh |
| Carga | ⚠️ **NO recargable** — la placa no carga |

---

## 3. Cableado

| AMG8833 | CubeCell | Descripción |
|---|---|---|
| `VIN` | `VEXT` (`P3_2`) | Alimentación conmutada (HIGH=ON / LOW=OFF) |
| `GND` | `GND` | Masa común |
| `SCL` | `SCL0` (`P0_0`, pin 39) | Reloj I2C |
| `SDA` | `SDA0` (`P0_1`, pin 40) | Datos I2C |

> El AMG8833 trae pull-ups onboard en SDA/SCL: **no** se añaden resistencias externas.

---

## 4. Operación

### Encendido y primer arranque

1. Inserta la pila `ER14250` respetando la **polaridad** (o conecta el cable USB).
2. La placa conmuta automáticamente entre USB y batería.
3. Al arrancar, el nodo hace el **join OTAA** automático.
4. Cada 60 s mide y envía.

### Indicadores por monitor serie (115200 baudios)

| Etiqueta | Significado |
|---|---|
| `[INIT]` | Banner de arranque y credenciales |
| `[JOIN] +++ JOINED +++` | Join OTAA correcto |
| `[AMG] OK therm=... pixels[0]=...` | Lectura del sensor correcta |
| `[AMG] init FAIL ...` | El sensor no responde (ver solución de problemas) |
| `[BATT] xxxx mV` | Voltaje de batería |
| `[UPLINK] port=1 payload=...` | Envío del reporte |
| `[SLEEP] Durmiendo 60000 ms...` | Entrada en deep sleep |
| `[RX] ...` | Downlink recibido (v1.0: solo log) |

### Verificación en el gateway (Milesight UG56)

En **Network Server → Incoming Packets** deben aparecer **uplinks de 133 bytes** en el puerto 1,
con el DevEUI `70B3D56F27CEE98B`, cada ~60 segundos.

---

## 5. Mantenimiento de la pila

- La pila Li-SOCl₂ `ER14250` es **de un solo uso**. No intentes recargarla.
- Sustitución: apaga el nodo, retira la pila agotada, inserta una nueva **respetando la polaridad**.
- El `battery_percent` del decoder es una estimación basada en voltaje. En esta química el voltaje
  se mantiene plano y cae al final; **no es un indicador lineal** de carga.
- Vida útil típica: meses–años, en función del intervalo de reporte y de la calidad del enlace.

---

## 6. Solución de problemas

| Síntoma | Causa probable | Solución |
|---|---|---|
| `sensor_ok = false` / `version = 0x81` | Fallo de lectura I2C (sensor no responde) | Revisar cableado VIN→VEXT, SDA/SCL, polaridad de VEXT, dirección I2C (0x69/0x68) |
| `[AMG] init FAIL (sin ACK en 0x69/0x68)` | Sensor sin alimentación o mal conectado | Verificar que VEXT entrega 3.3 V con `HIGH`; comprobar continuidad de SDA/SCL |
| **Sensor lee OK solo en el 1er ciclo y falla los siguientes** | Bug del core CubeCell: I2C no se re-inicializa tras el deep sleep (`I2C_initVar` queda en 1) | Ya corregido en firmware con `Wire.end()` antes de `Wire.begin()` en cada lectura. Si persiste, asegurar que se usa el `.ino` actualizado |
| `[JOIN] Fallo: ... NO_JOIN_ACCEPT` | Credenciales incorrectas o gateway sin sub-banda 2 | Verificar DevEUI/JoinEUI/AppKey en `credentials.h` y en el NS; habilitar AU915 SB2 en el UG56 |
| `"Never activated"` / `NOT_JOINED` | Sesión no establecida o perdida | El nodo re-intenta el join automáticamente (`ensureJoined()`); comprobar cobertura y credenciales. Al recrear el dispositivo en el NS, reiniciar la placa para re-hacer el join |
| No aparecen uplinks en el gateway | Sub-banda incorrecta, frecuencia, o antena | Confirmar AU915 SB2 en el gateway y antena SMA conectada |
| Downlink no llega | v1.0 sin comandos; o ventana Clase A desfasada | Esperado en v1.0 (solo se loguea). No se requiere respuesta |
| Consumo alto en reposo | VEXT no apagando el sensor o placa en standby | Verificar que VEXT quede en `LOW` (sensor apagado) antes de dormir |
| Lecturas de temperatura irreales | Lente sucia/obstruida o resolución mal aplicada | Limpiar lente; verificar conversión (termistor ×0.0625, píxeles ×0.25) |

### Error de join −1116 (nativo CubeCell)

Si se usa el stack nativo de CubeCell (no RadioLib), `−1116` suele corresponder a un **timeout del
join** (sin respuesta `JoinAccept` del NS). Causas habituales: sub-banda incorrecta, gateway fuera de
alcance, o credenciales erróneas. Este proyecto usa **RadioLib 7.7.1**, cuyos códigos se muestran
con `stateDecode()` (`NO_JOIN_ACCEPT`, `RX_TIMEOUT`, etc.).

---

## 7. Compatibilidad con otras placas

| Placa | ¿Compatible? | Notas |
|---|---|---|
| Heltec CubeCell HTCC-AB01 | Parcial | Mismo MCU/radio, pero distinto pinout (tiene OLED en I2C0). Verificar VEXT y SDA/SCL |
| Heltec CubeCell HTCC-AB02S | Parcial | Similar; revisar pads I2C y VEXT |
| LilyGO T-Beam (v1.1) | Adaptación | MCU ESP32 + SX1276/SX1262. Requiere re-mapeo de pines y otro BSP; misma lógica LoRaWAN |
| Heltec WiFi LoRa 32 (V2/V3) | Adaptación | ESP32 + SX1276/SX1262. Sin pad VEXT equivalente directo → usar GPIO + MOSFET P |
| Cualquier placa + SX1262 (RadioLib) | Adaptación | Reutilizable cambiando `Module`, pines VEXT/SDA/SCL y región |

> El firmware es modular: la lógica de lectura del AMG8833, el ciclo de reporte y el payload son
> independientes del *backend* de radio, por lo que migrar a otra placa RadioLib es directo.

---

## 8. Referencias

- Manual Heltec CubeCell HTCC-AB02A (pinout, esquema).
- Datasheet Panasonic AMG8833 (registros, protocolo I2C).
- RadioLib 7.7.1 (API LoRaWANNode / SX1262).
- Milesight UG56 — guía de configuración del Network Server embebido y Payload Codec.

> Para detalles técnicos del código, ver [`developer.md`](developer.md).
