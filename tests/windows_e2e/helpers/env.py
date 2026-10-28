"""Platform, dependency, and import-path guards for Windows E2E.

Purpose
-------
Centralize every precondition the suite needs so tests never "pass" by
accident when Windows APIs, Qt, or app modules are unavailable.

Pass means
----------
Callers get an explicit ``True``/``False`` or a skipped pytest outcome with a
human-readable reason. Silent success on a missing platform is a harness bug.

Windows-only notes
------------------
Real capture, WASAPI, WinRT StartupTask, mutex, tray, and gdigrab paths require
``sys.platform == "win32"``. Linux cloud agents may *collect* and run pure-logic
cases after installing lightweight stubs; those stubs are never a substitute
for a Windows GUI E2E pass claim.
"""

from __future__ import annotations

import os
import sys
import types
from functools import lru_cache
from pathlib import Path

import pytest

# Repository paths -------------------------------------------------------------

# tests/windows_e2e/helpers/env.py -> parents[3] == repo root
REPO_ROOT = Path(__file__).resolve().parents[3]
APP_DIR = REPO_ROOT / "app"
E2E_ROOT = REPO_ROOT / "tests" / "windows_e2e"
DEFAULT_REPORT_DIR = REPO_ROOT / "artifacts" / "windows_e2e"
SUITE_REPORT_DIR = E2E_ROOT / "reports"


def ensure_app_on_path() -> Path:
    """Insert ``app/`` on ``sys.path`` exactly once (pytest.ini also sets pythonpath)."""
    app = str(APP_DIR)
    if app not in sys.path:
        sys.path.insert(0, app)
    if not APP_DIR.is_dir():
        raise RuntimeError(f"WWRecorder app directory missing: {APP_DIR}")
    return APP_DIR


def is_windows() -> bool:
    return sys.platform == "win32"


def require_windows(reason: str = "This case needs real Windows APIs"):
    """Skip the calling test unless we are on Windows."""
    if not is_windows():
        pytest.skip(f"WINDOWS-ONLY: {reason}")


@lru_cache(maxsize=1)
def qt_importable() -> tuple[bool, str]:
    """Return (ok, detail) for PyQt6 import without creating a QApplication."""
    try:
        from PyQt6.QtCore import QT_VERSION_STR  # noqa: F401
        return True, f"PyQt6 {QT_VERSION_STR}"
    except Exception as exc:  # pragma: no cover - environment specific
        return False, f"{type(exc).__name__}: {exc}"


def require_qt():
    ok, detail = qt_importable()
    if not ok:
        pytest.skip(f"PyQt6 unavailable ({detail})")


def _stub_module(name: str, **attrs) -> types.ModuleType:
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    sys.modules[name] = module
    return module


def install_linux_windows_stubs() -> list[str]:
    """Install minimal stubs so Windows-targeted modules can be *imported* on Linux.

    Preconditions: ``not is_windows()``.
    Pass means: listed module names are present in ``sys.modules`` and safe for
    import-time side effects of ``main`` / ``recorder`` (no real COM/WASAPI).

    These stubs must NEVER be used to claim Windows GUI or audio E2E passed.
    """
    if is_windows():
        return []

    installed: list[str] = []

    def need(name: str, **attrs) -> types.ModuleType:
        existing = sys.modules.get(name)
        if existing is not None and getattr(existing, "__file__", None) is None:
            # Already a stub we installed — refresh attrs and return it.
            for key, value in attrs.items():
                setattr(existing, key, value)
            return existing
        if name in sys.modules and not attrs:
            return sys.modules[name]
        module = _stub_module(name, **attrs)
        if name not in installed:
            installed.append(name)
        return module

    need("pythoncom", CoInitialize=lambda *a, **k: None, CoUninitialize=lambda *a, **k: None)
    need("pywintypes")
    for name in (
        "win32api",
        "win32con",
        "win32gui",
        "win32ui",
        "win32process",
        "win32event",
        "win32clipboard",
        "winreg",
        "winsound",
    ):
        need(name)

    # soundcard may exist but fail without PulseAudio — replace with a quiet stub
    # when the real import raises, so recorder.py can be imported for pure checks.
    try:
        import soundcard  # noqa: F401
    except Exception:
        # Force-replace a broken partial import if present.
        sys.modules.pop("soundcard", None)
        sys.modules.pop("soundcard.pulseaudio", None)
        sys.modules.pop("soundcard.mediafoundation", None)
        sc = need("soundcard")
        sc.default_microphone = lambda: None
        sc.default_speaker = lambda: None
        sc.all_microphones = lambda include_loopback=False: []
        sc.all_speakers = lambda: []
        media = need("soundcard.mediafoundation")

        class _PropVariant:  # matches wasapi_compat probe attribute
            _wwr_native_size = 24

        media._PropVariant = _PropVariant

    try:
        import pynput  # noqa: F401
    except Exception:
        pk = need("pynput")
        kb = need("pynput.keyboard")

        class HotKey:
            @staticmethod
            def parse(value: str):
                parts = [p for p in value.replace("<", "").replace(">", "").split("+") if p]
                if not parts:
                    raise ValueError("empty hotkey")
                return tuple(parts)

        kb.HotKey = HotKey
        kb.Listener = object
        pk.keyboard = kb
        mouse = need("pynput.mouse")
        mouse.Listener = object
        pk.mouse = mouse

    # Ensure win32gui has the symbols recorder may touch at import/definition time.
    import win32gui  # type: ignore

    if not hasattr(win32gui, "GetDC"):
        win32gui.GetDC = lambda *a, **k: 0
        win32gui.ReleaseDC = lambda *a, **k: None

    return installed


def prepare_process_environment() -> dict:
    """Apply process-wide env for deterministic offscreen-capable runs.

    Always sets ``QT_QPA_PLATFORM=offscreen`` when unset so Linux collection does
    not try to open a display. On real Windows GUI runs, ``run_all.ps1`` clears
    or overrides this when a desktop session is available.
    """
    ensure_app_on_path()
    applied = {}
    if "QT_QPA_PLATFORM" not in os.environ and not is_windows():
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        applied["QT_QPA_PLATFORM"] = "offscreen"
    # Reduce Qt multimedia noise on headless agents
    os.environ.setdefault("QT_LOGGING_RULES", "qt.multimedia.*=false")
    if not is_windows():
        stubs = install_linux_windows_stubs()
        applied["linux_stubs"] = stubs
    return applied


def import_app(module_name: str):
    """Import an ``app/`` module after stubs/path setup; raise with context on failure."""
    prepare_process_environment()
    try:
        return __import__(module_name)
    except Exception as exc:
        raise RuntimeError(
            f"Failed to import app module {module_name!r} "
            f"(windows={is_windows()}, stubs_active={not is_windows()}): {exc}"
        ) from exc
