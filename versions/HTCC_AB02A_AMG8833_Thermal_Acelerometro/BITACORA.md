# Bitácora — Nodo LoRaWAN HTCC-AB02A + Termocámara AMG8833 + Acelerómetro ADXL335 (v2.0)

> **Ubicación local**: `/home/jma/Documents/Proyects/OpenCode/AG.CreadorContenido/proyectos/HTCC_AB02A_AMG8833_Thermal_Acelerometro/`
>
> Este archivo es la bitácora de desarrollo del proyecto v2.0. Registra lo realizado, las decisiones técnicas, los pendientes y las pruebas pendientes.

---

## ⚡ PUNTO DE DECISIÓN ACTUAL (04/09/2026) — ¡LEER PRIMERO!

**Estamos en una encrucijada de diseño.** No se continuará con las pruebas hasta decidir el camino.

### La decisión pendiente

| Opción | Descripción | Estado |
|---|---|---|
| **A. Un solo nodo (integrado)** | Termocámara + acelerómetro en UNA misma CubeCell HTCC-AB02A (v2.0 tal como está ahora) | El firmware v2.0 está listo, compilado y grabado; falta cablear el GY-61 y probar la clasificación |
| **B. Dos nodos separados** | Tarjeta 1: termocámara (ya logrado, v1.0). Tarjeta 2: acelerómetro (nuevo, partiendo de esta v2.0) | Requiere crear un firmware dedicado para el acelerómetro solo, con otra identidad LoRaWAN |

### Qué significa cada opción

**Opción A (integrado):** continuar donde quedamos:
- Ya está hecho: firmware v2.0 (138 B), decoder v2.0, join verificado, termocámara funcionando, código del acelerómetro listo.
- Falta: cablear GY-61 (VCC→VEXT, GND→GND, X_OUT→ADC1), probar clasificación de movimiento, verificar payload en gateway, alargar a 3 h, docs y publicación.

**Opción B (separado):** aprovechar todo lo aprendido:
- Tarjeta 1 (termocámara): ya completa y publicada en GitHub (`HTCC_AB02A_AMG8833_Thermal`).
- Tarjeta 2 (acelerómetro): crear un proyecto nuevo a partir de esta v2.0, quitando la termocámara y dejando solo el acelerómetro + clasificación + payload reducido. **IMPORTANTE**: tendrá que usar OTRA identidad LoRaWAN (otro DevEUI/AppKey) porque no pueden coexistir dos dispositivos con el mismo DevEUI en el gateway.
- Este firmware v2.0 integrado sirve de **base técnica** para el caso B: ya tiene el acelerómetro implementado, probado en código (falta cableado) y el decoder con `vib_label`.

### Estado para retomar

- El firmware v2.0 está **grabado en la placa** y transmitiendo (con el pin ADC1 flotando, el acelerómetro reporta valores no reales hasta cablear).
- La bitácora completa de la sesión del 03/09/2026 está en la sección 2.
- **No se realizarán más pruebas físicas** hasta decidir la opción A o B.

---

## 1. Información general

| Campo | Valor |
|---|---|
| **Proyecto** | HTCC_AB02A_AMG8833_Thermal_Acelerometro |
| **Versión** | v2.0 |
| **Placa** | Heltec CubeCell HTCC-AB02A (ASR6502 + SX1262) |
| **Sensores** | Termocámara AMG8833 (8×8) + Acelerómetro GY-61 (ADXL335) |
| **Red** | LoRaWAN AU915 sub-banda 2 · OTAA · Clase A · RadioLib 7.7.1 |
| **Gateway** | Milesight UG56 (Network Server embebido) |
| **DevEUI** | `70B3D56F27CEE98B` |
| **Periodo de reporte** | 60 s (1 min) — pendiente alargar a 3 h tras estabilizar |
| **Base** | Proyecto v1.0 `HTCC_AB02A_AMG8833_Thermal` (ya verificado en campo) |

---

## 2. Fecha: 03/09/2026 — Sesión de desarrollo de la v2.0

### 2.1 Requerimiento del usuario

