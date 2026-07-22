"""MegKnob 24-channel Hall oscilloscope and baseline recorder."""

from __future__ import annotations

import argparse
import csv
import json
import os
import statistics
import struct
import sys
import threading
import time
from collections import deque

import serial
from serial.tools import list_ports

MAGIC = b"MK"
FRAME = struct.Struct("<2sBBBBHI24HH")
COMMAND_MAGIC = b"MC"
RESPONSE_MAGIC = b"MR"
COMMAND_FRAME = struct.Struct("<2sBBBBH8sH")
COMMAND_GET_CONFIG = 1
COMMAND_SET_CONFIG = 2
COMMAND_SAVE_CONFIG = 3
COMMAND_RESET_CONFIG = 4
COMMAND_SET_STREAM = 5
COMMAND_PING = 6
COMMAND_STATUS = {
    0: "OK", 1: "协议版本不支持", 2: "命令长度错误", 3: "未知命令",
    4: "参数超出范围", 5: "Flash 存储失败",
}
MODE_NAMES = ("U26 · ADC3", "U27 · ADC2", "U28 · ADC1", "ALL · 24 CH")
CHANNEL_COLORS = (
    "#ffd000", "#00d8ff", "#ff4dcb", "#57e389", "#ff7b45", "#9d7cff", "#f5f5f5", "#72ffda",
    "#ffd000", "#00d8ff", "#ff4dcb", "#57e389", "#ff7b45", "#9d7cff", "#f5f5f5", "#72ffda",
    "#ffd000", "#00d8ff", "#ff4dcb", "#57e389", "#ff7b45", "#9d7cff", "#f5f5f5", "#72ffda",
)


def crc16(data: bytes) -> int:
    crc = 0xFFFF
    for value in data:
        crc ^= value << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


class Metrics:
    def __init__(self) -> None:
        self.started = time.perf_counter()
        self.frames = self.data_frames = self.mode_frames = 0
        self.bytes = self.crc_errors = self.lost_frames = 0
        self.last_seq = self.last_device_raw = self.last_data_us = self.last_version = None
        self.device_wrap_base = 0
        self.periods_us: deque[float] = deque(maxlen=2000)
        self.perf = {"scan_us": 0, "address_us": 0, "adc_us": 0, "process_us": 0}

    def add_bytes(self, count: int) -> None: self.bytes += count
    def add_crc_error(self) -> None: self.crc_errors += 1

    def add_frame(self, version: int, kind: int, seq: int, device_tick: int) -> float:
        self.frames += 1
        if self.last_seq is not None:
            gap = (seq - self.last_seq) & 0xFFFF
            if 1 < gap < 0x8000: self.lost_frames += gap - 1
        self.last_seq = seq
        if self.last_version != version:
            self.last_device_raw = self.last_data_us = None
            self.device_wrap_base = 0
        elif self.last_device_raw is not None and device_tick < self.last_device_raw:
            backward = self.last_device_raw - device_tick
            if backward > 0x80000000:
                # Protocol v3 uses a uint32 microsecond timestamp, which wraps
                # normally every ~71.6 minutes. Python integers keep the
                # unwrapped host-side timeline effectively unlimited.
                self.device_wrap_base += 1 << 32
        self.last_device_raw = device_tick
        self.last_version = version
        device_us = float(self.device_wrap_base + device_tick)
        if kind == 1:
            self.data_frames += 1
            if self.last_data_us is not None:
                delta_us = device_us - self.last_data_us
                if 0 < delta_us < 1_000_000: self.periods_us.append(delta_us)
            self.last_data_us = device_us
        elif kind == 2:
            self.mode_frames += 1
        return device_us

    def add_perf(self, values) -> None:
        self.perf = dict(zip(("scan_us", "address_us", "adc_us", "process_us"), values[:4]))

    def snapshot(self) -> dict[str, float | int]:
        elapsed = max(time.perf_counter() - self.started, 1e-6)
        periods_us = list(self.periods_us)
        mean_us = statistics.fmean(periods_us) if periods_us else 0.0
        return {
            "duration_s": elapsed, "data_frames": self.data_frames,
            "host_receive_hz": self.data_frames / elapsed,
            "device_scan_hz": 1_000_000.0 / mean_us if mean_us else 0.0,
            "period_mean_ms": mean_us / 1000.0,
            "period_min_ms": min(periods_us, default=0) / 1000.0,
            "period_max_ms": max(periods_us, default=0) / 1000.0,
            "period_jitter_stdev_ms": statistics.pstdev(periods_us) / 1000.0 if len(periods_us) > 1 else 0.0,
            "lost_frames": self.lost_frames, "crc_errors": self.crc_errors,
            "throughput_bytes_s": self.bytes / elapsed, **self.perf,
        }


