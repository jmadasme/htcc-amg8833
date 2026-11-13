/*
 * HTCC_AB02A_AMG8833_Thermal.ino — Nodo LoRaWAN Low-Power + Termocámara AMG8833 (v1.0)
 * ==============================================================================
 * Heltec CubeCell HTCC-AB02A (ASR6502 + SX1262, "CubeCell 1/2AA Node")
 * Region: AU915 sub-banda 2 | OTAA | Clase A | RadioLib 7.7.1
 * Gateway: Milesight UG56 (Network Server embebido)
 *
 * OBJETIVO:
 *   - Reutilizar la MISMA identidad LoRaWAN del proyecto HTCC_AB02A_LoRaWAN.
 *   - Leer TODOS los valores crudos (hex) de la termocámara AMG8833 (8x8):
 *       * Termistor  : registro 0x0E, 2 bytes (12-bit con signo, LE)
 *       * 64 píxeles : registros 0x80-0xFF, 128 bytes (64 x 12-bit con signo, LE)
 *   - Enviar 1 uplink cada 60 s (puerto 1) con payload de 133 bytes.
 *   - Deep sleep real entre envíos y DESENERGIZACIÓN TOTAL del sensor
 *     mediante el pad VEXT (P3_2, LOW=ON / HIGH=OFF) -> 0 uA en reposo.
 *
 * PAYLOAD (puerto 1, 133 bytes):
 *   [0]      version: 0x01 (OK) | 0x81 (fallo de lectura I2C)
 *   [1:2]    termistor crudo (2 bytes, tal como reporta el sensor)
 *   [3:130]  64 píxeles crudos (128 bytes, tal como reporta el sensor)
 *   [131:132] batería mV uint16 BE
 *
 * RADIO:
 *   - ADR OFF + DR4 (SF8) fijado tras el join para admitir 133 bytes
 *     (payloadLenMax AU915: DR4 = 242 B).
 *
 * LOW-POWER:
 *   - lowPowerHandler() (CySysPmDeepSleep) + TimerEvent_t (RTC).
 *   - radio.sleep() antes del deep sleep; radio.standby() al despertar.
 *   - Vext HIGH (sensor apagado) antes de dormir.
 *
 * ==============================================================================
 */

#include <RadioLib.h>
#include <Wire.h>
#include "credentials.h"
#include "Arduino.h"

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

/* Alimentación conmutada del sensor: pad VEXT (P3_2).
 * ATENCIÓN (verificado en campo en esta placa): la polaridad de VEXT
 * en el HTCC-AB02A es HIGH=ON / LOW=OFF (invertida respecto al pinout
 * oficial "LOW-ON, HIGH-OFF"). Verificado con escáner I2C: el AMG8833
 * responde en 0x69 solo con Vext en HIGH. */
#define SENSOR_PWR_PIN       Vext

/* ------------------------------------------------------------------ */
/* Ciclo de operación                                                  */
/* ------------------------------------------------------------------ */
#define SLEEP_INTERVAL_MS    60000UL   /* 60 s entre reportes              */

/* Payload fijo de 133 bytes (ver cabecera) */
#define PAYLOAD_LEN          133

uint8_t  downlinkData[RADIOLIB_LORAWAN_MAX_PAYLOAD_SIZE]; /* 242 B */
size_t   downlinkLen = 0;

/* Tras el join hay que enviar 1 uplink sonda para que el NS aplique
 * DR4 (LinkADRReq/Ans). Hasta que no se complete, el payload grande
 * no cabe en la DR inicial. */
static bool drProbePending = false;
static uint8_t drProbeRetries = 0;

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

/* ------------------------------------------------------------------ */
/* Diagnóstico                                                         */
/* ------------------------------------------------------------------ */
#define debug(fmt, ...) Serial.printf(fmt, ##__VA_ARGS__)

