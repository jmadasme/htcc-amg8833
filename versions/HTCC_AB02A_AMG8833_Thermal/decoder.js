/*
 * HTCC_AB02A_AMG8833_Thermal - Payload Decoder (Milesight NS embebido UG56)
 * ==========================================================================
 * Uso: Network Server (UG56/UG65/UG67) -> Payload Codec -> Payload Decoder.
 *
 * Formato (Milesight / ChirpStack v3):
 *   - JavaScript ES5 (sin let/const, sin arrow functions).
 *   - Decode(fPort, bytes) -> objeto JSON DIRECTO (NO {data, errors}).
 *   - Encode(fPort, obj)   -> array de bytes DIRECTO.
 *   - SOLO caracteres ASCII.
 *
 * Payload uplink (fPort 1, 133 bytes):
 *   [0]      version/estado: 0x01 = OK, 0x81 = fallo lectura I2C
 *   [1:2]    termistor crudo (2 bytes, 12-bit signed, LE, tal como reporta el sensor)
 *   [3:130]  64 píxeles crudos (128 bytes, 12-bit signed, LE)
 *   [131:132] bateria mV uint16 BE
 *
 * Conversión (IMPORTANTE — resoluciones distintas por registro):
 *   - Termistor (0x0E):  temp_C = valor12bit * 0.0625 °C/LSB
 *   - Píxeles (0x80-0xFF): temp_C = valor12bit * 0.25   °C/LSB
 *   (verificado en campo: termistor crudo 0x0196 = 406 -> 25.4 °C con 0.0625)
 * ==========================================================================
 */

function Decode(fPort, bytes) {
    var decoded = {};

    if (fPort === 1 && bytes.length >= 133) {

        var version = bytes[0];
        decoded.version = version;
        decoded.sensor_ok = (version === 0x01);

        /* [1:2] Termistor crudo */
        var thermRaw = (bytes[2] << 8) | bytes[1];
        decoded.thermistor_raw = "0x" + hex2(bytes[1]) + hex2(bytes[2]);
        decoded.thermistor_C = round2(sign12(thermRaw) * 0.0625);

        /* [3:130] 64 píxeles crudos */
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

        /* [131:132] Batería */
        var batt = (bytes[131] << 8) | bytes[132];
        decoded.battery_mV = batt;
        decoded.battery_V = round2(batt / 1000.0);
        decoded.battery_percent = batteryPercent(batt);
    }

    /* Señal LoRa (RSSI/SNR): la aporta el gateway, no el nodo.
     * Milesight expone la variable global LoRaObject con los metadatos
     * de radio del paquete recibido. Se añade si está disponible. */
    try {
        if (typeof LoRaObject !== "undefined" &&
            LoRaObject.rxInfo && LoRaObject.rxInfo.length > 0) {
            decoded.rssi = LoRaObject.rxInfo[0].rssi;         // dBm
            decoded.snr = LoRaObject.rxInfo[0].loRaSNR;       // dB
        }
    } catch (e) {
        /* LoRaObject no disponible (p.ej. pruebas fuera del gateway) */
    }

    return decoded;
}

function Encode(fPort, obj) {
    /* v1.0: sin comandos downlink */
    return [];
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

/* Porcentaje de batería a partir del voltaje en mV.
 * Curva aproximada para pila de litio Li-SOCl2 no recargable 14250
 * (ER14250/LS14250, 1/2AA, 3.6 V nominal).
 *
 * La descarga de Li-SOCl2 es MUY plana: se mantiene ~3.6 V durante casi
 * toda su vida y cae en picado al final. Por eso los tramos altos son
 * anchos y el final cae rápido. Esta curva es orientativa (el voltaje
 * es un indicador pobre de carga en esta química, pero es lo que hay
 * disponible sin contador de coulombs). */
function batteryPercent(mV) {
    var v = mV;
    if (v >= 3650) return 100;   /* nueva / plena */
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
    return 0;                     /* < 3.0 V: agotada */
}