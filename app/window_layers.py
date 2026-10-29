"""One transient-window policy for the floating Windows application.

Dialogs, menus, combo popups and tooltips must stay above topmost tools without
stealing keyboard focus. Floating controls yield while any transient is visible.
"""
import sys
from PyQt6.QtCore import QObject, QEvent, Qt, QAbstractNativeEventFilter
from PyQt6.QtWidgets import QApplication, QWidget, QDialog, QToolTip

_user32 = None
if sys.platform == 'win32':
    import ctypes
    from ctypes import wintypes
    _user32 = ctypes.WinDLL('user32', use_last_error=True)
    _user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
    _user32.SetWindowPos.restype = wintypes.BOOL
    _user32.IsWindow.argtypes = [wintypes.HWND]
    _user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]


def _set_topmost(handle):
    if _user32 is not None and _user32.IsWindow(handle):
        # No move/resize, focus activation, or change to ownership.
        _user32.SetWindowPos(handle, -1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010)


def is_transient(widget):
    return (isinstance(widget, QDialog) or
            widget.windowType() in (Qt.WindowType.Popup, Qt.WindowType.ToolTip))


def transient_is_visible():
    if QApplication.activeModalWidget() or QApplication.activePopupWidget() or QToolTip.isVisible():
        return True
    return any(widget.isVisible() and is_transient(widget)
               for widget in QApplication.topLevelWidgets())


def prepare_dialog(dialog, modality=Qt.WindowModality.WindowModal):
    # QMessageBox.setWindowModality can rebuild its flags (Qt::Sheet). Set the
    # topmost hint AFTER modality, never before it.
    dialog.setWindowModality(modality)
    dialog.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    return dialog


class _NativeDialogs(QAbstractNativeEventFilter):
    """Cover native Windows file choosers/tooltips as well as Qt widgets."""
    def nativeEventFilter(self, event_type, message):
        if _user32 is None:
            return False, 0
        try:
            msg = wintypes.MSG.from_address(int(message))
            # Only newly shown or activated windows, avoiding SetWindowPos recursion.
            if ((msg.message == 0x0018 and msg.wParam) or
                    (msg.message == 0x0006 and (msg.wParam & 0xffff))):
                name = ctypes.create_unicode_buffer(128)
                _user32.GetClassNameW(msg.hWnd, name, len(name))
                if name.value in ('#32770', 'tooltips_class32'):
                    _set_topmost(msg.hWnd)
        except (ValueError, TypeError, OSError):
            pass
        return False, 0


class WindowLayers(QObject):
    def eventFilter(self, watched, event):
        if (event.type() in (QEvent.Type.Show, QEvent.Type.WindowActivate) and
                isinstance(watched, QWidget) and watched.isWindow() and
                watched.isVisible() and is_transient(watched)):
            _set_topmost(int(watched.winId()))
        return False


def install_window_layers(application):
    policy = getattr(application, '_wwr_window_layers', None)
    if policy is None:
        policy = WindowLayers(application)
        application.installEventFilter(policy)
        policy.native = _NativeDialogs()
        application.installNativeEventFilter(policy.native)
        application._wwr_window_layers = policy
    return policy
