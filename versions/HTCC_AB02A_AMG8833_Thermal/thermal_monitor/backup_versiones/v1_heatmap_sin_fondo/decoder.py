"""
decoder.py

Decodificación del payload crudo (base64) que envía el nodo LoRaWAN
por el puerto 1 (fPort 1). Solo se usa cuando el gateway NO aplica
un payload decoder y el mensaje MQTT no trae el campo "object".

Formato del payload de 133 bytes:
  [0]        version/estado: 0x01 = OK, 0x81 = fallo de lectura del sensor
  [1:2]      termistor crudo  (2 bytes, 12-bit con signo, little-endian)
  [3:130]    64 píxeles crudos (128 bytes = 64 x 12-bit con signo, LE)
  [131:132]  batería en mV, uint16 big-endian

Conversión a °C:
  - Termistor: valor12bit_con_signo * 0.0625
  - Píxeles:   valor12bit_con_signo * 0.25
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


def decode_uplink_data(b64):
    """Decodifica el payload crudo en base64 y devuelve un dict con los campos.

    Devuelve:
        {
            "sensor_ok": bool,
            "thermistor_C": float,
            "thermistor_raw": int,
            "pixels_C": [float x64],
            "pixel_min_C": float,
            "pixel_max_C": float,
            "battery_mV": int,
        }
    """
    try:
        raw = base64.b64decode(b64)
    except Exception as e:
        raise PayloadDecodeError(f"base64 inválido: {e}")

    if len(raw) < 133:
        raise PayloadDecodeError(
            f"Payload demasiado corto: {len(raw)} bytes (se esperaban 133). "
            f"Tal vez el número de trama o el puerto no es el correcto."
        )

    status = raw[0]
    sensor_ok = (status & 0x7F) == 0x01

    # Termistor: 12-bit signed little-endian packed en 2 bytes
    term_raw = struct.unpack("<H", raw[1:3])[0]
    term_deg = sign_12(term_raw) * 0.0625

    # 64 píxeles: 128 bytes, cada píxel en 12-bit signed LE
    pixels = []
    for i in range(64):
        off = 3 + i * 2
        v = struct.unpack("<H", raw[off:off + 2])[0]
        pixels.append(sign_12(v) * 0.25)

    if len(pixels) != 64:
        raise PayloadDecodeError("No se pudieron obtener 64 píxeles.")

    # Batería: mV, big-endian (bytes 131 y 132)
    bat_mv = (raw[131] << 8) | raw[132]

    return {
        "sensor_ok": bool(sensor_ok),
        "thermistor_C": round(term_deg, 2),
        "thermistor_raw": term_raw,
        "pixels_C": pixels,
        "pixel_min_C": min(pixels),
        "pixel_max_C": max(pixels),
        "battery_mV": bat_mv,
    }
