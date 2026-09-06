"""
main.py - WWRecorder Entry Point

Wires together:
  • System tray icon + context menu
  • Global hotkey listener (pynput)  - works even when minimised
  • Windows Registry auto-start
  • SelectionOverlay → PillWidget → RecordingEngine lifecycle
  • JSON config persistence in %APPDATA%\\WWRecorder\\config.json
"""
import pythoncom
pythoncom.CoInitialize()

from PyQt6.QtWidgets import QMessageBox
import os
import sys
import io

if sys.stdout is None:
    sys.stdout = io.StringIO()
if sys.stderr is None:
    sys.stderr = io.StringIO()

import json 
import winreg
import subprocess
import logging
import threading
import traceback
from logging.handlers import RotatingFileHandler
from datetime import datetime
from pathlib import Path   


from PyQt6.QtWidgets import (
    QApplication, QMenu, QSystemTrayIcon, QWidget, QFileDialog,
    QLabel, QProgressBar, QVBoxLayout, QHBoxLayout, QPushButton,
    QToolTip, QGraphicsOpacityEffect, QLineEdit
)
from PyQt6.QtGui import QIcon, QAction, QPixmap, QPainter, QColor, QImage, QMovie, QPainterPath, QPen, QKeySequence, QShortcut
from PyQt6.QtCore import (
    Qt, QObject, QThread, pyqtSignal, QPoint, QRect, QRectF, QUrl, QMimeData, QTimer,
    qInstallMessageHandler, QtMsgType, QSize, QPropertyAnimation
)

from pynput import keyboard as pynput_keyboard

from recorder import RecordingEngine
from ui_elements import SelectionOverlay, PillWidget, SettingsWindow, CaptureBorderWidget
from dock_widget import (
    DockWidget, SettingsSidebar, RecentFilesSidebar, _ACTIVE_UPDATE_THREADS,
)
from updater import UpdateChecker
from display_geometry import build_capture_plan, compose_frozen_desktop, qt_screen_transforms
from user_messages import friendly_error

APP_NAME = "WWRecorder"

SAFE_IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg'}
SAFE_VIDEO_EXTENSIONS = {'.mkv', '.mp4', '.webm', '.avi'}


def _is_safe_media_path(path: str) -> bool:
    return os.path.isfile(path) and Path(path).suffix.lower() in (SAFE_IMAGE_EXTENSIONS | SAFE_VIDEO_EXTENSIONS)


def _available_media_path(path: str) -> str:
    """Return a collision-free sibling path without overwriting user media."""
    candidate = Path(path)
    if not candidate.exists():
        return str(candidate)
    counter = 2
    while True:
        alternate = candidate.with_name(f"{candidate.stem}_{counter}{candidate.suffix}")
        if not alternate.exists():
            return str(alternate)
        counter += 1


def _normalized_capture_plan(plan: dict, minimum_size: int = 32) -> dict | None:
    """Return an even-sized encoding plan, or reject an unusably small crop."""
    normalized = dict(plan)
    width = int(normalized.get("width", 0))
    height = int(normalized.get("height", 0))
    width -= width % 2
    height -= height % 2
    if width < minimum_size or height < minimum_size:
        return None
    normalized["width"] = width
    normalized["height"] = height
    return normalized


def _screen_for_anchor(anchor: QPoint | None):
    return (QApplication.screenAt(anchor) if anchor is not None else None) or QApplication.primaryScreen()


def _acquire_single_instance_mutex(kernel32=None):
    """Return (handle, already_running) without requiring elevation."""
    if sys.platform != 'win32' and kernel32 is None:
        return None, False
    import ctypes
    kernel32 = kernel32 or ctypes.windll.kernel32
    handle = kernel32.CreateMutexW(None, False, f"Local\\{APP_NAME}_mutex")
    return handle, kernel32.GetLastError() == 183

# Pre-import mss to avoid first-screenshot delay
try:
    import mss
except ImportError:
    pass


# ─────────────────────────────────────────────────────────────────────────────
#  Recording Save Popup
# ─────────────────────────────────────────────────────────────────────────────

class _RoundedMovieLabel(QLabel):
    """Antialiased rounded frame for playing animated GIF movies."""
    def __init__(self, radius: float = 8.0, parent=None):
        super().__init__(parent)
        self._radius = radius
        self.setStyleSheet("background: transparent; border: none;")

    def paintEvent(self, event):
        movie = self.movie()
        if movie and movie.isValid():
            pixmap = movie.currentPixmap()
            if not pixmap.isNull():
                p = QPainter(self)
                p.setRenderHint(QPainter.RenderHint.Antialiasing)
                p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
                rect = QRectF(0.0, 0.0, float(self.width()), float(self.height()))
                path = QPainterPath()
                path.addRoundedRect(rect, self._radius, self._radius)
                p.setClipPath(path)
                p.drawPixmap(0, 0, self.width(), self.height(), pixmap)
                p.end()
                return
        super().paintEvent(event)