Crear una nueva versión del proyecto que:
1. Mantenga todo lo de la termocámara AMG8833 (reporte cada 60 s, deep sleep, desenergización).
2. Agregue un **acelerómetro GY-61 (ADXL335)** con la **misma lógica de categorización de movimiento** que el nodo ESP8266 de referencia (`espNowDemo/firmware_nodo_8`): niveles reposo/baja/media/alta.
3. El acelerómetro debe **desenergizarse completamente** cuando la CubeCell duerme (alimentado desde VEXT, igual que la termocámara) → 0 µA en reposo, máxima vida útil.
4. El payload LoRaWAN se amplía para incluir el dato del acelerómetro.
5. El `decoder.js` del gateway Milesight se modifica para decodificar el nuevo payload.
6. El dashboard/app de escritorio (otra instancia) mostrará también el nivel de movimiento.
7. Periodo inicial: 1 minuto. Luego de estabilizar y probar → alargar a **3 horas**.

### 2.2 Decisiones tomadas (clarificación con el usuario)

| Decisión | Valor |
|---|---|
| Nombre del proyecto | `HTCC_AB02A_AMG8833_Thermal_Acelerometro` |
| Ejes del acelerómetro | Solo **eje X** (como el nodo de referencia) |
| Clasificación | 4 niveles: 0=reposo, 1=baja, 2=media, 3=alta |

### 2.3 Lo realizado en esta sesión

- [x] Crear carpeta local del nuevo proyecto en la ubicación de siempre.
- [x] Copiar la base: `credentials.h`, `credentials.example.h`, `.gitignore`.
- [x] Copiar el `.ino` v1.0 como base y modificarlo a **v2.0**.
- [x] Crear `PLAN.md` (392 líneas) con el análisis completo.
- [x] **Implementar el firmware v2.0**:
  - Termocámara AMG8833 intacta (con fix `Wire.end()`/`Wire.begin()` del bug I2C+deep sleep).
  - Acelerómetro ADXL335 eje X en **ADC1 (P2_0)**.
  - Ventana de muestreo: 50 muestras cada 10 ms (~100 Hz).
  - Normalización del ADC de 12 bits → 10 bits (`v >> 2`) para conservar umbrales 12/40/100.
  - Clasificación: `categorizeVibration()` → 0=reposo, 1=baja, 2=media, 3=alta.
  - Payload ampliado de 133 → **138 bytes** (accel_x + vib_level + vib_range).
  - Desenergización total en deep sleep: VEXT apaga AMG8833 + ADXL335 → 0 µA.
  - Debug serial `[ACC]` con x/rango/nivel.
- [x] **Compilar** con `--fqbn CubeCell:CubeCell:CubeCell_AB02A` → OK (90 044 B, 68%).
- [x] **Transferir a la placa** (tras resolver bootloader atrapado con desconexión USB).
- [x] **Verificar en placa** (serial): join OK, termocámara OK, acelerómetro reportando (`[ACC] x=710 rango=1 nivel=0`), uplink de 138 B OK.
- [x] **Crear y probar `decoder.js`** v2.0:
  - Decodifica `accel_x` (uint16 BE), `vib_level` (0-3), `vib_label` ("reposo"/"baja"/"media"/"alta"), `vib_range` (uint16 BE).
  - Retrocompatible con tramas v1.0 de 133 B.
  - ES5 compatible con Milesight UG56.
  - Probado con Node.js: resultados correctos.

### 2.4 Incidentes y soluciones

| Incidente | Solución |
|---|---|
| Upload fallaba con "Timed out waiting for Bootloader response" | El bootloader de la CubeCell quedó atrapado tras un upload interrumpido. Se resolvió **desconectando/reconectando físicamente el USB** y reintentando. |
| FQBN `CubeCell-1/2AA` no parseable por arduino-cli | Se usa `CubeCell:CubeCell:CubeCell_AB02A` (el que funciona en este entorno). |

---

## 3. Especificación del payload v2.0 (puerto 1, 138 bytes)

