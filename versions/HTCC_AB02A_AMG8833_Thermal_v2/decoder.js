/*
 * HTCC_AB02A_AMG8833_Thermal_v2 - Payload Codec (Milesight NS embebido UG56)
 * ==========================================================================
 * Uso: Network Server (UG56/UG65/UG67) -> Payload Codec -> Payload Decoder.
 *
 * Formato (Milesight / ChirpStack v3):
 *   - JavaScript ES5 (sin let/const, sin arrow functions).
 *   - Decode(fPort, bytes) -> objeto JSON DIRECTO (NO {data, errors}).
 *   - Encode(fPort, obj)   -> array de bytes DIRECTO.
 *   - SOLO caracteres ASCII.
 *
 * PAYLOAD UPLINK (fPort 1) — v2.1: TODO payload lleva SF + intervalo + RSSI
 *   A) Formato COMPLETO (138 B, solo SF7/DR5):
 *        [0]      version/estado: 0x01 = OK, 0x81 = fallo lectura I2C
 *        [1:2]    termistor crudo (2 B, 12-bit signed, LE)
 *        [3:130]  64 píxeles crudos (128 B, 12-bit signed, LE)
 *        [131:132] bateria mV uint16 BE
 *        [133]    SF actual (7..9)
 *        [134:135] intervalo en minutos (uint16 BE)
 *        [136:137] RSSI del último downlink (int16 BE, dBm); 0x8000 = no disponible
 *   B) Formato COMPACTO (16 B, SF8..SF9 porque 133 B no cabe en DR4+):
 *        [0]      version/estado: 0x11 = OK compacto, 0x91 = fallo compacto
 *        [1:2]    termistor crudo (2 B, LE)
 *        [3:4]    píxel MIN crudo (12-bit, LE)
 *        [5:6]    píxel MAX crudo (12-bit, LE)
 *        [7:8]    píxel PROMEDIO crudo (uint16 LE = suma/64)
 *        [9:10]   bateria mV uint16 BE
 *        [11]     SF actual (7..9)
 *        [12:13]  intervalo en minutos (uint16 BE)
 *        [14:15]  RSSI del último downlink (int16 BE, dBm); 0x8000 = no disponible
 *   C) Sonda (6 B, tras join):
 *        [0]      0x02 = sonda
 *        [1:2]    bateria mV BE
 *        [3]      SF solicitado
 *        [4:5]    intervalo en minutos (BE)
 *
 * CONVERSIÓN (resoluciones distintas por registro):
 *   - Termistor (0x0E): temp_C = valor12bit * 0.0625 °C/LSB
 *   - Píxeles (0x80-0xFF): temp_C = valor12bit * 0.25   °C/LSB
 *
 * DOWNLINK (Encode, fPort 1):
 *   { "set_sf": 8 }                  -> [0x01, 0x08]  cambiar SF (7..9)
 *   { "interval_min": 5 }            -> [0x02, 0x00, 0x05]  ciclo en minutos (1..1440)
 *   { "query_rssi": true }           -> [0x03, 0x00]  consulta de intensidad de señal
 *   { "set_sf": 7, "interval_min": 60 } -> [0x01, 0x07, 0x02, 0x00, 0x3C]
 * ==========================================================================
 */

function Decode(fPort, bytes) {
    var decoded = {};

    if (fPort !== 1 || !bytes) {
        return decoded;
    }

    /* --- Sonda (6 B) --- */
    if (bytes.length === 6 && bytes[0] === 0x02) {
        decoded.kind = "probe";
        decoded.battery_mV = (bytes[1] << 8) | bytes[2];
        decoded.battery_V = round2(decoded.battery_mV / 1000.0);
        decoded.sf = bytes[3];
        decoded.interval_min = (bytes[4] << 8) | bytes[5];
        return addRadioInfo(decoded);
    }

    /* --- Formato COMPACTO (16 B, v2.1) --- */
    if (bytes.length === 16 && (bytes[0] === 0x11 || bytes[0] === 0x91)) {
        decoded.kind = "compact";
        decoded.version = bytes[0];
        decoded.sensor_ok = (bytes[0] === 0x11);

        var thermRaw = (bytes[2] << 8) | bytes[1];
        decoded.thermistor_raw = "0x" + hex2(bytes[1]) + hex2(bytes[2]);
        decoded.thermistor_C = round2(sign12(thermRaw) * 0.0625);

        var pminRaw = (bytes[4] << 8) | bytes[3];
        var pmaxRaw = (bytes[6] << 8) | bytes[5];
        var pavgRaw = (bytes[8] << 8) | bytes[7];
        decoded.pixel_min_raw = "0x" + hex2(bytes[3]) + hex2(bytes[4]);
        decoded.pixel_max_raw = "0x" + hex2(bytes[5]) + hex2(bytes[6]);
        decoded.pixel_avg_raw = "0x" + hex2(bytes[7]) + hex2(bytes[8]);
        decoded.pixel_min_C = round2(sign12(pminRaw) * 0.25);
        decoded.pixel_max_C = round2(sign12(pmaxRaw) * 0.25);
        decoded.pixel_avg_C = round2(sign12(pavgRaw) * 0.25);

        decoded.battery_mV = (bytes[9] << 8) | bytes[10];
        decoded.battery_V = round2(decoded.battery_mV / 1000.0);
        decoded.battery_percent = batteryPercent(decoded.battery_mV);

        decoded.sf = bytes[11];
        decoded.interval_min = (bytes[12] << 8) | bytes[13];
        decoded.rssi_dBm = readRssi(bytes[14], bytes[15]);

        return addRadioInfo(decoded);
    }

    /* --- Formato COMPLETO (138 B, v2.1; acepta >=138 por compatibilidad) --- */
    if (bytes.length >= 138 && (bytes[0] === 0x01 || bytes[0] === 0x81)) {
        decoded.kind = "full";
        decoded.version = bytes[0];
        decoded.sensor_ok = (bytes[0] === 0x01);

        var thermRawF = (bytes[2] << 8) | bytes[1];
        decoded.thermistor_raw = "0x" + hex2(bytes[1]) + hex2(bytes[2]);
        decoded.thermistor_C = round2(sign12(thermRawF) * 0.0625);

        var pixels = [];
        var rawHex = "";
        for (var i = 0; i < 64; i++) {
            var lo = bytes[3 + i * 2];
            var hi = bytes[3 + i * 2 + 1];
            var raw = (hi << 8) | lo;
            pixels.push(round2(sign12(raw) * 0.25));
            rawHex += hex2(lo) + hex2(hi);
        }
        decoded.pixels_raw = "0x" + rawHex;
        decoded.pixels_C = pixels;
        decoded.pixel_min_C = round2(minArray(pixels));
        decoded.pixel_max_C = round2(maxArray(pixels));

        decoded.battery_mV = (bytes[131] << 8) | bytes[132];
        decoded.battery_V = round2(decoded.battery_mV / 1000.0);
        decoded.battery_percent = batteryPercent(decoded.battery_mV);

        decoded.sf = bytes[133];
        decoded.interval_min = (bytes[134] << 8) | bytes[135];
        decoded.rssi_dBm = readRssi(bytes[136], bytes[137]);

        return addRadioInfo(decoded);
    }

    return decoded;
}

