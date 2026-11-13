"""
app.py

Aplicación de escritorio para visualizar en tiempo real los datos del
nodo LoRaWAN con termocámara AMG8833 (matriz infrarroja 8x8).

Muestra:
  - Mapa térmico interpolado (8x8 -> imagen suave grande) con colorbar.
  - Tarjetas KPI: temp mín/máx, termistor, batería (V y %), RSSI/SNR.
  - Estado del sensor, última actualización y contador de frames.
  - Historial de temperatura máx/mín a lo largo del tiempo.

La conexión MQTT corre en un hilo separado y envía los datos a la GUI
mediante una cola thread-safe.
"""

import json
import os
import queue
import sys
import time

import tkinter as tk
from tkinter import ttk, Canvas, Frame

import paho.mqtt  # noqa: F401 (asegura dependencia; se usa en mqtt_client)

from PIL import Image, ImageTk

import numpy as np

from mqtt_client import MQTTBridge
from thermal_render import (
    render_thermal_heatmap,
    render_colorbar,
)


# ----------------------------------------------------------------------
# Paleta de colores (tema oscuro "dashboard")
# ----------------------------------------------------------------------
BG = "#0f1117"
PANEL = "#171a23"
PANEL2 = "#1d202b"
BORDER = "#2a2f3a"
TEXT = "#e8eaf0"
TEXT_DIM = "#98a2b3"
ACCENT = "#4f8cff"
GOOD = "#2fd26f"
WARN = "#f5a524"
BAD = "#f0445c"
INFO = "#4f8cff"


