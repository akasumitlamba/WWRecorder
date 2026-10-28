"""Start-with-Windows seams (EXE Run vs MSIX StartupTask).

Purpose: packaged startup is non-blocking with 10s timeout; EXE must not be
written by MSIX helpers. Full WinRT exercise is windows_native.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from helpers.env import import_app

pytestmark = [pytest.mark.feature_startup]


@pytest.mark.pure_logic
def test_packaged_startup_class_exists_with_timeout_contract():
    startup = import_app("startup_integration")
    assert hasattr(startup, "PackagedStartup")
    src = Path(startup.__file__).read_text(encoding="utf-8")
    assert "10" in src  # 10-second deadline
    assert "WWRecorderStartup" in src


@pytest.mark.pure_logic
def test_packaged_startup_class_does_not_write_exe_run_key():
    """PackagedStartup (MSIX) must use StartupTask APIs only — not HKCU Run writes.

    The module may also expose desktop_startup_state() for EXE reconciliation;
    that helper may read Run/StartupApproved. The packaged class must not write.
    """
    startup = import_app("startup_integration")
    src = Path(startup.__file__).read_text(encoding="utf-8")
    # Isolate the PackagedStartup class body roughly until the next top-level def
    start = src.index("class PackagedStartup")
    end = src.index("\ndef ", start)
    body = src[start:end]
    assert "winreg" not in body
    assert "SetValue" not in body
    assert "WWRecorderStartup" in body


@pytest.mark.windows_native
def test_packaged_startup_constructs_on_windows(qapp):
    startup = import_app("startup_integration")
    obj = startup.PackagedStartup()
    assert obj is not None
