"""Distribution boundaries. Core features must never branch on package identity."""
import ctypes
import json
import os
import sys
from pathlib import Path


def application_icon_path():
    """Canonical icon in source and PyInstaller installations."""
    return str(Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "icon.ico")

RELEASES_URL = "https://github.com/akasumitlamba/WWRecorder/releases/latest"
LEGACY_STORE_URL = "https://aka.ms/AA1364bx"
STORE_LIBRARY_URL = "ms-windows-store://downloadsandupdates"


def package_family_name():
    if sys.platform != "win32":
        return ""
    api = ctypes.windll.kernel32.GetCurrentPackageFamilyName
    api.argtypes = [ctypes.POINTER(ctypes.c_uint32), ctypes.c_wchar_p]
    api.restype = ctypes.c_long
    size = ctypes.c_uint32()
    result = api(ctypes.byref(size), None)
    if result == 15700:  # APPMODEL_ERROR_NO_PACKAGE
        return ""
    if result != 122:  # ERROR_INSUFFICIENT_BUFFER
        raise OSError(result, "Cannot determine Windows package identity")
    buffer = ctypes.create_unicode_buffer(size.value)
    result = api(ctypes.byref(size), buffer)
    if result:
        raise OSError(result, "Cannot read Windows package identity")
    return buffer.value


def is_packaged():
    return bool(package_family_name())


def package_metadata():
    if not is_packaged():
        return {}
    # This file is added to the MSIX staging folder, never the shared payload.
    try:
        value = json.loads((Path(sys.executable).parent / "distribution.json").read_text(encoding="utf-8-sig"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def store_url():
    if not is_packaged():
        return LEGACY_STORE_URL
    product_id = package_metadata().get("store_product_id", "")
    return f"ms-windows-store://pdp/?ProductId={product_id}" if product_id else STORE_LIBRARY_URL


def update_url():
    return store_url() if is_packaged() else RELEASES_URL


def config_directory():
    family = package_family_name()
    if family:
        return Path(os.environ["LOCALAPPDATA"]) / "Packages" / family / "LocalState" / "WWRecorder"
    return Path(os.environ.get("APPDATA", ".")) / "WWRecorder"


def migrate_legacy_config(destination, source=None):
    """Copy once, preserving the original bytes and never replacing MSIX choices.

    Errors deliberately propagate: callers must report migration failure rather
    than claim preferences were preserved. Config validation stays in main.py.
    """
    destination = Path(destination)
    source = Path(source) if source else Path(os.environ["APPDATA"]) / "WWRecorder" / "config.json"
    if destination.exists() or not source.exists():
        return False
    raw = source.read_bytes()
    if not isinstance(json.loads(raw.decode("utf-8-sig")), dict):
        raise ValueError("existing settings are not a JSON object")
    destination.parent.mkdir(parents=True, exist_ok=True)
    backup = destination.with_name("config.imported-exe.json")
    if not backup.exists():
        with backup.open("xb") as stream:
            stream.write(raw)
    temporary = destination.with_suffix(".importing")
    try:
        temporary.write_bytes(raw)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return True
