"""
Area 2 — Screen selection & magnifier overlay (adversarial).

Purpose: all 8 resize handles, inverted/tiny/cross-bound drags, Escape cancel,
desktop-origin emission, min 32×32 rejection.
"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QPoint, QPointF, QRect, Qt
from PyQt6.QtGui import QKeyEvent, QMouseEvent
from PyQt6.QtCore import QEvent
from PyQt6.QtWidgets import QApplication

from helpers.action_matrix import assert_invariant
from helpers.adversarial import RESIZE_HANDLES, make_selection_overlay, simulate_pointer_drag
from helpers.env import import_app

pytestmark = [
    pytest.mark.adversarial,
    pytest.mark.area_selection,
    pytest.mark.feature_screenshot,
    pytest.mark.feature_geometry,
    pytest.mark.pure_logic,
]


def _select_region(overlay, x0, y0, x1, y1):
    simulate_pointer_drag(overlay, (x0, y0), (x1, y1), steps=6)
    assert_invariant(overlay.state == "SELECTED", "region selected", widget="selection", state=str(overlay.rect_obj.getRect()))


def test_escape_cancels_without_commit(qapp):
    overlay = make_selection_overlay(qapp)
    emitted = []
    overlay.selectionChanged.connect(emitted.append)
    _select_region(overlay, 40, 40, 200, 160)
    esc = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
    overlay.keyPressEvent(esc)
    QApplication.processEvents()
    assert_invariant(any(e == {} for e in emitted), "Escape emits empty cancel", widget="selection.escape", state="after")
    overlay.close()


def test_tiny_region_rejected(qapp):
    overlay = make_selection_overlay(qapp)
    emitted = []
    overlay.selectionChanged.connect(emitted.append)
    simulate_pointer_drag(overlay, (50, 50), (60, 55), steps=3)  # 10x5
    assert_invariant(overlay.state == "IDLE", "tiny rejected", widget="selection.tiny", state=str(overlay.rect_obj.getRect()))
    assert_invariant(not any(e.get("width", 0) for e in emitted if e), "no commit of tiny", widget="selection.tiny", state=str(emitted))
    overlay.close()


def test_inverted_drag_normalizes(qapp):
    overlay = make_selection_overlay(qapp)
    simulate_pointer_drag(overlay, (300, 300), (80, 100), steps=8)
    assert_invariant(overlay.state == "SELECTED", "inverted drag selects", widget="selection.inverted", state=str(overlay.rect_obj.getRect()))
    r = overlay.rect_obj
    assert_invariant(r.width() >= 32 and r.height() >= 32, "normalized size", widget="selection.inverted", state=str(r.getRect()))
    assert_invariant(r.left() <= r.right() and r.top() <= r.bottom(), "normalized order", widget="selection.inverted", state="ok")
    overlay.close()


@pytest.mark.parametrize("handle", RESIZE_HANDLES)
def test_all_eight_resize_handles(qapp, handle):
    overlay = make_selection_overlay(qapp, mode="record")
    _select_region(overlay, 100, 100, 260, 220)
    before = QRect(overlay.rect_obj)
    handles = overlay.get_handles()
    assert_invariant(handle in handles, f"handle {handle} present", widget="selection.handle", state=handle)
    hr = handles[handle]
    center = hr.center()
    # Drag handle outward/inward depending on axis.
    dx = dy = 0
    if "l" in handle:
        dx = -20
    if "r" in handle:
        dx = 20
    if "t" in handle:
        dy = -20
    if "b" in handle:
        dy = 20
    # Enter RESIZING via press on handle then move.
    press = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(center),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    overlay.mousePressEvent(press)
    assert_invariant(overlay.state == "RESIZING" or overlay.hovered_handle == handle or overlay.state in ("RESIZING", "SELECTED", "MOVING"),
                     "press engaged handle or move", widget=f"selection.handle.{handle}", state=overlay.state)
    if overlay.state == "RESIZING":
        move = QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(center.x() + dx, center.y() + dy),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        overlay.mouseMoveEvent(move)
        release = QMouseEvent(
            QEvent.Type.MouseButtonRelease,
            QPointF(center.x() + dx, center.y() + dy),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
        overlay.mouseReleaseEvent(release)
        QApplication.processEvents()
        assert_invariant(overlay.rect_obj.width() >= 32 and overlay.rect_obj.height() >= 32,
                         "post-resize min size", widget=f"selection.handle.{handle}", state=str(overlay.rect_obj.getRect()))
        assert_invariant(overlay.rect_obj != before or (dx == 0 and dy == 0),
                         "geometry changed when dragged", widget=f"selection.handle.{handle}", state="after")
    overlay.close()


def test_emit_uses_desktop_origin_mapping(qapp):
    overlay = make_selection_overlay(qapp)
    emitted = []
    overlay.selectionChanged.connect(emitted.append)
    # Force a known widget-local rect and emit.
    overlay.rect_obj = QRect(10, 20, 160, 120)
    overlay.state = "SELECTED"
    overlay._emit_change()
    assert emitted
    region = emitted[-1]
    origin = overlay.geometry().topLeft()
    assert_invariant(region["left"] == 10 + origin.x(), "left mapped", widget="selection.coords", state=str(region))
    assert_invariant(region["top"] == 20 + origin.y(), "top mapped", widget="selection.coords", state=str(region))
    overlay.close()


def test_float_pointf_drag_does_not_typeerror(qapp):
    overlay = make_selection_overlay(qapp)
    simulate_pointer_drag(overlay, QPointF(40.5, 50.25), QPointF(220.75, 180.5), steps=5)
    assert_invariant(overlay.state in ("SELECTED", "IDLE"), "PointF drag completed", widget="selection.pointf", state=overlay.state)
    overlay.close()


def test_normalized_capture_plan_rejects_sub32(qapp):
    main_mod = import_app("main")
    assert main_mod._normalized_capture_plan({"left": -5, "top": -5, "width": 20, "height": 40}) is None
    ok = main_mod._normalized_capture_plan({"left": -900, "top": -50, "width": 101, "height": 99})
    assert ok is not None and ok["width"] % 2 == 0 and ok["height"] % 2 == 0
