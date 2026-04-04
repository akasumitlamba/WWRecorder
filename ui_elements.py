"""
ui_elements.py - WWRecorder UI Components

• SelectionOverlay  : Full-screen translucent region picker
• PillWidget        : Floating always-on-top recording controller
                      (invisible to capture via SetWindowDisplayAffinity)
• SettingsWindow    : Settings dialog
"""

import ctypes
import os
import sys
from typing import Optional

from PyQt6.QtWidgets import (
    QApplication, QDialog, QWidget, QLabel, QPushButton, QToolButton,
    QHBoxLayout, QVBoxLayout, QFileDialog, QLineEdit,
    QCheckBox, QGroupBox, QGraphicsDropShadowEffect,
    QSizePolicy, QToolTip,
)
from PyQt6.QtCore import (
    Qt, QRect, QPoint, QSize, QTimer, QThread,
    pyqtSignal, QPropertyAnimation, QEasingCurve,
)
from PyQt6.QtGui import (
    QPainter, QColor, QBrush, QPen, QFont, QFontMetrics,
    QPainterPath, QLinearGradient, QIcon, QCursor,
    QPixmap, QImage, QRegion,
)

# ── Windows API constants ──────────────────────────────────────────────────────
WDA_EXCLUDEFROMCAPTURE = 0x00000011   # Invisible to all capture APIs
WDA_MONITOR = 0x00000001              # Fallback for older Windows 10 versions

_user32 = ctypes.windll.user32 if sys.platform == "win32" else None
if _user32:
    from ctypes import wintypes
    _user32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
    _user32.SetWindowDisplayAffinity.restype = wintypes.BOOL

def _exclude_from_capture(hwnd: int) -> None:
    """Mark this HWND so it is invisible to all screen-capture APIs."""
    if _user32:
        try:
            # Try WDA_EXCLUDEFROMCAPTURE first (Windows 10 2004+)
            res = _user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE)
            if not res:
                # Fallback to WDA_MONITOR
                _user32.SetWindowDisplayAffinity(hwnd, WDA_MONITOR)
        except Exception as exc:
            pass



# ─────────────────────────────────────────────────────────────────────────────
#  SelectionOverlay
# ─────────────────────────────────────────────────────────────────────────────

