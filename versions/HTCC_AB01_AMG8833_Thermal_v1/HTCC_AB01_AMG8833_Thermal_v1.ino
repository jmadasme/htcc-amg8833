/*
 * HTCC_AB01_AMG8833_Thermal_v1.ino — Nodo LoRaWAN Low-Power + Termocámara AMG8833 (v1.0)
 * ==============================================================================
 * Heltec CubeCell HTCC-AB01 (ASR6502 + SX1262, "CubeCell Dev-Board")
 * Región: AU915 sub-banda 2 | OTAA | Clase A | RadioLib 7.7.1
 * Gateway: Milesight UG56 (Network Server embebido)
 *
 * Portado de: HTCC_AB02A_AMG8833_Thermal_v2 (placa AB02A) -> AB01.
 * Fusiona la termocámara AMG8833 + payload adaptativo + control por downlink
 * del proyecto de referencia CON las mejoras de fiabilidad del nodo AB01:
 *   - Persistencia de sesión LoRaWAN en EEPROM (nonces + session), evita
 *     re-joins rechazados por DevNonce reiniciado (error -1116 del UG56).
 *   - fatalErrorReset() con soft-reset (NVIC_SystemReset) + deep sleep.
 *
 * CONTROL POR DOWNLINK (whitelist estricto, puerto 1):
 *   Comando 0x01 <sf>        : cambia el Spreading Factor (7..9 -> DR5..DR3)
 *   Comando 0x02 <hi> <lo>   : cambia el ciclo de reporte en MINUTOS (1..1440, uint16 BE)
 *   Comando 0x03 <res>       : consulta de intensidad de señal (RSSI del último downlink)
 *   SF e intervalo se PERSISTEN en EEPROM (flash emulada) -> sobreviven a reset.
 *   NOTA (I-001): SF limitado a 7..9 porque AU915 con dwell time no admite SF10+.
 *
 * PAYLOAD ADAPTATIVO (restricción AU915 400ms dwell):
 *   TODO payload lleva SIEMPRE: SF actual, intervalo (min) y RSSI del
 *   último downlink (int16 BE dBm). 0x8000 = "aún sin downlink".
 *   - SF7  (DR5, maxPayload ~238 B): payload completo (133 B térmicos + 5 B meta = 138 B)
 *        [0]      0x01 OK | 0x81 fallo I2C
 *        [1:2]    termistor crudo (LE)
 *        [3:130]  64 píxeles crudos (128 B, 12-bit signed, LE)
 *        [131:132] batería mV (BE)
 *        [133]    SF actual (7..9)
 *        [134:135] intervalo en minutos (uint16 BE)
 *        [136:137] RSSI último downlink (int16 BE, dBm); 0x8000 = no disponible
 *   - SF8+ (DR4..DR3, maxPayload <=125 B): payload COMPACTO (16 B)
 *        [0]      0x11 OK | 0x91 fallo lectura  (0x1x = formato compacto)
 *        [1:2]    termistor crudo (LE)
 *        [3:4]    píxel MIN crudo (12-bit, LE)
 *        [5:6]    píxel MAX crudo (12-bit, LE)
 *        [7:8]    píxel PROMEDIO crudo (uint16 LE = suma/64)
 *        [9:10]   batería mV (BE)
 *        [11]     SF actual (7..9)
 *        [12:13]  intervalo en minutos (uint16 BE)
 *        [14:15]  RSSI último downlink (int16 BE, dBm); 0x8000 = no disponible
 *
 * RESTANTE (heredado y verificado en campo):
 *   - Deep sleep real entre envíos + desenergización total del sensor por VEXT.
 *   - Bug core CubeCell (deep sleep + I2C): Wire.end() antes de cada Wire.begin().
 *   - Uplink sonda tras join para que el NS aplique la DR (LinkADRReq/Ans).
 *   - ADR OFF + scanGuard=200 (workaround de timers).
 * ==============================================================================
 */

#include <RadioLib.h>
#include <Wire.h>
#include <EEPROM.h>
#include "Arduino.h"
#include "credentials.h"

/* Diagnóstico */
#define debug(fmt, ...) Serial.printf(fmt, ##__VA_ARGS__)

/* ------------------------------------------------------------------ */
/* Pines SX1262 (internos del SiP ASR6502, no reasignables)            */
/*   NSS=P4_3=35, DIO1=P4_6=38, RST=P5_7=47, BUSY=P4_7=39             */
/* ------------------------------------------------------------------ */
Module mod(35, 38, 47, 39);
SX1262 radio(&mod);

/* Región AU915, sub-banda 2 */
const LoRaWANBand_t Region = AU915;
const uint8_t subBand = 2;

LoRaWANNode node(&radio, &Region, subBand);

/* ------------------------------------------------------------------ */
/* Termocámara AMG8833 (I2C)                                           */
/* ------------------------------------------------------------------ */
#define AMG8833_ADDR         0x69      /* 0x68 si el puente Addr está soldado */
#define AMG8833_ADDR_ALT     0x68      /* alternativa si 0x69 no responde     */
#define AMG8833_REG_PCTL     0x00      /* Power Control Register             */
#define AMG8833_REG_RESET    0x01      /* Reset Register                     */
#define AMG8833_RESET_INITIAL 0x3F     /* Initial reset (arranque)           */
#define AMG8833_REG_FPSC     0x04      /* Frame Rate Register                */
#define AMG8833_REG_THERM    0x0E      /* Termistor (2 bytes, 12-bit signed) */
#define AMG8833_REG_PIXELS   0x80      /* 64 píxeles (128 bytes)             */
#define AMG8833_FPS_10       0x05      /* 10 fps                             */

