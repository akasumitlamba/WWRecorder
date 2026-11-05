"""Import and bytecode-compile every active app module.

Purpose: catch missing dependencies / syntax errors before feature assertions.
Preconditions: helpers.env prepared; Linux may use Windows stubs (not a GUI pass).
Pass means: each module imports OR is skipped with an explicit dependency reason;
py_compile of listed AGENTS.md modules succeeds on disk.
"""

from __future__ import annotations

import py_compile
from pathlib import Path

import pytest

from helpers.env import APP_DIR, import_app, is_windows

pytestmark = [pytest.mark.pure_logic, pytest.mark.harness]

# AGENTS.md required compile set + distribution seams
REQUIRED_COMPILE = [
    "main.py",
    "recorder.py",
    "ui_elements.py",
    "dock_widget.py",
    "video_editor.py",
    "annotation_tool.py",
    "updater.py",
    "distribution.py",
    "startup_integration.py",
]

CORE_IMPORTS = [
    "distribution",
    "user_messages",
    "display_geometry",
    "wasapi_compat",
    "capture_frames",
    "icon_theme",
    "tool_cursors",
    "processing_notice",
    "keycast",
    "microphone_capture",
    "updater",
    "startup_integration",
    "ui_elements",
    "dock_widget",
    "video_editor",
    "annotation_tool",
    "recorder",
    "main",
]


@pytest.mark.parametrize("filename", REQUIRED_COMPILE)
def test_required_modules_bytecode_compile(filename):
    path = APP_DIR / filename
    assert path.is_file(), f"missing required module {path}"
    py_compile.compile(str(path), doraise=True)


@pytest.mark.parametrize("module_name", CORE_IMPORTS)
def test_core_modules_import(module_name):
    mod = import_app(module_name)
    assert mod is not None
    assert getattr(mod, "__file__", None)


def test_app_package_has_no_linux_adapter_imports():
    """Active Windows tree must not import archived linux/ adapters (QA_AUDIT)."""
    offenders = []
    for path in APP_DIR.glob("*.py"):
        text = path.read_text(encoding="utf-8", errors="replace")
        if "linux." in text or "from linux" in text or "import linux" in text:
            # Allow comments mentioning linux archive
            for i, line in enumerate(text.splitlines(), 1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if "import linux" in stripped or "from linux" in stripped:
                    offenders.append(f"{path.name}:{i}:{stripped}")
    assert not offenders, f"Linux adapter imports in active app: {offenders}"


@pytest.mark.windows_native
def test_windows_native_modules_present_on_windows():
    import winreg  # noqa: F401
    import pythoncom  # noqa: F401
    assert is_windows()
