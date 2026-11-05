"""Non-blocking packaged startup integration, owned by the Qt GUI thread."""
import time
from PyQt6.QtCore import QObject, QTimer, pyqtSignal


class PackagedStartup(QObject):
    # Actual enabled state, message. A failure with unknown state uses None.
    finished = pyqtSignal(object, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._operation = None
        self._task = None
        self._desired = None
        self._pending = None
        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._poll)

    def sync(self, desired=None):
        """None reads Windows state; a bool applies an explicit preference."""
        if self._operation is not None:
            if desired is not None:
                self._pending = (desired,)
            return
        self._desired = desired
        try:
            from winrt.windows.applicationmodel import StartupTask
            self._phase = "get"
            self._operation = StartupTask.get_async("WWRecorderStartup")
            self._deadline = time.monotonic() + 10
            self._timer.start()
        except Exception as exc:
            self._complete(None, f"Could not read Windows startup settings: {exc}")

    def _poll(self):
        try:
            from winrt.windows.foundation import AsyncStatus
            if self._operation.status == AsyncStatus.STARTED:
                if time.monotonic() > self._deadline:
                    self._operation.cancel()
                    self._complete(None, "Windows startup settings timed out. Try again in Settings.")
                return
            result = self._operation.get_results()
            if self._phase == "get":
                self._task = result
                state = int(result.state)
                if self._desired is True and state == 0:
                    self._phase = "enable"
                    self._operation = result.request_enable_async()
                    self._deadline = time.monotonic() + 10
                    return
                if self._desired is False and state == 2:
                    result.disable()
                    state = int(result.state)
            else:
                state = int(result)
            enabled = state in (2, 4)
            message = ""
            if self._desired is not None and enabled != self._desired:
                if state == 1:
                    message = "Startup was disabled in Windows. Re-enable WWRecorder in Windows Settings > Apps > Startup."
                elif state in (3, 4):
                    message = "Your Windows administrator controls this startup setting."
                else:
                    message = "Windows did not apply the startup preference. Check Windows Settings > Apps > Startup."
            self._complete(enabled, message)
        except Exception as exc:
            self._complete(None, f"Could not change Windows startup settings: {exc}")

    def _complete(self, enabled, message):
        self._timer.stop()
        self._operation = None
        self._task = None
        pending, self._pending = self._pending, None
        # A newer request owns the final visible state.
        if pending is not None:
            self.sync(pending[0])
        else:
            self.finished.emit(enabled, message)

    def cancel(self):
        self._timer.stop()
        self._pending = None
        if self._operation is not None:
            try:
                self._operation.cancel()
            except Exception:
                pass
        self._operation = None


def desktop_startup_state(name='WWRecorder'):
    """Read Run registration and Windows Task Manager's approval state."""
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r'Software\Microsoft\Windows\CurrentVersion\Run') as key:
            winreg.QueryValueEx(key, name)
    except FileNotFoundError:
        return False, ''
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r'Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run') as key:
            data, _ = winreg.QueryValueEx(key, name)
        if isinstance(data, bytes) and len(data) >= 4 and int.from_bytes(data[:4], 'little') in (3, 7):
            return False, 'Startup is disabled in Windows Settings > Apps > Startup.'
    except FileNotFoundError:
        pass
    return True, ''