/* Alimentación conmutada del sensor: pad VEXT (P3_2 en AB01).
 * -------------------------------------------------------------------
 * POLARIDAD VEXT (HTCC-AB01 Dev-Board): LOW = ON / HIGH = OFF.
 *   Los ejemplos oficiales del core CubeCell (OneWire, BH1750, HDC1080,
 *   CCS811, MPU9250, BMP180, MultiSensor) usan digitalWrite(Vext, LOW)
 *   para ENCENDER el sensor. Es la polaridad ESTÁNDAR del Dev-Board
 *   (al revés que el HTCC-AB02A, que estaba invertida: HIGH=ON).
 *
 *   IMPORTANTE: tras soldar la termocámara, VERIFICAR con escáner I2C
 *   que 0x69/0x68 responden. Si NO responde, invertir las dos macros
 *   de abajo (VEXT_ON_LEVEL <-> VEXT_OFF_LEVEL).                     */
#define SENSOR_PWR_PIN       Vext
#define VEXT_ON_LEVEL        LOW      /* encender AMG8833 (polaridad AB01) */
#define VEXT_OFF_LEVEL       HIGH     /* apagar AMG8833 -> 0 uA            */

/* ------------------------------------------------------------------ */
/* Payload y comandos downlink                                         */
/* ------------------------------------------------------------------ */
#define PAYLOAD_LEN_FULL     133       /* payload completo (solo SF7) */
#define PAYLOAD_LEN_COMPACT  14        /* payload compacto (SF8..SF9) */
#define DL_CMD_SF            0x01      /* downlink: <sf> 7..9 */
#define DL_CMD_INTERVAL      0x02      /* downlink: <min_hi> <min_lo> BE */
#define DL_CMD_QUERY_RSSI    0x03      /* downlink: <0x00> consulta de intensidad */

/* Campos meta (SIEMPRE presentes en todo payload): SF (1 B), intervalo en
 * minutos (2 B BE), RSSI del último downlink (2 B int16 BE, dBm).
 *  - Payload COMPLETO  (SF7):  SF/intervalo/RSSI al final (índices 133..137).
 *  - Payload COMPACTO (SF8+):  SF [11] e intervalo [12:13] ya vienen del layout;
 *                              solo se AÑADE el RSSI [14:15]. */
#define ADDON_SF_IDX_FULL     133
#define ADDON_INT_IDX_FULL    134
#define ADDON_RSSI_IDX_FULL   136
#define PAYLOAD_LEN_FULL2     138       /* 133 + 5 (sf 1 + intervalo 2 + rssi 2) */

#define ADDON_RSSI_IDX_COMPACT 14
#define PAYLOAD_LEN_COMPACT2  16        /* 14 + 2 (rssi 2) */

#define RSSI_UNAVAILABLE      ((int16_t)0x8000)

/* Límites de seguridad del intervalo (minutos) */
#define INTERVAL_MIN_MIN     1
#define INTERVAL_MIN_MAX     1440

/* SF mínimo/máximo aceptados por downlink.
 * IMPORTANTE (I-001): AU915 con dwell time (400 ms) solo admite uplinks
 * en SF7/SF8/SF9. SF10+ deja el nodo sin uplink (DWELL_TIME_EXCEEDED/
 * PACKET_TOO_LONG) y, al persistirse en EEPROM, "brickea" el nodo sin
 * recuperación por radio. Por eso el rango seguro es 7..9.              */
#define SF_MIN               7
#define SF_MAX               9

/* ------------------------------------------------------------------ */
/* Configuración persistida (EEPROM emulada)                           */
/*   CFG_MAGIC0/1 = 0xC2/0xC3 (NUEVO para esta versión): distinto del   */
/*   proyecto AB01 previo (0xC0/0xC1) para forzar una reinicialización  */
/*   limpia de la config (el struct cambió: intervalSec -> intervalMin). */
/* ------------------------------------------------------------------ */
#define CFG_EEPROM_ADDR      0
#define CFG_MAGIC0           0xC2
#define CFG_MAGIC1           0xC3
#define SESS_EEPROM_ADDR     64
#define SESS_MAGIC0          0x5A   /* 'Z' — bloque de sesión LoRaWAN  */
#define SESS_MAGIC1          0x5B   /* '['                             */
#define EEPROM_ARENA_SIZE    512    /* 2 filas de flash (max core: 768) */

/* Layout bloque de sesión @ SESS_EEPROM_ADDR:
 *   +0  : SESS_MAGIC0
 *   +1  : SESS_MAGIC1
 *   +2  : nonces  (RADIOLIB_LORAWAN_NONCES_BUF_SIZE  = 14 B)
 *   +16 : session (RADIOLIB_LORAWAN_SESSION_BUF_SIZE = 302 B)
 * Total: 2 + 14 + 302 = 318 B -> 64 + 318 = 382 < 512 OK            */
#define SESS_NONCES_OFF           (SESS_EEPROM_ADDR + 2)
#define SESS_SESSION_OFF          (SESS_NONCES_OFF + RADIOLIB_LORAWAN_NONCES_BUF_SIZE)

#if (SESS_SESSION_OFF + RADIOLIB_LORAWAN_SESSION_BUF_SIZE) > EEPROM_ARENA_SIZE
#error "Bloque de sesion no cabe en la EEPROM emulada"
#endif

