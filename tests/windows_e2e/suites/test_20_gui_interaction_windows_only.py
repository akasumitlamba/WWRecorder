"""Interactive Windows GUI smoke — skipped on non-Windows by marker.

Purpose: light widget show/hide for dock, pill, settings, overlay.
These are NOT a substitute for full hardware capture acceptance.

Preconditions: Windows desktop session, Qt not forced offscreen unless
WWR_E2E_FORCE_OFFSCREEN=1 (then still runs but with limited fidelity).
Pass means: widgets construct, show, and close without uncaught exceptions.
"""

from __future__ import annotations

import os

import pytest

from helpers.env import import_app, is_windows
from helpers.waits import wait_until

pytestmark = [pytest.mark.windows_gui, pytest.mark.feature_ui]


@pytest.fixture
def skip_if_offscreen_forced():
    if os.environ.get("QT_QPA_PLATFORM") == "offscreen":
        pytest.skip(
            "QT_QPA_PLATFORM=offscreen — interactive GUI fidelity not claimed; "
            "unset platform or avoid WWR_E2E_FORCE_OFFSCREEN for desktop GUI smoke"
        )


def test_pill_widget_pre_record_constructs(qapp, skip_if_offscreen_forced):
    from types import SimpleNamespace

    ui = import_app("ui_elements")
    main_mod = import_app("main")
    engine = SimpleNamespace(
        list_microphones=lambda: [],
        get_system_audio=lambda: True,
        get_mic=lambda: True,
        is_recording=False,
        is_paused=False,
        discard=lambda: None,
    )
    pill = ui.PillWidget(engine, dict(main_mod.DEFAULT_CONFIG), pre_record=True)
    pill.show()
    qapp.processEvents()
    wait_until(lambda: pill.isVisible(), timeout_s=2.0, message="pill not visible")
    pill.close()
    qapp.processEvents()


def test_selection_overlay_record_mode_show_cancel(qapp, skip_if_offscreen_forced):
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest

    ui = import_app("ui_elements")
    overlay = ui.SelectionOverlay(mode="record")
    overlay.show()
    qapp.processEvents()
    QTest.keyClick(overlay, Qt.Key.Key_Escape)
    qapp.processEvents()
    overlay._cancel_emitted = True
    overlay.close()


def test_settings_sidebar_show_close(qapp, skip_if_offscreen_forced):
    dock_widget = import_app("dock_widget")
    sidebar = dock_widget.SettingsSidebar({"current_version": "1.7.0"})
    sidebar.show()
    qapp.processEvents()
    sidebar.close()
    qapp.processEvents()


def test_environment_is_windows():
    assert is_windows(), "windows_gui marker should have skipped on non-Windows"
