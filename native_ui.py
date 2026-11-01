"""Minimal PySide6 window for the native FocusMic pipeline."""
from __future__ import annotations

import sys
import threading
from pathlib import Path

import cv2
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFormLayout, QGroupBox, QHBoxLayout,
    QLabel, QMainWindow, QMenu, QPlainTextEdit, QPushButton, QSlider, QSpinBox,
    QSystemTrayIcon, QVBoxLayout, QWidget,
)

PROBE = Path(__file__).resolve().parent
sys.path.insert(0, str(PROBE / "Falcon" / "studio"))

from native.audio import LiveAudio, list_input_devices, resolve_input  # noqa: E402
from native.pipeline import NativePipeline  # noqa: E402
from native.video import MouthTracker  # noqa: E402

MEDIAPIPE_MODEL = PROBE / "Falcon" / "studio" / "web" / "vendor" / "mediapipe" / "face_landmarker.task"
ICON = PROBE / "focusmic_icon.ico"


class MainWindow(QMainWindow):
    log_signal = Signal(str)
    hotkey_signal = Signal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("FocusMic")
        self.setWindowIcon(QIcon(str(ICON)))
        self.resize(1180, 720)
        self.pipeline = None
        self.tracker = None
        self.worker = None
        self.last_log = ""
        self._build()
        self.log_signal.connect(self.log.appendPlainText)
        self.hotkey_signal.connect(self._toggle_bypass_from_hotkey)
        self._hotkey = None
        self._setup_tray()
        self._setup_hotkey()
        self.timer = QTimer(self)
        self.timer.setInterval(50)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()

    def _build(self):
        root = QWidget()
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)

        self.preview = QLabel("摄像头预览")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumSize(760, 428)
        self.preview.setStyleSheet("background:#0b0f14;color:#7a8494;border-radius:10px;")
        layout.addWidget(self.preview, 3)

        side = QVBoxLayout()
        layout.addLayout(side, 2)

        form_box = QGroupBox("输入")
        form = QFormLayout(form_box)
        self.mic = QComboBox()
        for d in list_input_devices(__import__("sounddevice")):
            self.mic.addItem(f"[{d['index']}] {d['name']} ({d['hostapi']})", d["index"])
        try:
            default_idx, _ = resolve_input(__import__("sounddevice"), None)
            pos = self.mic.findData(default_idx)
            if pos >= 0:
                self.mic.setCurrentIndex(pos)
        except Exception:
            pass
        form.addRow("麦克风", self.mic)
        self.camera = QSpinBox()
        self.camera.setRange(0, 8)
        form.addRow("摄像头索引", self.camera)
        self.model = QComboBox()
        self.model.addItems(["Falcon Small", "Falcon Big"])
        form.addRow("模型", self.model)
        side.addWidget(form_box)

        out_box = QGroupBox("输出")
        out_layout = QVBoxLayout(out_box)
        self.cable = QLabel("CABLE Input：未启动")
        self.cable.setWordWrap(True)
        out_layout.addWidget(self.cable)
        self.monitor = QCheckBox("耳机监听（启动前选择）")
        self.monitor.setChecked(False)
        out_layout.addWidget(self.monitor)
        self.hint = QLabel("Discord/游戏麦克风选 CABLE Output；关闭其降噪、AGC、回声消除。")
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color:#8b95a5;font-size:11px;")
        out_layout.addWidget(self.hint)
        side.addWidget(out_box)

        cal_box = QGroupBox("音画同步")
        cal = QVBoxLayout(cal_box)
        self.av_value = QLabel("30 ms")
        self.av = QSlider(Qt.Horizontal)
        self.av.setRange(-250, 250)
        self.av.setSingleStep(10)
        self.av.setValue(30)
        self.av.valueChanged.connect(lambda v: self.av_value.setText(f"{v} ms"))
        cal.addWidget(self.av)
        cal.addWidget(self.av_value)
        side.addWidget(cal_box)

        buttons = QHBoxLayout()
        self.start_btn = QPushButton("开始")
        self.start_btn.clicked.connect(self.start)
        self.stop_btn = QPushButton("停止")
        self.stop_btn.clicked.connect(self.stop)
        self.stop_btn.setEnabled(False)
        self.reacquire_btn = QPushButton("重新锁定")
        self.reacquire_btn.clicked.connect(self.reacquire)
        self.reacquire_btn.setEnabled(False)
        self.bypass_btn = QPushButton("旁路：关")
        self.bypass_btn.setCheckable(True)
        self.bypass_btn.setEnabled(False)
        self.bypass_btn.toggled.connect(self.toggle_bypass)
        buttons.addWidget(self.start_btn)
        buttons.addWidget(self.stop_btn)
        buttons.addWidget(self.reacquire_btn)
        buttons.addWidget(self.bypass_btn)
        side.addLayout(buttons)

        self.stats = QLabel("—")
        self.stats.setWordWrap(True)
        self.stats.setStyleSheet("font-family:Consolas,monospace;color:#b7c0cc;")
        side.addWidget(self.stats)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(150)
        side.addWidget(self.log)
        side.addStretch(1)

        self.setStyleSheet("""
            QMainWindow, QWidget { background:#121821; color:#e7edf5; }
            QGroupBox { border:1px solid #2a3442; border-radius:8px; margin-top:10px; padding:8px; }
            QGroupBox::title { subcontrol-origin:margin; left:10px; padding:0 4px; color:#9aa6b5; }
            QComboBox, QSpinBox, QPlainTextEdit { background:#0b0f14; border:1px solid #2a3442; border-radius:5px; padding:4px; }
            QPushButton { background:#ffb51b; color:#131a23; border:none; border-radius:6px; padding:8px 14px; font-weight:600; }
            QPushButton:disabled { background:#3a4350; color:#8892a0; }
            QLabel { color:#dfe6ef; }
        """)

    def _setup_tray(self):
        try:
            self.tray = QSystemTrayIcon(QIcon(str(ICON)), self)
            menu = QMenu()
            show_action = QAction("显示 / 隐藏", self)
            show_action.triggered.connect(lambda: self.hide() if self.isVisible() else self.showNormal())
            menu.addAction(show_action)
            start_action = QAction("开始分离", self)
            start_action.triggered.connect(self.start)
            menu.addAction(start_action)
            stop_action = QAction("停止", self)
            stop_action.triggered.connect(self.stop)
            menu.addAction(stop_action)
            bypass_action = QAction("切换旁路 (Ctrl+Alt+M)", self)
            bypass_action.triggered.connect(self.bypass_btn.toggle)
            menu.addAction(bypass_action)
            menu.addSeparator()
            quit_action = QAction("退出", self)
            quit_action.triggered.connect(self.close)
            menu.addAction(quit_action)
            self.tray.setContextMenu(menu)
            self.tray.setToolTip("FocusMic")
            self.tray.activated.connect(
                lambda reason: self.showNormal() if reason == QSystemTrayIcon.DoubleClick else None)
            self.tray.show()
        except Exception as exc:
            self.tray = None
            self.log_signal.emit(f"托盘不可用：{exc}")

    def _setup_hotkey(self):
        try:
            import keyboard
            self._keyboard = keyboard
            self._hotkey = keyboard.add_hotkey("ctrl+alt+m", self.hotkey_signal.emit)
            self.log_signal.emit("全局旁路热键：Ctrl+Alt+M")
        except Exception as exc:
            self._keyboard = None
            self._hotkey = None
            self.log_signal.emit(f"全局热键不可用：{exc}")

    def _toggle_bypass_from_hotkey(self):
        if self.pipeline is not None and self.worker is not None and self.worker.is_alive():
            self.bypass_btn.setChecked(not self.bypass_btn.isChecked())

    def toggle_bypass(self, checked: bool):
        if self.pipeline is not None:
            self.pipeline.manual_bypass = bool(checked)
        self.bypass_btn.setText("旁路：开" if checked else "旁路：关")
        self.log_signal.emit("手动旁路：" + ("开（原始麦克风）" if checked else "关（Falcon）"))

    def start(self):
        if self.worker and self.worker.is_alive():
            return
        mic_idx = self.mic.currentData()
        camera = self.camera.value()
        variant = "big" if self.model.currentIndex() == 1 else "small"
        av = self.av.value()
        monitor = self.monitor.isChecked()
        try:
            audio = LiveAudio(mic_idx)
            self.tracker = MouthTracker(camera, model_path=MEDIAPIPE_MODEL)
        except Exception as exc:
            self.log_signal.emit(f"设备初始化失败：{exc}")
            return
        self.pipeline = NativePipeline(
            audio, self.tracker, variant=variant, av_offset_ms=av,
            gain_db=6.0, output=True, monitor=monitor,
        )
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.reacquire_btn.setEnabled(True)
        self.bypass_btn.setEnabled(True)
        if self.bypass_btn.isChecked():
            self.bypass_btn.setChecked(False)
        self.mic.setEnabled(False)
        self.camera.setEnabled(False)
        self.model.setEnabled(False)
        self.av.setEnabled(False)
        self.monitor.setEnabled(False)
        self.cable.setText("CABLE Input：启动中…")
        self.log_signal.emit(f"启动：{self.mic.currentText()} / camera {camera} / {variant} / AV {av} ms")
        self.worker = threading.Thread(target=self._run, daemon=True, name="pipeline")
        self.worker.start()

    def _run(self):
        try:
            self.pipeline.load("cuda")
            self.log_signal.emit("模型就绪，开始分离")
            self.pipeline.run()
        except Exception as exc:
            self.log_signal.emit(f"运行失败：{exc}")
        finally:
            self.log_signal.emit("已停止")

    def reacquire(self):
        if self.tracker is not None:
            self.tracker.reset_target()
            self.log_signal.emit("已清除目标，下一帧重新选择最大/最近人脸")

    def stop(self):
        if self.pipeline is not None:
            self.pipeline.stop()
        if self.worker is not None and self.worker.is_alive():
            self.worker.join(timeout=3.0)
        if self.tracker is not None:
            self.tracker.stop()
        self.pipeline = None
        self.tracker = None
        self.worker = None
        self.stats.setText("—")
        self._reset_buttons()

    def _reset_buttons(self):
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.reacquire_btn.setEnabled(False)
        self.bypass_btn.setEnabled(False)
        if self.bypass_btn.isChecked():
            self.bypass_btn.setChecked(False)
        self.bypass_btn.setText("旁路：关")
        self.mic.setEnabled(True)
        self.camera.setEnabled(True)
        self.model.setEnabled(True)
        self.av.setEnabled(True)
        self.monitor.setEnabled(True)
        self.cable.setText("CABLE Input：已停止")
        self.preview.clear()
        self.preview.setText("摄像头预览")

    def refresh(self):
        if self.tracker is not None:
            frame, box = self.tracker.preview_frame()
            if frame is not None:
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                h, w, _ = rgb.shape
                image = QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888).copy()
                if box is not None:
                    painter = QPainter(image)
                    painter.setRenderHint(QPainter.Antialiasing)
                    painter.setPen(QPen(QColor("#35d07f"), 3))
                    cx, cy, size = box
                    side = size * min(w, h)
                    x = cx * w - side / 2
                    y = cy * h - side / 2
                    painter.drawRect(int(x), int(y), int(side), int(side))
                    painter.end()
                pix = QPixmap.fromImage(image).scaled(
                    self.preview.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self.preview.setPixmap(pix)
        if self.pipeline is not None:
            s = self.pipeline.status()
            cable = s["cable"]
            if cable.get("active"):
                self.cable.setText(f"CABLE Input：已连接（{cable.get('device','')}）")
            elif cable.get("error"):
                self.cable.setText(f"CABLE Input：错误 {cable['error']}")
            self.stats.setText(
                f"infer {s['infer_ms']:5.1f} ms | windows {s['windows']} | skip {s['skipped']} | "
                f"tracked {s['tracked']*100:5.1f}% | lag {s['audio_lag']:5.2f}s | "
                f"cable {cable.get('queued',0)}q/{cable.get('dropped',0)}drop"
                f"{' | 直通' if s.get('bypass') else ''}"
            )
            if not s["running"] and self.worker is not None and not self.worker.is_alive():
                if self.tracker is not None:
                    self.tracker.stop()
                self.tracker = None
                self.pipeline = None
                self.worker = None
                self.stats.setText("—")
                self._reset_buttons()

    def closeEvent(self, event):
        self.stop()
        if self._hotkey is not None and self._keyboard is not None:
            try:
                self._keyboard.remove_hotkey(self._hotkey)
            except Exception:
                pass
        if getattr(self, "tray", None) is not None:
            self.tray.hide()
        event.accept()


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
