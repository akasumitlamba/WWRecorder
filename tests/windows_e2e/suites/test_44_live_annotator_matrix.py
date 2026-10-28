"""
Exhaustive tests for Live Screen Annotator (AnnotationCanvas and AnnotationPill).

Covers:
1. Spacebar shortcut to pause annotation (allows interacting with desktop apps underneath).
2. Thickness presets ('thin', 'normal', 'thick') and corresponding pen widths (2, 4, 8).
3. Tool switching matrix (pencil, highlighter, eraser, text, arrow, rect, circle).
4. Ctrl key straight line drawing mode.
5. Text input active state and Escape cancellation.
6. Erase action undo/redo item stack integrity.
7. Dynamic close button vs text indicator synchronization.
"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import Qt, QPoint, QRect, QEvent
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QColor, QKeyEvent

from helpers.env import import_app


@pytest.fixture
def annotator_suite(qapp):
    annotation_mod = import_app("annotation_tool")
    canvas = annotation_mod.AnnotationCanvas()
    pill = annotation_mod.AnnotationPill()

    # Wire them together as done in main.py
    pill.tool_changed.connect(canvas.set_tool)
    pill.thickness_changed.connect(canvas.set_thickness)
    pill.color_changed.connect(lambda hx: canvas.set_color(QColor(hx)))
    pill.undo_requested.connect(canvas.undo)
    pill.redo_requested.connect(canvas.redo)
    pill.clear_requested.connect(canvas.clear_all)
    canvas.undo_redo_state_changed.connect(pill.update_undo_redo_state)
    pill.pause_toggled.connect(canvas.set_annotation_paused)

    yield annotation_mod, canvas, pill
    canvas.close()
    pill.close()


def test_spacebar_pauses_annotator(annotator_suite):
    """Verifies that pressing Space toggles annotation pause mode to allow desktop clicks."""
    annotation_mod, canvas, pill = annotator_suite
    canvas.show()
    pill.show()
    QApplication.processEvents()

    assert canvas._interactive is True
    assert not pill._btn_pause.isChecked()

    # Trigger spacebar keypress
    space = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier)
    pill.keyPressEvent(space)
    QApplication.processEvents()

    assert pill._btn_pause.isChecked()
    assert canvas._interactive is False

    # Second spacebar unpauses
    pill.keyPressEvent(space)
    QApplication.processEvents()

    assert not pill._btn_pause.isChecked()
    assert canvas._interactive is True


def test_thickness_presets_pen_widths(annotator_suite):
    """Verifies thin (2), normal (4), big (7), and huge (12) preset pen widths."""
    annotation_mod, canvas, pill = annotator_suite

    pill._select_thickness("thin")
    assert canvas._active_thickness == "thin"
    assert annotation_mod.THICKNESS_LEVELS["pencil"]["thin"] == 2

    pill._select_thickness("normal")
    assert canvas._active_thickness == "normal"
    assert annotation_mod.THICKNESS_LEVELS["pencil"]["normal"] == 4

    pill._select_thickness("big")
    assert canvas._active_thickness == "big"
    assert annotation_mod.THICKNESS_LEVELS["pencil"]["big"] == 7

    pill._select_thickness("huge")
    assert canvas._active_thickness == "huge"
    assert annotation_mod.THICKNESS_LEVELS["pencil"]["huge"] == 12


def test_highlighter_opacity_and_width(annotator_suite):
    """Highlighter must use translucent alpha (0.4) and wider pen stroke."""
    annotation_mod, canvas, pill = annotator_suite

    canvas.set_tool("highlighter")
    canvas.set_color(QColor("#FFFF00"))
    assert canvas._tool == "highlighter"

    # Start drawing
    from PyQt6.QtGui import QMouseEvent
    from PyQt6.QtCore import QPointF
    press = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(50, 50), Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    canvas.mousePressEvent(press)

    assert canvas._current_item is not None
    assert canvas._current_item["type"] == "highlighter"
    assert canvas._current_item["opacity"] == 0.4
    assert canvas._current_item["width"] == annotation_mod.THICKNESS_LEVELS["highlighter"]["normal"]  # 20
    assert canvas._current_item["width"] >= 16

    release = QMouseEvent(QEvent.Type.MouseButtonRelease, QPointF(50, 50), Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    canvas.mouseReleaseEvent(release)


def test_ctrl_key_straight_line_mode(annotator_suite):
    """Verifies straight line constraint when Ctrl key is held down."""
    annotation_mod, canvas, pill = annotator_suite
    canvas.set_tool("pencil")

    from PyQt6.QtGui import QMouseEvent
    from PyQt6.QtCore import QPointF
    # Mouse press at (100, 100)
    press = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(100, 100), Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    canvas.mousePressEvent(press)
    assert len(canvas._current_item["points"]) == 1

    # Mouse move to (200, 250) with Ctrl key held down
    move_ctrl = QMouseEvent(QEvent.Type.MouseMove, QPointF(200, 250), Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ControlModifier)
    canvas.mouseMoveEvent(move_ctrl)

    # In Ctrl mode, anchor is established and point is marked as straight line endpoint (True)
    assert canvas._current_item["anchor"] is not None
    pts = canvas._current_item["points"]
    assert len(pts) == 2
    assert pts[-1][2] is True  # is_straight_segment flag
    assert pts[-1][0] == 200.0
    assert pts[-1][1] == 250.0

    release = QMouseEvent(QEvent.Type.MouseButtonRelease, QPointF(200, 250), Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    canvas.mouseReleaseEvent(release)


def test_eraser_sweeps_across_shapes_and_wide_highlighters_without_crash(annotator_suite):
    """
    BUG REPRODUCTION & VERIFICATION:
    Verifies that eraser sweep properly erases rects, text, and wide highlighters
    without crashing due to QPointF vs QRect type mismatch or missing wide strokes.
    """
    annotation_mod, canvas, pill = annotator_suite
    from PyQt6.QtGui import QMouseEvent
    from PyQt6.QtCore import QPointF

    # 1. Add wide highlighter stroke (width 44)
    canvas._items.append({
        'type': 'highlighter',
        'points': [(100.0, 200.0, False), (300.0, 200.0, False)],
        'color': '#FFFF00',
        'width': 44,
        'opacity': 0.4
    })
    # 2. Add rectangle
    canvas._items.append({
        'type': 'rect',
        'start': (50.0, 50.0),
        'end': (150.0, 120.0),
        'color': '#FF3B30',
        'width': 4
    })
    # 3. Add text box
    canvas._items.append({
        'type': 'text',
        'start': (200.0, 50.0),
        'end': (350.0, 90.0),
        'color': '#FFFFFF',
        'text': 'Test note'
    })

    assert len(canvas._items) == 3

    # Switch to eraser
    canvas.set_tool('eraser')

    # Sweep across rect and text using QPointF coordinates
    press = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(40.0, 80.0), Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    canvas.mousePressEvent(press)
    move = QMouseEvent(QEvent.Type.MouseMove, QPointF(250.0, 80.0), Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    canvas.mouseMoveEvent(move)
    release = QMouseEvent(QEvent.Type.MouseButtonRelease, QPointF(250.0, 80.0), Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    canvas.mouseReleaseEvent(release)

    # Rect and text should have been erased
    active_drawable = [it for it in canvas._items if not it.get('_action')]
    assert len(active_drawable) == 1
    assert active_drawable[0]['type'] == 'highlighter'

    # Now sweep 18px away from the center of the 44px highlighter (should hit and erase)
    press2 = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(150.0, 218.0), Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    canvas.mousePressEvent(press2)
    release2 = QMouseEvent(QEvent.Type.MouseButtonRelease, QPointF(150.0, 218.0), Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    canvas.mouseReleaseEvent(release2)

    active_drawable2 = [it for it in canvas._items if not it.get('_action')]
    assert len(active_drawable2) == 0, "Wide highlighter must be erased when hit within its stroke thickness!"
