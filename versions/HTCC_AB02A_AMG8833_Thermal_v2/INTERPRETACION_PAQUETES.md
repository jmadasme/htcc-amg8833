# 📦 Interpretación y explicación de los paquetes LoRaWAN
### Nodo HTCC-AB02A + AMG8833 (v2.1)

> Este documento explica, campo por campo, cómo leer los paquetes que envía y recibe
> el nodo a través del gateway **Milesight UG56**. Sirve como referencia práctica para
> interpretar la consola del Network Server y verificar el correcto funcionamiento.

---

## 1. Estructura general de un paquete

Todo el tráfico del nodo ocurre por el **puerto FPort = 1**.

| Dirección | Tipo | Qué contiene |
|---|---|---|
| **Uplink** (nodo → gateway) | `UpUnc` / `UpCnf` | Datos térmicos + telemetría (SF, intervalo, RSSI) |
| **Downlink** (gateway → nodo) | `DnUnc` / `DnCnf` | Comandos de control (cambiar SF, ciclo, consultar RSSI) |

El nodo es **Clase A**, por lo que los downlink solo se entregan en las ventanas RX1/RX2
que se abren **justo después** de un uplink. Si mandas un comando cuando el nodo duerme,
el gateway lo **encola** y lo entrega en el siguiente uplink.

---

## 2. El uplink (nodo → gateway)

El nodo adapta el tamaño del payload según el **Spreading Factor (SF)** activo:

| SF | DR | Payload | Tamaño |
|---|---|---|---|
| **7** | DR5 | **Completo** (mapa térmico de 64 píxeles) | **138 bytes** |
| 8 | DR4 | **Compacto** (resumen min/max/prom) | **16 bytes** |
| 9 | DR3 | **Compacto** (resumen min/max/prom) | **16 bytes** |

> En SF7 hay margen de payload suficiente (~238 B máx) para el mapa completo;
> en SF8/SF9 el máximo disponible bajaría por debajo de 133 B, por lo que se envían
> solo las estadísticas de temperatura en formato compacto.

### 2.1. Formato del payload COMPLETO (138 bytes, SF7)

```
Byte(s)   Contenido
-------   ---------------------------------------------------------------
[0]       Versión/estado: 0x01 = sensor OK, 0x81 = fallo lectura I2C
[1:2]     Termistor crudo (2 bytes, 12-bit con signo, little-endian)
[3:130]   64 píxeles térmicos crudos (128 bytes, 2 bytes c/u, LE)
[131:132] Batería en milivoltios (uint16, big-endian)
[133]     SF actual (7..9)
[134:135] Intervalo de reporte en minutos (uint16, big-endian)
[136:137] RSSI del último downlink (int16, big-endian, dBm); 0x8000 = sin dato
```

### 2.2. Formato del payload COMPACTO (16 bytes, SF8/SF9)

```
Byte(s)   Contenido
-------   ---------------------------------------------------------------
[0]       Versión/estado: 0x11 = OK compacto, 0x91 = fallo compacto
[1:2]     Termistor crudo (2 bytes, LE)
[3:4]     Píxel MÍNIMO crudo (12-bit, LE)
[5:6]     Píxel MÁXIMO crudo (12-bit, LE)
[7:8]     Píxel PROMEDIO crudo (uint16 LE = suma/64)
[9:10]    Batería en milivoltios (uint16, BE)
[11]      SF actual (7..9)
[12:13]   Intervalo de reporte en minutos (uint16, BE)
[14:15]   RSSI del último downlink (int16, BE, dBm); 0x8000 = sin dato
```

### 2.3. Formato de la SONDA (6 bytes, tras el join)

```
Byte(s)   Contenido
-------   ---------------------------------------------------------------
[0]       0x02 = sonda
[1:2]     Batería en milivoltios (BE)
[3]       SF solicitado
[4:5]     Intervalo en minutos (BE)
```

---

## 3. Conversiones de temperatura

Los valores crudos usan **resoluciones distintas** según el registro:

| Registro | Resolución | Fórmula |
|---|---|---|
| Termistor (0x0E) | 0.0625 °C/LSB | `temp_C = raw12 * 0.0625` |
| Píxeles (0x80–0xFF) | 0.25 °C/LSB | `temp_C = raw12 * 0.25` |

> El termistor (sensor interno del AMG8833) mide la temperatura del propio chip;
> los 64 píxeles miden la escena térmica observada.

---

## 4. Los dos RSSI (no confundirlos)

El paquete muestra **dos campos de RSSI con significados distintos**:

| Campo | Quién lo mide | Qué significa |
|---|---|---|
| `rssi` | **El gateway** | Señal con la que el UG56 recibió al nodo. La aporta el gateway vía `LoRaObject.rxInfo`. |
| `rssi_dBm` | **El nodo** | Señal con la que el nodo recibió el último downlink del gateway. Se genera con `radio.getRSSI()`. |

- `rssi` **siempre** aparece (cada paquete que llega al gateway tiene ese dato).
- `rssi_dBm` puede ser `null` si el nodo **aún no recibió ningún downlink** desde el
  arranque (se codifica como el centinela `0x8000`). Tras mandar un comando (ej. `03 00`),
  el siguiente uplink reportará un valor real (numérico, negativo en dBm).

---

## 5. Ejemplo real 1 — Uplink completo SIN downlink previo (Fcnt 875)

### Packet Details
```
Type:              UpUnc
FPort:             1
Fcnt:              875
SpreadFactor:      7
Bandwidth:         125
SNR:               13.5
RSSI:              -40
Payload(hex):      01840160005b005e... 0d000700018000
```

### Payload hex (fragmento final)
```
... 0D 00 07 00 01 80 00
        │   │   │    │
        │   │   │    └── [136:137] RSSI = 0x8000 → null (sin downlink previo)
        │   │   └─────── [134:135] intervalo = 0x0001 = 1 minuto
        │   └─────────── [133] SF = 7
        └─────────────── [131:132] batería = 0x0D00 = 3328 mV
```

### JSON decodificado (resumido)
```json
{
  "kind": "full",
  "sf": 7,
  "interval_min": 1,
  "rssi_dBm": null,      ← aún no hubo downlink
  "battery_mV": 3328,
  "thermistor_C": 24.25,
  "pixel_min_C": 17.5,
  "pixel_max_C": 24.5,
  "rssi": -40,           ← del gateway (siempre presente)
  "snr": 13.5
}
```

**Interpretación**: el nodo envió el mapa térmico completo (138 B) en SF7, con ciclo de
1 minuto y SF=7. `rssi_dBm` está en `null` porque todavía no se le había mandado ningún
comando de downlink desde el arranque.

---

## 6. Ejemplo real 2 — Uplink completo TRAS el comando `03 00` (Fcnt 878)

Previamente se envió el comando **`03 00`** (consulta de RSSI). El nodo lo recibió, midió
la señal del gateway y la reporta en el siguiente uplink.

### Packet Details
```
Type:              UpUnc
FPort:             1
Fcnt:              878
SpreadFactor:      7
Bandwidth:         125
SNR:               10.0
RSSI:              -44
Payload(hex):      0167014e004b... 0d00070001ffec
```

### Payload hex (fragmento final)
```
... 0D 00 07 00 01 FF EC
        │   │   │    │
        │   │   │    └── [136:137] RSSI = 0xFFEC = -20 dBm  ← ¡YA HAY DATO!
        │   │   └─────── [134:135] intervalo = 0x0001 = 1 minuto
        │   └─────────── [133] SF = 7
        └─────────────── [131:132] batería = 0x0D00 = 3328 mV
```

> Cálculo del RSSI: `0xFFEC` en int16 big-endian = `0xFFEC = -20` (decimal con signo).
> Es decir, el nodo recibió el downlink del gateway con una potencia de **−20 dBm**.

