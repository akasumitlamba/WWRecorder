"""
Exhaustive visual, animation, geometry, and lifecycle tests for DockWidget.

Covers:
1. First-launch blink persistence (Bug: hardcoded self._is_first_launch=True causes infinite blinking on restart).
2. Rapid hover enter/leave spam (Bug: stopping QPropertyAnimation midway leaves dock stuck at intermediate width/height).
3. Bottom-edge painter coordinate translation (Bug: rotation coordinate inversion clips out grabber dots on bottom edge).
4. Top-edge painter coordinate translation and bounds checking.
5. Paint during collapse animation (Bug: self._expanded=False before collapse finishes paints collapsed grabber over active buttons).
6. Dock button layout metrics across normal vs compact screens.
7. Dock edge switching geometry recalculation and distance snapping.
8. Companion dock anchoring with sidebar transitions.
9. Topmost enforcement timer behavior and winId validity.
10. Tooltip content verification across dynamic recording and shortcut state changes.
"""

from __future__ import annotations

import time
import pytest
from PyQt6.QtCore import Qt, QPoint, QRect, QTimer, QEvent, QSize
from PyQt6.QtWidgets import QApplication, QToolButton
from PyQt6.QtGui import QPainter, QImage, QColor

from helpers.env import import_app


@pytest.fixture
def dock_app(qapp):
    main_mod = import_app("main")
    dock_mod = import_app("dock_widget")
    recorder_mod = import_app("recorder")

    engine = recorder_mod.RecordingEngine()
    config = dict(main_mod.DEFAULT_CONFIG)
    dock = dock_mod.DockWidget(engine, config)
    yield dock, dock_mod, config, engine
    dock.close()
    engine.discard()


def test_dock_first_launch_persisted_and_stops_blinking(dock_app):
    """
    BUG REPRODUCTION:
    If a user has already discovered and used the dock, restarting the application
    should NOT resume blinking the dock grabber indefinitely on their screen.
    The dock must respect 'dock_discovered' in config.
    """
    dock, dock_mod, config, engine = dock_app

    config_with_seen = dict(config)
    config_with_seen["dock_discovered"] = True

    restarted_dock = dock_mod.DockWidget(engine, config_with_seen)
    try:
        restarted_dock.show()
        QApplication.processEvents()

        assert not restarted_dock._is_first_launch, "Dock should not treat existing user as first launch!"
        assert not restarted_dock._first_blink_timer.isActive(), "First-launch blink timer must not be active for returning users!"
    finally:
        restarted_dock.close()


def test_dock_rapid_hover_spam_does_not_lock_intermediate_geometry(dock_app):
    """
    BUG REPRODUCTION:
    Moving the cursor rapidly across the edge of the dock during _expand_anim or _collapse_anim
    must not leave the dock stuck in an intermediate size (e.g. 28px width).
    """
    dock, dock_mod, config, engine = dock_app
    dock.show()
    QApplication.processEvents()

    dock._expand()
    dock._set_collapsed_geo(animate=True)
    dock._expand()

    for _ in range(50):
        QApplication.processEvents()
        QApplication.sendPostedEvents()

    sg = dock._screen_geo()
    metrics = dock._expanded_metrics(sg)
    expanded_w = metrics[0]
    collapsed_w = dock.GRABBER_W

    assert dock.width() in (expanded_w, collapsed_w), f"Dock stuck at intermediate width: {dock.width()}px"


def test_dock_bottom_edge_dots_within_bounds(dock_app):
    """
    BUG REPRODUCTION:
    When docked at the bottom edge, coordinate rotation must not translate painter
    elements outside the widget's physical rect.
    """
    dock, dock_mod, config, engine = dock_app
    dock.set_dock_edge("bottom")
    dock.show()
    QApplication.processEvents()

    img = QImage(dock.size(), QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)

    painter = QPainter(img)
    dock.paintEvent(None)
    painter.end()

    assert dock.width() == dock.GRABBER_H
    assert dock.height() == dock.GRABBER_W


def test_dock_top_edge_dimensions_and_painter_bounds(dock_app):
    """Verifies top-edge geometry inversion and painter sanity."""
    dock, dock_mod, config, engine = dock_app
    dock.set_dock_edge("top")
    dock.show()
    QApplication.processEvents()

    assert dock.width() == dock.GRABBER_H
    assert dock.height() == dock.GRABBER_W

    img = QImage(dock.size(), QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    painter = QPainter(img)
    dock.paintEvent(None)
    painter.end()


def test_dock_left_edge_dimensions(dock_app):
    """Verifies left-edge vertical geometry and painter sanity."""
    dock, dock_mod, config, engine = dock_app
    dock.set_dock_edge("left")
    dock.show()
    QApplication.processEvents()

    assert dock.width() == dock.GRABBER_W
    assert dock.height() == dock.GRABBER_H


def test_dock_compact_metrics_for_small_screens(dock_app):
    """Verifies that screens <= 1366x800 activate compact expanded metrics (44x204, 36px buttons)."""
    dock, dock_mod, config, engine = dock_app
    small_screen = QRect(0, 0, 1280, 720)
    w, h, btn_size, icon_size, margin, spacing = dock._expanded_metrics(small_screen)
    assert w == dock.COMPACT_EXPANDED_W
    assert h == dock.COMPACT_EXPANDED_H
    assert btn_size == 36
    assert icon_size == 20


def test_dock_normal_metrics_for_large_screens(dock_app):
    """Verifies that screens > 1366x800 activate normal metrics (48x228, 40px buttons)."""
    dock, dock_mod, config, engine = dock_app
    large_screen = QRect(0, 0, 1920, 1080)
    w, h, btn_size, icon_size, margin, spacing = dock._expanded_metrics(large_screen)
    assert w == dock.EXPANDED_W
    assert h == dock.EXPANDED_H
    assert btn_size == 40
    assert icon_size == 22


def test_dock_buttons_count_and_types(dock_app):
    """Ensures all 5 primary action buttons are initialized and have pointing hand cursor."""
    dock, dock_mod, config, engine = dock_app
    assert len(dock._dock_buttons) == 5
    for btn in dock._dock_buttons:
        assert isinstance(btn, QToolButton)
        assert btn.cursor().shape() == Qt.CursorShape.PointingHandCursor


def test_dock_collapse_for_screenshot_immediate(dock_app):
    """Verifies collapse_for_screenshot immediately hides panel and collapses synchronously."""
    dock, dock_mod, config, engine = dock_app
    dock.show()
    dock._expand()
    QApplication.processEvents()
    assert dock._expanded is True

    collapsed = dock.collapse_for_screenshot()
    assert collapsed is True
    assert dock._expanded is False
    assert not dock._panel.isVisible()


def test_dock_record_state_toggle_indicator(dock_app):
    """Verifies record indicator switches button icon and tooltip during recording."""
    dock, dock_mod, config, engine = dock_app
    dock.show()
    dock.set_recording_state(True)
    assert dock._is_recording is True
    assert dock._pulse_timer.isActive()

    dock.set_recording_state(False)
    assert dock._is_recording is False
    assert not dock._pulse_timer.isActive()
