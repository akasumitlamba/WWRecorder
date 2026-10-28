"""Screenshot flow contracts: selection emit, coordinate spaces, naming.

Purpose: cover freeze/select/crop contracts that can be tested without a
physical desktop freeze on Linux (overlay math + path helpers).
Windows GUI cases exercise SelectionOverlay interaction.
"""

from __future__ import annotations

import pytest

from helpers.env import import_app
from helpers.assertions import assert_eq

pytestmark = [pytest.mark.feature_screenshot]


@pytest.fixture(scope="module")
def ui():
    return import_app("ui_elements")


@pytest.fixture(scope="module")
def main_mod():
    return import_app("main")


@pytest.mark.pure_logic
def test_selection_overlay_emits_virtual_desktop_coordinates(qapp, ui):
    from PyQt6.QtCore import QRect

    overlay = ui.SelectionOverlay(mode="record")
    overlay.setGeometry(-900, -120, 800, 600)
    overlay.rect_obj = QRect(25, 30, 200, 100)
    emitted = []
    overlay.selectionChanged.connect(emitted.append)
    overlay._emit_change()
    assert_eq(
        emitted,
        [{"top": -90, "left": -875, "width": 200, "height": 100}],
        because="selection must emit virtual-desktop logical coords (may be negative)",
    )
    overlay._cancel_emitted = True
    overlay.close()


@pytest.mark.pure_logic
def test_screenshot_mode_overlay_constructs(qapp, ui):
    overlay = ui.SelectionOverlay(mode="screenshot")
    assert overlay is not None
    overlay._cancel_emitted = True
    overlay.close()


@pytest.mark.pure_logic
def test_notification_screen_uses_capture_anchor(main_mod, monkeypatch):
    from PyQt6.QtCore import QPoint

    secondary = object()
    primary = object()

    class Screens:
        @staticmethod
        def screenAt(point):
            return secondary if point.x() < 0 else None

        @staticmethod
        def primaryScreen():
            return primary

    monkeypatch.setitem(main_mod._screen_for_anchor.__globals__, "QApplication", Screens)
    assert main_mod._screen_for_anchor(QPoint(-700, 300)) is secondary
    assert main_mod._screen_for_anchor(QPoint(300, 300)) is primary


@pytest.mark.windows_gui
def test_screenshot_hotkey_string_default_is_shift_home(main_mod):
    assert main_mod.DEFAULT_CONFIG["hotkey_screenshot"] == "<shift>+<home>"
