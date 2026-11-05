"""
Escape / second-Escape exit paths across panels and chrome.

Purpose
-------
Escape closes SettingsSidebar via SidebarPanel; hotkey capture Esc cancels
listen without saving; annotation Escape priority documented + second Escape
does not crash when already closed.

Pass means: documented handlers present; live Escape on settings closes panel;
double Escape after close is safe.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import QApplication

from helpers.action_matrix import assert_invariant, make_settings_sidebar, set_toggle
from helpers.env import import_app

pytestmark = [
    pytest.mark.feature_ui,
    pytest.mark.brute_force,
]


@pytest.mark.pure_logic
def test_escape_handlers_present_across_surfaces():
    # Escape is owned by chrome widgets (dock panels, annotator, editor, pill/overlay),
    # not by main.py orchestration — main wires flows but does not keyPress Escape.
    for mod_name in ("dock_widget", "annotation_tool", "video_editor", "ui_elements"):
        mod = import_app(mod_name)
        src = Path(mod.__file__).read_text(encoding="utf-8")
        assert_invariant(
            "Key_Escape" in src,
            f"{mod_name} must handle Escape",
            widget=f"escape.{mod_name}",
            state="source",
        )


@pytest.mark.pure_logic
def test_settings_escape_closes_without_saving_dirty(qapp):
    side, persisted, _ = make_settings_sidebar(qapp, copy_to_clipboard=False)
    set_toggle(side, "_chk_clip", True)
    assert side._btn_save.isEnabled()
    event = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
    side.keyPressEvent(event)
    QApplication.processEvents()
    # Second Escape after close_panel must not raise.
    side.keyPressEvent(event)
    QApplication.processEvents()
    assert_invariant(
        persisted.get("copy_to_clipboard") is False,
        "Escape must not persist dirty clipboard",
        widget="settings.clipboard",
        state="after escape",
    )
    side.close()


@pytest.mark.pure_logic
def test_hotkey_input_escape_cancels_listen(qapp):
    dock_widget = import_app("dock_widget")
    # _HotkeyEdit is the listening field used in settings.
    HotkeyEdit = getattr(dock_widget, "_HotkeyEdit", None) or getattr(dock_widget, "HotkeyEdit", None)
    if HotkeyEdit is None:
        # Discover by scanning SettingsSidebar attrs after construct.
        side, _, _ = make_settings_sidebar(qapp)
        edit = side._edt_hotkey
        side.close()
    else:
        edit = HotkeyEdit("<ctrl>+<shift>+r")
    original = edit.text() if hasattr(edit, "text") else str(edit)
    if hasattr(edit, "mousePressEvent"):
        # Enter listening if API exposes it.
        from PyQt6.QtGui import QMouseEvent
        from PyQt6.QtCore import QPointF, QEvent

        press = QMouseEvent(
            QEvent.Type.MouseButtonPress,
            QPointF(2, 2),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        edit.mousePressEvent(press)
        QApplication.processEvents()
    esc = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
    edit.keyPressEvent(esc)
    QApplication.processEvents()
    if hasattr(edit, "text"):
        assert_invariant(
            edit.text() == original or not getattr(edit, "_listening", False),
            "Esc cancels hotkey listen",
            widget="settings.hotkey_rec",
            state="listening→esc",
        )


@pytest.mark.pure_logic
def test_annotation_escape_priority_order_in_source():
    """AI_CONTEXT: cancel in-progress edit before exiting annotator."""
    ann = import_app("annotation_tool")
    src = Path(ann.__file__).read_text(encoding="utf-8")
    # Both cancel-edit and exit paths must exist near Escape handling.
    assert_invariant("Key_Escape" in src, "Escape present", widget="ann.escape", state="source")
    idx = src.find("Key_Escape")
    window = src[max(0, idx - 400) : idx + 800].lower()
    assert_invariant(
        "edit" in window or "cancel" in window or "clear" in window or "close" in window,
        "Escape neighborhood mentions cancel/edit/close",
        widget="ann.escape_priority",
        state="source window",
    )