function Encode(fPort, obj) {
    var bytes = [];

    if (fPort === 1 && typeof obj === "object" && obj !== null) {
        /* Comando 1: cambiar SF (7..9) */
        if (typeof obj.set_sf !== "undefined") {
            var sf = obj.set_sf;
            if (sf >= 7 && sf <= 9) {
                bytes.push(0x01, sf);
            }
        }
        /* Comando 2: cambiar intervalo en minutos (1..1440) */
        if (typeof obj.interval_min !== "undefined") {
            var m = obj.interval_min;
            if (m >= 1 && m <= 1440) {
                bytes.push(0x02, (m >> 8) & 0xFF, m & 0xFF);
            }
        }
        /* Comando 3: consulta de intensidad de señal (RSSI del último downlink) */
        if (obj.query_rssi === true) {
            bytes.push(0x03, 0x00);
        }
    }

    return bytes;
}

/* Lee RSSI (int16 BE, dBm). 0x8000 = "no disponible" (sin downlink reciente). */
function readRssi(hi, lo) {
    var u = (hi << 8) | lo;
    if (u === 0x8000) {
        return null;   /* no disponible */
    }
    if (u & 0x8000) {
        u -= 0x10000;  /* signo negativo */
    }
    return u;
}

/* Helpers */
function sign12(v) {
    var s = v & 0x0FFF;
    if (s & 0x0800) {
        s -= 0x1000;
    }
    return s;
}

function hex2(v) {
    var h = v.toString(16).toUpperCase();
    return (h.length < 2) ? "0" + h : h;
}

function round2(v) {
    return Math.round(v * 100) / 100;
}

function minArray(arr) {
    var m = arr[0];
    for (var i = 1; i < arr.length; i++) {
        if (arr[i] < m) m = arr[i];
    }
    return m;
}

function maxArray(arr) {
    var m = arr[0];
    for (var i = 1; i < arr.length; i++) {
        if (arr[i] > m) m = arr[i];
    }
    return m;
}

/* Señal LoRa (RSSI/SNR): la aporta el gateway, no el nodo. */
function addRadioInfo(decoded) {
    try {
        if (typeof LoRaObject !== "undefined" &&
            LoRaObject.rxInfo && LoRaObject.rxInfo.length > 0) {
            decoded.rssi = LoRaObject.rxInfo[0].rssi;         /* dBm */
            decoded.snr = LoRaObject.rxInfo[0].loRaSNR;       /* dB */
        }
    } catch (e) {
        /* LoRaObject no disponible */
    }
    return decoded;
}

/* Porcentaje de batería a partir del voltaje en mV.
 * Curva aproximada para pila de litio Li-SOCl2 no recargable 14250
 * (ER14250/LS14250, 1/2AA, 3.6 V nominal). Descarga MUY plana. */
function batteryPercent(mV) {
    var v = mV;
    if (v >= 3650) return 100;
    if (v >= 3600) return 95;
    if (v >= 3550) return 85;
    if (v >= 3500) return 75;
    if (v >= 3450) return 65;
    if (v >= 3400) return 50;
    if (v >= 3350) return 40;
    if (v >= 3300) return 30;
    if (v >= 3200) return 20;
    if (v >= 3100) return 10;
    if (v >= 3000) return 5;
    return 0;
}