"""Pytest configuration for Windows E2E Testing (tests/windows_e2e).

Loaded automatically when collecting this package. Applies path/stub setup
*before* suite modules import app code. Does not mutate product source.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Make helpers importable as ``helpers.*`` when pytest collects this directory.
_E2E_ROOT = Path(__file__).resolve().parent
if str(_E2E_ROOT) not in sys.path:
    sys.path.insert(0, str(_E2E_ROOT))

from helpers.env import (  # noqa: E402
    DEFAULT_REPORT_DIR,
    prepare_process_environment,
    is_windows,
)
from helpers.qt_session import qapp, qtbot_compat  # noqa: E402,F401


# Apply environment as early as conftest import so collection-time imports work.
_ENV_APPLIED = prepare_process_environment()


def pytest_configure(config):
    """Register feature markers used for selective runs and report tagging."""
    markers = {
        "feature_recording": "Recording / capture engine / pill / border contracts",
        "feature_screenshot": "Screenshot freeze / crop / clipboard contracts",
        "feature_audio": "Microphone / system audio / WASAPI / mixing",
        "feature_annotation": "Live and photo annotation / undo / Escape",
        "feature_editor": "Video editor / export / Save As non-destructive",
        "feature_playback": "Playback transport / fullscreen chrome",
        "feature_hotkeys": "Global hotkey validation / listener ownership",
        "feature_ui": "Dock / panels / tray / visual chrome",
        "feature_settings": "Settings schema / drafts / persistence",
        "feature_distribution": "EXE vs MSIX parity hooks / updater guards",
        "feature_startup": "Start with Windows / StartupTask / Run key seams",
        "feature_keycast": "Keycast overlay during recording",
        "feature_geometry": "Multi-monitor / DPI / negative virtual desktop",
        "feature_icons": "Icon theme / tool cursors / branding",
        "feature_processing": "Processing notice / saving popup / recovery messaging",
        "feature_files": "Recent files / rename / delete / path safety",
        "pure_logic": "No GUI interaction; safe on offscreen / stubbed Linux",
        "windows_gui": "Requires interactive Windows desktop + real Qt GUI",
        "windows_native": "Requires win32 / WASAPI / WinRT (skip on non-Windows)",
        "harness": "Validates the E2E harness itself (must stay green)",
        "behavior_question": "Asserts documented intent; may skip if live code contradicts pending user decision",
        "brute_force": "Combinatorial / exhaustive action matrices (toggles×exits, spam, busy)",
        "settings_matrix": "Settings draft toggle/combo × save/cancel/Escape matrices",
        "parallel_actions": "Overlapping / interleaved / busy-state action guards",
        "adversarial": "Hostile interaction / type-coercion / illegal-transition audit cases",
        "area_dock": "Area 1 — edge dock & companion sidebars",
        "area_selection": "Area 2 — screen selection & overlay handles",
        "area_transport": "Area 3 — recording transport pill state machine",
        "area_annotator": "Area 4 — live annotator & photo editor",
        "area_editor": "Area 5 — video player / trimmer / export",
    }
    for name, desc in markers.items():
        config.addinivalue_line("markers", f"{name}: {desc}")


def pytest_collection_modifyitems(config, items):
    """Auto-skip windows_gui / windows_native off Windows; never silent-pass them."""
    if is_windows():
        return
    skip_gui = pytest.mark.skip(reason="WINDOWS-ONLY: windows_gui requires interactive Windows desktop")
    skip_native = pytest.mark.skip(reason="WINDOWS-ONLY: windows_native requires win32/WASAPI/WinRT")
    for item in items:
        if "windows_gui" in item.keywords:
            item.add_marker(skip_gui)
        if "windows_native" in item.keywords:
            item.add_marker(skip_native)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Attach feature_* markers as JUnit properties for the QA report generator."""
    outcome = yield
    report = outcome.get_result()
    if report.when != "call":
        return
    features = sorted(
        m.name[len("feature_") :]
        for m in item.iter_markers()
        if m.name.startswith("feature_")
    )
    if features and hasattr(report, "user_properties"):
        report.user_properties.append(("features", ",".join(features)))


@pytest.fixture(scope="session")
def e2e_report_dir(tmp_path_factory) -> Path:
    """Preferred report directory; runners override via WWR_E2E_REPORT_DIR."""
    override = os.environ.get("WWR_E2E_REPORT_DIR", "").strip()
    if override:
        path = Path(override)
    else:
        path = DEFAULT_REPORT_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


@pytest.fixture(scope="session")
def e2e_env_info() -> dict:
    return {
        "platform": sys.platform,
        "is_windows": is_windows(),
        "env_applied": _ENV_APPLIED,
        "qt_platform": os.environ.get("QT_QPA_PLATFORM", ""),
    }