/* Guardado periódico de sesión: cada N uplinks exitosos (límite de desgaste
 * de flash; la sesión siempre se guarda completa tras un join). */
#define SESS_SAVE_EVERY_UPLINKS   32

struct NodeConfig {
    uint8_t  magic0;
    uint8_t  magic1;
    uint8_t  sf;              /* 7..9 */
    uint16_t intervalMin;     /* 1..1440 */
};

static NodeConfig gCfg;

/* RSSI (dBm) del último downlink recibido. RSSI_UNAVAILABLE si aún no
 * hubo downlink (o el último fue "sin downlink"). Se refresca en cada
 * sendReceive vía radio.getRSSI(). */
static int16_t gLastRssi = RSSI_UNAVAILABLE;

/* Uplinks exitosos desde el último guardado de sesión */
static uint16_t gUplinksSinceSave = 0;

/* Buffers de downlink (globales para no ocupar pila) */
static uint8_t downlinkData[256];
static size_t  downlinkLen = 0;

/* ------------------------------------------------------------------ */
/* Diagnóstico                                                         */
/* ------------------------------------------------------------------ */
static const char* stateDecode(int16_t s) {
    switch (s) {
        case RADIOLIB_ERR_NONE:                return "OK";
        case RADIOLIB_ERR_CHIP_NOT_FOUND:      return "CHIP_NOT_FOUND";
        case RADIOLIB_ERR_PACKET_TOO_LONG:     return "PACKET_TOO_LONG";
        case RADIOLIB_ERR_RX_TIMEOUT:          return "RX_TIMEOUT";
        case RADIOLIB_ERR_MIC_MISMATCH:        return "MIC_MISMATCH";
        case RADIOLIB_ERR_NETWORK_NOT_JOINED:  return "NOT_JOINED";
        case RADIOLIB_ERR_NO_JOIN_ACCEPT:      return "NO_JOIN_ACCEPT";
        case RADIOLIB_ERR_CHECKSUM_MISMATCH:   return "CHECKSUM_MISMATCH";
        case RADIOLIB_ERR_NONCES_DISCARDED:    return "NONCES_DISCARDED";
        case RADIOLIB_ERR_SESSION_DISCARDED:   return "SESSION_DISCARDED";
        case RADIOLIB_LORAWAN_NEW_SESSION:     return "NEW_SESSION";
        case RADIOLIB_LORAWAN_SESSION_RESTORED:return "SESSION_RESTORED";
        default:                               return "UNKNOWN";
    }
}

/* ------------------------------------------------------------------ */
/* Mapeo SF -> DR de AU915 (BW125)                                     */
/*   SF12->DR0, SF11->DR1, SF10->DR2, SF9->DR3, SF8->DR4, SF7->DR5    */
/* ------------------------------------------------------------------ */
static uint8_t drFromSf(uint8_t sf)
{
    switch (sf) {
        case 12: return 0;
        case 11: return 1;
        case 10: return 2;
        case 9:  return 3;
        case 8:  return 4;
        case 7:  return 5;
        default: return 5;
    }
}

/* Aplica la DR correspondiente al SF configurado (ADR off, LinkADRReq encolado) */
static void applyDrFromConfig(void)
{
    int16_t s = node.setDatarate(drFromSf(gCfg.sf));
    debug("[DR] setDatarate(%u)=%d maxPayload=%u B\r\n",
          (unsigned)drFromSf(gCfg.sf), s, (unsigned)node.getMaxPayloadLen());
}

/* Longitud de payload que corresponde según el SF actual */
static size_t requiredPayloadLen(void)
{
    return (gCfg.sf == 7) ? PAYLOAD_LEN_FULL2 : PAYLOAD_LEN_COMPACT2;
}

/* ------------------------------------------------------------------ */
/* Configuración persistida (EEPROM emulada)                           */
/* ------------------------------------------------------------------ */
static void saveConfig(void)
{
    EEPROM.put(CFG_EEPROM_ADDR, gCfg);
    EEPROM.commit();
    debug("[CFG] EEPROM guardada: sf=%u interval=%u min\r\n",
          (unsigned)gCfg.sf, (unsigned)gCfg.intervalMin);
}

static void loadConfig(void)
{
    EEPROM.begin(EEPROM_ARENA_SIZE);
    EEPROM.get(CFG_EEPROM_ADDR, gCfg);

    if (gCfg.magic0 != CFG_MAGIC0 || gCfg.magic1 != CFG_MAGIC1) {
        /* Primer arranque o EEPROM vacía -> defaults (SF7, 1 min) */
        gCfg.magic0      = CFG_MAGIC0;
        gCfg.magic1      = CFG_MAGIC1;
        gCfg.sf          = 7;
        gCfg.intervalMin = 1;
        saveConfig();
    }

    /* Sanidad por si la EEPROM tiene basura con magic válido */
    if (gCfg.sf < SF_MIN || gCfg.sf > SF_MAX) gCfg.sf = 7;
    if (gCfg.intervalMin < INTERVAL_MIN_MIN || gCfg.intervalMin > INTERVAL_MIN_MAX) {
        gCfg.intervalMin = 1;
    }

    debug("[CFG] EEPROM: sf=%u interval=%u min\r\n",
          (unsigned)gCfg.sf, (unsigned)gCfg.intervalMin);
}