| Byte(s) | Campo | Contenido | Endianidad |
|---|---|---|---|
| 0 | `version/estado` | 0x01 = OK térmica, 0x81 = fallo I2C | — |
| 1–2 | `thermistor` | Termistor crudo AMG8833 (12-bit signed) | LE |
| 3–130 | `pixels[64]` | 64 píxeles crudos (128 B) | LE |
| 131–132 | `battery_mV` | Voltaje de batería | BE |
| 133–134 | `accel_x` | Promedio eje X (dominio 10-bit, ≤1023) | BE |
| 135 | `vib_level` | 0=reposo, 1=baja, 2=media, 3=alta | — |
| 136–137 | `vib_range` | max−min de la ventana (dominio 10-bit) | BE |

**Conversión a °C** (resoluciones distintas):
- Termistor (0x0E): `temp_C = valor12bit * 0.0625`
- Píxeles (0x80-0xFF): `temp_C = valor12bit * 0.25`

---

## 4. Mapeo de pines (v2.0)

### 4.1 Termocámara AMG8833 (sin cambios)

| Pin AMG8833 | Pad CubeCell | Nota |
|---|---|---|
| VIN | VEXT (P3_2) | Alimentación conmutada (HIGH=ON / LOW=OFF) |
| GND | GND | Común |
| SCL | SCL0 (P0_0, pin 39) | I2C0 |
| SDA | SDA0 (P0_1, pin 40) | I2C0 |

### 4.2 Acelerómetro GY-61 (ADXL335) — NUEVO

| Pin GY-61 | Pad CubeCell | Nota |
|---|---|---|
| VCC | **VEXT** (P3_2) | Mismo rail conmutado que AMG8833 → 0 µA en sleep |
| GND | GND | Común |
| X_OUT | **ADC1** (P2_0) | Entrada analógica eje X |
| Y_OUT / Z_OUT | — | **SIN CONECTAR** |

> ⚠️ **IMPORTANTE**: el cableado físico del acelerómetro **aún NO se ha realizado** (pendiente). El firmware está grabado y probado con el pin ADC flotando; los valores del acelerómetro serán reales solo después de cablear.

---

## 5. Pendientes (TODO)

> **⚠️ ESTADO: PRUEBAS DETENIDAS (04/09/2026)** — No se continúa hasta decidir entre Opción A (integrador) u Opción B (separado). Ver sección "PUNTO DE DECISIÓN ACTUAL".

### 5.1 Pendiente del usuario
- [ ] **Decidir**: ¿integrar ambos sensores en una sola CubeCell (Opción A) o separarlos en dos tarjetas (Opción B)?
- [ ] Si se elige la **Opción A**: cablear el GY-61 (ADXL335): VCC→VEXT, GND→GND, X_OUT→ADC1 (P2_0).
- [ ] Si se elige la **Opción B**: preparar la segunda CubeCell y definir su nueva identidad LoRaWAN (DevEUI/AppKey distintos).

### 5.2 Pendientes del desarrollo (Opción A — integrado)
- [ ] Verificar en placa la **clasificación de movimiento** (sacudir el sensor → nivel 0→3).
- [ ] Verificar que el payload llega **decodificado al gateway** (con `accel_x`, `vib_label`).
- [ ] **Alargar el periodo de reporte a 3 horas** cuando el sistema esté estable (cambiar `SLEEP_INTERVAL_MS` en el `.ino`; actualmente 60000 ms).
- [ ] Actualizar la documentación (README, datasheet, developer) para la v2.0.
- [ ] Publicar la v2.0 en GitHub (modo privado, cuenta wanderc137).
- [ ] Actualizar la app de escritorio/dashboard (otra instancia) para mostrar el nivel de movimiento.

### 5.3 Pendientes del desarrollo (Opción B — separado)
- [ ] Crear proyecto nuevo: `HTCC_AB02A_ADXL335_Acelerometro` (o nombre similar).
- [ ] Firmware dedicado: quitar termocámara, dejar solo acelerómetro + clasificación.
- [ ] Payload reducido (sin los 128 B de píxeles): p. ej. version + accel_x + vib_level + vib_range + batería.
- [ ] Nueva identidad LoRaWAN (DevEUI/JoinEUI/AppKey diferentes) y registrarla en el gateway.
- [ ] Decoder.js dedicado para el nuevo payload.
- [ ] Documentación + publicación GitHub.