class _SavingPopup(QWidget):
    """Small bottom-right popup shown while a recording is being processed."""
    def __init__(self):
        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        super().__init__(None, flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        self._dot_count = 0
        self._dot_timer = QTimer(self)
        self._dot_timer.setInterval(500)
        self._dot_timer.timeout.connect(self._animate_dot)

        container = QWidget(self)
        container.setObjectName("savingContainer")
        container.setStyleSheet("""
            QWidget#savingContainer {
                background: #1C1C1E;
                border: 1px solid #3A3A3C;
                border-radius: 12px;
            }
        """)
        container.setFixedWidth(320)

        main_layout = QHBoxLayout(container)
        main_layout.setContentsMargins(12, 8, 16, 8)
        main_layout.setSpacing(14)

        icon_lbl = _RoundedMovieLabel(radius=8.0)
        icon_lbl.setFixedSize(64, 64)
        gif_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons", "waiting.gif")
        self._movie = QMovie(gif_path)
        self._movie.setScaledSize(QSize(64, 64))
        icon_lbl.setMovie(self._movie)
        main_layout.addWidget(icon_lbl)

        right_layout = QVBoxLayout()
        right_layout.setSpacing(4)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        self._status_lbl = QLabel("Processing recording...")
        self._status_lbl.setStyleSheet(
            "background: transparent; border: none; color: #FFFFFF; "
            "font-size: 12px; font-weight: 600;"
        )

        btn_min = QPushButton("−")
        btn_min.setFixedSize(20, 20)
        btn_min.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_min.setStyleSheet("""
            QPushButton { background: transparent; color: #8E8E93; border: none; font-size: 16px; font-weight: bold; padding-bottom: 2px; }
            QPushButton:hover { color: #FFFFFF; }
        """)
        btn_min.clicked.connect(self.hide_saving)
        
        header.addWidget(self._status_lbl, 1)
        header.addWidget(btn_min)
        right_layout.addLayout(header)

        self._sub_lbl = QLabel("Will appear in your files once ready")
        self._sub_lbl.setStyleSheet(
            "background: transparent; border: none; color: rgba(255,255,255,0.45); "
            "font-size: 10px;"
        )
        right_layout.addWidget(self._sub_lbl)

        self._bar = QProgressBar()
        self._bar.setRange(0, 0)   # indeterminate pulse
        self._bar.setFixedHeight(3)
        self._bar.setTextVisible(False)
        self._bar.setStyleSheet("""
            QProgressBar { background: #2C2C2E; border-radius: 1px; border: none; margin-top: 4px; }
            QProgressBar::chunk { background: #3B82F6; border-radius: 1px; }
        """)
        right_layout.addWidget(self._bar)
        
        main_layout.addLayout(right_layout, 1)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(container)
        self.adjustSize()

    def show_saving(self, anchor: QPoint | None = None):
        self._dot_count = 0
        self._position_bottom_right(anchor)
        self.show()
        self.raise_()
        self._dot_timer.start()
        self._movie.start()

    def hide_saving(self):
        self._dot_timer.stop()
        if hasattr(self, '_movie') and self._movie:
            self._movie.stop()
        self.hide()

    def _animate_dot(self):
        self._dot_count = (self._dot_count + 1) % 4
        dots = '.' * self._dot_count
        self._status_lbl.setText(f"Processing recording{dots}")

    def _position_bottom_right(self, anchor: QPoint | None = None):
        screen_obj = _screen_for_anchor(anchor)
        screen = screen_obj.availableGeometry() if screen_obj else QRect(0, 0, 1920, 1080)
        self.adjustSize()
        x = screen.right() - self.width() - 16
        y = screen.bottom() - self.height() - 16
        self.move(x, y)


# ─────────────────────────────────────────────────────────────────────────────
#  Success Notification (custom in-app notification for saves)
# ─────────────────────────────────────────────────────────────────────────────

class _SuccessNotification(QWidget):
    """Custom floating notification shown after successful screenshot/recording save."""
    renamed       = pyqtSignal(str, str)  # (old_filepath, new_filepath)
    open_clicked  = pyqtSignal(str)       # filepath
    rename_needed = pyqtSignal(str, str)  # (old_path, new_path) — app handles player lock

    def __init__(self, filepath: str, title: str, subtitle: str, icon_pixmap: QPixmap = None, duration: int = 6000):
        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        super().__init__(None, flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._filepath = filepath
        self._duration = duration
        self._is_renaming = False

        container = QWidget(self)
        container.setObjectName("notifContainer")
        container.setStyleSheet("""
            QWidget#notifContainer {
                background: #1C1C1E;
                border: 1px solid #3A3A3C;
                border-radius: 12px;
            }
        """)
        container.setFixedWidth(370)

        main_layout = QHBoxLayout(container)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)

        # Thumbnail — larger for better preview
        self._thumb_lbl = QLabel()
        self._thumb_lbl.setFixedSize(80, 80)
        self._thumb_lbl.setStyleSheet("background: #000; border-radius: 8px; border: 1px solid #333;")
        if icon_pixmap and not icon_pixmap.isNull():
            scaled = icon_pixmap.scaled(80, 80, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            self._thumb_lbl.setPixmap(scaled)
            self._thumb_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        else:
            self._thumb_lbl.setText("\u2714")
            self._thumb_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._thumb_lbl.setStyleSheet("background: rgba(34, 197, 94, 0.15); border-radius: 8px; color: #22C55E; font-size: 28px; font-weight: bold;")
        main_layout.addWidget(self._thumb_lbl, 0, Qt.AlignmentFlag.AlignTop)

        right = QVBoxLayout()
        right.setSpacing(2)
        right.setContentsMargins(0, 0, 0, 0)

        # Title row with close button
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(0)
        lbl_title = QLabel(title)
        lbl_title.setStyleSheet("background: transparent; border: none; color: #FFFFFF; font-size: 13px; font-weight: 700; font-family: 'Segoe UI';")
        header.addWidget(lbl_title, 1)

        btn_close = QPushButton("\u00d7")
        btn_close.setFixedSize(22, 22)
        btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_close.setStyleSheet("""
            QPushButton { background: transparent; color: #8E8E93; border: none; font-size: 16px; font-weight: bold; }
            QPushButton:hover { color: #FFFFFF; }
        """)
        btn_close.clicked.connect(self._dismiss)
        header.addWidget(btn_close)
        right.addLayout(header)

        # Subtitle (filename) — allows 2 lines
        self._lbl_sub = QLabel(subtitle)
        self._lbl_sub.setStyleSheet("background: transparent; border: none; color: rgba(255,255,255,0.55); font-size: 11px; font-family: 'Segoe UI';")
        self._lbl_sub.setWordWrap(True)
        self._lbl_sub.setMaximumHeight(34)  # ~2 lines
        right.addWidget(self._lbl_sub)

        # Rename inline editor (hidden by default)
        self._rename_edit = QLineEdit()
        self._rename_edit.setVisible(False)
        self._rename_edit.setFixedHeight(28)
        self._rename_edit.setStyleSheet("""
            QLineEdit {
                background: #2C2C2E; border: 1px solid #DC2626; border-radius: 5px;
                padding: 0 8px; color: #FFFFFF; font-size: 11px; font-family: 'Segoe UI';
                selection-background-color: #DC2626;
            }
        """)
        self._rename_edit.returnPressed.connect(self._commit_rename)
        QShortcut(QKeySequence("Esc"), self._rename_edit, self._toggle_rename)
        right.addWidget(self._rename_edit)

        right.addStretch()

        # Action buttons — right-aligned
        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 2, 0, 0)
        btn_row.setSpacing(6)
        btn_row.addStretch()

        self._btn_rename = QPushButton("Rename")
        self._btn_rename.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_rename.setFixedHeight(26)
        self._btn_rename.setStyleSheet("""
            QPushButton {
                background: #2C2C2E; color: rgba(255,255,255,0.8); border: 1px solid #3C3C3E;
                border-radius: 5px; font-size: 11px; font-weight: 600; padding: 0 14px; font-family: 'Segoe UI';
            }
            QPushButton:hover { background: #3C3C3E; color: #FFFFFF; }
        """)
        self._btn_rename.clicked.connect(self._toggle_rename)
        btn_row.addWidget(self._btn_rename)

        btn_open = QPushButton("Open")
        btn_open.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_open.setFixedHeight(26)
        btn_open.setStyleSheet("""
            QPushButton {
                background: #DC2626; color: #FFFFFF; border: none; border-radius: 5px;
                font-size: 11px; font-weight: 600; padding: 0 14px; font-family: 'Segoe UI';
            }
            QPushButton:hover { background: #EF4444; }
        """)
        btn_open.clicked.connect(self._on_open)
        btn_row.addWidget(btn_open)

        right.addLayout(btn_row)

        main_layout.addLayout(right, 1)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(container)
        self.adjustSize()

        # Auto-dismiss timer
        self._auto_timer = QTimer(self)
        self._auto_timer.setSingleShot(True)
        self._auto_timer.timeout.connect(self._dismiss)

        # Opacity effect for fade animations
        self._opacity_effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._opacity_effect)
        self._opacity_effect.setOpacity(0.0)

    def set_thumbnail(self, pixmap: QPixmap) -> None:
        if pixmap and not pixmap.isNull():
            self._thumb_lbl.setPixmap(pixmap.scaled(
                80, 80, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))
            self._thumb_lbl.setText("")
            self._thumb_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._thumb_lbl.setStyleSheet(
                "background: #000; border-radius: 8px; border: 1px solid #333;"
            )

    def show_notification(self, anchor: QPoint | None = None):
        screen_obj = _screen_for_anchor(anchor)
        screen = screen_obj.availableGeometry() if screen_obj else QRect(0, 0, 1920, 1080)
        self.adjustSize()
        x = screen.right() - self.width() - 16
        y = screen.bottom() - self.height() - 16
        self.move(x, y)
        self.show()

        # Fade in
        self._fade_in = QPropertyAnimation(self._opacity_effect, b"opacity")
        self._fade_in.setDuration(250)
        self._fade_in.setStartValue(0.0)
        self._fade_in.setEndValue(1.0)
        self._fade_in.start()

        self._auto_timer.start(self._duration)

        # Play success sound
        self._play_sound()

    def _play_sound(self):
        """Play a subtle success chime using Windows system sound."""
        try:
            import winsound
            # Play the Windows system asterisk sound (non-blocking)
            winsound.PlaySound("SystemAsterisk", winsound.SND_ALIAS | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
        except Exception:
            pass

    def _dismiss(self):
        self._dismissing = True
        self._auto_timer.stop()
        # Fade out then close
        self._fade_out = QPropertyAnimation(self._opacity_effect, b"opacity")
        self._fade_out.setDuration(200)
        self._fade_out.setStartValue(self._opacity_effect.opacity())
        self._fade_out.setEndValue(0.0)
        self._fade_out.finished.connect(self.close)
        self._fade_out.finished.connect(self.deleteLater)
        self._fade_out.start()

    def _on_open(self):
        self.open_clicked.emit(self._filepath)
        self._dismiss()

    def _toggle_rename(self):
        """Show/hide the inline rename editor."""
        if self._is_renaming:
            # Cancel rename
            self._rename_edit.setVisible(False)
            self._lbl_sub.setVisible(True)
            self._btn_rename.setText("Rename")
            self._is_renaming = False
            if not getattr(self, '_dismissing', False):
                self._auto_timer.start(3000)
        else:
            # Show rename editor pre-filled with stem (no extension)
            self._auto_timer.stop()
            stem = Path(self._filepath).stem
            self._rename_edit.setText(stem)
            self._rename_edit.setVisible(True)
            self._lbl_sub.setVisible(False)
            self._rename_edit.setFocus()
            self._rename_edit.selectAll()
            self._btn_rename.setText("Cancel")
            self._is_renaming = True

    def _commit_rename(self):
        """Perform the file rename from the inline editor."""
        new_stem = self._rename_edit.text().strip()
        if not new_stem:
            return

        old_path = self._filepath
        ext = Path(old_path).suffix
        new_name = new_stem + ext
        new_path = os.path.join(os.path.dirname(old_path), new_name)

        if new_path == old_path:
            self._toggle_rename()  # No change, just close editor
            return

        new_path = _available_media_path(new_path)
        new_name = Path(new_path).name

        try:
            # Emit so the app can release any player file lock first,
            # then rename, then notify us via the `renamed` signal.
            self.rename_needed.emit(old_path, new_path)
            # Update notification UI optimistically — if rename fails the app
            # will show an error toast but we still close the editor here.
            self._filepath = new_path
            self._lbl_sub.setText(new_name)
            self._rename_edit.setVisible(False)
            self._lbl_sub.setVisible(True)
            self._btn_rename.setText("Rename")
            self._is_renaming = False
            if not getattr(self, '_dismissing', False):
                self._auto_timer.start(3000)
        except Exception as e:
            print(f"[Notification] Rename failed: {e}")

    def enterEvent(self, event):
        self._auto_timer.stop()  # Pause auto-dismiss while hovered
        super().enterEvent(event)

    def leaveEvent(self, event):
        if not self._is_renaming and not getattr(self, '_dismissing', False):
            self._auto_timer.start(2000)  # Resume auto-dismiss after leaving
        super().leaveEvent(event)


def qt_message_handler(mode, context, message):
    if "QFont::setPointSize" in message or "Point size <= 0" in message:
        return
    if mode == QtMsgType.QtDebugMsg:
        sys.stdout.write(f"Debug: {message}\n")
    elif mode == QtMsgType.QtWarningMsg:
        sys.stderr.write(f"Warning: {message}\n")
    elif mode == QtMsgType.QtCriticalMsg:
        sys.stderr.write(f"Critical: {message}\n")
    elif mode == QtMsgType.QtFatalMsg:
        sys.stderr.write(f"Fatal: {message}\n")
        sys.exit(1)

qInstallMessageHandler(qt_message_handler)


# ─────────────────────────────────────────────────────────────────────────────
#  Constants / defaults
# ─────────────────────────────────────────────────────────────────────────────

APP_VERSION = "1.6.3"

CONFIG_DIR  = Path(os.environ.get("APPDATA", ".")) / APP_NAME
CONFIG_FILE = CONFIG_DIR / "config.json"
LOG_FILE    = CONFIG_DIR / "wwrecorder.log"
CRASH_FILE  = CONFIG_DIR / "wwrecorder-crash.log"

_crash_stream = None


def _install_crash_logging() -> None:
    """Persist uncaught Python/thread failures for production diagnosis."""
    global _crash_stream
    logger = logging.getLogger("wwrecorder")
    if not logger.handlers:
        handler = RotatingFileHandler(
            LOG_FILE, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8"
        )
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(threadName)s %(message)s"
        ))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

    def _record_exception(exc_type, exc_value, exc_tb):
        logger.critical("Uncaught exception", exc_info=(exc_type, exc_value, exc_tb))

    sys.excepthook = _record_exception
    if hasattr(threading, "excepthook"):
        threading.excepthook = lambda args: _record_exception(
            args.exc_type, args.exc_value, args.exc_traceback
        )
    try:
        import faulthandler
        _crash_stream = CRASH_FILE.open("a", encoding="utf-8")
        faulthandler.enable(_crash_stream, all_threads=True)
    except Exception as exc:
        logger.warning("Could not enable native crash logging: %s", exc)

_REG_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

