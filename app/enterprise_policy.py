"""Optional administrator policy shared by EXE and MSIX; no consumer defaults change."""
import sys


def disabled(name):
    if name not in ('Keycast', 'AutomaticClipboard') or sys.platform != 'win32':
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Policies\WWRecorder',
                            0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
            value, kind = winreg.QueryValueEx(key, 'Disable' + name)
            return kind == winreg.REG_DWORD and value == 1
    except OSError:
        return False