/* ------------------------------------------------------------------ */
/* Persistencia de sesión LoRaWAN (nonces + session)                   */
/* ------------------------------------------------------------------ */
static void saveNoncesToEeprom(void)
{
    uint8_t* nonces = node.getBufferNonces();
    if (nonces == NULL) return;

    EEPROM.write(SESS_EEPROM_ADDR, SESS_MAGIC0);
    EEPROM.write(SESS_EEPROM_ADDR + 1, SESS_MAGIC1);
    for (uint16_t i = 0; i < RADIOLIB_LORAWAN_NONCES_BUF_SIZE; i++) {
        EEPROM.write(SESS_NONCES_OFF + i, nonces[i]);
    }
    EEPROM.commit();
    debug("[SESS] Nonces guardados en EEPROM (%u B)\r\n",
          (unsigned)RADIOLIB_LORAWAN_NONCES_BUF_SIZE);
}

static void saveSessionToEeprom(void)
{
    uint8_t* nonces  = node.getBufferNonces();
    uint8_t* session = node.getBufferSession();
    if (nonces == NULL || session == NULL) return;

    EEPROM.write(SESS_EEPROM_ADDR, SESS_MAGIC0);
    EEPROM.write(SESS_EEPROM_ADDR + 1, SESS_MAGIC1);
    for (uint16_t i = 0; i < RADIOLIB_LORAWAN_NONCES_BUF_SIZE; i++) {
        EEPROM.write(SESS_NONCES_OFF + i, nonces[i]);
    }
    for (uint16_t i = 0; i < RADIOLIB_LORAWAN_SESSION_BUF_SIZE; i++) {
        EEPROM.write(SESS_SESSION_OFF + i, session[i]);
    }
    EEPROM.commit();
    gUplinksSinceSave = 0;
    debug("[SESS] Sesion completa guardada en EEPROM (%u B)\r\n",
          (unsigned)(RADIOLIB_LORAWAN_NONCES_BUF_SIZE + RADIOLIB_LORAWAN_SESSION_BUF_SIZE));
}

/* Guardado periódico para refrescar los frame counters sin desgastar flash */
static void saveSessionThrottled(void)
{
    if (++gUplinksSinceSave >= SESS_SAVE_EVERY_UPLINKS) {
        saveSessionToEeprom();
    }
}

/* Intenta cargar el bloque de sesión desde EEPROM en el nodo RadioLib.
 * Debe llamarse DESPUÉS de beginOTAA() y ANTES de activateOTAA().
 * Devuelve true si ambos buffers fueron aceptados (activateOTAA()
 * devolverá entonces SESSION_RESTORED sin tráfico de join).            */
static bool loadSession(void)
{
    if (EEPROM.read(SESS_EEPROM_ADDR) != SESS_MAGIC0 ||
        EEPROM.read(SESS_EEPROM_ADDR + 1) != SESS_MAGIC1) {
        debug("[SESS] Sin bloque de sesion en EEPROM (primer arranque)\r\n");
        return false;
    }

    static uint8_t nonces[RADIOLIB_LORAWAN_NONCES_BUF_SIZE];
    static uint8_t session[RADIOLIB_LORAWAN_SESSION_BUF_SIZE];

    for (uint16_t i = 0; i < RADIOLIB_LORAWAN_NONCES_BUF_SIZE; i++) {
        nonces[i] = EEPROM.read(SESS_NONCES_OFF + i);
    }
    for (uint16_t i = 0; i < RADIOLIB_LORAWAN_SESSION_BUF_SIZE; i++) {
        session[i] = EEPROM.read(SESS_SESSION_OFF + i);
    }

    int16_t st = node.setBufferNonces(nonces);
    if (st != RADIOLIB_ERR_NONE) {
        debug("[SESS] setBufferNonces=%d (%s); se hara join nuevo\r\n",
              st, stateDecode(st));
        return false;
    }
    st = node.setBufferSession(session);
    if (st != RADIOLIB_ERR_NONE) {
        debug("[SESS] setBufferSession=%d (%s); no restaurable, join nuevo\r\n",
              st, stateDecode(st));
        return false;
    }
    debug("[SESS] Bloque de sesion cargado; restaurando sin re-join...\r\n");
    return true;
}

/* ------------------------------------------------------------------ */
/* Low-power nativo: TimerEvent_t (RTC) + lowPowerHandler()            */
/* ------------------------------------------------------------------ */
TimerEvent_t sleepTimer;
static volatile bool sleepExpired = false;

static void onSleepTimerExpired(void)
{
    sleepExpired = true;
}

/* Duerme el MCU en deep sleep hasta que expire el timer RTC.
 * NO retorna hasta que pasen los milisegundos indicados.              */
static void deepSleepMillis(uint32_t ms)
{
    sleepExpired = false;
    TimerInit(&sleepTimer, onSleepTimerExpired);
    TimerSetValue(&sleepTimer, ms);
    TimerStart(&sleepTimer);

    /* Dormir el radio antes del deep sleep del MCU */
    radio.sleep();

    while (!sleepExpired) {
        lowPowerHandler();   /* CySysPmDeepSleep() hasta IRQ del RTC */
    }

    TimerStop(&sleepTimer);
    /* Al despertar, re-activar el radio (SX1262 en standby) */
    radio.standby();
}

/* Recuperación ante fallo irrecuperable de init: soft-reset del core ARM.
 * Respaldo: deep sleep en vez de bucle ocupado (nunca while(true) delay(1)). */