static const char* stateDecode(int16_t s) {
    switch (s) {
        case RADIOLIB_ERR_NONE:              return "OK";
        case RADIOLIB_ERR_CHIP_NOT_FOUND:    return "CHIP_NOT_FOUND";
        case RADIOLIB_ERR_PACKET_TOO_LONG:   return "PACKET_TOO_LONG";
        case RADIOLIB_ERR_RX_TIMEOUT:        return "RX_TIMEOUT";
        case RADIOLIB_ERR_MIC_MISMATCH:      return "MIC_MISMATCH";
        case RADIOLIB_ERR_NETWORK_NOT_JOINED:return "NOT_JOINED";
        case RADIOLIB_ERR_NO_JOIN_ACCEPT:    return "NO_JOIN_ACCEPT";
        case RADIOLIB_LORAWAN_NEW_SESSION:   return "NEW_SESSION";
        case RADIOLIB_LORAWAN_SESSION_RESTORED: return "SESSION_RESTORED";
        default:                             return "UNKNOWN";
    }
}

/* ------------------------------------------------------------------ */
/* Alimentación del sensor (VEXT)                                      */
/* ------------------------------------------------------------------ */
static void vextSensorOn(void)
{
    /* El core puede re-aplicar pinMode a otros pines tras el deep sleep;
     * no confiar en el pinMode() hecho en setup(). Re-aplicar aquí. */
    pinMode(SENSOR_PWR_PIN, OUTPUT);
    digitalWrite(SENSOR_PWR_PIN, HIGH);  /* enciende AMG8833 (polaridad invertida) */
    /* El AMG8833 necesita >= 50 ms tras encenderse para estabilizar su
     * oscilador y responder por I2C. Antes usaba 20 ms, que provocaba
     * fallos intermitentes de lectura (sensor_ok=false, payload 0x81).
     * 250 ms da margen cómodo (cold-start) sin afectar el ciclo de 60 s. */
    delay(250);
}

