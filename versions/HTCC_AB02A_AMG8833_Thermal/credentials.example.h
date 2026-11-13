#ifndef CREDENTIALS_EXAMPLE_H
#define CREDENTIALS_EXAMPLE_H

/* =====================================================================
 * Credenciales OTAA — PLANTILLA PÚBLICA (EJEMPLO)
 * ---------------------------------------------------------------------
 * Copia este archivo a credentials.h y rellena con tus credenciales REALES.
 * El archivo credentials.h NO se sube al repositorio (.gitignore).
 *
 * RadioLib espera big-endian (orden over-the-air).
 * ===================================================================== */

/* JoinEUI / AppEUI (big-endian) — reemplazar */
static const uint64_t joinEui = 0x0000000000000000ULL;

/* DevEUI (big-endian) — reemplazar */
static const uint64_t devEui  = 0x0000000000000000ULL;

/* AppKey (big-endian, 16 bytes) — reemplazar */
static const uint8_t appKey[] = { 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
                                  0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00 };

/* NwkKey (big-endian, 16 bytes) — reemplazar */
static const uint8_t nwkKey[] = { 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
                                  0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00 };

#endif /* CREDENTIALS_EXAMPLE_H */