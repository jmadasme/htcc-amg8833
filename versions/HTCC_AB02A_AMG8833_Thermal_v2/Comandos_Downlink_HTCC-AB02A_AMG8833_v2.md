# 📡 Comandos Downlink — Nodo HTCC-AB02A + AMG8833 (v2.1)

Guía rápida para controlar el nodo LoRaWAN desde el gateway **Milesight UG56**.

> **Importante**: todos los comandos se envían por **FPort = 1**.
> Los cambios se guardan en **flash** → sobreviven a reinicio o corte de energía.

> **Nuevo en v2.1**: ahora el nodo envía en **todo reporte** su SF actual, su ciclo de
> reporte (minutos) y la **intensidad de señal (RSSI)** del último downlink recibido.
> Además se añadió un tercer comando (`03 00`) para consultar el RSSI.

---

## 1. Cambiar el Spreading Factor (SF)

### Formato
```
01 <SF>        → 2 bytes
```
`<SF>` en hexadecimal, valores válidos: **7, 8 o 9**.

### Tabla de comandos

| SF | Bytes hex | Efecto (Data Rate) | Nota |
|---|---|---|---|
| SF7 | `01 07` | DR5 | Más rápido, más datos (envía 138 bytes) |
| SF8 | `01 08` | DR4 | Intermedio (envía compacto de 16 bytes) |
| SF9 | `01 09` | DR3 | Más alcance (envía compacto de 16 bytes) |

### Ejemplos
- Poner SF7 (máxima velocidad): envía `01 07`
- Poner SF9 (máximo alcance): envía `01 09`

> ⚠️ **Límite**: el SF está limitado a 7–9 porque el dwell time de AU915 (400 ms)
> no permite uplinks en SF10+. Un SF fuera de rango se **ignora**.

---

## 2. Cambiar el ciclo de reporte (minutos)

### Formato
```
02 <min_HI> <min_LO>        → 3 bytes
```
El intervalo se expresa en **minutos** como un número de 16 bits **big-endian**
(dos bytes: parte alta y parte baja).

### Tabla de comandos (más usados)

| Ciclo | Bytes hex |
|---|---|
| 1 minuto | `02 00 01` |
| 2 minutos | `02 00 02` |
| 5 minutos | `02 00 05` |
| 10 minutos | `02 00 0A` |
| 15 minutos | `02 00 0F` |
| 30 minutos | `02 00 1E` |
| 45 minutos | `02 00 2D` |
| 1 hora (60 min) | `02 00 3C` |
| 2 horas (120 min) | `02 00 78` |
| 3 horas (180 min) | `02 00 B4` |
| 4 horas (240 min) | `02 00 F0` |
| 6 horas (360 min) | `02 01 68` |
| 8 horas (480 min) | `02 01 E0` |
| 12 horas (720 min) | `02 02 D0` |
| 24 horas (1440 min) | `02 05 A0` |

### Ejemplos
- Reportar cada 5 minutos: envía `02 00 05`
- Reportar cada hora: envía `02 00 3C`
- Reportar cada 24 horas: envía `02 05 A0`

---

## 3. Consultar la intensidad de señal (RSSI)

### Formato
```
03 00        → 2 bytes
```
Consulta la **intensidad de señal** del último downlink. El comando no cambia nada;
simplemente hace que el **próximo uplink** reporte el RSSI recibido (en dBm, valor
negativo). Es útil para medir la calidad del enlace en un momento dado.

### Cómo se interpreta el resultado
- El RSSI aparece en **todo reporte** (antes lo hacía solo tras un downlink). Un valor
  negativo (p. ej. `-85 dBm`) indica buena recepción del gateway.
- Si el nodo reporta `null` / `8000` en RSSI, significa que aún **no recibió ningún
  downlink** desde el último arranque (no hay dato que medir todavía).

> 💡 **Consejo**: manda primero `03 00` (u otro comando) y, en el siguiente reporte,
> mira el campo RSSI para conocer la señal que llega al nodo.

---

## 4. Cómo calcular cualquier intervalo tú mismo

1. Convierte los minutos a **hexadecimal** (4 dígitos).
2. Separa en dos bytes: `02 <byte_alto> <byte_bajo>`.

**Ejemplo — 90 minutos:**
- 90 decimal = `0x005A`
- `<min_HI>` = `00`, `<min_LO>` = `5A`
- → Comando: `02 00 5A`

---

## 4. Enviar con JSON (usando el decoder `Encode`)

Si tienes el `decoder.js` cargado en el Milesight, puedes usar el **encoder**
mandando JSON en el downlink:

| JSON | Bytes generados | Qué hace |
|---|---|---|
| `{ "set_sf": 7 }` | `01 07` | SF7 |
| `{ "set_sf": 8 }` | `01 08` | SF8 |
| `{ "set_sf": 9 }` | `01 09` | SF9 |
| `{ "interval_min": 5 }` | `02 00 05` | ciclo 5 min |
| `{ "interval_min": 60 }` | `02 00 3C` | ciclo 1 h |
| `{ "interval_min": 1440 }` | `02 05 A0` | ciclo 24 h |

---

## 5. Enviar con JSON (usando el decoder `Encode`)

Si tienes el `decoder.js` cargado en el Milesight, puedes usar el **encoder**
mandando JSON en el downlink:

| JSON | Bytes generados | Qué hace |
|---|---|---|
| `{ "set_sf": 7 }` | `01 07` | SF7 |
| `{ "set_sf": 8 }` | `01 08` | SF8 |
| `{ "set_sf": 9 }` | `01 09` | SF9 |
| `{ "interval_min": 5 }` | `02 00 05` | ciclo 5 min |
| `{ "interval_min": 60 }` | `02 00 3C` | ciclo 1 h |
| `{ "interval_min": 1440 }` | `02 05 A0` | ciclo 24 h |
| `{ "query_rssi": true }` | `03 00` | consultar RSSI |

---

## 6. Resumen visual

```
┌────────────────────────────────────────────────────────┐
│  FPort = 1                                             │
│                                                        │
│  Cambiar SF:       01 <sf>            (7..9)           │
│  Cambiar ciclo:    02 <hi> <lo>       (min, 1..1440)   │
│  Consultar RSSI:   03 00                               │
│                                                        │
│  Cambios de SF/ciclo se guardan en flash (persisten).  │
└────────────────────────────────────────────────────────┘
```

---

## 7. Notas importantes

- **Clase A**: el downlink solo se recibe justo después de un uplink (ventanas RX1/RX2).
  Si el nodo acaba de enviar, el comando se encola en el gateway y se aplica en el
  **siguiente** uplink (~1 min después). Es normal que tarde un minuto.

- Al aplicar un comando, el nodo imprime por serial la confirmación:
  - `[DL] SF cambiado a X (DRx, maxPayload=... B)`
  - `[DL] Intervalo cambiado a X min`
  - `[DL] Consulta RSSI recibida` (comando `03 00`)

- **Payload del uplink (v2.1)**: además de los datos térmicos, TODO reporte incluye
  los 3 campos de telemetría al final del payload:
  - **SF** actual (1 byte)
  - **ciclo de reporte** en minutos (2 bytes, big-endian)
  - **RSSI** del último downlink (2 bytes, int16 big-endian; `8000`/`null` = no disponible)

  Con SF7 envía el mapa térmico completo (64 píxeles, **138 bytes**).
  Con SF8/SF9 envía un resumen compacto (min, max y promedio + batería, **16 bytes**).