def decode_frames(buffer: bytearray, metrics: Metrics, responses: list | None = None):
    decoded = []
    while True:
        stream_at = buffer.find(MAGIC)
        response_at = buffer.find(RESPONSE_MAGIC) if responses is not None else -1
        starts = [offset for offset in (stream_at, response_at) if offset >= 0]
        if not starts:
            del buffer[:-1]
            break
        start = min(starts)
        if start: del buffer[:start]
        if response_at == start and (stream_at < 0 or response_at < stream_at):
            if len(buffer) < COMMAND_FRAME.size: break
            raw = bytes(buffer[:COMMAND_FRAME.size])
            try:
                response = decode_response(raw)
            except ValueError:
                metrics.add_crc_error(); del buffer[0]; continue
            del buffer[:COMMAND_FRAME.size]
            responses.append(response)
            continue
        if len(buffer) < FRAME.size: break
        raw = bytes(buffer[:FRAME.size])
        if crc16(raw[:-2]) != int.from_bytes(raw[-2:], "little"):
            metrics.add_crc_error(); del buffer[0]; continue
        del buffer[:FRAME.size]
        magic, version, kind, mode, count, seq, timestamp, *tail = FRAME.unpack(raw)
        if version != 3 or mode > 3: continue
        device_us = metrics.add_frame(version, kind, seq, timestamp)
        values = tuple(tail[:count])
        if kind == 3 and count >= 4: metrics.add_perf(values)
        timestamp_ms = device_us / 1000.0
        decoded.append((kind, mode, seq, timestamp_ms,
                        values if kind == 1 and count == 24 else None))
    return decoded


def encode_command(command: int, request_id: int, payload: bytes = b"") -> bytes:
    if len(payload) > 8:
        raise ValueError("command payload is limited to 8 bytes")
    padded = payload.ljust(8, b"\0")
    raw = COMMAND_FRAME.pack(COMMAND_MAGIC, 1, command, len(payload), 0, request_id, padded, 0)
    return raw[:-2] + struct.pack("<H", crc16(raw[:-2]))


def decode_response(raw: bytes) -> dict[str, int | bytes]:
    if len(raw) != COMMAND_FRAME.size:
        raise ValueError("invalid response length")
    magic, version, command, length, status, request_id, payload, received_crc = COMMAND_FRAME.unpack(raw)
    if magic != RESPONSE_MAGIC or version != 1 or length > 8 or crc16(raw[:-2]) != received_crc:
        raise ValueError("invalid response frame")
    return {"command": command, "status": status, "request_id": request_id, "payload": payload[:length]}


def capture_baseline(port: str, seconds: float) -> dict[str, float | int]:
    metrics, buffer = Metrics(), bytearray()
    with serial.Serial(port, 115200, timeout=0.1) as device:
        device.dtr = True
        deadline = time.perf_counter() + seconds
        while time.perf_counter() < deadline:
            chunk = device.read(512); metrics.add_bytes(len(chunk)); buffer.extend(chunk)
            decode_frames(buffer, metrics)
    return metrics.snapshot()