static void vextSensorOff(void)
{
    /* Libera el bus I2C (SCB) antes del deep sleep: resetea I2C_initVar
     * y reduce fuga de corriente en reposo. */
    Wire.end();
    digitalWrite(SENSOR_PWR_PIN, LOW);   /* apaga AMG8833 -> 0 uA */
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
 *   PCTL=0x00 (normal) -> RESET=0x3F (initial reset) -> FPSC=10fps.
 * Intenta la dirección 0x69 y, si no responde, 0x68.
 * Los píxeles se leen en 2 tramos de 64 B (buffer I2C del core = 128 B). */
static bool readAmg8833(uint8_t* therm, uint8_t* pixels)
{
    /* BUG CORE CUBECELL (deep sleep + I2C): tras despertar, Wire.begin()
     * NO re-inicializa el periférico SCB porque I2C_initVar queda en 1
     * (la SRAM se retiene en deep sleep). Wire.end() resetea ese flag y
     * obliga al siguiente begin() a ejecutar I2C_Init() completo.
     * Sin esto, el sensor solo responde en el 1er ciclo tras reset. */
    Wire.end();
    bool wireOk = Wire.begin(SDA, SCL, 100000);
    debug("[AMG] Wire.begin=%s\r\n", wireOk ? "OK" : "FAIL");

    /* Inicialización (probar 0x69 y 0x68) */
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
/* Enviar uplink de 133 bytes (puerto 1) + capturar downlink           */
/* ------------------------------------------------------------------ */
static int sendReport(const uint8_t* therm, const uint8_t* pixels, bool sensorOk)
{
    uint16_t batt = readBatteryMv();

    uint8_t payload[PAYLOAD_LEN];
    payload[0] = sensorOk ? 0x01 : 0x81;        /* version/estado */
    payload[1] = therm[0];                      /* termistor crudo */
    payload[2] = therm[1];
    memcpy(&payload[3], pixels, 128);           /* 64 píxeles crudos */
    payload[131] = (uint8_t)(batt >> 8);        /* batería mV BE */
    payload[132] = (uint8_t)(batt & 0xFF);

    debug("[UPLINK] port=1 payload=");
    for (uint8_t i = 0; i < PAYLOAD_LEN; i++) {
        debug("%02X", payload[i]);
    }
    debug(" (%u B)\r\n", (unsigned)PAYLOAD_LEN);

    downlinkLen = sizeof(downlinkData);
    int state = node.sendReceive(payload, sizeof(payload), 1,
                                 downlinkData, &downlinkLen,
                                 false, NULL, NULL);

    if (state == RADIOLIB_ERR_NONE) {
        debug("[UPLINK] OK (sin downlink)\r\n");
    } else if (state > 0) {
        debug("[RX] %u bytes: ", (unsigned)downlinkLen);
        for (size_t i = 0; i < downlinkLen; i++) {
            debug("%02X", downlinkData[i]);
        }
        debug("\r\n");
        handleDownlink(downlinkData, downlinkLen);
    } else {
        debug("[UPLINK] ERROR %d (%s)\r\n", state, stateDecode(state));
    }

    return state;
}

/* ------------------------------------------------------------------ */
/* Downlink (v1.0: solo log, sin comandos)                             */
/* ------------------------------------------------------------------ */
static void handleDownlink(const uint8_t* data, size_t len)
{
    if (len < 1) return;
    debug("[RX] comando 0x%02X (v1.0: sin acciones)\r\n", data[0]);
}

/* ------------------------------------------------------------------ */
/* Uplink sonda: tras el join, la DR inicial del NS es baja (51-115 B).*/
/* setDatarate(4) encola un LinkADRReq que viaja en los FOpts del      */
/* próximo uplink; al llegar el LinkADRAns (downlink), el NS aplica    */
/* DR4 y los siguientes envíos de 133 B ya caben.                      */
/* ------------------------------------------------------------------ */
static void sendProbeUplink(void)
{
    uint16_t batt = readBatteryMv();
    uint8_t probe[6];
    probe[0] = 0x02;                       /* version: sonda DR */
    probe[1] = (uint8_t)(batt >> 8);
    probe[2] = (uint8_t)(batt & 0xFF);
    probe[3] = 0x00;
    probe[4] = 0x00;
    probe[5] = 0x00;

    debug("[PROBE] uplink sonda port=1 payload=");
    for (uint8_t i = 0; i < 6; i++) debug("%02X", probe[i]);
    debug(" (6 B)\r\n");

    downlinkLen = sizeof(downlinkData);
    int state = node.sendReceive(probe, sizeof(probe), 1,
                                 downlinkData, &downlinkLen,
                                 false, NULL, NULL);

    if (state > 0) {
        debug("[RX] %u bytes: ", (unsigned)downlinkLen);
        for (size_t i = 0; i < downlinkLen; i++) {
            debug("%02X", downlinkData[i]);
        }
        debug("\r\n");
        handleDownlink(downlinkData, downlinkLen);
    } else if (state != RADIOLIB_ERR_NONE) {
        debug("[PROBE] ERROR %d (%s)\r\n", state, stateDecode(state));
    }

    debug("[DR] tras sonda maxPayload=%u B\r\n",
          (unsigned)node.getMaxPayloadLen());
}

/* ------------------------------------------------------------------ */
/* Re-join automático + fijar DR4/SF8 (ADR off)                        */
/* ------------------------------------------------------------------ */
static void applyDrSettings(void)
{
    /* Payload de 133 B: AU915 tiene dwell time de 400 ms en uplink.
     * - DR4 (SF8)  -> maxPayload ~125 B (NO sirve)
     * - DR5 (SF7)  -> maxPayload ~238 B (sirve, toa ~80 ms)
     * setDatarate aplica la DR localmente (LinkADRReq encolado). */
    int16_t s = node.setDatarate(5);
    debug("[DR] setDatarate(5)=%d maxPayload=%u B\r\n",
          s, (unsigned)node.getMaxPayloadLen());
}

static bool ensureJoined(void)
{
    if (node.isActivated()) return true;

    debug("[REJOIN] Intentando re-join...\r\n");
    int state = node.activateOTAA();
    if (state == RADIOLIB_LORAWAN_NEW_SESSION ||
        state == RADIOLIB_LORAWAN_SESSION_RESTORED) {
        debug("[REJOIN] +++ EXITOSO +++\r\n");
        node.setADR(false);
        applyDrSettings();
        drProbePending = true;
        drProbeRetries = 0;
        return true;
    }
    debug("[REJOIN] Fallo: %d (%s)\r\n", state, stateDecode(state));
    return false;
}

/* ------------------------------------------------------------------ */
/* SETUP                                                               */
/* ------------------------------------------------------------------ */
void setup() {
    Serial.begin(115200);
    delay(3000);

    debug("\r\n[INIT] HTCC-AB02A + AMG8833 nodo v1.0 (RadioLib) — AU915 SB2\r\n");
    debug("[INIT] DevEUI=%016llX JoinEUI=%016llX\r\n",
          (unsigned long long)devEui, (unsigned long long)joinEui);

    /* Sensor apagado desde el inicio (VEXT: LOW = OFF en esta placa) */
    pinMode(SENSOR_PWR_PIN, OUTPUT);
    digitalWrite(SENSOR_PWR_PIN, LOW);

    /* Inicializar radio */
    int state = radio.begin();
    if (state != RADIOLIB_ERR_NONE) {
        debug("[INIT] Radio FAILED: %d (%s)\r\n", state, stateDecode(state));
        while (true) delay(1);
    }
    debug("[INIT] Radio OK\r\n");

    /* Inicializar nodo OTAA */
    state = node.beginOTAA(joinEui, devEui, nwkKey, appKey);
    if (state != RADIOLIB_ERR_NONE) {
        debug("[INIT] Node FAILED: %d (%s)\r\n", state, stateDecode(state));
        while (true) delay(1);
    }
    debug("[INIT] Node OK\r\n");

    /* Workaround bug de timers (esperas de radio) */
    node.scanGuard = 200;
    debug("[INIT] scanGuard=%d ms\r\n", node.scanGuard);

    /* Join OTAA inicial */
    debug("[JOIN] Iniciando OTAA (AU915 SB2)...\r\n");
    state = node.activateOTAA();
    if (state == RADIOLIB_LORAWAN_NEW_SESSION ||
        state == RADIOLIB_LORAWAN_SESSION_RESTORED) {
        debug("[JOIN] +++ JOINED +++\r\n");
        node.setADR(false);
        applyDrSettings();
        drProbePending = true;
        drProbeRetries = 0;
    } else {
        debug("[JOIN] Fallo: %d (%s)\r\n", state, stateDecode(state));
    }

    debug("[INIT] Ciclo de %lu ms (60 s). Listo.\r\n",
          (unsigned long)SLEEP_INTERVAL_MS);
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
    }

    /* Si aún no se aplicó DR4, enviar uplink sonda (lleva el LinkADRReq
     * en los FOpts). Al recibir el LinkADRAns, el NS fija DR4/SF8. */
    if (drProbePending) {
        sendProbeUplink();
        if (node.getMaxPayloadLen() >= PAYLOAD_LEN) {
            debug("[DR] DR4 confirmada, payload de %u B habilitado\r\n",
                  (unsigned)PAYLOAD_LEN);
            drProbePending = false;
        } else if (++drProbeRetries >= 5) {
            debug("[DR] Sin confirmación DR4 tras %u intentos; continúo.\r\n",
                  (unsigned)drProbeRetries);
            drProbePending = false;
        }
    }

    uint8_t therm[2]   = { 0, 0 };
    uint8_t pixels[128] = { 0 };

    /* Encender sensor, medir y apagar (consumo 0 fuera de la medición) */
    vextSensorOn();
    bool ok = readAmg8833(therm, pixels);
    debug("[AMG] %s therm=0x%02X%02X pixels[0]=0x%02X%02X\r\n",
          ok ? "OK" : "FAIL",
          therm[1], therm[0], pixels[1], pixels[0]);
    vextSensorOff();

    /* Enviar reporte */
    sendReport(therm, pixels, ok);

    /* Deep sleep 60 s */
    debug("[SLEEP] Durmiendo %lu ms...\r\n", (unsigned long)SLEEP_INTERVAL_MS);
    Serial.flush();
    deepSleepMillis(SLEEP_INTERVAL_MS);
}