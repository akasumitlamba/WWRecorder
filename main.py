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

from PyQt6.QtWidgets import (
    QApplication, QMenu, QSystemTrayIcon, QWidget, QFileDialog
)
from PyQt6.QtGui import QIcon, QAction, QPixmap, QPainter, QColor, QImage
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QPoint, QRect, QUrl, QMimeData

from pynput import keyboard as pynput_keyboard

from recorder import RecordingEngine
from ui_elements import SelectionOverlay, PillWidget, SettingsWindow, CaptureBorderWidget
from dock_widget import DockWidget, SettingsSidebar, RecentFilesSidebar


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
    "hotkey_screenshot":    "<shift>+<home>",
    "default_system_audio": True,
    "default_mic":          False,
    "start_on_boot":        True,
    "copy_to_clipboard":    True,
    "sidebar_width":        380,
}


# ─────────────────────────────────────────────────────────────────────────────
#  HotkeyListener  - runs pynput in a QThread so it doesn't block Qt
# ─────────────────────────────────────────────────────────────────────────────

class HotkeyListener(QThread):
    """
    Listens for the global hotkeys in a background thread.
    Emits `record_triggered` and `screenshot_triggered` on the Qt side.
    """
    record_triggered = pyqtSignal()
    screenshot_triggered = pyqtSignal()

    def __init__(self, record_hk: str, screenshot_hk: str):
        super().__init__()
        self._record_hk = record_hk
        self._screenshot_hk = screenshot_hk
        self._ghk = None

    def run(self):
        def _on_rec():
            self.record_triggered.emit()
            
        def _on_ss():
            self.screenshot_triggered.emit()

        mapping = {}
        if self._record_hk:
            mapping[self._record_hk] = _on_rec
        if self._screenshot_hk:
            mapping[self._screenshot_hk] = _on_ss

        try:
            with pynput_keyboard.GlobalHotKeys(mapping) as ghk:
                self._ghk = ghk
                ghk.join()
        except Exception as exc:
            print(f"[HotkeyListener] Error binding: {exc}")

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
        self._recent_panel: RecentFilesSidebar | None = None
        self._settings_sidebar: SettingsSidebar | None = None
        self._screenshot_mode = False  # True when selecting area for screenshot

        self._hotkey_listener: HotkeyListener | None = None

        self._setup_tray()
        self._setup_dock()
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

        hk_ss = self.config.get("hotkey_screenshot", DEFAULT_CONFIG["hotkey_screenshot"]).replace("<", "").replace(">", "").title()
        self._act_ss = QAction(f"Take Screenshot  ({hk_ss})", menu)
        self._act_ss.triggered.connect(self._on_screenshot_requested)
        menu.addAction(self._act_ss)

        hk_rec = self.config.get("hotkey", DEFAULT_CONFIG["hotkey"]).replace("<", "").replace(">", "").title()
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
        if hasattr(self, "_last_saved_filepath") and self._last_saved_filepath:
            if os.path.isfile(self._last_saved_filepath):
                # Opens folder and selects the file
                subprocess.run(f'explorer /select,"{os.path.normpath(self._last_saved_filepath)}"')

    # ── Dock ──────────────────────────────────────────────────────────────────

    def _setup_dock(self) -> None:
        self.dock = DockWidget(self.engine, self.config)
        self.dock.screenshot_requested.connect(self._on_screenshot_requested)
        self.dock.record_requested.connect(self._on_dock_record)
        self.dock.files_requested.connect(self._on_files_requested)
        self.dock.settings_requested.connect(self._open_settings)
        self.dock.show()

    def _on_screenshot_requested(self) -> None:
        """Open the selection overlay in screenshot mode."""
        if self.engine.is_recording():
            return
        if hasattr(self, '_overlay') and self._overlay and self._overlay.isVisible():
            return

        self._screenshot_mode = True
        self._overlay = SelectionOverlay(mode="screenshot")
        self._overlay.selectionChanged.connect(self._on_screenshot_selection)
        self._overlay.show()
        self._overlay.raise_()
        self._overlay.activateWindow()

    def _on_screenshot_selection(self, region: dict) -> None:
        """Handle area selected for screenshot."""
        if hasattr(self, '_overlay') and self._overlay:
            self._overlay.close()
            self._overlay = None

        self._screenshot_mode = False

        if not region:
            return  # Cancelled

        # Convert logical coordinates to physical coordinates for mss (DPI scaling)
        r = QRect(int(region["left"]), int(region["top"]), int(region["width"]), int(region["height"]))
        if r.width() > 0 and r.height() > 0:
            screen = QApplication.screenAt(QPoint(r.left(), r.top()))
            ratio = screen.devicePixelRatio() if screen else 1.0
            phys_region = {
                "left": int(r.left() * ratio),
                "top": int(r.top() * ratio),
                "width": int(r.width() * ratio),
                "height": int(r.height() * ratio),
            }
            out_dir = self.config.get("output_folder", DEFAULT_CONFIG["output_folder"])
            saved_path = self.engine.take_screenshot(phys_region, out_dir)
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
                
            self.tray.showMessage(
                "Screenshot Saved",
                f"{Path(saved_path).name}\nClick to view.",
                QSystemTrayIcon.MessageIcon.Information,
                4000,
            )
            # Refresh recent files if open
            if self._recent_panel and self._recent_panel.isVisible():
                self._recent_panel.refresh()

    def _on_dock_record(self) -> None:
        """Toggle recording from the dock button."""
        if self.engine.is_recording():
            # Stop recording
            if self.pill:
                self.pill._initiate_stop()
        else:
            self._on_start_recording()

    def _on_files_requested(self) -> None:
        """Toggle the recent files sidebar."""
        if self._recent_panel and self._recent_panel.isVisible():
            self._recent_panel.close_panel()
            return

        # Close settings panel if open
        if self._settings_sidebar and self._settings_sidebar.isVisible():
            self._settings_sidebar.close_panel()

        output_folder = self.config.get("output_folder", DEFAULT_CONFIG["output_folder"])
        self._recent_panel = RecentFilesSidebar(
            output_folder,
            font_size_mode=self.config.get("font_size", "Default"),
            edge=self.config.get("dock_edge", "right"),
        )
        self._recent_panel.settings_requested.connect(self._open_settings)
        self._recent_panel.closed.connect(lambda: setattr(self, '_recent_panel', None))
        self._recent_panel.width_changed.connect(self._on_sidebar_resized)
        
        w = self.config.get("sidebar_width", 380)
        self._recent_panel.resize(w, 10) # height gets overridden
        self._recent_panel.open_panel()

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
        if self._settings_sidebar and self._settings_sidebar.isVisible():
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
        
        # Initialize engine audio config from defaults before showing pre-record pill
        self.engine.set_system_audio(self.config.get("default_system_audio", True))
        self.engine.set_mic(self.config.get("default_mic", False))
        
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

        # Calculate physical region to solve dpi scaling offset for FFmpeg/MSS
        screen = QApplication.screenAt(QPoint(int(region["left"]), int(region["top"])))
        ratio = screen.devicePixelRatio() if screen else 1.0

        physical_region = {
            "top": int(region["top"] * ratio),
            "left": int(region["left"] * ratio),
            "width": int(region["width"] * ratio),
            "height": int(region["height"] * ratio),
        }

        # Engine handles physical coordinates (audio state is already configured in engine)
        ok = self.engine.start(physical_region, output_folder)
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

        # Update dock recording state
        if hasattr(self, 'dock'):
            self.dock.set_recording_state(True)
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

        # Update dock recording state
        if hasattr(self, 'dock'):
            self.dock.set_recording_state(False)

        # Refresh recent files if open
        if self._recent_panel and self._recent_panel.isVisible():
            self._recent_panel.refresh()

        if filepath and os.path.isfile(filepath):
            self._last_saved_filepath = filepath
            size_mb = os.path.getsize(filepath) / (1024 * 1024)
            
            # Copy to clipboard
            if self.config.get("copy_to_clipboard", True):
                mime = QMimeData()
                mime.setUrls([QUrl.fromLocalFile(filepath)])
                QApplication.clipboard().setMimeData(mime)

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
        """Open the settings sidebar (replaces legacy SettingsWindow)."""
        if self._settings_sidebar and self._settings_sidebar.isVisible():
            self._settings_sidebar.close_panel()
            return

        # Close recent panel if open
        if self._recent_panel and self._recent_panel.isVisible():
            self._recent_panel.close_panel()

        self._cancel_pre_record()

        self._settings_sidebar = SettingsSidebar(
            self.config,
            default_config=DEFAULT_CONFIG,
            edge=self.config.get("dock_edge", "right"),
        )
        self._settings_sidebar.settings_saved.connect(self._on_settings_saved)
        self._settings_sidebar.files_requested.connect(self._on_files_requested)
        self._settings_sidebar.quit_requested.connect(self._quit)
        self._settings_sidebar.closed.connect(lambda: setattr(self, '_settings_sidebar', None))
        self._settings_sidebar.width_changed.connect(self._on_sidebar_resized)
        
        w = self.config.get("sidebar_width", 380)
        self._settings_sidebar.resize(w, 10)
        self._settings_sidebar.open_panel()

    def _on_sidebar_resized(self, width: int) -> None:
        self.config["sidebar_width"] = width
        self._save_config()

    def _on_settings_saved(self, new_config: dict) -> None:
        """Handle settings saved from the sidebar."""
        self.config = new_config
        self._save_config()
        self._sync_registry()
        self._start_hotkey_listener()
        
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

        Path(self.config["output_folder"]).mkdir(parents=True, exist_ok=True)

    # ── Quit ──────────────────────────────────────────────────────────────────

    def _quit(self) -> None:
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