class SelectionOverlay(QWidget):
    selectionChanged = pyqtSignal(dict)
    
    def __init__(self, mode="record"):
        flags = (
            Qt.WindowType.Window
            | Qt.WindowType.FramelessWindowHint 
            | Qt.WindowType.WindowStaysOnTopHint
        )
        super().__init__(None, flags)

        self._mode = mode
        self.state = 'IDLE'
        self._origin = None
        self._current = None
        self.rect_obj = QRect()
        self._bg_pixmap = None
        
        if self._mode == "screenshot":
            self.hint_text = "  ⊞  Click and drag to select screenshot area  -  Esc to cancel  "
            self.selection_color = QColor(255, 59, 48)  # Red
        else:
            self.hint_text = "  ⊞  Click and drag to select recording area  -  Esc to cancel  "
            self.selection_color = QColor(10, 132, 255)  # Blue

        self.handle_size = 5
        self.hovered_handle = None

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFocus()
        
        # Determine logical desktop bounds
        bounds = QRect()
        for screen in QApplication.screens():
            bounds = bounds.united(screen.geometry())
        self.setGeometry(bounds)

        self._hint = QLabel(self.hint_text, self)
        self._hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hint.setStyleSheet("""
            QLabel {
                color: #FFFFFF;
                background: rgba(0,0,0,175);
                border-radius: 10px;
                font-family: 'Segoe UI', sans-serif;
                font-size: 13px;
                font-weight: 500;
                padding: 8px 20px;
            }
        """)
        self._hint.adjustSize()
        self._hint.move(bounds.width() // 2 - self._hint.width() // 2, 28)

    def set_background(self, pixmap: QPixmap):
        """Set a static background image (frozen screenshot)."""
        self._bg_pixmap = pixmap
        self.update()

    def showEvent(self, event):
        super().showEvent(event)
        # We use a small delay to ensure the window is mapped and ready before 
        # we shout at Windows to give us the focus. This is more robust than 
        # doing it immediately.
        QTimer.singleShot(100, self._force_focus)

    def _force_focus(self):
        """Low-level Windows API call plus Qt activation to reliably steal focus."""
        if sys.platform == "win32":
            try:
                import ctypes
                user32 = ctypes.windll.user32
                kernel32 = ctypes.windll.kernel32

                hwnd = int(self.winId())
                target_hwnd = user32.GetForegroundWindow()
                target_thread = user32.GetWindowThreadProcessId(target_hwnd, None)
                my_thread = kernel32.GetCurrentThreadId()

                if target_thread != my_thread and target_thread != 0:
                    user32.AttachThreadInput(my_thread, target_thread, True)
                    user32.BringWindowToTop(hwnd)
                    user32.ShowWindow(hwnd, 5) # SW_SHOW
                    user32.SetForegroundWindow(hwnd)
                    user32.SetFocus(hwnd)
                    user32.AttachThreadInput(my_thread, target_thread, False)
                else:
                    user32.BringWindowToTop(hwnd)
                    user32.ShowWindow(hwnd, 5)
                    user32.SetForegroundWindow(hwnd)
                    user32.SetFocus(hwnd)
            except Exception as e:
                print(f"Focus error: {e}")
        
        self.activateWindow()
        self.raise_()
        self.setFocus()
        self.grabKeyboard()

    def hideEvent(self, event):
        super().hideEvent(event)
        self.releaseKeyboard()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.selectionChanged.emit({})
            self.close()

    def get_handles(self):
        if not self.rect_obj.isValid(): return {}
        hs = self.handle_size
        r = self.rect_obj
        return {
            'tl': QRect(r.left() - hs, r.top() - hs, hs*2, hs*2),
            't': QRect(r.center().x() - hs, r.top() - hs, hs*2, hs*2),
            'tr': QRect(r.right() - hs, r.top() - hs, hs*2, hs*2),
            'r': QRect(r.right() - hs, r.center().y() - hs, hs*2, hs*2),
            'br': QRect(r.right() - hs, r.bottom() - hs, hs*2, hs*2),
            'b': QRect(r.center().x() - hs, r.bottom() - hs, hs*2, hs*2),
            'bl': QRect(r.left() - hs, r.bottom() - hs, hs*2, hs*2),
            'l': QRect(r.left() - hs, r.center().y() - hs, hs*2, hs*2)
        }

    def mousePressEvent(self, event):
        self.setFocus()
        pos = event.position().toPoint()
        if event.button() == Qt.MouseButton.LeftButton:
            if self.state == 'IDLE':
                self.state = 'DRAWING'
                self._origin = pos
                self._current = pos
                self._hint.hide()
            elif self.state == 'SELECTED':
                handles = self.get_handles()
                for h, hr in handles.items():
                    if hr.contains(pos):
                        self.state = 'RESIZING'
                        self.hovered_handle = h
                        self._origin = pos
                        return
                if self.rect_obj.contains(pos):
                    self.state = 'MOVING'
                    self._origin = pos
                else:
                    self.state = 'DRAWING'
                    self._origin = pos
                    self._current = pos
                    self.rect_obj = QRect()
            self.update()

    def mouseMoveEvent(self, event):
        pos = event.position().toPoint()
        if self.state == 'DRAWING':
            self._current = pos
            self.rect_obj = QRect(self._origin, self._current).normalized()
            self.update()
        elif self.state == 'MOVING':
            dp = pos - self._origin
            self.rect_obj.translate(dp)
            self._origin = pos
            self.update()
        elif self.state == 'RESIZING':
            dp = pos - self._origin
            r = self.rect_obj
            h = self.hovered_handle
            if 't' in h: r.setTop(r.top() + dp.y())
            if 'b' in h: r.setBottom(r.bottom() + dp.y())
            if 'l' in h: r.setLeft(r.left() + dp.x())
            if 'r' in h: r.setRight(r.right() + dp.x())
            self.rect_obj = r.normalized()
            self._origin = pos
            self.update()
        elif self.state == 'SELECTED':
            handles = self.get_handles()
            h_found = None
            for h, hr in handles.items():
                if hr.contains(pos):
                    h_found = h
                    break
            if h_found in ['tl', 'br']: self.setCursor(Qt.CursorShape.SizeFDiagCursor)
            elif h_found in ['tr', 'bl']: self.setCursor(Qt.CursorShape.SizeBDiagCursor)
            elif h_found in ['t', 'b']: self.setCursor(Qt.CursorShape.SizeVerCursor)
            elif h_found in ['l', 'r']: self.setCursor(Qt.CursorShape.SizeHorCursor)
            elif self.rect_obj.contains(pos): self.setCursor(Qt.CursorShape.SizeAllCursor)
            else: self.setCursor(Qt.CursorShape.CrossCursor)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self.state == 'DRAWING':
                if self.rect_obj.width() >= 32 and self.rect_obj.height() >= 32:
                    self.state = 'SELECTED'
                    self._emit_change()
                else:
                    self.state = 'IDLE'
                    self.rect_obj = QRect()
                    self._hint.show()
                self.setCursor(Qt.CursorShape.CrossCursor)
            elif self.state in ['MOVING', 'RESIZING']:
                self.state = 'SELECTED'
                self._emit_change()
            self.update()

    def _emit_change(self):
        region = {
            "top": self.rect_obj.top(),
            "left": self.rect_obj.left(),
            "width": self.rect_obj.width(),
            "height": self.rect_obj.height()
        }
        self.selectionChanged.emit(region)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 1. Draw the static frozen background if we have one
        if self._bg_pixmap:
            p.drawPixmap(self.rect(), self._bg_pixmap)
        else:
            # Fallback if no frozen background: just clear background
            p.fillRect(self.rect(), Qt.GlobalColor.transparent)

        # 2. Dim the area OUTSIDE the selection
        # We use QRegion to exclude the selection from the dimming fill
        dim_color = QColor(0, 0, 0, 110)
        if self.rect_obj.isValid():
            full_region = QRegion(self.rect())
            sel_region = QRegion(self.rect_obj)
            dim_region = full_region.subtracted(sel_region)
            
            p.setClipRegion(dim_region)
            p.fillRect(self.rect(), dim_color)
            p.setClipping(False)
            
            # 3. Draw selection border and handles
            sel = self.rect_obj
            pen = QPen(self.selection_color, 1.5, Qt.PenStyle.DashLine)
            pen.setDashPattern([8, 4])
            p.setPen(pen)
            p.drawRect(sel)

            handles = self.get_handles()
            for hr in handles.values():
                p.fillRect(hr, self.selection_color)

            # 4. Draw dimensions label
            dim = f"{sel.width()} × {sel.height()}"
            p.setFont(QFont("Segoe UI", 10, QFont.Weight.Medium))
            fm = QFontMetrics(p.font())
            lw = fm.horizontalAdvance(dim) + 12
            lh = fm.height() + 6
            lx = sel.left() + 4
            ly = sel.top() - lh - 4 if sel.top() > lh + 8 else sel.top() + lh + 4

            bg_rect = QRect(lx - 2, ly - lh + 2, lw, lh)
            bg_color = QColor(self.selection_color)
            bg_color.setAlpha(200)
            p.fillRect(bg_rect, bg_color)
            p.setPen(QColor(255, 255, 255))
            p.drawText(bg_rect, Qt.AlignmentFlag.AlignCenter, dim)
        else:
            # If no selection, dim the whole thing
            p.fillRect(self.rect(), dim_color)

        p.end()


# ─────────────────────────────────────────────────────────────────────────────
#  CaptureBorderWidget
# ─────────────────────────────────────────────────────────────────────────────

class CaptureBorderWidget(QWidget):
    """
    A thin, transparent window that overlays the selected region to show
    a visible red outline during recording. It is excluded from capture
    and transparent to mouse clicks.
    """

    def __init__(self, region: dict):
        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowTransparentForInput
        )
        super().__init__(None, flags)

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        # Enforce exclusion initially
        _exclude_from_capture(int(self.winId()))

        # Use EXACT selection coordinates so border is visible at screen edges
        self.setGeometry(
            region["left"],
            region["top"],
            region["width"],
            region["height"],
        )

        # Enforce topmost to stay above Windows Taskbar
        self._top_timer = QTimer(self)
        self._top_timer.timeout.connect(self._enforce_topmost)
        self._top_timer.start(500)

    def showEvent(self, event):
        super().showEvent(event)
        _exclude_from_capture(int(self.winId()))

    def _enforce_topmost(self):
        if self.isVisible() and _user32:
            HWND_TOPMOST = -1
            SWP_NOSIZE = 0x0001
            SWP_NOMOVE = 0x0002
            SWP_NOACTIVATE = 0x0010
            _user32.SetWindowPos(int(self.winId()), HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
            _exclude_from_capture(int(self.winId()))
        self.raise_()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Draw a thicker dashed red border to indicate recording area
        pen = QPen(QColor(255, 59, 48, 220), 2.5, Qt.PenStyle.DashLine)
        pen.setDashPattern([6, 3]) 
        p.setPen(pen)
        
        # Border sits precisely on the inner boundary
        # Since the widget is exactly the region size, drawing at adjusted(1,1,-1,-1)
        # keeps the line VISIBLE and centered.
        rect_border = self.rect().adjusted(1, 1, -1, -1)
        p.drawRect(rect_border)
        
        p.end()


# ─────────────────────────────────────────────────────────────────────────────
#  _PillToolButton  (internal)
# ─────────────────────────────────────────────────────────────────────────────

def _asset(filename: str) -> str:
    import os, sys
    base_dir = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_dir, 'icons', filename)

