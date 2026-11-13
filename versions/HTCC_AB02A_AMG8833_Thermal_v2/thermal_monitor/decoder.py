"""
decoder.py

Decodificación del payload LoRaWAN que envía el nodo (HTCC-AB02A + AMG8833)
por el puerto 1 (fPort 1). Soporta los TRES formatos según la longitud:

  * Completo (138 bytes, SF7)  ->  mapa térmico 64 + telemetría completa.
  * Compacto (16 bytes, SF8/9) ->  resumen min/max/prom + telemetría.
  * Legacy  (133 bytes)        ->  formato de la v1 (sin sf/intervalo/rssi).

Conversiones a °C:
  - Termistor: valor12bit_con_signo * 0.0625
  - Píxeles:   valor12bit_con_signo * 0.25

Los campos sf / interval_min / rssi_dBm solo existen en 138 y 16 bytes.
"""

import base64
import struct


class PayloadDecodeError(Exception):
    """Se lanza cuando el payload no se puede decodificar."""


def sign_12(v):
    """Convierte un valor de 12 bits (2's complement) a entero con signo."""
    s = v & 0x0FFF
    if s & 0x0800:
        s -= 0x1000
    return s


def sign_16(v):
    """Convierte un valor de 16 bits (2's complement) a entero con signo."""
    s = v & 0xFFFF
    if s & 0x8000:
        s -= 0x10000
    return s


def _decode_termistor(raw2):
    """Termistor: 2 bytes, 12-bit signed LE -> °C."""
    v = struct.unpack("<H", raw2)[0]
    return sign_12(v) * 0.0625


def _decode_pixels(raw128):
    """64 píxeles: 128 bytes, cada uno 12-bit signed LE -> [float x64] °C."""
    px = []
    for i in range(64):
        off = i * 2
        v = struct.unpack("<H", raw128[off:off + 2])[0]
        px.append(sign_12(v) * 0.25)
    return px


def decode_uplink_data(b64):
    """Decodifica un payload LoRaWAN en base64 y devuelve un dict normalizado.

    Devuelve:
        {
            "kind": "full" | "compact" | "legacy",
            "sensor_ok": bool,
            "thermistor_C": float,
            "thermistor_raw": int,
            "pixels_C": [float x64] | None,   # None en formato compacto
            "pixel_min_C": float,
            "pixel_max_C": float,
            "pixel_avg_C": float,
            "battery_mV": int,
            "sf": int|None,                   # 7/8/9 (full y compact)
            "interval_min": int|None,         # ciclo de reporte en min
            "rssi_dBm": int|None,             # rssi del NODO; 0x8000 = None
        }
    """
    try:
        raw = base64.b64decode(b64)
    except Exception as e:
        raise PayloadDecodeError(f"base64 inválido: {e}")

    n = len(raw)

    if n == 138:
        return _decode_full(raw)
    if n == 16:
        return _decode_compact(raw)
    if n >= 133:
        return _decode_legacy(raw)

    raise PayloadDecodeError(
        f"Longitud inesperada: {n} bytes (se esperaban 138, 16 o 133). "
        f"Tal vez el puerto no es el correcto o el payload cambió."
    )


def _decode_full(raw):
    """Formato completo, 138 bytes (SF7)."""
    status = raw[0]
    sensor_ok = (status & 0x7F) == 0x01
    thermistor_C = _decode_termistor(raw[1:3])
    pixels = _decode_pixels(raw[3:131])
    battery_mV = (raw[131] << 8) | raw[132]
    sf = raw[133]
    interval_min = (raw[134] << 8) | raw[135]
    rssi_raw = sign_16(struct.unpack(">H", raw[136:138])[0])
    rssi_dBm = None if (raw[136] == 0x80 and raw[137] == 0x00) else rssi_raw

    return {
        "kind": "full",
        "sensor_ok": bool(sensor_ok),
        "thermistor_C": round(thermistor_C, 2),
        "pixels_C": pixels,
        "pixel_min_C": min(pixels),
        "pixel_max_C": max(pixels),
        "pixel_avg_C": round(sum(pixels) / 64, 2),
        "battery_mV": battery_mV,
        "sf": sf,
        "interval_min": interval_min,
        "rssi_dBm": rssi_dBm,
    }


def _decode_compact(raw):
    """Formato compacto, 16 bytes (SF8/SF9). No trae los 64 píxeles."""
    status = raw[0]
    sensor_ok = (status & 0x7F) == 0x11
    thermistor_C = _decode_termistor(raw[1:3])
    pixel_min = sign_12(struct.unpack("<H", raw[3:5])[0]) * 0.25
    pixel_max = sign_12(struct.unpack("<H", raw[5:7])[0]) * 0.25
    pixel_avg = sign_12(struct.unpack("<H", raw[7:9])[0]) * 0.25
    battery_mV = (raw[9] << 8) | raw[10]
    sf = raw[11]
    interval_min = (raw[12] << 8) | raw[13]
    rssi_raw = sign_16(struct.unpack(">H", raw[14:16])[0])
    rssi_dBm = None if (raw[14] == 0x80 and raw[15] == 0x00) else rssi_raw

    return {
        "kind": "compact",
        "sensor_ok": bool(sensor_ok),
        "thermistor_C": round(thermistor_C, 2),
        "pixels_C": None,
        "pixel_min_C": round(pixel_min, 2),
        "pixel_max_C": round(pixel_max, 2),
        "pixel_avg_C": round(pixel_avg, 2),
        "battery_mV": battery_mV,
        "sf": sf,
        "interval_min": interval_min,
        "rssi_dBm": rssi_dBm,
    }


def _decode_legacy(raw):
    """Formato antiguo, 133 bytes (primeras versiones, sin sf/intervalo)."""
    status = raw[0]
    sensor_ok = (status & 0x7F) == 0x01
    thermistor_C = _decode_termistor(raw[1:3])
    pixels = _decode_pixels(raw[3:131])
    battery_mV = (raw[131] << 8) | raw[132]

    return {
        "kind": "legacy",
        "sensor_ok": bool(sensor_ok),
        "thermistor_C": round(thermistor_C, 2),
        "pixels_C": pixels,
        "pixel_min_C": min(pixels),
        "pixel_max_C": max(pixels),
        "pixel_avg_C": round(sum(pixels) / 64, 2),
        "battery_mV": battery_mV,
        "sf": None,
        "interval_min": None,
        "rssi_dBm": None,
    }