DEFAULT_CONFIG: dict = {
    "output_folder":        str(Path.home() / "Videos" / APP_NAME),
    "hotkey":               "<shift>+<backspace>",
    "hotkey_screenshot":    "<shift>+<home>",
    "default_system_audio": False,
    "default_mic":          False,
    "start_on_boot":        True,
    "copy_to_clipboard":    True,
    "sidebar_width":        380,
    "close_on_focus_loss":  True,
    "developer_mode":       False,
    "ignored_update_version": "",
    "font_size":            "Default",
    "dock_edge":            "right",
    "dock_y":               -1,
}


# ─────────────────────────────────────────────────────────────────────────────
#  HotkeyListener - pynput owns the native listener thread
# ─────────────────────────────────────────────────────────────────────────────

class HotkeyListener(QObject):
    """
    Listens for global hotkeys on pynput's own background thread.
    Emits `record_triggered` and `screenshot_triggered` on the Qt side.

    Nesting Listener inside QThread caused a Windows shutdown/join race because
    pynput.Listener is already a thread. Keep exactly one native listener owner.
    """
    record_triggered = pyqtSignal()
    screenshot_triggered = pyqtSignal()

    def __init__(self, record_hk: str, screenshot_hk: str):
        super().__init__()
        self._record_hk = record_hk
        self._screenshot_hk = screenshot_hk
        self._ghk = None
        self._hotkeys = ()
        self._lock = threading.RLock()

    def start(self):
        # We use the lower-level HotKey + Listener approach because 
        # pynput's GlobalHotKeys can sometimes leave modifiers "stuck" in a 
        # pressed state on Windows, causing false triggers.
        from pynput import keyboard

        def _on_rec_activate():
            self.record_triggered.emit()

        def _on_ss_activate():
            self.screenshot_triggered.emit()

        # Parse hotkey strings into formal HotKey objects
        try:
            hk_rec = keyboard.HotKey(keyboard.HotKey.parse(self._record_hk), _on_rec_activate)
            hk_ss = keyboard.HotKey(keyboard.HotKey.parse(self._screenshot_hk), _on_ss_activate)
        except Exception as exc:
            print(f"[HotkeyListener] Invalid hotkey configuration: {exc}")
            return

        def on_press(key):
            # Pass the canonical key to the HotKey objects
            listener = self._ghk
            if listener is None:
                return
            k = listener.canonical(key)
            hk_rec.press(k)
            hk_ss.press(k)

        def on_release(key):
            # Pass the canonical key to the HotKey objects
            listener = self._ghk
            if listener is None:
                return
            k = listener.canonical(key)
            hk_rec.release(k)
            hk_ss.release(k)

        try:
            listener = keyboard.Listener(on_press=on_press, on_release=on_release)
            with self._lock:
                self._ghk = listener
                self._hotkeys = (hk_rec, hk_ss)
            listener.start()
        except Exception as exc:
            print(f"[HotkeyListener] Error binding: {exc}")
            with self._lock:
                self._ghk = None

    def reset_state(self):
        """Forget pressed modifiers after UAC/secure-desktop focus transitions."""
        with self._lock:
            for hotkey in self._hotkeys:
                state = getattr(hotkey, '_state', None)
                if state is not None:
                    state.clear()

    def isRunning(self):
        with self._lock:
            listener = self._ghk
        return bool(listener and listener.is_alive())

    def stop(self):
        with self._lock:
            listener = self._ghk
            self._ghk = None
        if listener:
            try:
                listener.stop()
                if threading.current_thread() is not listener:
                    listener.join(timeout=2.0)
            except Exception as exc:
                print(f"[HotkeyListener] Shutdown warning: {exc}")


def validate_hotkey(value: str) -> tuple[bool, str]:
    """Validate exactly the syntax/shape accepted by pynput's global listener."""
    value = (value or "").strip()
    if not value:
        return False, "Choose a shortcut."
    try:
        parsed = pynput_keyboard.HotKey.parse(value)
    except Exception as exc:
        return False, f"This shortcut cannot be registered: {exc}"
    modifier_names = {"ctrl", "ctrl_l", "ctrl_r", "alt", "alt_l", "alt_r", "shift", "shift_l", "shift_r"}
    tokens = [part.strip("<>").lower() for part in value.split("+") if part]
    if len(parsed) < 2 or not any(token in modifier_names for token in tokens):
        return False, "Use at least one modifier (Ctrl, Alt, or Shift) plus another key."
    return True, ""


class PrepareWorker(QThread):
    """Handles RecordingEngine.prepare in a background thread to avoid UI lag."""
    prepare_finished = pyqtSignal(bool)

    def __init__(self, engine, region, folder):
        super().__init__()
        self.engine = engine
        self.region = region
        self.folder = folder

    def run(self):
        try:
            success = self.engine.prepare(self.region, self.folder)
        except Exception as exc:
            print(f"[PrepareWorker] Unexpected failure: {exc}")
            self.engine.reset_failed_prepare()
            success = False
        self.prepare_finished.emit(success)


class NotificationThumbnailWorker(QThread):
    thumbnail_ready = pyqtSignal(str, bytes)

    def __init__(self, filepath: str):
        super().__init__()
        self.filepath = filepath

    def run(self):
        data = RecordingEngine.extract_thumbnail(self.filepath, size=160)
        self.thumbnail_ready.emit(self.filepath, data)


# ─────────────────────────────────────────────────────────────────────────────
#  Fallback tray icon (drawn in-process if icon.ico is missing)
# ─────────────────────────────────────────────────────────────────────────────

def _make_fallback_icon(size: int = 64) -> QIcon:
    px = QPixmap(size, size)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor(10, 132, 255))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(4, 4, size - 8, size - 8)
    p.setBrush(QColor(255, 59, 48))
    r = size // 5
    cx, cy = size // 2, size // 2
    p.drawEllipse(cx - r, cy - r, 2 * r, 2 * r)
    p.end()
    return QIcon(px)


# ─────────────────────────────────────────────────────────────────────────────
#  WWRecorderApp
# ─────────────────────────────────────────────────────────────────────────────