class _PillToolButton(QToolButton):
    """Icon only button used inside the Pill widget."""

    def __init__(self, icon_filename: str, text: str, checkable: bool = False, icon_off_filename: str = None):
        super().__init__()
        self.setCheckable(checkable)
        
        # NOTE: Tooltip only, no text label
        self.setToolTip(text)
        
        self.setIconSize(QSize(20, 20))
        self.setFixedSize(36, 36) # True square
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_AlwaysShowToolTips)
        
        self.icon_path_on = _asset(icon_filename)
        self.icon_path_off = _asset(icon_off_filename) if icon_off_filename else self.icon_path_on
        
        self._is_danger = False
        self._update_icon()
        self._update_style()
        self.toggled.connect(self._on_toggled)

        self._tip_timer = QTimer(self)
        self._tip_timer.setSingleShot(True)
        self._tip_timer.setInterval(400) 
        self._tip_timer.timeout.connect(self._show_tip)
        self.setMouseTracking(True)

    def set_danger(self, enabled: bool):
        """Toggle between standard and 'danger' red styling."""
        self._is_danger = enabled
        self._update_style()

    def _show_tip(self):
        if self.underMouse() and self.toolTip():
            QToolTip.showText(QCursor.pos(), self.toolTip(), self)

    def enterEvent(self, e):
        self._tip_timer.start()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._tip_timer.stop()
        QToolTip.hideText()
        super().leaveEvent(e)
        
    def _on_toggled(self):
        self._update_icon()
        self._update_style()

    def _update_icon(self):
        path = self.icon_path_on if (not self.isCheckable() or self.isChecked()) else self.icon_path_off
        if os.path.isfile(path):
            self.setIcon(QIcon(path))

    def _update_style(self):
        # Unified Red Shade: background #2A1F22, border #4A2B2E
        if self._is_danger or (self.isCheckable() and not self.isChecked()):
            bg = "#2A1F22"
            border = "#4A2B2E"
            hover = "#3A2326"
        else:
            bg = "#252528"
            border = "#333336"
            hover = "#333336"

        base_style = f"""
            QToolButton {{
                background: {bg};
                border: 1px solid {border};
                border-radius: 6px;
                padding: 0px;
            }}
            QToolButton:hover {{ background: {hover}; }}
            QToolButton:pressed {{ background: #1C1C1E; }}
        """
        checked_style = """
            QToolButton:checked {
                background: rgba(255, 255, 255, 0.12);
                color: #FFFFFF;
                border: 1px solid rgba(255, 255, 255, 0.25);
            }
        """
        self.setStyleSheet(base_style + (checked_style if self.isCheckable() else ""))

    def update_text(self, text: str):
        self.setToolTip(text)


