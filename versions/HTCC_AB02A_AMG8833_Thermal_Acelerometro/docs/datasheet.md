# Datasheet — Nodo LoRaWAN HTCC-AB02A + Termocámara AMG8833 + Acelerómetro ADXL335 (v2.0)

> **Documentación de usuario final**
>
> Dispositivo de telemetría LoRaWAN de bajo consumo que combina una termocámara infrarroja de 8×8 píxeles y un acelerómetro con clasificación de movimiento, alimentado por una pila no recargable.

---

## 1. Descripción general

El nodo **HTCC-AB02A + AMG8833 + ADXL335** es un sensor autónomo que:

- Captura una **imagen térmica de 8×8 píxeles** (64 puntos de temperatura) mediante el sensor **AMG8833**.
- Mide el **movimiento/vibración** con un acelerómetro **ADXL335** (eje X) y lo **clasifica** en 4 niveles: reposo, baja, media y alta.
- Reporta todos los datos por **LoRaWAN** (AU915, clase A) cada **60 segundos** a un gateway **Milesight UG56**.
- Permanece en **deep sleep** entre reportes, desenergizando ambos sensores (**0 µA**) para maximizar la vida de la pila.

### Versión

- **v2.0**: añade el acelerómetro al nodo de termografía v1.0 ya verificado.

### Estado actual

| Elemento | Estado |
|---|---|
| Firmware v2.0 | ✅ Grabado y transmitiendo |
| Termocámara AMG8833 | ✅ Cableada y funcionando |
| Acelerómetro ADXL335 | ⏸️ No cableado (en decisión de diseño) |
| Periodo de reporte | 60 s (previsto alargar a 3 h) |

---

## 2. Especificaciones técnicas

### 2.1 Placa

| Característica | Valor |
|---|---|
| Modelo | Heltec CubeCell **HTCC-AB02A** ("CubeCell 1/2AA Node") |
| MCU | ASR6502 (ARM Cortex-M0+ @ 48 MHz) + SX1262 integrada |
| RAM | 16 KB |
| Flash | 128 KB |
| Deep sleep | 3,5 µA |
| Frecuencia LoRa | 915 MHz (AU915) |
| Antena | SMA |
| Puerto serie | USB (CP210x) |

### 2.2 Sensores

| Sensor | Tipo | Rango / resolución | Interfaz |
|---|---|---|---|
| AMG8833 | Termopila IR 8×8 | −20 a +100 °C (objeto), 0,25 °C/LSB (píxeles), 0,0625 °C/LSB (termistor) | I2C (0x69) |
| ADXL335 (GY-61) | Acelerómetro MEMS ±3 g | ~300 mV/g, salida analógica 0–3,3 V | Analógico (ADC1) |

### 2.3 Alimentación

| Parámetro | Valor |
|---|---|
| Tipo de pila | Li-SOCl₂ 1/2AA **ER14250** |
| Tensión nominal | 3,6 V |
| Capacidad | 1200 mAh |
| Recargable | **No** |

### 2.4 Radio LoRaWAN

| Parámetro | Valor |
|---|---|
| Región | AU915, sub-banda 2 |
| Activación | OTAA |
| Clase | A |
| Data rate | DR5 (SF7/125 kHz) |
| ADR | OFF |
| Puerto | 1 (no confirmado) |
| Intervalo | 60 s |

---

## 3. Qué mide y qué reporta

| Campo | Significado |
|---|---|
| `thermistor_C` | Temperatura interna del AMG8833 (termistor) |
| `pixels_C[64]` | Temperatura de cada uno de los 64 píxeles (mapa térmico) |
| `pixel_min_C` / `pixel_max_C` | Temperaturas mínima y máxima del mapa |
| `battery_mV` / `battery_V` / `battery_percent` | Estado de la pila |
| `accel_x` | Promedio de aceleración del eje X (conteo 10-bit) |
| `vib_level` / `vib_label` | Nivel de movimiento (0–3 / texto) |
| `vib_range` | Rango de variación del eje X (max − min) |

---

## 4. Cableado (referencia para instalación)

### 4.1 Termocámara AMG8833

| AMG8833 | CubeCell | Descripción |
|---|---|---|
| VIN | VEXT (P3_2) | Alimentación conmutada |
| GND | GND | Común |
| SCL | SCL0 (P0_0) | Reloj I2C |
| SDA | SDA0 (P0_1) | Datos I2C |

### 4.2 Acelerómetro GY-61 (ADXL335)

| GY-61 | CubeCell | Descripción |
|---|---|---|
| VCC | VEXT (P3_2) | Mismo rail que AMG8833 |
| GND | GND | Común |
| X_OUT | ADC1 (P2_0) | Eje X |
| Y_OUT | — | Sin conectar |
| Z_OUT | — | Sin conectar |

> **Importante**: la polaridad de VEXT en esta placa está **invertida** (HIGH = encendido, LOW = apagado). Ambos sensores se alimentan del mismo pad VEXT y se desenergizan juntos durante el deep sleep.

---

## 5. Operación

### 5.1 Puesta en marcha

1. Conecta la pila ER14250 (observa la **polaridad**: positivo/negativo correctos).
2. El nodo arranca, se une a la red (OTAA) y comienza a transmitir automáticamente cada 60 s.
3. No requiere configuración en campo: toda la configuración está en el firmware y en `credentials.h`.