def run_gui() -> None:
    try:
        os.environ["PYQTGRAPH_QT_LIB"] = "PyQt5"
        import numpy as np
        import pyqtgraph as pg
        from PyQt5 import QtCore, QtGui, QtWidgets
    except ImportError as exc:
        raise SystemExit(
            "GUI dependencies are missing. Run: python -m pip install -r "
            "tools/requirements-hall-viewer.txt"
        ) from exc

    class SerialReader(QtCore.QThread):
        metrics_changed = QtCore.pyqtSignal(object)
        response_received = QtCore.pyqtSignal(object)
        failed = QtCore.pyqtSignal(str)

        def __init__(self, port: str):
            super().__init__(); self.port = port; self.keep_running = True; self.metrics = Metrics()
            self.device = None; self.request_id = 0
            self.outgoing = deque(); self.outgoing_lock = threading.Lock()
            # Bound latency: old acquisition frames are less valuable than the live signal.
            self.pending = deque(maxlen=64)
            self.pending_lock = threading.Lock()
            self.ui_dropped_frames = 0

        def run(self):
            buffer = bytearray(); last_metrics = 0.0
            try:
                with serial.Serial(self.port, 115200, timeout=0.02) as device:
                    self.device = device; device.dtr = True
                    while self.keep_running:
                        with self.outgoing_lock:
                            outgoing = list(self.outgoing); self.outgoing.clear()
                        for frame in outgoing:
                            device.write(frame)
                        if outgoing: device.flush()
                        chunk = device.read(512); self.metrics.add_bytes(len(chunk)); buffer.extend(chunk)
                        responses = []
                        decoded = decode_frames(buffer, self.metrics, responses)
                        for response in responses:
                            self.response_received.emit(response)
                        if decoded:
                            arrival_ms = time.perf_counter() * 1000.0
                            stamped = [(*frame, arrival_ms) for frame in decoded]
                            with self.pending_lock:
                                self.ui_dropped_frames += max(0, len(self.pending) + len(stamped) - self.pending.maxlen)
                                self.pending.extend(stamped)
                        now = time.perf_counter()
                        if now - last_metrics >= 0.25:
                            self.metrics_changed.emit(self.metrics.snapshot()); last_metrics = now
            except serial.SerialException as exc:
                self.failed.emit(str(exc))
            finally:
                self.device = None

        def send_command(self, command, payload=b""):
            if self.device is None or not self.keep_running:
                return False
            self.request_id = (self.request_id + 1) & 0xFFFF or 1
            frame = encode_command(command, self.request_id, payload)
            with self.outgoing_lock:
                self.outgoing.append(frame)
            return True

        def stop(self):
            self.keep_running = False; self.wait(1000)

        def take_pending(self):
            with self.pending_lock:
                frames = list(self.pending); self.pending.clear()
            return frames

        def ui_dropped(self):
            with self.pending_lock: return self.ui_dropped_frames

    class ScopePlotWidget(pg.PlotWidget):
        """Keep pyqtgraph's scene item synchronized after splitter/window resizes."""

        def resizeEvent(self, event):
            super().resizeEvent(event)
            QtCore.QTimer.singleShot(0, self.sync_scene_geometry)

        def sync_scene_geometry(self):
            # QGraphicsView scene units are not physical pixels. Mapping the viewport
            # rectangle is essential when moving between monitors with different DPI.
            scene_rect = self.mapToScene(self.viewport().rect()).boundingRect()
            self.setSceneRect(scene_rect)
            self.getPlotItem().setGeometry(scene_rect)

        def showEvent(self, event):
            super().showEvent(event)
            handle = self.window().windowHandle()
            if handle is not None and not getattr(self, "_screen_hooked", False):
                handle.screenChanged.connect(lambda _screen: QtCore.QTimer.singleShot(50, self.sync_scene_geometry))
                self._screen_hooked = True

    class ScopeWindow(QtWidgets.QMainWindow):
        def __init__(self):
            super().__init__()
            self.setWindowTitle("MEGKNOB · HALL ANALYZER")
            self.resize(1500, 900)
            self.reader = None; self.running = True; self.mode = 0
            self.device_info = {}; self.device_config = None
            self.window_seconds = 2.0; self.history = deque(); self.latest = [0] * 24
            self.curves = []; self.channel_checks = []; self.value_labels = []
            self.csv_file = self.csv_writer = None
            self.display_lag_ms = 0.0
            self.last_label_update = 0.0
            self.setStyleSheet("""
                QMainWindow, QWidget { background:#101215; color:#d9dde3; font-family:'Segoe UI'; font-size:10pt; }
                QToolBar { background:#171a1f; border-bottom:1px solid #343942; spacing:8px; padding:9px; }
                QPushButton, QComboBox { background:#242830; border:1px solid #424954; border-radius:3px; padding:7px 11px; min-height:18px; }
                QPushButton:hover, QComboBox:hover { border-color:#e6b800; }
                QPushButton:checked { background:#5b4900; border-color:#ffd000; color:#ffd000; }
                QGroupBox { border:1px solid #343942; margin-top:9px; padding-top:10px; font-weight:600; }
                QGroupBox::title { subcontrol-origin:margin; left:8px; color:#9da5b2; }
                QCheckBox { spacing:7px; }
                QScrollArea { border:0; }
                QStatusBar { background:#171a1f; border-top:1px solid #343942; }
                QLabel#brand { color:#ffd000; font-size:17px; font-weight:700; letter-spacing:2px; }
                QLabel#mode { color:#ffd000; font-size:14px; font-weight:700; }
                QLabel#measure { background:#171a1f; border:1px solid #343942; padding:10px; font-family:'Segoe UI'; }
            """)
            self.build_toolbar(); self.build_body(); self.build_status()
            self.refresh_ports()
            self.timer = QtCore.QTimer(self); self.timer.timeout.connect(self.redraw); self.timer.start(40)

        def build_toolbar(self):
            bar = QtWidgets.QToolBar(); bar.setMovable(False); self.addToolBar(bar)
            brand = QtWidgets.QLabel(" MEGKNOB  "); brand.setObjectName("brand"); bar.addWidget(brand)
            bar.addSeparator(); self.port_box = QtWidgets.QComboBox(); self.port_box.setMinimumWidth(230); bar.addWidget(self.port_box)
            refresh = QtWidgets.QPushButton("刷新"); refresh.clicked.connect(self.refresh_ports); bar.addWidget(refresh)
            self.connect_btn = QtWidgets.QPushButton("连接"); self.connect_btn.clicked.connect(self.toggle_connection); bar.addWidget(self.connect_btn)
            bar.addSeparator(); self.run_btn = QtWidgets.QPushButton("RUN"); self.run_btn.setCheckable(True); self.run_btn.setChecked(True)
            self.run_btn.clicked.connect(self.toggle_run); bar.addWidget(self.run_btn)
            clear = QtWidgets.QPushButton("清屏"); clear.clicked.connect(self.clear_history); bar.addWidget(clear)
            autoscale = QtWidgets.QPushButton("自动量程"); autoscale.clicked.connect(self.autoscale); bar.addWidget(autoscale)
            shot = QtWidgets.QPushButton("截图"); shot.clicked.connect(self.save_screenshot); bar.addWidget(shot)
            self.record_btn = QtWidgets.QPushButton("记录 CSV"); self.record_btn.setCheckable(True)
            self.record_btn.clicked.connect(self.toggle_csv_recording); bar.addWidget(self.record_btn)
            bar.addSeparator(); bar.addWidget(QtWidgets.QLabel(" 时基 "))
            self.time_box = QtWidgets.QComboBox(); self.time_box.addItems(("100 ms", "200 ms", "500 ms", "1 s", "2 s", "5 s", "10 s", "20 s")); self.time_box.setCurrentText("2 s")
            self.time_box.currentTextChanged.connect(self.update_timebase); bar.addWidget(self.time_box)
            bar.addWidget(QtWidgets.QLabel(" 量程 "))
            self.range_box = QtWidgets.QComboBox(); self.range_box.addItems(("2.0 V", "2.5 V", "3.3 V")); self.range_box.setCurrentText("2.0 V")
            self.range_box.currentTextChanged.connect(self.update_range); bar.addWidget(self.range_box)
            spacer = QtWidgets.QWidget(); spacer.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred); bar.addWidget(spacer)
            self.mode_label = QtWidgets.QLabel(MODE_NAMES[0] + "  "); self.mode_label.setObjectName("mode"); bar.addWidget(self.mode_label)

        def build_body(self):
            splitter = QtWidgets.QSplitter(); splitter.setHandleWidth(1); self.setCentralWidget(splitter)
            channel_panel = QtWidgets.QWidget(); channel_panel.setMinimumWidth(320); channel_panel.setMaximumWidth(380)
            panel_layout = QtWidgets.QVBoxLayout(channel_panel); panel_layout.setContentsMargins(8, 8, 8, 8)
            title = QtWidgets.QLabel("CHANNELS"); title.setStyleSheet("color:#9da5b2;font-weight:700;padding:4px"); panel_layout.addWidget(title)
            groups = QtWidgets.QHBoxLayout()
            for label, mode in (("U26", 0), ("U27", 1), ("U28", 2), ("ALL", 3)):
                button = QtWidgets.QPushButton(label); button.clicked.connect(lambda _checked, m=mode: self.select_group(m)); groups.addWidget(button)
            panel_layout.addLayout(groups)
            scroll = QtWidgets.QScrollArea(); scroll.setWidgetResizable(True); channel_list = QtWidgets.QWidget(); list_layout = QtWidgets.QVBoxLayout(channel_list)
            for ch in range(24):
                row = QtWidgets.QWidget(); layout = QtWidgets.QHBoxLayout(row); layout.setContentsMargins(2, 2, 2, 2)
                check = QtWidgets.QCheckBox(f"U{26 + ch//8} · Y{ch%8}"); check.setChecked(ch < 8); check.toggled.connect(self.apply_visibility)
                check.setMinimumWidth(105)
                check.setStyleSheet(f"QCheckBox{{color:{CHANNEL_COLORS[ch]};font-weight:600}}")
                value = QtWidgets.QLabel("— mV"); value.setAlignment(QtCore.Qt.AlignRight); value.setStyleSheet("color:#aab1bc")
                layout.addWidget(check); layout.addStretch(); layout.addWidget(value)
                list_layout.addWidget(row); self.channel_checks.append(check); self.value_labels.append(value)
            list_layout.addStretch(); scroll.setWidget(channel_list); panel_layout.addWidget(scroll); splitter.addWidget(channel_panel)

            right = QtWidgets.QWidget(); right_layout = QtWidgets.QVBoxLayout(right); right_layout.setContentsMargins(7, 7, 7, 7)
            pg.setConfigOptions(antialias=False, background="#080a0c", foreground="#aeb5bf")
            self.plot = ScopePlotWidget(); self.plot.showGrid(x=False, y=False)
            axis_style = {"color": "#aeb5bf", "font-size": "10pt", "font-family": "Segoe UI, sans-serif"}
            self.plot.setLabel("left", "VOLTAGE", units="V", **axis_style)
            self.plot.setLabel("bottom", "TIME", units="s", **axis_style)
            self.plot.setYRange(0, 2.0, padding=0); self.plot.setMouseEnabled(x=True, y=True)
            left_axis = self.plot.getPlotItem().getAxis("left")
            left_axis.setWidth(72); left_axis.enableAutoSIPrefix(False)
            self.plot.getPlotItem().getAxis("bottom").enableAutoSIPrefix(False)
            tick_font = QtGui.QFont("Consolas", 9)
            left_axis.setTickFont(tick_font); self.plot.getPlotItem().getAxis("bottom").setTickFont(tick_font)
            grid_pen = pg.mkPen("#3a4048", width=1)
            self.vertical_grid = [pg.InfiniteLine(angle=90, movable=False, pen=grid_pen) for _ in range(11)]
            self.horizontal_grid = [pg.InfiniteLine(angle=0, movable=False, pen=grid_pen) for _ in range(9)]
            for line in (*self.vertical_grid, *self.horizontal_grid):
                line.setZValue(-100); self.plot.addItem(line, ignoreBounds=True)
            self.plot.getPlotItem().vb.sigYRangeChanged.connect(
                lambda _view, y_range: self.position_horizontal_grid(y_range[0], y_range[1]))
            for ch in range(24):
                curve = self.plot.plot(pen=pg.mkPen(CHANNEL_COLORS[ch], width=1.2), name=f"U{26+ch//8} Y{ch%8}")
                curve.setClipToView(True); curve.setDownsampling(auto=True, method="peak")
                self.curves.append(curve)
            scope_row = QtWidgets.QHBoxLayout(); scope_row.addWidget(self.plot, 1)
            analysis = QtWidgets.QGroupBox("MEASUREMENTS"); analysis.setFixedWidth(230)
            analysis_layout = QtWidgets.QVBoxLayout(analysis)
            self.analysis_channel = QtWidgets.QComboBox()
            self.analysis_channel.addItems([f"U{26+ch//8} · Y{ch%8}" for ch in range(24)])
            analysis_layout.addWidget(self.analysis_channel)
            self.analysis_values = QtWidgets.QLabel("CURRENT   —\nMINIMUM   —\nMAXIMUM   —\nMEAN      —\nPEAK-PEAK —")
            self.analysis_values.setStyleSheet("font-family:'Consolas';font-size:11pt;line-height:150%;color:#d9dde3;padding:8px")
            analysis_layout.addWidget(self.analysis_values)
            config_group = QtWidgets.QGroupBox("DEVICE CONFIG")
            config_layout = QtWidgets.QFormLayout(config_group)
            self.press_spin = QtWidgets.QSpinBox(); self.press_spin.setRange(50, 3000); self.press_spin.setSuffix(" mV"); self.press_spin.setValue(900)
            self.release_spin = QtWidgets.QSpinBox(); self.release_spin.setRange(50, 3300); self.release_spin.setSuffix(" mV"); self.release_spin.setValue(1400)
            self.stable_spin = QtWidgets.QSpinBox(); self.stable_spin.setRange(1, 20); self.stable_spin.setValue(3)
            config_layout.addRow("Press", self.press_spin); config_layout.addRow("Release", self.release_spin); config_layout.addRow("Stable scans", self.stable_spin)
            config_buttons = QtWidgets.QGridLayout()
            read_config = QtWidgets.QPushButton("读取"); read_config.clicked.connect(self.read_device_config)
            apply_config = QtWidgets.QPushButton("临时应用"); apply_config.clicked.connect(self.apply_device_config)
            save_config = QtWidgets.QPushButton("保存 Flash"); save_config.clicked.connect(self.save_device_config)
            reset_config = QtWidgets.QPushButton("恢复默认"); reset_config.clicked.connect(self.reset_device_config)
            config_buttons.addWidget(read_config, 0, 0); config_buttons.addWidget(apply_config, 0, 1)
            config_buttons.addWidget(save_config, 1, 0); config_buttons.addWidget(reset_config, 1, 1)
            config_layout.addRow(config_buttons)
            self.stream_check = QtWidgets.QCheckBox("实时遥测"); self.stream_check.setChecked(True); self.stream_check.toggled.connect(self.set_stream_enabled)
            config_layout.addRow(self.stream_check)
            self.device_label = QtWidgets.QLabel("未读取设备信息"); self.device_label.setWordWrap(True); self.device_label.setStyleSheet("color:#858e9b")
            config_layout.addRow(self.device_label)
            analysis_layout.addWidget(config_group)
            analysis_layout.addStretch()
            hint = QtWidgets.QLabel("鼠标滚轮缩放\n拖动波形平移\n双击恢复视图")
            hint.setStyleSheet("color:#858e9b;padding:8px"); analysis_layout.addWidget(hint)
            scope_row.addWidget(analysis); right_layout.addLayout(scope_row, 1)
            measure_row = QtWidgets.QHBoxLayout(); self.measure_labels = {}
            for key, caption in (("rate", "SCAN RATE"), ("period", "PERIOD"), ("jitter", "JITTER"),
                                 ("lag", "DISPLAY LAG"), ("loss", "FRAME LOSS"), ("crc", "CRC ERROR")):
                label = QtWidgets.QLabel(f"{caption}\n—"); label.setObjectName("measure"); label.setAlignment(QtCore.Qt.AlignCenter)
                measure_row.addWidget(label); self.measure_labels[key] = label
            right_layout.addLayout(measure_row); splitter.addWidget(right); splitter.setStretchFactor(1, 1)
            self.update_grid_spacing()

        def build_status(self):
            self.connection_status = QtWidgets.QLabel(" DISCONNECTED "); self.statusBar().addWidget(self.connection_status)
            self.throughput_status = QtWidgets.QLabel("0 B/s  "); self.statusBar().addPermanentWidget(self.throughput_status)

        def refresh_ports(self):
            current = self.port_box.currentData(); self.port_box.clear()
            for port in list_ports.comports(): self.port_box.addItem(f"{port.device}  ·  {port.description}", port.device)
            if current:
                index = self.port_box.findData(current)
                if index >= 0: self.port_box.setCurrentIndex(index)

        def toggle_connection(self):
            if self.reader: self.disconnect(); return
            port = self.port_box.currentData()
            if not port: self.connection_status.setText(" NO SERIAL PORT "); return
            self.reader = SerialReader(port)
            self.reader.metrics_changed.connect(self.on_metrics)
            self.reader.response_received.connect(self.on_response)
            self.reader.failed.connect(self.on_failure); self.reader.start()
            self.display_lag_ms = 0.0
            QtCore.QTimer.singleShot(250, lambda: self.send_device_command(COMMAND_PING))
            QtCore.QTimer.singleShot(400, self.read_device_config)
            self.connect_btn.setText("断开"); self.connection_status.setText(f" ● CONNECTED  {port} "); self.connection_status.setStyleSheet("color:#57e389")

        def disconnect(self):
            if self.reader: self.reader.stop(); self.reader = None
            self.connect_btn.setText("连接"); self.connection_status.setText(" DISCONNECTED "); self.connection_status.setStyleSheet("")

        def on_failure(self, message):
            self.disconnect(); self.connection_status.setText(" SERIAL ERROR: " + message)

        def send_device_command(self, command, payload=b""):
            if self.reader is None or not self.reader.send_command(command, payload):
                self.connection_status.setText(" DEVICE COMMAND NOT SENT ")
                return False
            return True

        def read_device_config(self):
            self.send_device_command(COMMAND_GET_CONFIG)

        def apply_device_config(self):
            press = self.press_spin.value(); release = self.release_spin.value()
            if press >= release:
                self.connection_status.setText(" PRESS MUST BE LOWER THAN RELEASE "); return
            self.send_device_command(COMMAND_SET_CONFIG, struct.pack("<HHB", press, release, self.stable_spin.value()))

        def save_device_config(self):
            self.send_device_command(COMMAND_SAVE_CONFIG)

        def reset_device_config(self):
            self.send_device_command(COMMAND_RESET_CONFIG)

        def set_stream_enabled(self, enabled):
            if self.reader is not None:
                self.send_device_command(COMMAND_SET_STREAM, bytes((int(enabled),)))

        def on_response(self, response):
            status = response["status"]
            if status != 0:
                self.connection_status.setText(" DEVICE ERROR: " + COMMAND_STATUS.get(status, str(status)))
                return
            payload = response["payload"]; command = response["command"]
            if command == COMMAND_PING and len(payload) >= 4:
                self.device_info = {"stream": payload[0], "schema": payload[1], "channels": payload[2], "command": payload[3]}
                self.device_label.setText(
                    f"Stream v{payload[0]} · Config v{payload[1]}\n{payload[2]} channels · Command v{payload[3]}")
            elif command in (COMMAND_GET_CONFIG, COMMAND_SET_CONFIG, COMMAND_SAVE_CONFIG,
                             COMMAND_RESET_CONFIG, COMMAND_SET_STREAM) and len(payload) >= 6:
                press, release, stable, enabled = struct.unpack("<HHBB", payload[:6])
                self.device_config = (press, release, stable, bool(enabled))
                for widget, value in ((self.press_spin, press), (self.release_spin, release), (self.stable_spin, stable)):
                    widget.blockSignals(True); widget.setValue(value); widget.blockSignals(False)
                self.stream_check.blockSignals(True); self.stream_check.setChecked(bool(enabled)); self.stream_check.blockSignals(False)
                self.connection_status.setText(" DEVICE CONFIG OK ")

        def on_packet(self, kind, mode, timestamp, values, arrival_ms):
            if mode != self.mode:
                self.mode = mode; self.mode_label.setText(MODE_NAMES[mode] + "  ")
                visible = range(mode*8, mode*8+8) if mode < 3 else range(24)
                for ch, check in enumerate(self.channel_checks): check.setChecked(ch in visible)
            if kind == 1 and values is not None and self.running:
                self.display_lag_ms = max(0.0, time.perf_counter() * 1000.0 - arrival_ms)
                self.latest = values; now = timestamp / 1000.0; self.history.append((now, values))
                cutoff = now - max(self.window_seconds * 1.1, 0.25)
                while self.history and self.history[0][0] < cutoff: self.history.popleft()
                if self.csv_writer is not None:
                    self.csv_writer.writerow((timestamp, *values))

        def on_metrics(self, m):
            self.measure_labels["rate"].setText(f"SCAN RATE\n{m['device_scan_hz']:.2f} Hz")
            self.measure_labels["period"].setText(f"PERIOD\n{m['period_mean_ms']:.3f} ms")
            self.measure_labels["jitter"].setText(f"JITTER σ\n{m['period_jitter_stdev_ms']:.3f} ms")
            self.measure_labels["lag"].setText(f"DISPLAY LAG\n{self.display_lag_ms:.1f} ms")
            ui_dropped = self.reader.ui_dropped() if self.reader is not None else 0
            self.measure_labels["loss"].setText(f"LOSS DEV/UI\n{m['lost_frames']} / {ui_dropped}")
            self.measure_labels["crc"].setText(f"CRC ERROR\n{m['crc_errors']}")
            self.throughput_status.setText(
                f"RX {m['host_receive_hz']:.2f} fps  ·  {m['throughput_bytes_s']:.0f} B/s  ·  "
                f"PERF {m['scan_us']} µs = ADDR {m['address_us']} + ADC {m['adc_us']} + PROC {m['process_us']}  ")

        def redraw(self):
            if self.reader is not None:
                for kind, mode, _seq, timestamp, values, arrival_ms in self.reader.take_pending():
                    self.on_packet(kind, mode, timestamp, values, arrival_ms)
            if not self.history: return
            points = list(self.history); end = points[-1][0]
            if len(points) > 1000:
                stride = (len(points) + 999) // 1000
                reduced = points[::stride]
                if reduced[-1] is not points[-1]: reduced.append(points[-1])
                points = reduced
            x = np.fromiter((stamp - end for stamp, _ in points), dtype=np.float64, count=len(points))
            data = np.asarray([values for _, values in points], dtype=np.float32)
            update_labels = time.perf_counter() - self.last_label_update >= 0.2
            for ch, curve in enumerate(self.curves):
                if self.channel_checks[ch].isChecked(): curve.setData(x, data[:, ch] / 1000.0); curve.show()
                else: curve.hide()
                if update_labels: self.value_labels[ch].setText(f"{self.latest[ch]:4d} mV")
            if update_labels: self.last_label_update = time.perf_counter()
            self.plot.setXRange(-self.window_seconds, 0, padding=0)
            channel = self.analysis_channel.currentIndex()
            values = data[:, channel].astype(float)
            self.analysis_values.setText(
                f"CURRENT   {values[-1]:7.0f} mV\n"
                f"MINIMUM   {values.min():7.0f} mV\n"
                f"MAXIMUM   {values.max():7.0f} mV\n"
                f"MEAN      {values.mean():7.1f} mV\n"
                f"PEAK-PEAK {np.ptp(values):7.0f} mV")

        def apply_visibility(self):
            for ch, curve in enumerate(self.curves): curve.setVisible(self.channel_checks[ch].isChecked())

        def select_group(self, mode):
            visible = range(mode * 8, mode * 8 + 8) if mode < 3 else range(24)
            for ch, check in enumerate(self.channel_checks): check.setChecked(ch in visible)

        def update_timebase(self, text):
            value, unit = text.split()
            self.window_seconds = float(value) / 1000.0 if unit == "ms" else float(value)
            self.update_grid_spacing()

        def update_grid_spacing(self):
            x_axis = self.plot.getPlotItem().getAxis("bottom")
            y_axis = self.plot.getPlotItem().getAxis("left")
            x_axis.setTickSpacing(levels=[(self.window_seconds / 10.0, 0.0)])
            y_min, y_max = self.plot.getPlotItem().vb.viewRange()[1]
            y_axis.setTickSpacing(levels=[((y_max - y_min) / 8.0, 0.0)])
            for index, line in enumerate(self.vertical_grid):
                line.setPos(-self.window_seconds + index * self.window_seconds / 10.0)
            self.position_horizontal_grid(y_min, y_max)
            self.plot.setXRange(-self.window_seconds, 0, padding=0)

        def position_horizontal_grid(self, y_min, y_max):
            step = (y_max - y_min) / 8.0
            for index, line in enumerate(self.horizontal_grid): line.setPos(y_min + index * step)

        def autoscale(self):
            if not self.history: return
            visible = [ch for ch, check in enumerate(self.channel_checks) if check.isChecked()]
            if not visible: return
            values = [sample[ch] / 1000.0 for _, sample in self.history for ch in visible]
            low, high = min(values), max(values)
            margin = max((high - low) * 0.08, 0.03)
            self.plot.setYRange(max(0.0, low - margin), min(3.3, high + margin), padding=0)

        def save_screenshot(self):
            path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "保存截图", "megknob-capture.png", "PNG (*.png)")
            if path: self.grab().save(path)

        def toggle_csv_recording(self, checked):
            if checked:
                path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "记录采样数据", "megknob-capture.csv", "CSV (*.csv)")
                if not path:
                    self.record_btn.setChecked(False); return
                self.csv_file = open(path, "w", newline="", encoding="utf-8-sig")
                self.csv_writer = csv.writer(self.csv_file)
                self.csv_writer.writerow(("device_timestamp_ms", *[f"U{26+ch//8}_Y{ch%8}_mV" for ch in range(24)]))
                self.record_btn.setText("停止记录")
            else:
                self.stop_csv_recording()

        def stop_csv_recording(self):
            self.csv_writer = None
            if self.csv_file is not None: self.csv_file.close(); self.csv_file = None
            self.record_btn.setText("记录 CSV"); self.record_btn.setChecked(False)

        def toggle_run(self, checked):
            self.running = checked; self.run_btn.setText("RUN" if checked else "STOP")

        def clear_history(self): self.history.clear()
        def update_range(self, text):
            self.plot.setYRange(0, float(text.split()[0]), padding=0); self.update_grid_spacing()

        def closeEvent(self, event):
            self.stop_csv_recording(); self.disconnect(); event.accept()

    app = QtWidgets.QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setFont(QtGui.QFont("Segoe UI", 10))
    window = ScopeWindow(); window.show()
    if os.environ.get("MEGKNOB_SMOKE_TEST") == "1":
        def finish_smoke_test():
            screenshot = os.environ.get("MEGKNOB_SMOKE_SCREENSHOT")
            if screenshot: window.grab().save(screenshot)
            app.quit()
        QtCore.QTimer.singleShot(500, finish_smoke_test)
    sys.exit(app.exec_())


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", metavar="COM_PORT", help="headless baseline capture")
    parser.add_argument("--seconds", type=float, default=30.0)
    args = parser.parse_args()
    if args.baseline:
        print(json.dumps(capture_baseline(args.baseline, args.seconds), ensure_ascii=False, indent=2))
    else:
        run_gui()