static void fatalErrorReset(void)
{
    debug("[INIT] Auto-reset en 1 s...\r\n");
    Serial.flush();
    delay(1000);
    NVIC_SystemReset();       /* soft-reset del core ARM */
    while (true) {
        radio.sleep();
        deepSleepMillis(10000);
    }
}

/* ------------------------------------------------------------------ */
/* Re-join automático + ADR off + DR según config                      */
/* ------------------------------------------------------------------ */
static bool ensureJoined(void)
{
    if (node.isActivated()) return true;

    debug("[REJOIN] Iniciando join OTAA (AU915 SB2)...\r\n");
    int16_t state = node.activateOTAA();

    /* Persistir nonces SIEMPRE (éxito o fallo): el DevNonce debe avanzar
     * monótonamente aunque el intento falle, para que un corte de energía
     * no reutilice DevNonce (error -1116 del UG56). */
    saveNoncesToEeprom();

    if (state == RADIOLIB_LORAWAN_NEW_SESSION ||
        state == RADIOLIB_LORAWAN_SESSION_RESTORED) {
        debug("[REJOIN] +++ OK +++ (%s)\r\n", stateDecode(state));
        node.setADR(false);
        node.setDwellTime(false);   /* defensa: evitar bloqueo por dwell time AU915 */
        applyDrFromConfig();
        return true;
    }
    debug("[REJOIN] Fallo: %d (%s)\r\n", state, stateDecode(state));
    return false;
}

/* ------------------------------------------------------------------ */
/* Alimentación del sensor (VEXT)                                      */
/* ------------------------------------------------------------------ */
static void vextSensorOn(void)
{
    pinMode(SENSOR_PWR_PIN, OUTPUT);
    digitalWrite(SENSOR_PWR_PIN, VEXT_ON_LEVEL);   /* enciende AMG8833 */
    delay(250);
}

static void vextSensorOff(void)
{
    Wire.end();
    digitalWrite(SENSOR_PWR_PIN, VEXT_OFF_LEVEL);  /* apaga AMG8833 -> 0 uA */
}

/* ------------------------------------------------------------------ */
/* I2C helpers (AMG8833)                                               */
/* ------------------------------------------------------------------ */
static bool amgWriteRegAt(uint8_t addr, uint8_t reg, uint8_t val)
{
    Wire.beginTransmission(addr);
    Wire.write(reg);
    Wire.write(val);
    return (Wire.endTransmission() == 0);
}

static int amgReadAt(uint8_t addr, uint8_t reg, uint8_t* buf, uint8_t len)
{
    Wire.beginTransmission(addr);
    Wire.write(reg);
    if (Wire.endTransmission(false) != 0) {
        return -1;   /* no ACK */
    }
    uint8_t got = Wire.requestFrom((uint8_t)addr, len);
    if (got < len) {
        return -2;   /* menos bytes de los esperados */
    }
    for (uint8_t i = 0; i < len; i++) {
        buf[i] = Wire.read();
    }
    return 0;
}

/* Inicializa y lee termistor + 64 píxeles. Devuelve true si todo OK.
 * Secuencia de arranque según datasheet AMG8833 (patrón Adafruit):
 *   PCTL=0x00 (normal) -> RESET=0x3F (initial reset) -> FPSC=10fps.  */
static bool readAmg8833(uint8_t* therm, uint8_t* pixels)
{
    /* BUG CORE CUBECELL (deep sleep + I2C): tras despertar, Wire.begin()
     * NO re-inicializa el periférico SCB porque I2C_initVar queda en 1
     * (la SRAM se retiene en deep sleep). Wire.end() resetea ese flag. */
    Wire.end();
    bool wireOk = Wire.begin(SDA, SCL, 100000);
    debug("[AMG] Wire.begin=%s\r\n", wireOk ? "OK" : "FAIL");

    uint8_t addr = 0;
    bool initOk = false;
    for (uint8_t a = 0; a < 2; a++) {
        uint8_t cand = (a == 0) ? AMG8833_ADDR : AMG8833_ADDR_ALT;
        if (amgWriteRegAt(cand, AMG8833_REG_PCTL, 0x00) &&
            amgWriteRegAt(cand, AMG8833_REG_RESET, AMG8833_RESET_INITIAL) &&
            amgWriteRegAt(cand, AMG8833_REG_FPSC, AMG8833_FPS_10)) {
            addr = cand;
            initOk = true;
            break;
        }
    }
    if (!initOk) {
        debug("[AMG] init FAIL (sin ACK en 0x69/0x68) — revisar cableado VEXT/I2C\r\n");
        return false;
    }
    debug("[AMG] init OK addr=0x%02X\r\n", addr);

    delay(200);   /* espera primer frame (10 fps -> 100 ms) + margen */

    if (amgReadAt(addr, AMG8833_REG_THERM, therm, 2) != 0) {
        debug("[AMG] termistor FAIL\r\n");
        return false;
    }
    if (amgReadAt(addr, AMG8833_REG_PIXELS, pixels, 64) != 0) {
        debug("[AMG] pixels[0:64] FAIL\r\n");
        return false;
    }
    if (amgReadAt(addr, AMG8833_REG_PIXELS + 64, pixels + 64, 64) != 0) {
        debug("[AMG] pixels[64:128] FAIL\r\n");
        return false;
    }

    return true;
}

/* ------------------------------------------------------------------ */
/* Batería                                                             */
/* ------------------------------------------------------------------ */
static uint16_t readBatteryMv(void)
{
    uint16_t mv = getBatteryVoltage();
    debug("[BATT] %u mV\r\n", mv);
    return mv;
}