### 5.2 Indicadores

El nodo no tiene LED de estado ni pantalla. Para observar su funcionamiento, conéctalo por USB a un ordenador y abre el monitor serial a **115200 baud**:

- `[INIT]` → banner de arranque.
- `[JOIN] +++ JOINED +++` → unión exitosa.
- `[ACC] x=… rango=… nivel=…` → datos del acelerómetro.
- `[AMG] OK therm=… pixels[0]=…` → lectura térmica correcta.
- `[UPLINK] OK` → envío correcto.
- `[SLEEP] Durmiendo 60000 ms...` → entrada en deep sleep.

### 5.3 Ciclo de reporte

Cada 60 segundos el nodo: despierta → enciende VEXT (sensores) → muestrea el acelerómetro (500 ms) → lee la termocámara → apaga VEXT → envía el uplink de 138 B → duerme.

---

## 6. Mantenimiento de la pila

- La pila **Li-SOCl₂ ER14250 no es recargable**. Sustitúyela por otra idéntica cuando el voltaje reportado (`battery_mV`) baje de ~3,0 V.
- La curva de descarga de Li-SOCl₂ es **muy plana**: se mantiene cerca de 3,6 V durante casi toda su vida y cae en picado al final. El `battery_percent` es una estimación orientativa.
- **Vida útil estimada**: con el ciclo de 60 s (~760 ms activos por ciclo) y una pila de 1200 mAh, la duración esperada es de varios meses; al alargar el periodo a **3 h**, la duración se extiende considerablemente (el consumo dominante pasa a ser el deep sleep de 3,5 µA).

### 6.1 Recomendación de cambio de pila

| battery_mV | Interpretación | Acción |
|---|---|---|
| ≥ 3,6 V | Plena / nueva | Ninguna |
| 3,3 – 3,6 V | En uso normal | Ninguna |
| 3,0 – 3,3 V | Baja | Planifica el reemplazo |
| < 3,0 V | Agotada | Reemplaza la pila |

---

## 7. Solución de problemas

| Síntoma | Causa probable | Solución |
|---|---|---|
| **Join fallido** (`-1116` o `NO_JOIN_ACCEPT`) | Credenciales incorrectas, sub-banda errónea, gateway fuera de alcance | Verifica `credentials.h`, confirma AU915 sub-banda 2 en el gateway, acerca el nodo al gateway |
| **Sin uplink en el gateway** | Sesión perdida, DR no aplicada, fuera de cobertura | Revisa el serial (`[UPLINK]`); comprueba que la sonda DR5 se confirmó |
| **Payload `0x81` (fallo I2C)** | AMG8833 no responde, VEXT apagado, cableado suelto | Verifica VEXT (HIGH), cableado I2C, dirección 0x69/0x68 |
| **El sensor solo responde el primer ciclo** | Bug del core (I2C no se reinicializa tras deep sleep) | Ya corregido en v2.0 (`Wire.end()` antes de `Wire.begin()`); si ocurre, actualiza el firmware |
| **Downlink no llega** | v2.0 no procesa downlinks (solo loguea) | Esperado: no hay comandos de downlink en esta versión |
| **`accel_x` / `vib_level` no realistas** | GY-61 no cableado o ADC1 flotante | Cablea el GY-61: VCC→VEXT, GND→GND, X_OUT→ADC1 |
| **Upload "Timed out waiting for Bootloader"** | Bootloader atrapado | Desconecta/reconecta el USB y reintenta |
| **Lecturas térmicas inestables** | Cold-start insuficiente | Asegúrate de usar el firmware v2.0 (con `delay(250)` de estabilización) |

---

## 8. Compatibilidad con otras placas LoRaWAN

El diseño y el payload son portables a otras placas LoRaWAN que integren el radio SX1262 y soporten RadioLib. Tabla de compatibilidad:

| Placa | Radio | Compatible | Notas |
|---|---|---|---|
| Heltec CubeCell HTCC-AB02A | SX1262 (SiP) | ✅ **Placa objetivo** | VEXT con polaridad invertida |
| Heltec CubeCell HTCC-AB01 | SX1262 (SiP) | ✅ | Pines de VEXT/SDA/SCL distintos |
| Heltec Wireless Stick / Lite (ASR650x) | SX1262 | ⚠️ Parcial | Requiere reasignar pines y VEXT |
| LilyGO T-Beam (ESP32) | SX1276/1262 | ⚠️ Parcial | ADC de 12 bits distinto; VEXT ausente |
| LilyGO T3 (ESP32) | SX1276 | ⚠️ Parcial | Radio distinto (SX127x) |
| RAKwireless RAK4631 (nRF52840) | SX1262 | ⚠️ Parcial | Core nRF, low-power distinto |
| MCCI Catena / Feather M0 + RFM95 | SX1276 | ⚠️ Parcial | Región/frecuencia según módulo |

> Los `#define` de pines (`SENSOR_PWR_PIN`, `SCL`, `SDA`, `ACCEL_ADC_PIN`), la resolución ADC y la polaridad de VEXT son los principales puntos a adaptar al migrar a otra placa.

---

*Fin del datasheet. Para detalles de desarrollo, consulta `docs/developer.md`.*
