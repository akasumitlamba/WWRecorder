"""
video_editor.py - WWRecorder Video Player & Editor

• VideoPlayerWindow : In-app video player with playback controls,
                      frame screenshot, and integrated editor.
• VideoEditorPanel  : Trim, delete segment, mute audio, add text overlay.

All editing operations are FFmpeg-based and non-destructive —
the original file is always preserved.
"""
import ctypes
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import OrderedDict
from pathlib import Path
from typing import List, Optional

from PyQt6.QtWidgets import (
    QApplication, QWidget, QLabel, QPushButton, QToolButton,
    QHBoxLayout, QVBoxLayout, QSlider, QSizePolicy, QMessageBox,
    QFrame, QToolTip, QGraphicsDropShadowEffect, QStyle,
    QMenu, QComboBox, QFileDialog, QGridLayout, QLineEdit,
    QSpinBox, QDoubleSpinBox, QScrollArea, QStackedWidget, QProgressBar,
    QStackedLayout, QGraphicsView, QGraphicsScene, QGraphicsTextItem,
    QGraphicsObject, QScrollBar, QPlainTextEdit,
)
from PyQt6.QtCore import (
    Qt, QRect, QRectF, QPoint, QSize, QTimer, QPointF,
    pyqtSignal, QUrl, QThread, QSizeF, QEvent,
)
from PyQt6.QtGui import (
    QPainter, QColor, QBrush, QPen, QFont, QFontMetrics,
    QPainterPath, QIcon, QPixmap, QImage, QCursor, QKeySequence,
    QShortcut, QTransform, QAction, QTextOption, QTextCursor,
)
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput, QMediaDevices
from PyQt6.QtMultimediaWidgets import QVideoWidget, QGraphicsVideoItem

# ── Windows API ────────────────────────────────────────────────────────────────
WDA_EXCLUDEFROMCAPTURE = 0x00000011
_user32 = ctypes.windll.user32 if sys.platform == "win32" else None


def _exclude_from_capture(hwnd: int) -> None:
    if _user32:
        try:
            _user32.SetWindowDisplayAffinity(ctypes.c_void_p(hwnd), WDA_EXCLUDEFROMCAPTURE)
        except Exception:
            pass


def _asset(filename: str) -> str:
    base_dir = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_dir, 'icons', filename)


def _ffmpeg_filter_path(path: str) -> str:
    normalized = os.path.abspath(path)
    if normalized.startswith("\\\\"):
        normalized = normalized.replace("\\", "/")
    else:
        normalized = normalized.replace("\\", "/").replace(":", "\\:", 1)
    return normalized.replace("'", r"\'")


def _available_output_path(path: str) -> str:
    """Keep automatic/export saves non-destructive when a name already exists."""
    candidate = Path(path)
    if not candidate.exists():
        return str(candidate)
    counter = 2
    while True:
        alternate = candidate.with_name(f"{candidate.stem}_{counter}{candidate.suffix}")
        if not alternate.exists():
            return str(alternate)
        counter += 1


def _merge_delete_regions(regions, trim_start_ms: int = 0) -> list[tuple[float, float]]:
    spans = sorted((max(0.0, (r.start_ms - trim_start_ms) / 1000.0),
                    max(0.0, (r.end_ms - trim_start_ms) / 1000.0)) for r in regions)
    merged = []
    for start, end in spans:
        if end <= start:
            continue
        # Timeline values are integer milliseconds. A 1 ms gap is below any
        # displayed video frame and should be one cut, not two filter edges.
        if merged and start <= merged[-1][1] + 0.001:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _overlay_font_file(overlay) -> str:
    if overlay.bold and overlay.italic:
        filename = 'arialbi.ttf'
    elif overlay.bold:
        filename = 'arialbd.ttf'
    elif overlay.italic:
        filename = 'ariali.ttf'
    else:
        filename = 'arial.ttf'
    windows_dir = os.environ.get("WINDIR") or os.environ.get("SystemRoot") or r"C:\Windows"
    return _ffmpeg_filter_path(os.path.join(windows_dir, "Fonts", filename))


def _drawtext_filter(overlay, text_path: str, start: float, end: float, preview_height: float) -> str:
    x_expr = f"(w*{overlay.x_percent / 100.0:.4f}-tw/2)"
    y_expr = f"(h*{overlay.y_percent / 100.0:.4f}-th/2)"
    # Font size is stored in preview-scene units. Scale it by output height so
    # 1080p and 4K exports preserve the same visual proportion.
    fontsize = f"h*{float(overlay.font_size) / max(1.0, preview_height):.8f}"
    return (
        f"drawtext=fontfile='{_overlay_font_file(overlay)}'"
        f":textfile='{text_path}':fontsize={fontsize}:fontcolor={overlay.color}"
        f":borderw=2:bordercolor=black:x={x_expr}:y={y_expr}"
        f":enable='between(t,{start:.3f},{end:.3f})'"
    )

class _SegmentedToggle(QWidget):
    valueChanged = pyqtSignal(str)
    
    def __init__(self, options: list[str], current: str):
        super().__init__()
        self._options = options
        self._current = current
        self._buttons = {}
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        for i, opt in enumerate(options):
            b = QPushButton(opt)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setFixedHeight(24)
            b.setFixedWidth(60)
            b.clicked.connect(lambda checked, o=opt: self._set_value(o))
            self._buttons[opt] = b
            layout.addWidget(b)
            
        self._update_styles()
        
    def _set_value(self, val):
        if val != self._current:
            self._current = val
            self._update_styles()
            self.valueChanged.emit(val)
            
    def value(self) -> str:
        return self._current
        
    def setValue(self, val: str):
        if val in self._options:
            self._current = val
            self._update_styles()
            
    def _update_styles(self):
        opts = list(self._options)
        for i, opt in enumerate(opts):
            b = self._buttons[opt]
            rad = "4px 0 0 4px" if i == 0 else "0 4px 4px 0"
            if opt == self._current:
                b.setStyleSheet(f"""
                    QPushButton {{
                        background: #DC2626; color: #FFFFFF; font-weight: bold; font-family: 'Segoe UI'; font-size: 11px;
                        border: 1px solid #DC2626; border-radius: {rad};
                    }}
                """)
            else:
                b.setStyleSheet(f"""
                    QPushButton {{
                        background: #1C1C1E; color: rgba(255,255,255,0.6); font-family: 'Segoe UI'; font-size: 11px;
                        border: 1px solid #3C3C3E; border-radius: {rad};
                    }}
                    QPushButton:hover {{ background: #2D2D30; color: #FFFFFF; }}
                """)


class _PillToggle(QWidget):
    """iOS-style pill-shaped toggle switch (red when ON)."""
    toggled = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(42, 24)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._checked = False

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, val: bool):
        self._checked = val
        self.update()

    def mousePressEvent(self, event):
        self._checked = not self._checked
        self.update()
        self.toggled.emit(self._checked)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        bg = QColor("#DC2626") if self._checked else QColor("#39393D")
        p.setBrush(bg)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(0, 0, self.width(), self.height(), 12, 12)
        p.setBrush(QColor("#FFFFFF"))
        if self._checked:
            p.drawEllipse(self.width() - 22, 2, 20, 20)
        else:
            p.drawEllipse(2, 2, 20, 20)
        p.end()


class NoScrollSpinBox(QSpinBox):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        up_arrow = _asset("spn_up.png").replace("\\", "/")
        down_arrow = _asset("spn_down.png").replace("\\", "/")
        self.setStyleSheet("""
            QSpinBox {
                background: #1C1C1E; border: 1px solid #3C3C3E; border-radius: 4px;
                color: #FFFFFF; font-size: 11px; padding: 2px 26px 2px 8px;
            }
            QSpinBox::up-button {
                subcontrol-origin: padding; subcontrol-position: top right;
                width: 20px; border-left: 1px solid #3C3C3E; border-bottom: 1px solid #3C3C3E;
                border-top-right-radius: 4px; background: #252528;
            }
            QSpinBox::down-button {
                subcontrol-origin: padding; subcontrol-position: bottom right;
                width: 20px; border-left: 1px solid #3C3C3E;
                border-bottom-right-radius: 4px; background: #252528;
            }
            QSpinBox::up-button:hover, QSpinBox::down-button:hover { background: #3C3C3E; }
            QSpinBox::up-arrow { 
                image: url("__UP_ARROW__");
                width: 10px; height: 10px; 
            }
            QSpinBox::down-arrow { 
                image: url("__DOWN_ARROW__");
                width: 10px; height: 10px; 
            }
        """.replace("__UP_ARROW__", up_arrow).replace("__DOWN_ARROW__", down_arrow))

    def wheelEvent(self, event):
        event.ignore()


