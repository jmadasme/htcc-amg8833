"""
mqtt_client.py

Conexión MQTT al broker y parseo de los mensajes de uplink del
gateway Milesight UG56 (formato de Network Server / ChirpStack v3).

Usa paho-mqtt en un hilo separado y entrega los mensajes decodificados
a la GUI mediante una cola thread-safe (queue.Queue).
"""

import json
import queue
import threading
import time
from datetime import datetime

import paho.mqtt.client as mqtt

from decoder import decode_uplink_data, PayloadDecodeError


class ThermalData:
    """Datos decodificados de un uplink, listos para mostrar en la GUI."""

    def __init__(self):
        self.raw = {}
        self.dev_eui = None
        self.device_name = None
        self.f_port = None
        self.f_cnt = None
        self.topic = None
        self.received_at = time.time()
        self.received_time_str = datetime.now().strftime("%H:%M:%S")
        self.gateway_decoded = False

        # Campos poblados por object (gateway) o por decoder (fallback)
        self.sensor_ok = False
        self.thermistor_C = None
        self.pixels_C = None
        self.pixel_min_C = None
        self.pixel_max_C = None
        self.battery_mV = None
        self.rssi = None
        self.snr = None

    def to_dict(self):
        return {
            "dev_eui": self.dev_eui,
            "device_name": self.device_name,
            "f_port": self.f_port,
            "f_cnt": self.f_cnt,
            "received_time_str": self.received_time_str,
            "gateway_decoded": self.gateway_decoded,
            "sensor_ok": self.sensor_ok,
            "thermistor_C": self.thermistor_C,
            "pixels_C": self.pixels_C,
            "pixel_min_C": self.pixel_min_C,
            "pixel_max_C": self.pixel_max_C,
            "battery_mV": self.battery_mV,
            "rssi": self.rssi,
            "snr": self.snr,
            "raw": self.raw,
        }


def _extract_rx_info(payload):
    """Extrae rssi/snr del bloque rxInfo si está presente."""
    rssi, snr = None, None
    rx = payload.get("rxInfo")
    if isinstance(rx, list) and rx:
        first = rx[0]
        if isinstance(first, dict):
            rssi = first.get("rssi")
            snr = first.get("loRaSNR", first.get("snr"))
    return rssi, snr


