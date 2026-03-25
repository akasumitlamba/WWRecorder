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
import os
import sys
import json 
import winreg
import subprocess
from pathlib import Path   

from PyQt6.QtWidgets import QApplication, QSystemTrayIcon, QMenu
from PyQt6.QtGui import QIcon, QPixmap, QColor, QPainter, QAction
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QPoint

from pynput import keyboard as pynput_keyboard

from recorder import RecordingEngine
from ui_elements import SelectionOverlay, PillWidget, SettingsWindow, CaptureBorderWidget


# ─────────────────────────────────────────────────────────────────────────────
#  Constants / defaults
# ─────────────────────────────────────────────────────────────────────────────

APP_NAME    = "WWRecorder"
APP_VERSION = "1.0.0"

CONFIG_DIR  = Path(os.environ.get("APPDATA", ".")) / APP_NAME
CONFIG_FILE = CONFIG_DIR / "config.json"
LOG_FILE    = CONFIG_DIR / "wwrecorder.log"

_REG_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

DEFAULT_CONFIG: dict = {
    "output_folder":        str(Path.home() / "Videos" / APP_NAME),
    "hotkey":               "<shift>+<backspace>",
    "default_system_audio": True,
    "default_mic":          False,
    "start_on_boot":        True,
}


# ─────────────────────────────────────────────────────────────────────────────
#  HotkeyListener  - runs pynput in a QThread so it doesn't block Qt
# ─────────────────────────────────────────────────────────────────────────────

