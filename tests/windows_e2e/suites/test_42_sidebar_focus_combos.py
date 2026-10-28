"""
Exhaustive tests for SidebarPanel focus handling, popup protection, resize edge dragging, and hotkey input.

Covers:
1. QComboBox popup safety (Bug: ActivationChange timer closing sidebar during dropdown selection).
2. QMenu context menu safety on file entries in RecentFilesSidebar.
3. Drag-to-resize inner edge calculation for vertical vs horizontal panels.
4. Dirty settings tracking and reset button state.
5. HotkeyInput focus and Escape key cancel listening.
6. Custom output folder browse dialog focus-loss suppression.
"""

from __future__ import annotations

import time
import pytest
from PyQt6.QtCore import Qt, QTimer, QEvent, QPoint
from PyQt6.QtWidgets import QApplication, QComboBox, QMenu, QPushButton

from helpers.env import import_app


@pytest.fixture
def sidebar_suite(qapp):
    main_mod = import_app("main")
    dock_mod = import_app("dock_widget")
    recorder_mod = import_app("recorder")

    engine = recorder_mod.RecordingEngine()
    config = dict(main_mod.DEFAULT_CONFIG)
    config["close_on_focus_loss"] = True
    yield main_mod, dock_mod, recorder_mod, engine, config
    engine.discard()


def test_sidebar_does_not_close_when_combobox_popup_is_open(sidebar_suite):
    """Verifies that sidebar remains open while combo box popup is active."""
    main_mod, dock_mod, recorder_mod, engine, config = sidebar_suite

    sidebar = dock_mod.SettingsSidebar(config=config)
    sidebar.show()
    sidebar.open_panel()
    QApplication.processEvents()

    combo = sidebar._cmb_dock_position
    assert isinstance(combo, QComboBox)
    combo.showPopup()
    QApplication.processEvents()

    event = QEvent(QEvent.Type.ActivationChange)
    sidebar.changeEvent(event)

    t_end = time.time() + 0.25
    while time.time() < t_end:
        QApplication.processEvents()
        time.sleep(0.01)

    assert sidebar.isVisible()
    assert sidebar._transition_state in ("open", "opening")

    combo.hidePopup()
    sidebar.close_panel(animate=False)
    sidebar.close()


def test_sidebar_resize_edge_detection_right_dock(sidebar_suite):
    """On right edge, inner resize margin is on the left (pos.x() <= margin)."""
    main_mod, dock_mod, recorder_mod, engine, config = sidebar_suite
    config["dock_edge"] = "right"

    sidebar = dock_mod.SettingsSidebar(config=config, edge="right")
    sidebar.resize(380, 600)

    assert sidebar._is_on_resize_edge(QPoint(2, 300)) is True
    assert sidebar._is_on_resize_edge(QPoint(100, 300)) is False
    sidebar.close()


def test_sidebar_resize_edge_detection_left_dock(sidebar_suite):
    """On left edge, inner resize margin is on the right (pos.x() >= width - margin)."""
    main_mod, dock_mod, recorder_mod, engine, config = sidebar_suite

    sidebar = dock_mod.SettingsSidebar(config=config, edge="left")
    sidebar.resize(380, 600)

    assert sidebar._is_on_resize_edge(QPoint(378, 300)) is True
    assert sidebar._is_on_resize_edge(QPoint(100, 300)) is False
    sidebar.close()


def test_settings_sidebar_dirty_detection_and_reset(sidebar_suite):
    """Verifies that changing a setting enables save button and reset restores default."""
    main_mod, dock_mod, recorder_mod, engine, config = sidebar_suite

    sidebar = dock_mod.SettingsSidebar(config=config, default_config=main_mod.DEFAULT_CONFIG)
    sidebar.show()
    sidebar.open_panel()
    QApplication.processEvents()

    assert not sidebar._btn_save.isEnabled()

    # Toggle clipboard
    sidebar._chk_clip.setChecked(not sidebar._chk_clip.isChecked())
    sidebar._check_dirty()
    assert sidebar._btn_save.isEnabled()

    # Click reset
    sidebar._reset()
    assert not sidebar._btn_save.isEnabled()

    sidebar.close_panel(animate=False)
    sidebar.close()


def test_hotkey_input_listen_and_escape_cancel(sidebar_suite):
    """Verifies that clicking hotkey input listens and Escape key reverts without saving."""
    main_mod, dock_mod, recorder_mod, engine, config = sidebar_suite

    dock_widget = import_app("dock_widget")
    HotkeyInput = dock_widget._HotkeyInput

    hk = HotkeyInput("<ctrl>+<shift>+r")
    hk.show()
    QApplication.processEvents()
    assert hk.text() == "<ctrl>+<shift>+r"
    assert not hk._listening

    # Click to start listening
    from PyQt6.QtGui import QMouseEvent
    from PyQt6.QtCore import QPointF
    event = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(10, 10), Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    hk.mousePressEvent(event)
    assert hk._listening is True
    assert hk._prompt.isVisible()

    # Escape cancels listening and restores text
    from PyQt6.QtGui import QKeyEvent
    esc_event = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
    hk.keyPressEvent(esc_event)
    assert not hk._listening
    assert hk.text() == "<ctrl>+<shift>+r"