/* ------------------------------------------------------------------ */
/* Construcción del payload adaptativo                                 */
/* ------------------------------------------------------------------ */
static size_t buildPayload(uint8_t* payload,
                           const uint8_t* therm,
                           const uint8_t* pixels,
                           bool sensorOk)
{
    uint16_t batt = readBatteryMv();

    if (gCfg.sf == 7 && node.getMaxPayloadLen() >= PAYLOAD_LEN_FULL2) {
        /* --- Payload completo (133 B térmicos + 5 B config/rssi = 138 B) --- */
        payload[0] = sensorOk ? 0x01 : 0x81;        /* version/estado */
        payload[1] = therm[0];                      /* termistor crudo */
        payload[2] = therm[1];
        memcpy(&payload[3], pixels, 128);           /* 64 píxeles crudos */
        payload[131] = (uint8_t)(batt >> 8);        /* batería mV BE */
        payload[132] = (uint8_t)(batt & 0xFF);
        /* --- campos meta: SF + intervalo + RSSI (siempre) --- */
        payload[ADDON_SF_IDX_FULL]    = gCfg.sf;
        payload[ADDON_INT_IDX_FULL]   = (uint8_t)(gCfg.intervalMin >> 8);
        payload[ADDON_INT_IDX_FULL+1] = (uint8_t)(gCfg.intervalMin & 0xFF);
        payload[ADDON_RSSI_IDX_FULL]  = (uint8_t)((uint16_t)gLastRssi >> 8);
        payload[ADDON_RSSI_IDX_FULL+1] = (uint8_t)((uint16_t)gLastRssi & 0xFF);
        return PAYLOAD_LEN_FULL2;
    }

    /* --- Payload compacto (14 B + 2 B RSSI = 16 B) --- */
    uint16_t pmin = 0x0FFF, pmax = 0;
    uint32_t sum = 0;
    for (uint8_t i = 0; i < 64; i++) {
        uint16_t raw = (uint16_t)(pixels[i * 2] | (pixels[i * 2 + 1] << 8));
        raw &= 0x0FFF;
        if (raw < pmin) pmin = raw;
        if (raw > pmax) pmax = raw;
        sum += raw;
    }
    uint16_t pavg = (uint16_t)(sum / 64);

    payload[0] = sensorOk ? 0x11 : 0x91;            /* version compacto */
    payload[1] = therm[0];                          /* termistor crudo */
    payload[2] = therm[1];
    payload[3] = (uint8_t)(pmin & 0xFF);            /* min LE */
    payload[4] = (uint8_t)(pmin >> 8);
    payload[5] = (uint8_t)(pmax & 0xFF);            /* max LE */
    payload[6] = (uint8_t)(pmax >> 8);
    payload[7] = (uint8_t)(pavg & 0xFF);            /* promedio LE */
    payload[8] = (uint8_t)(pavg >> 8);
    payload[9]  = (uint8_t)(batt >> 8);             /* batería mV BE */
    payload[10] = (uint8_t)(batt & 0xFF);
    payload[11] = gCfg.sf;                          /* eco SF actual */
    payload[12] = (uint8_t)(gCfg.intervalMin >> 8); /* eco intervalo BE */
    payload[13] = (uint8_t)(gCfg.intervalMin & 0xFF);
    /* --- campo meta: RSSI (SF e intervalo ya están en [11] y [12:13]) --- */
    payload[ADDON_RSSI_IDX_COMPACT]    = (uint8_t)((uint16_t)gLastRssi >> 8);
    payload[ADDON_RSSI_IDX_COMPACT+1]  = (uint8_t)((uint16_t)gLastRssi & 0xFF);
    return PAYLOAD_LEN_COMPACT2;
}

/* ------------------------------------------------------------------ */
/* Downlink — whitelist estricta de comandos                           */
/*  0x01 <sf>        -> cambiar SF (7..9) + persistir                  */
/*  0x02 <hi> <lo>   -> cambiar intervalo en minutos (1..1440) + persistir */
/*  0x03 [0x00]      -> consulta RSSI del último downlink (log serial) */
/* ------------------------------------------------------------------ */
static void handleDownlink(const uint8_t* data, size_t len)
{
    if (len < 1) return;

    uint8_t cmd = data[0];

    if (cmd == DL_CMD_SF) {
        if (len < 2) {
            debug("[DL] SF: faltan datos; ignorado\r\n");
            return;
        }
        uint8_t sf = data[1];
        if (sf >= SF_MIN && sf <= SF_MAX) {
            gCfg.sf = sf;
            node.setADR(false);
            applyDrFromConfig();
            /* Guard-check (I-001): no persistir un SF cuyo payload no quepa.
             * Evita dejar el nodo "bricked" sin uplink por dwell time. */
            if (node.getMaxPayloadLen() >= PAYLOAD_LEN_COMPACT) {
                saveConfig();
                debug("[DL] SF cambiado a %u (DR%u, maxPayload=%u B)\r\n",
                      (unsigned)sf, (unsigned)drFromSf(sf),
                      (unsigned)node.getMaxPayloadLen());
            } else {
                debug("[DL] SF %u sin uplink (max=%u B <%u B); NO persistido\r\n",
                      (unsigned)sf, (unsigned)node.getMaxPayloadLen(),
                      (unsigned)PAYLOAD_LEN_COMPACT);
            }
        } else {
            debug("[DL] SF %u fuera de rango (7..9); ignorado\r\n", (unsigned)sf);
        }
        return;
    }

    if (cmd == DL_CMD_INTERVAL) {
        if (len < 3) {
            debug("[DL] Intervalo: faltan datos; ignorado\r\n");
            return;
        }
        uint16_t minutes = (uint16_t)(((uint16_t)data[1] << 8) | data[2]);
        if (minutes >= INTERVAL_MIN_MIN && minutes <= INTERVAL_MIN_MAX) {
            gCfg.intervalMin = minutes;
            saveConfig();
            debug("[DL] Intervalo cambiado a %u min\r\n", (unsigned)minutes);
        } else {
            debug("[DL] Intervalo %u min fuera de rango (1..1440); ignorado\r\n",
                  (unsigned)minutes);
        }
        return;
    }

    if (cmd == DL_CMD_QUERY_RSSI) {
        if (gLastRssi == RSSI_UNAVAILABLE) {
            debug("[DL] Consulta RSSI: sin medicion disponible aun\r\n");
        } else {
            debug("[DL] Consulta RSSI: ultimo downlink RSSI=%d dBm\r\n",
                  (int)gLastRssi);
        }
        return;
    }

    debug("[DL] Comando 0x%02X desconocido; ignorado\r\n", cmd);
}

