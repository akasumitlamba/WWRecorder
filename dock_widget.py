"""
dock_widget.py - Floating Assistive Dock & Sidebar Panels

• DockWidget       : Edge-snapping floating dock with 4 action buttons
• SidebarPanel     : Full-height resizable sidebar (base class)
• SettingsSidebar  : All app settings in a sidebar
• RecentFilesSidebar : Recent files gallery in a sidebar

All are invisible to screen capture via SetWindowDisplayAffinity.
Red + white theme to match the WWRECORDER brand.
"""

import ctypes
import os
import sys
from pathlib import Path
from datetime import datetime
from collections import OrderedDict
from typing import Optional

from PyQt6.QtWidgets import (
    QApplication, QWidget, QLabel, QPushButton, QToolButton,
    QHBoxLayout, QVBoxLayout, QScrollArea, QLineEdit,
    QMessageBox, QSizePolicy, QFileDialog, QCheckBox,
    QFrame, QComboBox, QToolTip, QGraphicsOpacityEffect,
)
from PyQt6.QtCore import (
    Qt, QRect, QPoint, QPointF, QSize, QTimer, QMimeData, QUrl,
    pyqtSignal, pyqtSlot, QPropertyAnimation, QEasingCurve, QSequentialAnimationGroup,
    QRunnable, QThreadPool, QObject, QEvent,
)
from PyQt6.QtGui import (
    QPainter, QColor, QBrush, QPen, QFont, QFontMetrics,
    QPainterPath, QIcon, QDrag, QPixmap, QCursor, QImage, QLinearGradient,
)

import subprocess
import webbrowser
import threading
from updater import UpdateChecker

# Keep manual check threads alive even if their sidebar is recreated. Qt aborts
# the process when a running QThread is destroyed.
_ACTIVE_UPDATE_THREADS = set()

# ── Windows API ────────────────────────────────────────────────────────────────
WDA_EXCLUDEFROMCAPTURE = 0x00000011
_user32 = ctypes.windll.user32 if sys.platform == "win32" else None


def _exclude_from_capture(hwnd: int) -> None:
    if _user32:
        try:
            _user32.SetWindowDisplayAffinity(ctypes.c_void_p(hwnd), WDA_EXCLUDEFROMCAPTURE)
        except Exception as exc:
            print(f"[Dock] SetWindowDisplayAffinity failed: {exc}")


def _asset(filename: str) -> str:
    base_dir = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_dir, 'icons', filename)


def _set_explicit_tab_chain(root: QWidget) -> int:
    controls = [w for w in root.findChildren(QWidget)
                if w.window() is root.window() and w.focusPolicy() & Qt.FocusPolicy.TabFocus]
    for first, second in zip(controls, controls[1:]):
        QWidget.setTabOrder(first, second)
    if len(controls) > 1:
        QWidget.setTabOrder(controls[-1], controls[0])
    return len(controls)


# ── Theme ─────────────────────────────────────────────────────────────────────
CLR_BG      = QColor(10, 12, 17, 250)
CLR_SURFACE = QColor(18, 22, 31)
CLR_CARD    = QColor(25, 30, 42)
CLR_BORDER  = QColor(52, 59, 72)
CLR_RED     = QColor(255, 51, 71)
CLR_RED_HVR = QColor(255, 82, 100)

# ── Global Performance Cache ──────────────────────────────────────────────────
# Stores {filepath: (mtime, jpeg_bytes, duration_str)} to avoid redundant FFmpeg tasks
GLOBAL_THUMB_CACHE = OrderedDict()
GLOBAL_THUMB_CACHE_LIMIT = 256
GLOBAL_THUMB_CACHE_LOCK = threading.Lock()
THUMBNAIL_POOL = QThreadPool()
THUMBNAIL_POOL.setMaxThreadCount(2)


def _cache_thumbnail(filepath: str, value) -> None:
    with GLOBAL_THUMB_CACHE_LOCK:
        GLOBAL_THUMB_CACHE[filepath] = value
        GLOBAL_THUMB_CACHE.move_to_end(filepath)
        while len(GLOBAL_THUMB_CACHE) > GLOBAL_THUMB_CACHE_LIMIT:
            GLOBAL_THUMB_CACHE.popitem(last=False)


def _get_cached_thumbnail(filepath: str):
    with GLOBAL_THUMB_CACHE_LOCK:
        return GLOBAL_THUMB_CACHE.get(filepath)


# PERF-002: Background file scanner to avoid blocking UI thread during iterdir() + stat()
class _FileScanSignals(QObject):
    finished = pyqtSignal(list, int)  # files and the scan generation that produced them

class _FileScanTask(QRunnable):
    """Scans the output folder for media files in a background thread."""
    def __init__(self, folder: str, exclude_filename: str = None, generation: int = 0):
        super().__init__()
        self.folder = folder
        self.exclude_filename = exclude_filename
        self.generation = generation
        self.signals = _FileScanSignals()

    def run(self):
        exts = {".mkv", ".mp4", ".png", ".jpg", ".webm", ".avi"}
        files = []
        try:
            folder = Path(self.folder)
            if folder.exists():
                for f in folder.iterdir():
                    if f.is_file() and f.suffix.lower() in exts:
                        if self.exclude_filename and f.name == self.exclude_filename:
                            continue
                        try:
                            files.append((str(f), f.stat().st_mtime))
                        except Exception:
                            pass
        except Exception:
            pass
        files.sort(key=lambda x: x[1], reverse=True)
        self.signals.finished.emit(files[:50], self.generation)


# ─────────────────────────────────────────────────────────────────────────────
#  Red Toggle Switch
# ─────────────────────────────────────────────────────────────────────────────