### JSON decodificado (resumido)
```json
{
  "kind": "full",
  "sf": 7,
  "interval_min": 1,
  "rssi_dBm": -20,       ← ahora reporta un valor real
  "battery_mV": 3328,
  "thermistor_C": 22.44,
  "pixel_min_C": 15.5,
  "pixel_max_C": 20.25,
  "rssi": -44,
  "snr": 10.0
}
```

**Interpretación**: el nodo confirma que recibió el comando `03 00` y reporta que "oye" al
gateway con **−20 dBm** (enlace excelente). El campo `rssi` (−44 dBm) sigue siendo la
perspectiva del gateway.

---

## 7. El downlink (gateway → nodo)

En la secuencia de eventos, los downlink aparecen con `Type: DnUnc` y tamaño pequeño
(2 o 3 bytes). Los **3 comandos** disponibles (todos FPort=1):

| Comando | Bytes | Acción |
|---|---|---|
| `01 <sf>` | `01 07` / `01 08` / `01 09` | Cambiar SF (7..9). Persiste en flash. |
| `02 <hi> <lo>` | `02 00 05` (p. ej.) | Cambiar ciclo de reporte, 1..1440 min. Persiste. |
| `03 00` | `03 00` | Consultar RSSI. No cambia nada; el siguiente uplink reporta `rssi_dBm`. |

### Ejemplo real de downlink (DnUnc, Fcnt 1)
```
Type:           DnUnc
Size:           2
Fcnt:           1
Datarate:       SF7 BW500
```
→ Corresponde al comando **`03 00`** (2 bytes).

---

## 8. Secuencia de eventos de ejemplo (registro real)

```
Time        Type    Fcnt  Size  DR          RSSI/SNR   Nota
──────────  ──────  ────  ────  ──────────  ────────   ───────────────────────────
20:02:13    UpUnc   874   138   SF7 BW125    -40/11.8   Uplink completo (sin downlink)
20:03:16    UpUnc   875   138   SF7 BW125    -40/13.5   Uplink completo (rssi_dBm=null)
20:03:16    DnUnc   1     2     SF7 BW500    -/-        ← comando 03 00 (consulta RSSI)
20:04:18    UpUnc   876   138   SF7 BW125    -46/13.2   Uplink completo
20:05:21    UpUnc   877   138   SF7 BW125    -44/13.5   Uplink completo
20:06:24    UpUnc   878   138   SF7 BW125    -44/10.0   Uplink (rssi_dBm=-20) ← respuesta
```

Observa el patrón:
1. El `DnUnc` de 2 bytes (`03 00`) aparece **intercalado** justo tras un `UpUnc`
   (porque en clase A la ventana RX se abre tras cada uplink).
2. El uplink inmediatamente posterior reporta `rssi_dBm` con el valor medido.

---

## 9. Cómo verificar el correcto funcionamiento

| Qué comprobar | Dónde mirar | Valor esperado |
|---|---|---|
| Nodo envía y decodifica | `kind` en JSON | `full` (SF7) o `compact` (SF8/9) |
| SF actual | JSON `sf` | 7, 8 o 9 |
| Ciclo de reporte | JSON `interval_min` | 1..1440 |
| RSSI del nodo | JSON `rssi_dBm` | `null` inicial → nº negativo tras downlink |
| RSSI del gateway | JSON `rssi` | siempre presente (nº negativo) |
| Sensor OK | JSON `sensor_ok` | `true` |
| Batería | JSON `battery_V` / `battery_percent` | ~3.3 V (aprox. 30 % con la curva Li-SOCl2) |

---

## 10. Resumen rápido

- **Todo** ocurre por **FPort = 1**.
- El uplink **siempre** trae telemetría: `sf`, `interval_min` y `rssi_dBm`.
- `rssi_dBm = null` es **normal** si el nodo aún no recibió downlink; deja de serlo tras
  el primer comando.
- Los comandos se encolan en clase A: pueden tardar un ciclo en aplicarse.
- Los cambios de SF y ciclo se guardan en **flash** (sobreviven a reset/corte de energía).