/* ------------------------------------------------------------------ */
/* Enviar uplink (puerto 1) + capturar downlink + RSSI                 */
/* ------------------------------------------------------------------ */
static int sendReport(const uint8_t* therm, const uint8_t* pixels, bool sensorOk)
{
    uint8_t payload[RADIOLIB_LORAWAN_MAX_PAYLOAD_SIZE];
    size_t payloadLen = buildPayload(payload, therm, pixels, sensorOk);

    debug("[UPLINK] port=1 len=%u payload=", (unsigned)payloadLen);
    for (size_t i = 0; i < payloadLen; i++) {
        debug("%02X", payload[i]);
    }
    debug(" (sf=%u max=%u B)\r\n", (unsigned)gCfg.sf,
          (unsigned)node.getMaxPayloadLen());

    LoRaWANEvent_t evtUp, evtDown;

    downlinkLen = sizeof(downlinkData);
    int state = node.sendReceive(payload, payloadLen, 1,
                                 downlinkData, &downlinkLen,
                                 false, &evtUp, &evtDown);

    if (state == RADIOLIB_ERR_NONE) {
        debug("[UPLINK] OK (sin downlink)\r\n");
        saveSessionThrottled();
    } else if (state > 0) {
        /* Capturar el RSSI real del downlink recibido.
         * OJO: LoRaWANEvent_t.power en RadioLib 7.7.1 NO es el RSSI. El RSSI
         * real se lee de la capa PHY con radio.getRSSI() ANTES de que el
         * radio entre en sleep. */
        gLastRssi = (int16_t)radio.getRSSI();
        debug("[RX] %u bytes: ", (unsigned)downlinkLen);
        for (size_t i = 0; i < downlinkLen; i++) {
            debug("%02X", downlinkData[i]);
        }
        debug(" (RSSI=%d dBm)\r\n", (int)gLastRssi);
        handleDownlink(downlinkData, downlinkLen);
        saveSessionThrottled();
    } else {
        debug("[UPLINK] ERROR %d (%s)\r\n", state, stateDecode(state));
    }

    return state;
}

/* ------------------------------------------------------------------ */
/* Uplink sonda: tras el join, envía 6 B para que el NS aplique la DR  */
/* (LinkADRReq viaja en los FOpts del uplink; LinkADRAns llega como    */
/* downlink). Mientras maxPayload no alcance la longitud requerida,    */
/* se re-envía la sonda (máx 5 intentos).                              */
/* ------------------------------------------------------------------ */
static void sendProbeUplink(void)
{
    uint16_t batt = readBatteryMv();
    uint8_t probe[6];
    probe[0] = 0x02;                       /* version: sonda DR */
    probe[1] = (uint8_t)(batt >> 8);
    probe[2] = (uint8_t)(batt & 0xFF);
    probe[3] = gCfg.sf;                    /* eco del SF solicitado */
    probe[4] = (uint8_t)(gCfg.intervalMin >> 8);
    probe[5] = (uint8_t)(gCfg.intervalMin & 0xFF);

    debug("[PROBE] uplink sonda port=1 payload=");
    for (uint8_t i = 0; i < 6; i++) debug("%02X", probe[i]);
    debug(" (6 B)\r\n");

    downlinkLen = sizeof(downlinkData);
    int state = node.sendReceive(probe, sizeof(probe), 1,
                                 downlinkData, &downlinkLen,
                                 false, NULL, NULL);

    if (state > 0) {
        gLastRssi = (int16_t)radio.getRSSI();
        debug("[RX] %u bytes: ", (unsigned)downlinkLen);
        for (size_t i = 0; i < downlinkLen; i++) {
            debug("%02X", downlinkData[i]);
        }
        debug("\r\n");
        handleDownlink(downlinkData, downlinkLen);
        saveSessionThrottled();
    } else if (state != RADIOLIB_ERR_NONE) {
        debug("[PROBE] ERROR %d (%s)\r\n", state, stateDecode(state));
    }

    debug("[DR] tras sonda maxPayload=%u B (requerido %u B)\r\n",
          (unsigned)node.getMaxPayloadLen(), (unsigned)requiredPayloadLen());
}