class MQTTBridge:
    """Cliente MQTT que corre en su propio hilo y reenvía datos a una cola."""

    def __init__(self, config):
        self.cfg = config["broker"]
        topics = config.get("topics")
        if not topics:
            topics = [config["topic"]]
        elif isinstance(topics, str):
            topics = [topics]
        self.topics = list(topics)
        self.device_filter = config.get("device_eui_filter")
        self.out_queue = queue.Queue()
        self._client = None
        self._running = False
        self._thread = None
        self.connected_flag = threading.Event()
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Control de conexión
    # ------------------------------------------------------------------
    def start(self):
        with self._lock:
            if self._running:
                return
            self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        with self._lock:
            self._running = False
        client = self._client
        if client:
            try:
                client.loop_stop()
                client.disconnect()
            except Exception:
                pass
        self.connected_flag.clear()

    def is_connected(self):
        return self.connected_flag.is_set()

    def _run(self):
        cfg = self.cfg
        self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)

        if cfg.get("username"):
            self._client.username_pw_set(cfg["username"], cfg.get("password", ""))

        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message

        try:
            self._client.reconnect_delay_set(
                min_delay=cfg.get("reconnect_delay_min", 2),
                max_delay=cfg.get("reconnect_delay_max", 30),
            )
            self._client.connect_async(
                cfg["host"], cfg.get("port", 1883),
                keepalive=cfg.get("keepalive", 60),
            )
            self._client.loop_forever(retry_first_connection=True)
        except Exception as e:
            self._push_status("error", f"Error de conexión MQTT: {e}")
            # reintento manual en bucle
            while self._running:
                time.sleep(cfg.get("reconnect_delay_min", 2))
                try:
                    self._client.connect_async(
                        cfg["host"], cfg.get("port", 1883),
                        keepalive=cfg.get("keepalive", 60),
                    )
                    self._client.loop_forever(retry_first_connection=True)
                except Exception:
                    pass

    # ------------------------------------------------------------------
    # Callbacks paho
    # ------------------------------------------------------------------
    def _on_connect(self, client, userdata, flags, rc, properties=None):
        if rc == 0:
            self.connected_flag.set()
            self._push_status("connect", f"Conectado al broker MQTT")
            for t in self.topics:
                client.subscribe(t, qos=self.cfg.get("qos", 1))
            self._push_status("connect", f"Suscrito a tópicos: {', '.join(self.topics)}")
        else:
            self.connected_flag.clear()
            self._push_status("error", f"Error de conexión MQTT, código rc={rc}")

    def _on_disconnect(self, client, userdata, rc, properties=None):
        self.connected_flag.clear()
        if rc != 0:
            self._push_status("error", "Desconexión inesperada; reconectando...")

    def _on_message(self, client, userdata, msg):
        td = self._parse_message(msg)
        if td is not None:
            self.out_queue.put(td)

    # ------------------------------------------------------------------
    # Parseo
    # ------------------------------------------------------------------
    def _parse_message(self, msg):
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._push_status("error", "Mensaje MQTT no es JSON válido (ignorado)")
            return None

        if not isinstance(payload, dict):
            return None

        dev_eui = None
        for key in ("devEUI", "devEui", "deveui", "DevEUI", "dev_eui"):
            v = payload.get(key)
            if v:
                dev_eui = str(v)
                break
        # Filtrar por dispositivo si está configurado
        if self.device_filter and dev_eui:
            if dev_eui.lower() != self.device_filter.lower():
                return None

        td = ThermalData()
        td.raw = payload
        td.dev_eui = dev_eui or payload.get("deviceName")
        td.device_name = payload.get("deviceName")
        td.f_cnt = payload.get("fCnt") or payload.get("f_cnt")
        td.f_port = payload.get("fPort") or payload.get("fport") or payload.get("f_port")

        rssi, snr = _extract_rx_info(payload)
        td.rssi = rssi
        td.snr = snr

        obj = payload.get("object")
        if isinstance(obj, dict) and isinstance(obj.get("pixels_C"), list) \
                and len(obj["pixels_C"]) == 64:
            # El gateway ya decodificó el JSON (máxima prioridad)
            td.gateway_decoded = True
            td.sensor_ok = bool(obj.get("sensor_ok", True))
            td.thermistor_C = obj.get("thermistor_C")
            td.pixels_C = [float(v) for v in obj["pixels_C"]]
            td.pixel_min_C = obj.get("pixel_min_C", min(td.pixels_C))
            td.pixel_max_C = obj.get("pixel_max_C", max(td.pixels_C))
            td.battery_mV = obj.get("battery_mV")
            if td.rssi is None:
                td.rssi = obj.get("rssi")
            if td.snr is None:
                td.snr = obj.get("snr")
            return td

        # Formato Milesight UG56: campos decodificados a nivel raíz
        if isinstance(payload.get("pixels_C"), list) and len(payload["pixels_C"]) == 64:
            td.gateway_decoded = True
            td.sensor_ok = bool(payload.get("sensor_ok", True))
            td.thermistor_C = payload.get("thermistor_C")
            td.pixels_C = [float(v) for v in payload["pixels_C"]]
            td.pixel_min_C = payload.get("pixel_min_C", min(td.pixels_C))
            td.pixel_max_C = payload.get("pixel_max_C", max(td.pixels_C))
            td.battery_mV = payload.get("battery_mV")
            if td.battery_mV is None and "battery_V" in payload:
                td.battery_mV = round(payload["battery_V"] * 1000)
            if td.rssi is None:
                td.rssi = payload.get("rssi")
            if td.snr is None:
                td.snr = payload.get("snr")
            return td

        # Fallback: decodificar payload crudo
        b64 = payload.get("data")
        if b64:
            try:
                dec = decode_uplink_data(b64)
                td.gateway_decoded = False
                td.sensor_ok = dec["sensor_ok"]
                td.thermistor_C = dec["thermistor_C"]
                td.pixels_C = dec["pixels_C"]
                td.pixel_min_C = dec["pixel_min_C"]
                td.pixel_max_C = dec["pixel_max_C"]
                td.battery_mV = dec["battery_mV"]
                return td
            except PayloadDecodeError:
                self._push_status("error", "No se pudo decodificar el payload crudo")
                return None

        # Ni object ni data decodificable
        self._push_status("error", "Mensaje sin 'object.pixels_C' ni 'data' decodificable")
        return None

    def _push_status(self, level, text):
        self.out_queue.put(("status", level, text))