class _RedToggle(QCheckBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(40, 22)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        bg = QColor("#DC2626") if self.isChecked() else QColor("#39393D")
        p.setBrush(bg)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(0, 0, self.width(), self.height(), 11, 11)
        p.setBrush(QColor("#FFFFFF"))
        if self.isChecked():
            p.drawEllipse(self.width() - 20, 2, 18, 18)
        else:
            p.drawEllipse(2, 2, 18, 18)
        p.end()

    def hitButton(self, pos):
        return self.rect().contains(pos)


# ─────────────────────────────────────────────────────────────────────────────
#  Hotkey Input (reused from ui_elements style, red themed)
# ─────────────────────────────────────────────────────────────────────────────

class _HotkeyInput(QFrame):
    textChanged = pyqtSignal(str)

    def __init__(self, default=""):
        super().__init__()
        self._text = default
        self._listening = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(36)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(10, 0, 10, 0)
        self._layout.setSpacing(6)
        
        self._prompt = QLabel("Listening... (Press Esc to cancel)")
        self._prompt.setStyleSheet("color: rgba(255,255,255,0.7); font-size: 13px; font-family: 'Segoe UI';")
        self._prompt.hide()
        self._layout.addWidget(self._prompt)
        
        self._keys_container = QWidget()
        self._keys_layout = QHBoxLayout(self._keys_container)
        self._keys_layout.setContentsMargins(0, 0, 0, 0)
        self._keys_layout.setSpacing(4)
        self._keys_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self._layout.addWidget(self._keys_container)
        self._layout.addStretch()

        self._update_style()
        self.setText(default)

    def _update_style(self):
        if self._listening:
            self.setStyleSheet("""
                _HotkeyInput { background: #DC2626; border: 1px solid #EF4444; border-radius: 6px; }
            """)
        else:
            self.setStyleSheet("""
                _HotkeyInput { background: #1C1C1E; border: 1px solid #3C3C3E; border-radius: 6px; }
                _HotkeyInput:hover { border: 1px solid #5C5C5E; }
            """)

    def text(self):
        return self._text

    def setText(self, txt):
        if self._text != txt:
            self._text = txt
            self.textChanged.emit(txt)
        
        while self._keys_layout.count():
            item = self._keys_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
                
        if not txt:
            self._prompt.setText("Click to set shortcut")
            self._prompt.show()
            self._keys_container.hide()
            return
            
        self._prompt.hide()
        self._keys_container.show()
        
        keys = txt.replace('<', '').replace('>', '').split('+')
        for k in keys:
            if not k:
                continue
            lbl = QLabel(k.title())
            lbl.setFixedHeight(22)
            lbl.setStyleSheet("""
                background: #2D2D30; color: #FFFFFF; border: 1px solid #4D4D50;
                border-radius: 4px; padding: 0 6px; font-size: 11px; font-weight: 600; font-family: 'Segoe UI';
            """)
            self._keys_layout.addWidget(lbl)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._listening = True
            self._keys_container.hide()
            self._prompt.setText("Listening... (Press Esc to cancel)")
            self._prompt.show()
            self._update_style()
            self.setFocus()

    def keyPressEvent(self, e):
        if not self._listening:
            return
        
        k = e.key()
        if k == Qt.Key.Key_Escape:
            self._listening = False
            self.setText(self._text)
            self._update_style()
            return

        mods = []
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            mods.append("<ctrl>")
        if e.modifiers() & Qt.KeyboardModifier.AltModifier:
            mods.append("<alt>")
        if e.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            mods.append("<shift>")
            
        if k in (Qt.Key.Key_Control, Qt.Key.Key_Shift, Qt.Key.Key_Alt, Qt.Key.Key_Meta):
            return
            
        ks = ""
        if Qt.Key.Key_A <= k <= Qt.Key.Key_Z:
            ks = chr(k).lower()
        elif Qt.Key.Key_0 <= k <= Qt.Key.Key_9:
            ks = chr(k)
        else:
            map_k = {
                Qt.Key.Key_Return: "<enter>", Qt.Key.Key_Space: "<space>", Qt.Key.Key_Backspace: "<backspace>",
                Qt.Key.Key_Home: "<home>", Qt.Key.Key_End: "<end>", Qt.Key.Key_Insert: "<insert>",
                Qt.Key.Key_Delete: "<delete>", Qt.Key.Key_PageUp: "<page_up>", Qt.Key.Key_PageDown: "<page_down>",
                Qt.Key.Key_Up: "<up>", Qt.Key.Key_Down: "<down>", Qt.Key.Key_Left: "<left>", Qt.Key.Key_Right: "<right>",
                Qt.Key.Key_Print: "<print_screen>", Qt.Key.Key_SysReq: "<print_screen>",
                Qt.Key.Key_Escape: "<esc>", Qt.Key.Key_Tab: "<tab>",
            }
            if k in map_k:
                ks = map_k[k]
            elif Qt.Key.Key_F1 <= k <= Qt.Key.Key_F12:
                ks = f"<f{k - Qt.Key.Key_F1 + 1}>"
                
        if ks:
            mods.append(ks)
            self._listening = False
            self.setText("+".join(mods))
            self._update_style()
            
    def focusOutEvent(self, e):
        if self._listening:
            self._listening = False
            self.setText(self._text)
            self._update_style()
        super().focusOutEvent(e)


class _RenameLineEdit(QLineEdit):
    cancel_requested = pyqtSignal()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.cancel_requested.emit()
            event.accept()
            return
        super().keyPressEvent(event)


# ─────────────────────────────────────────────────────────────────────────────
#  _ShareWidget
# ─────────────────────────────────────────────────────────────────────────────

# _ShareWidget removed - logic moved to SettingsSidebar share button


# ─────────────────────────────────────────────────────────────────────────────
#  DockWidget — Clean 4-button dock
# ─────────────────────────────────────────────────────────────────────────────

class DockWidget(QWidget):
    """
    Small grabber on screen edge → hovers to reveal 4 action buttons.
    """

    screenshot_requested = pyqtSignal()
    record_requested     = pyqtSignal()
    annotate_requested   = pyqtSignal()
    files_requested      = pyqtSignal()
    settings_requested   = pyqtSignal()

    GRABBER_W = 12
    GRABBER_H = 48

    # Default is deliberately slimmer than the earlier 52px dock. Compact
    # screens reduce it again when the hover panel opens.
    EXPANDED_W = 48
    EXPANDED_H = 228
    COMPACT_EXPANDED_W = 44
    COMPACT_EXPANDED_H = 204

    def __init__(self, engine, config: dict, parent=None):
        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        super().__init__(None, flags)

        self._engine = engine
        # Keep the app-owned config mapping so dock position updates persist.
        self._config = config
        self._expanded = False
        self._is_recording = False
        self._drag_pos: Optional[QPoint] = None
        self._is_dragging = False
        self._edge = config.get("dock_edge", "right")
        self._dock_y = config.get("dock_y", -1)

        self._collapse_timer = QTimer(self)
        self._collapse_timer.setSingleShot(True)
        self._collapse_timer.setInterval(400)
        self._collapse_timer.timeout.connect(self._collapse)

        self._pulse_visible = True
        self._pulse_timer = QTimer(self)
        self._pulse_timer.setInterval(600)
        self._pulse_timer.timeout.connect(self._pulse_tick)

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_AlwaysShowToolTips)

        self.setMouseTracking(True)
        
        # Explicit font setup to prevent QFont terminal spam
        # (Qt warns if pointSize is -1 when showing tooltips)
        f = QFont("Segoe UI", 10)
        self.setFont(f)
        
        self.setStyleSheet("""
            * {
                font-family: 'Segoe UI';
                font-size: 10pt;
            }
            QToolTip {
                font-family: 'Segoe UI';
                font-size: 10pt;
                color: #FFFFFF;
                background: #1C1C1E;
                border: 1px solid #3C3C3E;
            }
        """)

        self._build_panel()
        self._position_on_edge()

        self._topmost_timer = QTimer(self)
        self._topmost_timer.timeout.connect(self._enforce_topmost)
        self._topmost_timer.start(2000)

        # First Launch Blink
        self._is_first_launch = True
        self._blink_on = False
        self._blink_count = 0
        self._first_blink_timer = QTimer(self)
        self._first_blink_timer.setInterval(450)
        self._first_blink_timer.timeout.connect(self._on_first_blink_tick)
        self._first_blink_timer.start()

    def showEvent(self, event):
        super().showEvent(event)
        handle = self.windowHandle()
        if handle and not getattr(self, '_screen_change_connected', False):
            handle.screenChanged.connect(self._on_screen_changed)
            self._screen_change_connected = True
            self._on_screen_changed(handle.screen())

    def _on_screen_changed(self, screen):
        old = getattr(self, '_geometry_screen', None)
        if old is not None:
            try:
                old.availableGeometryChanged.disconnect(self._on_screen_geometry_changed)
            except (TypeError, RuntimeError):
                pass
        self._geometry_screen = screen
        if screen is not None:
            screen.availableGeometryChanged.connect(self._on_screen_geometry_changed)
        self._on_screen_geometry_changed()

    def _on_screen_geometry_changed(self, *_):
        self._stop_animations()
        self._position_on_edge()

    def _on_first_blink_tick(self):
        # Keep blinking until the dock is discovered. There is deliberately no
        # timeout: a user may not notice the edge grabber immediately.
        self._blink_on = not self._blink_on
        self._blink_count += 1
        self.update()

    def _acknowledge_startup_indicator(self):
        """Stop the one-time ready blink for the remainder of this process."""
        if not self._is_first_launch:
            return
        self._is_first_launch = False
        self._blink_on = False
        self._first_blink_timer.stop()
        self.update()

    def _enforce_topmost(self):
        if self.isVisible() and not self._expanded:
            if _user32:
                HWND_TOPMOST = -1
                SWP_NOSIZE = 0x0001
                SWP_NOMOVE = 0x0002
                SWP_NOACTIVATE = 0x0010
                _user32.SetWindowPos(int(self.winId()), HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
            self.raise_()

    def _build_panel(self):
        self._panel = QWidget(self)
        self._panel.setVisible(False)
        self._panel.setMouseTracking(True)

        layout = QVBoxLayout(self._panel)
        self._panel_layout = layout
        layout.setContentsMargins(4, 6, 4, 6)
        layout.setSpacing(4)
        self._dock_buttons = []

        hk_ss = self._config.get("hotkey_screenshot", "<ctrl>+<alt>+c").replace("<", "").replace(">", "").title()
        self._btn_screenshot = self._make_btn("screenshot.png", f"Screenshot ({hk_ss})")
        self._btn_screenshot.clicked.connect(self.screenshot_requested.emit)
        layout.addWidget(self._btn_screenshot)
        self._dock_buttons.append(self._btn_screenshot)

        hk_rec = self._config.get("hotkey", "<shift>+<backspace>").replace("<", "").replace(">", "").title()
        self._btn_record = self._make_btn("record.png", f"Recording ({hk_rec})")
        self._btn_record.clicked.connect(self.record_requested.emit)
        layout.addWidget(self._btn_record)
        self._dock_buttons.append(self._btn_record)

        self._btn_annotate = self._make_btn("annotate.png", "Live Annotator / Draw over screen")
        if not os.path.isfile(_asset("annotate.png")):
            self._btn_annotate.setText("✎")
            self._btn_annotate.setStyleSheet(self._btn_annotate.styleSheet() + "QToolButton { font-size: 16px; }")
        self._btn_annotate.clicked.connect(self.annotate_requested.emit)
        layout.addWidget(self._btn_annotate)
        self._dock_buttons.append(self._btn_annotate)

        self._btn_files = self._make_btn("folder.png", "Recent Files")
        self._btn_files.clicked.connect(self.files_requested.emit)
        layout.addWidget(self._btn_files)
        self._dock_buttons.append(self._btn_files)

        self._btn_settings = self._make_btn("settings.png", "Settings")
        self._btn_settings.clicked.connect(self.settings_requested.emit)
        layout.addWidget(self._btn_settings)
        self._dock_buttons.append(self._btn_settings)

        self._panel.adjustSize()

    def set_annotation_active(self, active: bool):
        if hasattr(self, '_btn_annotate') and hasattr(self._btn_annotate, 'set_dynamic_icon'):
            if active:
                self._btn_annotate.set_dynamic_icon("close.png", "X", "Close Annotator")
            else:
                self._btn_annotate.set_dynamic_icon("annotate.png", "✎", "Live Annotator / Draw over screen")

    def _make_btn(self, icon_file: str, tooltip: str) -> QToolButton:
        icon_path = _asset(icon_file)

        class TintingToolButton(QToolButton):
            def __init__(self, tooltip):
                super().__init__()
                self.setToolTip(tooltip)
                self.setIconSize(QSize(22, 22))
                self.setFixedSize(40, 40)
                self.setCursor(Qt.CursorShape.PointingHandCursor)
                self.setMouseTracking(True)
                self.setAttribute(Qt.WidgetAttribute.WA_AlwaysShowToolTips)
                
                self.icon_normal = QIcon()
                self.icon_hover = QIcon()
                
                if os.path.isfile(icon_path):
                    pm = QPixmap(icon_path)
                    self.icon_normal = QIcon(pm)
                    
                    pm_white = QPixmap(pm.size())
                    pm_white.fill(Qt.GlobalColor.transparent)
                    p = QPainter(pm_white)
                    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
                    p.drawPixmap(0, 0, pm)
                    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
                    p.fillRect(pm_white.rect(), QColor(255, 255, 255))
                    p.end()
                    self.icon_hover = QIcon(pm_white)
                    
                    self.setIcon(self.icon_normal)

                self._tip_timer = QTimer(self)
                self._tip_timer.setSingleShot(True)
                self._tip_timer.setInterval(400) # Standard tooltip delay
                self._tip_timer.timeout.connect(self._show_tip)

            def set_dynamic_icon(self, icon_name: str, fallback: str, new_tooltip: str):
                self.setToolTip(new_tooltip)
                path = _asset(icon_name)
                if os.path.isfile(path):
                    pm = QPixmap(path)
                    self.icon_normal = QIcon(pm)
                    pm_white = QPixmap(pm.size())
                    pm_white.fill(Qt.GlobalColor.transparent)
                    p = QPainter(pm_white)
                    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
                    p.drawPixmap(0, 0, pm)
                    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
                    p.fillRect(pm_white.rect(), QColor(255, 255, 255))
                    p.end()
                    self.icon_hover = QIcon(pm_white)
                    if self.underMouse():
                        self.setIcon(self.icon_hover)
                    else:
                        self.setIcon(self.icon_normal)
                    self.setText("")
                else:
                    self.icon_normal = QIcon()
                    self.icon_hover = QIcon()
                    self.setIcon(QIcon())
                    self.setText(fallback)
                    self.setStyleSheet(self.styleSheet() + " QToolButton { font-size: 16px; }")
                
            def _show_tip(self):
                if self.underMouse() and self.toolTip():
                    pos = self.mapToGlobal(QPoint(self.width() // 2, self.height() + 4))
                    QToolTip.showText(pos, self.toolTip(), self)

            def mousePressEvent(self, e):
                self._tip_timer.stop()
                QToolTip.hideText()
                super().mousePressEvent(e)

            def enterEvent(self, e):
                if not self.icon_hover.isNull():
                    self.setIcon(self.icon_hover)
                self._tip_timer.start()
                super().enterEvent(e)
                
            def leaveEvent(self, e):
                if not self.icon_normal.isNull():
                    self.setIcon(self.icon_normal)
                self._tip_timer.stop()
                QToolTip.hideText()
                super().leaveEvent(e)

        btn = TintingToolButton(tooltip)

        btn.setStyleSheet("""
            QToolButton {
                background: transparent;
                border: 1px solid transparent;
                border-radius: 12px;
            }
            QToolButton:hover {
                background: #FF4055;
                border: 1px solid #FF6373;
            }
            QToolButton:pressed {
                background: #B91C1C;
            }
        """)
        return btn

    def update_config(self, config: dict):
        self._config = config.copy()
        self._edge = self._config.get("dock_edge", "right")
        hk_ss = self._config.get("hotkey_screenshot", "<ctrl>+<alt>+c").replace("<", "").replace(">", "").title()
        hk_rec = self._config.get("hotkey", "<shift>+<backspace>").replace("<", "").replace(">", "").title()
        if hasattr(self, '_btn_screenshot'):
            self._btn_screenshot.setToolTip(f"Screenshot ({hk_ss})")
        if hasattr(self, '_btn_record'):
            self._btn_record.setToolTip(f"Start / Stop Recording ({hk_rec})")

    # ── Geometry ─────────────────────────────────────────────────────────────

    def _screen_geo(self) -> QRect:
        s = self.screen()
        if not s:
            s = QApplication.primaryScreen()
        return s.availableGeometry() if s else QRect(0, 0, 1920, 1080)

    def _position_on_edge(self):
        self._stop_animations()
        sg = self._screen_geo()
        if self._dock_y < 0:
            self._dock_y = sg.center().y() - self.GRABBER_H // 2
        self._dock_y = max(sg.top(), min(self._dock_y, sg.bottom() - self.GRABBER_H))
        self._set_collapsed_geo()

    def _stop_animations(self):
        if hasattr(self, '_collapse_anim') and self._collapse_anim.state() == QPropertyAnimation.State.Running:
            self._collapse_anim.stop()
        if hasattr(self, '_expand_anim') and self._expand_anim.state() == QPropertyAnimation.State.Running:
            self._expand_anim.stop()

    def _set_collapsed_geo(self, animate=True):
        self._stop_animations()
        sg = self._screen_geo()
        x = sg.left() if self._edge == "left" else sg.right() - self.GRABBER_W + 1
        end_rect = QRect(x, self._dock_y, self.GRABBER_W, self.GRABBER_H)
        
        self._expanded = False
        
        if animate and self.isVisible():
            self._collapse_anim = QPropertyAnimation(self, b"geometry")
            self._collapse_anim.setDuration(250)
            self._collapse_anim.setStartValue(self.geometry())
            self._collapse_anim.setEndValue(end_rect)
            self._collapse_anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
            self._collapse_anim.finished.connect(self._on_collapse_finished)
            self._collapse_anim.start()
        else:
            self.setGeometry(end_rect)
            self._panel.setVisible(False)

    def _on_collapse_finished(self):
        if not self._expanded:
            self._panel.setVisible(False)

    def _set_expanded_geo(self, animate=True):
        self._stop_animations()
        sg = self._screen_geo()
        w, h, button_size, icon_size, margin, spacing = self._expanded_metrics(sg)
        self._apply_expanded_metrics(button_size, icon_size, margin, spacing)

        if self._edge == "left":
            x = sg.left()
        else:
            x = sg.right() - w + 1

        center_y = self._dock_y + self.GRABBER_H // 2
        y = center_y - h // 2
        y = max(sg.top(), min(y, sg.bottom() - h))

        end_rect = QRect(x, y, w, h)
        self._expanded = True
        self._panel.setGeometry(0, 0, w, h)
        self._panel.setVisible(True)

        if animate and self.isVisible():
            self._expand_anim = QPropertyAnimation(self, b"geometry")
            self._expand_anim.setDuration(300)
            self._expand_anim.setStartValue(self.geometry())
            self._expand_anim.setEndValue(end_rect)
            self._expand_anim.setEasingCurve(QEasingCurve.Type.OutBack)
            self._expand_anim.start()
        else:
            self.setGeometry(end_rect)

    @classmethod
    def _expanded_metrics(cls, screen_geometry: QRect):
        """Return hover-dock dimensions appropriate for the available screen."""
        compact = (
            screen_geometry.width() <= 1366
            or screen_geometry.height() <= 800
        )
        if compact:
            return (
                cls.COMPACT_EXPANDED_W, cls.COMPACT_EXPANDED_H,
                36, 20, 4, 3,
            )
        return (cls.EXPANDED_W, cls.EXPANDED_H, 40, 22, 4, 4)

    def _apply_expanded_metrics(self, button_size: int, icon_size: int,
                                margin: int, spacing: int):
        """Resize existing controls rather than recreating them during hover."""
        self._panel_layout.setContentsMargins(margin, 6, margin, 6)
        self._panel_layout.setSpacing(spacing)
        for button in self._dock_buttons:
            button.setFixedSize(button_size, button_size)
            button.setIconSize(QSize(icon_size, icon_size))
        self._panel_layout.invalidate()
        self._panel_layout.activate()

    # ── Expand / Collapse ────────────────────────────────────────────────────

    def _expand(self):
        if self._expanded or self._is_dragging:
            return
        self._collapse_timer.stop()
        self._set_expanded_geo()

    def _collapse(self):
        if not self._expanded:
            return
        self._set_collapsed_geo()

    def collapse_for_screenshot(self) -> bool:
        """Collapse immediately before the desktop is frozen for a screenshot."""
        if not self._expanded:
            return False
        self._collapse_timer.stop()
        self._set_collapsed_geo(animate=False)
        self.update()
        return True

    # ── Mouse events ─────────────────────────────────────────────────────────

    def enterEvent(self, event):
        self._collapse_timer.stop()
        self._acknowledge_startup_indicator()

        if not self._expanded and not self._is_dragging:
            self._expand()
        super().enterEvent(event)

    def leaveEvent(self, event):
        if self._expanded:
            self._collapse_timer.start()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint()
            self._drag_start_y = self._dock_y
            self._is_dragging = False

    def mouseMoveEvent(self, event):
        if self._drag_pos and (event.buttons() & Qt.MouseButton.LeftButton):
            delta = event.globalPosition().toPoint() - self._drag_pos
            if abs(delta.y()) > 8 or abs(delta.x()) > 8 or self._is_dragging:
                if not self._is_dragging:
                    self._is_dragging = True
                    self._expanded = False
                    self._panel.setVisible(False)
                    self._stop_animations()
                
                sg = self._screen_geo()
                new_y = self._drag_start_y + delta.y()
                self._dock_y = max(sg.top(), min(new_y, sg.bottom() - self.GRABBER_H))
                
                # Instantly move without animating during drag
                self._set_collapsed_geo(animate=False)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self._is_dragging:
                sg = self._screen_geo()
                gpos = event.globalPosition().toPoint()
                self._edge = "left" if gpos.x() < sg.left() + sg.width() // 2 else "right"
                self._set_collapsed_geo()
                self._save_dock_position()
            self._drag_pos = None
            self._is_dragging = False

    def _save_dock_position(self):
        self._config["dock_edge"] = self._edge
        self._config["dock_y"] = self._dock_y

    # ── Paint ────────────────────────────────────────────────────────────────

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        if self._expanded:
            path = QPainterPath()
            r = self.rect().adjusted(1, 1, -1, -1)
            path.addRoundedRect(float(r.x()), float(r.y()), float(r.width()), float(r.height()), 10.0, 10.0)
            gradient = QLinearGradient(0, 0, self.width(), self.height())
            gradient.setColorAt(0.0, QColor(25, 30, 42, 252))
            gradient.setColorAt(1.0, QColor(10, 12, 17, 252))
            p.fillPath(path, QBrush(gradient))

            # Red accent on docked edge
            aw = 2
            if self._edge == "left":
                p.fillRect(0, 12, aw, self.height() - 24, QBrush(CLR_RED))
            else:
                p.fillRect(self.width() - aw, 12, aw, self.height() - 24, QBrush(CLR_RED))

            p.setPen(QPen(CLR_BORDER, 1.0))
            p.drawPath(path)
        else:
            # Collapsed grabber — round outer corners only
            gp = QPainterPath()
            if self._edge == "left":
                gp.moveTo(0, 0)
                gp.lineTo(float(self.GRABBER_W - 5), 0)
                gp.arcTo(float(self.GRABBER_W - 10), 0, 10, 10, 90, -90)
                gp.lineTo(float(self.GRABBER_W), float(self.GRABBER_H - 5))
                gp.arcTo(float(self.GRABBER_W - 10), float(self.GRABBER_H - 10), 10, 10, 0, -90)
                gp.lineTo(0, float(self.GRABBER_H))
                gp.closeSubpath()
            else:
                gp.moveTo(float(self.GRABBER_W), 0)
                gp.lineTo(5.0, 0)
                gp.arcTo(0, 0, 10, 10, 90, 90)
                gp.lineTo(0, float(self.GRABBER_H - 5))
                gp.arcTo(0, float(self.GRABBER_H - 10), 10, 10, 180, 90)
                gp.lineTo(float(self.GRABBER_W), float(self.GRABBER_H))
                gp.closeSubpath()

            gradient = QLinearGradient(0, 0, self.width(), 0)
            gradient.setColorAt(0.0, QColor(44, 51, 65, 240))
            gradient.setColorAt(1.0, QColor(18, 22, 31, 240))
            p.fillPath(gp, QBrush(gradient))

            # Add outline to grabber for visibility on dark backgrounds
            p.setPen(QPen(CLR_BORDER, 1.0))
            p.drawPath(gp)

            # Before first discovery, the complete affordance blinks on/off.
            # Once discovered (including while recording), lines stay steady.
            if self._is_first_launch and not self._blink_on:
                p.setPen(Qt.PenStyle.NoPen)
            elif self._is_first_launch:
                p.setPen(QPen(CLR_RED, 1.5))
            else:
                p.setPen(QPen(QColor(200, 200, 200, 160), 1.5))
            
            cx = self.GRABBER_W // 2
            cy = self.GRABBER_H // 2
            for dy in [-7, 0, 7]:
                p.drawLine(cx - 3, cy + dy, cx + 3, cy + dy)

            # Red dots (top and bottom)
            if self._is_recording:
                if self._pulse_visible:
                    p.setBrush(QColor(255, 59, 48))
                    p.setPen(Qt.PenStyle.NoPen)
                    p.drawEllipse(cx - 2, 6, 4, 4)
                    p.drawEllipse(cx - 2, self.GRABBER_H - 10, 4, 4)
            else:
                # Startup dots blink fully on/off at one constant size.
                if self._is_first_launch and self._blink_on:
                    p.setBrush(CLR_RED_HVR)
                    p.setPen(Qt.PenStyle.NoPen)
                    p.drawEllipse(cx - 2, 6, 4, 4)
                    p.drawEllipse(cx - 2, self.GRABBER_H - 10, 4, 4)
                elif not self._is_first_launch:
                    p.setBrush(CLR_RED)
                    p.setPen(Qt.PenStyle.NoPen)
                    p.drawEllipse(cx - 2, 6, 4, 4)
                    p.drawEllipse(cx - 2, self.GRABBER_H - 10, 4, 4)

        p.end()

    # ── Recording state ──────────────────────────────────────────────────────

    def set_recording_state(self, is_recording: bool):
        self._is_recording = is_recording
        hk = self._config.get("hotkey", "<shift>+<backspace>").replace("<", "").replace(">", "").title()
        
        if is_recording:
            # Starting an action also proves the user has discovered the app.
            self._acknowledge_startup_indicator()
            self._btn_record.setToolTip(f"Stop Recording ({hk})")
            stop_ico = _asset("stop.png")
            if os.path.isfile(stop_ico):
                self._btn_record.setIcon(QIcon(stop_ico))
            self._btn_record.setStyleSheet("""
                QToolButton { background: transparent; border: 2px solid #DC2626; border-radius: 12px; }
                QToolButton:hover { background: rgba(220,38,38,0.14); border-color: #EF4444; }
            """)
            self._pulse_timer.start()
        else:
            self._btn_record.setToolTip(f"Record ({hk})")
            rec_ico = _asset("record.png")
            if os.path.isfile(rec_ico):
                self._btn_record.setIcon(QIcon(rec_ico))
            self._btn_record.setStyleSheet("""
                QToolButton { background: transparent; border: 1px solid transparent; border-radius: 12px; }
                QToolButton:hover { background: #FF4055; border: 1px solid #FF6373; }
                QToolButton:pressed { background: #B91C1C; }
            """)
            self._pulse_timer.stop()
            self._pulse_visible = True
        self.update()

    def _pulse_tick(self):
        self._pulse_visible = not self._pulse_visible
        self.update()


# ─────────────────────────────────────────────────────────────────────────────
#  SidebarPanel (base)
# ─────────────────────────────────────────────────────────────────────────────

class SidebarPanel(QWidget):
    """
    Full-screen-height sidebar with WWRECORDER heading PNG and resizable width.
    Sidebars remain visible in captures; only the recording pill is excluded.
    """

    closed = pyqtSignal()
    width_changed = pyqtSignal(int)

    MIN_WIDTH = 300
    DEFAULT_WIDTH = 380
    MAX_WIDTH = 1200

    def __init__(self, edge: str = "right", close_on_focus_loss: bool = True, parent=None, font_size_mode="Default"):
        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        super().__init__(None, flags)

        self._edge = edge
        self._close_on_focus_loss = close_on_focus_loss
        self._font_size_mode = font_size_mode
        self._resizing = False
        self._resize_start_x = 0
        self._resize_start_w = 0

        # Calculate dynamic limits using screen proportions
        screen_geo = QApplication.primaryScreen().geometry()
        sw = screen_geo.width()
        
        # Max width is constrained so it doesn't get too wide and components look weird
        if font_size_mode == "Large":
            # Compact Large mode
            self.MIN_WIDTH = 480
            self.MAX_WIDTH = min(900, int(sw * 0.5))
            self.DEFAULT_WIDTH = self.MIN_WIDTH
        else:
            # Compact Default mode
            self.MIN_WIDTH = 380
            self.MAX_WIDTH = min(800, int(sw * 0.5))
            self.DEFAULT_WIDTH = self.MIN_WIDTH

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        if not self._close_on_focus_loss:
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        
        self.setAttribute(Qt.WidgetAttribute.WA_AlwaysShowToolTips)
        self.setMouseTracking(True)
        self.setMinimumWidth(self.MIN_WIDTH)
        self.setMaximumWidth(self.MAX_WIDTH)

    def set_close_on_focus_loss(self, enabled: bool):
        self._close_on_focus_loss = enabled

    def showEvent(self, event):
        super().showEvent(event)

    def changeEvent(self, event):
        if event.type() == QEvent.Type.ActivationChange:
            if not self.isActiveWindow() and self._close_on_focus_loss:
                # Use a small timer to prevent closing if a sub-dialog (like QFileDialog) is opened
                # although in this app we usually don't have sub-dialogs for the sidebar itself.
                QTimer.singleShot(100, self._check_should_close)
        super().changeEvent(event)

    def _check_should_close(self):
        if not self.isVisible() or not self._close_on_focus_loss:
            return
        
        active = QApplication.activeWindow()
        if active == self:
            return

        # Check if the active window is a child or descendant of this sidebar
        is_descendant = False
        if active:
            # Modal dialogs often have the sidebar as parent
            p = active
            while p:
                if p == self:
                    is_descendant = True
                    break
                try:
                    p = p.parent()
                except RuntimeError:
                    # Handle cases where the object might be being destroyed
                    p = None
        
        if not is_descendant and not self._resizing:
            self.close_panel()

    def _position_sidebar(self, width: int = 0):
        sg = QApplication.primaryScreen().availableGeometry()
        w = width or self.DEFAULT_WIDTH
        h = sg.height()

        # Flush to the screen edge
        if self._edge == "left":
            x = sg.left()
        else:
            x = sg.right() - w + 1

        y = sg.top()
        self.setFixedHeight(h)
        self.resize(w, h)
        self.move(x, y)

    def _build_heading(self, parent_layout: QVBoxLayout, extra_buttons: list = None):
        """Add the WWRECORDER heading image from icons folder."""
        heading_container = QWidget()
        heading_layout = QHBoxLayout(heading_container)
        heading_layout.setContentsMargins(0, 4, 0, 4)
        heading_layout.setSpacing(10)

        # Try to load the WWRECORDER PNG
        heading_path = _asset("wwrecorder.png")
        if os.path.isfile(heading_path):
            img_label = QLabel()
            px = QPixmap(heading_path)
            scaled = px.scaledToHeight(26, Qt.TransformationMode.SmoothTransformation)
            img_label.setPixmap(scaled)
            heading_layout.addWidget(img_label)
        else:
            lbl_ww = QLabel("WW")
            lbl_ww.setStyleSheet("color: #FFFFFF; font-size: 18px; font-weight: 900; font-family: 'Segoe UI Black', 'Impact';")
            heading_layout.addWidget(lbl_ww)
            lbl_r = QLabel("R")
            lbl_r.setStyleSheet("color: #DC2626; font-size: 18px; font-weight: 900; font-family: 'Segoe UI Black', 'Impact';")
            heading_layout.addWidget(lbl_r)
            lbl_rest = QLabel("ECORDER")
            lbl_rest.setStyleSheet("color: #FFFFFF; font-size: 18px; font-weight: 900; font-family: 'Segoe UI Black', 'Impact';")
            heading_layout.addWidget(lbl_rest)

        heading_layout.addStretch()

        # Optional extra buttons (e.g. settings gear in recent files)
        if extra_buttons:
            for btn in extra_buttons:
                heading_layout.addWidget(btn)

        # Close button
        btn_close = QPushButton("✕")
        btn_close.setFixedSize(26, 26)
        btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_close.setStyleSheet("""
            QPushButton {
                background: #262628; color: rgba(255,255,255,0.6); border: 1px solid #3C3C3E;
                border-radius: 13px; font-size: 11px; font-weight: 600;
            }
            QPushButton:hover { background: #DC2626; color: #FFFFFF; border-color: #EF4444; }
        """)
        btn_close.clicked.connect(self.close_panel)
        heading_layout.addWidget(btn_close)

        parent_layout.addWidget(heading_container)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background-color: #3C3C3E; max-height: 1px; border: none;")
        parent_layout.addWidget(sep)
        parent_layout.addSpacing(8)

    def open_panel(self):
        sg = QApplication.primaryScreen().availableGeometry()
        w = self.width() if self.width() >= self.MIN_WIDTH else self.DEFAULT_WIDTH
        h = sg.height()
        y = sg.top()

        if self._edge == "left":
            start_x = sg.left() - w
            end_x = sg.left()
        else:
            start_x = sg.right() + 1
            end_x = sg.right() - w + 1

        self.setGeometry(start_x, y, w, h)
        self.show()
        
        if self._close_on_focus_loss:
            self.activateWindow()
            self.raise_()

        self._anim = QPropertyAnimation(self, b"geometry")
        self._anim.setDuration(350)
        self._anim.setStartValue(QRect(start_x, y, w, h))
        self._anim.setEndValue(QRect(end_x, y, w, h))
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.start()

    def close_panel(self, animate=True):
        if not self.isVisible():
            return
            
        if not animate:
            self._finish_close()
            return
        
        sg = QApplication.primaryScreen().availableGeometry()
        w = self.width()
        h = sg.height()
        y = sg.top()
        
        if self._edge == "left":
            start_x = sg.left()
            end_x = sg.left() - w
        else:
            start_x = sg.right() - w + 1
            end_x = sg.right() + 1

        self._anim = QPropertyAnimation(self, b"geometry")
        self._anim.setDuration(300)
        self._anim.setStartValue(QRect(start_x, y, w, h))
        self._anim.setEndValue(QRect(end_x, y, w, h))
        self._anim.setEasingCurve(QEasingCurve.Type.InCubic)
        self._anim.finished.connect(self._finish_close)
        self._anim.start()

    def _finish_close(self):
        self.hide()
        self.closed.emit()

    # ── Resize by dragging inner edge ────────────────────────────────────────

    def _is_on_resize_edge(self, pos: QPoint) -> bool:
        margin = 6
        if self._edge == "right":
            return pos.x() <= margin
        else:
            return pos.x() >= self.width() - margin

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._is_on_resize_edge(event.pos()):
            self._resizing = True
            self._resize_start_x = event.globalPosition().toPoint().x()
            self._resize_start_w = self.width()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._resizing:
            dx = event.globalPosition().toPoint().x() - self._resize_start_x
            if self._edge == "right":
                new_w = self._resize_start_w - dx
            else:
                new_w = self._resize_start_w + dx
            new_w = max(self.MIN_WIDTH, min(new_w, self.MAX_WIDTH))
            self._position_sidebar(new_w)
            event.accept()
        elif self._is_on_resize_edge(event.pos()):
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._resizing:
            self._resizing = False
            self.width_changed.emit(self.width())
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    # ── Paint ────────────────────────────────────────────────────────────────

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        r = self.rect().adjusted(0, 0, 0, 0)

        # Only round corners on the inner edge (away from screen edge)
        if self._edge == "right":
            # Round left corners only
            path.moveTo(float(r.right()), float(r.top()))
            path.lineTo(float(r.left() + 12), float(r.top()))
            path.arcTo(float(r.left()), float(r.top()), 24, 24, 90, 90)
            path.lineTo(float(r.left()), float(r.bottom() - 12))
            path.arcTo(float(r.left()), float(r.bottom() - 24), 24, 24, 180, 90)
            path.lineTo(float(r.right()), float(r.bottom()))
            path.closeSubpath()
        else:
            # Round right corners only
            path.moveTo(float(r.left()), float(r.top()))
            path.lineTo(float(r.right() - 12), float(r.top()))
            path.arcTo(float(r.right() - 24), float(r.top()), 24, 24, 90, -90)
            path.lineTo(float(r.right()), float(r.bottom() - 12))
            path.arcTo(float(r.right() - 24), float(r.bottom() - 24), 24, 24, 0, -90)
            path.lineTo(float(r.left()), float(r.bottom()))
            path.closeSubpath()

        gradient = QLinearGradient(0, 0, self.width(), self.height())
        gradient.setColorAt(0.0, QColor(24, 29, 40, 252))
        gradient.setColorAt(0.55, QColor(13, 16, 23, 252))
        gradient.setColorAt(1.0, QColor(8, 10, 15, 252))
        p.fillPath(path, QBrush(gradient))
        p.setPen(QPen(QColor(255, 255, 255, 34), 1.0))
        p.drawPath(path)
        p.end()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close_panel()


# ─────────────────────────────────────────────────────────────────────────────
#  Settings UI Helpers
# ─────────────────────────────────────────────────────────────────────────────

class _SegmentedToggle(QWidget):
    valueChanged = pyqtSignal(str)
    
    def __init__(self, options: list[str], current: str, font_size_mode: str = "Default"):
        super().__init__()
        self._options = options
        self._current = current
        self._font_size_mode = font_size_mode
        self._buttons = {}
        
        self.setFixedSize(120, 24)
        
        # Outer container for the pill shape
        self.container = QFrame(self)
        self.container.setObjectName("container")
        self.container.setFixedSize(120, 24)
        self.container.setStyleSheet("""
            #container {
                background: #1C1C1E;
                border: 1px solid #3C3C3E;
                border-radius: 12px;
            }
        """)
        
        layout = QHBoxLayout(self.container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        for i, opt in enumerate(options):
            b = QPushButton(opt)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
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
        fs = 13 if getattr(self, "_font_size_mode", "Default") == "Large" else 11
        opts = list(self._options)
        for i, opt in enumerate(opts):
            b = self._buttons[opt]
            
            # Explicitly set each corner to match container pill shape
            tl = 11 if i == 0 else 0
            bl = 11 if i == 0 else 0
            tr = 11 if i == len(opts)-1 else 0
            br = 11 if i == len(opts)-1 else 0
            
            rad_style = f"border-top-left-radius: {tl}px; border-bottom-left-radius: {bl}px; border-top-right-radius: {tr}px; border-bottom-right-radius: {br}px;"
            
            if opt == self._current:
                b.setStyleSheet(f"""
                    QPushButton {{
                        background: #DC2626; color: #FFFFFF; font-weight: bold; font-family: 'Segoe UI'; font-size: {fs}px;
                        border: none; {rad_style}
                    }}
                """)
            else:
                b.setStyleSheet(f"""
                    QPushButton {{
                        background: transparent; color: rgba(255,255,255,0.6); font-family: 'Segoe UI'; font-size: {fs}px;
                        border: none; {rad_style}
                    }}
                    QPushButton:hover {{ background: rgba(255,255,255,0.05); color: #FFFFFF; }}
                """)

# ─────────────────────────────────────────────────────────────────────────────
#  Settings UI Helper Components
# ─────────────────────────────────────────────────────────────────────────────

class _SettingsCard(QFrame):
    def __init__(self, title=None, parent=None, font_size_mode="Default"):
        super().__init__(parent)
        self.setStyleSheet("""
            _SettingsCard {
                background: #151923; border: 1px solid #343B48;
                border-radius: 12px;
            }
        """)
        self._card_layout = QVBoxLayout(self)
        self._card_layout.setContentsMargins(12, 12, 12, 12)
        self._card_layout.setSpacing(12)
        if title:
            fs = 12 if font_size_mode == "Large" else 10
            lbl = QLabel(title.upper())
            lbl.setStyleSheet(f"color: #FF5264; font-size: {fs}px; font-weight: 800; letter-spacing: 0.8px; font-family: 'Segoe UI';")
            self._card_layout.addWidget(lbl)
            self._card_layout.addSpacing(4)

class _CollapsibleAccordion(QWidget):
    def __init__(self, title: str, parent=None, font_size_mode="Default", flat=False):
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

        fs = 13 if font_size_mode == "Large" else 11
        self.btn_toggle = QPushButton()
        self.btn_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_toggle.setFixedHeight(38 if font_size_mode == "Large" else 34)
        if flat:
            btn_style = f"""
                QPushButton {{
                    background: transparent; color: rgba(255,255,255,0.7);
                    border: none; border-radius: 4px;
                }}
                QPushButton:hover {{ background: rgba(255,255,255,0.05); color: #FFFFFF; }}
            """
        else:
            btn_style = f"""
                QPushButton {{
                    background: #18181A; color: rgba(255,255,255,0.7);
                    border: 1px solid #28282A; border-radius: 6px;
                }}
                QPushButton:hover {{ background: #202022; color: #FFFFFF; }}
            """
        self.btn_toggle.setStyleSheet(btn_style)
        
        btn_lay = QHBoxLayout(self.btn_toggle)
        btn_lay.setContentsMargins(12, 0, 12, 0)
        
        self.lbl_title = QLabel(title)
        self.lbl_title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.lbl_title.setStyleSheet(f"color: rgba(255,255,255,0.8); font-size: {fs}px; font-weight: bold; font-family: 'Segoe UI'; background: transparent;")
        
        self.lbl_arrow = QLabel()
        self.lbl_arrow.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.lbl_arrow.setFixedSize(12, 12)
        self.lbl_arrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._set_arrow_icon(expanded=False)
        
        btn_lay.addWidget(self.lbl_title)
        btn_lay.addStretch()
        btn_lay.addWidget(self.lbl_arrow)
        
        self.btn_toggle.clicked.connect(self.toggle)
        self._layout.addWidget(self.btn_toggle)

        self.content_area = QWidget()
        self.content_layout = QVBoxLayout(self.content_area)
        self.content_layout.setContentsMargins(8, 12, 8, 8)
        self.content_layout.setSpacing(12)
        self.content_area.setVisible(False)
        self.content_area.setMaximumHeight(0)
        self._layout.addWidget(self.content_area)
        self._expanded = False
        self._content_anim = QPropertyAnimation(self.content_area, b"maximumHeight", self)
        self._content_anim.setDuration(220)
        self._content_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._content_anim.finished.connect(self._on_animation_finished)

    def _set_arrow_icon(self, expanded: bool):
        """Use bundled arrow artwork instead of font-dependent glyphs."""
        path = _asset("spn_up.png" if expanded else "spn_down.png")
        pixmap = QPixmap(path)
        if not pixmap.isNull():
            self.lbl_arrow.setPixmap(pixmap.scaled(
                QSize(10, 10), Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))

    def addWidget(self, w):
        self.content_layout.addWidget(w)
        
    def addLayout(self, l):
        self.content_layout.addLayout(l)

    def addSpacing(self, s):
        self.content_layout.addSpacing(s)

    def toggle(self):
        self._content_anim.stop()
        self._expanded = not self._expanded
        if self._expanded:
            self.content_area.setVisible(True)
            self.content_area.setMaximumHeight(0)
            target = max(1, self.content_area.sizeHint().height())
            self._content_anim.setStartValue(0)
            self._content_anim.setEndValue(target)
            self._set_arrow_icon(expanded=True)
        else:
            self._content_anim.setStartValue(self.content_area.height())
            self._content_anim.setEndValue(0)
            self._set_arrow_icon(expanded=False)
        self._content_anim.start()

    def _on_animation_finished(self):
        if self._expanded:
            self.content_area.setMaximumHeight(16777215)
        else:
            self.content_area.setVisible(False)


# ─────────────────────────────────────────────────────────────────────────────
#  SettingsSidebar
# ─────────────────────────────────────────────────────────────────────────────

class _CreditRatingLink(QPushButton):
    """One footer slot, two links; never switch the target during interaction."""

    LINKS = (
        ("Made by akasumitlamba", "https://github.com/akasumitlamba", "Meet the developer on GitHub"),
        ("Rate us ★★★★★", "https://aka.ms/AA1364bx", "Enjoying WWRecorder? Leave a review on Microsoft Store."),
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self._index = 0
        self.setMinimumWidth(0)
        self.setFixedHeight(22)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("""
            QPushButton { color: #DC2626; background: transparent;
                border: 1px solid transparent; font-size: 11px; font-weight: 600; }
            QPushButton:hover { color: #F87171; }
            QPushButton:focus { border-color: #DC2626; border-radius: 4px; }
        """)
        self._opacity = QGraphicsOpacityEffect(self)
        self._opacity.setOpacity(1.0)
        self.setGraphicsEffect(self._opacity)
        self._animation = QSequentialAnimationGroup(self)
        for start, end in ((1.0, 0.0), (0.0, 1.0)):
            fade = QPropertyAnimation(self._opacity, b"opacity", self._animation)
            fade.setDuration(180)
            fade.setStartValue(start)
            fade.setEndValue(end)
            self._animation.addAnimation(fade)
        self._animation.animationAt(0).finished.connect(self._swap_link)
        self._cycle_timer = QTimer(self)
        self._cycle_timer.setInterval(6000)
        self._cycle_timer.timeout.connect(self._advance)
        self.clicked.connect(self._open_link)
        self._set_link()

    def _set_link(self):
        label, _, tooltip = self.LINKS[self._index]
        self.setText(label)
        self.setToolTip(tooltip)
        self.setAccessibleName(label)

    def _advance(self):
        if self.isVisible() and not (self.underMouse() or self.hasFocus()):
            self._animation.start()

    def _swap_link(self):
        if not (self.underMouse() or self.hasFocus()):
            self._index = (self._index + 1) % len(self.LINKS)
            self._set_link()

    def _open_link(self):
        webbrowser.open(self.LINKS[self._index][1])

    def showEvent(self, event):
        super().showEvent(event)
        self._cycle_timer.start()

    def hideEvent(self, event):
        self._cycle_timer.stop()
        self._animation.stop()
        self._opacity.setOpacity(1.0)
        super().hideEvent(event)


class SettingsSidebar(SidebarPanel):
    """Full settings panel in a sidebar, matching the old SettingsWindow features."""

    settings_saved = pyqtSignal(dict)
    files_requested = pyqtSignal()
    quit_requested = pyqtSignal()
    manual_update_check_requested = pyqtSignal()
    manual_update_check_finished = pyqtSignal(bool, str, str, str)
    font_size_changed = pyqtSignal(str)

    def __init__(self, config: dict, default_config: dict = None, edge: str = "right"):
        fs_mode = config.get("font_size", "Default")
        super().__init__(edge, config.get("close_on_focus_loss", True), font_size_mode=fs_mode)
        self._config = config.copy()
        self._default_config = default_config or {}
        self._update_status = {"available": False, "version": "", "url": "", "download_url": ""}
        self._updater = None
        self._build_ui()
        _set_explicit_tab_chain(self)
        self._position_sidebar()

    def _build_ui(self):
        fs_mode = self._config.get("font_size", "Default")
        f_small = 10 if fs_mode == "Default" else 12
        f_norm = 11 if fs_mode == "Default" else 13
        f_med = 12 if fs_mode == "Default" else 14
        f_large = 13 if fs_mode == "Default" else 15

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 6)
        root.setSpacing(0)

        # Recent files folder button for heading bar
        btn_files = QPushButton()
        btn_files.setToolTip("Recent Files")
        btn_files.setFixedSize(26, 26)
        btn_files.setCursor(Qt.CursorShape.PointingHandCursor)
        files_ico = _asset("folder.png")
        if os.path.isfile(files_ico):
            btn_files.setIcon(QIcon(files_ico))
            btn_files.setIconSize(QSize(14, 14))
        btn_files.setStyleSheet("""
            QPushButton {
                background: #262628; border: 1px solid #3C3C3E;
                border-radius: 13px;
            }
            QPushButton:hover { background: #DC2626; border-color: #EF4444; }
        """)
        btn_files.clicked.connect(self.files_requested.emit)

        self._build_heading(root, extra_buttons=[btn_files])

        # Scrollable content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("""
            QScrollArea { background: transparent; border: none; }
            QScrollBar:vertical { background: transparent; width: 5px; }
            QScrollBar::handle:vertical { background: rgba(220,38,38,0.4); border-radius: 2px; min-height: 20px; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
        """)

        content = QWidget()
        content.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(content)
        lay.setContentsMargins(0, 4, 6, 2)
        lay.setSpacing(16)

        # ── Card 1: Capture & Output ─────────────────────────────────────────
        card_capture = _SettingsCard("CAPTURE & OUTPUT")
        lay.addWidget(card_capture)

        folder_row = QHBoxLayout()
        folder_row.setSpacing(8)
        self._edt_folder = QLineEdit(self._config.get("output_folder", ""))
        self._edt_folder.setReadOnly(True)
        self._edt_folder.setMinimumHeight(32)
        self._edt_folder.setStyleSheet(f"""
            QLineEdit {{
                background: #0B0E14; border: 1px solid #343B48; border-radius: 8px;
                padding: 0 10px; color: #FFFFFF; font-size: {f_norm}px; font-family: 'Segoe UI';
            }}
        """)
        folder_row.addWidget(self._edt_folder)

        btn_browse = QPushButton("Browse")
        btn_browse.setFixedSize(60, 32)
        btn_browse.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_browse.setStyleSheet(f"""
            QPushButton {{
                background: #242B39; color: #FFFFFF; border: 1px solid #424B5D;
                border-radius: 8px; font-size: {f_norm}px; font-weight: 700;
            }}
            QPushButton:hover {{ background: #DC2626; border-color: #EF4444; }}
        """)
        btn_browse.clicked.connect(self._browse)
        folder_row.addWidget(btn_browse)
        card_capture._card_layout.addLayout(folder_row)
        
        self._chk_clip = self._add_toggle(card_capture._card_layout, "Auto-copy captures to clipboard", self._config.get("copy_to_clipboard", True))

        # ── Card 2: Audio Setting ────────────────────────────────────────────
        card_audio = _SettingsCard("AUDIO DEFAULTS", font_size_mode=fs_mode)
        lay.addWidget(card_audio)
        self._chk_sys = self._add_toggle(card_audio._card_layout, "Record system sound by default", self._config.get("default_system_audio", False))
        self._chk_mic = self._add_toggle(card_audio._card_layout, "Record mic audio by default", self._config.get("default_mic", False))

        # ── Card 3: Hotkeys ─────────────────────────────────────────────────
        card_hk = _SettingsCard("SHORTCUTS", font_size_mode=fs_mode)
        lay.addWidget(card_hk)
        
        hk_row2 = QHBoxLayout()
        lbl_s = QLabel("Screenshot:")
        lbl_s.setFixedWidth(80)
        lbl_s.setStyleSheet(f"color: #FFFFFF; font-size: {f_med}px; font-family: 'Segoe UI';")
        hk_row2.addWidget(lbl_s)
        self._edt_screenshot = _HotkeyInput(self._config.get("hotkey_screenshot", "<ctrl>+<alt>+c"))
        hk_row2.addWidget(self._edt_screenshot, 1)
        card_hk._card_layout.addLayout(hk_row2)

        hk_row = QHBoxLayout()
        lbl_r = QLabel("Recording:")
        lbl_r.setFixedWidth(80)
        lbl_r.setStyleSheet(f"color: #FFFFFF; font-size: {f_med}px; font-family: 'Segoe UI';")
        hk_row.addWidget(lbl_r)
        self._edt_hotkey = _HotkeyInput(self._config.get("hotkey", "<shift>+<backspace>"))
        hk_row.addWidget(self._edt_hotkey, 1)
        card_hk._card_layout.addLayout(hk_row)

        # ── Advanced Settings (Card + Accordion) ──────────────────────────────
        card_adv = _SettingsCard(None, font_size_mode=fs_mode)
        lay.addWidget(card_adv)
        
        adv_sec = _CollapsibleAccordion("Advanced Settings", font_size_mode=fs_mode, flat=True)
        card_adv._card_layout.addWidget(adv_sec)

        self._chk_boot = self._add_toggle(adv_sec.content_layout, "Start WWRecorder with Windows", self._config.get("start_on_boot", False))
        self._chk_autoclose = self._add_toggle(adv_sec.content_layout, "Auto-close sidebar on focus loss", self._config.get("close_on_focus_loss", True))

        row_app = QHBoxLayout()
        row_app.setContentsMargins(0, 0, 0, 0)
        lbl_app = QLabel("UI Font Size")
        lbl_app.setStyleSheet(f"color: rgba(255,255,255,0.85); font-size: {f_med}px; font-family: 'Segoe UI';")
        row_app.addWidget(lbl_app, 1)
        self._seg_font = _SegmentedToggle(["Default", "Large"], self._config.get("font_size", "Default"), font_size_mode=fs_mode)
        self._seg_font.valueChanged.connect(self._check_dirty)
        row_app.addWidget(self._seg_font)
        adv_sec.addLayout(row_app)
        
        # System/Updates inside Advanced
        ver_row = QHBoxLayout()
        ver_row.setContentsMargins(0, 10, 0, 0)
        full_version = str(self._config.get("current_version", "1.2.0"))
        display_version = ".".join(full_version.split(".")[:2])
        self._lbl_version = QLabel(f"Version {display_version}")
        self._lbl_version.setStyleSheet(f"color: rgba(255,255,255,0.6); font-size: {f_med}px; font-family: 'Segoe UI';")
        ver_row.addWidget(self._lbl_version, 1)
        
        self._btn_check_update = QPushButton("Check for Updates")
        self._btn_check_update.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_check_update.setMinimumWidth(110)
        self._btn_check_update.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: #DC2626; border: 1px solid #DC2626;
                border-radius: 4px; padding: 4px 10px; font-size: {f_norm}px; font-weight: 700;
            }}
            QPushButton:hover {{ background: rgba(220,38,38,0.1); }}
            QPushButton:disabled {{ color: rgba(255,255,255,0.4); border: 1px solid rgba(255,255,255,0.1); background: transparent; }}
        """)
        self._btn_check_update.clicked.connect(self._on_check_updates)
        ver_row.addWidget(self._btn_check_update)
        adv_sec.addLayout(ver_row)

        self._chk_developer_mode = self._add_toggle(
            adv_sec.content_layout, "Developer mode", self._config.get("developer_mode", False)
        )

        self._dev_mode_details = QFrame()
        self._dev_mode_details.setMinimumWidth(0)
        self._dev_mode_details.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        dev_details_layout = QVBoxLayout(self._dev_mode_details)
        dev_details_layout.setContentsMargins(0, 4, 0, 2)
        dev_details_layout.setSpacing(8)
        self._lbl_dev_mode_info = QLabel(
            "Use GitHub Releases to test preview builds. Normal app updates still "
            "come from Microsoft Store."
        )
        self._lbl_dev_mode_info.setWordWrap(True)
        self._lbl_dev_mode_info.setMinimumWidth(0)
        self._lbl_dev_mode_info.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        self._lbl_dev_mode_info.setStyleSheet(
            f"color: rgba(255,255,255,0.62); font-size: {f_small}px; "
            "line-height: 1.35; font-family: 'Segoe UI';"
        )
        dev_details_layout.addWidget(self._lbl_dev_mode_info)

        self._btn_dev_releases = QPushButton("GitHub Releases")
        self._btn_dev_releases.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_dev_releases.setMinimumWidth(0)
        self._btn_dev_releases.setMinimumHeight(34)
        self._btn_dev_releases.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._btn_dev_releases.setToolTip("Open the WWRecorder GitHub Releases page")
        self._btn_dev_releases.clicked.connect(
            lambda: webbrowser.open("https://github.com/akasumitlamba/WWRecorder/releases")
        )
        dev_details_layout.addWidget(self._btn_dev_releases)
        self._dev_mode_details.setVisible(self._chk_developer_mode.isChecked())
        self._chk_developer_mode.toggled.connect(self._dev_mode_details.setVisible)
        adv_sec.addWidget(self._dev_mode_details)

        self._lbl_update_status = QLabel("")
        self._lbl_update_status.setVisible(False)
        adv_sec.addWidget(self._lbl_update_status)

        # Push everything below this to the bottom of the scroll area
        lay.addStretch()
        
        lay.addSpacing(16)

        # Old Share Widget removed

        # Credits (Bottom Aligned) moved below buttons

        # ── Quit & Save Bottom Area ──────────────────────────────────────────
        bot_lay = QVBoxLayout()
        bot_lay.setContentsMargins(0, 0, 0, 0)
        bot_lay.setSpacing(0)

        self._btn_save = QPushButton("Save Settings")
        self._btn_save.setFixedHeight(34)
        self._btn_save.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_save.clicked.connect(self._save)
        bot_lay.addWidget(self._btn_save)

        row2 = QHBoxLayout()
        row2.setContentsMargins(0, 0, 0, 0)
        row2.setSpacing(10)

        self._btn_quit = QPushButton("⏻  Quit App")
        self._btn_quit.setFixedHeight(34)
        self._btn_quit.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_quit.setStyleSheet(f"""
            QPushButton {{
                background: #1C1C1E; border: 1px solid #3C3C3E; border-radius: 6px;
                color: #EF4444; font-size: {f_med}px; font-weight: 600; font-family: 'Segoe UI';
            }}
            QPushButton:hover {{ background: #DC2626; color: #FFFFFF; border-color: #EF4444; }}
        """)
        self._btn_quit.clicked.connect(self.quit_requested.emit)
        row2.addWidget(self._btn_quit, 1)

        self._btn_share = QPushButton()
        self._btn_share.setFixedSize(34, 34)
        self._btn_share.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_share.setToolTip("Share WWRecorder")
        self._btn_share.setIcon(self._get_share_icon())
        self._btn_share.setIconSize(QSize(18, 18))
        self._btn_share.setStyleSheet(f"""
            QPushButton {{
                background: #1C1C1E; border: 1px solid #3C3C3E; border-radius: 6px;
            }}
            QPushButton:hover {{ background: #2D2D30; border-color: #5C5C5E; }}
        """)
        self._btn_share.clicked.connect(self._on_share)
        row2.addWidget(self._btn_share)

        self._btn_reset = QPushButton("↺  Reset")
        self._btn_reset.setFixedHeight(34)
        self._btn_reset.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_reset.setStyleSheet(f"""
            QPushButton {{
                background: #1C1C1E; border: 1px solid #3C3C3E; border-radius: 6px;
                color: #A0A0A5; font-size: {f_med}px; font-weight: 600; font-family: 'Segoe UI';
                padding-bottom: 2px;
            }}
            QPushButton:hover {{ background: #5C5C5E; color: #FFFFFF; }}
        """)
        self._btn_reset.clicked.connect(self._reset)
        row2.addWidget(self._btn_reset, 1)

        bot_lay.addSpacing(10)
        bot_lay.addLayout(row2)
        # Keep the one-line footer inside the button group so the main card
        # spacing cannot accumulate above and below it.
        self._credit_link = _CreditRatingLink()
        bot_lay.addSpacing(4)
        bot_lay.addWidget(self._credit_link)
        lay.addLayout(bot_lay)

        # Connect signals for dirty checking
        self._edt_folder.textChanged.connect(self._check_dirty)
        self._edt_hotkey.textChanged.connect(self._check_dirty)
        self._edt_screenshot.textChanged.connect(self._check_dirty)
        self._chk_sys.toggled.connect(self._check_dirty)
        self._chk_mic.toggled.connect(self._check_dirty)
        self._chk_boot.toggled.connect(self._check_dirty)
        self._chk_clip.toggled.connect(self._check_dirty)
        self._chk_autoclose.toggled.connect(self._check_dirty)
        self._chk_developer_mode.toggled.connect(self._check_dirty)
        self._seg_font.valueChanged.connect(self._check_dirty)
        self._check_dirty()

        scroll.setWidget(content)
        root.addWidget(scroll, 1)

    def _check_dirty(self, *_):
        dirty = (
            self._edt_folder.text() != self._config.get("output_folder", "") or
            self._edt_hotkey.text() != self._config.get("hotkey", "") or
            self._edt_screenshot.text() != self._config.get("hotkey_screenshot", "") or
            self._chk_sys.isChecked() != self._config.get("default_system_audio", False) or
            self._chk_mic.isChecked() != self._config.get("default_mic", False) or
            self._chk_boot.isChecked() != self._config.get("start_on_boot", False) or
            self._chk_clip.isChecked() != self._config.get("copy_to_clipboard", True) or
            self._chk_autoclose.isChecked() != self._config.get("close_on_focus_loss", True) or
            self._chk_developer_mode.isChecked() != self._config.get("developer_mode", False) or
            self._seg_font.value() != self._config.get("font_size", "Default")
        )
        self._btn_save.setEnabled(dirty)
        if dirty:
            fs = 14 if self._config.get("font_size") == "Large" else 13
            self._btn_save.setStyleSheet(f"""
                QPushButton {{
                    background: #DC2626; border: 1px solid #EF4444; border-radius: 6px;
                    color: #FFFFFF; font-size: {fs}px; font-weight: 600; font-family: 'Segoe UI';
                }}
                QPushButton:hover {{ background: #B91C1C; }}
            """)
        else:
            fs = 14 if self._config.get("font_size") == "Large" else 13
            self._btn_save.setStyleSheet(f"""
                QPushButton {{
                    background: #2D2D30; border: 1px solid #3C3C3E; border-radius: 6px;
                    color: rgba(255,255,255,0.4); font-size: {fs}px; font-weight: 500; font-family: 'Segoe UI';
                }}
            """)

    def _add_section_title(self, parent_layout, text: str):
        fs = 12 if self._config.get("font_size") == "Large" else 10
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color: rgba(255,255,255,0.4); font-size: {fs}px; font-weight: 700; letter-spacing: 1.5px; font-family: 'Segoe UI';")
        parent_layout.addWidget(lbl)

    def _add_toggle(self, parent_layout, label: str, checked: bool) -> _RedToggle:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        lbl = QLabel(label)
        fs = 14 if self._config.get("font_size") == "Large" else 12
        lbl.setStyleSheet(f"color: rgba(255,255,255,0.85); font-size: {fs}px; font-family: 'Segoe UI';")
        row.addWidget(lbl, 1)
        toggle = _RedToggle()
        toggle.setChecked(checked)
        row.addWidget(toggle)
        parent_layout.addLayout(row)
        return toggle

    def _browse(self):
        # BUG-015: Temporarily suppress focus-loss auto-close during native file dialog
        old_close = self._close_on_focus_loss
        self._close_on_focus_loss = False
        try:
            folder = QFileDialog.getExistingDirectory(self, "Select Output Folder", self._edt_folder.text())
            if folder:
                self._edt_folder.setText(folder)
        finally:
            self._close_on_focus_loss = old_close
            self.activateWindow()
            self.raise_()

    def _on_font_toggle_changed(self, mode: str):
        self._save()
        self.font_size_changed.emit(mode)

    def _save(self):
        from main import validate_hotkey
        for label, value in (
            ("Recording", self._edt_hotkey.text()),
            ("Screenshot", self._edt_screenshot.text()),
        ):
            valid, reason = validate_hotkey(value)
            if not valid:
                QMessageBox.warning(self, "Invalid Shortcut", f"{label} shortcut was not saved.\n\n{reason}")
                return
        if self._edt_hotkey.text() == self._edt_screenshot.text():
            QMessageBox.warning(self, "Shortcut Conflict", "Recording and Screenshot must use different shortcuts.")
            return
        self._config.update({
            "output_folder":        self._edt_folder.text(),
            "hotkey":               self._edt_hotkey.text(),
            "hotkey_screenshot":    self._edt_screenshot.text(),
            "default_system_audio": self._chk_sys.isChecked(),
            "default_mic":          self._chk_mic.isChecked(),
            "start_on_boot":        self._chk_boot.isChecked(),
            "copy_to_clipboard":    self._chk_clip.isChecked(),
            "close_on_focus_loss":  self._chk_autoclose.isChecked(),
            "developer_mode":       self._chk_developer_mode.isChecked(),
            "font_size":            self._seg_font.value(),
        })
        self.settings_saved.emit(self._config)
        # Update dirty state to reflect saved values (sidebar stays open)
        self._check_dirty()

    def _reset(self):
        if not self._default_config: return
        self._edt_folder.setText(self._default_config.get("output_folder", ""))
        self._edt_hotkey.setText(self._default_config.get("hotkey", ""))
        self._edt_screenshot.setText(self._default_config.get("hotkey_screenshot", ""))
        self._chk_sys.setChecked(self._default_config.get("default_system_audio", False))
        self._chk_mic.setChecked(self._default_config.get("default_mic", False))
        self._chk_boot.setChecked(self._default_config.get("start_on_boot", False))
        self._chk_clip.setChecked(self._default_config.get("copy_to_clipboard", True))
        self._chk_autoclose.setChecked(self._default_config.get("close_on_focus_loss", True))
        self._chk_developer_mode.setChecked(self._default_config.get("developer_mode", False))
        self._seg_font.setValue(self._default_config.get("font_size", "Default"))
        # setValue() is intentionally silent for programmatic initialization;
        # Reset is a user action and must still update the Save button.
        self._check_dirty()

    def get_config(self) -> dict:
        return self._config

    def set_update_status(self, available: bool, version: str, url: str, download_url: str = ""):
        self._update_status = {"available": available, "version": version, "url": url, "download_url": download_url}
        if available:
            self._btn_check_update.setText("Open Microsoft Store")
            self._btn_check_update.setToolTip(f"Update to {version} through Microsoft Store.")
            self._btn_check_update.setStyleSheet("""
                QPushButton {
                    background: #DC2626; color: #FFFFFF; border: none;
                    border-radius: 4px; padding: 4px 10px; font-size: 11px; font-weight: 800;
                }
                QPushButton:hover { background: #B91C1C; }
            """)
            # BUG-022: Show update status label
            self._lbl_update_status.setText(f"New version {version} available!")
            self._lbl_update_status.setStyleSheet("color: #22C55E; font-size: 11px; font-family: 'Segoe UI';")
            self._lbl_update_status.setVisible(True)
            # Store-first update path: never download or launch a GitHub EXE.
            self._btn_check_update.clicked.disconnect()
            self._btn_check_update.clicked.connect(self._on_update_now)
        else:
            from main import APP_VERSION
            self._btn_check_update.setText(f"v{APP_VERSION} Latest")
            self._btn_check_update.setEnabled(False)
            self._btn_check_update.setStyleSheet("""
                QPushButton {
                    background: #22C55E; color: #000000; border: none;
                    border-radius: 4px; padding: 4px 12px; font-size: 11px; font-weight: 800;
                }
            """)
            self._lbl_update_status.setText("You're on the latest version.")
            self._lbl_update_status.setStyleSheet("color: rgba(255,255,255,0.4); font-size: 11px; font-family: 'Segoe UI';")
            self._lbl_update_status.setVisible(True)

    def _on_check_updates(self):
        if self._updater and self._updater.isRunning():
            return
        self._btn_check_update.setEnabled(False)
        self._btn_check_update.setText("Checking...")
        from main import APP_VERSION
        self._updater = UpdateChecker(APP_VERSION)
        _ACTIVE_UPDATE_THREADS.add(self._updater)
        self._updater.finished.connect(
            lambda worker=self._updater: _ACTIVE_UPDATE_THREADS.discard(worker)
        )
        self._updater.check_finished.connect(self._on_manual_check_finished)
        self._updater.check_failed.connect(self._on_manual_check_failed)
        self._updater.start()

    def _on_manual_check_finished(self, available: bool, version: str, url: str, download_url: str = ""):
        self.set_update_status(available, version, url, download_url)
        self.manual_update_check_finished.emit(available, version, url, download_url)

    def _on_manual_check_failed(self, message: str):
        self.set_update_error(message)

    def set_update_error(self, message: str):
        self._btn_check_update.setEnabled(True)
        self._btn_check_update.setText("Try Update Check Again")
        self._lbl_update_status.setText(message)
        self._lbl_update_status.setStyleSheet("color: #FCA5A5; font-size: 11px; font-family: 'Segoe UI';")
        self._lbl_update_status.setWordWrap(True)
        self._lbl_update_status.setVisible(True)

    def _on_update_now(self):
        target = self._update_status.get("url") or "https://aka.ms/AA1364bx"
        webbrowser.open(target)
    def _on_share(self):
        # Create a premium share menu
        from PyQt6.QtWidgets import QMenu
        from PyQt6.QtGui import QAction
        
        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{
                background: #1C1C1E; border: 1px solid #3C3C3E; border-radius: 6px;
                color: #FFFFFF; padding: 4px; font-family: 'Segoe UI';
            }}
            QMenu::item {{
                padding: 8px 24px 8px 12px; border-radius: 4px;
                font-size: 13px;
            }}
            QMenu::item:selected {{
                background: #DC2626; color: #FFFFFF;
            }}
            QMenu::icon {{
                padding-left: 10px;
            }}
        """)
        
        # Helper to draw SVG-like icons
        def create_icon(icon_type):
            pm = QPixmap(32, 32)
            pm.fill(Qt.GlobalColor.transparent)
            p = QPainter(pm)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setPen(QPen(QColor("#FFFFFF"), 2.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            if icon_type == "copy":
                p.drawRoundedRect(6, 11, 13, 15, 2, 2)
                p.drawPath(self._get_copy_overlay_path())
            elif icon_type == "web":
                p.drawEllipse(6, 6, 20, 20)
                p.drawLine(6, 16, 26, 16)
                p.drawEllipse(11, 6, 10, 20)
            p.end()
            return QIcon(pm)

        copy_action = QAction(create_icon("copy"), "Copy App Link", self)
        copy_action.triggered.connect(self._copy_link)
        menu.addAction(copy_action)
        
        web_action = QAction(create_icon("web"), "Open Website", self)
        web_action.triggered.connect(lambda: webbrowser.open("https://akasumitlamba.github.io/WWRecorder/"))
        menu.addAction(web_action)
        
        # Position menu above the button
        pos = self._btn_share.mapToGlobal(QPoint(0, 0))
        menu.exec(QPoint(pos.x() - 100, pos.y() - menu.sizeHint().height() - 5))

    def _get_copy_overlay_path(self):
        from PyQt6.QtGui import QPainterPath
        path = QPainterPath()
        path.moveTo(13, 11)
        path.lineTo(13, 8)
        path.arcTo(13, 6, 4, 4, 180, -90)
        path.lineTo(24, 6)
        path.arcTo(22, 6, 4, 4, 90, -90)
        path.lineTo(26, 17)
        path.arcTo(22, 17, 4, 4, 0, -90)
        path.lineTo(19, 21)
        return path

    def _copy_link(self):
        url = "https://aka.ms/AA1364bx"
        QApplication.clipboard().setText(url)
        QToolTip.showText(QCursor.pos() + QPoint(10, 16), "Link copied to clipboard!", self._btn_share)

    def _get_share_icon(self):
        pm = QPixmap(32, 32)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(255, 255, 255, 220)
        p.setPen(QPen(color, 2.0, Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.setBrush(color)
        p.drawEllipse(21, 7, 5, 5)
        p.drawEllipse(6, 14, 5, 5)
        p.drawEllipse(21, 21, 5, 5)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawLine(10, 15, 22, 10)
        p.drawLine(10, 18, 22, 23)
        p.end()
        return QIcon(pm)

# ─────────────────────────────────────────────────────────────────────────────
#  _FileRow + Thumbnail Extraction
# ─────────────────────────────────────────────────────────────────────────────

class _ThumbSignals(QObject):
    loaded = pyqtSignal(bytes, str)

class _VideoThumbnailTask(QRunnable):
    def __init__(self, filepath: str, signal: pyqtSignal):
        super().__init__()
        self.filepath = filepath
        self.signal = signal

    def run(self):
        try:
            from recorder import get_ffmpeg_path
            ffmpeg = get_ffmpeg_path()
            ffprobe = ffmpeg.replace('ffmpeg', 'ffprobe')
            flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            
            dur_str = ""
            try:
                # 1. Get duration (Try ffprobe first, if available)
                dur_cmd = [
                    ffprobe, "-v", "error", "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1", self.filepath
                ]
                dur_res = subprocess.run(dur_cmd, capture_output=True, text=True, creationflags=flags, timeout=10)
                if dur_res.stdout.strip():
                    s = float(dur_res.stdout.strip())
                    m, s = divmod(int(s), 60)
                    h, m = divmod(m, 60)
                    dur_str = f"{h}:{m:02d}:{s:02d}" if h > 0 else f"{m}:{s:02d}"
            except Exception:
                pass

            if not dur_str:
                # Fallback to ffmpeg if ffprobe is missing
                try:
                    ffmpeg_dur_cmd = [ffmpeg, "-i", self.filepath]
                    res2 = subprocess.run(ffmpeg_dur_cmd, capture_output=True, text=True, creationflags=flags, timeout=10)
                    # ffmpeg prints info to stderr
                    import re
                    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+)\.\d+", res2.stderr)
                    if match:
                        h, m, s = int(match.group(1)), int(match.group(2)), int(match.group(3))
                        dur_str = f"{h}:{m:02d}:{s:02d}" if h > 0 else f"{m}:{s:02d}"
                except Exception:
                    pass

            # 2. Grab a tiny jpeg of the very first frame quickly
            cmd = [
                ffmpeg, "-y", "-v", "quiet", "-ss", "00:00:00.000", "-i", self.filepath,
                "-vframes", "1", "-f", "image2pipe", "-vcodec", "mjpeg",
                "-vf", "scale=-1:80", "-"
            ]
            res = subprocess.run(cmd, capture_output=True, check=True, creationflags=flags, timeout=15)
            if res.stdout:
                # Update Cache
                _cache_thumbnail(self.filepath, (os.path.getmtime(self.filepath), res.stdout, dur_str))
                self.signal.emit(res.stdout, dur_str)
        except Exception:
            pass

class _FileRow(QWidget):
    """A single row in the recent files list."""

    open_requested     = pyqtSignal(str)
    rename_requested   = pyqtSignal(str, str)
    delete_requested   = pyqtSignal(str)
    annotate_requested = pyqtSignal(str)
    play_video_requested = pyqtSignal(str)
    edit_requested     = pyqtSignal(str)

    def __init__(self, filepath: str, font_size_mode: str = "Default", parent=None, defer_load=False):
        super().__init__(parent)
        self._filepath = filepath
        self._font_size_mode = font_size_mode
        self._is_renaming = False
        self._drag_start_pos = None
        self._loaded = False
        h = 68 if font_size_mode == "Large" else 54
        self.setFixedHeight(h)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._build_ui()
        if not defer_load:
            self.load_content()

    @property
    def filename(self) -> str:
        return Path(self._filepath).name

    def _build_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(10)

        # Thumbnail Placeholder
        self._thumb = QLabel()
        if self._font_size_mode == "Large":
            self._thumb.setFixedSize(80, 60)
        else:
            self._thumb.setFixedSize(60, 45)
        self._thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._thumb.setStyleSheet("background: rgba(255,255,255,0.045); border: 1px solid rgba(255,255,255,0.08); border-radius: 7px;")
        layout.addWidget(self._thumb)

        info = QVBoxLayout()
        info.setSpacing(2)
        info.setContentsMargins(4, 0, 0, 0)

        fs_name = "16px" if self._font_size_mode == "Large" else "13px"
        fs_meta = "14px" if self._font_size_mode == "Large" else "11px"
        self._rename_h = 26 if self._font_size_mode == "Large" else 22
        
        fname = Path(self._filepath).name
        self._lbl_name = QLabel(fname)
        self._lbl_name.setStyleSheet(f"color: #F7F7FA; font-size: {fs_name}; font-weight: 600; font-family: 'Segoe UI';")
        self._lbl_name.setToolTip(fname)
        self._lbl_name.setMinimumWidth(10)
        self._lbl_name.setSizePolicy(QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.Preferred)
        info.addWidget(self._lbl_name)

        # Inline rename
        self._rename_edit = _RenameLineEdit()
        self._rename_edit.setVisible(False)
        self._rename_edit.setStyleSheet(f"""
            QLineEdit {{
                background: #1C1C1E; border: 1px solid #DC2626; border-radius: 4px;
                color: #FFFFFF; font-size: {fs_meta}; padding: 2px 6px;
            }}
        """)
        self._rename_edit.returnPressed.connect(self._finish_rename)
        self._rename_edit.editingFinished.connect(self._finish_rename)
        self._rename_edit.cancel_requested.connect(self._cancel_rename)
        info.addWidget(self._rename_edit)

        try:
            st = os.stat(self._filepath)
            mt = datetime.fromtimestamp(st.st_mtime)
            
            # Formulate file size suffix
            size_mb = st.st_size / (1024 * 1024)
            if size_mb >= 1.0:
                self._size_str = f"{size_mb:.1f} MB"
            else:
                size_kb = st.st_size / 1024
                self._size_str = f"{size_kb:.0f} KB"
                
            date_str = mt.strftime('%b %d, %Y  •  %I:%M %p')
        except Exception:
            self._size_str = ""
            date_str = ""
            
        meta_row = QHBoxLayout()
        meta_row.setSpacing(8)
        
        # Metadata Item: File Size (No box, bold)
        self._lbl_size_text = QLabel(self._size_str)
        self._lbl_size_text.setStyleSheet(f"color: rgba(255, 255, 255, 0.45); font-size: {int(fs_meta[:-2])-1}px; font-weight: 800; font-family: 'Segoe UI';")
        if not self._size_str: self._lbl_size_text.setVisible(False)
        meta_row.addWidget(self._lbl_size_text)


        
        self._lbl_date = QLabel(date_str)
        self._lbl_date.setStyleSheet(f"color: rgba(255,255,255,0.45); font-size: {fs_meta}; font-family: 'Segoe UI';")
        meta_row.addWidget(self._lbl_date)
        meta_row.addStretch()
        
        info.addLayout(meta_row)
        info.addStretch()
        layout.addLayout(info, 1)

        self._btn_menu = self._icon_btn("", "More actions")
        self._btn_menu.setText("")
        dots = QPixmap(24, 24)
        dots.fill(Qt.GlobalColor.transparent)
        dots_painter = QPainter(dots)
        dots_painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        dots_painter.setPen(Qt.PenStyle.NoPen)
        dots_painter.setBrush(QColor(255, 255, 255, 225))
        for y in (2, 10, 18):
            dots_painter.drawEllipse(10, y, 5, 5)
        dots_painter.end()
        self._menu_dots_icon = QIcon(dots)
        self._btn_menu.setIcon(self._menu_dots_icon)
        self._btn_menu.setIconSize(QSize(24, 24))
        self._btn_menu.clicked.connect(self._show_actions_menu)
        layout.addWidget(self._btn_menu)

        self.setStyleSheet("""
            _FileRow { background: #131721; border: 1px solid #292F3B; border-radius: 10px; }
            _FileRow:hover { background: #1B2130; border-color: #FF4055; }
        """)

    def load_content(self):
        """Perform the actual loading of thumbnails and duration."""
        if self._loaded: return
        self._loaded = True

        ext = Path(self._filepath).suffix.lower()
        if ext in (".png", ".jpg", ".jpeg"):
            px = QPixmap(self._filepath)
            if not px.isNull():
                self._thumb.setPixmap(px.scaled(self._thumb.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
                self._thumb.setStyleSheet("background: #000000; border-radius: 4px; border: 1px solid #333;")
            else:
                self._thumb.setText("IMG")
                self._thumb.setStyleSheet("background: rgba(34, 197, 94, 0.1); color: #22C55E; border-radius: 4px; font-size: 10px; font-weight: 800;")
        elif ext in (".mkv", ".mp4", ".webm", ".avi"):
            play_ico = _asset("play.png")
            if os.path.isfile(play_ico):
                px = QPixmap(play_ico)
                self._thumb.setPixmap(px.scaled(20, 20, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
                self._thumb.setStyleSheet("background: rgba(220, 38, 38, 0.15); border-radius: 4px; border: 1px solid rgba(220, 38, 38, 0.3);")
            else:
                self._thumb.setText("▶")
                self._thumb.setStyleSheet("background: rgba(220, 38, 38, 0.15); color: #DC2626; border-radius: 4px; font-size: 14px; border: 1px solid rgba(220, 38, 38, 0.3);")
                
            # Check Performance Cache first
            try:
                mtime = os.path.getmtime(self._filepath)
                cached = _get_cached_thumbnail(self._filepath)
                if cached is not None:
                    c_mtime, c_data, c_dur = cached
                    if c_mtime == mtime:
                        self._on_video_thumb_loaded(c_data, c_dur)
                        return
            except Exception:
                pass

            # Async thumbnail load (Cache miss)
            self._thumb_signals = _ThumbSignals()
            self._thumb_signals.loaded.connect(self._on_video_thumb_loaded)
            task = _VideoThumbnailTask(self._filepath, self._thumb_signals.loaded)
            THUMBNAIL_POOL.start(task)
        else:
            self._thumb.setText("FILE")
            self._thumb.setStyleSheet("background: rgba(255, 255, 255, 0.1); color: #FFFFFF; border-radius: 4px; font-size: 10px; font-weight: 800;")

    def _draw_clock_icon(self, sz):
        pm = QPixmap(sz, sz)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Use a soft white for the icon
        color = QColor(255, 255, 255, 110)
        p.setPen(QPen(color, 1.3))
        # Draw outer circle
        p.drawEllipse(1, 1, sz-2, sz-2)
        # Draw hands
        cx, cy = sz/2, sz/2
        p.drawLine(QPointF(cx, cy), QPointF(cx, 4))      # Minute hand
        p.drawLine(QPointF(cx, cy), QPointF(cx + 3, cy)) # Hour hand
        p.end()
        return pm

    def _on_video_thumb_loaded(self, pm_data: bytes, dur_str: str = ""):
        pm = QPixmap()
        pm.loadFromData(pm_data, "JPEG")
        if not pm.isNull():
            self._thumb.setText("")
            # Scale the frame first, THEN draw the play button to prevent icon distortion
            scaled_pm = pm.scaled(self._thumb.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
            
            # Crop to exact thumb size if needed
            final_pm = scaled_pm.copy(
                (scaled_pm.width() - self._thumb.width()) // 2,
                (scaled_pm.height() - self._thumb.height()) // 2,
                self._thumb.width(), self._thumb.height()
            )

            # Draw overlay on the correctly sized pixmap
            painter = QPainter(final_pm)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setBrush(QColor(0, 0, 0, 30)) # Very light darkening for contrast
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRect(final_pm.rect())
            
            # Draw play icon in center
            play_ico = _asset("play.png")
            if os.path.isfile(play_ico):
                ico = QPixmap(play_ico).scaled(20, 20, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                painter.drawPixmap((final_pm.width()-20)//2, (final_pm.height()-20)//2, ico)
                
            # Draw duration on bottom-right (clean text, no box/icon)
            if dur_str:
                painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
                f_size = 9 if getattr(self, "_font_size_mode", "Default") == "Large" else 8
                font = QFont("Segoe UI", f_size, QFont.Weight.Bold)
                painter.setFont(font)
                fm = QFontMetrics(font)
                tw = fm.horizontalAdvance(dur_str)
                th = fm.height()
                
                # Bottom right margin
                bg_margin = 2
                rect_x = final_pm.width() - tw - bg_margin * 2 - 4
                rect_y = final_pm.height() - th - bg_margin * 2 - 2
                rect_w = tw + bg_margin * 2
                rect_h = th + bg_margin * 2
                
                # Draw semi-transparent black background
                painter.setBrush(QColor(0, 0, 0, 180))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawRoundedRect(rect_x, rect_y, rect_w, rect_h, 3, 3)
                
                # White text
                tx = rect_x + bg_margin
                ty = rect_y + th - fm.descent() + bg_margin - 1
                painter.setPen(QColor(255, 255, 255, 240))
                painter.drawText(tx, ty, dur_str)
                
            painter.end()
                
            self._thumb.setPixmap(final_pm)
            self._thumb.setStyleSheet("background: #000000; border-radius: 4px; border: 1px solid #333;")

    def _icon_btn(self, icon_name, tip):
        b = QPushButton()
        b.setToolTip(tip)
        b.setFixedSize(26, 26)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setAttribute(Qt.WidgetAttribute.WA_AlwaysShowToolTips)
        ico = _asset(icon_name) if icon_name else ""
        if ico and os.path.isfile(ico):
            b.setIcon(QIcon(ico))
            b.setIconSize(QSize(14, 14))
        else:
            b.setText(tip[0])
        b.setStyleSheet("""
            QPushButton { background: transparent; border: none; border-radius: 4px; color: rgba(255,255,255,0.45); font-size: 11px; }
            QPushButton:hover { background: rgba(220,38,38,0.2); }
        """)
        return b

    def _build_actions_menu(self):
        """Build the one canonical file-action menu used by click/right-click."""
        from PyQt6.QtWidgets import QMenu
        from PyQt6.QtGui import QAction

        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu { background: #151923; color: #F7F7FA; border: 1px solid #3E4656;
                    border-radius: 9px; padding: 6px; font-family: 'Segoe UI'; }
            QMenu::item { padding: 8px 38px 8px 12px; border-radius: 6px; font-size: 12px; }
            QMenu::item:selected { background: #DC2626; color: #FFFFFF; }
            QMenu::item:disabled { color: rgba(255,255,255,0.30); }
        """)

        ext = Path(self._filepath).suffix.lower()
        if ext in ('.png', '.jpg', '.jpeg'):
            open_edit_action = QAction("Open & Edit", menu)
            open_edit_action.triggered.connect(self._edit_file)
            menu.addAction(open_edit_action)
        elif ext in ('.mkv', '.mp4', '.webm', '.avi'):
            play_action = QAction("Play", menu)
            play_action.triggered.connect(lambda: self.play_video_requested.emit(self._filepath))
            menu.addAction(play_action)
            edit_action = QAction("Edit", menu)
            edit_action.triggered.connect(self._edit_file)
            menu.addAction(edit_action)
        else:
            open_action = QAction("Open", menu)
            open_action.triggered.connect(lambda: self.open_requested.emit(self._filepath))
            menu.addAction(open_action)

        copy_action = QAction("Copy", menu)
        copy_action.triggered.connect(self._copy_file)
        menu.addAction(copy_action)

        rename_action = QAction("Rename", menu)
        rename_action.triggered.connect(self._start_rename)
        menu.addAction(rename_action)

        delete_action = QAction("Delete", menu)
        delete_action.triggered.connect(lambda: self.delete_requested.emit(self._filepath))
        menu.addAction(delete_action)
        return menu

    def _show_actions_menu(self, _checked=False, global_pos=None):
        if self._is_renaming:
            return
        menu = self._build_actions_menu()
        pos = global_pos or self._btn_menu.mapToGlobal(QPoint(0, self._btn_menu.height()))
        menu.exec(pos)

    def contextMenuEvent(self, event):
        self._show_actions_menu(global_pos=event.globalPos())
        event.accept()

    def _is_editable_media(self) -> bool:
        return Path(self._filepath).suffix.lower() in (
            '.png', '.jpg', '.jpeg', '.mkv', '.mp4', '.webm', '.avi'
        )

    def _edit_file(self):
        if self._is_editable_media():
            self.edit_requested.emit(self._filepath)

    def _copy_file(self):
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(self._filepath)])
        mime.setText(self._filepath)
        QApplication.clipboard().setMimeData(mime)
        self._show_copy_confirmation()

    def _show_copy_confirmation(self):
        self._btn_menu.setIcon(QIcon())
        self._btn_menu.setText("✓")
        self._btn_menu.setStyleSheet(
            self._btn_menu.styleSheet()
            + "QPushButton { color: #22C55E; font-size: 17px; font-weight: 900; }"
        )
        QTimer.singleShot(900, self._restore_menu_dots)

    def _restore_menu_dots(self):
        try:
            self._btn_menu.setText("")
            self._btn_menu.setIcon(self._menu_dots_icon)
        except RuntimeError:
            pass

    def _build_drag_pixmap(self) -> QPixmap:
        """Translucent thumbnail + filename preview that follows a file drag."""
        width = 220
        height = 52
        preview = QPixmap(width, height)
        preview.fill(Qt.GlobalColor.transparent)
        painter = QPainter(preview)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(255, 255, 255, 55), 1))
        painter.setBrush(QColor(24, 24, 27, 205))
        painter.drawRoundedRect(1, 1, width - 2, height - 2, 8, 8)

        source = self._thumb.pixmap()
        if source and not source.isNull():
            thumb = source.scaled(
                54, 40, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            painter.setOpacity(0.82)
            painter.drawPixmap(7, (height - thumb.height()) // 2, thumb)
            painter.setOpacity(1.0)

        painter.setPen(QColor(255, 255, 255, 225))
        painter.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
        text_rect = QRect(67, 4, width - 76, height - 8)
        metrics = painter.fontMetrics()
        name = metrics.elidedText(
            Path(self._filepath).name, Qt.TextElideMode.ElideMiddle, text_rect.width()
        )
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter, name)
        painter.end()
        return preview

    def _start_rename(self):
        self._is_renaming = True
        self._rename_edit.setText(Path(self._filepath).stem)
        self._rename_edit.setVisible(True)
        self._rename_edit.setFocus()
        self._rename_edit.selectAll()
        self._lbl_name.setVisible(False)

    def _finish_rename(self):
        if not self._is_renaming:
            return  # Guard against double-call from returnPressed + editingFinished
        new = self._rename_edit.text().strip()
        if new and new != Path(self._filepath).stem:
            target = Path(self._filepath).with_name(new + Path(self._filepath).suffix)
            if target.exists():
                QMessageBox.warning(
                    self, "Name Already Used",
                    f"A file named “{target.name}” already exists. Choose a different name.",
                )
                self._rename_edit.setFocus()
                self._rename_edit.selectAll()
                return
            self.rename_requested.emit(self._filepath, new + Path(self._filepath).suffix)
        self._rename_edit.setVisible(False)
        self._lbl_name.setVisible(True)
        self._is_renaming = False

    def _cancel_rename(self):
        if not self._is_renaming:
            return
        self._is_renaming = False
        self._rename_edit.hide()
        self._lbl_name.show()
        self.setFocus(Qt.FocusReason.OtherFocusReason)

    def mouseDoubleClickEvent(self, event):
        if not self._is_renaming:
            self.open_requested.emit(self._filepath)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and not self._is_renaming:
            self._drag_start_pos = event.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not (event.buttons() & Qt.MouseButton.LeftButton) or self._is_renaming or not self._drag_start_pos:
            return
        if (event.pos() - self._drag_start_pos).manhattanLength() < QApplication.startDragDistance():
            return

        drag = QDrag(self)
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(self._filepath)])
        drag.setMimeData(mime)

        preview = self._build_drag_pixmap()
        drag.setPixmap(preview)
        drag.setHotSpot(QPoint(22, preview.height() // 2))

        # COPY only — never move files
        drag.exec(Qt.DropAction.CopyAction)


# ─────────────────────────────────────────────────────────────────────────────
#  RecentFilesSidebar
# ─────────────────────────────────────────────────────────────────────────────

class RecentFilesSidebar(SidebarPanel):
    """Recent files gallery in a full-height sidebar."""

    TIPS = (
        "Drag & Drop captures anywhere.",
        "Customize shortcuts in Settings.",
        "Right click or use ⋮ to see options.",
        "Edit Video -> Remove segments or add captions.",
        "Edit Video -> Trim & adjusts video ends.",
        "Edit Video -> Delete Video Segments.",
        "Edit Video -> To mute audio from the recording.",
        "Settings-> Adjust audio capture defaults.",
        "Use annotator to add Text and doodle on screen.",
        "Open & Edit images-> Copy edits without saving.",
        "Hold CTRL or ALT key to draw straight lines.",
    )

    settings_requested  = pyqtSignal()
    annotate_file_requested = pyqtSignal(str)  # filepath to open in WWR: Image Editor
    play_video_requested    = pyqtSignal(str)  # filepath to open in video player
    edit_file_requested     = pyqtSignal(str)  # filepath to open directly in editor mode
    rename_needed           = pyqtSignal(str, str)  # (old_path, new_path) — app handles player lock

    def __init__(self, output_folder: str, font_size_mode: str = "Default", edge: str = "right", close_on_focus_loss: bool = True):
        super().__init__(edge, close_on_focus_loss, font_size_mode=font_size_mode)
        self._output_folder = output_folder
        self._font_size_mode = font_size_mode
        self._processing_file = None  # filename shown as "Processing..." placeholder
        self._processing_widget = None
        self._scan_generation = 0
        self._build_ui()
        self._position_sidebar()
        self._load_files()

    def _build_ui(self):
        fs_mode = getattr(self, "_font_size_mode", "Default")
        f_small = 11 if fs_mode == "Default" else 13
        f_norm = 12 if fs_mode == "Default" else 14
        f_med = 13 if fs_mode == "Default" else 15
        f_large = 15 if fs_mode == "Default" else 17

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 0)
        root.setSpacing(0)

        # Settings gear button for heading bar
        btn_settings = QPushButton()
        btn_settings.setToolTip("Settings")
        sz = 30 if fs_mode == "Large" else 26
        btn_settings.setFixedSize(sz, sz)
        btn_settings.setCursor(Qt.CursorShape.PointingHandCursor)
        settings_ico = _asset("settings.png")
        if os.path.isfile(settings_ico):
            btn_settings.setIcon(QIcon(settings_ico))
            btn_settings.setIconSize(QSize(14, 14))
        btn_settings.setStyleSheet(f"""
            QPushButton {{
                background: #262628; border: 1px solid #3C3C3E;
                border-radius: {sz//2}px;
            }}
            QPushButton:hover {{ background: #DC2626; border-color: #EF4444; }}
        """)
        btn_settings.clicked.connect(self.settings_requested.emit)

        self._build_heading(root, extra_buttons=[btn_settings])

        # Header Actions Row
        actions_row = QHBoxLayout()
        actions_row.setContentsMargins(0, 0, 0, 0)
        actions_row.setSpacing(6)

        # Open folder button
        btn_folder = QPushButton("  Open Folder in Explorer")
        btn_folder.setFixedHeight(34)
        btn_folder.setCursor(Qt.CursorShape.PointingHandCursor)
        ico = _asset("folder.png")
        if os.path.isfile(ico):
            btn_folder.setIcon(QIcon(ico))
            btn_folder.setIconSize(QSize(14, 14))
        btn_folder.setStyleSheet(f"""
            QPushButton {{
                background: #262628; color: rgba(255,255,255,0.8); border: 1px solid #3C3C3E;
                border-radius: 6px; font-size: {f_norm}px; text-align: left; padding-left: 10px;
            }}
            QPushButton:hover {{ background: #DC2626; color: #FFFFFF; border-color: #EF4444; }}
        """)
        btn_folder.clicked.connect(self._open_folder)
        actions_row.addWidget(btn_folder, 1)

        # Toggle Search Button
        btn_toggle_search = QPushButton()
        btn_toggle_search.setFixedSize(34, 34)
        btn_toggle_search.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_toggle_search.setToolTip("Search Recordings")
        s_ico = _asset("search.png")
        if os.path.isfile(s_ico):
            btn_toggle_search.setIcon(QIcon(s_ico))
            btn_toggle_search.setIconSize(QSize(14, 14))
        else:
            btn_toggle_search.setText("🔍")
            btn_toggle_search.setStyleSheet(f"color: rgba(255,255,255,0.6); font-size: {f_large}px;")
        btn_toggle_search.setStyleSheet("""
            QPushButton {
                background: #262628; border: 1px solid #3C3C3E; border-radius: 6px;
            }
            QPushButton:hover { background: #DC2626; border-color: #EF4444; }
        """)
        btn_toggle_search.clicked.connect(self._toggle_search)
        actions_row.addWidget(btn_toggle_search)

        root.addLayout(actions_row)

        # Search box (hidden by default)
        self._edt_search = QLineEdit()
        self._edt_search.setVisible(False)
        self._edt_search.setPlaceholderText("Search recordings...")
        self._edt_search.setFixedHeight(34)
        self._edt_search.setStyleSheet(f"""
            QLineEdit {{
                background: #1C1C1E; border: 1px solid #3C3C3E; border-radius: 6px;
                padding: 0 10px; color: #FFFFFF; font-size: {f_norm}px; font-family: 'Segoe UI';
                margin-top: 6px;
            }}
            QLineEdit:focus {{ border: 1px solid #DC2626; }}
        """)
        self._edt_search.textChanged.connect(self._filter_files)
        root.addWidget(self._edt_search)

        root.addSpacing(8)

        # Scroll area
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet("""
            QScrollArea { background: transparent; border: none; }
            QScrollBar:vertical { background: transparent; width: 5px; }
            QScrollBar::handle:vertical { background: rgba(220,38,38,0.4); border-radius: 2px; min-height: 20px; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
        """)

        self._file_container = QWidget()
        self._file_container.setStyleSheet("background: transparent;")
        self._file_layout = QVBoxLayout(self._file_container)
        self._file_layout.setContentsMargins(0, 0, 0, 0)
        self._file_layout.setSpacing(2)
        self._file_layout.addStretch()

        self._scroll.setWidget(self._file_container)
        # PERF-003: Throttle scroll-based lazy load to max 10fps
        self._lazy_load_timer = QTimer(self)
        self._lazy_load_timer.setSingleShot(True)
        self._lazy_load_timer.setInterval(100)
        self._lazy_load_timer.timeout.connect(self._check_lazy_load)
        self._scroll.verticalScrollBar().valueChanged.connect(self._schedule_lazy_load)
        root.addWidget(self._scroll, 1)

        # Drag and drop hint
        self._tips = list(self.TIPS)
        self._tip_index = 0
        self._lbl_drag_info = QLabel(f"Tip: {self._tips[self._tip_index]}")
        self._lbl_drag_info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_drag_info.setWordWrap(False)
        self._lbl_drag_info.setStyleSheet(f"color: rgba(255,255,255,0.35); font-size: {f_small}px; font-style: italic; font-family: 'Segoe UI';")
        self._lbl_drag_info.ensurePolished()
        self._lbl_drag_info.setFixedHeight(self._lbl_drag_info.fontMetrics().height())
        root.addWidget(self._lbl_drag_info)
        self._tip_timer = QTimer(self)
        self._tip_timer.setInterval(6000)
        self._tip_timer.timeout.connect(self._advance_tip)
        self._tip_timer.start()

        self._lbl_empty = QLabel("No files yet.\nCapture something to get started.")
        self._lbl_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_empty.setStyleSheet(f"color: rgba(255,255,255,0.25); font-size: {f_norm}px; padding: 30px;")
        self._lbl_empty.setWordWrap(True)
        self._lbl_empty.setVisible(False)
        root.addWidget(self._lbl_empty, 1)

    def _advance_tip(self):
        self._tip_index = (self._tip_index + 1) % len(self._tips)
        self._lbl_drag_info.setText(f"Tip: {self._tips[self._tip_index]}")

    def _load_files(self):
        self._scan_generation += 1
        generation = self._scan_generation
        # The processing widget gets destroyed along with all others here.
        # Nullify the reference so _insert_processing_widget creates a fresh one.
        self._processing_widget = None

        while self._file_layout.count() > 1:
            item = self._file_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        folder_path = self._output_folder
        if not Path(folder_path).exists():
            if not self._processing_file:
                self._lbl_empty.setVisible(True)
                self._scroll.setVisible(False)
                self._lbl_drag_info.setVisible(False)
            if self._processing_file:
                self._insert_processing_widget()
            return

        # PERF-002: Scan files in a background thread to avoid blocking UI
        self._scan_task = _FileScanTask(folder_path, self._processing_file, generation)
        self._scan_task.signals.finished.connect(self._on_files_scanned)
        QThreadPool.globalInstance().start(self._scan_task)

    @pyqtSlot(list, int)
    def _on_files_scanned(self, files: list, generation: int = None):
        """Receive scan results on the GUI thread; Qt disconnects a deleted sidebar."""
        if generation is not None and generation != self._scan_generation:
            return
        # BUG-FIX: Re-filter against current processing filename to prevent race condition.
        # The scan ran in a background thread, so _processing_file may have been set
        # after the scan started but before results arrived here.
        if self._processing_file:
            processing_name = self._processing_file
            files = [(fp, mt) for fp, mt in files
                     if os.path.basename(fp) != processing_name]

        if not files and not self._processing_file:
            self._lbl_empty.setVisible(True)
            self._scroll.setVisible(False)
            self._lbl_drag_info.setVisible(False)
            return

        self._lbl_empty.setVisible(False)
        self._scroll.setVisible(True)
        self._lbl_drag_info.setVisible(True)

        font_size_mode = getattr(self, "_font_size_mode", "Default")
        current_group = None

        for i, (fpath, mtime) in enumerate(files):
            # Determine date group
            group = self._get_date_group(mtime)
            if group != current_group:
                current_group = group
                self._add_date_separator(group)

            # Build the first page immediately, then load only rows reached by scrolling.
            defer = (i >= 15)
            row = _FileRow(str(fpath), font_size_mode, defer_load=defer)
            row.open_requested.connect(self._open_file)
            row.rename_requested.connect(self._rename_file)
            row.delete_requested.connect(self._delete_file)
            row.annotate_requested.connect(self._annotate_file)
            row.play_video_requested.connect(self._play_video_file)
            row.edit_requested.connect(self._edit_file)
            self._file_layout.insertWidget(self._file_layout.count() - 1, row)
            
        # Re-insert the processing placeholder at the top if active
        if self._processing_file:
            self._insert_processing_widget()

        # Initial check for visibility (in case viewport shows more than 8 or we need to load them)
        QTimer.singleShot(100, self._check_lazy_load)
            
        # apply any existing search filter
        if getattr(self, '_edt_search', None) and self._edt_search.text():
            self._filter_files(self._edt_search.text())

    def _get_date_group(self, timestamp):
        from datetime import date, timedelta
        dt = datetime.fromtimestamp(timestamp)
        today = date.today()
        yesterday = today - timedelta(days=1)
        
        file_date = dt.date()
        if file_date == today:
            return "Today"
        elif file_date == yesterday:
            return "Yesterday"
        else:
            return file_date.strftime("%B %d, %Y")

    def _add_date_separator(self, text):
        fs_mode = getattr(self, "_font_size_mode", "Default")
        fs = 11 if fs_mode == "Default" else 13
        
        container = QWidget()
        container.is_date_separator = True
        lay = QHBoxLayout(container)
        lay.setContentsMargins(4, 12, 4, 4)
        lay.setSpacing(10)
        
        lbl = QLabel(text.upper())
        lbl.setStyleSheet(f"color: #DC2626; font-size: {fs}px; font-weight: 800; font-family: 'Segoe UI'; letter-spacing: 0.5px;")
        lay.addWidget(lbl)
        
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("background: rgba(220, 38, 38, 0.2); height: 1px; border: none;")
        lay.addWidget(line, 1)
        
        self._file_layout.insertWidget(self._file_layout.count() - 1, container)

    def _schedule_lazy_load(self):
        """PERF-003: Debounce lazy load checks during rapid scrolling."""
        if not self._lazy_load_timer.isActive():
            self._lazy_load_timer.start()

    def _check_lazy_load(self):
        """Check which rows are visible and load their content if deferred."""
        if not self.isVisible(): return
        
        viewport_rect = self._scroll.viewport().rect()
        # Add some buffer (100px)
        load_threshold = viewport_rect.bottom() + 100
        
        for i in range(self._file_layout.count() - 1):
            item = self._file_layout.itemAt(i)
            row = item.widget()
            if row and hasattr(row, 'load_content') and not row._loaded:
                if not row.isVisible():
                    continue
                # Map row top to viewport coordinates
                row_y = row.mapTo(self._scroll.viewport(), QPoint(0, 0)).y()
                if row_y < load_threshold:
                    row.load_content()
                else:
                    # Since rows are ordered, we can stop once we hit the first row below threshold
                    break

    def _filter_files(self, text: str):
        query = text.lower()
        last_date_sep = None
        has_visible_in_group = False
        
        for i in range(self._file_layout.count() - 1): # skip stretch at end
            item = self._file_layout.itemAt(i)
            widget = item.widget()
            if not widget: continue
            
            if getattr(widget, "is_date_separator", False):
                if last_date_sep:
                    last_date_sep.setVisible(has_visible_in_group)
                last_date_sep = widget
                has_visible_in_group = False
            elif hasattr(widget, 'filename'):
                is_match = query in widget.filename.lower()
                widget.setVisible(is_match)
                if is_match:
                    has_visible_in_group = True
                    
        if last_date_sep:
            last_date_sep.setVisible(has_visible_in_group)
            
        QTimer.singleShot(50, self._check_lazy_load)

    def _toggle_search(self):
        is_visible = self._edt_search.isVisible()
        if is_visible:
            self._edt_search.setVisible(False)
            self._edt_search.clear()  # Clear search when closed
        else:
            self._edt_search.setVisible(True)
            self._edt_search.setFocus()

    def close_panel(self, animate=True):
        # BUG-025: Reset search filter so reopening shows all files
        if hasattr(self, '_edt_search') and self._edt_search.text():
            self._edt_search.clear()
            self._edt_search.setVisible(False)
            self._filter_files("")
        super().close_panel(animate=animate)

    def refresh(self):
        self._load_files()

    def set_processing_file(self, filename: str):
        """Show a 'Processing...' placeholder at the top of the file list."""
        self._processing_file = filename
        self._insert_processing_widget()

    def clear_processing_file(self):
        """Remove the processing placeholder."""
        self._processing_file = None
        if self._processing_widget:
            self._processing_widget.setParent(None)
            self._processing_widget.deleteLater()
            self._processing_widget = None

    def _insert_processing_widget(self):
        """Build and insert the processing placeholder row at the top of the file list."""
        if self._processing_widget:
            self._processing_widget.setParent(None)
            self._processing_widget.deleteLater()

        fs_mode = self._font_size_mode
        h = 68 if fs_mode == "Large" else 54
        fs_name = "16px" if fs_mode == "Large" else "13px"
        fs_meta = "14px" if fs_mode == "Large" else "11px"

        w = QWidget()
        w.setFixedHeight(h)
        w.setStyleSheet("_FileRow { background: transparent; border-radius: 6px; }")
        lay = QHBoxLayout(w)
        lay.setContentsMargins(6, 4, 6, 4)
        lay.setSpacing(10)

        # Thumbnail placeholder with pulsing sync icon
        thumb = QLabel("\u27f3")  # ⟳ refresh/sync icon
        if fs_mode == "Large":
            thumb.setFixedSize(80, 60)
        else:
            thumb.setFixedSize(60, 45)
        thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        thumb.setStyleSheet(
            "background: rgba(59, 130, 246, 0.1); border-radius: 4px; "
            "color: #3B82F6; font-size: 18px; border: 1px solid rgba(59, 130, 246, 0.2);"
        )
        lay.addWidget(thumb)

        info = QVBoxLayout()
        info.setSpacing(2)
        info.setContentsMargins(4, 0, 0, 0)

        lbl_name = QLabel(self._processing_file or "Recording")
        lbl_name.setStyleSheet(f"color: rgba(255,255,255,0.6); font-size: {fs_name}; font-weight: 500; font-family: 'Segoe UI';")
        info.addWidget(lbl_name)

        lbl_status = QLabel("Processing…")
        lbl_status.setStyleSheet(f"color: #3B82F6; font-size: {fs_meta}; font-weight: 600; font-family: 'Segoe UI';")
        info.addWidget(lbl_status)
        info.addStretch()
        lay.addLayout(info, 1)

        # Ensure the processing widget shows even when list is empty
        self._lbl_empty.setVisible(False)
        self._scroll.setVisible(True)
        self._lbl_drag_info.setVisible(True)

        self._processing_widget = w
        self._file_layout.insertWidget(0, w)

    def _open_file(self, fp):
        """Open supported media in WWRecorder, not the Windows default app."""
        if not os.path.isfile(fp):
            return
        ext = Path(fp).suffix.lower()
        if ext in ('.png', '.jpg', '.jpeg'):
            self.annotate_file_requested.emit(fp)
        elif ext in ('.mkv', '.mp4', '.webm', '.avi'):
            self.play_video_requested.emit(fp)

    def _annotate_file(self, fp):
        """Open a screenshot file in WWR: Image Editor."""
        if os.path.isfile(fp):
            self.annotate_file_requested.emit(fp)

    def _play_video_file(self, fp):
        """Open a video file in the in-app video player."""
        if os.path.isfile(fp):
            self.play_video_requested.emit(fp)

    def _edit_file(self, fp):
        """Open supported media directly in its WWRecorder editing surface."""
        if os.path.isfile(fp):
            self.edit_file_requested.emit(fp)

    def _rename_file(self, old, new_name):
        new = os.path.join(os.path.dirname(old), new_name)
        if os.path.exists(new):
            QMessageBox.warning(
                self, "Name Already Used",
                f"A file named “{new_name}” already exists. Choose a different name.",
            )
            return
        # Delegate to app-level handler so it can release any player lock first
        self.rename_needed.emit(old, new)

    def _delete_file(self, fp):
        reply = QMessageBox.question(
            self, "Delete File", f"Permanently delete\n{os.path.basename(fp)}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            try:
                os.remove(fp)
                self._load_files()
            except Exception as e:
                from user_messages import friendly_error
                QMessageBox.warning(self, "Could Not Delete File", friendly_error(e))

    def _open_folder(self):
        if os.path.isdir(self._output_folder):
            os.startfile(self._output_folder)