class NoScrollDoubleSpinBox(QDoubleSpinBox):
    """0.1-second-precision spinbox for sub-second editing."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setDecimals(1)
        self.setSingleStep(0.1)
        up_arrow = _asset("spn_up.png").replace("\\", "/")
        down_arrow = _asset("spn_down.png").replace("\\", "/")
        self.setStyleSheet("""
            QDoubleSpinBox {
                background: #1C1C1E; border: 1px solid #3C3C3E; border-radius: 4px;
                color: #FFFFFF; font-size: 11px; padding: 2px 26px 2px 8px;
            }
            QDoubleSpinBox::up-button {
                subcontrol-origin: padding; subcontrol-position: top right;
                width: 20px; border-left: 1px solid #3C3C3E; border-bottom: 1px solid #3C3C3E;
                border-top-right-radius: 4px; background: #252528;
            }
            QDoubleSpinBox::down-button {
                subcontrol-origin: padding; subcontrol-position: bottom right;
                width: 20px; border-left: 1px solid #3C3C3E;
                border-bottom-right-radius: 4px; background: #252528;
            }
            QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover { background: #3C3C3E; }
            QDoubleSpinBox::up-arrow { 
                image: url("__UP_ARROW__");
                width: 10px; height: 10px; 
            }
            QDoubleSpinBox::down-arrow { 
                image: url("__DOWN_ARROW__");
                width: 10px; height: 10px; 
            }
        """.replace("__UP_ARROW__", up_arrow).replace("__DOWN_ARROW__", down_arrow))

    def wheelEvent(self, event):
        event.ignore()


def _get_ffmpeg() -> str:
    from recorder import get_ffmpeg_path
    return get_ffmpeg_path()


def _format_time(ms: int) -> str:
    total_secs = max(0, ms // 1000)
    h = total_secs // 3600
    m = (total_secs % 3600) // 60
    s = total_secs % 60
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def _format_time_precise(ms: int) -> str:
    total_secs = max(0, ms / 1000.0)
    h = int(total_secs) // 3600
    m = (int(total_secs) % 3600) // 60
    s = total_secs - h * 3600 - m * 60
    s = min(s, 59.999)  # BUG-024: Prevent '60.000' from float rounding
    return f"{h:02d}:{m:02d}:{s:06.3f}"


def _delete_region_at_playhead(position_ms: int, duration_ms: int) -> tuple[int, int]:
    """Create the default two-second cut without rounding the playhead."""
    start_ms = max(0, int(position_ms))
    return start_ms, min(start_ms + 2000, max(0, int(duration_ms)))


def _text_overlay_range_at_playhead(position_ms: int, duration_ms: int) -> tuple[int, int]:
    """Start an overlay at the exact seek position, preserving sub-second time."""
    duration_ms = max(0, int(duration_ms))
    start_ms = max(0, min(int(position_ms), duration_ms))
    return start_ms, min(start_ms + 5000, duration_ms)


# ── Theme Constants ───────────────────────────────────────────────────────────
CLR_BG = QColor(9, 11, 16)
CLR_SURFACE = QColor(18, 22, 31)
CLR_CARD = QColor(38, 38, 40)
CLR_BORDER = QColor(55, 55, 58)
CLR_RED = QColor(255, 51, 71)
CLR_RED_HVR = QColor(255, 82, 100)
CLR_TEXT = QColor(235, 235, 245)
CLR_TEXT_DIM = QColor(255, 255, 255, 100)
CLR_ACCENT_BLUE = QColor(59, 130, 246)
CLR_ACCENT_BLUE_HVR = QColor(96, 165, 250)

# Color palette matching annotation tool
TEXT_COLORS = [
    '#FFFFFF', '#FF3B30', '#FFD60A', '#34C759',
    '#0A84FF', '#FF9500', '#AF52DE', '#000000',
]


# ─────────────────────────────────────────────────────────────────────────────
#  Toast
# ─────────────────────────────────────────────────────────────────────────────

class _Toast(QLabel):
    def __init__(self, parent):
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("""
            QLabel {
                background: rgba(34, 197, 94, 0.9); color: #FFFFFF;
                border-radius: 8px; font-size: 12px; font-weight: 700;
                font-family: 'Segoe UI'; padding: 8px 18px;
            }
        """)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.hide()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

    def show_message(self, text: str, duration_ms: int = 2000, color: str = "rgba(34, 197, 94, 0.9)"):
        self.setText(text)
        self.setStyleSheet(f"""
            QLabel {{
                background: {color}; color: #FFFFFF;
                border-radius: 8px; font-size: 12px; font-weight: 700;
                font-family: 'Segoe UI'; padding: 8px 18px;
            }}
        """)
        self.adjustSize()
        if self.parent():
            pw = self.parent().width()
            self.move((pw - self.width()) // 2, 60)
        self.show()
        self.raise_()
        self._timer.start(duration_ms)


# ─────────────────────────────────────────────────────────────────────────────
#  Custom Glass Seekbar (replaces QSlider for pixel-perfect rendering)
# ─────────────────────────────────────────────────────────────────────────────

class _GlassSeekbar(QWidget):
    """Custom-painted seekbar. No QSlider — no stylesheet pixel glitches."""
    positionChanged = pyqtSignal(int)
    sliderPressed = pyqtSignal()
    sliderReleased = pyqtSignal()

    TRACK_H = 4
    HANDLE_R = 7      # normal radius
    HANDLE_R_HVR = 8  # hover / drag radius

    def __init__(self, parent=None):
        super().__init__(parent)
        self._min = 0
        self._max = 0
        self._value = 0
        self._dragging = False
        self._hovering = False
        self._hover_x = -1
        self.setFixedHeight(28)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

    # ── public API matching QSlider ──────────────────────────────────────────
    def setRange(self, lo: int, hi: int):
        self._min = lo
        self._max = hi
        self.update()

    def setValue(self, v: int):
        if not self._dragging:
            self._value = max(self._min, min(v, self._max))
            self.update()

    def value(self) -> int:
        return self._value

    def maximum(self) -> int:
        return self._max

    # ── coordinate helpers ───────────────────────────────────────────────────
    def _usable_rect(self):
        m = self.HANDLE_R_HVR + 1
        return m, self.width() - 2 * m

    def _val_to_x(self, v: int) -> float:
        left, w = self._usable_rect()
        if self._max <= self._min or w <= 0:
            return float(left)
        return left + w * ((v - self._min) / (self._max - self._min))

    def _x_to_val(self, x: float) -> int:
        left, w = self._usable_rect()
        if w <= 0:
            return self._min
        ratio = max(0.0, min(1.0, (x - left) / w))
        return int(self._min + ratio * (self._max - self._min))

    # ── paint ────────────────────────────────────────────────────────────────
    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        cy = self.height() / 2.0
        left, w = self._usable_rect()
        hx = self._val_to_x(self._value)

        # Track background
        track_rect = QRectF(left, cy - self.TRACK_H / 2, w, self.TRACK_H)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 30))
        p.drawRoundedRect(track_rect, 2, 2)

        # Elapsed portion
        if hx > left:
            elapsed = QRectF(left, cy - self.TRACK_H / 2, hx - left, self.TRACK_H)
            p.setBrush(QColor(220, 38, 38))
            p.drawRoundedRect(elapsed, 2, 2)

        # Hover preview line
        if self._hovering and not self._dragging and self._hover_x >= left:
            p.setPen(QPen(QColor(255, 255, 255, 60), 1))
            p.drawLine(QPointF(self._hover_x, cy - 8), QPointF(self._hover_x, cy + 8))

        # Handle (circle)
        r = self.HANDLE_R_HVR if (self._hovering or self._dragging) else self.HANDLE_R
        # Glow
        if self._hovering or self._dragging:
            glow = QColor(220, 38, 38, 50)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(glow)
            p.drawEllipse(QPointF(hx, cy), r + 4, r + 4)
        # Solid circle
        p.setBrush(QColor(220, 38, 38))
        p.setPen(QPen(QColor(255, 255, 255, 40), 1.5))
        p.drawEllipse(QPointF(hx, cy), r, r)
        # Inner white dot
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 200))
        p.drawEllipse(QPointF(hx, cy), 2.5, 2.5)

        p.end()

    # ── mouse ────────────────────────────────────────────────────────────────
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self.sliderPressed.emit()
            self._seek_to(e.position().x())

    def mouseMoveEvent(self, e):
        self._hover_x = e.position().x()
        if self._dragging:
            self._seek_to(e.position().x())
        self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self._dragging:
            self._dragging = False
            self._seek_to(e.position().x())
            self.sliderReleased.emit()

    def enterEvent(self, e):
        self._hovering = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hovering = False
        self._hover_x = -1
        self.update()
        super().leaveEvent(e)

    def _seek_to(self, x: float):
        v = self._x_to_val(x)
        self._value = v
        self.positionChanged.emit(v)
        self.update()


_VOLUME_SLIDER_STYLE = """
    QSlider::groove:horizontal {
        height: 3px; background: rgba(255,255,255,0.15); border-radius: 1px;
    }
    QSlider::handle:horizontal {
        background: #FFFFFF; width: 10px; height: 10px;
        margin: -4px 0; border-radius: 5px;
    }
    QSlider::sub-page:horizontal {
        background: rgba(255, 255, 255, 0.55); border-radius: 1px;
    }
    QSlider::add-page:horizontal {
        background: rgba(255,255,255,0.08); border-radius: 1px;
    }
"""


# ─────────────────────────────────────────────────────────────────────────────
#  Saving Overlay (progress bar shown during export)
# ─────────────────────────────────────────────────────────────────────────────

class _SavingOverlay(QFrame):
    def __init__(self, parent):
        super().__init__(parent)
        self.setStyleSheet("background: rgba(0, 0, 0, 0.92);")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.lbl = QLabel("Saving Video...")
        self.lbl.setStyleSheet("color: #FFFFFF; font-size: 15px; font-weight: 700; background: transparent;")
        self.lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.pct_lbl = QLabel("0%")
        self.pct_lbl.setStyleSheet("color: #A0A0A8; font-size: 12px; font-weight: 500; background: transparent;")
        self.pct_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setFixedWidth(260)
        self.bar.setFixedHeight(5)
        self.bar.setTextVisible(False)
        self.bar.setStyleSheet("""
            QProgressBar { background-color: #2C2C2E; border-radius: 2px; }
            QProgressBar::chunk { background-color: #3B82F6; border-radius: 2px; }
        """)

        layout.addWidget(self.lbl)
        layout.addSpacing(6)
        layout.addWidget(self.bar, alignment=Qt.AlignmentFlag.AlignHCenter)
        layout.addSpacing(4)
        layout.addWidget(self.pct_lbl)

        self.hide()

    def set_progress(self, pct: int):
        self.bar.setValue(pct)
        self.pct_lbl.setText(f"{pct}%")


# ─────────────────────────────────────────────────────────────────────────────
#  Loading Overlay
# ─────────────────────────────────────────────────────────────────────────────

class _LoadingOverlay(QFrame):
    def __init__(self, parent):
        super().__init__(parent)
        self.setStyleSheet("background: rgba(0, 0, 0, 0.95);")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        self.spinner = QProgressBar(self)
        self.spinner.setRange(0, 0)
        self.spinner.setFixedWidth(200)
        self.spinner.setFixedHeight(4)
        self.spinner.setTextVisible(False)
        self.spinner.setStyleSheet("""
            QProgressBar {
                background-color: #3C3C3E;
                border-radius: 2px;
            }
            QProgressBar::chunk {
                background-color: #3B82F6;
                border-radius: 2px;
            }
        """)
        
        self.lbl = QLabel("Preparing Editor...")
        self.lbl.setStyleSheet("color: #FFFFFF; font-size: 14px; font-weight: 600; background: transparent;")
        self.lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        layout.addWidget(self.lbl)
        layout.addSpacing(10)
        layout.addWidget(self.spinner)
        
        self.hide()


# ─────────────────────────────────────────────────────────────────────────────
#  FFmpeg Export Worker
# ─────────────────────────────────────────────────────────────────────────────

class _ExportWorker(QThread):
    progress = pyqtSignal(int)   # 0-100
    export_finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, cmd: list, output_path: str, temp_files: list = None, duration_ms: int = 0):
        super().__init__()
        self._cmd = cmd
        self._output_path = output_path
        self._temp_files = temp_files or []
        self._duration_ms = duration_ms
        self._process = None
        self._is_stopped = False

    def stop(self):
        self._is_stopped = True
        if self._process:
            try:
                self._process.kill()
            except Exception:
                pass

    def run(self):
        try:
            flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            cmd_with_progress = self._cmd[:-1] + ["-progress", "pipe:2", self._cmd[-1]]
            self._process = subprocess.Popen(
                cmd_with_progress, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                creationflags=flags,
            )
            stderr_lines = []
            if self._duration_ms > 0:
                # Read stderr line-by-line to parse progress
                for raw_line in self._process.stderr:
                    if self._is_stopped:
                        break
                    line = raw_line.decode(errors='replace').strip()
                    stderr_lines.append(line)
                    if line.startswith("out_time_us="):
                        try:
                            us = int(line.split("=")[1])
                            pct = min(99, int(us / (self._duration_ms * 1000) * 100))
                            self.progress.emit(pct)
                        except Exception:
                            pass
                _, raw_err = self._process.communicate(timeout=10)
                if raw_err:
                    stderr_lines.extend(raw_err.decode(errors='replace').splitlines())
            else:
                _, raw_err = self._process.communicate()
                if raw_err:
                    stderr_lines = raw_err.decode(errors='replace').splitlines()

            if self._is_stopped:
                return
            if self._process.returncode == 0 and os.path.isfile(self._output_path):
                self.progress.emit(100)
                self.export_finished.emit(self._output_path)
            else:
                err_msg = "\n".join(stderr_lines[-10:]) or "Unknown error"
                self.error.emit(err_msg)
        except Exception as e:
            if not self._is_stopped:
                self.error.emit(str(e))
        finally:
            if self._process and self._process.poll() is None:
                try:
                    self._process.kill()
                    self._process.wait(timeout=3)
                except Exception:
                    pass
            if self._is_stopped:
                try:
                    if os.path.isfile(self._output_path):
                        os.remove(self._output_path)
                except Exception:
                    pass
            for tf in self._temp_files:
                try:
                    if os.path.isfile(tf):
                        os.remove(tf)
                except Exception:
                    pass


# ─────────────────────────────────────────────────────────────────────────────
#  Screenshot Worker
# ─────────────────────────────────────────────────────────────────────────────

class _ScreenshotWorker(QThread):
    screenshot_finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, video_path: str, time_ms: int, output_path: str):
        super().__init__()
        self._video_path = video_path
        self._time_ms = time_ms
        self._output_path = output_path
        self._process = None
        self._is_stopped = False

    def stop(self):
        self._is_stopped = True
        if self._process:
            try:
                self._process.kill()
            except Exception:
                pass

    def run(self):
        try:
            ffmpeg = _get_ffmpeg()
            time_str = _format_time_precise(self._time_ms)
            cmd = [
                ffmpeg, "-y", "-ss", time_str,
                "-i", self._video_path,
                "-vframes", "1", "-q:v", "2",
                self._output_path,
            ]
            flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            self._process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=flags)
            self._process.communicate(timeout=30)
            if self._is_stopped:
                return
            if self._process.returncode == 0 and os.path.isfile(self._output_path):
                self.screenshot_finished.emit(self._output_path)
            else:
                self.error.emit("FFmpeg screenshot failed")
        except Exception as e:
            if not self._is_stopped:
                self.error.emit(str(e))
        finally:
            if self._process and self._process.poll() is None:
                try:
                    self._process.kill()
                    self._process.wait(timeout=3)
                except Exception:
                    pass


# ─────────────────────────────────────────────────────────────────────────────
#  Thumbnail Extractor
# ─────────────────────────────────────────────────────────────────────────────

class _ThumbnailExtractor(QThread):
    thumbnails_ready = pyqtSignal(list, float, float)  # images (QImage), start_sec, fps_rate
    error = pyqtSignal(str)

    def __init__(self, video_path: str, num_frames: int = 40, thumb_height: int = 56,
                 start_sec: float = 0.0, end_sec: float = None, target_fps: float = None):
        super().__init__()
        self._video_path = video_path
        self._num_frames = num_frames
        self._thumb_height = thumb_height
        self._start_sec = start_sec
        self._end_sec = end_sec
        self._target_fps = target_fps
        self._process = None
        self._is_stopped = False

    def stop(self):
        self._is_stopped = True
        if self._process:
            try:
                self._process.kill()
            except Exception:
                pass

    def run(self):
        tmp_dir = None
        try:
            ffmpeg = _get_ffmpeg()
            flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            tmp_dir = tempfile.mkdtemp(prefix="ww_thumbs_")

            # Probe duration without decoding the full video. Fall back to
            # ffmpeg's metadata output if ffprobe is unavailable.
            ffprobe = os.path.join(os.path.dirname(ffmpeg), "ffprobe.exe") if ffmpeg.lower().endswith("ffmpeg.exe") else "ffprobe"
            probe_stdout = b""
            probe_stderr = b""
            try:
                probe_cmd = [
                    ffprobe, "-v", "error", "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1", self._video_path,
                ]
                self._process = subprocess.Popen(
                    probe_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=flags
                )
                probe_stdout, probe_stderr = self._process.communicate(timeout=15)
            except (FileNotFoundError, subprocess.SubprocessError, OSError):
                probe_cmd = [ffmpeg, "-i", self._video_path]
                self._process = subprocess.Popen(
                    probe_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=flags
                )
                probe_stdout, probe_stderr = self._process.communicate(timeout=15)
            if self._is_stopped:
                return

            duration_secs = 10
            try:
                duration_secs = max(0.1, float((probe_stdout or b"").decode(errors="replace").strip()))
            except Exception:
                probe_stderr_str = probe_stderr.decode(errors='replace') if probe_stderr else ""
                match = re.search(r'Duration:\s*(\d{2}):(\d{2}):(\d{2})\.(\d+)', probe_stderr_str)
                if match:
                    h, m, s, frac = match.groups()
                    duration_secs = int(h) * 3600 + int(m) * 60 + int(s) + float(f"0.{frac}")

            start_sec = self._start_sec
            end_sec = self._end_sec if self._end_sec is not None else duration_secs
            end_sec = min(end_sec, duration_secs)
            segment_dur = max(0.1, end_sec - start_sec)

            if self._target_fps is not None:
                fps_rate = self._target_fps
                num_frames = max(1, int(segment_dur * fps_rate) + 1)
            else:
                fps_rate = max(0.1, self._num_frames / max(0.1, segment_dur))
                num_frames = self._num_frames

            # Build vf filter with optional trim
            vf = f"fps={fps_rate:.4f},scale=-1:{self._thumb_height}:flags=fast_bilinear"
            cmd = [ffmpeg, "-y"]
            if start_sec > 0:
                cmd.extend(["-ss", f"{start_sec:.3f}"])
            if self._end_sec is not None:
                cmd.extend(["-to", f"{end_sec:.3f}"])
            cmd.extend([
                "-i", self._video_path,
                "-vf", vf,
                "-frames:v", str(num_frames),
                "-q:v", "5",
                os.path.join(tmp_dir, "thumb_%04d.jpg"),
            ])
            
            if self._is_stopped:
                return
                
            self._process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=flags
            )
            self._process.communicate(timeout=60)

            if self._is_stopped:
                return

            images = []
            i = 1
            while True:
                path = os.path.join(tmp_dir, f"thumb_{i:04d}.jpg")
                if not os.path.isfile(path):
                    break
                img = QImage(path)
                if not img.isNull():
                    images.append(img)
                i += 1

            if not self._is_stopped:
                self.thumbnails_ready.emit(images, start_sec, fps_rate)
        except Exception as e:
            if not self._is_stopped:
                self.error.emit(str(e))
        finally:
            if self._process and self._process.poll() is None:
                try:
                    self._process.kill()
                    self._process.wait(timeout=3)
                except Exception:
                    pass
            if tmp_dir:
                shutil.rmtree(tmp_dir, ignore_errors=True)


# ─────────────────────────────────────────────────────────────────────────────
#  Frame Timeline Widget
# ─────────────────────────────────────────────────────────────────────────────

class FrameTimelineWidget(QWidget):
    """
    Zoomable, scrollable timeline with frame thumbnails, trim pins, delete regions,
    time ruler, scrollbar, and 100ms-precision editing.

    - Ctrl+Scroll : zoom in/out (anchored at cursor)
    - Scroll      : horizontal pan when zoomed
    - Drag handle : 100ms precision
    """

    position_changed    = pyqtSignal(int)        # Moves playhead + seeks player
    preview_seek        = pyqtSignal(int)        # Seeks player for preview (no playhead move)
    zoom_changed        = pyqtSignal(float)      # Emits current zoom level
    frames_needed       = pyqtSignal(float, float)  # start_sec, end_sec
    overlay_time_changed = pyqtSignal(int, str, int)  # idx, 'start'/'end', ms
    overlay_selected    = pyqtSignal(int)
    lanes_changed       = pyqtSignal()            # emitted when lane count changes

    FILMSTRIP_HEIGHT = 56
    RULER_HEIGHT     = 16
    SB_HEIGHT        = 6
    LANE_H           = 22
    BASE_HEIGHT      = 120  # ruler + filmstrip + sb + time label

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(self.BASE_HEIGHT)
        self.setFixedHeight(self.BASE_HEIGHT)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._duration_ms  = 0
        self._position_ms  = 0
        self._zoom         = 1.0   # 1x–40x
        self._scroll_ms    = 0.0   # ms at left edge of visible window

        self._thumbnails: List[QPixmap] = []
        self._frame_cache: OrderedDict = OrderedDict()   # {int_second: QPixmap} dense frames from zoom extraction
        self._scaled_cache: OrderedDict = OrderedDict()  # PERF-012: {(id, height): QPixmap} cached scaled thumbnails
        self._frame_cache_limit = 240
        self._scaled_cache_limit = 500
        self._filmstrip_cache: Optional[QPixmap] = None
        self._cache_key    = (0, 0.0, 0.0)   # (width, zoom, scroll_ms)

        self._trim_start_ms = 0
        self._trim_end_ms   = 0
        self._trim_enabled  = False

        self._delete_regions: List['_DeleteRegionItem'] = []

        # Text overlay lanes
        self._text_overlays: list = []
        self._drag_ghost_x: float = -1   # x pixel of current overlay drag for ghost line
        self._drag_ghost_ms: int  = -1
        self._drag_lane_offset_ms: int = 0

        self._dragging     = None
        self._hover_handle = None
        self._margin_x     = 12

        # Scrollbar drag state
        self._sb_dragging       = False
        self._sb_drag_start_x   = 0.0
        self._sb_drag_start_scroll = 0.0

        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.timeout.connect(self._do_emit_frames)

        self._auto_scroll_timer = QTimer(self)
        self._auto_scroll_timer.timeout.connect(self._do_auto_scroll)
        self._auto_scroll_dir = 0

    # ── Public API ────────────────────────────────────────────────────────────

    def set_thumbnails(self, thumbnails: List[QPixmap]):
        self._thumbnails   = thumbnails
        self._frame_cache  = OrderedDict()
        self._scaled_cache = OrderedDict()  # PERF-012: Clear scaled cache
        self._filmstrip_cache = None
        self.update()

    def update_frame_cache(self, cache: dict):
        """Merge dense frame dict {int_second: QPixmap} and repaint."""
        for key, value in cache.items():
            self._frame_cache[key] = value
            self._frame_cache.move_to_end(key)
        while len(self._frame_cache) > self._frame_cache_limit:
            self._frame_cache.popitem(last=False)
        self._filmstrip_cache = None
        self.update()

    def set_duration(self, ms: int):
        self._duration_ms  = max(1, ms)
        self._trim_end_ms  = ms
        self._scroll_ms    = 0.0
        self.update()

    def set_position(self, ms: int):
        if self._dragging:
            return
        self._position_ms = ms
        self.update()

    def set_trim_enabled(self, enabled: bool):
        self._trim_enabled = enabled
        if enabled:
            self._trim_start_ms = 0
            self._trim_end_ms   = self._duration_ms
        self.update()

    def get_trim(self):
        return self._trim_start_ms, self._trim_end_ms

    def set_delete_regions(self, regions: List['_DeleteRegionItem']):
        self._delete_regions = regions
        self.update()

    def set_text_overlays(self, overlays: list):
        """Pass text overlay items so they are drawn as lanes below the filmstrip.

        Uses greedy interval packing: overlays that do not overlap in time are
        placed on the same lane, so we use the minimum number of lanes needed.
        """
        self._text_overlays = overlays

        # ── Greedy lane packing ───────────────────────────────────────────────
        # lanes_end[lane_idx] = the end_ms of the last overlay placed in that lane.
        # We iterate overlays in start-time order and assign each to the first
        # lane whose last overlay ends at or before this one's start_ms.
        lanes_end: list[int] = []          # one entry per lane
        orig_index_to_lane: dict[int, int] = {}

        # Build (start_ms, original_index) pairs sorted by start time
        order = sorted(range(len(overlays)), key=lambda i: overlays[i].start_ms)

        for orig_i in order:
            ov = overlays[orig_i]
            # Find first lane that doesn't overlap (its last end <= our start)
            placed = False
            for lane_idx, end_ms in enumerate(lanes_end):
                if end_ms <= ov.start_ms:
                    orig_index_to_lane[orig_i] = lane_idx
                    lanes_end[lane_idx] = ov.end_ms
                    placed = True
                    break
            if not placed:
                # Need a new lane
                orig_index_to_lane[orig_i] = len(lanes_end)
                lanes_end.append(ov.end_ms)

        self._overlay_lanes = orig_index_to_lane
        num_lanes = len(lanes_end) if overlays else 0
        new_h = self.BASE_HEIGHT + num_lanes * self.LANE_H
        self.setFixedHeight(new_h)
        self.update()

    def set_selected_overlay(self, idx: int):
        self._selected_overlay_idx = idx
        self.update()

    def _repack_lanes(self):
        """Re-run the greedy interval packing on the current overlays and update
        the widget height to match the (possibly changed) lane count.  Called
        whenever an overlay's start/end time changes so lanes stay compact."""
        overlays = self._text_overlays
        if not overlays:
            self._overlay_lanes = {}
            self.setFixedHeight(self.BASE_HEIGHT)
            return
        lanes_end: list[int] = []
        orig_index_to_lane: dict[int, int] = {}
        order = sorted(range(len(overlays)), key=lambda i: overlays[i].start_ms)
        for orig_i in order:
            ov = overlays[orig_i]
            placed = False
            for lane_idx, end_ms in enumerate(lanes_end):
                if end_ms <= ov.start_ms:
                    orig_index_to_lane[orig_i] = lane_idx
                    lanes_end[lane_idx] = ov.end_ms
                    placed = True
                    break
            if not placed:
                orig_index_to_lane[orig_i] = len(lanes_end)
                lanes_end.append(ov.end_ms)
        self._overlay_lanes = orig_index_to_lane
        num_lanes = len(lanes_end)
        new_h = self.BASE_HEIGHT + num_lanes * self.LANE_H
        if self.height() != new_h:
            self.setFixedHeight(new_h)
            self.lanes_changed.emit()
        self.update()

    def reset(self):
        self._zoom      = 1.0
        self._scroll_ms = 0.0
        self._filmstrip_cache = None
        self._frame_cache = OrderedDict()
        self._scaled_cache = OrderedDict()  # PERF-012: Clear scaled cache
        self.update()

    # ── Layout helpers ────────────────────────────────────────────────────────

    def _ruler_rect(self) -> QRect:
        return QRect(self._margin_x, 0, self.width() - 2 * self._margin_x, self.RULER_HEIGHT)

    def _filmstrip_rect(self) -> QRect:
        y = self.RULER_HEIGHT + 2
        return QRect(self._margin_x, y, self.width() - 2 * self._margin_x, self.FILMSTRIP_HEIGHT)

    def _overlay_lanes_top(self) -> int:
        """Y where overlay lanes begin (below filmstrip)."""
        fr = self._filmstrip_rect()
        return fr.bottom() + 2

    def _sb_rect(self) -> QRect:
        num_lanes = len(getattr(self, '_overlay_lanes', {}) and
                        set(getattr(self, '_overlay_lanes', {}).values()) or [])
        # Scrollbar sits below overlay lanes
        ot = self._overlay_lanes_top()
        num = len(set(getattr(self, '_overlay_lanes', {}).values())) if self._text_overlays else 0
        y = ot + num * self.LANE_H + 6
        fr = self._filmstrip_rect()
        return QRect(fr.x(), y, fr.width(), self.SB_HEIGHT)

    # ── Coordinate Mapping ────────────────────────────────────────────────────

    def _visible_duration_ms(self) -> float:
        return self._duration_ms / self._zoom

    def _ms_to_x(self, ms: float) -> float:
        r    = self._filmstrip_rect()
        vis  = self._visible_duration_ms()
        ratio = (ms - self._scroll_ms) / max(1.0, vis)
        return r.x() + ratio * r.width()

    def _x_to_ms(self, x: float) -> int:
        r    = self._filmstrip_rect()
        vis  = self._visible_duration_ms()
        ratio = max(0.0, min(1.0, (x - r.x()) / max(1, r.width())))
        ms   = self._scroll_ms + ratio * vis
        return int(ms)

    def _clamp_scroll(self):
        max_scroll = max(0.0, self._duration_ms - self._visible_duration_ms())
        self._scroll_ms = max(0.0, min(max_scroll, self._scroll_ms))

    def _handle_at(self, pos: QPoint) -> Optional[str]:
        threshold = 10
        x = pos.x()
        y = pos.y()
        lane_top = self._overlay_lanes_top()
        # In overlay lane area — only match overlay handles within their specific vertical lane
        if self._text_overlays and y >= lane_top:
            lanes = getattr(self, '_overlay_lanes', {})
            for i, ov in enumerate(self._text_overlays):
                li = lanes.get(i, 0)
                ly = lane_top + li * self.LANE_H
                if ly <= y <= ly + self.LANE_H:
                    is_selected = getattr(self, '_selected_overlay_idx', -1) == i
                    if is_selected:
                        if abs(x - self._ms_to_x(ov.end_ms)) < threshold:
                            return f'ov_end_{i}'
                        if abs(x - self._ms_to_x(ov.start_ms)) < threshold:
                            return f'ov_start_{i}'
                    sx = self._ms_to_x(ov.start_ms)
                    ex = self._ms_to_x(ov.end_ms)
                    if sx <= x <= ex:
                        return f'ov_lane_{i}'
            return None
        # In filmstrip / ruler area — trim/delete handles
        if self._trim_enabled:
            if abs(x - self._ms_to_x(self._trim_start_ms)) < threshold:
                return 'trim_start'
            if abs(x - self._ms_to_x(self._trim_end_ms)) < threshold:
                return 'trim_end'
        for i, reg in enumerate(self._delete_regions):
            if abs(x - self._ms_to_x(reg.start_ms)) < threshold:
                return f'del_start_{i}'
            if abs(x - self._ms_to_x(reg.end_ms)) < threshold:
                return f'del_end_{i}'
        return None

    def _in_scrollbar(self, pos: QPoint) -> bool:
        return self._sb_rect().contains(pos) and self._zoom > 1.0

    # ── Mouse Events ──────────────────────────────────────────────────────────

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta  = event.angleDelta().y()
            factor = 1.15 if delta > 0 else 1 / 1.15  # PERF-012: Smoother zoom factor
            old_zoom = self._zoom
            self._zoom = max(1.0, min(40.0, self._zoom * factor))
            if self._zoom != old_zoom:
                r = self._filmstrip_rect()
                cursor_x   = event.position().x()
                cursor_ratio = max(0.0, min(1.0, (cursor_x - r.x()) / max(1, r.width())))
                cursor_ms  = self._scroll_ms + cursor_ratio * (self._duration_ms / old_zoom)
                new_vis    = self._duration_ms / self._zoom
                self._scroll_ms = cursor_ms - cursor_ratio * new_vis
                self._clamp_scroll()
                # PERF-012: Only invalidate filmstrip cache, not the whole widget tree
                self._filmstrip_cache = None
                self.zoom_changed.emit(self._zoom)
                self._emit_frames_needed()
                self.update()
            elif self._zoom == 1.0:
                # Explicit reset when zoom returns to minimum
                self._scroll_ms = 0.0
                self._filmstrip_cache = None
                self.update()
        else:
            if self._zoom > 1.0:
                delta_x = event.angleDelta().x()
                if delta_x == 0:
                    delta_x = event.angleDelta().y()
                
                if delta_x != 0:
                    if not event.pixelDelta().isNull() and event.pixelDelta().x() != 0:
                        px_shift = -event.pixelDelta().x()
                        pan = px_shift * (self._visible_duration_ms() / max(1, self.width()))
                    elif not event.pixelDelta().isNull() and event.pixelDelta().y() != 0:
                        px_shift = -event.pixelDelta().y()
                        pan = px_shift * (self._visible_duration_ms() / max(1, self.width()))
                    else:
                        pan = -(delta_x / 120.0) * (self._visible_duration_ms() * 0.1)

                    self._scroll_ms += pan
                    self._clamp_scroll()
                    self._filmstrip_cache = None
                    self._emit_frames_needed()
                    self.update()
        event.accept()

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self._in_scrollbar(event.pos()):
            self._sb_dragging          = True
            self._sb_drag_start_x      = event.position().x()
            self._sb_drag_start_scroll = self._scroll_ms
            return
        handle = self._handle_at(event.pos())
        if handle:
            self._dragging = handle
            if str(handle).startswith('ov_'):
                idx = int(str(handle).split('_')[-1])
                self.overlay_selected.emit(idx)
                if str(handle).startswith('ov_lane_'):
                    ms = self._x_to_ms(event.pos().x())
                    ov = self._text_overlays[idx]
                    self._drag_lane_offset_ms = ms - ov.start_ms
                    self.setCursor(Qt.CursorShape.ClosedHandCursor)
        else:
            self._dragging = 'seek'
            ms = self._x_to_ms(event.pos().x())
            self._position_ms = ms
            self.position_changed.emit(ms)
        self.update()

    def mouseMoveEvent(self, event):
        if self._sb_dragging:
            dx     = event.position().x() - self._sb_drag_start_x
            sb     = self._sb_rect()
            ratio  = dx / max(1, sb.width())
            max_scroll = self._duration_ms - self._visible_duration_ms()
            self._scroll_ms = max(0.0, min(max_scroll,
                self._sb_drag_start_scroll + ratio * self._duration_ms))
            self._filmstrip_cache = None
            self.update()
            return

        if self._dragging:
            x = event.pos().x()
            self._last_drag_x = x
            self._apply_drag(x)
            
            if self._dragging != 'seek':
                if x < 40:
                    self._auto_scroll_dir = -1
                    if not self._auto_scroll_timer.isActive():
                        self._auto_scroll_timer.start(30)
                elif x > self.width() - 40:
                    self._auto_scroll_dir = 1
                    if not self._auto_scroll_timer.isActive():
                        self._auto_scroll_timer.start(30)
                else:
                    self._auto_scroll_dir = 0
                    self._auto_scroll_timer.stop()
        else:
            handle = self._handle_at(event.pos())
            if handle != self._hover_handle:
                self._hover_handle = handle
                if handle:
                    if handle.startswith('ov_lane_'):
                        self.setCursor(Qt.CursorShape.OpenHandCursor)
                    else:
                        self.setCursor(Qt.CursorShape.SizeHorCursor)
                else:
                    self.setCursor(Qt.CursorShape.PointingHandCursor)
                self.update()

    def mouseReleaseEvent(self, event):
        self._auto_scroll_timer.stop()
        self._auto_scroll_dir = 0
        self._sb_dragging = False
        self._dragging    = None
        self._drag_ghost_x  = -1
        self._drag_ghost_ms = -1
        handle = self._handle_at(event.pos())
        self._hover_handle = handle
        if handle:
            if handle.startswith('ov_lane_'):
                self.setCursor(Qt.CursorShape.OpenHandCursor)
            else:
                self.setCursor(Qt.CursorShape.SizeHorCursor)
        else:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.update()

    def _do_auto_scroll(self):
        if not self._dragging or self._auto_scroll_dir == 0:
            self._auto_scroll_timer.stop()
            return
            
        vis = self._visible_duration_ms()
        if vis >= self._duration_ms:
            return
            
        # Scroll roughly 2% of the visible window per 30ms tick
        scroll_amt = vis * 0.02 * self._auto_scroll_dir
        new_scroll = self._scroll_ms + scroll_amt
        max_scroll = max(0.0, self._duration_ms - vis)
        self._scroll_ms = max(0.0, min(max_scroll, new_scroll))
        self._filmstrip_cache = None
        
        if hasattr(self, '_last_drag_x'):
            self._apply_drag(self._last_drag_x)

    def _apply_drag(self, x: float):
        ms = self._x_to_ms(x)
        ms = max(0, min(self._duration_ms, ms))

        # Snap to playhead
        if self._dragging != 'seek':
            pos_x = self._ms_to_x(self._position_ms)
            if abs(x - pos_x) < 15:
                ms = self._position_ms

        if self._dragging == 'seek':
            self._position_ms = ms
            self.position_changed.emit(ms)
        elif self._dragging == 'trim_start':
            max_start = self._trim_end_ms - 100
            self._trim_start_ms = min(max_start, max(0, ms))
            self.preview_seek.emit(self._trim_start_ms)
        elif self._dragging == 'trim_end':
            min_end = self._trim_start_ms + 100
            self._trim_end_ms = min(self._duration_ms, max(min_end, ms))
            self.preview_seek.emit(self._trim_end_ms)
        elif str(self._dragging).startswith('del_start_'):
            idx = int(self._dragging.split('_')[2])
            reg = self._delete_regions[idx]
            min_start = self._trim_start_ms if self._trim_enabled else 0
            for i, r in enumerate(self._delete_regions):
                if i != idx and r.end_ms <= reg.end_ms:
                    min_start = max(min_start, r.end_ms)
            reg.start_ms = max(min_start, min(ms, reg.end_ms - 100))
            self.preview_seek.emit(reg.start_ms)
        elif str(self._dragging).startswith('del_end_'):
            idx = int(self._dragging.split('_')[2])
            reg = self._delete_regions[idx]
            max_end = self._trim_end_ms if self._trim_enabled else self._duration_ms
            for i, r in enumerate(self._delete_regions):
                if i != idx and r.start_ms >= reg.start_ms:
                    max_end = min(max_end, r.start_ms)
            reg.end_ms = min(max_end, max(ms, reg.start_ms + 100))
            self.preview_seek.emit(reg.end_ms)
        elif str(self._dragging).startswith('ov_start_'):
            idx = int(self._dragging.split('_')[2])
            ov = self._text_overlays[idx]
            
            # Snap to other overlays
            snap_ms = ms
            for i, other_ov in enumerate(self._text_overlays):
                if i != idx:
                    if abs(ms - other_ov.start_ms) < 200: snap_ms = other_ov.start_ms
                    if abs(ms - other_ov.end_ms) < 200: snap_ms = other_ov.end_ms
            
            ov.start_ms = max(0, min(snap_ms, ov.end_ms - 100))
            self._drag_ghost_x = self._ms_to_x(ov.start_ms)
            self._drag_ghost_ms = ov.start_ms
            self.overlay_time_changed.emit(idx, 'start', ov.start_ms)
            self._repack_lanes()
        elif str(self._dragging).startswith('ov_end_'):
            idx = int(self._dragging.split('_')[2])
            ov = self._text_overlays[idx]
            
            # Snap to other overlays
            snap_ms = ms
            for i, other_ov in enumerate(self._text_overlays):
                if i != idx:
                    if abs(ms - other_ov.start_ms) < 200: snap_ms = other_ov.start_ms
                    if abs(ms - other_ov.end_ms) < 200: snap_ms = other_ov.end_ms

            ov.end_ms = min(self._duration_ms, max(snap_ms, ov.start_ms + 100))
            self._drag_ghost_x = self._ms_to_x(ov.end_ms)
            self._drag_ghost_ms = ov.end_ms
            self.overlay_time_changed.emit(idx, 'end', ov.end_ms)
            self._repack_lanes()
        elif str(self._dragging).startswith('ov_lane_'):
            idx = int(self._dragging.split('_')[2])
            ov = self._text_overlays[idx]
            duration = ov.end_ms - ov.start_ms
            new_start_ms = ms - self._drag_lane_offset_ms
            
            # Snap to other overlays
            snap_ms = new_start_ms
            for i, other_ov in enumerate(self._text_overlays):
                if i != idx:
                    if abs(new_start_ms - other_ov.start_ms) < 200: snap_ms = other_ov.start_ms
                    if abs(new_start_ms - other_ov.end_ms) < 200: snap_ms = other_ov.end_ms
                    if abs((new_start_ms + duration) - other_ov.start_ms) < 200: snap_ms = other_ov.start_ms - duration
                    if abs((new_start_ms + duration) - other_ov.end_ms) < 200: snap_ms = other_ov.end_ms - duration

            new_start_ms = max(0, min(self._duration_ms - duration, snap_ms))
            ov.start_ms = new_start_ms
            ov.end_ms = new_start_ms + duration
            
            self._drag_ghost_x = self._ms_to_x(ov.start_ms)
            self._drag_ghost_ms = ov.start_ms
            self.overlay_time_changed.emit(idx, 'start', ov.start_ms)
            self.overlay_time_changed.emit(idx, 'end', ov.end_ms)
            self._repack_lanes()
        self.update()

    # ── Dense frame emission ──────────────────────────────────────────────────

    def _emit_frames_needed(self):
        if self._zoom <= 1.5 or self._duration_ms <= 0:
            return
        self._debounce_timer.start(400)

    def _do_emit_frames(self):
        vis    = self._visible_duration_ms()
        start_s = max(0.0, self._scroll_ms / 1000.0)
        end_s   = min(self._duration_ms / 1000.0, (self._scroll_ms + vis) / 1000.0)
        if end_s > start_s:
            self.frames_needed.emit(start_s, end_s)

    # ── Filmstrip Cache ───────────────────────────────────────────────────────

    def _build_filmstrip_cache(self):
        r = self._filmstrip_rect()
        if r.width() <= 0:
            self._filmstrip_cache = None
            return

        vis_start = self._scroll_ms
        vis_end   = self._scroll_ms + self._visible_duration_ms()
        vis_dur   = max(1.0, vis_end - vis_start)

        # Collect all frames sorted by time
        frames: list = []
        n = len(self._thumbnails)
        if n > 0:
            dur = self._duration_ms
            for i, pm in enumerate(self._thumbnails):
                t_ms = int(i * dur / max(1, n - 1)) if n > 1 else 0
                frames.append((t_ms, pm))
        for sec, pm in self._frame_cache.items():
            frames.append((sec * 1000, pm))
        frames.sort(key=lambda x: x[0])

        if not frames:
            self._filmstrip_cache = None
            self._cache_key = (r.width(), self._zoom, self._scroll_ms)
            return

        # Keep last frame before visible_start + all frames in visible range
        before = [f for f in frames if f[0] <= vis_start]
        inside = [f for f in frames if vis_start < f[0] <= vis_end]
        vis_frames = (before[-1:] if before else []) + inside
        if not vis_frames:
            vis_frames = frames[:1]



        # Filter frames to prevent "squeezing" when zoomed out
        thumb_w_est = int(r.height() * 1.77)
        filtered_vis = []
        last_x = -9999
        for f in vis_frames:
            x_f = (f[0] - vis_start) / vis_dur * r.width()
            if x_f - last_x >= thumb_w_est * 0.9:
                filtered_vis.append(f)
                last_x = x_f
                
        if not filtered_vis:
            filtered_vis = vis_frames[:1]
        vis_frames = filtered_vis

        cache = QPixmap(r.width(), r.height())
        cache.fill(QColor(30, 30, 32))
        p = QPainter(cache)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        for idx, (t_ms, pm) in enumerate(vis_frames):
            x_f = (t_ms - vis_start) / vis_dur * r.width()
            if idx + 1 < len(vis_frames):
                next_t = vis_frames[idx + 1][0]
                tile_w = max(1, int((next_t - vis_start) / vis_dur * r.width() - x_f))
            else:
                tile_w = max(1, r.width() - int(max(0, x_f)))

            x_draw = int(max(0, x_f))
            remaining_w = tile_w
            
            # PERF-012: Cache scaled thumbnails to avoid re-scaling on every rebuild
            cache_key = (id(pm), r.height())
            if cache_key in self._scaled_cache:
                scaled = self._scaled_cache[cache_key]
                self._scaled_cache.move_to_end(cache_key)
            else:
                scaled = pm.scaledToHeight(r.height(), Qt.TransformationMode.FastTransformation)
                self._scaled_cache[cache_key] = scaled
                if len(self._scaled_cache) > self._scaled_cache_limit:
                    self._scaled_cache.popitem(last=False)
            thumb_actual_w = scaled.width()
            
            curr_src_off = int(max(0, x_draw - x_f)) % max(1, thumb_actual_w)
            
            # Tile the frame to fill empty gaps if tile_w exceeds thumb width
            while remaining_w > 0:
                w_draw = min(remaining_w, thumb_actual_w - curr_src_off)
                if w_draw <= 0:
                    break
                p.drawPixmap(x_draw, 0, scaled, curr_src_off, 0, w_draw, r.height())
                x_draw += w_draw
                remaining_w -= w_draw
                curr_src_off = 0

        p.end()
        self._filmstrip_cache = cache
        self._cache_key = (r.width(), self._zoom, self._scroll_ms)

    # ── Paint ─────────────────────────────────────────────────────────────────

    def paintEvent(self, _event):
        p   = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w   = self.width()
        fr  = self._filmstrip_rect()
        rr  = self._ruler_rect()

        # ── Ruler ──
        p.fillRect(rr, QColor(22, 22, 25))
        p.setPen(QPen(QColor(70, 70, 76), 1))
        p.drawLine(rr.x(), rr.bottom(), rr.right(), rr.bottom())

        vis_start = self._scroll_ms
        vis_dur   = self._visible_duration_ms()
        vis_end   = vis_start + vis_dur

        tick_candidates = [100, 200, 500, 1000, 2000, 5000, 10000, 30000, 60000, 120000, 300000]
        tick_ms = 1000
        for t in tick_candidates:
            if vis_dur / t <= 12:
                tick_ms = t
                break

        ruler_font = QFont("Segoe UI", 7)
        p.setFont(ruler_font)
        start_tick = int(vis_start / tick_ms) * tick_ms
        t = start_tick
        while t <= vis_end + tick_ms:
            rx = self._ms_to_x(t)
            if rr.x() <= rx <= rr.right():
                p.setPen(QPen(QColor(90, 90, 96), 1))
                p.drawLine(int(rx), rr.bottom() - 5, int(rx), rr.bottom())
                p.setPen(QColor(140, 140, 150))
                if tick_ms >= 1000:
                    label = _format_time(t)
                else:
                    label = f"{t / 1000.0:.1f}s"
                p.drawText(int(rx) + 2, rr.bottom() - 1, label)
            t += tick_ms

        # ── Filmstrip ──
        cur_key = (fr.width(), self._zoom, self._scroll_ms)
        if self._thumbnails or self._frame_cache:
            if self._filmstrip_cache is None or self._cache_key != cur_key:
                self._build_filmstrip_cache()
            if self._filmstrip_cache:
                p.drawPixmap(fr.topLeft(), self._filmstrip_cache)
        else:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(40, 40, 42))
            p.drawRoundedRect(fr, 6, 6)
            p.setPen(QColor(255, 255, 255, 60))
            p.setFont(QFont("Segoe UI", 9))
            p.drawText(fr, Qt.AlignmentFlag.AlignCenter, "Loading frames...")

        p.setPen(QPen(QColor(60, 60, 65), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(fr, 6, 6)

        # ── Trim region ──
        if self._trim_enabled:
            sx = self._ms_to_x(self._trim_start_ms)
            ex = self._ms_to_x(self._trim_end_ms)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, 160))
            if sx > fr.x():
                p.drawRect(QRectF(fr.x(), fr.y(), sx - fr.x(), fr.height()))
            if ex < fr.x() + fr.width():
                p.drawRect(QRectF(ex, fr.y(), fr.x() + fr.width() - ex, fr.height()))
            p.setPen(QPen(CLR_ACCENT_BLUE, 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(QRectF(sx, fr.y(), ex - sx, fr.height()))
            for hx, label_ms in [(sx, self._trim_start_ms), (ex, self._trim_end_ms)]:
                pin_rect = QRectF(hx - 5, fr.y() - 2, 10, fr.height() + 4)
                p.setPen(QPen(QColor(255, 255, 255, 220), 1))
                p.setBrush(CLR_ACCENT_BLUE)
                p.drawRoundedRect(pin_rect, 3, 3)
                p.setPen(QPen(QColor(255, 255, 255, 150), 1))
                cx_pin = int(hx)
                for dy in [-6, 0, 6]:
                    cy_pin = int(fr.y() + fr.height() / 2 + dy)
                    p.drawLine(cx_pin - 2, cy_pin, cx_pin + 2, cy_pin)
                p.setPen(CLR_ACCENT_BLUE)
                font = QFont("Segoe UI Semibold", 8)
                p.setFont(font)
                time_text = _format_time(label_ms)
                fm  = QFontMetrics(font)
                tw  = fm.horizontalAdvance(time_text)
                lx  = max(2, min(w - tw - 2, int(hx - tw / 2)))
                p.drawText(lx, fr.y() - 5, time_text)

        # ── Delete regions ──
        for reg in self._delete_regions:
            sx = self._ms_to_x(reg.start_ms)
            ex = self._ms_to_x(reg.end_ms)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(220, 38, 38, 90))
            p.drawRect(QRectF(sx, fr.y(), ex - sx, fr.height()))
            p.setPen(QPen(QColor(220, 38, 38, 80), 1))
            x_pos = int(sx) + 8
            while x_pos < int(ex):
                p.drawLine(x_pos, fr.y(), x_pos, fr.y() + fr.height())
                x_pos += 8
            for hx in [sx, ex]:
                pin_rect = QRectF(hx - 4, fr.y() - 2, 8, fr.height() + 4)
                p.setPen(QPen(QColor(255, 255, 255, 200), 1))
                p.setBrush(CLR_RED)
                p.drawRoundedRect(pin_rect, 3, 3)

        # ── Scrollbar ──
        if self._zoom > 1.0:
            sb  = self._sb_rect()
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(38, 38, 42))
            p.drawRoundedRect(QRectF(sb), 4, 4)
            max_scroll   = max(1.0, self._duration_ms - self._visible_duration_ms())
            handle_ratio = min(1.0, self._visible_duration_ms() / max(1, self._duration_ms))
            handle_w     = max(20, int(sb.width() * handle_ratio))
            scroll_ratio = self._scroll_ms / max_scroll
            handle_x     = sb.x() + scroll_ratio * (sb.width() - handle_w)
            p.setBrush(QColor(110, 110, 120) if not self._sb_dragging else QColor(160, 160, 180))
            p.drawRoundedRect(QRectF(handle_x, sb.y(), handle_w, sb.height()), 4, 4)

            self._zoom_lbl_text = f"{self._zoom:.1f}×"

        # ── Overlay lanes ───────────────────────────────────────────
        if self._text_overlays:
            lane_colors = [QColor('#0A84FF'), QColor('#FF9500'), QColor('#AF52DE'),
                           QColor('#34C759'), QColor('#FF3B30'), QColor('#FFD60A')]
            ot = self._overlay_lanes_top()
            num_lanes = len(set(self._overlay_lanes.values())) if self._overlay_lanes else 0

            # Lane backgrounds
            for li in range(num_lanes):
                ly = ot + li * self.LANE_H
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(22, 22, 26))
                p.drawRoundedRect(QRectF(fr.x(), ly + 2, fr.width(), self.LANE_H - 2), 3, 3)

            for i, ov in enumerate(self._text_overlays):
                li = self._overlay_lanes.get(i, 0)
                ly = ot + li * self.LANE_H
                sx = self._ms_to_x(ov.start_ms)
                ex = self._ms_to_x(ov.end_ms)
                bar_w = max(6, ex - sx)
                clr = QColor(lane_colors[i % len(lane_colors)])
                clr.setAlpha(170)
                is_selected = getattr(self, '_selected_overlay_idx', -1) == i
                is_active = (str(self._hover_handle or '').endswith(f'_{i}') or
                             str(self._dragging or '').endswith(f'_{i}') or
                             is_selected)
                p.setBrush(clr)
                p.setPen(QPen(QColor(255, 255, 255, 200), 1.5) if is_active else Qt.PenStyle.NoPen)
                p.drawRoundedRect(QRectF(sx, ly + 3, bar_w, self.LANE_H - 5), 3, 3)

                # Label
                p.setPen(QColor(255, 255, 255, 220))
                font7 = QFont("Segoe UI", 7)
                p.setFont(font7)
                fm7 = QFontMetrics(font7)
                lbl = ov.text if fm7.horizontalAdvance(ov.text) < bar_w - 6 else ov.text[:max(0,int(bar_w/7))] + "…"
                p.drawText(QRectF(sx + 3, ly + 3, bar_w - 6, self.LANE_H - 5),
                           Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, lbl)

                # Edge handles (visible pill) - ONLY IF SELECTED
                if is_selected:
                    for hx in [sx, ex]:
                        p.setPen(Qt.PenStyle.NoPen)
                        p.setBrush(QColor(255, 255, 255, 180))
                        p.drawRoundedRect(QRectF(hx - 3, ly + 4, 6, self.LANE_H - 7), 3, 3)

            # Ghost drag line drawn over all lanes
            if self._drag_ghost_x >= 0:
                gx = self._drag_ghost_x
                num = len(set(self._overlay_lanes.values()))
                p.setPen(QPen(QColor(255, 220, 50, 220), 1.5, Qt.PenStyle.DashLine))
                p.drawLine(QPointF(gx, self.RULER_HEIGHT), QPointF(gx, ot + num * self.LANE_H))
                t_lbl = _format_time(self._drag_ghost_ms)
                p.setPen(QColor(255, 220, 50, 230))
                p.setFont(QFont("Segoe UI Semibold", 8))
                fm_g = QFontMetrics(p.font())
                tw_g = fm_g.horizontalAdvance(t_lbl)
                lx_g = max(fr.x() + 2, min(fr.right() - tw_g - 2, int(gx - tw_g / 2)))
                p.drawText(int(lx_g), int(ot) - 3, t_lbl)

        # ── Unified playhead — extends through overlay lanes too ───────────────
        pos_x = self._ms_to_x(self._position_ms)
        ot2 = self._overlay_lanes_top()
        num_lanes2 = len(set(self._overlay_lanes.values())) if self._text_overlays else 0
        ph_bottom = ot2 + num_lanes2 * self.LANE_H if num_lanes2 else fr.bottom()
        
        # Draw black outline for the line
        p.setPen(QPen(QColor(0, 0, 0, 180), 4))
        p.drawLine(QPointF(pos_x, fr.y()), QPointF(pos_x, ph_bottom))
        # Draw white line
        p.setPen(QPen(QColor(255, 255, 255), 2))
        p.drawLine(QPointF(pos_x, fr.y()), QPointF(pos_x, ph_bottom))
        
        triangle = QPainterPath()
        triangle.moveTo(pos_x - 6, fr.y() - 9)
        triangle.lineTo(pos_x + 6, fr.y() - 9)
        triangle.lineTo(pos_x, fr.y() + 1)
        triangle.closeSubpath()
        
        # Draw white triangle with black outline
        p.setPen(QPen(QColor(0, 0, 0, 180), 1.5))
        p.setBrush(QColor(255, 255, 255))
        p.drawPath(triangle)

        # ── Footer row: zoom badge (left) + playhead timestamp (centred) ───────
        # Rendered BELOW the scrollbar so nothing overlaps the lane zone.
        sb = self._sb_rect()
        footer_y = sb.bottom() + 14
        p.setFont(QFont("Segoe UI", 7))
        # Zoom badge (only when zoomed)
        if self._zoom > 1.0 and hasattr(self, '_zoom_lbl_text'):
            p.setPen(QColor(160, 160, 180))
            p.drawText(self._margin_x, footer_y, self._zoom_lbl_text)
        # Playhead time stamp (centred on playhead x)
        time_str = f"{self._position_ms / 1000.0:.1f}s"
        fm_t = QFontMetrics(p.font())
        tw_t = fm_t.horizontalAdvance(time_str)
        tx   = max(self._margin_x + 30, min(w - tw_t - 2, int(pos_x - tw_t / 2)))
        p.setPen(QColor(255, 255, 255, 180))
        p.drawText(tx, footer_y, time_str)

        p.end()



# ─────────────────────────────────────────────────────────────────────────────
#  Overlay Data Models
# ─────────────────────────────────────────────────────────────────────────────

class _DeleteRegionItem:
    def __init__(self, start_ms=0, end_ms=2000):
        self.start_ms = start_ms
        self.end_ms = end_ms


class _DeleteRegionRow(QWidget):
    removed = pyqtSignal(object)
    changed = pyqtSignal()

    def __init__(self, item: _DeleteRegionItem, duration_ms: int, parent=None):
        super().__init__(parent)
        self.item = item
        self._duration_ms = duration_ms
        self._build_ui()

    def _build_ui(self):
        self.setStyleSheet("""
            _DeleteRegionRow {
                background: #1A1A1C; border: 1px solid #2A2A2E;
                border-radius: 10px;
            }
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        r1 = QHBoxLayout()
        r1.setSpacing(6)
        
        lbl_info = QLabel("Delete Section")
        lbl_info.setStyleSheet("color: #DC2626; font-weight: bold; font-size: 11px;")
        r1.addWidget(lbl_info, 1)

        btn_remove = QPushButton()
        btn_remove.setIcon(QIcon(_asset("ve_close.png")))
        btn_remove.setFixedSize(24, 24)
        btn_remove.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_remove.setStyleSheet("""
            QPushButton {
                background: rgba(220,38,38,0.15); border: none; border-radius: 12px;
            }
            QPushButton:hover { background: #DC2626; }
        """)
        btn_remove.clicked.connect(lambda: self.removed.emit(self))
        r1.addWidget(btn_remove)
        layout.addLayout(r1)

        max_sec = max(0.1, self._duration_ms / 1000.0)
        r2 = QHBoxLayout()
        r2.setSpacing(4)
        lbl_time = QLabel("Time:")
        lbl_time.setStyleSheet("color: rgba(255,255,255,0.5); font-size: 10px; border: none;")
        r2.addWidget(lbl_time)

        self._spn_start = NoScrollDoubleSpinBox()
        self._spn_start.setRange(0.0, max_sec)
        self._spn_start.setValue(self.item.start_ms / 1000.0)
        self._spn_start.setSuffix("s")
        self._spn_start.setFixedWidth(100)
        self._spn_start.valueChanged.connect(lambda v: self._on_time_changed('start', v))
        r2.addWidget(self._spn_start)

        lbl_to = QLabel("to")
        lbl_to.setStyleSheet("color: rgba(255,255,255,0.5); font-size: 11px;")
        r2.addWidget(lbl_to)

        self._spn_end = NoScrollDoubleSpinBox()
        self._spn_end.setRange(0.0, max_sec)
        self._spn_end.setValue(min(self.item.end_ms / 1000.0, max_sec))
        self._spn_end.setSuffix("s")
        self._spn_end.setFixedWidth(100)
        self._spn_end.valueChanged.connect(lambda v: self._on_time_changed('end', v))
        r2.addWidget(self._spn_end)
        r2.addStretch()
        layout.addLayout(r2)

    def _on_time_changed(self, which: str, val: float):
        if which == 'start':
            self.item.start_ms = int(round(val * 1000))
            if self.item.end_ms <= self.item.start_ms:
                self.item.end_ms = self.item.start_ms + 100
                self._spn_end.blockSignals(True)
                self._spn_end.setValue(self.item.end_ms / 1000.0)
                self._spn_end.blockSignals(False)
        else:
            self.item.end_ms = int(round(val * 1000))
            if self.item.end_ms <= self.item.start_ms:
                self.item.start_ms = max(0, self.item.end_ms - 100)
                self._spn_start.blockSignals(True)
                self._spn_start.setValue(self.item.start_ms / 1000.0)
                self._spn_start.blockSignals(False)
        self.changed.emit()

    def set_start_time(self, ms: int):
        self._spn_start.blockSignals(True)
        self._spn_start.setValue(ms / 1000.0)
        self._spn_start.blockSignals(False)
        self.item.start_ms = ms
        self.changed.emit()
        
    def set_end_time(self, ms: int):
        self._spn_end.blockSignals(True)
        self._spn_end.setValue(ms / 1000.0)
        self._spn_end.blockSignals(False)
        self.item.end_ms = ms
        self.changed.emit()

# ─────────────────────────────────────────────────────────────────────────────

class _TextOverlayItem:
    def __init__(self):
        self.text = "Sample Text"
        self.x_percent = 50.0
        self.y_percent = 50.0
        self.font_size = 32
        self.bold = False
        self.italic = False
        self.underline = False
        self.color = "#FF3B30"
        self.start_ms = 0
        self.end_ms = 5000
        self._gfx_item = None   # Reference to DraggableTextItem (QGraphicsTextItem)


# ─────────────────────────────────────────────────────────────────────────────
#  Text Overlay Config Row
# ─────────────────────────────────────────────────────────────────────────────

class _TextOverlayRow(QFrame):
    changed = pyqtSignal()
    removed = pyqtSignal(object)
    selected = pyqtSignal(object)

    def __init__(self, item: _TextOverlayItem, duration_ms: int, parent=None):
        super().__init__(parent)
        self.item = item
        self._duration_ms = duration_ms
        self._build_ui()

    def set_selected(self, is_selected: bool):
        border_color = "#3B82F6" if is_selected else "#2A2A2E"
        self.setStyleSheet(f"""
            _TextOverlayRow {{
                background: #1A1A1C; border: 1px solid {border_color};
                border-radius: 10px;
            }}
        """)

    def mousePressEvent(self, event):
        self.selected.emit(self)
        super().mousePressEvent(event)

    def _build_ui(self):
        self.setStyleSheet("""
            _TextOverlayRow {
                background: #1A1A1C; border: 1px solid #2A2A2E;
                border-radius: 10px;
            }
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        # Row 1: text input + remove
        r1 = QHBoxLayout()
        r1.setSpacing(6)
        self._edt_text = QPlainTextEdit(self.item.text)
        self._edt_text.setPlaceholderText("Enter overlay text...")
        self._edt_text.setFixedHeight(72)
        self._edt_text.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self._edt_text.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        self._edt_text.setStyleSheet("""
            QPlainTextEdit {
                background: #111113; border: 1px solid #333336; border-radius: 6px;
                color: #FFFFFF; font-size: 12px; padding: 6px 10px; font-family: 'Segoe UI';
            }
            QPlainTextEdit:focus { border-color: #DC2626; }
        """)
        self._edt_text.textChanged.connect(self._on_text_changed)
        r1.addWidget(self._edt_text, 1)

        btn_remove = QPushButton()
        btn_remove.setIcon(QIcon(_asset("ve_close.png")))
        btn_remove.setFixedSize(26, 26)
        btn_remove.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_remove.setToolTip("Remove overlay")
        btn_remove.setStyleSheet("""
            QPushButton {
                background: rgba(220,38,38,0.15); color: rgba(255,255,255,0.5); border: none;
                border-radius: 13px; font-size: 10px; font-weight: bold;
            }
            QPushButton:hover { background: #DC2626; color: #FFFFFF; }
        """)
        btn_remove.clicked.connect(lambda: self.removed.emit(self))
        r1.addWidget(btn_remove)
        layout.addLayout(r1)

        # Row 2: color swatches
        r_color = QHBoxLayout()
        r_color.setSpacing(4)
        lbl_clr = QLabel("Color:")
        lbl_clr.setStyleSheet("color: rgba(255,255,255,0.5); font-size: 10px; border: none;")
        r_color.addWidget(lbl_clr)
        for hex_color in TEXT_COLORS:
            dot = QPushButton()
            dot.setFixedSize(18, 18)
            dot.setCursor(Qt.CursorShape.PointingHandCursor)
            dot.setStyleSheet(f"""
                QPushButton {{
                    background: {hex_color}; border: 2px solid {'#555' if hex_color != self.item.color else '#DC2626'};
                    border-radius: 9px;
                }}
                QPushButton:hover {{ border-color: #FFFFFF; }}
            """)
            dot.clicked.connect(lambda checked, c=hex_color: self._on_color_picked(c))
            r_color.addWidget(dot)
        r_color.addStretch()
        layout.addLayout(r_color)

        # Row 3: font size + B/I/U
        r2 = QHBoxLayout()
        r2.setSpacing(6)
        lbl_size = QLabel("Size:")
        lbl_size.setStyleSheet("color: rgba(255,255,255,0.5); font-size: 10px; border: none;")
        r2.addWidget(lbl_size)

        self._spn_size = NoScrollSpinBox()
        self._spn_size.setRange(12, 140)
        self._spn_size.setValue(self.item.font_size)
        self._spn_size.setSuffix(" pt")
        self._spn_size.setFixedWidth(80)
        self._spn_size.valueChanged.connect(self._on_size_changed)
        r2.addWidget(self._spn_size)
        r2.addSpacing(8)

        for label, attr, initial in [("B", "bold", self.item.bold),
                                      ("I", "italic", self.item.italic),
                                      ("U", "underline", self.item.underline)]:
            btn = QPushButton(label)
            btn.setFixedSize(28, 28)
            btn.setCheckable(True)
            btn.setChecked(initial)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            font_style = "font-weight: bold;" if label == "B" else ("font-style: italic;" if label == "I" else "text-decoration: underline;")
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: #1C1C1E; color: rgba(255,255,255,0.7); border: 1px solid #3C3C3E;
                    border-radius: 4px; font-size: 12px; {font_style}
                }}
                QPushButton:checked {{ background: #DC2626; color: #FFFFFF; border-color: #EF4444; }}
                QPushButton:hover {{ border-color: #5C5C5E; }}
            """)
            btn.toggled.connect(lambda checked, a=attr: self._on_format_toggled(a, checked))
            r2.addWidget(btn)
        r2.addStretch()
        layout.addLayout(r2)

        # Row 4: start/end time
        max_sec = max(0.1, self._duration_ms / 1000.0)
        r3 = QHBoxLayout()
        r3.setSpacing(4)
        lbl_time = QLabel("Time:")
        lbl_time.setStyleSheet("color: rgba(255,255,255,0.5); font-size: 10px; border: none;")
        r3.addWidget(lbl_time)

        self._spn_start = NoScrollDoubleSpinBox()
        self._spn_start.setRange(0.0, max_sec)
        self._spn_start.setValue(self.item.start_ms / 1000.0)
        self._spn_start.setSuffix("s")
        self._spn_start.setFixedWidth(100)
        self._spn_start.valueChanged.connect(lambda v: self._on_time_changed('start', v))
        r3.addWidget(self._spn_start)

        lbl_to = QLabel("to")
        lbl_to.setStyleSheet("color: rgba(255,255,255,0.5); font-size: 11px;")
        r3.addWidget(lbl_to)

        self._spn_end = NoScrollDoubleSpinBox()
        self._spn_end.setRange(0.0, max_sec)
        self._spn_end.setValue(min(self.item.end_ms / 1000.0, max_sec))
        self._spn_end.setSuffix("s")
        self._spn_end.setFixedWidth(100)
        self._spn_end.valueChanged.connect(lambda v: self._on_time_changed('end', v))
        r3.addWidget(self._spn_end)
        r3.addStretch()
        layout.addLayout(r3)

    def _on_text_changed(self):
        text = self._edt_text.toPlainText()
        if len(text) > 500:
            cursor = self._edt_text.textCursor()
            pos = min(cursor.position(), 500)
            self._edt_text.blockSignals(True)
            self._edt_text.setPlainText(text[:500])
            cursor = self._edt_text.textCursor()
            cursor.setPosition(pos)
            self._edt_text.setTextCursor(cursor)
            self._edt_text.blockSignals(False)
            text = text[:500]
        self.item.text = text
        self.changed.emit()

    def _on_color_picked(self, hex_color: str):
        self.item.color = hex_color
        self.changed.emit()

    def _on_size_changed(self, val):
        self.item.font_size = int(val)
        self.changed.emit()

    def _on_format_toggled(self, attr: str, checked: bool):
        setattr(self.item, attr, checked)
        self.changed.emit()

    def _on_time_changed(self, which: str, val: float):
        if which == 'start':
            self.item.start_ms = int(round(val * 1000))
            if self.item.end_ms <= self.item.start_ms:
                self.item.end_ms = self.item.start_ms + 100
                self._spn_end.blockSignals(True)
                self._spn_end.setValue(self.item.end_ms / 1000.0)
                self._spn_end.blockSignals(False)
        else:
            self.item.end_ms = int(round(val * 1000))
            if self.item.end_ms <= self.item.start_ms:
                self.item.start_ms = max(0, self.item.end_ms - 100)
                self._spn_start.blockSignals(True)
                self._spn_start.setValue(self.item.start_ms / 1000.0)
                self._spn_start.blockSignals(False)
        self.changed.emit()

    def set_start_time(self, ms: int):
        """Safely set start time from timeline drag, avoiding infinite loops."""
        self._spn_start.blockSignals(True)
        self._spn_start.setValue(ms / 1000.0)
        self._spn_start.blockSignals(False)
        self.item.start_ms = ms
        self.changed.emit()
        
    def set_end_time(self, ms: int):
        """Safely set end time from timeline drag, avoiding infinite loops."""
        self._spn_end.blockSignals(True)
        self._spn_end.setValue(ms / 1000.0)
        self._spn_end.blockSignals(False)
        self.item.end_ms = ms
        self.changed.emit()


# ─────────────────────────────────────────────────────────────────────────────
#  Video Graphics View — QGraphicsView + QGraphicsVideoItem
#  This is the ONLY reliable way to overlay Qt items on video in Qt6.
# ─────────────────────────────────────────────────────────────────────────────

class _VideoGraphicsView(QGraphicsView):
    """
    Custom QGraphicsView that hosts a QGraphicsVideoItem.
    Text overlay items are added to the same scene, ensuring they render
    correctly on top of the video with proper compositing.
    """
    double_clicked = pyqtSignal()
    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: #000000; border: none;")
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)

        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)

        self._video_item = QGraphicsVideoItem()
        self._scene.addItem(self._video_item)
        self._video_item.nativeSizeChanged.connect(self._on_native_size_changed)
        self._native_size = QSizeF(1920, 1080)

    @property
    def video_item(self) -> QGraphicsVideoItem:
        return self._video_item

    @property
    def gfx_scene(self) -> QGraphicsScene:
        return self._scene

    def _on_native_size_changed(self, size: QSizeF):
        if size.isEmpty():
            return
        self._native_size = size
        self._fit_video()

    def _fit_video(self):
        if self._native_size.isEmpty():
            return
        self._video_item.setSize(self._native_size)
        self._scene.setSceneRect(self._video_item.boundingRect())
        self.fitInView(self._video_item, Qt.AspectRatioMode.KeepAspectRatio)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_video()

    def mouseDoubleClickEvent(self, event):
        item = self.itemAt(event.pos())
        if item and isinstance(item, (DraggableTextItem, _SelectionActionBarItem)):
            super().mouseDoubleClickEvent(event)
        else:
            self.double_clicked.emit()
            event.accept()

    def mousePressEvent(self, event):
        item = self.itemAt(event.pos())
        interactive_types = (DraggableTextItem, _SelectionActionBarItem, _ResizeHandleItem)
        if event.button() == Qt.MouseButton.LeftButton and not isinstance(item, interactive_types):
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)


# ─────────────────────────────────────────────────────────────────────────────
#  Draggable Text Item — Matching Annotator Text Box Behavior & Action Bar
# ─────────────────────────────────────────────────────────────────────────────

class _ResizeHandleItem(QGraphicsObject):
    """Corner resize grip for DraggableTextItem."""
    def __init__(self, parent_text_item, position: str):
        super().__init__(parent_text_item)
        self._parent_item = parent_text_item
        self._position = position  # 'tl', 'tr', 'bl', 'br'
        self.setCursor(Qt.CursorShape.SizeFDiagCursor if position in ('tl', 'br') else Qt.CursorShape.SizeBDiagCursor)
        self.setZValue(250)
        self.setVisible(False)
        self.setFlag(QGraphicsObject.GraphicsItemFlag.ItemIgnoresParentOpacity, True)
        self.setAcceptHoverEvents(True)
        self._dragging = False
        self._start_pos = QPointF(0, 0)
        self._start_size = 32

    def boundingRect(self) -> QRectF:
        sz = max(16.0, self._parent_item.item.font_size * 0.45)
        hs = sz / 2.0
        return QRectF(-hs, -hs, sz, sz)

    def paint(self, painter, option, widget):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        sz = max(16.0, self._parent_item.item.font_size * 0.45)
        r = sz * 0.42
        painter.setPen(QPen(QColor(255, 255, 255, 240), max(1.5, sz * 0.12)))
        painter.setBrush(QColor(220, 38, 38, 240))
        painter.drawEllipse(QRectF(-r, -r, r * 2, r * 2))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._start_pos = event.scenePos()
            self._start_size = self._parent_item.item.font_size
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._dragging:
            dx = event.scenePos().x() - self._start_pos.x()
            dy = event.scenePos().y() - self._start_pos.y()
            if self._position == 'tl':
                delta = (-dx - dy) / 2.0
            elif self._position == 'tr':
                delta = (dx - dy) / 2.0
            elif self._position == 'bl':
                delta = (-dx + dy) / 2.0
            else:  # 'br'
                delta = (dx + dy) / 2.0
            new_size = max(12, min(140, int(self._start_size + delta * 0.3)))
            if new_size != self._parent_item.item.font_size:
                self._parent_item.item.font_size = new_size
                self._parent_item.update_style()
                if self._parent_item._change_callback:
                    self._parent_item._change_callback()
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._dragging:
            self._dragging = False
            event.accept()
        else:
            super().mouseReleaseEvent(event)


class _SelectionActionBarItem(QGraphicsObject):
    """Floating action bar shown next to a selected DraggableTextItem with [Edit] and [Delete] buttons."""
    def __init__(self, parent_text_item):
        super().__init__(parent_text_item)
        self._parent_item = parent_text_item
        self.setZValue(300)
        self.setVisible(False)
        self.setFlag(QGraphicsObject.GraphicsItemFlag.ItemIgnoresParentOpacity, True)
        self.setAcceptHoverEvents(True)
        self._hovered_btn = None

        self._edit_icon = QIcon(_asset('pencil.png')) if os.path.isfile(_asset('pencil.png')) else (QIcon(_asset('ve_edit.png')) if os.path.isfile(_asset('ve_edit.png')) else QIcon())
        self._delete_icon = QIcon(_asset('delete.png')) if os.path.isfile(_asset('delete.png')) else (QIcon(_asset('ve_close.png')) if os.path.isfile(_asset('ve_close.png')) else QIcon())
        self._w = 160.0
        self._h = 36.0
        self.update_layout()

    def update_layout(self):
        fs = self._parent_item.item.font_size if hasattr(self._parent_item, 'item') else 32
        self._h = max(36.0, fs * 0.85)
        self._w = self._h * 4.6
        self.prepareGeometryChange()

    def boundingRect(self) -> QRectF:
        return QRectF(0, 0, self._w, self._h)

    def paint(self, painter, option, widget):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w, h = self._w, self._h
        radius = max(6.0, h * 0.2)

        # Background bar
        painter.setPen(QPen(QColor(68, 68, 72), max(1.0, h * 0.03)))
        painter.setBrush(QColor(26, 26, 30, 245))
        painter.drawRoundedRect(QRectF(0, 0, w, h), radius, radius)

        # Button dimensions
        btn_margin = h * 0.1
        btn_w = (w - (btn_margin * 3)) / 2.0
        btn_h = h - (btn_margin * 2)
        btn_radius = max(4.0, radius * 0.7)
        font_pt = max(9, int(h * 0.35))
        font = QFont("Segoe UI", font_pt, QFont.Weight.DemiBold)
        painter.setFont(font)

        # Edit button
        edit_rect = QRectF(btn_margin, btn_margin, btn_w, btn_h)
        if self._hovered_btn == 'edit':
            painter.setPen(QPen(QColor(80, 80, 86), 1))
            painter.setBrush(QColor(56, 56, 62))
        else:
            painter.setPen(QPen(QColor(62, 62, 66), 1))
            painter.setBrush(QColor(40, 40, 44))
        painter.drawRoundedRect(edit_rect, btn_radius, btn_radius)

        # Edit content
        painter.setPen(QColor(255, 255, 255))
        icon_sz = max(12, int(btn_h * 0.55))
        if not self._edit_icon.isNull():
            pm = self._edit_icon.pixmap(icon_sz, icon_sz)
            painter.drawPixmap(int(edit_rect.left() + btn_h * 0.25), int(edit_rect.top() + (btn_h - icon_sz) / 2), pm)
            text_rect = QRectF(edit_rect.left() + icon_sz + btn_h * 0.25, edit_rect.top(), btn_w - icon_sz - btn_h * 0.25, btn_h)
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, "Edit")
        else:
            painter.drawText(edit_rect, Qt.AlignmentFlag.AlignCenter, "✎ Edit")

        # Delete button
        del_x = edit_rect.right() + btn_margin
        del_rect = QRectF(del_x, btn_margin, btn_w, btn_h)
        if self._hovered_btn == 'delete':
            painter.setPen(QPen(QColor(239, 68, 68), 1))
            painter.setBrush(QColor(220, 38, 38))
        else:
            painter.setPen(QPen(QColor(62, 62, 66), 1))
            painter.setBrush(QColor(40, 40, 44))
        painter.drawRoundedRect(del_rect, btn_radius, btn_radius)

        # Delete content
        painter.setPen(QColor(255, 255, 255))
        if not self._delete_icon.isNull():
            pm = self._delete_icon.pixmap(icon_sz, icon_sz)
            painter.drawPixmap(int(del_rect.left() + btn_h * 0.25), int(del_rect.top() + (btn_h - icon_sz) / 2), pm)
            text_rect = QRectF(del_rect.left() + icon_sz + btn_h * 0.25, del_rect.top(), btn_w - icon_sz - btn_h * 0.25, btn_h)
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, "Delete")
        else:
            painter.drawText(del_rect, Qt.AlignmentFlag.AlignCenter, "✕ Delete")

    def _get_button_at(self, pos: QPointF) -> Optional[str]:
        w, h = self._w, self._h
        btn_margin = h * 0.1
        btn_w = (w - (btn_margin * 3)) / 2.0
        btn_h = h - (btn_margin * 2)
        edit_rect = QRectF(btn_margin, btn_margin, btn_w, btn_h)
        del_rect = QRectF(edit_rect.right() + btn_margin, btn_margin, btn_w, btn_h)
        if edit_rect.contains(pos):
            return 'edit'
        if del_rect.contains(pos):
            return 'delete'
        return None

    def hoverMoveEvent(self, event):
        btn = self._get_button_at(event.pos())
        self.setCursor(Qt.CursorShape.PointingHandCursor if btn else Qt.CursorShape.ArrowCursor)
        if btn != self._hovered_btn:
            self._hovered_btn = btn
            self.update()
        super().hoverMoveEvent(event)

    def hoverLeaveEvent(self, event):
        self._hovered_btn = None
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.update()
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            btn = self._get_button_at(event.pos())
            if btn == 'edit':
                event.accept()
                self._parent_item._start_editing()
                return
            elif btn == 'delete':
                event.accept()
                from PyQt6.QtCore import QTimer
                QTimer.singleShot(0, self._parent_item._on_delete_clicked)
                return
        super().mousePressEvent(event)


class DraggableTextItem(QGraphicsTextItem):
    """
    Text overlay rendered directly in the video's graphics scene.
    Draggable, inline-editable (double-click / Edit button / sidebar), shrink-wrapped.
    Has corner resize handles and a floating Action Bar with Edit and Delete buttons when selected.
    """

    def __init__(self, item: _TextOverlayItem, video_item: QGraphicsVideoItem):
        super().__init__()
        self.item = item
        self._video_item = video_item
        self._delete_callback = None
        self._change_callback = None
        self._select_callback = None
        self._is_editing = False
        self._is_selected = False

        self.setFlag(QGraphicsTextItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsTextItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsTextItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setZValue(100)
        
        opt = QTextOption()
        opt.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        self.document().setDefaultTextOption(opt)
        self.document().setDocumentMargin(8.0)

        # Action bar child (Edit & Delete buttons)
        self._action_bar = _SelectionActionBarItem(self)

        # Corner resize handles
        self._resize_handles = [
            _ResizeHandleItem(self, 'tl'),
            _ResizeHandleItem(self, 'tr'),
            _ResizeHandleItem(self, 'bl'),
            _ResizeHandleItem(self, 'br')
        ]

        self.update_style()
        self._position_from_percent()

    def set_delete_callback(self, callback):
        self._delete_callback = callback

    def set_change_callback(self, callback):
        self._change_callback = callback

    def set_select_callback(self, callback):
        self._select_callback = callback

    def set_selected(self, selected: bool):
        self._is_selected = selected
        show_decorations = selected and not self._is_editing
        self._action_bar.setVisible(show_decorations)
        for h in self._resize_handles:
            h.setVisible(show_decorations)
        self.update()

    def _on_delete_clicked(self):
        if self._delete_callback:
            self._delete_callback()

    def _start_editing(self):
        """Enter inline text editing mode."""
        self._is_editing = True
        self._action_bar.setVisible(False)
        for h in self._resize_handles:
            h.setVisible(False)
        self.setFlag(QGraphicsTextItem.GraphicsItemFlag.ItemIsMovable, False)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextEditorInteraction)
        self.setCursor(Qt.CursorShape.IBeamCursor)
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        cursor = self.textCursor()
        cursor.select(QTextCursor.SelectionType.Document)
        self.setTextCursor(cursor)
        self.update()

    def update_style(self):
        font = QFont("Segoe UI", self.item.font_size)
        font.setBold(self.item.bold)
        font.setItalic(self.item.italic)
        font.setUnderline(self.item.underline)
        self.setFont(font)
        self.setDefaultTextColor(QColor(self.item.color))
        self.document().setDocumentMargin(8.0)

        vr = self._video_item.boundingRect()
        max_w = max(160, vr.width() * 0.7) if not vr.isEmpty() else 600

        if not self._is_editing:
            self.setPlainText(self.item.text)

        # Shrink-wrap width to ideal text content
        self.setTextWidth(-1)
        ideal_w = self.document().idealWidth()
        if ideal_w > max_w:
            self.setTextWidth(max_w)
        else:
            self.setTextWidth(-1)
            
        self._action_bar.update_layout()
        self._position_from_percent()
        self._update_child_positions()
        self.update()

    def _update_child_positions(self):
        br = self.boundingRect()
        bar_w = self._action_bar.boundingRect().width()
        bar_h = self._action_bar.boundingRect().height()
        bar_x = (br.width() - bar_w) / 2.0
        bar_y = -(bar_h + 8.0)
        if self.pos().y() + bar_y < 0:
            bar_y = br.height() + 8.0
        self._action_bar.setPos(bar_x, bar_y)

        if len(self._resize_handles) == 4:
            self._resize_handles[0].setPos(0, 0)
            self._resize_handles[1].setPos(br.width(), 0)
            self._resize_handles[2].setPos(0, br.height())
            self._resize_handles[3].setPos(br.width(), br.height())

    def _position_from_percent(self):
        vr = self._video_item.boundingRect()
        if vr.isEmpty():
            return
        x = vr.x() + (self.item.x_percent / 100.0) * vr.width() - self.boundingRect().width() / 2
        y = vr.y() + (self.item.y_percent / 100.0) * vr.height() - self.boundingRect().height() / 2
        self.setPos(x, y)

    def _update_percent_from_pos(self):
        vr = self._video_item.boundingRect()
        if vr.isEmpty():
            return
        cx = self.pos().x() + self.boundingRect().width() / 2
        cy = self.pos().y() + self.boundingRect().height() / 2
        self.item.x_percent = max(0, min(100, ((cx - vr.x()) / vr.width()) * 100))
        self.item.y_percent = max(0, min(100, ((cy - vr.y()) / vr.height()) * 100))

    def paint(self, painter, option, widget):
        self._update_child_positions()
        rect = self.boundingRect()

        # 1. Antialiased rounded dark background matching annotator
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(20, 20, 24, 190))
        painter.drawRoundedRect(rect, 6.0, 6.0)

        # 2. Selection highlight border when selected or editing
        if self._is_selected or self._is_editing:
            painter.setPen(QPen(QColor(59, 130, 246, 220), 1.5, Qt.PenStyle.SolidLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect, 6.0, 6.0)
        painter.restore()

        # 3. Render text content
        super().paint(painter, option, widget)

    def mouseDoubleClickEvent(self, event):
        self._start_editing()
        super().mouseDoubleClickEvent(event)

    def focusOutEvent(self, event):
        if self._is_editing:
            self._is_editing = False
            self.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
            self.setFlag(QGraphicsTextItem.GraphicsItemFlag.ItemIsMovable, True)
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            self.item.text = self.toPlainText()
            self.update_style()
            show_decorations = self._is_selected
            self._action_bar.setVisible(show_decorations)
            for h in self._resize_handles:
                h.setVisible(show_decorations)
            if self._change_callback:
                self._change_callback()
        super().focusOutEvent(event)

    def keyPressEvent(self, event):
        if not self._is_editing and self._is_selected:
            if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
                event.accept()
                self._on_delete_clicked()
                return
            elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_F2):
                event.accept()
                self._start_editing()
                return
        elif self._is_editing:
            if event.key() == Qt.Key.Key_Escape:
                event.accept()
                self.clearFocus()
                return
        super().keyPressEvent(event)
        if self._is_editing:
            self.item.text = self.toPlainText()
            # Dynamically shrink-wrap during live typing if width changed
            self.setTextWidth(-1)
            vr = self._video_item.boundingRect()
            max_w = max(160, vr.width() * 0.7) if not vr.isEmpty() else 600
            if self.document().idealWidth() > max_w:
                self.setTextWidth(max_w)
            self._update_child_positions()
            if self._change_callback:
                self._change_callback()

    def mousePressEvent(self, event):
        if self._select_callback:
            self._select_callback()
        if not self._is_editing:
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        if not self._is_editing:
            self._update_percent_from_pos()

    def mouseReleaseEvent(self, event):
        if not self._is_editing:
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            self._update_percent_from_pos()
        super().mouseReleaseEvent(event)

    def itemChange(self, change, value):
        if change == QGraphicsTextItem.GraphicsItemChange.ItemPositionChange and self._video_item:
            vr = self._video_item.boundingRect()
            br = self.boundingRect()
            new_pos = value
            x = max(vr.x(), min(new_pos.x(), vr.x() + vr.width() - br.width()))
            y = max(vr.y(), min(new_pos.y(), vr.y() + vr.height() - br.height()))
            return QPointF(x, y)
        return super().itemChange(change, value)


# ─────────────────────────────────────────────────────────────────────────────
#  Text Overlay Mini Timeline
# ─────────────────────────────────────────────────────────────────────────────

class TextOverlayTimeline(QWidget):
    """Small timeline showing when text overlays are active during the video."""
    overlay_time_changed = pyqtSignal(int, str, int)  # index, handle ('start' or 'end'), time_ms

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(28)
        self.setMouseTracking(True)
        self._duration_ms = 1
        self._position_ms = 0
        self._overlays: List[_TextOverlayItem] = []
        self._margin_x = 12
        
        self._hovered_idx = -1
        self._hovered_handle = ""  # "start" or "end"
        self._dragging_idx = -1
        self._drag_handle = ""

    def set_data(self, overlays, duration_ms, position_ms):
        self._overlays = overlays
        self._duration_ms = max(1, duration_ms)
        self._position_ms = position_ms
        self.update()

    def set_position(self, ms):
        self._position_ms = ms
        self.update()

    def mouseMoveEvent(self, event):
        x = event.position().x()
        ms = int(max(0, min(1.0, (x - self._margin_x) / max(1, self.width() - 2 * self._margin_x))) * self._duration_ms)
        track_w = max(1, self.width() - 2 * self._margin_x)
        
        # Snap to playhead
        px = self._margin_x + (self._position_ms / self._duration_ms) * track_w
        if abs(x - px) < 15:
            ms = self._position_ms
        
        if self._dragging_idx >= 0:
            # Snap to integer seconds or exactly playhead
            if ms != self._position_ms:
                ms = round(ms / 1000) * 1000
            self.overlay_time_changed.emit(self._dragging_idx, self._drag_handle, ms)
            # Show tooltip indicating current dragged time (offset so cursor doesn't overlap popup)
            QToolTip.showText(event.globalPosition().toPoint() + QPoint(12, 16), _format_time(ms), self)
            self.update()
            return

        # Hit test for handles
        hover_idx = -1
        hover_handle = ""
        
        for i, ov in enumerate(self._overlays):
            sx = self._margin_x + (ov.start_ms / self._duration_ms) * track_w
            ex = self._margin_x + (ov.end_ms / self._duration_ms) * track_w
            
            # Prioritize 'end' if we're near it, to ensure we don't block expanding
            if abs(x - ex) < 12:
                hover_idx = i
                hover_handle = "end"
                break
            elif abs(x - sx) < 12:
                hover_idx = i
                hover_handle = "start"
                break
                
        if hover_idx != self._hovered_idx or hover_handle != self._hovered_handle:
            self._hovered_idx = hover_idx
            self._hovered_handle = hover_handle
            if hover_handle:
                self.setCursor(Qt.CursorShape.SizeHorCursor)
                ov = self._overlays[hover_idx]
                t_ms = ov.end_ms if hover_handle == 'end' else ov.start_ms
                QToolTip.showText(event.globalPosition().toPoint() + QPoint(12, 16), _format_time(t_ms), self)
            else:
                self.unsetCursor()
                QToolTip.hideText()
        self.update()

    def mousePressEvent(self, event):
        QToolTip.hideText()
        if event.button() == Qt.MouseButton.LeftButton and self._hovered_idx >= 0 and self._hovered_handle:
            self._dragging_idx = self._hovered_idx
            self._drag_handle = self._hovered_handle
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging_idx = -1
            self._drag_handle = ""
            QToolTip.hideText()
            self.update()

    def paintEvent(self, _event):
        if not self._overlays:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        track_x = self._margin_x
        track_w = w - 2 * self._margin_x
        track_y = 4
        track_h = 20

        # Multi-row layout
        lanes = []
        overlay_lanes = {}
        for i, ov in enumerate(self._overlays):
            placed = False
            for lane_idx, lane_end_time in enumerate(lanes):
                if ov.start_ms >= lane_end_time:
                    lanes[lane_idx] = ov.end_ms
                    overlay_lanes[i] = lane_idx
                    placed = True
                    break
            if not placed:
                lanes.append(ov.end_ms)
                overlay_lanes[i] = len(lanes) - 1
                
        num_lanes = max(1, len(lanes))
        self.setFixedHeight(12 + num_lanes * 24)

        # Track background
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(25, 25, 28))
        p.drawRoundedRect(QRectF(track_x, track_y, track_w, num_lanes * 24), 4, 4)

        # Draw each overlay as a colored bar
        colors = [QColor('#0A84FF'), QColor('#FF9500'), QColor('#AF52DE'),
                  QColor('#34C759'), QColor('#FF3B30'), QColor('#FFD60A')]

        for i, ov in enumerate(self._overlays):
            sx = track_x + (ov.start_ms / self._duration_ms) * track_w
            ex = track_x + (ov.end_ms / self._duration_ms) * track_w
            bar_w = max(4, ex - sx)
            y_pos = track_y + overlay_lanes[i] * 24
            
            clr = colors[i % len(colors)]
            clr.setAlpha(160)
            p.setBrush(clr)
            
            # Highlight border if hovering handle
            if i == self._hovered_idx or i == self._dragging_idx:
                p.setPen(QPen(QColor(255, 255, 255, 180), 1.5))
            else:
                p.setPen(Qt.PenStyle.NoPen)
                
            p.drawRoundedRect(QRectF(sx, y_pos + 2, bar_w, 20), 3, 3)

            # Text label inside bar
            p.setPen(QColor(255, 255, 255, 220))
            font = QFont("Segoe UI", 7)
            p.setFont(font)
            fm = QFontMetrics(font)
            label = ov.text if fm.horizontalAdvance(ov.text) < bar_w - 4 else ov.text[:int(bar_w / 6)] + "…"
            clip_rect = QRectF(sx + 2, y_pos + 2, bar_w - 4, 20)
            p.drawText(clip_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, label)

        # Playhead (same style as FrameTimelineWidget)
        px = track_x + (self._position_ms / self._duration_ms) * track_w
        p.setPen(QPen(QColor(255, 255, 255, 200), 2))
        p.drawLine(QPointF(px, track_y), QPointF(px, track_y + num_lanes * 24))
        
        triangle = QPainterPath()
        triangle.moveTo(px - 6, track_y - 4)
        triangle.lineTo(px + 6, track_y - 4)
        triangle.lineTo(px, track_y + 4)
        triangle.closeSubpath()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255))
        p.drawPath(triangle)
        p.end()


# ─────────────────────────────────────────────────────────────────────────────
#  VideoPlayerWindow
# ─────────────────────────────────────────────────────────────────────────────

class VideoPlayerWindow(QWidget):
    closed = pyqtSignal(object)

    def __init__(self, filepath: str, output_folder: str = "", start_in_edit_mode: bool = False):
        super().__init__(None, Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

        self._filepath = filepath
        self._output_folder = output_folder or str(Path(filepath).parent)
        self._start_in_edit_mode = start_in_edit_mode
        self._edit_mode = False
        self._text_overlays: List[_TextOverlayItem] = []
        self._delete_regions: List[_DeleteRegionItem] = []
        self._mute_on_export = False
        self._export_worker: Optional[_ExportWorker] = None
        self._ss_worker: Optional[_ScreenshotWorker] = None
        self._thumb_extractor: Optional[_ThumbnailExtractor] = None
        self._zoom_extractor: Optional[_ThumbnailExtractor] = None
        self._selected_overlay_idx = -1

        self.setWindowTitle(f"WWR: Player — {Path(filepath).name}")
        icon_path = _asset('icon.ico')
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        self.setMinimumSize(720, 500)
        self.resize(960, 640)
        self.setWindowState(Qt.WindowState.WindowMaximized)

        self.setStyleSheet(f"""
            QWidget {{
                background: {CLR_BG.name()};
                color: {CLR_TEXT.name()};
                font-family: 'Segoe UI';
            }}
            QToolTip {{
                color: #FFFFFF; background: #202024; border: 1px solid #4A4A52;
                border-radius: 4px; padding: 5px 8px;
            }}
        """)

        self._build_ui()
        self._setup_player()

        QShortcut(QKeySequence("Space"), self, self._toggle_playback)
        QShortcut(QKeySequence("F11"), self, self._toggle_fullscreen)
        QShortcut(QKeySequence("Escape"), self, self._exit_fullscreen)
        QShortcut(QKeySequence("Left"), self, lambda: self._seek_relative(-5000))
        QShortcut(QKeySequence("Right"), self, lambda: self._seek_relative(5000))

        self._toast = _Toast(self)

        self._video_files = []
        self._current_video_index = -1
        self._refresh_video_list()

        self._thumbnails_loaded = False
        self._loading_overlay = _LoadingOverlay(self)
        self._saving_overlay = _SavingOverlay(self)
        self._closing = False
        self._close_ready = False
        self._close_deadline = 0.0
        self._close_poll_timer = QTimer(self)
        self._close_poll_timer.setInterval(50)
        self._close_poll_timer.timeout.connect(self._poll_close_workers)
        if self._start_in_edit_mode:
            QTimer.singleShot(0, self._enter_initial_edit_mode)

    def closeEvent(self, event):
        if self._closing and not self._close_ready:
            event.ignore()
            return

        if not self._close_ready and self._edit_mode:
            has_changes = (self._chk_trim.isChecked() or self._mute_on_export
                           or len(self._text_overlays) > 0 or len(self._delete_regions) > 0)
            if has_changes:
                reply = QMessageBox.question(
                    self, "Discard Changes?",
                    "You have unsaved edits. Are you sure you want to discard them and close the player?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No
                )
                if reply == QMessageBox.StandardButton.No:
                    event.ignore()
                    return

        active_workers = self._active_close_workers()
        if active_workers and not self._close_ready:
            event.ignore()
            self._begin_async_close(active_workers)
            return

        self._close_poll_timer.stop()
        try:
            self._player.setVideoOutput(None)
        except Exception:
            pass
        # QMediaPlayer.stop() can synchronously wait for the Windows media
        # backend while it drains a long/Opus stream.  That made the whole app
        # look hung during an otherwise completed close.  Detaching the output
        # is enough here; Qt tears the player down with the closing window.
        if self._video_view and self._video_view.scene():
            self._video_view.scene().clear()
        self.closed.emit(self)
        super().closeEvent(event)

    def _active_close_workers(self):
        return [
            worker for worker in (
                self._thumb_extractor, self._zoom_extractor,
                self._export_worker, self._ss_worker,
            ) if worker is not None and worker.isRunning()
        ]

    def _begin_async_close(self, workers):
        """Cancel workers without blocking Qt's GUI event loop."""
        import time
        self._closing = True
        self._close_deadline = time.monotonic() + 15.0
        try:
            self._player.pause()
        except Exception:
            pass
        self.setEnabled(False)
        self._loading_overlay.lbl.setText("Closing player…")
        self._loading_overlay.resize(self.size())
        self._loading_overlay.show()
        self._loading_overlay.raise_()
        for worker in workers:
            try:
                worker.stop()
            except Exception as exc:
                print(f"[VideoEditor] Worker cancellation warning: {exc}")
        self._close_poll_timer.start()

    def _poll_close_workers(self):
        import time
        if not self._active_close_workers():
            self._close_poll_timer.stop()
            self._close_ready = True
            self.close()
            return
        if time.monotonic() >= self._close_deadline:
            self._close_poll_timer.stop()
            self._closing = False
            self.setEnabled(True)
            self._loading_overlay.hide()
            QMessageBox.warning(
                self, "Still Closing",
                "Media cleanup is taking longer than expected. The player remains open so no running worker is destroyed."
            )

    def _enter_initial_edit_mode(self):
        if not self._edit_mode and not self._closing:
            self._toggle_edit_mode()

    # ── UI Build ──────────────────────────────────────────────────────────────

    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Fullscreen-only chrome reuses the top-bar surface; normal windows
        # retain their native title bar and lose no video space.
        self._top_bar = QWidget(self)
        self._top_bar.setObjectName("FullscreenChrome")
        self._top_bar.setFixedHeight(42)
        self._top_bar.setStyleSheet("""
            QWidget#FullscreenChrome { background: rgba(12, 15, 21, 0.94); }
            QPushButton { background: transparent; border: none; padding: 6px 12px; }
            QPushButton:hover, QPushButton:focus { background: #343A46; }
        """)
        top_layout = QHBoxLayout(self._top_bar)
        top_layout.setContentsMargins(8, 2, 8, 2)
        top_layout.addStretch()
        self._btn_exit_fullscreen = QPushButton("Exit fullscreen")
        self._btn_exit_fullscreen.setIcon(QIcon(_asset("ve_fullscreen_exit.png")))
        self._btn_exit_fullscreen.clicked.connect(self._exit_fullscreen)
        self._btn_minimize = QPushButton("Minimize")
        self._btn_minimize.clicked.connect(self._minimize_player)
        self._btn_close_player = QPushButton("Close player")
        self._btn_close_player.setIcon(QIcon(_asset("ve_close.png")))
        self._btn_close_player.clicked.connect(self.close)
        for button in (self._btn_exit_fullscreen, self._btn_minimize, self._btn_close_player):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            top_layout.addWidget(button)
        self._top_bar.hide()

        self._btn_screenshot = QPushButton(" Screenshot")
        self._btn_screenshot.setIcon(QIcon(_asset("ve_screenshot.png")))
        self._btn_screenshot.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_screenshot.setStyleSheet("""
            QPushButton { background: #262628; color: rgba(255,255,255,0.8); border: 1px solid #3C3C3E;
                          border-radius: 6px; padding: 5px 12px; font-size: 11px; font-weight: 600; }
            QPushButton:hover { background: #333336; border-color: #5C5C5E; }
        """)
        self._btn_screenshot.clicked.connect(self._take_screenshot)

        self._btn_edit = QPushButton(" Edit")
        self._btn_edit.setIcon(QIcon(_asset("ve_edit.png")))
        self._btn_edit.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_edit.setCheckable(True)
        self._btn_edit.setStyleSheet("""
            QPushButton { background: #DC2626; color: #FFFFFF; border: none;
                           border-radius: 6px; padding: 5px 14px; font-size: 11px; font-weight: 700; }
            QPushButton:hover { background: #B91C1C; }
            QPushButton:checked { background: #1D4ED8; }
            QPushButton:checked:hover { background: #1E40AF; }
        """)
        self._btn_edit.clicked.connect(self._toggle_edit_mode)

        # ── Content Area ─────────────────────────────────────────────────────
        content_area = QHBoxLayout()
        content_area.setContentsMargins(0, 0, 0, 0)
        content_area.setSpacing(0)

        # Video display: QGraphicsView with QGraphicsVideoItem
        self._video_view = _VideoGraphicsView()
        self._video_view.setMouseTracking(True)
        self._video_view.viewport().setMouseTracking(True)
        self._video_view.viewport().installEventFilter(self)
        self._video_view.installEventFilter(self)
        self._video_view.double_clicked.connect(self._toggle_fullscreen)
        self._video_view.clicked.connect(self._toggle_playback)
        content_area.addWidget(self._video_view, 1)

        # Fullscreen auto-hide timer
        self._fullscreen_controls_timer = QTimer(self)
        self._fullscreen_controls_timer.setInterval(2000)
        self._fullscreen_controls_timer.setSingleShot(True)
        self._fullscreen_controls_timer.timeout.connect(self._hide_fullscreen_controls)

        # Editor side panel (hidden by default)
        self._editor_panel = self._build_editor_panel()
        self._editor_panel.setVisible(False)
        content_area.addWidget(self._editor_panel)

        self._main_layout = main_layout
        main_layout.addLayout(content_area, 1)

        # ── Bottom Controls (floating overlay — NOT in layout) ────────────────
        # By making this a direct child positioned via resizeEvent,
        # showing/hiding in fullscreen never resizes the video area.
        self._controls_widget = QWidget(self)
        self._controls_widget.setObjectName("GlassControls")
        self._controls_widget.setStyleSheet("""
            QWidget#GlassControls {
                background: rgba(12, 15, 21, 0.96);
                border-top: 1px solid rgba(255, 255, 255, 0.12);
                border-top-left-radius: 0px;
                border-top-right-radius: 0px;
            }
        """)
        ctrl_layout = QVBoxLayout(self._controls_widget)
        ctrl_layout.setContentsMargins(16, 10, 16, 10)
        ctrl_layout.setSpacing(6)

        # Custom glass seekbar (player mode)
        self._seekbar = _GlassSeekbar()
        self._seekbar.setRange(0, 0)
        self._seekbar.positionChanged.connect(self._on_seekbar_moved)
        self._seekbar.sliderPressed.connect(self._on_seekbar_pressed)
        self._seekbar.sliderReleased.connect(self._on_seekbar_released)
        self._seekbar_dragging = False
        ctrl_layout.addWidget(self._seekbar)

        # Frame timeline (edit mode only — hidden by default)
        self._timeline = FrameTimelineWidget()
        self._timeline.position_changed.connect(self._on_timeline_seek)
        self._timeline.preview_seek.connect(self._on_timeline_preview)
        self._timeline.setVisible(False)
        self._timeline.overlay_time_changed.connect(self._on_text_timeline_drag)
        self._timeline.overlay_selected.connect(self._select_text_overlay)
        self._timeline.lanes_changed.connect(self._refresh_controls_geometry)
        ctrl_layout.addWidget(self._timeline)

        # ── Three-zone symmetric control row ──
        btn_row = QHBoxLayout()
        btn_row.setSpacing(0)
        btn_row.setContentsMargins(0, 0, 0, 0)

        # ── LEFT ZONE ──
        left_zone = QHBoxLayout()
        left_zone.setSpacing(8)
        left_zone.setContentsMargins(0, 0, 0, 0)

        self._lbl_time = QLabel("00:00 / 00:00")
        self._lbl_time.setStyleSheet("""
            color: rgba(255,255,255,0.6); font-size: 12px;
            font-family: 'Segoe UI', sans-serif; font-weight: 500;
            letter-spacing: 0.3px; border: none; background: transparent;
        """)
        self._lbl_time.setFixedWidth(120)
        left_zone.addWidget(self._lbl_time)

        self._lbl_speed = QLabel("Speed")
        self._lbl_speed.setStyleSheet(
            "color: #9AA4B2; font-size: 10px; font-weight: 700; "
            "border: none; background: transparent;"
        )
        left_zone.addWidget(self._lbl_speed)

        self._speed_control = QWidget()
        self._speed_control.setObjectName("SpeedControl")
        self._speed_control.setFixedSize(64, 30)
        self._speed_control.setStyleSheet("""
            QWidget#SpeedControl { background: #181D27; border: 1px solid #343B48; border-radius: 8px; }
        """)
        speed_layout = QHBoxLayout(self._speed_control)
        speed_layout.setContentsMargins(2, 0, 2, 0)
        speed_layout.setSpacing(0)

        self._cmb_speed = QComboBox()
        self._cmb_speed.addItems(["0.25x", "0.5x", "1x", "1.5x", "2x"])
        self._cmb_speed.setCurrentText("1x")
        self._cmb_speed.setFixedWidth(60)
        self._cmb_speed.setFixedHeight(26)
        self._cmb_speed.setCursor(Qt.CursorShape.PointingHandCursor)
        self._cmb_speed.setStyleSheet("""
            QComboBox {
                background: transparent; color: #F8FAFC; border: none;
                padding: 1px 2px 1px 5px; font-size: 11px; font-weight: 700;
            }
            QComboBox:hover { background: rgba(255,255,255,0.07); border-radius: 6px; }
            QComboBox::drop-down { border: none; width: 18px; }
            QComboBox QAbstractItemView {
                background: #181D27; color: #FFFFFF; border: 1px solid #343B48;
                selection-background-color: #FF4055;
            }
        """)
        self._cmb_speed.currentTextChanged.connect(self._on_speed_changed)
        speed_layout.addWidget(self._cmb_speed)
        left_zone.addWidget(self._speed_control)

        left_zone.addStretch()

        left_widget = QWidget()
        left_widget.setLayout(left_zone)
        left_widget.setStyleSheet("border: none; background: transparent;")
        btn_row.addWidget(left_widget, 1)

        # ── CENTER ZONE (transport controls) ──
        center_zone = QHBoxLayout()
        center_zone.setSpacing(6)
        center_zone.setContentsMargins(0, 0, 0, 0)
        center_zone.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._btn_prev = self._make_nav_btn("ve_prev.png", 36)
        self._btn_prev.clicked.connect(self._play_prev_video)
        center_zone.addWidget(self._btn_prev)

        self._btn_back_30 = self._make_transport_btn("ve_back_30.png", 36)
        self._btn_back_30.clicked.connect(lambda: self._seek_relative(-30000))
        center_zone.addWidget(self._btn_back_30)

        center_zone.addSpacing(4)

        # Play/Pause — glassmorphic accent button
        self._btn_play = QPushButton()
        self._btn_play.setFixedSize(42, 42)
        self._btn_play.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_play.setToolTip("Play preview")
        self._btn_play.setIcon(QIcon(_asset("ve_play.png")))
        self._btn_play.setIconSize(QSize(20, 20))
        self._update_play_button_style(False)
        self._btn_play.clicked.connect(self._toggle_playback)
        center_zone.addWidget(self._btn_play)

        center_zone.addSpacing(4)

        self._btn_fwd_30 = self._make_transport_btn("ve_fwd_30.png", 36)
        self._btn_fwd_30.clicked.connect(lambda: self._seek_relative(30000))
        center_zone.addWidget(self._btn_fwd_30)

        self._btn_next = self._make_nav_btn("ve_next.png", 36)
        self._btn_next.clicked.connect(self._play_next_video)
        center_zone.addWidget(self._btn_next)

        center_widget = QWidget()
        center_widget.setLayout(center_zone)
        center_widget.setStyleSheet("border: none; background: transparent;")
        btn_row.addWidget(center_widget, 1)

        # ── RIGHT ZONE (fullscreen + volume) ──
        right_zone = QHBoxLayout()
        right_zone.setSpacing(6)
        right_zone.setContentsMargins(0, 0, 0, 0)

        right_zone.addStretch()

        self._btn_fullscreen = QPushButton()
        self._btn_fullscreen.setFixedSize(30, 30)
        self._btn_fullscreen.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_fullscreen.setToolTip("Fullscreen")
        self._btn_fullscreen.setIcon(QIcon(_asset("ve_fullscreen.png")))
        self._btn_fullscreen.setIconSize(QSize(16, 16))
        self._btn_fullscreen.setStyleSheet("""
            QPushButton {
                background: rgba(255,255,255,0.08); border: 1px solid rgba(255,255,255,0.06);
                border-radius: 6px; color: rgba(255,255,255,0.6);
            }
            QPushButton:hover { background: rgba(255,255,255,0.15); color: #FFFFFF; }
        """)
        self._btn_fullscreen.clicked.connect(self._toggle_fullscreen)

        self._playback_only_widgets = [
            self._btn_prev, self._btn_back_30, self._btn_fwd_30,
            self._btn_next, self._lbl_speed, self._speed_control, self._btn_fullscreen
        ]

        self._btn_vol = QPushButton()
        self._btn_vol.setIcon(QIcon(_asset("ve_vol_up.png")))
        self._btn_vol.setFixedSize(28, 28)
        self._btn_vol.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_vol.setToolTip("Mute preview")
        self._btn_vol.setStyleSheet("""
            QPushButton {
                background: transparent; border: none;
                font-size: 14px; color: rgba(255,255,255,0.6);
            }
            QPushButton:hover { color: #FFFFFF; }
        """)
        self._btn_vol.clicked.connect(self._toggle_mute)
        right_zone.addWidget(self._btn_vol)

        self._sld_volume = QSlider(Qt.Orientation.Horizontal)
        self._sld_volume.setRange(0, 100)
        self._sld_volume.setValue(80)
        self._sld_volume.setFixedWidth(80)
        self._sld_volume.setStyleSheet(_VOLUME_SLIDER_STYLE)
        self._sld_volume.valueChanged.connect(self._on_volume_changed)
        right_zone.addWidget(self._sld_volume)

        # File actions are bottom-right beside the other playback controls.
        right_zone.addWidget(self._btn_fullscreen)
        right_zone.addWidget(self._btn_screenshot)
        right_zone.addWidget(self._btn_edit)

        right_widget = QWidget()
        right_widget.setLayout(right_zone)
        right_widget.setStyleSheet("border: none; background: transparent;")
        btn_row.addWidget(right_widget, 1)

        self._btn_row_widget = QWidget()
        self._btn_row_widget.setLayout(btn_row)
        self._btn_row_widget.setStyleSheet("border: none; background: transparent;")
        ctrl_layout.addWidget(self._btn_row_widget)
        # NOTE: controls_widget is NOT added to main_layout.
        # It's positioned absolutely in resizeEvent — this is the key fix.
        self._controls_height = 90  # estimated; recalculated in resizeEvent

        # Export progress bar (still in layout)
        self._progress_bar = QProgressBar()
        self._progress_bar.setFixedHeight(3)
        self._progress_bar.setRange(0, 0)
        self._progress_bar.setStyleSheet("QProgressBar { background: #1C1C1E; border: none; } QProgressBar::chunk { background: #DC2626; }")
        self._progress_bar.setVisible(False)
        main_layout.addWidget(self._progress_bar)

        # Treat movement over any fullscreen chrome as user activity. Child
        # controls receive their own mouse events, so filtering only the video
        # viewport would allow the bar to disappear while it was being used.
        self._fullscreen_activity_widgets = [self._top_bar, self._controls_widget]
        self._fullscreen_activity_widgets.extend(self._top_bar.findChildren(QWidget))
        self._fullscreen_activity_widgets.extend(self._controls_widget.findChildren(QWidget))
        for widget in self._fullscreen_activity_widgets:
            widget.setMouseTracking(True)
            widget.installEventFilter(self)

    def _update_play_button_style(self, is_playing: bool):
        padding_style = "padding: 0px;" if is_playing else "padding-left: 2px; padding-top: 0px; padding-bottom: 0px; padding-right: 0px;"
        self._btn_play.setStyleSheet(f"""
            QPushButton {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #EF4444, stop:1 #B91C1C);
                border: 1px solid rgba(255,255,255,0.15);
                border-radius: 21px; color: white;
                {padding_style}
            }}
            QPushButton:hover {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #F05252, stop:1 #DC2626);
            }}
            QPushButton:pressed {{ background: #991B1B; }}
        """)

    def _make_nav_btn(self, icon_name: str, size: int) -> QPushButton:
        btn = QPushButton()
        btn.setFixedSize(size, size)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setIcon(QIcon(_asset(icon_name)))
        btn.setIconSize(QSize(18, 18))
        btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; border: none;
                border-radius: {size // 2}px; color: white;
            }}
            QPushButton:hover {{ background: rgba(255,255,255,0.08); }}
            QPushButton:pressed {{ background: rgba(255,255,255,0.04); }}
            QPushButton:disabled {{ background: transparent; color: rgba(255,255,255,0.15); }}
        """)
        return btn

    def _make_transport_btn(self, icon_name: str, size: int) -> QPushButton:
        btn = QPushButton()
        btn.setFixedSize(size, size)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setIcon(QIcon(_asset(icon_name)))
        btn.setIconSize(QSize(20, 20))
        btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: white; border: none;
                border-radius: {size // 2}px;
            }}
            QPushButton:hover {{ background: rgba(255,255,255,0.08); }}
            QPushButton:pressed {{ background: rgba(255,255,255,0.04); }}
        """)
        return btn

    def _build_editor_panel(self) -> QWidget:
        PANEL_BG = "#11151D"
        CARD_BG = "#181D27"
        BORDER = "#343B48"
        TEXT_PRIMARY = "rgba(255,255,255,0.92)"
        TEXT_SECONDARY = "rgba(255,255,255,0.50)"
        TEXT_DIM = "rgba(255,255,255,0.30)"
        ACCENT = "#FF4055"

        panel = QWidget()
        panel.setFixedWidth(300)
        panel.setObjectName("EditorPanel")
        panel.setStyleSheet(f"QWidget#EditorPanel {{ background: #11151D; border-left: 1px solid #343B48; }}")

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Header ──
        header = QWidget()
        header.setFixedHeight(46)
        header.setStyleSheet("background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #202633, stop:1 #151923); border-bottom: 1px solid #343B48;")
        h_lay = QHBoxLayout(header)
        h_lay.setContentsMargins(16, 0, 10, 0)

        lbl_h = QLabel("Edit")
        lbl_h.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 14px; font-weight: 700; font-family: 'Segoe UI'; border: none;")
        h_lay.addWidget(lbl_h, 1)

        btn_close = QPushButton()
        btn_close.setIcon(QIcon(_asset("ve_close.png")))
        btn_close.setFixedSize(28, 28)
        btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_close.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {TEXT_SECONDARY}; border: none; border-radius: 6px; font-size: 13px; }}
            QPushButton:hover {{ background: rgba(220,38,38,0.2); color: #FF6B6B; }}
        """)
        btn_close.clicked.connect(self._toggle_edit_mode)
        h_lay.addWidget(btn_close)
        layout.addWidget(header)

        # ── Scrollable Content ──
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(f"""
            QScrollArea {{ background: {PANEL_BG}; border: none; }}
            QScrollBar:vertical {{ background: transparent; width: 4px; margin: 4px 0; }}
            QScrollBar::handle:vertical {{ background: rgba(255,255,255,0.10); border-radius: 2px; min-height: 24px; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        """)

        content = QWidget()
        content.setStyleSheet(f"background: {PANEL_BG}; border: none;")
        self._edit_layout = QVBoxLayout(content)
        self._edit_layout.setContentsMargins(12, 12, 12, 12)
        self._edit_layout.setSpacing(12)

        # ═══════════ CLIP ═══════════
        self._edit_layout.addWidget(self._panel_section_header("ve_trim.png", "Clip"))

        self._chk_trim = self._make_tool_btn("ve_trim.png", "Trim", CARD_BG, BORDER)
        self._chk_trim.clicked.connect(self._on_trim_toggled)
        self._edit_layout.addWidget(self._chk_trim)

        self._edit_layout.addSpacing(10)
        self._edit_layout.addWidget(self._panel_section_header("ve_delete.png", "Delete Segments"))
        
        self._delete_regions_container = QVBoxLayout()
        self._delete_regions_container.setSpacing(8)
        self._edit_layout.addLayout(self._delete_regions_container)

        btn_add_del = QPushButton(" Add Delete Region")
        btn_add_del.setIcon(QIcon(_asset("ve_add.png")))
        btn_add_del.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_add_del.setFixedHeight(32)
        btn_add_del.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {TEXT_SECONDARY};
                border: 1px solid #555555; border-radius: 6px;
                font-size: 11px; font-weight: 500;
            }}
            QPushButton:hover {{ background: {CARD_BG}; color: {TEXT_PRIMARY}; border-color: #FFFFFF; }}
        """)
        btn_add_del.clicked.connect(self._add_delete_region)
        self._edit_layout.addWidget(btn_add_del)

        # separator
        self._edit_layout.addWidget(self._thin_separator(BORDER))

        # ═══════════ AUDIO ═══════════
        self._edit_layout.addWidget(self._panel_section_header("ve_vol_up.png", "Audio"))

        row_audio = QHBoxLayout()
        row_audio.setContentsMargins(0, 0, 0, 0)
        lbl_audio = QLabel("Export Audio")
        lbl_audio.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 13px; font-weight: 500;")
        
        self._toggle_audio = _PillToggle()
        self._toggle_audio.setChecked(True)  # On by default
        self._toggle_audio.toggled.connect(self._on_mute_export_toggled)
        
        row_audio.addWidget(lbl_audio)
        row_audio.addStretch()
        row_audio.addWidget(self._toggle_audio)
        
        self._edit_layout.addLayout(row_audio)

        # separator
        self._edit_layout.addWidget(self._thin_separator(BORDER))

        # ═══════════ TEXT ═══════════
        self._edit_layout.addWidget(self._panel_section_header("ve_text.png", "Text Overlay"))

        self._text_overlays_container = QVBoxLayout()
        self._text_overlays_container.setSpacing(8)
        self._edit_layout.addLayout(self._text_overlays_container)

        btn_add_text = QPushButton(" Add Text")
        btn_add_text.setIcon(QIcon(_asset("ve_add.png")))
        btn_add_text.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_add_text.setFixedHeight(32)
        btn_add_text.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {TEXT_SECONDARY};
                border: 1px solid #555555; border-radius: 6px;
                font-size: 11px; font-weight: 500;
            }}
            QPushButton:hover {{ background: {CARD_BG}; color: {TEXT_PRIMARY}; border-color: #FFFFFF; }}
        """)
        btn_add_text.clicked.connect(self._add_text_overlay)
        self._edit_layout.addWidget(btn_add_text)

        self._edit_layout.addStretch()

        scroll.setWidget(content)
        layout.addWidget(scroll, 1)

        # ── Bottom Action Bar ──
        action_bar = QWidget()
        action_bar.setStyleSheet(f"background: {PANEL_BG}; border-top: 1px solid {BORDER};")
        ab = QVBoxLayout(action_bar)
        ab.setContentsMargins(12, 10, 12, 12)
        ab.setSpacing(8)

        row_save = QHBoxLayout()
        row_save.setSpacing(8)

        self._btn_save = QPushButton(" Save")
        self._btn_save.setIcon(QIcon(_asset("ve_save.png")))
        self._btn_save.setFixedHeight(38)
        self._btn_save.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_save.setStyleSheet(f"""
            QPushButton {{
                background: {ACCENT}; color: #FFFFFF; border: none;
                border-radius: 8px; font-size: 13px; font-weight: 700; font-family: 'Segoe UI';
            }}
            QPushButton:hover {{ background: #EF4444; }}
            QPushButton:disabled {{ background: #333336; color: rgba(255,255,255,0.25); }}
        """)
        self._btn_save.clicked.connect(self._save_overwrite)
        row_save.addWidget(self._btn_save, 1)

        self._btn_save_as = QPushButton(" Save As")
        self._btn_save_as.setIcon(QIcon(_asset("ve_save.png")))
        self._btn_save_as.setFixedHeight(38)
        self._btn_save_as.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_save_as.setStyleSheet(f"""
            QPushButton {{
                background: {CARD_BG}; color: rgba(255,255,255,0.85);
                border: 1px solid {BORDER}; border-radius: 8px;
                font-size: 13px; font-weight: 600; font-family: 'Segoe UI';
            }}
            QPushButton:hover {{ background: #303034; border-color: #555; color: #FFFFFF; }}
            QPushButton:disabled {{ background: #1C1C1E; color: rgba(255,255,255,0.2); border-color: #222; }}
        """)
        self._btn_save_as.clicked.connect(self._save_as)
        row_save.addWidget(self._btn_save_as, 1)

        ab.addLayout(row_save)
        layout.addWidget(action_bar)

        return panel

    # ── Sidebar helper widgets ────────────────────────────────────────────────

    def _panel_section_header(self, icon_name: str, label: str) -> QWidget:
        """Consistent section header: icon + label."""
        w = QWidget()
        w.setFixedHeight(24)
        w.setStyleSheet("background: transparent; border: none;")
        lay = QHBoxLayout(w)
        lay.setContentsMargins(4, 0, 0, 0)
        lay.setSpacing(6)

        lbl_icon = QLabel()
        pm = QPixmap(_asset(icon_name))
        if not pm.isNull():
            lbl_icon.setPixmap(pm.scaled(14, 14, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        lbl_icon.setFixedWidth(16)
        lbl_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(lbl_icon)

        lbl = QLabel(label)
        lbl.setStyleSheet("color: rgba(255,255,255,0.45); font-size: 11px; font-weight: 600; letter-spacing: 0.5px; font-family: 'Segoe UI'; border: none;")
        lay.addWidget(lbl, 1)

        return w

    def _thin_separator(self, color: str) -> QFrame:
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background: {color}; border: none;")
        return sep

    def _make_tool_btn(self, icon_name: str, label: str, card_bg: str, border: str) -> QPushButton:
        """Icon + label toggle button."""
        btn = QPushButton(f" {label}")
        btn.setIcon(QIcon(_asset(icon_name)))
        btn.setIconSize(QSize(16, 16))
        btn.setCheckable(True)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFixedHeight(36)
        btn.setStyleSheet(f"""
            QPushButton {{
                background: {card_bg}; color: rgba(255,255,255,0.88);
                border: 1px solid {border}; border-radius: 8px;
                padding: 0 14px; font-size: 12px; font-weight: 600;
                text-align: left; font-family: 'Segoe UI';
            }}
            QPushButton:hover {{ background: #2E2E32; border-color: #444; }}
            QPushButton:checked {{
                background: rgba(220,38,38,0.12); border: 1px solid #DC2626;
                color: #FFFFFF;
            }}
            QPushButton:checked:hover {{ background: rgba(220,38,38,0.18); }}
        """)
        return btn

    # ── Player Setup ──────────────────────────────────────────────────────────

    def _setup_player(self):
        self._media_devices = QMediaDevices(self)
        self._audio_output = QAudioOutput()
        self._audio_output.setVolume(0.8)
        self._audio_output.setDevice(self._media_devices.defaultAudioOutput())
        self._media_devices.audioOutputsChanged.connect(self._sync_default_audio_output)
        self._audio_device_timer = QTimer(self)
        self._audio_device_timer.setInterval(1000)
        self._audio_device_timer.timeout.connect(self._sync_default_audio_output)
        self._audio_device_timer.start()

        self._player = QMediaPlayer()
        self._player.setAudioOutput(self._audio_output)
        # Set video output to the QGraphicsVideoItem inside the view
        self._player.setVideoOutput(self._video_view.video_item)

        self._player.setSource(QUrl.fromLocalFile(self._filepath))

        self._player.durationChanged.connect(self._on_duration_changed)
        self._player.positionChanged.connect(self._on_position_changed)
        self._player.playbackStateChanged.connect(self._on_state_changed)
        self._player.errorOccurred.connect(self._on_media_error)

        if not self._start_in_edit_mode:
            QTimer.singleShot(300, self._player.play)

    def _on_default_audio_output_changed(self, device):
        """Follow Windows when headphones or another default output is selected."""
        if not hasattr(self, '_audio_output'):
            return
        was_muted = self._audio_output.isMuted()
        volume = self._audio_output.volume()
        self._audio_output.setDevice(device)
        self._audio_output.setVolume(volume)
        self._audio_output.setMuted(was_muted)
        if hasattr(self, '_toast'):
            description = device.description() if hasattr(device, 'description') else 'Windows default output'
            self._toast.show_message(f"Audio output switched to {description}", 2500, "rgba(34, 197, 94, 0.92)")

    def _sync_default_audio_output(self):
        """Re-read the default after Windows reports an output-device change."""
        default_device = self._media_devices.defaultAudioOutput()
        current_device = self._audio_output.device()
        try:
            if current_device.id() == default_device.id():
                return
        except Exception:
            pass
        self._on_default_audio_output_changed(default_device)

    def _on_media_error(self, error, error_string: str = ""):
        if error == QMediaPlayer.Error.NoError:
            return
        detail = error_string or self._player.errorString() or "Unsupported or damaged media"
        print(f"[VideoEditor] Playback error: {detail}")
        self._btn_play.setEnabled(False)
        self._timeline.setEnabled(False)
        if hasattr(self, '_toast'):
            self._toast.show_message(
                f"Cannot play this video: {detail}", 4500,
                "rgba(220, 38, 38, 0.92)",
            )

    # ── Thumbnail Extraction ──────────────────────────────────────────────────

    def _extract_thumbnails(self):
        if self._thumb_extractor and self._thumb_extractor.isRunning():
            self._thumb_extractor.stop()
            self._thumb_extractor.wait(5000)

        self._loading_overlay.resize(self.size())
        self._loading_overlay.show()
        self._loading_overlay.raise_()

        self._thumb_extractor = _ThumbnailExtractor(self._filepath, num_frames=40, thumb_height=56)
        self._thumb_extractor.thumbnails_ready.connect(self._on_thumbnails_ready)
        self._thumb_extractor.error.connect(self._on_thumbnail_error)
        self._thumb_extractor.start()

    def _on_thumbnails_ready(self, thumbnails: list, start_sec: float, fps_rate: float):
        pixmaps = [QPixmap.fromImage(item) if isinstance(item, QImage) else item for item in thumbnails]
        if self._thumb_extractor is not None and self.sender() is self._thumb_extractor:
            # Base filmstrip extraction
            self._timeline.set_thumbnails(pixmaps)
            self._loading_overlay.hide()
        else:
            # Dense zoom extraction — build {second: pixmap} dict
            new_frames = {}
            for i, pm in enumerate(pixmaps):
                t_sec = int(start_sec + i / max(0.001, fps_rate))
                new_frames[t_sec] = pm
            self._timeline.update_frame_cache(new_frames)

    def _on_thumbnail_error(self, err: str):
        print(f"[Thumbnails] {err}")
        if self._loading_overlay:
            self._loading_overlay.hide()
        self._timeline.set_thumbnails([])
        self._thumbnails_loaded = False
        self._toast.show_message("Preview thumbnails unavailable", 2500, "rgba(220, 38, 38, 0.92)")

    def _fetch_frames_for_range(self, start_sec: float, end_sec: float):
        """Launch a targeted dense extraction for the visible zoom window."""
        if self._thumb_extractor and self._thumb_extractor.isRunning():
            return  # Don't interrupt base extraction
            
        if self._zoom_extractor and self._zoom_extractor.isRunning():
            return  # Debounce will handle it later if needed
            
        dur = max(0.5, end_sec - start_sec)
        
        vis_width = self._timeline._filmstrip_rect().width() if self._timeline else 1000
        num_frames_needed = max(1.0, vis_width / 80.0)
        target_fps = num_frames_needed / dur
        target_fps = min(15.0, max(1.0, target_fps))
        
        extractor = _ThumbnailExtractor(
            self._filepath, thumb_height=56,
            start_sec=start_sec, end_sec=end_sec, target_fps=target_fps
        )
        extractor.thumbnails_ready.connect(self._on_thumbnails_ready)
        extractor.error.connect(lambda e: print(f"[ZoomFrames] {e}"))
        extractor.start()
        # Keep reference to avoid GC (don't override base extractor)
        self._zoom_extractor = extractor


    # ── Playback Controls ─────────────────────────────────────────────────────

    def _is_typing_active(self) -> bool:
        fw = QApplication.focusWidget()
        if fw and isinstance(fw, (QLineEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox)):
            return True
        if hasattr(self, '_video_view') and self._video_view and self._video_view.scene():
            fi = self._video_view.scene().focusItem()
            if fi and getattr(fi, '_is_editing', False):
                return True
        return False

    def _toggle_playback(self):
        if self._is_typing_active():
            return
        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()
        else:
            if self._edit_mode and self._chk_trim.isChecked():
                start_ms, end_ms = self._timeline.get_trim()
                pos = self._player.position()
                if pos >= end_ms or pos < start_ms:
                    self._player.setPosition(start_ms)
            self._player.play()

    def _seek_relative(self, delta_ms: int):
        if self._is_typing_active():
            return
        self._seek_to_position(self._player.position() + delta_ms)

    def _seek_to_position(self, ms: int, *, preview: bool = False):
        """Stopped players do not decode seek frames; paused players do.

        Enter paused state before seeking after EOF, without a play/pause
        timer or separate frame decoder. A playing seek stays playing.
        """
        if self._player.duration() <= 0 or not self._player.isSeekable():
            return
        position = max(0, min(int(ms), self._player.duration() - 1))
        if preview or self._player.playbackState() == QMediaPlayer.PlaybackState.StoppedState:
            self._player.pause()
        self._player.setPosition(position)

    def _on_timeline_seek(self, ms: int):
        """User clicked on timeline to move playhead."""
        self._seek_to_position(ms)

    def _on_timeline_preview(self, ms: int):
        """Handle drag is being moved — seek player for frame preview only."""
        self._seek_to_position(ms, preview=True)
        # Update button text in real-time as handles are dragged
        if self._chk_trim.isChecked():
            s, e = self._timeline.get_trim()
            self._chk_trim.setText(f"Trim  ·  {_format_time(s)} → {_format_time(e)}")
            
        for i, reg in enumerate(self._delete_regions):
            row_w = self._delete_regions_container.itemAt(i).widget()
            if isinstance(row_w, _DeleteRegionRow):
                row_w.set_start_time(reg.start_ms)
                row_w.set_end_time(reg.end_ms)

    def _on_seekbar_pressed(self):
        self._seekbar_dragging = True

    def _on_seekbar_moved(self, position: int):
        self._seek_to_position(position)

    def _on_seekbar_released(self):
        self._seekbar_dragging = False
        self._seek_to_position(self._seekbar.value())

    def _on_duration_changed(self, duration: int):
        self._timeline.setEnabled(duration > 0)
        self._timeline.set_duration(duration)
        self._seekbar.setRange(0, duration)
        self._update_time_label()

    def _on_position_changed(self, position: int):
        self._timeline.set_position(position)
        if not self._seekbar_dragging:
            self._seekbar.setValue(position)
        self._update_time_label()

        # Restrict playback to trim region
        if self._edit_mode and self._chk_trim.isChecked():
            start_ms, end_ms = self._timeline.get_trim()
            if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                if end_ms <= position <= end_ms + 250:
                    self._player.pause()
                    self._player.setPosition(end_ms)

        # Skip delete regions during playback if we are previewing edit mode
        if self._edit_mode and self._delete_regions and self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            for reg in self._delete_regions:
                # If we entered a delete region (add a bit of slack to prevent loops)
                if reg.start_ms <= position < reg.end_ms - 50:
                    self._player.setPosition(reg.end_ms)
                    break

        # Update text overlay visibility
        for overlay in self._text_overlays:
            if overlay._gfx_item:
                visible = (overlay.start_ms <= position <= overlay.end_ms)
                if overlay._gfx_item.isVisible() != visible:
                    overlay._gfx_item.setVisible(visible)


    def _on_state_changed(self, state):
        is_playing = (state == QMediaPlayer.PlaybackState.PlayingState)
        if is_playing:
            self._btn_play.setIcon(QIcon(_asset("ve_pause.png")))
            self._btn_play.setToolTip("Pause preview")
        else:
            self._btn_play.setIcon(QIcon(_asset("ve_play.png")))
            self._btn_play.setToolTip("Play preview")
        self._update_play_button_style(is_playing)

    def _update_time_label(self):
        pos = _format_time(self._player.position())
        dur = _format_time(self._player.duration())
        self._lbl_time.setText(f"{pos} / {dur}")

    def _on_speed_changed(self, text: str):
        self._player.setPlaybackRate(float(text.replace("x", "")))

    def _on_volume_changed(self, value: int):
        self._audio_output.setVolume(value / 100.0)
        icon_name = "ve_vol_mute.png" if value == 0 else ("ve_vol_down.png" if value < 50 else "ve_vol_up.png")
        self._btn_vol.setIcon(QIcon(_asset(icon_name)))
        self._btn_vol.setToolTip("Unmute preview" if value == 0 else "Mute preview")

    def _toggle_mute(self):
        """Toggle playback mute — does NOT affect export mute setting."""
        muted = not self._audio_output.isMuted()
        self._audio_output.setMuted(muted)
        self._btn_vol.setIcon(QIcon(_asset("ve_vol_mute.png" if muted else "ve_vol_up.png")))
        self._btn_vol.setToolTip("Unmute preview" if muted else "Mute preview")

    def eventFilter(self, obj, event):
        fullscreen_activity = (
            obj is self._video_view
            or obj is self._video_view.viewport()
            or obj in getattr(self, '_fullscreen_activity_widgets', ())
        )
        if self.isFullScreen() and fullscreen_activity:
            if event.type() in (QEvent.Type.MouseMove, QEvent.Type.HoverMove):
                pos = event.position().toPoint() if hasattr(event, 'position') else event.pos()
                global_pos = obj.mapToGlobal(pos) if isinstance(obj, QWidget) else QCursor.pos()
                at_top = self.mapFromGlobal(global_pos).y() <= self._top_bar.height()
                if not hasattr(self, '_last_mouse_global_pos'):
                    self._last_mouse_global_pos = global_pos
                if at_top or (global_pos - self._last_mouse_global_pos).manhattanLength() > 2:
                    self._last_mouse_global_pos = global_pos
                    self._show_fullscreen_controls(reveal_top=at_top)
            elif event.type() == QEvent.Type.MouseButtonPress:
                self._fullscreen_keyboard_focus = False
                self._show_fullscreen_controls()
            elif event.type() == QEvent.Type.FocusIn:
                self._fullscreen_keyboard_focus = event.reason() in (
                    Qt.FocusReason.TabFocusReason, Qt.FocusReason.BacktabFocusReason,
                    Qt.FocusReason.ShortcutFocusReason,
                )
                self._show_fullscreen_controls(reveal_top=self._top_bar.isAncestorOf(obj))
        return super().eventFilter(obj, event)

    def _fullscreen_chrome_has_pointer(self) -> bool:
        focus = QApplication.focusWidget() if getattr(self, '_fullscreen_keyboard_focus', False) else None
        return any(
            bar.isVisible() and (bar.underMouse() or (focus is not None and bar.isAncestorOf(focus)))
            for bar in (self._top_bar, self._controls_widget)
        )

    def _show_fullscreen_controls(self, reveal_top: bool = False):
        if self.isFullScreen():
            self._controls_widget.setVisible(True)
            self._refresh_controls_geometry()
            if reveal_top:
                self._top_bar.show()
                self._top_bar.raise_()
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self._video_view.viewport().setCursor(Qt.CursorShape.ArrowCursor)
            self._fullscreen_controls_timer.start()

    def _hide_fullscreen_controls(self):
        if not self.isFullScreen():
            return
        if self._fullscreen_chrome_has_pointer():
            self._fullscreen_controls_timer.start()
            return
        self._controls_widget.hide()
        self._top_bar.hide()
        self.setCursor(Qt.CursorShape.BlankCursor)
        self._video_view.viewport().setCursor(Qt.CursorShape.BlankCursor)

    def _toggle_fullscreen(self):
        if self.isFullScreen():
            self._exit_fullscreen()
        else:
            if self._edit_mode:
                self._toast.show_message(
                    "Exit Edit mode before entering fullscreen", 2500,
                    "rgba(220, 38, 38, 0.92)"
                )
                return
            self._was_maximized = self.isMaximized()
            self.showFullScreen()
            self._set_player_topmost(True)
            # In fullscreen: no bottom margin, controls float over video
            self._main_layout.setContentsMargins(0, 0, 0, 0)
            self._btn_fullscreen.setIcon(QIcon(_asset("ve_fullscreen_exit.png")))
            self._btn_fullscreen.setText("")
            self._btn_fullscreen.setToolTip("Exit Fullscreen")
            # Make controls background more transparent in fullscreen
            self._controls_widget.setStyleSheet("""
                QWidget#GlassControls {
                    background: rgba(8, 8, 10, 0.82);
                    border-top: 1px solid rgba(255, 255, 255, 0.06);
                }
            """)
            self._show_fullscreen_controls()

    def _exit_fullscreen(self):
        if self.isFullScreen():
            self._fullscreen_controls_timer.stop()
            self._top_bar.hide()
            self._set_player_topmost(False)
            if getattr(self, '_was_maximized', False):
                self.showMaximized()
            else:
                self.showNormal()
            self._controls_widget.setVisible(True)
            if self._edit_mode:
                self._editor_panel.setVisible(True)
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self._video_view.viewport().setCursor(Qt.CursorShape.ArrowCursor)
            self._btn_fullscreen.setIcon(QIcon(_asset("ve_fullscreen.png")))
            self._btn_fullscreen.setText("")
            self._btn_fullscreen.setToolTip("Fullscreen")
            # Restore normal controls styling
            self._controls_widget.setStyleSheet("""
                QWidget#GlassControls {
                    background: rgba(12, 12, 14, 0.88);
                    border-top: 1px solid rgba(255, 255, 255, 0.08);
                }
            """)
            # Restore bottom margin
            ch = self._controls_height
            self._main_layout.setContentsMargins(0, 0, 0, ch)
            self._controls_widget.setGeometry(0, self.height() - ch, self.width(), ch)
            self._controls_widget.raise_()

    def _set_player_topmost(self, enabled: bool):
        if _user32 and self.winId():
            HWND_TOPMOST, HWND_NOTOPMOST = -1, -2
            SWP_NOMOVE, SWP_NOSIZE, SWP_NOACTIVATE = 0x0002, 0x0001, 0x0010
            try:
                _user32.SetWindowPos(int(self.winId()), HWND_TOPMOST if enabled else HWND_NOTOPMOST,
                                     0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
            except Exception:
                pass

    def _minimize_player(self):
        self._exit_fullscreen()
        self.showMinimized()

    # ── Screenshot ────────────────────────────────────────────────────────────

    def _take_screenshot(self):
        if self._ss_worker and self._ss_worker.isRunning():
            return
        current_pos = self._player.position()
        from recorder import _unique_media_path
        out_path = _unique_media_path(self._output_folder, "Frame", ".png")
        self._btn_screenshot.setEnabled(False)
        self._btn_screenshot.setText(" Capturing...")
        self._ss_worker = _ScreenshotWorker(self._filepath, current_pos, out_path)
        self._ss_worker.screenshot_finished.connect(self._on_screenshot_done)
        self._ss_worker.error.connect(self._on_screenshot_error)
        self._ss_worker.start()

    def _on_screenshot_done(self, path: str):
        self._btn_screenshot.setEnabled(True)
        self._btn_screenshot.setText(" Screenshot")
        self._toast.show_message(f"✓ Saved: {Path(path).name}", 2500, "rgba(34, 197, 94, 0.92)")
        from PyQt6.QtCore import QMimeData
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(path)])
        img = QImage(path)
        if not img.isNull():
            mime.setImageData(img)
        QApplication.clipboard().setMimeData(mime)

    def _on_screenshot_error(self, err: str):
        self._btn_screenshot.setEnabled(True)
        self._btn_screenshot.setText(" Screenshot")
        self._toast.show_message("Screenshot failed", 2500, "rgba(220, 38, 38, 0.92)")

    # ── Edit Mode ─────────────────────────────────────────────────────────────

    def _force_exit_edit_mode(self):
        """Exit edit mode silently (no discard-changes dialog). Used when
        loading a new video so we never block with a modal dialog."""
        if not self._edit_mode:
            return
        # Clear all in-memory edit state first so toggle sees no changes
        for ov in list(self._text_overlays):
            if ov._gfx_item:
                try:
                    self._video_view.gfx_scene.removeItem(ov._gfx_item)
                except Exception:
                    pass
                ov._gfx_item = None
        self._text_overlays.clear()
        self._delete_regions.clear()
        self._chk_trim.setChecked(False)
        self._mute_on_export = False
        self._audio_output.setMuted(False)
        if hasattr(self, '_toggle_audio'):
            self._toggle_audio.blockSignals(True)
            self._toggle_audio.setChecked(True)
            self._toggle_audio.blockSignals(False)
        # Now toggle — has_changes will be False so no dialog
        self._toggle_edit_mode()

    def _toggle_edit_mode(self):
        if self._edit_mode:
            has_changes = (self._chk_trim.isChecked() or self._mute_on_export
                           or len(self._text_overlays) > 0 or len(self._delete_regions) > 0)
            if has_changes:
                reply = QMessageBox.question(
                    self, "Discard Changes?",
                    "You have unsaved edits. Are you sure you want to discard them and exit edit mode?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No
                )
                if reply == QMessageBox.StandardButton.No:
                    self._btn_edit.setChecked(True)
                    return

        self._edit_mode = not self._edit_mode
        self._editor_panel.setVisible(self._edit_mode)
        self._btn_edit.setChecked(self._edit_mode)

        self._seekbar.setVisible(not self._edit_mode)
        self._timeline.setVisible(self._edit_mode)

        for w in self._playback_only_widgets:
            w.setVisible(not self._edit_mode)

        # Keep the compact transport row in Edit mode so users can preview the
        # exact timeline result before saving.  The per-widget loop above hides
        # unrelated navigation/fullscreen actions, leaving Play/Pause, the time
        # readout, and preview Mute/Unmute + volume available.
        if hasattr(self, '_btn_row_widget'):
            self._btn_row_widget.setVisible(True)
        # Reposition controls widget for the new mode (handles margins + geometry)
        self._refresh_controls_geometry()

        if self._edit_mode:
            self._player.pause()
            self._btn_edit.setText(" Editing")
            if not self._thumbnails_loaded:
                self._extract_thumbnails()
                self._thumbnails_loaded = True
                # Wire zoom-triggered dense frame fetching (once only)
                self._timeline.frames_needed.connect(self._fetch_frames_for_range)
            # Show text overlay timeline if overlays exist
            self._update_text_timeline()
        else:
            self._btn_edit.setText(" Edit")
            self._timeline.set_trim_enabled(False)
            self._timeline.reset()
            self._chk_trim.setChecked(False)
            self._chk_trim.setText("Trim")
            # Clear all text overlays: scene items + sidebar rows + data list
            for ov in list(self._text_overlays):
                if ov._gfx_item:
                    self._video_view.gfx_scene.removeItem(ov._gfx_item)
                    ov._gfx_item = None
            # Remove all sidebar rows
            while self._text_overlays_container.count():
                item = self._text_overlays_container.takeAt(0)
                if item and item.widget():
                    item.widget().deleteLater()
            self._text_overlays.clear()
            self._timeline.set_text_overlays([])
            while self._delete_regions_container.count():
                item = self._delete_regions_container.takeAt(0)
                if item and item.widget():
                    item.widget().deleteLater()
            self._delete_regions.clear()
            self._timeline.set_delete_regions([])
            self._mute_on_export = False
            self._audio_output.setMuted(False)
            if hasattr(self, '_toggle_audio'):
                self._toggle_audio.setChecked(True)


    # ── Edit Panel Actions ────────────────────────────────────────────────────

    def _on_trim_toggled(self):
        enabled = self._chk_trim.isChecked()
        self._timeline.set_trim_enabled(enabled)
        if enabled:
            start_ms, end_ms = self._timeline.get_trim()
            self._chk_trim.setText(f"Trim  ·  {_format_time(start_ms)} → {_format_time(end_ms)}")
        else:
            self._chk_trim.setText("Trim")

    def _add_delete_region(self):
        new_start, new_end = _delete_region_at_playhead(
            self._player.position(), self._player.duration()
        )
        
        if self._chk_trim.isChecked():
            ts, te = self._timeline.get_trim()
            if new_start >= te or new_end <= ts:
                self._toast.show_message("Cannot add: Cut area outside trim bounds!", 2500, "#EF4444")
                return
            new_start = max(new_start, ts)
            new_end = min(new_end, te)
            if new_end - new_start < 500:
                self._toast.show_message("Cannot add: Not enough space to insert cut", 2500, "#EF4444")
                return

        # Check overlaps
        for reg in self._delete_regions:
            if max(new_start, reg.start_ms) < min(new_end, reg.end_ms):
                self._toast.show_message("Cannot add region: Overlaps existing", 2500, "#EF4444")
                return

        item = _DeleteRegionItem(new_start, new_end)
        self._delete_regions.append(item)
        row = _DeleteRegionRow(item, self._player.duration())
        self._delete_regions_container.addWidget(row)
        
        row.changed.connect(lambda: self._timeline.set_delete_regions(self._delete_regions))
        row.removed.connect(self._remove_delete_region)
        self._timeline.set_delete_regions(self._delete_regions)

    def _remove_delete_region(self, row_widget):
        if row_widget.item in self._delete_regions:
            self._delete_regions.remove(row_widget.item)
        row_widget.deleteLater()
        self._timeline.set_delete_regions(self._delete_regions)

    def _on_mute_export_toggled(self, checked=None):
        if checked is None:
            checked = self._toggle_audio.isChecked()
        self._mute_on_export = not checked  # Checked = On = audio enabled
        # Also mute/unmute playback preview to reflect the setting immediately
        self._audio_output.setMuted(self._mute_on_export)
        icon_name = "ve_vol_mute.png" if self._mute_on_export else "ve_vol_up.png"
        self._btn_vol.setIcon(QIcon(_asset(icon_name)))
        self._btn_vol.setToolTip("Unmute preview" if self._mute_on_export else "Mute preview")




    # ── Text Overlays ─────────────────────────────────────────────────────────

    def _add_text_overlay(self):
        item = _TextOverlayItem()
        item.start_ms, item.end_ms = _text_overlay_range_at_playhead(
            self._player.position(), self._player.duration()
        )
        self._text_overlays.append(item)

        # Config row in editor panel
        row = _TextOverlayRow(item, self._player.duration())
        self._text_overlays_container.addWidget(row)

        # Draggable text in the video scene
        gfx_item = DraggableTextItem(item, self._video_view.video_item)
        self._video_view.gfx_scene.addItem(gfx_item)
        item._gfx_item = gfx_item

        # Wire X button on scene item to remove via row signal
        gfx_item.set_delete_callback(lambda r=row: self._remove_text_overlay(r))

        # Wire inline edit/resize sync: scene → sidebar
        def _sync_scene_to_sidebar(r=row):
            r._edt_text.blockSignals(True)
            r._edt_text.setPlainText(r.item.text)
            r._edt_text.blockSignals(False)
            r._spn_size.blockSignals(True)
            r._spn_size.setValue(r.item.font_size)
            r._spn_size.blockSignals(False)
            self._update_text_timeline()
        gfx_item.set_change_callback(_sync_scene_to_sidebar)
        
        gfx_item.set_select_callback(lambda it=item: self._select_text_overlay(self._text_overlays.index(it) if it in self._text_overlays else -1))

        row.changed.connect(gfx_item.update_style)
        row.changed.connect(self._update_text_timeline)
        row.removed.connect(self._remove_text_overlay)
        row.selected.connect(lambda r=row: self._select_text_overlay(self._text_overlays.index(r.item) if r.item in self._text_overlays else -1))

        # Update text overlay timeline
        self._update_text_timeline()
        self._select_text_overlay(len(self._text_overlays) - 1)

    def _on_text_timeline_drag(self, idx: int, handle: str, ms: int):
        if idx < 0 or idx >= len(self._text_overlays):
            return
        row_widget = self._text_overlays_container.itemAt(idx).widget()
        if isinstance(row_widget, _TextOverlayRow):
            if handle == 'start':
                ms = min(ms, row_widget.item.end_ms)
                row_widget.set_start_time(ms)
            elif handle == 'end':
                ms = max(ms, row_widget.item.start_ms)
                row_widget.set_end_time(ms)

    def _remove_text_overlay(self, row_widget):
        if hasattr(row_widget, 'item') and row_widget.item in self._text_overlays:
            self._text_overlays.remove(row_widget.item)
            if row_widget.item._gfx_item:
                self._video_view.gfx_scene.removeItem(row_widget.item._gfx_item)
                row_widget.item._gfx_item = None
        self._text_overlays_container.removeWidget(row_widget)
        row_widget.deleteLater()
        self._update_text_timeline()
        self._select_text_overlay(-1)

    def _select_text_overlay(self, idx: int):
        self._selected_overlay_idx = idx
        
        # Update Timeline
        self._timeline.set_selected_overlay(idx)
        
        # Update Sidebar Rows
        for i in range(self._text_overlays_container.count()):
            w = self._text_overlays_container.itemAt(i).widget()
            if isinstance(w, _TextOverlayRow):
                w.set_selected(i == idx)
                
        # Update Video Scene Items
        for i, ov in enumerate(self._text_overlays):
            if ov._gfx_item:
                ov._gfx_item.set_selected(i == idx)

    def _update_text_timeline(self):
        """Refresh text overlay lanes in the unified FrameTimelineWidget."""
        self._timeline.set_text_overlays(self._text_overlays if self._edit_mode else [])
        # Timeline height may have changed (more/fewer lanes) — reposition the
        # floating controls widget so it actually fits the new height.
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(0, self._refresh_controls_geometry)

    # ── Save/Export ───────────────────────────────────────────────────────────

    def _save_overwrite(self):
        import time
        ext = Path(self._filepath).suffix
        temp_out = self._filepath + f"_{int(time.time())}.tmp{ext}"
        self._save_edited(temp_out, is_overwrite=True)

    def _save_as(self):
        from PyQt6.QtWidgets import QInputDialog
        base_name = Path(self._filepath).stem
        ext = Path(self._filepath).suffix
        new_name, ok = QInputDialog.getText(
            self, "Save As", "Enter new file name (saves in same folder):",
            text=base_name
        )
        if ok and new_name.strip():
            new_name = new_name.strip()
            if "." not in new_name:
                new_name += ext
            out_path = os.path.join(self._output_folder, new_name)
            if out_path.lower() == self._filepath.lower():
                self._save_overwrite()
                return
            out_path = _available_output_path(out_path)
            self._save_edited(out_path, is_overwrite=False)

    def _save_edited(self, out_path: str, is_overwrite: bool = False):
        self._is_exporting_overwrite = is_overwrite
        self._export_target_path = self._filepath if is_overwrite else out_path
        if is_overwrite:
            staging_path = out_path
        else:
            target = Path(out_path)
            fd, staging_path = tempfile.mkstemp(
                prefix=f".{target.stem}_", suffix=f".partial{target.suffix}", dir=str(target.parent)
            )
            os.close(fd)
            os.remove(staging_path)
        ffmpeg = _get_ffmpeg()
        
        self._export_temp_files = getattr(self, '_export_temp_files', [])

        cmd = [ffmpeg, "-y"]

        trim_start_ms = 0
        trim_end_ms = self._player.duration()
        if self._chk_trim.isChecked():
            trim_start_ms, trim_end_ms = self._timeline.get_trim()
            cmd.extend(["-ss", _format_time_precise(trim_start_ms)])
            cmd.extend(["-to", _format_time_precise(trim_end_ms)])

        cmd.extend(["-i", self._filepath])
        cmd.extend(["-vsync", "1"])

        vfilters = []
        native_size = self._video_view.video_item.nativeSize()
        preview_height = float(native_size.height() or self._video_view.video_item.boundingRect().height() or 1080.0)

        # FIX 001: Append text overlay filters BEFORE delete segments
        for overlay in self._text_overlays:
            if not overlay.text.strip():
                continue
            t_start = max(0, (overlay.start_ms - trim_start_ms) / 1000.0)
            t_end = max(0, (overlay.end_ms - trim_start_ms) / 1000.0)
            
            # Write text to a temporary file to avoid ffmpeg escaping hell
            tf_fd, tf_path = tempfile.mkstemp(suffix='.txt', text=True)
            with os.fdopen(tf_fd, 'w', encoding='utf-8') as f:
                f.write(overlay.text)
            self._export_temp_files.append(tf_path)
            
            ff_path = _ffmpeg_filter_path(tf_path)
            
            vfilters.append(_drawtext_filter(overlay, ff_path, t_start, t_end, preview_height))

        merged_cuts = _merge_delete_regions(self._delete_regions, trim_start_ms)
        if merged_cuts:
            filters = [f"not(between(t\\,{ds:.3f}\\,{de:.3f}))" for ds, de in merged_cuts]
            if filters:
                vfilters.append(f"select='{'*'.join(filters)}',setpts=N/FRAME_RATE/TB")

        if vfilters:
            cmd.extend(["-vf", ",".join(vfilters)])

        if self._mute_on_export:
            cmd.append("-an")
        elif merged_cuts:
            filters = [f"not(between(t\\,{ds:.3f}\\,{de:.3f}))" for ds, de in merged_cuts]
            if filters:
                cmd.extend(["-af", f"aselect='{'*'.join(filters)}',asetpts=N/SR/TB,aresample=async=1"])

        if not self._mute_on_export:
            cmd.extend(["-c:a", "aac", "-b:a", "128k"])

        cmd.extend(["-c:v", "libx264", "-preset", "fast", "-crf", "23", "-pix_fmt", "yuv420p"])
        cmd.append(staging_path)

        self._btn_save.setEnabled(False)
        self._btn_save_as.setEnabled(False)
        self._btn_save.setText("⏳ Exporting...")
        self._progress_bar.setVisible(True)

        duration_ms = self._player.duration()
        self._export_worker = _ExportWorker(
            cmd, staging_path, temp_files=list(self._export_temp_files), duration_ms=duration_ms
        )
        self._export_worker.progress.connect(self._on_export_progress)
        self._export_worker.export_finished.connect(self._on_export_done)
        self._export_worker.error.connect(self._on_export_error)
        self._export_worker.start()

        self._saving_overlay.set_progress(0)
        self._saving_overlay.resize(self.size())
        self._saving_overlay.show()
        self._saving_overlay.raise_()

    def _on_export_progress(self, pct: int):
        self._saving_overlay.set_progress(pct)

    def _on_export_done(self, path: str):
        self._cleanup_temp_files()
        is_overwrite = getattr(self, '_is_exporting_overwrite', False)
        target_path = getattr(self, '_export_target_path', self._filepath if is_overwrite else path)
        if is_overwrite:
            self._player.setSource(QUrl())
            QTimer.singleShot(150, lambda: self._replace_and_reload(path, target_path, is_overwrite))
        else:
            self._replace_and_reload(path, target_path, is_overwrite)

    def _replace_and_reload(self, temp_path: str, target_path: str, did_overwrite: bool, attempt=1):
        try:
            os.replace(temp_path, target_path)
        except PermissionError as e:
            if attempt <= 5:
                QTimer.singleShot(
                    250, lambda: self._replace_and_reload(temp_path, target_path, did_overwrite, attempt + 1)
                )
                return
            self._on_export_error(f"Save failed (file locked): {e}")
            return
        except Exception as e:
            self._on_export_error(f"Save failed: {e}")
            return

        self._saving_overlay.hide()
        self._progress_bar.setVisible(False)
        self._btn_save.setEnabled(True)
        self._btn_save_as.setEnabled(True)
        self._btn_save.setText("Save")

        msg = f"✓ Overwritten: {Path(target_path).name}" if did_overwrite else f"✓ Saved: {Path(target_path).name}"
        self._toast.show_message(msg, 3000, "rgba(34, 197, 94, 0.92)")
        self._load_video(target_path, discard_edits=True)

    def _on_export_error(self, err: str):
        self._cleanup_temp_files()
        worker = getattr(self, '_export_worker', None)
        staging = getattr(worker, '_output_path', '') if worker else ''
        if staging and staging != getattr(self, '_export_target_path', ''):
            try:
                if os.path.isfile(staging):
                    os.remove(staging)
            except Exception:
                pass
        self._saving_overlay.hide()
        self._progress_bar.setVisible(False)
        self._btn_save.setEnabled(True)
        self._btn_save_as.setEnabled(True)
        self._btn_save.setText("Save")
        from user_messages import friendly_error
        self._toast.show_message(friendly_error(err), 5000, "rgba(220, 38, 38, 0.92)")
        print(f"[VideoEditor] Export error:\n{err}")

    def _cleanup_temp_files(self):
        if hasattr(self, '_export_temp_files'):
            for p in self._export_temp_files:
                try:
                    if os.path.exists(p):
                        os.remove(p)
                except Exception as e:
                    print(f"Failed to clean up temp file {p}: {e}")
            self._export_temp_files.clear()

    # ── Resize ────────────────────────────────────────────────────────────────

    def _refresh_controls_geometry(self):
        """Reposition the floating controls widget to fit its current sizeHint.
        Called from both resizeEvent and after timeline height changes."""
        if not hasattr(self, '_controls_widget'):
            return
        ctrl = self._controls_widget
        ctrl.adjustSize()
        ch = ctrl.sizeHint().height()
        self._controls_height = ch
        w = self.width()
        self._top_bar.setGeometry(0, 0, w, self._top_bar.height())
        edit_mode = getattr(self, '_edit_mode', False)
        if edit_mode:
            # In edit mode the controls widget holds the timeline — position it
            # at the bottom so the timeline rows are fully visible, and reserve
            # the matching bottom margin so the video area doesn't overlap it.
            ctrl.setGeometry(0, self.height() - ch, w, ch)
            self._main_layout.setContentsMargins(0, 0, 0, ch)
        elif self.isFullScreen():
            self._main_layout.setContentsMargins(0, 0, 0, 0)
            # Keep the absolute bottom pixel away from the Windows auto-hide
            # taskbar activation strip while leaving controls visually flush.
            ctrl.setGeometry(0, self.height() - ch - 2, w, ch)
            ctrl.raise_()
        else:
            self._main_layout.setContentsMargins(0, 0, 0, ch)
            ctrl.setGeometry(0, self.height() - ch, w, ch)
            ctrl.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh_controls_geometry()
        if hasattr(self, '_toast') and self._toast.isVisible():
            self._toast.move((self.width() - self._toast.width()) // 2, 60)
        if hasattr(self, '_loading_overlay') and self._loading_overlay.isVisible():
            self._loading_overlay.resize(self.size())
        if hasattr(self, '_saving_overlay') and self._saving_overlay.isVisible():
            self._saving_overlay.resize(self.size())

    def showEvent(self, event):
        super().showEvent(event)
        # NOTE: Do NOT call _exclude_from_capture here.
        # The video player window must remain visible for screenshots.


    # ── Folder Navigation ─────────────────────────────────────────────────────

    def _refresh_video_list(self):
        self._video_files = []
        if os.path.isdir(self._output_folder):
            import glob
            files = []
            for ext in ('*.mkv', '*.mp4', '*.webm', '*.avi'):
                files.extend(glob.glob(os.path.join(self._output_folder, ext)))
            files.sort(key=os.path.getmtime, reverse=True)
            self._video_files = [os.path.normpath(p) for p in files]

        target_path = os.path.normpath(self._filepath)
        try:
            self._current_video_index = self._video_files.index(target_path)
        except ValueError:
            self._video_files.insert(0, target_path)
            self._current_video_index = 0

        self._update_nav_buttons()

    def _update_nav_buttons(self):
        self._btn_prev.setEnabled(self._current_video_index > 0)
        self._btn_next.setEnabled(self._current_video_index < len(self._video_files) - 1)

    def _play_prev_video(self):
        if self._current_video_index > 0:
            self._load_video(self._video_files[self._current_video_index - 1])

    def _play_next_video(self):
        if self._current_video_index < len(self._video_files) - 1:
            self._load_video(self._video_files[self._current_video_index + 1])

    def _has_unsaved_edits(self) -> bool:
        return bool(
            self._edit_mode and (
                self._chk_trim.isChecked() or self._mute_on_export
                or self._text_overlays or self._delete_regions
            )
        )

    def _confirm_video_switch(self, filepath: str) -> bool:
        if os.path.normcase(os.path.abspath(filepath)) == os.path.normcase(os.path.abspath(self._filepath)):
            return True
        if not self._has_unsaved_edits():
            return True
        reply = QMessageBox.question(
            self, "Discard Unsaved Edits?",
            "Opening another video will discard the unsaved edits on this video. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return reply == QMessageBox.StandardButton.Yes

    def _load_video(self, filepath: str, discard_edits: bool = False):
        try:
            if not discard_edits and not self._confirm_video_switch(filepath):
                return False
            self._filepath = filepath

            # Stop the player and release file lock BEFORE doing anything else
            self._player.setSource(QUrl())

            # Force-exit edit mode silently (no dialog) — clears all in-memory
            # edit state and resets the UI without showing any modal.
            self._force_exit_edit_mode()

            # Now set the new source
            self._btn_play.setEnabled(True)
            self._timeline.setEnabled(True)
            self._player.setSource(QUrl.fromLocalFile(filepath))
            self._player.pause()
            self.setWindowTitle(f"WWR: Player — {Path(filepath).name}")
            self._refresh_video_list()

            # Clear any remaining data lists (force_exit_edit_mode clears
            # text_overlays and delete_regions but we do it again to be safe)
            self._text_overlays.clear()
            self._delete_regions.clear()

            # Clear overlay UI rows
            while self._text_overlays_container.count():
                item = self._text_overlays_container.takeAt(0)
                w = item.widget() if item else None
                if w:
                    w.deleteLater()

            # Clear delete region UI rows
            while self._delete_regions_container.count():
                item = self._delete_regions_container.takeAt(0)
                w = item.widget() if item else None
                if w:
                    w.deleteLater()

            # Clear scene text items (leave video item untouched)
            for scene_item in list(self._video_view.gfx_scene.items()):
                if isinstance(scene_item, DraggableTextItem):
                    try:
                        self._video_view.gfx_scene.removeItem(scene_item)
                    except Exception:
                        pass

            # Reset thumbnail state
            self._thumbnails_loaded = False
            self._timeline.set_thumbnails([])
            self._timeline.set_delete_regions([])
            self._timeline.set_trim_enabled(False)
            return True
        except Exception as e:
            print(f"[VideoEditor] _load_video error: {e}")
            return False

    def restore_source_after_rename(self, filepath: str):
        """Rebind a renamed file without destroying unsaved edit state."""
        self._filepath = filepath
        self._player.setSource(QUrl.fromLocalFile(filepath))
        self._player.pause()
        self._btn_play.setEnabled(True)
        self._timeline.setEnabled(True)
        self.setWindowTitle(f"WWR: Player — {Path(filepath).name}")
        self._refresh_video_list()