---

## 6. Notas técnicas importantes

1. **Bug del core CubeCell (I2C + deep sleep)**: `Wire.begin()` no reinicializa el I2C tras deep sleep (`I2C_initVar` queda en 1 en SRAM). Fix: `Wire.end()` antes de `Wire.begin()` en cada lectura. Sin esto, el sensor solo responde el 1er ciclo.
2. **Polaridad de VEXT invertida** en esta placa: HIGH = ON / LOW = OFF (contrario al pinout oficial). Verificado en campo.
3. **ADC de la CubeCell**: 12 bits (0-4095), fondo de escala ~2.4 V (no 3.3 V). Se normaliza a 10 bits (`v >> 2`) para conservar los umbrales del nodo de referencia.
4. **`accel_x` en reposo** ≈ 710 (no 512): el punto de 0 g del ADXL335 queda desplazado por la diferencia de escala ADC. Para la clasificación importa el **rango** (max−min), no el valor absoluto.
5. **Umbrales de vibración**: calibrados en el ESP8266 de referencia (12/40/100). Pueden requerir re-verificación en campo con la CubeCell (son `#define`s ajustables).

---

## 7. Referencias

| Recurso | Ruta |
|---|---|
| Firmware base v1.0 | `../HTCC_AB02A_AMG8833_Thermal/HTCC_AB02A_AMG8833_Thermal.ino` |
| Firmware de referencia del acelerómetro | `../espNowDemo/firmware_nodo_8/firmware_nodo_8.txt` |
| Plan de implementación v2.0 | `./PLAN.md` |
| Decoder v2.0 | `./decoder.js` |
| Credenciales (real) | `./credentials.h` (NO versionar) |
| Plantilla de credenciales | `./credentials.example.h` |

---

## 8. Fecha: 04/09/2026 — Sesión: detención de pruebas y decisión de diseño

### 8.1 Contexto

El usuario vuelve al día siguiente indicando que **es probable que se separen los sensores en dos tarjetas CubeCell distintas**:
- Tarjeta 1: termocámara AMG8833 (ya lograda, publicada en GitHub).
- Tarjeta 2: acelerómetro ADXL335 (lo que se estaba integrando), de forma separada.

Aún no hay decisión definitiva. Por eso se ordena:
1. **Detener las pruebas físicas aquí** (no cablear ni probar la clasificación por ahora).
2. **Documentar todo muy bien** (esta bitácora + README + docs).
3. **Subir esta versión a GitHub** (modo privado).
4. Registrar en la bitácora el **punto de decisión** para poder retomar cualquiera de las dos vías.

### 8.2 Acciones realizadas en esta sesión

- [x] Actualizar esta bitácora con el **PUNTO DE DECISIÓN ACTUAL** (sección superior).
- [x] Reestructurar los pendientes en Opción A (integrado) y Opción B (separado).
- [x] Crear documentación (README, datasheet, developer) de la v2.0.
- [x] Publicar la v2.0 en GitHub (modo privado, cuenta wanderc137).
- [x] Asegurar que `credentials.h`, `PLAN.md`, `AUDIT_REPORT.md` NO se suben.

### 8.3 Estado físico de la placa

- El firmware **v2.0 (integrado)** quedó grabado en la CubeCell y transmitiendo (con ADC1 flotando).
- La termocámara AMG8833 está **cableada** y funcionando.
- El acelerómetro GY-61 **NO está cableado** (pendiente de decisión).

### 8.4 Próximo paso (depende de la decisión del usuario)

| Si se elige... | Acción inmediata |
|---|---|
| **Opción A (integrado)** | Cablear GY-61 → probar clasificación → alargar a 3 h → actualizar docs |
| **Opción B (separado)** | Crear nuevo proyecto del acelerómetro solo, con nueva identidad LoRaWAN |

---

*Bitácora creada: 03/09/2026. Actualizada: 04/09/2026. Se actualizará en cada sesión de desarrollo.*