class WWRecorderApp:
    """
    Top-level application controller.  Owns the QApplication lifetime,
    the system tray, the hotkey listener, and the recording engine.
    """

    def __init__(self):
        self.app = QApplication(sys.argv)
        self.app.setApplicationName(APP_NAME)
        self.app.setApplicationVersion(APP_VERSION)
        self.app.setQuitOnLastWindowClosed(False)

        from PyQt6.QtGui import QFont
        self.app.setFont(QFont("Segoe UI", 10))
        self.app.setStyleSheet("""
            QWidget { font-size: 10pt; font-family: 'Segoe UI'; }
            QToolTip { font-size: 10pt; font-family: 'Segoe UI'; }
        """)

        # Ensure config & output dirs exist
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        _install_crash_logging()

        self.config = self._load_config()
        out_folder = self.config.get("output_folder") or DEFAULT_CONFIG["output_folder"]
        try:
            Path(out_folder).mkdir(parents=True, exist_ok=True)
        except (OSError, TypeError, ValueError) as exc:
            print(f"[Config] Output folder unavailable ({exc}); using the default folder.")
            out_folder = DEFAULT_CONFIG["output_folder"]
            Path(out_folder).mkdir(parents=True, exist_ok=True)
            self.config["output_folder"] = out_folder

        self.engine: RecordingEngine = RecordingEngine()
        self.app.processEvents()  # Keep UI responsive during startup
        self.pill:   PillWidget | None = None
        self.border_widget: CaptureBorderWidget | None = None
        self._saving_popup: _SavingPopup | None = None
        self._recent_panel: RecentFilesSidebar | None = None
        self._settings_sidebar: SettingsSidebar | None = None
        self._screenshot_mode = False  # True when selecting area for screenshot
        self._screenshot_in_progress = False  # Guard against re-entrant spawning
        self._recording_prepare_in_progress = False
        self._screenshot_bg_image = None
        self._screenshot_native_origin = (0, 0)
        self._screenshot_screen_transforms = []
        self._last_capture_anchor = None
        self._success_notif = None
        self._notification_thumb_worker = None
        self._notification_thumb_workers = set()

        # Annotation state
        self._global_annotation_on = False
        self._annotation_canvas = None
        self._annotation_pill = None
        self._annotate_windows = []

        # Video player windows
        self._video_player_windows = []

        # Processing state: filename being processed (shown in sidebar)
        self._processing_filename = None

        self._hotkey_listener: HotkeyListener | None = None

        self._update_status = {"available": False, "version": "", "url": "", "download_url": ""}
        self._has_manually_checked_updates = False
        self._last_tray_type = None  # 'update' or 'file' — distinguishes tray click intent
        self._update_downloading = False

        self._setup_tray()
        self._setup_dock()
        self.app.processEvents()  # Keep UI responsive during startup
        self._start_hotkey_listener()
        self.app.applicationStateChanged.connect(self._on_application_state_changed)

        self._runtime_event_timer = QTimer()
        self._runtime_event_timer.setInterval(250)
        self._runtime_event_timer.timeout.connect(self._poll_engine_events)
        self._runtime_event_timer.start()

        # Apply registry setting on startup
        self._sync_registry()

        # Silent update check on boot
        self._updater = UpdateChecker(APP_VERSION)
        self._updater.check_finished.connect(self._on_update_check_finished)
        self._updater.check_failed.connect(self._on_update_check_failed)
        self._updater.start()

    # ── Config ────────────────────────────────────────────────────────────────

    def _load_config(self) -> dict:
        if CONFIG_FILE.exists():
            try:
                with CONFIG_FILE.open("r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if not isinstance(loaded, dict):
                    raise ValueError("configuration root must be an object")
                clean = DEFAULT_CONFIG.copy()
                for key, default in DEFAULT_CONFIG.items():
                    value = loaded.get(key, default)
                    if type(value) is type(default):
                        clean[key] = value
                if not clean["output_folder"].strip():
                    clean["output_folder"] = DEFAULT_CONFIG["output_folder"]
                clean["sidebar_width"] = max(300, min(1200, clean["sidebar_width"]))
                if clean["font_size"] not in ("Default", "Large"):
                    clean["font_size"] = "Default"
                if clean["dock_edge"] not in ("left", "right", "top", "bottom"):
                    clean["dock_edge"] = "right"
                return clean
            except Exception as exc:
                print(f"[Config] Load failed ({exc}); using defaults.")
        return DEFAULT_CONFIG.copy()

    def _save_config(self) -> None:
        """Write config atomically: write to .tmp then rename, preventing corruption."""
        tmp_path = CONFIG_FILE.with_suffix('.json.tmp')
        try:
            with tmp_path.open("w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=2)
            os.replace(str(tmp_path), str(CONFIG_FILE))
        except Exception as exc:
            print(f"[Config] Save failed: {exc}")
            # Clean up temp file if rename failed
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass

    # ── Windows Registry (auto-start) ─────────────────────────────────────────

    def _sync_registry(self) -> None:
        """Add or remove WWRecorder from the Windows startup registry key."""
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                _REG_RUN_KEY,
                0,
                winreg.KEY_SET_VALUE,
            ) as key:
                if self.config.get("start_on_boot"):
                    if getattr(sys, "frozen", False):
                        exe = f'"{os.path.abspath(sys.executable)}"'
                    else:
                        exe = f'"{sys.executable}" "{os.path.abspath(__file__)}"'
                    winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, exe)
                else:
                    try:
                        winreg.DeleteValue(key, APP_NAME)
                    except FileNotFoundError:
                        pass  # Key didn't exist - that's fine
        except OSError as exc:
            print(f"[Registry] {exc}")

    # ── Tray ──────────────────────────────────────────────────────────────────

    def _setup_tray(self) -> None:
        icon_path = self._asset("icon.ico")
        icon = QIcon(icon_path) if os.path.isfile(icon_path) else _make_fallback_icon()

        self.tray = QSystemTrayIcon(icon)
        self.tray.setToolTip(f"{APP_NAME} - Ready")

        menu = QMenu()

        hk_ss_str = self.config.get("hotkey_screenshot") or DEFAULT_CONFIG["hotkey_screenshot"]
        hk_ss = hk_ss_str.replace("<", "").replace(">", "").title()
        self._act_ss = QAction(f"Take Screenshot  ({hk_ss})", menu)
        self._act_ss.triggered.connect(self._on_screenshot_requested)
        menu.addAction(self._act_ss)

        hk_rec_str = self.config.get("hotkey") or DEFAULT_CONFIG["hotkey"]
        hk_rec = hk_rec_str.replace("<", "").replace(">", "").title()
        self._act_record = QAction(f"Start Recording  ({hk_rec})", menu)
        self._act_record.triggered.connect(self._on_start_recording)
        menu.addAction(self._act_record)

        menu.addSeparator()

        act_settings = QAction("Settings", menu)
        act_settings.triggered.connect(self._open_settings)
        menu.addAction(act_settings)

        menu.addSeparator()

        act_quit = QAction("Quit WWRecorder", menu)
        act_quit.triggered.connect(self._quit)
        menu.addAction(act_quit)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.messageClicked.connect(self._on_tray_message_clicked)
        self.tray.show()

    def _on_tray_message_clicked(self) -> None:
        # Check if this was an update notification
        if self._last_tray_type == 'update' and self._update_status["available"]:
            import webbrowser
            webbrowser.open(self._update_status["url"])
            return

        if hasattr(self, "_last_saved_filepath") and self._last_saved_filepath:
            if os.path.isfile(self._last_saved_filepath):
                ext = os.path.splitext(self._last_saved_filepath)[1].lower()
                if ext in ('.png', '.jpg', '.jpeg'):
                    self._open_annotate_window(self._last_saved_filepath)
                elif ext in ('.mkv', '.mp4', '.webm', '.avi'):
                    self._open_video_player(self._last_saved_filepath)

    # ── Dock ──────────────────────────────────────────────────────────────────

    def _setup_dock(self) -> None:
        self.dock = DockWidget(self.engine, self.config)
        self.dock.screenshot_requested.connect(self._on_screenshot_requested)
        self.dock.record_requested.connect(self._on_dock_record)
        self.dock.annotate_requested.connect(self._toggle_global_annotator)
        self.dock.files_requested.connect(self._on_files_requested)
        self.dock.settings_requested.connect(self._open_settings)
        self.dock.show()

    def _on_screenshot_requested(self) -> None:
        """Open the selection overlay in screenshot mode with instant freeze."""
        # Suppress if user is actively rebinding a hotkey
        if self._is_hotkey_listening():
            return
        if self.engine.is_busy() or self._recording_prepare_in_progress:
            return
        if self._screenshot_in_progress:
            return
        if hasattr(self, '_overlay') and self._overlay and self._overlay.isVisible():
            return

        self._screenshot_in_progress = True

        # Hide any visible tooltips so they don't appear in the frozen screenshot
        QToolTip.hideText()
        self._dismiss_success_notification()

        # A dock-button click happens while the hover dock is still expanded.
        # Collapse it synchronously, then give DWM one repaint interval before
        # freezing the desktop so the expanded panel is never baked in.
        dock_collapsed = bool(
            getattr(self, 'dock', None)
            and self.dock.collapse_for_screenshot()
        )
        if dock_collapsed:
            QTimer.singleShot(100, self._perform_screenshot_freeze)
        else:
            self._perform_screenshot_freeze()

    def _perform_screenshot_freeze(self) -> None:
        """Execute the actual screen freeze and show the SelectionOverlay."""
        QToolTip.hideText()  # Safety net: ensure no tooltips in capture
        # Instant Freeze: Capture before showing overlay
        try:
            pil_img = self.engine.grab_full_desktop()
            self._screenshot_bg_image = pil_img
            self._screenshot_screen_transforms = qt_screen_transforms(QApplication.screens())
            if self._screenshot_screen_transforms:
                self._screenshot_native_origin = (
                    min(s.native_left for s in self._screenshot_screen_transforms),
                    min(s.native_top for s in self._screenshot_screen_transforms),
                )
            # Build the frozen selection preview with the same piecewise map as
            # the final crop. Drawing the raw virtual bitmap with one stretch
            # would visibly shift monitor boundaries on mixed-DPI desktops.
            logical_left = min(s.logical_left for s in self._screenshot_screen_transforms)
            logical_top = min(s.logical_top for s in self._screenshot_screen_transforms)
            logical_right = max(s.logical_left + s.logical_width for s in self._screenshot_screen_transforms)
            logical_bottom = max(s.logical_top + s.logical_height for s in self._screenshot_screen_transforms)
            full_region = {"left": logical_left, "top": logical_top,
                           "width": logical_right - logical_left,
                           "height": logical_bottom - logical_top}
            preview_plan = build_capture_plan(full_region, self._screenshot_screen_transforms)
            preview = compose_frozen_desktop(pil_img, self._screenshot_native_origin, preview_plan)
            rgba_data = preview.convert("RGBA").tobytes("raw", "RGBA")
            qimg = QImage(rgba_data, preview.width, preview.height, QImage.Format.Format_RGBA8888)
            self._screenshot_bg_pixmap = QPixmap.fromImage(qimg)
        except Exception as e:
            print(f"[Screenshot] Freeze failed: {e}")
            import traceback
            traceback.print_exc()
            self._screenshot_bg_pixmap = None
            self._screenshot_bg_image = None

        self._screenshot_mode = True
        try:
            self._overlay = SelectionOverlay(mode="screenshot")
            if self._screenshot_bg_pixmap:
                self._overlay.set_background(self._screenshot_bg_pixmap)

            self._overlay.selectionChanged.connect(self._on_screenshot_selection)
            self._overlay.show()
            self._overlay.raise_()
            self._overlay.activateWindow()
        except Exception as exc:
            self._screenshot_mode = False
            self._screenshot_in_progress = False
            self._screenshot_bg_pixmap = None
            self._screenshot_bg_image = None
            self._overlay = None
            print(f"[Screenshot] Could not open selection overlay: {exc}")
            QMessageBox.critical(None, "Screenshot Failed", f"Could not open screen selection:\n{exc}")

    def _on_screenshot_selection(self, region: dict) -> None:
        """Handle area selected for screenshot by cropping the frozen capture."""
        if hasattr(self, '_overlay') and self._overlay:
            self._overlay.close()
            self._overlay = None

        self._screenshot_mode = False
        self._screenshot_in_progress = False

        if not region:
            self._screenshot_bg_pixmap = None
            self._screenshot_bg_image = None
            return  # Cancelled

        if not hasattr(self, '_screenshot_bg_pixmap') or not self._screenshot_bg_pixmap:
            # Fallback to live capture if freeze failed (should not happen normally)
            self._on_screenshot_selection_live_fallback(region)
            return

        r = QRect(int(region["left"]), int(region["top"]), int(region["width"]), int(region["height"]))
        if r.width() > 0 and r.height() > 0:
            try:
                source = self._screenshot_bg_image
                if source is None:
                    raise RuntimeError("Frozen desktop image is unavailable.")
                plan = build_capture_plan(region, self._screenshot_screen_transforms)
                cropped_image = compose_frozen_desktop(source, self._screenshot_native_origin, plan)
                self._last_capture_anchor = r.center()
                self._screenshot_bg_pixmap = None
                self._screenshot_bg_image = None

                out_dir = self.config.get("output_folder", DEFAULT_CONFIG["output_folder"])
                saved_path = self.engine.take_screenshot_image(cropped_image, out_dir)
            except Exception as exc:
                self._screenshot_bg_pixmap = None
                self._screenshot_bg_image = None
                QMessageBox.critical(None, "Screenshot Failed", str(exc))
                return

            self._last_saved_filepath = saved_path
            
            # Copy to clipboard
            if self.config.get("copy_to_clipboard", True):
                if saved_path and os.path.exists(saved_path):
                    mime = QMimeData()
                    mime.setUrls([QUrl.fromLocalFile(saved_path)])
                    img = QImage(saved_path)
                    if not img.isNull():
                        mime.setImageData(img)
                    QApplication.clipboard().setMimeData(mime)
                
            self._last_tray_type = 'file'
            # Show custom in-app success notification
            self._show_success_notification(
                saved_path,
                "Screenshot Saved \u2714",
                Path(saved_path).name,
                self._load_thumbnail_pixmap(saved_path),
            )
            # Refresh recent files if open
            if self._recent_panel and self._recent_panel.isVisible():
                self._recent_panel.refresh()

    def _on_screenshot_selection_live_fallback(self, region: dict) -> None:
        """Old live capture logic as fallback."""
        r = QRect(int(region["left"]), int(region["top"]), int(region["width"]), int(region["height"]))
        if r.width() > 0 and r.height() > 0:
            plan = build_capture_plan(region, qt_screen_transforms(QApplication.screens()))
            self._last_capture_anchor = r.center()
            out_dir = self.config.get("output_folder", DEFAULT_CONFIG["output_folder"])
            saved_path = self.engine.take_screenshot(plan, out_dir)
            self._last_saved_filepath = saved_path
            
            # ... clipboard and tray logic ...
            if self.config.get("copy_to_clipboard", True):
                if saved_path and os.path.exists(saved_path):
                    mime = QMimeData()
                    mime.setUrls([QUrl.fromLocalFile(saved_path)])
                    img = QImage(saved_path)
                    if not img.isNull():
                        mime.setImageData(img)
                    QApplication.clipboard().setMimeData(mime)
            self.tray.showMessage("Screenshot Saved", f"{Path(saved_path).name}\nClick to view.", self._make_thumbnail_icon(saved_path), 4000)
            if self._recent_panel and self._recent_panel.isVisible(): self._recent_panel.refresh()

    def _on_dock_record(self) -> None:
        """Toggle recording from the dock button."""
        if self.engine.is_recording():
            # Stop recording
            if self.pill:
                self.pill._initiate_stop()
        else:
            # A sidebar closing on focus loss can consume the same mouse event.
            # Close it synchronously and start selection on the next GUI tick.
            self._dismiss_sidebars_for_recording()
            QTimer.singleShot(0, self._on_start_recording)

    def _on_files_requested(self) -> None:
        """Toggle the recent files sidebar (cached for performance)."""
        if self._recent_panel and self._recent_panel.isVisible():
            self._recent_panel.close_panel()
            return

        # Close settings panel if open
        if self._settings_sidebar and self._settings_sidebar.isVisible():
            self._settings_sidebar.close_panel()

        output_folder = self.config.get("output_folder", DEFAULT_CONFIG["output_folder"])
        fs_mode = self.config.get("font_size", "Default")
        edge = self.config.get("dock_edge", "right")
        close_on_focus = self.config.get("close_on_focus_loss", True)

        # PERF-001: Reuse cached sidebar if config hasn't changed
        needs_rebuild = (
            self._recent_panel is None
            or getattr(self._recent_panel, '_output_folder', None) != output_folder
            or getattr(self._recent_panel, '_font_size_mode', None) != fs_mode
            or getattr(self._recent_panel, '_edge', None) != edge
        )

        if needs_rebuild:
            if self._recent_panel:
                self._recent_panel.close()
                self._recent_panel.deleteLater()

            self._recent_panel = RecentFilesSidebar(
                output_folder,
                font_size_mode=fs_mode,
                edge=edge,
                close_on_focus_loss=close_on_focus,
            )
            self._recent_panel.settings_requested.connect(self._open_settings)
            self._recent_panel.annotate_file_requested.connect(self._open_annotate_window)
            self._recent_panel.play_video_requested.connect(self._open_video_player)
            self._recent_panel.edit_file_requested.connect(self._open_media_editor)
            self._recent_panel.rename_needed.connect(self._safe_rename)
            self._recent_panel.width_changed.connect(self._on_sidebar_resized)
        else:
            # Reuse existing panel — update focus loss setting
            # (refresh is deferred until after processing state is synced below)
            self._recent_panel.set_close_on_focus_loss(close_on_focus)

        # Always reconnect closed signal (it fires once per close cycle)
        try:
            self._recent_panel.closed.disconnect()
        except TypeError:
            pass
        self._recent_panel.closed.connect(self._on_recent_panel_closed)

        # Sync processing state BEFORE refresh to avoid race conditions.
        # The processing file must be set before _load_files() starts the background scan,
        # otherwise the scanner won't know to exclude the processing file.
        if self._processing_filename:
            self._recent_panel.set_processing_file(self._processing_filename)
        else:
            # Clear any stale processing state from a previous session
            self._recent_panel.clear_processing_file()

        # Refresh file list if reusing cached panel (needs_rebuild panels auto-load in __init__)
        if not needs_rebuild:
            self._recent_panel.refresh()
        
        # Compact defaults
        def_w = 480 if fs_mode == "Large" else 380
        min_w = 480 if fs_mode == "Large" else 380
        w = max(self.config.get("sidebar_width", def_w), min_w)
        self._recent_panel.resize(w, 10) # height gets overridden
        self._recent_panel.open_panel()

    def _on_recent_panel_closed(self):
        """Handle recent panel close — keep instance cached for reuse."""
        pass  # PERF-001: Don't destroy — keep cached for next open

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._on_start_recording()
        elif reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._on_files_requested()

    # ── Hotkey ────────────────────────────────────────────────────────────────

    def _start_hotkey_listener(self) -> None:
        if self._hotkey_listener and self._hotkey_listener.isRunning():
            self._hotkey_listener.stop()

        hk_rec = self.config.get("hotkey", DEFAULT_CONFIG["hotkey"])
        hk_ss = self.config.get("hotkey_screenshot", DEFAULT_CONFIG["hotkey_screenshot"])
        self._hotkey_listener = HotkeyListener(hk_rec, hk_ss)
        self._hotkey_listener.record_triggered.connect(self._on_hotkey_triggered)
        self._hotkey_listener.screenshot_triggered.connect(self._on_screenshot_requested)
        self._hotkey_listener.start()

    def _on_application_state_changed(self, state) -> None:
        if state == Qt.ApplicationState.ApplicationActive and self._hotkey_listener:
            self._hotkey_listener.reset_state()

    def _poll_engine_events(self) -> None:
        for kind, message in self.engine.drain_runtime_events():
            if kind == 'audio_error':
                self.tray.showMessage("Audio device disconnected", friendly_error(message), self.tray.icon(), 8000)
            elif kind == 'audio_reconnected':
                self.tray.showMessage("Audio device changed", message, self.tray.icon(), 5000)

    def _on_hotkey_triggered(self) -> None:
        """
        If a recording is active: toggle pause/resume.
        Otherwise:  open the region-picker and start a new recording.
        Suppressed when a hotkey input is actively listening for a new binding.
        """
        # Suppress hotkey if user is actively rebinding a key in settings
        if self._is_hotkey_listening():
            return
        if self.engine.is_recording():
            if self.pill:
                self.pill.toggle_pause()
        else:
            self._on_start_recording()

    def _is_hotkey_listening(self) -> bool:
        """Check if any hotkey input widget in the settings sidebar is currently listening."""
        if not self._settings_sidebar or not self._settings_sidebar.isVisible():
            return False
        # Search for _HotkeyInput widgets that are in listening mode
        try:
            from dock_widget import _HotkeyInput
            for widget in self._settings_sidebar.findChildren(_HotkeyInput):
                if hasattr(widget, '_listening') and widget._listening:
                    return True
        except Exception:
            pass
        return False

    # ── Recording lifecycle ───────────────────────────────────────────────────

    def _dismiss_sidebars_for_recording(self) -> None:
        """Hide navigation surfaces immediately before opening capture selection."""
        for panel in (self._settings_sidebar, self._recent_panel):
            if panel and panel.isVisible():
                panel.close_panel(animate=False)

    def _on_start_recording(self) -> None:
        if (self.engine.is_busy() or self._screenshot_in_progress
                or self._recording_prepare_in_progress):
            return  # Already recording

        if hasattr(self, '_overlay') and self._overlay and self._overlay.isVisible():
            return

        self._dismiss_sidebars_for_recording()
        self._overlay = SelectionOverlay()
        self._overlay.selectionChanged.connect(self._on_selection_made)
        self._overlay.show()
        self._overlay.raise_()
        self._overlay.activateWindow()

    def _on_selection_made(self, region: dict) -> None:
        if not region:  # Cancelled
            if hasattr(self, '_overlay') and self._overlay:
                self._overlay.close()
                self._overlay = None
            if hasattr(self, 'pill') and self.pill:
                self.pill.close()
                self.pill = None
            # Discard any pre-warmed state
            self.engine.discard()
            return

        # Just store the latest region — do NOT prepare the engine yet.
        # The user might resize/move the selection multiple times.
        # Engine preparation happens once in _do_start when user clicks "Start".
        self._current_region = region
        
        # Initialize audio config from defaults only on first selection
        if not getattr(self, '_audio_config_initialized', False):
            self.engine.set_system_audio(self.config.get("default_system_audio", False))
            self.engine.set_mic(self.config.get("default_mic", False))
            self._audio_config_initialized = True

        if not getattr(self, 'pill', None) or not self.pill.isVisible():
            self.pill = PillWidget(self.engine, self.config, pre_record=True)
            self.pill.settings_requested.connect(self._open_settings)
            self.pill.stopped.connect(self._on_recording_stopped)
            self.pill.save_completed.connect(self._on_save_completed)
            self.pill.start_requested.connect(self._do_start)
            # Annotation signals
            self.pill.annotate_requested.connect(self._toggle_global_annotator)
            self.pill.annotation_toggled.connect(self._on_annotation_toggled)
            self.pill.show()
            
            # Sync initial annotation state to recording pill
            if getattr(self, '_global_annotation_on', False):
                if hasattr(self.pill, '_btn_annotate'):
                    self.pill._btn_annotate.setChecked(True)

    def _do_start(self) -> None:
        if self._recording_prepare_in_progress:
            return

        # Close the overlay first — we have the final region stored
        if hasattr(self, '_overlay') and self._overlay:
            self._overlay.close()
            self._overlay = None
        region = getattr(self, '_current_region', None)
        if region:
            # PillWidget.closeEvent means discard. Keep the pre-record pill alive
            # so discard cannot race RecordingEngine.prepare().
            self._recording_prepare_in_progress = True
            if self.pill:
                self.pill.set_preparing(True)
            self._audio_config_initialized = False  # Reset for next recording session
            self._start_recording(region)

    def _start_recording(self, region: dict) -> None:
        output_folder = self.config.get("output_folder", DEFAULT_CONFIG["output_folder"])

        physical_region = _normalized_capture_plan(
            build_capture_plan(region, qt_screen_transforms(QApplication.screens()))
        )
        if physical_region is None:
            self._recording_prepare_in_progress = False
            self._current_region = None
            if self.pill:
                self.pill._stopping = True
                self.pill.close()
                self.pill = None
            QMessageBox.warning(
                None, APP_NAME,
                "The selected recording area is too small. Select an area at least 32 × 32 pixels.",
            )
            return
        self._last_capture_anchor = QRect(region["left"], region["top"], region["width"], region["height"]).center()

        # PERF-005: Use PrepareWorker to avoid blocking UI during FFmpeg startup
        self._pending_region = region  # Store logical region for border widget
        self._prepare_worker = PrepareWorker(self.engine, physical_region, output_folder)
        self._prepare_worker.prepare_finished.connect(self._on_recording_prepared)
        self._prepare_worker.start()

    def _on_recording_prepared(self, ok: bool) -> None:
        """Callback after background engine preparation completes."""
        self._recording_prepare_in_progress = False
        if not ok:
            if self.pill:
                self.pill.set_preparing(False)
            # UX-002: Differentiate disk space errors from FFmpeg errors
            if getattr(self.engine, '_low_disk_space', None) == 'critical':
                self.tray.showMessage(
                    APP_NAME, "Cannot start recording — disk space is critically low (<100 MB free).",
                    self.tray.icon(), 6000,
                )
            else:
                self.tray.showMessage(
                    APP_NAME, "Failed to start recording - is FFmpeg installed?",
                    self.tray.icon(), 4000,
                )
            return

        # Transition from prepared to active recording
        self.engine._is_prewarming = False
        self.engine.resume()
        if self.pill:
            self.pill.set_recording_mode()

        region = getattr(self, '_pending_region', None)

        # UX-002: Show low disk space warning (recording still starts)
        if getattr(self.engine, '_low_disk_space', None) == 'warning':
            self.tray.showMessage(
                APP_NAME, "⚠ Low disk space (<500 MB). Recording may stop unexpectedly.",
                self.tray.icon(), 5000,
            )

        self.tray.setToolTip(f"{APP_NAME} - Recording…")
        self._act_record.setEnabled(False)

        # Reuse existing pill if available from pre-record
        if not self.pill:
            self.pill = PillWidget(self.engine, self.config)
            self.pill.stopped.connect(self._on_recording_stopped)
            self.pill.save_completed.connect(self._on_save_completed)
            self.pill.settings_requested.connect(self._open_settings)
            self.pill.annotate_requested.connect(self._toggle_global_annotator)
            self.pill.annotation_toggled.connect(self._on_annotation_toggled)
        
        # Update dock recording state
        if hasattr(self, 'dock'):
            self.dock.set_recording_state(True)
            
        self.pill.show()

        # Outline handles logical coordinates (Qt handles the scaling)
        self.border_widget = CaptureBorderWidget(region)
        self.border_widget.show()

        # Store logical region for annotation canvas placement
        self._annotation_region = region

    def _on_recording_stopped(self, filepath: str) -> None:
        """Called immediately when user clicks Stop/Discard — clears all visual UI."""
        was_recording = self.border_widget is not None
        if self.border_widget:
            self.border_widget.close()
            self.border_widget = None

        if hasattr(self, '_overlay') and self._overlay:
            self._overlay.close()
            self._overlay = None

        self._act_record.setEnabled(True)

        # Cleanup annotation canvas
        self._destroy_annotation_canvas()

        # Disable annotation UI on pill if it's still alive
        if self.pill and hasattr(self.pill, 'disable_annotation'):
            self.pill.disable_annotation()

        # Update dock recording state
        if hasattr(self, 'dock'):
            self.dock.set_recording_state(False)

        if filepath == "<SAVING>":
            # Muxing in progress — pill stays alive (hidden) to run _StopWorker.
            # Notification will come from _on_save_completed.
            self.tray.setToolTip(f"{APP_NAME} - Processing…")
            # Establish the media lockout before constructing any optional UI.
            # A popup failure must never expose FFmpeg's half-written output as
            # a playable Recent Files row.
            expected_name = os.path.basename(self.engine._output_path) if self.engine._output_path else "Recording"
            self._processing_filename = expected_name

            if self._recent_panel and self._recent_panel.isVisible():
                self._recent_panel.set_processing_file(expected_name)

            try:
                if not self._saving_popup:
                    self._saving_popup = _SavingPopup()
                self._saving_popup.show_saving(self._last_capture_anchor)
            except Exception as exc:
                self._saving_popup = None
                print(f"[WWRecorder] Processing popup failed: {exc}")
                self.tray.showMessage(
                    APP_NAME,
                    "Your recording is still processing. It will appear in Files when ready.",
                    self.tray.icon(), 5000,
                )
            return

        # For <DISCARDED> and other immediate results, clean up pill now
        self.pill = None
        self.tray.setToolTip(f"{APP_NAME} - Ready")

        if filepath == "<DISCARDED>":
            self._last_saved_filepath = None
            if was_recording:
                self.tray.showMessage(
                    APP_NAME, "Recording discarded.",
                    self.tray.icon(), 3000,
                )
        else:
            self._last_saved_filepath = None

    def _on_save_completed(self, filepath: str) -> None:
        """Called when background muxing finishes — shows notification, copies to clipboard."""
        if self._saving_popup:
            self._saving_popup.hide_saving()
            self._saving_popup = None
        self.pill = None
        self.tray.setToolTip(f"{APP_NAME} - Ready")

        # Clear processing state at app level and in sidebar
        self._processing_filename = None
        if self._recent_panel and self._recent_panel.isVisible():
            self._recent_panel.clear_processing_file()
            self._recent_panel.refresh()

        if filepath and os.path.isfile(filepath):
            self._last_saved_filepath = filepath
            size_mb = os.path.getsize(filepath) / (1024 * 1024)

            # Copy to clipboard
            if self.config.get("copy_to_clipboard", True):
                mime = QMimeData()
                mime.setUrls([QUrl.fromLocalFile(filepath)])
                QApplication.clipboard().setMimeData(mime)

            self._last_tray_type = 'file'
            # Show custom in-app success notification
            self._show_success_notification(
                filepath,
                "Recording Saved \u2714",
                f"{os.path.basename(filepath)}  ({size_mb:.1f} MB)",
                QPixmap(),
            )
            self._notification_thumb_worker = NotificationThumbnailWorker(filepath)
            self._notification_thumb_worker.thumbnail_ready.connect(
                self._on_notification_thumbnail_ready
            )
            worker = self._notification_thumb_worker
            self._notification_thumb_workers.add(worker)
            worker.finished.connect(
                lambda: (
                    self._notification_thumb_workers.discard(worker),
                    setattr(self, '_notification_thumb_worker', None)
                    if self._notification_thumb_worker is worker else None,
                )
            )
            self._notification_thumb_worker.start()
        else:
            self._last_saved_filepath = None
            self.tray.showMessage(
                "Recording Save Failed",
                f"{getattr(self.engine, '_last_error', 'No output file was created.')}\n"
                "Recovery media was kept in your Windows temporary folder.",
                self.tray.icon(), 8000,
            )

    def _make_thumbnail_icon(self, image_path: str) -> QIcon:
        """Create a QIcon from an image file for use in tray notifications."""
        try:
            px = QPixmap(image_path)
            if not px.isNull():
                scaled = px.scaled(64, 64, Qt.AspectRatioMode.KeepAspectRatio,
                                   Qt.TransformationMode.SmoothTransformation)
                return QIcon(scaled)
        except Exception:
            pass
        return self.tray.icon()

    def _make_video_thumbnail_icon(self, video_path: str) -> QIcon:
        """Create a QIcon from a video's first frame for tray notifications."""
        try:
            thumb_bytes = RecordingEngine.extract_thumbnail(video_path, size=64)
            if thumb_bytes:
                px = QPixmap()
                px.loadFromData(thumb_bytes, "JPEG")
                if not px.isNull():
                    return QIcon(px)
        except Exception:
            pass
        # Fallback: use app icon
        return self.tray.icon()

    def _load_thumbnail_pixmap(self, image_path: str) -> QPixmap:
        """Load a QPixmap from an image file for the notification thumbnail."""
        try:
            px = QPixmap(image_path)
            if not px.isNull():
                return px.scaled(160, 160, Qt.AspectRatioMode.KeepAspectRatio,
                                 Qt.TransformationMode.SmoothTransformation)
        except Exception:
            pass
        return QPixmap()

    def _load_video_thumbnail_pixmap(self, video_path: str) -> QPixmap:
        """Load a QPixmap from a video's first frame for the notification thumbnail."""
        try:
            thumb_bytes = RecordingEngine.extract_thumbnail(video_path, size=160)
            if thumb_bytes:
                px = QPixmap()
                px.loadFromData(thumb_bytes, "JPEG")
                if not px.isNull():
                    return px
        except Exception:
            pass
        return QPixmap()

    def _on_notification_thumbnail_ready(self, filepath: str, data: bytes) -> None:
        notification = self._success_notif
        if (not notification or not notification.isVisible()
                or notification._filepath != filepath or not data):
            return
        pixmap = QPixmap()
        if pixmap.loadFromData(data, "JPEG"):
            notification.set_thumbnail(pixmap)

    def _show_success_notification(self, filepath: str, title: str, subtitle: str, thumb_pixmap: QPixmap = None):
        """Show a custom in-app success notification with Open and Rename buttons."""
        self._dismiss_success_notification(delete=True)

        notification = _SuccessNotification(
            filepath, title, subtitle, thumb_pixmap, duration=6000
        )
        self._success_notif = notification
        notification.destroyed.connect(
            lambda _obj=None, item=notification: self._forget_success_notification(item)
        )
        notification.open_clicked.connect(self._on_notif_open)
        notification.renamed.connect(self._on_notif_renamed)
        notification.rename_needed.connect(self._safe_rename)
        notification.show_notification(self._last_capture_anchor)

    def _forget_success_notification(self, notification) -> None:
        if self._success_notif is notification:
            self._success_notif = None

    def _dismiss_success_notification(self, delete: bool = False) -> None:
        """Close a notification even if Qt already deleted its C++ object."""
        notification = getattr(self, '_success_notif', None)
        self._success_notif = None
        if notification is None:
            return
        try:
            if notification.isVisible():
                notification.close()
            if delete:
                notification.deleteLater()
        except RuntimeError:
            pass

    def _on_notif_open(self, filepath: str):
        """Handle Open button click from success notification."""
        if not _is_safe_media_path(filepath):
            return
        ext = os.path.splitext(filepath)[1].lower()
        if ext in ('.png', '.jpg', '.jpeg'):
            self._open_annotate_window(filepath)
        elif ext in ('.mkv', '.mp4', '.webm', '.avi'):
            self._open_video_player(filepath)

    def _on_notif_renamed(self, old_path: str, new_path: str):
        """Handle successful inline rename from the notification."""
        self._last_saved_filepath = new_path
        # Refresh recent files sidebar if it's open
        if self._recent_panel and self._recent_panel.isVisible():
            self._recent_panel.refresh()

    def _safe_rename(self, old_path: str, new_path: str):
        """Rename a file safely, releasing any open VideoPlayerWindow lock first.

        Steps:
          1. Find any player window that has old_path loaded.
          2. Tell it to release the file (setSource empty).
          3. Attempt os.rename with a short retry loop (player may need a tick to release).
          4. Reload the player with new_path.
          5. Refresh the recent-files sidebar.
          6. Show a clear error toast if still locked after retries.
        """
        import time

        old = Path(old_path)
        new = Path(new_path)
        invalid_chars = set('<>:"/\\|?*')
        reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                    *(f"LPT{i}" for i in range(1, 10))}
        invalid_name = (
            not new.stem or new.name.endswith((" ", "."))
            or any(ch in invalid_chars or ord(ch) < 32 for ch in new.name)
            or new.stem.upper() in reserved
            or old.parent.resolve() != new.parent.resolve()
            or old.suffix.lower() != new.suffix.lower()
        )
        if invalid_name:
            self._show_rename_error("Choose a valid filename without path characters or Windows reserved names.")
            return

        # Find player windows with this file open
        locked_windows = [
            w for w in self._video_player_windows
            if getattr(w, '_filepath', '').lower() == old_path.lower()
        ]

        # Release file lock in all matching players
        for win in locked_windows:
            try:
                win._player.setSource(QUrl())
            except Exception:
                pass

        # Retry os.rename up to 8 times (~2s) to give Windows time to release the handle
        max_tries = 8
        delay = 0.25
        last_err = None
        for attempt in range(max_tries):
            try:
                os.rename(old_path, new_path)
                last_err = None
                break
            except PermissionError as e:
                last_err = e
                self.app.processEvents()
                time.sleep(delay)
            except FileExistsError:
                # Target already exists
                self._show_rename_error(f"❌ Rename failed: '{Path(new_path).name}' already exists.")
                # Re-bind player source with original path without resetting edit mode
                for win in locked_windows:
                    try:
                        win._player.setSource(QUrl.fromLocalFile(old_path))
                    except Exception:
                        pass
                return
            except Exception as e:
                last_err = e
                break

        if last_err is not None:
            print(f"[Rename] Failed after {max_tries} attempts: {last_err}")
            self._show_rename_error(
                f"❌ Rename failed — file is in use by another process.\n"
                f"Close any app using '{Path(old_path).name}' and try again."
            )
            # Restore only the media source.  Calling _load_video would erase
            # the current overlay and cut lists.
            for win in locked_windows:
                try:
                    win.restore_source_after_rename(old_path)
                except Exception:
                    pass
            return

        # Success — update the source without resetting in-progress edits.
        for win in locked_windows:
            try:
                win.restore_source_after_rename(new_path)
            except Exception:
                pass

        # Update notification widget filepath if it's the same file
        if self._success_notif and getattr(self._success_notif, '_filepath', '').lower() == old_path.lower():
            self._success_notif._filepath = new_path
            self._success_notif.renamed.emit(old_path, new_path)

        # Refresh recent files sidebar
        self._last_saved_filepath = new_path if getattr(self, '_last_saved_filepath', '').lower() == old_path.lower() else getattr(self, '_last_saved_filepath', '')
        if self._recent_panel and self._recent_panel.isVisible():
            self._recent_panel.refresh()
        print(f"[Rename] OK: '{Path(old_path).name}' → '{Path(new_path).name}'")

    def _show_rename_error(self, message: str):
        """Show a non-blocking error toast for rename failures."""
        from PyQt6.QtWidgets import QMessageBox
        msg = QMessageBox(self._tray_icon_widget if hasattr(self, '_tray_icon_widget') else None)
        msg.setWindowTitle("Rename Failed")
        msg.setText(message)
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setWindowFlags(Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Dialog)
        msg.exec()

    # ── Update Checker ────────────────────────────────────────────────────────

    def _on_update_check_finished(self, available: bool, version: str, url: str, download_url: str):
        self._update_status = {"available": available, "version": version, "url": url, "download_url": download_url}
        
        # Best Practice: Avoid auto-updating if user has explicitly ignored this version
        # (Useful if they manually downgraded because of a bug in the new version)
        if available and version == self.config.get("ignored_update_version"):
            # Still set status for settings sidebar if it's open, but don't notify or auto-download
            if self._settings_sidebar and self._settings_sidebar.isVisible():
                self._settings_sidebar.set_update_status(available, version, url)
            return

        if available:
            self._last_tray_type = 'update'
            self.tray.showMessage(
                "Update Available!",
                f"WWRecorder {version} is now available.\nClick to update from Microsoft Store.",
                self.tray.icon(),
                10000
            )
        
        # If settings is open, tell it!
        if self._settings_sidebar and self._settings_sidebar.isVisible():
            self._settings_sidebar.set_update_status(available, version, url)

    def _on_update_check_failed(self, message: str):
        if self._settings_sidebar and self._settings_sidebar.isVisible():
            self._settings_sidebar.set_update_error(message)

    def _on_manual_update_check_finished(self, available: bool, version: str, url: str, download_url: str = ""):
        self._has_manually_checked_updates = True

    # _on_tray_message_clicked is defined above at line ~322

    def _cancel_pre_record(self) -> None:
        is_pre_record = bool(self.pill and getattr(self.pill, '_pre_record', False))
        is_record_selection = bool(
            getattr(self, '_overlay', None) and not self._screenshot_mode
        )
        if not is_pre_record and not is_record_selection:
            return
        if hasattr(self, '_overlay') and self._overlay:
            self._overlay.close()
            self._overlay = None
        if hasattr(self, 'pill') and self.pill and getattr(self.pill, '_pre_record', False):
            self.pill.close()
            self.pill = None
        
        if self.engine.is_prewarming():
            self.engine.discard()

    # ── Annotation Handlers ───────────────────────────────────────────────────

    def _toggle_global_annotator(self) -> None:
        """Called from dock button to toggle the global annotator."""
        self._on_annotation_toggled(not self._global_annotation_on)

    def _on_annotation_toggled(self, enabled: bool) -> None:
        """Create or toggle the global annotation canvas and pill."""
        self._global_annotation_on = enabled
        
        # Sync the recording pill visually if active
        if self.pill:
            if hasattr(self.pill, 'set_annotation_active'):
                self.pill.set_annotation_active(enabled)
            elif getattr(self.pill, '_btn_annotate', None):
                self.pill._btn_annotate.setChecked(enabled)
                
        # Sync the dock widget
        if hasattr(self, 'dock') and self.dock:
            if hasattr(self.dock, 'set_annotation_active'):
                self.dock.set_annotation_active(enabled)

        if enabled:
            if not self._annotation_canvas:
                from annotation_tool import AnnotationCanvas, AnnotationPill
                
                # Full screen canvas
                self._annotation_canvas = AnnotationCanvas()
                
                # Floating tool pill
                self._annotation_pill = AnnotationPill()
                
                # Wire them together natively
                self._annotation_pill.tool_changed.connect(self._annotation_canvas.set_tool)
                self._annotation_pill.thickness_changed.connect(self._annotation_canvas.set_thickness)
                from PyQt6.QtGui import QColor
                self._annotation_pill.color_changed.connect(lambda hx: self._annotation_canvas.set_color(QColor(hx)))
                self._annotation_pill.undo_requested.connect(self._annotation_canvas.undo)
                self._annotation_pill.redo_requested.connect(self._annotation_canvas.redo)
                self._annotation_pill.clear_requested.connect(self._annotation_canvas.clear_all)
                self._annotation_canvas.undo_redo_state_changed.connect(self._annotation_pill.update_undo_redo_state)
                self._annotation_canvas.pause_requested.connect(lambda: self._annotation_pill._btn_pause.toggle())
                self._annotation_pill.pause_toggled.connect(self._annotation_canvas.set_annotation_paused)
                
                # Close destroys the annotator
                self._annotation_pill.close_requested.connect(self._destroy_annotation_canvas)
                self._annotation_canvas.close_requested.connect(self._destroy_annotation_canvas)

            self._annotation_canvas.set_interactive(True)
            self._annotation_canvas.show()
            self._annotation_canvas.raise_()
            self._annotation_pill.show()
            self._annotation_pill.raise_()
        else:
            self._destroy_annotation_canvas()

    def _destroy_annotation_canvas(self) -> None:
        """Completely close and destroy the global annotator."""
        self._global_annotation_on = False
        if self.pill:
            if hasattr(self.pill, 'set_annotation_active'):
                self.pill.set_annotation_active(False)
            elif getattr(self.pill, '_btn_annotate', None):
                self.pill._btn_annotate.setChecked(False)
            
        if hasattr(self, 'dock') and self.dock:
            if hasattr(self.dock, 'set_annotation_active'):
                self.dock.set_annotation_active(False)

        if self._annotation_pill:
            self._annotation_pill.close()
            self._annotation_pill.deleteLater()
            self._annotation_pill = None
            
        if self._annotation_canvas:
            self._annotation_canvas.close()
            self._annotation_canvas.deleteLater()
            self._annotation_canvas = None

    def _open_annotate_window(self, filepath: str) -> None:
        """Open the WWR: Image Editor screenshot editor. Supports multiple windows."""
        from annotation_tool import AnnotateWindow
        win = AnnotateWindow(filepath)
        self._annotate_windows.append(win)
        win.closed.connect(lambda w=win: self._on_annotate_window_closed(w))
        win.show()
        win.raise_()
        win.activateWindow()

    def _on_annotate_window_closed(self, window) -> None:
        if window in self._annotate_windows:
            self._annotate_windows.remove(window)
        # Refresh recent files if open (in case image was saved with annotations)
        if self._recent_panel and self._recent_panel.isVisible():
            self._recent_panel.refresh()

    def _open_video_player(self, filepath: str) -> None:
        """Open the in-app video player. Supports multiple windows."""
        from video_editor import VideoPlayerWindow
        output_folder = self.config.get("output_folder", DEFAULT_CONFIG["output_folder"])
        win = VideoPlayerWindow(filepath, output_folder)
        self._video_player_windows.append(win)
        win.closed.connect(self._on_video_player_closed)
        win.show()
        win.raise_()
        win.activateWindow()

    def _open_media_editor(self, filepath: str) -> None:
        """Open a file directly in WWRecorder's relevant editing surface."""
        ext = Path(filepath).suffix.lower()
        if ext in ('.png', '.jpg', '.jpeg'):
            self._open_annotate_window(filepath)
            return
        if ext not in ('.mkv', '.mp4', '.webm', '.avi'):
            return
        from video_editor import VideoPlayerWindow
        output_folder = self.config.get("output_folder", DEFAULT_CONFIG["output_folder"])
        win = VideoPlayerWindow(filepath, output_folder, start_in_edit_mode=True)
        self._video_player_windows.append(win)
        win.closed.connect(self._on_video_player_closed)
        win.show()
        win.raise_()
        win.activateWindow()

    def _on_video_player_closed(self, window) -> None:
        if window in self._video_player_windows:
            self._video_player_windows.remove(window)
        # Refresh recent files if open (in case edited video was saved)
        if self._recent_panel and self._recent_panel.isVisible():
            self._recent_panel.refresh()

    def _open_settings(self) -> None:
        """Open the settings sidebar (always recreated to reflect current config)."""
        if self._recording_prepare_in_progress:
            self.tray.showMessage(
                APP_NAME, "Please wait for recording startup to finish.",
                self.tray.icon(), 2500,
            )
            return
        if self._settings_sidebar and self._settings_sidebar.isVisible():
            self._settings_sidebar.close_panel()
            return

        # Close recent panel if open
        if self._recent_panel and self._recent_panel.isVisible():
            self._recent_panel.close_panel()

        self._cancel_pre_record()

        # Settings sidebar is always recreated since it reflects live config state
        if self._settings_sidebar:
            self._settings_sidebar.close()
            self._settings_sidebar.deleteLater()

        self._settings_sidebar = SettingsSidebar(
            {**self.config, "current_version": APP_VERSION},
            default_config=DEFAULT_CONFIG,
            edge=self.config.get("dock_edge", "right"),
        )
        self._settings_sidebar.settings_saved.connect(self._on_settings_saved)
        self._settings_sidebar.files_requested.connect(self._on_files_requested)
        self._settings_sidebar.quit_requested.connect(self._quit)
        self._settings_sidebar.manual_update_check_finished.connect(self._on_manual_update_check_finished)
        self._settings_sidebar.font_size_changed.connect(self._on_font_size_changed)
        self._settings_sidebar.closed.connect(lambda: None)  # Keep reference for potential reuse
        self._settings_sidebar.width_changed.connect(self._on_sidebar_resized)
        
        fs_mode = self.config.get("font_size", "Default")
        # Start at the smallest usable width in each font mode.
        def_w = 480 if fs_mode == "Large" else 380
        min_w = 480 if fs_mode == "Large" else 380
        w = max(self.config.get("sidebar_width", def_w), min_w)
        self._settings_sidebar.resize(w, 10)
        self._settings_sidebar.open_panel()

        # If a background check already found an update, reflect it in the UI immediately
        if self._update_status["available"]:
            self._settings_sidebar.set_update_status(
                True, self._update_status["version"], self._update_status["url"]
            )
        elif self._has_manually_checked_updates:
            self._settings_sidebar.set_update_status(False, "", "")

    def _on_font_size_changed(self, mode: str) -> None:
        self.config["font_size"] = mode
        # Reset width to default for the new mode so user sees the difference
        def_w = 480 if mode == "Large" else 380
        self.config["sidebar_width"] = def_w
        self._save_config()
        if self._settings_sidebar:
            self._settings_sidebar.close_panel()
            # Open immediately to rebuild UI with new font sizes
            QTimer.singleShot(350, self._open_settings)

    def _on_sidebar_resized(self, width: int) -> None:
        self.config["sidebar_width"] = width
        self._save_config()

    def _on_settings_saved(self, new_config: dict) -> None:
        """Handle settings saved from the sidebar."""
        old_fs = self.config.get("font_size", "Default")
        new_fs = new_config.get("font_size", "Default")

        # PERF-006: Only restart hotkey listener if hotkeys actually changed
        old_hk = self.config.get("hotkey", "")
        old_hk_ss = self.config.get("hotkey_screenshot", "")
        new_hk = new_config.get("hotkey", "")
        new_hk_ss = new_config.get("hotkey_screenshot", "")
        hotkeys_changed = (old_hk != new_hk or old_hk_ss != new_hk_ss)
 
        self.config = new_config
        self._save_config()
        self._sync_registry()

        if hotkeys_changed:
            self._start_hotkey_listener()

        # PERF-001: Invalidate cached recent panel if output folder changed
        if self._recent_panel and self._recent_panel._output_folder != self.config.get("output_folder", ""):
            self._recent_panel.close()
            self._recent_panel.deleteLater()
            self._recent_panel = None
 
        # If font size changed, trigger an instant refresh by re-opening the panel
        if old_fs != new_fs:
            # Invalidate cached sidebars since font size affects layout
            if self._recent_panel:
                self._recent_panel.close()
                self._recent_panel.deleteLater()
                self._recent_panel = None
            if self._settings_sidebar:
                self._settings_sidebar.close_panel()
                QTimer.singleShot(350, self._open_settings)
        
        # Update tray labels
        hk_ss = self.config.get("hotkey_screenshot", DEFAULT_CONFIG["hotkey_screenshot"]).replace("<", "").replace(">", "").title()
        hk_rec = self.config.get("hotkey", DEFAULT_CONFIG["hotkey"]).replace("<", "").replace(">", "").title()
        if hasattr(self, '_act_ss'):
            self._act_ss.setText(f"Take Screenshot  ({hk_ss})")
        if hasattr(self, '_act_record'):
            self._act_record.setText(f"Start Recording  ({hk_rec})")

        # Update dock
        if hasattr(self, 'dock') and self.dock:
            self.dock.update_config(self.config)

        try:
            Path(self.config["output_folder"]).mkdir(parents=True, exist_ok=True)
        except (OSError, TypeError, ValueError) as exc:
            QMessageBox.critical(None, "Settings Error", f"The output folder cannot be used:\n{exc}")
            self.config["output_folder"] = DEFAULT_CONFIG["output_folder"]
            Path(self.config["output_folder"]).mkdir(parents=True, exist_ok=True)
            self._save_config()

    # ── Quit ──────────────────────────────────────────────────────────────────

    def _quit(self) -> None:
        update_workers = [
            worker for worker in (
                getattr(self, '_updater', None), getattr(self, '_downloader', None),
                *_ACTIVE_UPDATE_THREADS,
            ) if worker and worker.isRunning()
        ]
        if update_workers:
            self.tray.showMessage(
                APP_NAME, "Finishing an update check or download. Try Quit again shortly.",
                self.tray.icon(), 3000,
            )
            return
        if any(worker.isRunning() for worker in self._notification_thumb_workers):
            self.tray.showMessage(
                APP_NAME, "Finishing media preview. Try Quit again in a moment.",
                self.tray.icon(), 2500,
            )
            return
        if self._recording_prepare_in_progress:
            self.tray.showMessage(
                APP_NAME, "Recording is still starting. Try Quit again in a moment.",
                self.tray.icon(), 3000,
            )
            return
        if getattr(self.engine, '_finalizing', False):
            self.tray.showMessage(
                APP_NAME, "Your recording is still being saved. WWRecorder will stay open until it finishes.",
                self.tray.icon(), 4000,
            )
            return
        for window in list(self._video_player_windows) + list(self._annotate_windows):
            try:
                if not window.close():
                    return
            except RuntimeError:
                pass

        if self.engine.is_recording():
            self.engine.stop()

        if self._hotkey_listener:
            self._hotkey_listener.stop()

        # Save dock position before quitting
        if hasattr(self, 'dock'):
            self.dock._save_dock_position()
            self._save_config()
            self.dock.close()

        if self._recent_panel:
            self._recent_panel.close()
        if self._settings_sidebar:
            self._settings_sidebar.close()

        self.tray.hide()
        self.app.quit()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _asset(self, name: str) -> str:
        if getattr(sys, "frozen", False):
            base = sys._MEIPASS  # type: ignore[attr-defined]
            candidates = [os.path.join(base, "assets", name), os.path.join(base, name)]
        else:
            base = os.path.dirname(os.path.abspath(__file__))
            candidates = [os.path.join(base, name), os.path.join(base, "icons", name)]
        return next((path for path in candidates if os.path.isfile(path)), candidates[0])

    # ── Run ───────────────────────────────────────────────────────────────────

    def run(self) -> int:
        return self.app.exec()


# ─────────────────────────────────────────────────────────────────────────────
#  Entry point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Prevent multiple instances via a named mutex (Windows)
    mutex = None
    if sys.platform == "win32":
        import ctypes
        mutex, already_running = _acquire_single_instance_mutex()
        if already_running:
            import ctypes.wintypes
            ctypes.windll.user32.MessageBoxW(
                0,
                ctypes.c_wchar_p(f"{APP_NAME} is already running.\nCheck the system tray."),
                ctypes.c_wchar_p(APP_NAME),
                0x40,   # MB_ICONINFORMATION
            )
            sys.exit(0)

    try:
        application = WWRecorderApp()
        sys.exit(application.run())
    finally:
        # BUG-003: Release mutex handle so a subsequent launch isn't blocked
        if mutex and sys.platform == "win32":
            try:
                ctypes.windll.kernel32.CloseHandle(mutex)
            except Exception:
                pass
