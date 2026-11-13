/*
 * credentials.example.h — Plantilla pública de credenciales LoRaWAN OTAA
 * Nodo: HTCC_AB01_AMG8833_Thermal_v1 (Heltec CubeCell HTCC-AB01)
 *
 * Copiar como credentials.h y COMPLETAR con los valores reales del nodo
 * (registrados en el Network Server Milesight UG56):
 *
 *   cp credentials.example.h credentials.h
 *
 * Generar valores únicos, por ejemplo con:
 *   openssl rand -hex 8    -> DevEUI (8 bytes, orden big-endian)
 *   openssl rand -hex 8    -> JoinEUI (8 bytes)
 *   openssl rand -hex 16   -> AppKey / NwkKey (16 bytes)
 *
 * El archivo credentials.h con valores reales NUNCA se versiona
 * (ver .gitignore).
 */
#ifndef CREDENTIALS_H
#define CREDENTIALS_H

/* JoinEUI (AppEUI) — asignado en el Network Server Milesight UG56 */
static const uint64_t joinEui = 0x0000000000000000ULL;

/* DevEUI del nodo */
static const uint64_t devEui = 0x0000000000000000ULL;

/* AppKey / NwkKey — 16 bytes (LoRaWAN 1.0.x: mismo valor para ambas) */
static const uint8_t appKey[] = {
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00
};

static const uint8_t nwkKey[] = {
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00
};

#endif /* CREDENTIALS_H */