class HotkeyListener(QThread):
    """
    Listens for the global hotkey in a background thread.
    Emits `triggered` on the Qt side (thread-safe via signal).
    """

    triggered = pyqtSignal()

    def __init__(self, hotkey_str: str, parent=None):
        super().__init__(parent)
        self._hotkey_str  = hotkey_str
        self._ghk: pynput_keyboard.GlobalHotKeys | None = None

    def run(self):
        def _on_activate():
            self.triggered.emit()

        try:
            with pynput_keyboard.GlobalHotKeys(
                {self._hotkey_str: _on_activate}
            ) as ghk:
                self._ghk = ghk
                ghk.join()
        except Exception as exc:
            print(f"[HotkeyListener] Error: {exc}")

    def stop(self):
        if self._ghk:
            self._ghk.stop()
        self.wait(2000)


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

        # Ensure config & output dirs exist
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)

        self.config = self._load_config()
        Path(self.config["output_folder"]).mkdir(parents=True, exist_ok=True)

        self.engine: RecordingEngine = RecordingEngine()
        self.pill:   PillWidget | None = None
        self.border_widget: CaptureBorderWidget | None = None

        self._hotkey_listener: HotkeyListener | None = None

        self._setup_tray()
        self._start_hotkey_listener()

        # Apply registry setting on startup
        self._sync_registry()

    # ── Config ────────────────────────────────────────────────────────────────

    def _load_config(self) -> dict:
        if CONFIG_FILE.exists():
            try:
                with CONFIG_FILE.open("r", encoding="utf-8") as f:
                    loaded = json.load(f)
                return {**DEFAULT_CONFIG, **loaded}
            except Exception as exc:
                print(f"[Config] Load failed ({exc}); using defaults.")
        return DEFAULT_CONFIG.copy()

    def _save_config(self) -> None:
        try:
            with CONFIG_FILE.open("w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=2)
        except Exception as exc:
            print(f"[Config] Save failed: {exc}")

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
                        exe = os.path.abspath(sys.executable)
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

        self._act_record = QAction(f"Start Recording  (Ctrl+Shift+R)", menu)
        self._act_record.triggered.connect(self._on_start_recording)
        menu.addAction(self._act_record)

        menu.addSeparator()

        act_settings = QAction("Settings…", menu)
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
        if hasattr(self, "_last_saved_filepath") and self._last_saved_filepath:
            if os.path.isfile(self._last_saved_filepath):
                # Opens folder and selects the file
                subprocess.run(f'explorer /select,"{os.path.normpath(self._last_saved_filepath)}"')

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._on_start_recording()

    # ── Hotkey ────────────────────────────────────────────────────────────────

    def _start_hotkey_listener(self) -> None:
        if self._hotkey_listener and self._hotkey_listener.isRunning():
            self._hotkey_listener.stop()

        hk = self.config.get("hotkey", DEFAULT_CONFIG["hotkey"])
        self._hotkey_listener = HotkeyListener(hk)
        self._hotkey_listener.triggered.connect(self._on_hotkey_triggered)
        self._hotkey_listener.start()

    def _on_hotkey_triggered(self) -> None:
        """
        If a recording is active: toggle pause/resume.
        Otherwise:  open the region-picker and start a new recording.
        """
        if self.engine.is_recording():
            if self.pill:
                self.pill.toggle_pause()
        else:
            self._on_start_recording()

    # ── Recording lifecycle ───────────────────────────────────────────────────

    def _on_start_recording(self) -> None:
        if getattr(self, '_is_settings_open', False):
            return

        if self.engine.is_recording():
            return  # Already recording

        if hasattr(self, '_overlay') and self._overlay and self._overlay.isVisible():
            return

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
            return

        self._current_region = region
        if not getattr(self, 'pill', None) or not self.pill.isVisible():
            self.pill = PillWidget(self.engine, self.config, pre_record=True)
            self.pill.settings_requested.connect(self._open_settings)
            self.pill.start_requested.connect(self._do_start)
            self.pill.show()

    def _do_start(self) -> None:
        if hasattr(self, '_overlay') and self._overlay:
            self._overlay.close()
            self._overlay = None
        if hasattr(self, 'pill') and self.pill:
            self.pill.close()
            
        region = getattr(self, '_current_region', None)
        if region:
            self._start_recording(region)

    def _start_recording(self, region: dict) -> None:
        output_folder = self.config.get("output_folder", DEFAULT_CONFIG["output_folder"])
        audio_cfg = {
            "system_audio": self.config.get("default_system_audio", True),
            "mic":          self.config.get("default_mic",          False),
        }

        # Calculate physical region to solve dpi scaling offset for FFmpeg/MSS
        screen = QApplication.screenAt(QPoint(int(region["left"]), int(region["top"])))
        ratio = screen.devicePixelRatio() if screen else 1.0

        physical_region = {
            "top": int(region["top"] * ratio),
            "left": int(region["left"] * ratio),
            "width": int(region["width"] * ratio),
            "height": int(region["height"] * ratio),
        }

        # Engine handles physical coordinates
        ok = self.engine.start(physical_region, output_folder, audio_cfg)
        if not ok:
            self.tray.showMessage(
                APP_NAME, "Failed to start recording - is FFmpeg installed?",
                QSystemTrayIcon.MessageIcon.Critical, 4000,
            )
            return

        self.tray.setToolTip(f"{APP_NAME} - Recording…")
        self._act_record.setEnabled(False)

        self.pill = PillWidget(self.engine, self.config)
        self.pill.stopped.connect(self._on_recording_stopped)
        self.pill.settings_requested.connect(self._open_settings)
        self.pill.show()

        # Outline handles logical coordinates (Qt handles the scaling)
        self.border_widget = CaptureBorderWidget(region)
        self.border_widget.show()

    def _on_recording_stopped(self, filepath: str) -> None:
        self.pill = None
        if self.border_widget:
            self.border_widget.close()
            self.border_widget = None

        self.tray.setToolTip(f"{APP_NAME} - Ready")
        self._act_record.setEnabled(True)

        if filepath and os.path.isfile(filepath):
            self._last_saved_filepath = filepath
            size_mb = os.path.getsize(filepath) / (1024 * 1024)
            self.tray.showMessage(
                "Recording saved",
                f"{os.path.basename(filepath)}  ({size_mb:.1f} MB)\nClick to view.",
                QSystemTrayIcon.MessageIcon.Information,
                4000,
            )
        else:
            self._last_saved_filepath = None
            self.tray.showMessage(
                APP_NAME, "Recording finished (no output file).",
                QSystemTrayIcon.MessageIcon.Warning, 3000,
            )

    # ── Settings ──────────────────────────────────────────────────────────────

    def _cancel_pre_record(self) -> None:
        if hasattr(self, '_overlay') and self._overlay:
            self._overlay.close()
            self._overlay = None
        if hasattr(self, 'pill') and self.pill and getattr(self.pill, '_pre_record', False):
            self.pill.close()
            self.pill = None

    def _open_settings(self) -> None:
        if getattr(self, '_is_settings_open', False):
            return
            
        self._cancel_pre_record()
        
        self._is_settings_open = True
        try:
            dlg = SettingsWindow(self.config)
            if dlg.exec() == SettingsWindow.DialogCode.Accepted:
                self.config = dlg.get_config()
                self._save_config()
                self._sync_registry()
                self._start_hotkey_listener()   # Re-register new hotkey
    
                # Update hotkey label in tray menu
                hk = self.config.get("hotkey", "")
                self._act_record.setText(f"Start Recording  ({hk})")
    
                # Ensure output folder exists
                from pathlib import Path
                Path(self.config["output_folder"]).mkdir(parents=True, exist_ok=True)
        finally:
            self._is_settings_open = False

    # ── Quit ──────────────────────────────────────────────────────────────────

    def _quit(self) -> None:
        if self.engine.is_recording():
            self.engine.stop()
        if self._hotkey_listener:
            self._hotkey_listener.stop()
        self.tray.hide()
        self.app.quit()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _asset(self, name: str) -> str:
        if getattr(sys, "frozen", False):
            base = sys._MEIPASS  # type: ignore[attr-defined]
        else:
            base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
        return os.path.join(base, name)

    # ── Run ───────────────────────────────────────────────────────────────────

    def run(self) -> int:
        return self.app.exec()


# ─────────────────────────────────────────────────────────────────────────────
#  Entry point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Prevent multiple instances via a named mutex (Windows)
    if sys.platform == "win32":
        import ctypes
        mutex = ctypes.windll.kernel32.CreateMutexW(None, False, f"Global\\{APP_NAME}_mutex")
        if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
            import ctypes.wintypes
            ctypes.windll.user32.MessageBoxW(
                0,
                f"{APP_NAME} is already running.\nCheck the system tray.",
                APP_NAME,
                0x40,   # MB_ICONINFORMATION
            )
            sys.exit(0)

    application = WWRecorderApp()
    sys.exit(application.run())