/* Tras el join hay que enviar 1 uplink sonda para que el NS aplique la
 * DR (LinkADRReq/Ans). Hasta que no se complete, el payload requerido
 * puede no caber en la DR inicial del NS. */
static bool drProbePending = false;
static uint8_t drProbeRetries = 0;

/* ------------------------------------------------------------------ */
/* SETUP                                                               */
/* ------------------------------------------------------------------ */
void setup() {
    Serial.begin(115200);
    delay(3000);   /* espera al monitor serial */

    debug("\r\n[INIT] HTCC-AB01 + AMG8833 nodo v1.0 (RadioLib) — AU915 SB2\r\n");
    debug("[INIT] DevEUI=%016llX JoinEUI=%016llX\r\n",
          (unsigned long long)devEui, (unsigned long long)joinEui);

    /* Configuración persistida (SF e intervalo) */
    loadConfig();

    /* Sensor apagado desde el inicio */
    pinMode(SENSOR_PWR_PIN, OUTPUT);
    digitalWrite(SENSOR_PWR_PIN, VEXT_OFF_LEVEL);

    /* Inicializar radio */
    int state = radio.begin();
    if (state != RADIOLIB_ERR_NONE) {
        debug("[INIT] Radio FAILED: %d (%s)\r\n", state, stateDecode(state));
        fatalErrorReset();
    }
    debug("[INIT] Radio OK\r\n");

    /* Inicializar nodo OTAA */
    state = node.beginOTAA(joinEui, devEui, nwkKey, appKey);
    if (state != RADIOLIB_ERR_NONE) {
        debug("[INIT] Node FAILED: %d (%s)\r\n", state, stateDecode(state));
        fatalErrorReset();
    }
    debug("[INIT] Node OK\r\n");

    /* Workaround bug de timers (esperas de radio) */
    node.scanGuard = 200;
    debug("[INIT] scanGuard=%d ms\r\n", node.scanGuard);

    /* Restaurar sesión persistida (si existe) y activar */
    bool hadSavedSession = loadSession();

    debug("[JOIN] %s (AU915 SB2)...\r\n",
          hadSavedSession ? "Restaurando sesion" : "Iniciando OTAA");

    state = node.activateOTAA();

    if (state == RADIOLIB_LORAWAN_SESSION_RESTORED) {
        debug("[JOIN] +++ SESION RESTAURADA +++ (sin re-join) DevAddr=0x%08X\r\n",
              (unsigned)node.getDevAddr());
    } else if (state == RADIOLIB_LORAWAN_NEW_SESSION) {
        debug("[JOIN] +++ JOINED +++ DevAddr=0x%08X\r\n",
              (unsigned)node.getDevAddr());
        /* Persistir la sesión para sobrevivir a reset/power-cycle */
        saveSessionToEeprom();
    } else {
        debug("[JOIN] Fallo: %d (%s)\r\n", state, stateDecode(state));
        /* Persistir nonces aunque el join falle (DevNonce avanza) */
        saveNoncesToEeprom();
    }

    /* Tras join/restauración: ADR off, dwell time off y DR de la config */
    if (node.isActivated()) {
        node.setADR(false);
        node.setDwellTime(false);
        applyDrFromConfig();
        drProbePending = true;
        drProbeRetries = 0;
    }

    debug("[INIT] Ciclo de %u min (%lu ms). Listo.\r\n",
          (unsigned)gCfg.intervalMin,
          (unsigned long)gCfg.intervalMin * 60000UL);
    Serial.flush();
}

/* ------------------------------------------------------------------ */
/* LOOP                                                                */
/* ------------------------------------------------------------------ */
void loop() {
    /* Re-join si se pierde la sesión */
    if (!node.isActivated()) {
        if (!ensureJoined()) {
            deepSleepMillis(10000);   /* backoff y reintento */
            return;
        }
        saveSessionToEeprom();
        drProbePending = true;
        drProbeRetries = 0;
    }

    /* Uplink sonda hasta confirmar DR con el NS */
    if (drProbePending) {
        sendProbeUplink();
        if (node.getMaxPayloadLen() >= requiredPayloadLen()) {
            debug("[DR] DR confirmada, payload de %u B habilitado\r\n",
                  (unsigned)requiredPayloadLen());
            drProbePending = false;
        } else if (++drProbeRetries >= 5) {
            debug("[DR] Sin confirmacion tras %u intentos; continuo.\r\n",
                  (unsigned)drProbeRetries);
            drProbePending = false;
        }
    }

    uint8_t therm[2]    = { 0, 0 };
    uint8_t pixels[128] = { 0 };

    /* Encender sensor, medir y apagar (consumo 0 fuera de la medición) */
    vextSensorOn();
    bool ok = readAmg8833(therm, pixels);
    debug("[AMG] %s therm=0x%02X%02X pixels[0]=0x%02X%02X\r\n",
          ok ? "OK" : "FAIL",
          therm[1], therm[0], pixels[1], pixels[0]);
    vextSensorOff();

    /* Enviar reporte (138 B si SF7, 16 B compacto si SF>7) */
    sendReport(therm, pixels, ok);

    /* Deep sleep según intervalo configurado (minutos) */
    uint32_t sleepMs = (uint32_t)gCfg.intervalMin * 60000UL;
    debug("[SLEEP] Durmiendo %lu ms (%u min)...\r\n",
          (unsigned long)sleepMs, (unsigned)gCfg.intervalMin);
    Serial.flush();
    deepSleepMillis(sleepMs);
}