# ─────────────────────────────────────────────────────────────────────────────
#  PillWidget
# ─────────────────────────────────────────────────────────────────────────────

class _StopWorker(QThread):
    finished = pyqtSignal(str)
    def __init__(self, engine):
        super().__init__()
        self._engine = engine
    def run(self):
        # Phase 1: stop capture threads + close FFmpeg pipe (fast)
        self._engine.stop_capture()
        # Phase 2: mux audio+video into final file (slow)
        path = self._engine.mux_and_save()
        self.finished.emit(path)

class PillWidget(QWidget):
    stopped            = pyqtSignal(str)
    save_completed     = pyqtSignal(str)   # Emitted when background muxing finishes
    settings_requested = pyqtSignal()
    start_requested    = pyqtSignal()

    _BG_DARK    = QColor(28, 28, 30, 245)
    _BORDER_CLR = QColor(255, 255, 255, 20)

    def __init__(self, engine, config: dict, pre_record: bool = False):
        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        super().__init__(None, flags)
        self._engine  = engine
        self._config  = config
        self._pre_record = pre_record
        self._drag_pos: Optional[QPoint] = None
        self._elapsed = 0
        self._stop_worker: Optional[_StopWorker] = None

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_AlwaysShowToolTips)
        self.setMouseTracking(True)

        self._build_ui()
        self._setup_timers()
        self._position_on_screen()

        self._topmost_timer = QTimer(self)
        self._topmost_timer.timeout.connect(self._enforce_topmost)
        self._topmost_timer.start(2000)

        QTimer.singleShot(150, self._apply_exclusion)

    def showEvent(self, event):
        super().showEvent(event)
        _exclude_from_capture(int(self.winId()))

    def _enforce_topmost(self):
        if self.isVisible() and not self.underMouse():
            if _user32:
                HWND_TOPMOST = -1
                SWP_NOSIZE = 0x0001
                SWP_NOMOVE = 0x0002
                SWP_NOACTIVATE = 0x0010
                _user32.SetWindowPos(int(self.winId()), HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
                _exclude_from_capture(int(self.winId()))
            self.raise_()

    def _apply_exclusion(self):
        _exclude_from_capture(int(self.winId()))

    def _build_ui(self):
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self._pill = QWidget(self)
        self._pill.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        row = QHBoxLayout(self._pill)
        row.setContentsMargins(8, 6, 8, 6)
        row.setSpacing(4)

        # ── Left Section: Recording Status ────────────────────────────────────
        self._btn_start = QPushButton("Start")
        self._btn_start.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_start.setStyleSheet(
            """
            QPushButton {
                background: #34C759; color: white; border: none; border-radius: 6px;
                font-weight: bold; padding: 6px 12px;
            }
            QPushButton:hover { background: #32D74B; }
            """
        )
        self._btn_start.clicked.connect(self.start_requested.emit)
        row.addWidget(self._btn_start)

        self._sep_start = self._make_sep(row, True)
        self._sep_start.setVisible(self._pre_record)

        self._dot = QLabel("●")
        self._dot.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._dot.setStyleSheet("color:#FF3B30; font-size:14px; padding:0; margin:0;")
        row.addWidget(self._dot)
        self._dot.setVisible(not self._pre_record)
        
        self._lbl_time = QLabel("00:00:00")
        self._lbl_time.setFixedWidth(54)
        self._lbl_time.setStyleSheet(
            "color:#EBEBF5; font-family:'Segoe UI', monospace; font-size:13px; font-weight:600; margin-top:1px;"
        )
        row.addWidget(self._lbl_time)
        self._lbl_time.setVisible(not self._pre_record)

        self._sep_timer = self._make_sep(row, False)

        # ── Buttons ───────────────────────────────────────────────────────────
        self._btn_pause = _PillToolButton("pause.png", "Pause\n(or Resume ▶)")
        self._btn_pause.clicked.connect(self.toggle_pause)
        row.addWidget(self._btn_pause)
        self._btn_pause.setVisible(not self._pre_record)

        self._btn_stop = _PillToolButton("stop.png", "Stop")
        self._btn_stop.set_danger(True)
        self._btn_stop.clicked.connect(self._initiate_stop)
        row.addWidget(self._btn_stop)
        self._btn_stop.setVisible(not self._pre_record)

        self._btn_stop.setVisible(not self._pre_record)

        self._sep_stop = self._make_sep(row, False)

        self._btn_sys = _PillToolButton("desktop_audio.png", "Desktop Audio\nON", checkable=True, icon_off_filename="desktop_audiooff.png")
        sys_state = self._engine.get_system_audio()
        self._btn_sys.setChecked(sys_state)
        self._btn_sys.update_text("Desktop Audio\nON" if sys_state else "Desktop Audio\nOFF")
        self._btn_sys.toggled.connect(self._on_sys_toggled)
        row.addWidget(self._btn_sys)

        self._btn_mic = _PillToolButton("mic.png", "Microphone\nON", checkable=True, icon_off_filename="micoff.png")
        mic_state = self._engine.get_mic()
        self._btn_mic.setChecked(mic_state)
        self._btn_mic.update_text("Microphone\nON" if mic_state else "Microphone\nOFF")
        self._btn_mic.toggled.connect(self._on_mic_toggled)
        row.addWidget(self._btn_mic)

        self._btn_settings = _PillToolButton("settings.png", "Settings")
        self._btn_settings.clicked.connect(self.settings_requested.emit)
        row.addWidget(self._btn_settings)

        self._sep_settings = self._make_sep(row, True)

        self._btn_discard = _PillToolButton("delete.png", "Discard Recording")
        self._btn_discard.set_danger(True)
        self._btn_discard.clicked.connect(self._initiate_discard)
        if self._pre_record:
            self._btn_discard.setToolTip("Cancel / Discard")
        row.addWidget(self._btn_discard)

        # ── Group Visibility Initialization ───────────────────────────────────
        # Ensure every element starts in the correct state for the current mode
        self._btn_start.setVisible(self._pre_record)
        self._sep_start.setVisible(self._pre_record)
        self._dot.setVisible(not self._pre_record)
        self._lbl_time.setVisible(not self._pre_record)
        self._sep_timer.setVisible(not self._pre_record)
        self._btn_pause.setVisible(not self._pre_record)
        self._btn_stop.setVisible(not self._pre_record)
        self._sep_stop.setVisible(not self._pre_record)

        # ── Size Pill to content ───────────────────────────────────────────────
        self._update_size()
        outer.addWidget(self._pill)

    def _on_sys_toggled(self, checked):
        self._btn_sys.update_text("Desktop Audio\nON" if checked else "Desktop Audio\nOFF")
        self._engine.set_system_audio(checked)

    def _on_mic_toggled(self, checked):
        self._btn_mic.update_text("Microphone\nON" if checked else "Microphone\nOFF")
        self._engine.set_mic(checked)

    # ── Timers ────────────────────────────────────────────────────────────────
    def _setup_timers(self):
        if self._pre_record:
            return
        self._tick = QTimer(self)
        self._tick.setInterval(1000)
        self._tick.timeout.connect(self._on_tick)
        self._tick.start()

        self._blink = QTimer(self)
        self._blink.setInterval(700)
        self._blink.timeout.connect(self._on_blink)
        self._blink.start()
        self._blink_on = True

    def set_recording_mode(self):
        """Transition from 'Pre-Record' (setup) to active recording UI."""
        if not self._pre_record:
            return
        self._pre_record = False
        
        # Hide start button, show recording status
        self._btn_start.hide()
        self._dot.show()
        self._lbl_time.show()
        self._sep_timer.show()
        self._sep_start.hide()
        
        # Show control buttons
        self._btn_pause.show()
        self._btn_stop.show()
        self._sep_stop.show()
        
        # Setup and start timers
        self._setup_timers()
        self._update_size()

    def _update_size(self):
        """Recalculate layout and resize window to fit content."""
        self._pill.adjustSize()
        w = self._pill.sizeHint().width()
        h = self._pill.sizeHint().height()
        self.setFixedSize(w, h)
        self.setFixedSize(w, h)
        self._pill.setGeometry(0, 0, w, h)

    def _on_tick(self):
        if not self._engine.is_paused():
            self._elapsed += 1
        h = self._elapsed // 3600
        m = (self._elapsed % 3600) // 60
        s = self._elapsed % 60
        if h > 0:
            self._lbl_time.setText(f"{h:02d}:{m:02d}:{s:02d}")
        else:
            self._lbl_time.setText(f"00:{m:02d}:{s:02d}")

    def _on_blink(self):
        if self._engine.is_paused():
            self._dot.setStyleSheet("color:#FF9F0A; font-size:12px; padding:0; margin:0;")
        else:
            self._blink_on = not self._blink_on
            clr = "#FF3B30" if self._blink_on else "rgba(255,59,48,0)"
            self._dot.setStyleSheet(f"color:{clr}; font-size:12px; padding:0; margin:0;")

    # ── Actions ─────────────────────────────────────────────────────────────
    def toggle_pause(self):
        if self._engine.is_paused():
            self._engine.resume()
            self._btn_pause.update_text("Pause")
            self._btn_pause.setIcon(QIcon(_asset("pause.png")))
        else:
            self._engine.pause()
            self._btn_pause.update_text("Resume")
            self._btn_pause.setIcon(QIcon(_asset("play.png")))

    def _initiate_stop(self):
        if hasattr(self, '_tick'): self._tick.stop()
        if hasattr(self, '_blink'): self._blink.stop()

        # Hide pill IMMEDIATELY — user sees instant response
        self.hide()

        # Tell main.py to clear border/overlay right now
        self.stopped.emit("<SAVING>")

        # Run capture stop + muxing in background
        self._stop_worker = _StopWorker(self._engine)
        self._stop_worker.finished.connect(self._on_save_done)
        self._stop_worker.start()

    def _initiate_discard(self):
        if hasattr(self, '_tick'): self._tick.stop()
        if hasattr(self, '_blink'): self._blink.stop()

        # Hide pill IMMEDIATELY
        self.hide()
        self.stopped.emit("<DISCARDED>")

        # Discard in background (fast — no muxing needed)
        self._discard_worker = _StopWorker.__new__(_StopWorker)  # avoid __init__
        # Use a simple thread for the discard
        import threading
        threading.Thread(target=self._do_discard, daemon=True).start()

    def _do_discard(self):
        self._engine.discard()

    def _on_save_done(self, filepath: str):
        self.save_completed.emit(filepath)
        self.close()

    def _make_sep(self, layout, visible=True):
        """Creates a separator container with internal margins that collapse when hidden."""
        container = QWidget()
        container.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        l = QHBoxLayout(container)
        l.setContentsMargins(4, 0, 4, 0)
        l.setSpacing(0)
        
        line = QWidget()
        line.setFixedSize(1, 20)
        line.setStyleSheet("background-color: #4A4A4C;")
        l.addWidget(line)
        
        container.setVisible(visible)
        layout.addWidget(container)
        return container

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = 12.0
        rect = self.rect().adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(float(rect.x()), float(rect.y()), float(rect.width()), float(rect.height()), r, r)

        p.fillPath(path, QBrush(self._BG_DARK))
        p.setPen(QPen(self._BORDER_CLR, 1.0))
        p.drawPath(path)
        p.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, event):
        if self._drag_pos and (event.buttons() & Qt.MouseButton.LeftButton):
            self.move(event.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, _event):
        self._drag_pos = None

    def _position_on_screen(self):
        sg = QApplication.primaryScreen().geometry()
        # Move up a bit to match control center styling commonly used
        self.move(sg.center().x() - self.width() // 2, sg.top() + 30)


# ─────────────────────────────────────────────────────────────────────────────
#  SettingsWindow
# ─────────────────────────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────────────────────────
#  Settings Custom Widgets
# ─────────────────────────────────────────────────────────────────────────────
class ToggleSwitch(QCheckBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(46, 26)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        bg = QColor("#32D74B") if self.isChecked() else QColor("#39393D")
        p.setBrush(bg)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(0, 0, self.width(), self.height(), 13, 13)
        p.setBrush(QColor("#FFFFFF"))
        if self.isChecked(): p.drawEllipse(self.width() - 24, 2, 22, 22)
        else: p.drawEllipse(2, 2, 22, 22)
        p.end()
    def hitButton(self, pos: QPoint) -> bool:
        return self.rect().contains(pos)

class HotkeyInput(QLineEdit):
    def __init__(self, default=""):
        super().__init__(default)
        self.setReadOnly(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._listening = False
    def mousePressEvent(self, e):
        super().mousePressEvent(e)
        self._listening = True
        self.setText("Listening...")
        self.setStyleSheet("background: #0A84FF; color: white;")
    def keyPressEvent(self, e):
        if not self._listening: return
        mods = []
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier: mods.append("<ctrl>")
        if e.modifiers() & Qt.KeyboardModifier.AltModifier: mods.append("<alt>")
        if e.modifiers() & Qt.KeyboardModifier.ShiftModifier: mods.append("<shift>")
        k = e.key()
        if k in (Qt.Key.Key_Control, Qt.Key.Key_Shift, Qt.Key.Key_Alt, Qt.Key.Key_Meta): return
        ks = ""
        if Qt.Key.Key_A <= k <= Qt.Key.Key_Z: ks = chr(k).lower()
        elif Qt.Key.Key_0 <= k <= Qt.Key.Key_9: ks = chr(k)
        else:
            map_k = {Qt.Key.Key_Return:"<enter>", Qt.Key.Key_Escape:"<esc>", Qt.Key.Key_Space:"<space>", Qt.Key.Key_Backspace:"<backspace>"}
            if k in map_k: ks = map_k[k]
            elif Qt.Key.Key_F1 <= k <= Qt.Key.Key_F12: ks = f"<f{k - Qt.Key.Key_F1 + 1}>"
        if ks:
            mods.append(ks)
            self.setText("+".join(mods))
            self._listening = False
            self.setStyleSheet("")

class SettingsWindow(QDialog):
    def __init__(self, config: dict):
        super().__init__(None, Qt.WindowType.WindowCloseButtonHint)
        self._config = config.copy()
        
        # OS window title & icon
        self.setWindowTitle("WWRecorder Settings")
        icon_path = _asset('icon.ico')
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
            
        self.setFixedWidth(500)
        self.setModal(True)
        self._build_ui()
        self._apply_style()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(30, 25, 30, 30)
        root.setSpacing(25)

        # Header
        hdr_lay = QHBoxLayout()
        icon_lbl = QLabel()
        icon_path = _asset('icon.ico')
        if os.path.exists(icon_path):
            from PyQt6.QtGui import QPixmap
            icon_lbl.setPixmap(QPixmap(icon_path).scaled(28, 28, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        hdr = QLabel("WWRecorder Settings")
        hdr.setObjectName("heading")
        hdr_lay.addWidget(icon_lbl)
        hdr_lay.addSpacing(8)
        hdr_lay.addWidget(hdr)
        hdr_lay.addStretch()
        root.addLayout(hdr_lay)

        # Layout Helper
        def create_group(title):
            grp = QGroupBox(title)
            lay = QVBoxLayout(grp)
            lay.setContentsMargins(20, 25, 20, 20)
            lay.setSpacing(14)
            return grp, lay

        # ── Output folder ─────────────────────────────────────────────────────
        grp_out, lay_out = create_group("Recording Output")
        
        row_out = QHBoxLayout()
        self._edt_folder = QLineEdit(self._config.get("output_folder", ""))
        self._edt_folder.setReadOnly(True)
        self._edt_folder.setMinimumHeight(38)
        row_out.addWidget(self._edt_folder)

        btn_browse = QPushButton("Browse")
        btn_browse.setObjectName("secondary")
        btn_browse.setMinimumHeight(38)
        btn_browse.setFixedWidth(80)
        btn_browse.clicked.connect(self._browse)
        row_out.addWidget(btn_browse)
        
        lay_out.addLayout(row_out)
        root.addWidget(grp_out)

        # ── Shortcuts & Share ─────────────────────────────────────────────────
        hk_share_lay = QHBoxLayout()
        hk_share_lay.setSpacing(15)

        grp_hk, lay_hk = create_group("Hotkey Settings")
        
        lbl_hk = QLabel("Shortcut Key:")
        lay_hk.addWidget(lbl_hk)
        
        self._edt_hotkey = HotkeyInput(self._config.get("hotkey", "<shift>+<backspace>"))
        self._edt_hotkey.setMinimumHeight(38)
        lay_hk.addWidget(self._edt_hotkey)
        
        hk_share_lay.addWidget(grp_hk)

        # ── Share App ─────────────────────────────────────────────────────────
        grp_share, lay_share = create_group("Share App")
        
        lbl_share = QLabel("Invite friends to use WWRecorder:")
        lay_share.addWidget(lbl_share)

        btn_copy_link = QPushButton("Copy App Link")
        btn_copy_link.setObjectName("secondary")
        btn_copy_link.setMinimumHeight(38)
        btn_copy_link.clicked.connect(self._copy_app_link)
        lay_share.addWidget(btn_copy_link)
        
        hk_share_lay.addWidget(grp_share)

        root.addLayout(hk_share_lay)

        # ── Toggles ───────────────────────────────────────────────────────────
        grp_def, lay_def = create_group("Default Behavior")

        def add_toggle_row(lay, label_text, is_checked):
            row = QHBoxLayout()
            chk = ToggleSwitch()
            chk.setChecked(is_checked)
            lbl = QLabel(label_text)
            lbl.setStyleSheet("font-size: 14px; color: #EBEBF5;")
            row.addWidget(chk)
            row.addSpacing(10)
            row.addWidget(lbl)
            row.addStretch()
            lay.addLayout(row)
            return chk

        self._chk_sys = add_toggle_row(lay_def, "Record system audio by default", self._config.get("default_system_audio", True))
        self._chk_mic = add_toggle_row(lay_def, "Record microphone by default", self._config.get("default_mic", False))
        self._chk_boot = add_toggle_row(lay_def, "Start WWRecorder with Windows", self._config.get("start_on_boot", False))
        
        root.addWidget(grp_def)

        # ── Buttons ───────────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        
        credit = QLabel("<a href='https://github.com/akasumitlamba' style='color:#0A84FF; text-decoration:underline; font-size:12px;'>Made by akasumitlamba</a>")
        credit.setOpenExternalLinks(True)
        btn_row.addWidget(credit)
        
        btn_row.addStretch()

        btn_cancel = QPushButton("Cancel")
        btn_cancel.setObjectName("secondary")
        btn_cancel.setMinimumHeight(38)
        btn_cancel.setFixedWidth(100)
        btn_cancel.clicked.connect(self.reject)
        
        btn_save = QPushButton("Save Settings")
        btn_save.setObjectName("primary")
        btn_save.setMinimumHeight(38)
        btn_save.setFixedWidth(130)
        btn_save.clicked.connect(self._save)

        btn_row.addWidget(btn_cancel)
        btn_row.addSpacing(6)
        btn_row.addWidget(btn_save)
        root.addLayout(btn_row)

    def _browse(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Output Folder", self._edt_folder.text())
        if folder:
            self._edt_folder.setText(folder)

    def _copy_app_link(self):
        QApplication.clipboard().setText("https://akasumitlamba.github.io/WWRecorder/")
        btn = self.sender()
        if btn:
            orig = btn.text()
            btn.setText("Copied!")
            QTimer.singleShot(1500, lambda: btn.setText(orig))

    def _save(self):
        self._config.update({
            "output_folder":        self._edt_folder.text(),
            "hotkey":               self._edt_hotkey.text().strip(),
            "default_system_audio": self._chk_sys.isChecked(),
            "default_mic":          self._chk_mic.isChecked(),
            "start_on_boot":        self._chk_boot.isChecked(),
        })
        self.accept()

    def get_config(self) -> dict: return self._config

    def _apply_style(self):
        self.setStyleSheet("""
            QDialog {
                background-color: #1C1C1E;
                color: #FFFFFF;
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            }
            #heading {
                font-size: 26px; font-weight: 700; color: #FFFFFF;
            }
            QGroupBox {
                background: #252528; border: 1px solid #333336; border-radius: 8px;
                font-size: 13px; font-weight: 600; color: #8E8E93;
                margin-top: 14px; padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin; subcontrol-position: top left; left: 16px; padding: 0 4px;
            }
            QLabel { font-size: 13px; color: #D1D1D6; }
            QLineEdit {
                background: #1C1C1E; border: 1px solid #333336; border-radius: 6px;
                padding: 0 12px; color: #FFFFFF; font-size: 14px;
            }
            QLineEdit:focus { border: 1px solid #0A84FF; }
            
            QCheckBox { font-size: 14px; color: #EBEBF5; spacing: 12px; height: 30px; }
            /* Default QCheckBox styles are ignored for the custom ToggleSwitch. */
            
            QPushButton {
                font-size: 14px; font-weight: 600; border-radius: 8px;
            }
            QPushButton#secondary {
                background: #3A3A3C; color: #FFFFFF; border: none;
            }
            QPushButton#secondary:hover { background: #48484A; }
            QPushButton#primary {
                background: #0A84FF; color: #FFFFFF; border: none;
            }
            QPushButton#primary:hover { background: #0070DF; }
        """)