def load_config(path="config.json"):
    """Carga la configuración; si no existe, devuelve valores por defecto."""
    defaults = {
        "broker": {"host": "192.168.2.30", "port": 1883,
                   "username": "", "password": ""},
        "topic": "application/+/device/+/event/up",
        "device_eui_filter": "70b3d56f27cee98b",
        "colormap": "turbo",
        "heatmap_size": 720,
        "default_frame_period_s": 60,
        "window": {"title": "Termocámara LoRaWAN AMG8833",
                   "width": 1240, "height": 860},
    }
    try:
        with open(path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        # fusionar con defaults
        for k, v in defaults.items():
            if k == "broker":
                full = dict(v)
                full.update(cfg.get("broker", {}))
                cfg[k] = full
            else:
                cfg.setdefault(k, v)
        return cfg
    except Exception:
        return defaults


# ----------------------------------------------------------------------
# Widgets reutilizables
# ----------------------------------------------------------------------
class Card(tk.Frame):
    """Panel con fondo y borde definidos (estilo dashboard)."""
    def __init__(self, master, **kw):
        super().__init__(master, bg=PANEL, highlightbackground=BORDER,
                         highlightthickness=1, **kw)


class MetricCard(Card):
    """Tarjeta con etiqueta + valor principal + subvalor."""

    def __init__(self, master, title, unit="", accent=ACCENT, right=False):
        super().__init__(master)
        self._accent = accent
        self._value_var = tk.StringVar(value="--")
        self._sub_var = tk.StringVar(value="")

        self._top = tk.Frame(self, bg=PANEL)
        self._top.pack(fill="x", padx=12, pady=(10, 2))

        tk.Label(self._top, text=title, bg=PANEL, fg=TEXT_DIM,
                 font=("Segoe UI", 10)).pack(side="left")
        if unit:
            tk.Label(self._top, text=unit, bg=PANEL, fg=TEXT_DIM,
                     font=("Segoe UI", 10)).pack(side="right")

        self._value_label = tk.Label(self, textvariable=self._value_var,
                                     bg=PANEL, fg=accent,
                                     font=("Segoe UI", 26, "bold"))
        self._value_label.pack(anchor="w", padx=12, pady=(0, 0))

        self._sub_label = tk.Label(self, textvariable=self._sub_var,
                                   bg=PANEL, fg=TEXT_DIM,
                                   font=("Segoe UI", 9))
        self._sub_label.pack(anchor="w", padx=12, pady=(0, 10))

    def set(self, value, sub=None, color=None):
        self._value_var.set(value)
        if sub is not None:
            self._sub_var.set(sub)
        if color:
            self._value_label.configure(fg=color)
        else:
            self._value_label.configure(fg=self._accent)


class TitleBar(tk.Frame):
    def __init__(self, master, left_title, right_title=""):
        super().__init__(master, bg=BG)
        tk.Label(self, text=left_title, bg=BG, fg=TEXT,
                 font=("Segoe UI", 15, "bold")).pack(side="left")
        if right_title:
            tk.Label(self, text=right_title, bg=BG, fg=TEXT_DIM,
                     font=("Segoe UI", 10)).pack(side="right")


# ----------------------------------------------------------------------
# Vista del mapa térmico
# ----------------------------------------------------------------------
class ThermalPanel(Card):
    def __init__(self, master):
        super().__init__(master)
        self._img_tk = None
        self._bar_tk = None

        header = tk.Frame(self, bg=PANEL)
        header.pack(fill="x", padx=12, pady=(10, 6))
        tk.Label(header, text="MAPAS TÉRMICO", bg=PANEL, fg=TEXT_DIM,
                 font=("Segoe UI", 10, "bold")).pack(side="left")
        self._range_label = tk.Label(header, text="", bg=PANEL, fg=TEXT_DIM,
                                     font=("Segoe UI", 9))
        self._range_label.pack(side="right")

        body = tk.Frame(self, bg=PANEL)
        body.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        self._canvas_label = tk.Label(body, bg=PANEL)
        self._canvas_label.pack(side="left", fill="both", expand=True)

        self._bar_label = tk.Label(body, bg=PANEL, width=54)
        self._bar_label.pack(side="left", padx=(4, 0), fill="y")
        self._bar_label.pack(fill="y")

        # etiqueta "esperando datos"
        self._placeholder = tk.Label(self, text="Esperando datos...",
                                     bg=PANEL, fg=TEXT_DIM,
                                     font=("Segoe UI", 13))
        self._placeholder.place(relx=0.5, rely=0.5, anchor="center")

    def sample_placeholder(self):
        # imagen de espera: gradiente vacío
        size = 360
        arr = np.full((size, size, 3), 18, dtype=np.uint8)
        img = Image.fromarray(arr, mode="RGB")
        return self._apply_placeholder(img)

    def _apply_placeholder(self, img):
        return img

    def update(self, pixels_C, vmin, vmax):
        self._placeholder.place_forget()

        try:
            img, _vmin, _vmax = render_thermal_heatmap(
                pixels_C, size=640, vmin=vmin, vmax=vmax)
        except Exception:
            return

        self._img_tk = ImageTk.PhotoImage(img)
        self._canvas_label.configure(image=self._img_tk)

        bar = render_colorbar(height=img.size[1], width=30, vmin=_vmin, vmax=_vmax)
        self._bar_tk = ImageTk.PhotoImage(bar)
        self._bar_label.configure(image=self._bar_tk)

        self._range_label.configure(
            text=f"escala: {_vmin:.1f} °C  —  {_vmax:.1f} °C")

    def clear(self):
        self._img_tk = None
        self._bar_tk = None
        self._canvas_label.configure(image="")
        self._bar_label.configure(image="")
        self._placeholder.place(relx=0.5, rely=0.5, anchor="center")


# ----------------------------------------------------------------------
# Historial (temperatura máx/mín)
# ----------------------------------------------------------------------
class HistoryChart(Card):
    MAX_POINTS = 300

    def __init__(self, master):
        super().__init__(master, height=140)
        self.pack_propagate(False)
        self._values = []  # pares (min, max, timestamp)
        self._canvas_tk = None

        header = tk.Frame(self, bg=PANEL)
        header.pack(fill="x", padx=12, pady=(8, 2))
        tk.Label(header, text="HISTORIAL TEMP. MÁX / MÍN", bg=PANEL,
                 fg=TEXT_DIM, font=("Segoe UI", 9, "bold")).pack(side="left")

        self._plot = Canvas(self, bg=PANEL, highlightthickness=0)
        self._plot.pack(fill="both", expand=True, padx=8, pady=(0, 10))

    def push(self, tmin, tmax):
        self._values.append((tmin, tmax, time.time()))
        if len(self._values) > self.MAX_POINTS:
            self._values = self._values[-self.MAX_POINTS:]
        self._redraw()

    def _redraw(self):
        c = self._plot
        c.delete("all")
        w = c.winfo_width()
        h = c.winfo_height()
        if w < 10 or h < 10 or w > 10:
            w = c.winfo_width()
        if w < 10:
            return

        pad_l, pad_r, pad_t, pad_b = 34, 8, 12, 20
        plot_w = w - pad_l - pad_r
        plot_h = h - pad_t - pad_b
        if plot_w <= 0 or plot_h <= 0:
            return

        if not self._values:
            c.create_text(w / 2, h / 2, text="Esperando datos...",
                          fill=TEXT_DIM, font=("Segoe UI", 10))
            return

        allv = [v for pair in self._values for v in (pair[0], pair[1])]
        lo, hi = min(allv), max(allv)
        if hi - lo < 0.5:
            mid = (hi + lo) / 2
            lo, hi = mid - 0.5, mid + 0.5
        lo -= 0.5
        hi += 0.5

        n = len(self._values)
        x = lambda i: pad_l + (i / (n - 1)) * plot_w if n > 1 else pad_l + plot_w / 2
        y = lambda v: pad_t + plot_h - ((v - lo) / (hi - lo)) * plot_h

        # grid
        for g in range(0, 5):
            gy = pad_t + plot_h * g / 4
            c.create_line(pad_l, gy, pad_l + plot_w, gy, fill="#232733",
                          width=1)
            gval = hi - (hi - lo) * g / 4
            c.create_text(pad_l - 6, gy, text=f"{gval:.1f}", anchor="e",
                          fill=TEXT_DIM, font=("Segoe UI", 8))

        # líneas máx y mín
        coords_min = []
        coords_max = []
        for i in range(n):
            coords_min.append(x(i))
            coords_min.append(y(self._values[i][0]))
            coords_max.append(x(i))
            coords_max.append(y(self._values[i][1]))
        c.create_line(coords_min, fill="#4f8cff", width=2, smooth=True)
        c.create_line(coords_max, fill="#f0445c", width=2, smooth=True)

        # leyenda
        c.create_line(pad_l + plot_w - 118, pad_t + 8, pad_l + plot_w - 102,
                      pad_t + 8, fill="#4f8cff", width=2)
        c.create_text(pad_l + plot_w - 98, pad_t + 8, text="Mín", anchor="w",
                      fill=TEXT_DIM, font=("Segoe UI", 8))
        c.create_line(pad_l + plot_w - 48, pad_t + 8, pad_l + plot_w - 32,
                      pad_t + 8, fill="#f0445c", width=2)
        c.create_text(pad_l + plot_w - 28, pad_t + 8, text="Máx", anchor="w",
                      fill=TEXT_DIM, font=("Segoe UI", 8))


# ----------------------------------------------------------------------
# Aplicación principal
# ----------------------------------------------------------------------
class ThermalApp:
    def __init__(self, root, config):
        self.root = root
        self.cfg = config
        self.bridge = MQTTBridge(config)
        self.packet_count = 0
        self.last_data = None
        self._fixed_scale = False
        self._hist = []

        win = config["window"]
        root.title(win["title"])
        root.geometry(f"{win['width']}x{win['height']}")
        root.configure(bg=BG)
        root.minsize(1000, 700)

        self._build_ui()

        # Timer para procesar la cola MQTT cada 60 ms
        self.root.after(60, self._poll_queue)

        # Iniciar conexión
        self._connect()

    # -- UI -----------------------------------------------------------
    def _build_ui(self):
        # Barra superior
        self._build_statusbar()

        # Cuerpo: mapa a la izquierda, KPIs y estado a la derecha
        body = tk.Frame(self.root, bg=BG)
        body.pack(fill="both", expand=True, padx=14, pady=(6, 4))

        # Columna izquierda: mapa térmico
        left = tk.Frame(body, bg=BG)
        left.pack(side="left", fill="both", expand=True)
        self.thermal = ThermalPanel(left)
        self.thermal.pack(fill="both", expand=True)

        # Columna derecha
        right = tk.Frame(body, bg=BG, width=370)
        right.pack(side="right", fill="y", padx=(12, 0))
        right.pack_propagate(False)

        # Tarjetas KPI (2x2)
        grid = tk.Frame(right, bg=BG)
        grid.pack(fill="x")

        row1 = tk.Frame(grid, bg=BG)
        row1.pack(fill="x", pady=(0, 8))
        self.card_min = MetricCard(row1, "TEMP MÍN", "°C", accent="#4f8cff")
        self.card_max = MetricCard(row1, "TEMP MÁX", "°C", accent="#f0445c")
        self.card_min.pack(side="left", fill="x", expand=True)
        self.card_max.pack(side="left", fill="x", expand=True, padx=(8, 0))

        row2 = tk.Frame(grid, bg=BG)
        row2.pack(fill="x", pady=(0, 8))
        self.card_therm = MetricCard(row2, "TERMISTOR", "°C", accent="#f5a524")
        self.card_bat = MetricCard(row2, "BATERÍA", "", accent=GOOD)
        self.card_therm.pack(side="left", fill="x", expand=True)
        self.card_bat.pack(side="left", fill="x", expand=True, padx=(8, 0))

        row3 = tk.Frame(grid, bg=BG)
        row3.pack(fill="x")
        self.card_rssi = MetricCard(row3, "RSSI", "dBm", accent=ACCENT)
        self.card_snr = MetricCard(row3, "SNR", "dB", accent=ACCENT)
        self.card_rssi.pack(side="left", fill="x", expand=True)
        self.card_snr.pack(side="left", fill="x", expand=True, padx=(8, 0))

        # Estado
        state = tk.Frame(right, bg=BG)
        state.pack(fill="x", pady=(12, 0))
        self._build_state_panel(state)

        # Historial
        hist = tk.Frame(right, bg=BG)
        hist.pack(fill="both", expand=True, pady=(12, 0))
        self.chart = HistoryChart(hist)
        self.chart.pack(fill="both", expand=True)

    def _build_statusbar(self):
        bar = tk.Frame(self.root, bg=BG)
        bar.pack(fill="x", padx=14, pady=(10, 4))

        tk.Label(bar, text="AMG8833 · TERMOCÁMARA LoRaWAN",
                 bg=BG, fg=TEXT, font=("Segoe UI", 17, "bold")).pack(side="left")

        self._conn_dot = tk.Label(bar, text="●", bg=BG, fg=WARN,
                                  font=("Segoe UI", 14))
        self._conn_dot.pack(side="left", padx=(18, 6))
        self._conn_label = tk.Label(bar, text="Conectando...", bg=BG,
                                    fg=TEXT_DIM, font=("Segoe UI", 10))
        self._conn_label.pack(side="left")

        self._dev_label = tk.Label(bar, text="", bg=BG, fg=TEXT_DIM,
                                   font=("Segoe UI", 10))
        self._dev_label.pack(side="right")

        self._frame_label = tk.Label(bar, text="Frames: 0", bg=BG, fg=TEXT_DIM,
                                     font=("Segoe UI", 10))
        self._frame_label.pack(side="right", padx=(0, 18))

    def _build_state_panel(self, parent):
        card = Card(parent)
        card.pack(fill="x")

        inner = tk.Frame(card, bg=PANEL)
        inner.pack(fill="x", padx=12, pady=10)

        tk.Label(inner, text="ESTADO DEL SENSOR", bg=PANEL, fg=TEXT_DIM,
                 font=("Segoe UI", 9, "bold")).pack(anchor="w")

        # línea del sensor_ok
        srow = tk.Frame(inner, bg=PANEL)
        srow.pack(fill="x", pady=(8, 0))
        tk.Label(srow, text="Sensor", bg=PANEL, fg=TEXT_DIM,
                 font=("Segoe UI", 10)).pack(side="left")
        self._sensor_dot = tk.Label(srow, text="●", bg=PANEL, fg=WARN,
                                    font=("Segoe UI", 12))
        self._sensor_dot.pack(side="right")
        self._sensor_label = tk.Label(srow, text="Desconocido", bg=PANEL,
                                      fg=TEXT_DIM, font=("Segoe UI", 10))
        self._sensor_label.pack(side="right", padx=(0, 6))

        # última actualización
        urow = tk.Frame(inner, bg=PANEL)
        urow.pack(fill="x", pady=(4, 0))
        tk.Label(urow, text="Última actualización", bg=PANEL, fg=TEXT_DIM,
                 font=("Segoe UI", 10)).pack(side="left")
        self._last_update = tk.Label(urow, text="--:--:--", bg=PANEL, fg=TEXT,
                                     font=("Segoe UI", 11, "bold"))
        self._last_update.pack(side="right")

        # Decodificación
        drows = tk.Frame(inner, bg=PANEL)
        drows.pack(fill="x", pady=(4, 0))
        tk.Label(drows, text="Decodificación", bg=PANEL, fg=TEXT_DIM,
                 font=("Segoe UI", 10)).pack(side="left")
        self._dec_label = tk.Label(drows, text="—", bg=PANEL, fg=TEXT_DIM,
                                   font=("Segoe UI", 10))
        self._dec_label.pack(side="right")

        # alcance de escala
        srow2 = tk.Frame(inner, bg=PANEL)
        srow2.pack(fill="x", pady=(6, 0))
        self._scale_btn = tk.Button(
            srow2, text="Escala automática", command=self._toggle_scale,
            bg=PANEL2, fg=TEXT, relief="flat", font=("Segoe UI", 9),
            activebackground="#232733", activeforeground=TEXT,
            cursor="hand2", padx=8, pady=4)
        self._scale_btn.pack(side="left")
        self._scale_state = tk.Label(srow2, text="auto", bg=PANEL, fg=GOOD,
                                     font=("Segoe UI", 9, "bold"))
        self._scale_state.pack(side="right")

    # -- Conexión & cola ----------------------------------------------
    def _connect(self):
        self.bridge.start()

    def _poll_queue(self):
        try:
            while True:
                item = self.bridge.out_queue.get_nowait()
                if isinstance(item, tuple) and item and item[0] == "status":
                    _, level, text = item
                    self._on_status(level, text)
                elif isinstance(item, tuple) and item and item[0] == "error":
                    _, text = item
                    self._on_status("error", text)
                elif hasattr(item, "to_dict"):
                    self._on_data(item)
        except queue.Empty:
            pass

        # chivato de tiempo muerto (no muestra datos) - desconexión
        self.root.after(60, self._poll_queue)

    def _on_status(self, level, text):
        if level == "connect":
            self._conn_dot.configure(fg=GOOD)
            self._conn_label.configure(text="Conectado al broker",
                                       fg=TEXT_DIM)
        elif level == "error":
            self._conn_dot.configure(fg=BAD)
            self._conn_label.configure(text=text, fg=BAD)

    def _on_data(self, td):
        self.packet_count += 1
        self._frame_label.configure(text=f"Frames: {self.packet_count}")
        self._last_update.configure(text=td.received_time_str)

        if td.device_name or td.dev_eui:
            self._dev_label.configure(text=td.device_name or td.dev_eui)

        self._dec_label.configure(
            text="Gateway" if td.gateway_decoded else "Local (fallback)")

        # Sensor OK
        if td.sensor_ok:
            self._sensor_dot.configure(fg=GOOD)
            self._sensor_label.configure(text="OK", fg=GOOD)
        else:
            self._sensor_dot.configure(fg=BAD)
            self._sensor_label.configure(text="FALLO", fg=BAD)

        # Píxeles
        px = td.pixels_C
        if px:
            if not self._fixed_scale:
                vmin, vmax = None, None
            else:
                vmin = self._last_vmin
                vmax = self._last_vmax
            self.thermal.update(px, vmin, vmax)
            self._last_vmin = float(min(px))
            self._last_vmax = float(max(px))

            # min/max cards
            if td.pixel_min_C is not None:
                self.card_min.set(f"{td.pixel_min_C:.1f}")
            else:
                self.card_min.set(f"{min(px):.1f}")
            if td.pixel_max_C is not None:
                self.card_max.set(f"{td.pixel_max_C:.1f}")
            else:
                self.card_max.set(f"{max(px):.1f}")

            # historial
            tmn = float(min(px))
            tmx = float(max(px))
            self.chart.push(tmn, tmx)

        # termistor
        if td.thermistor_C is not None:
            self.card_therm.set(f"{td.thermistor_C:.1f}")

        # batería
        if td.battery_mV is not None:
            mv = td.battery_mV
            v = mv / 1000.0
            pct = min(100, max(0, round((mv - 3000) / (4200 - 3000) * 100)))
            color = GOOD
            if pct < 30:
                color = WARN
            if pct < 15:
                color = BAD
            self.card_bat.set(f"{v:.2f} V", sub=f"{pct} %", color=color)

        # señal
        if td.rssi is not None:
            color = ACCENT
            if td.rssi < -95:
                color = BAD
            elif td.rssi < -80:
                color = WARN
            self.card_rssi.set(f"{td.rssi}", color=color)
        if td.snr is not None:
            color = ACCENT
            if td.snr < 0:
                color = BAD
            elif td.snr < 6:
                color = WARN
            self.card_snr.set(f"{td.snr:.1f}", color=color)

    def _toggle_scale(self):
        self._fixed_scale = not self._fixed_scale
        if self._fixed_scale:
            self._scale_btn.configure(text="Escala fija")
            self._scale_state.configure(text="fija", fg=WARN)
        else:
            self._scale_btn.configure(text="Escala automática")
            self._scale_state.configure(text="auto", fg=GOOD)

    def on_close(self):
        try:
            self.bridge.stop()
        except Exception:
            pass
        self.root.destroy()


# ----------------------------------------------------------------------
# Punto de entrada
# ----------------------------------------------------------------------
def main():
    config = load_config()
    root = tk.Tk()
    app = ThermalApp(root, config)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
