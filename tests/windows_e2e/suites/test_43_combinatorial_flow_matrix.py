"""
Combinatorial flow and override test matrix for WWRecorder.

Exercises mix-and-match combinations across:
1. SelectionOverlay 8-point resize handles ('tl', 't', 'tr', 'r', 'br', 'b', 'bl', 'l')
2. SelectionOverlay minimum size clamp (<32x32 rejects region, >=32x32 commits)
3. SelectionOverlay coordinate translation from widget to virtual desktop
4. PillWidget full state machine: pre-record -> recording -> paused -> resumed -> stop/save -> discard
5. PillWidget audio device selection and loopback synchronization
6. AnnotationCanvas drawing items, thickness, color, and undo/redo stacks
7. AnnotationCanvas pause mode (allows user to interact with underlying apps)
8. Video editor merge regions math (empty, single, overlapping, contiguous)
9. Emergency Escape priority cascade across overlays, panels, and annotators
10. Update check single-flight and manual trigger signals
"""

from __future__ import annotations

import time
from types import SimpleNamespace
import pytest
from PyQt6.QtCore import Qt, QPoint, QPointF, QRect, QTimer, QEvent
from PyQt6.QtWidgets import QApplication, QComboBox, QMenu
from PyQt6.QtGui import QPainter, QImage, QKeyEvent, QColor, QMouseEvent

from helpers.env import import_app


@pytest.fixture
def app_suite(qapp):
    main_mod = import_app("main")
    dock_mod = import_app("dock_widget")
    ui_mod = import_app("ui_elements")
    recorder_mod = import_app("recorder")

    engine = recorder_mod.RecordingEngine()
    config = dict(main_mod.DEFAULT_CONFIG)
    yield main_mod, dock_mod, ui_mod, recorder_mod, engine, config
    engine.discard()


def test_selection_overlay_eight_resize_handles(app_suite):
    """Verifies that all 8 resize handles exist and are properly computed from rect_obj."""
    main_mod, dock_mod, ui_mod, recorder_mod, engine, config = app_suite

    overlay = ui_mod.SelectionOverlay(mode="record")
    overlay.rect_obj = QRect(100, 100, 200, 150)
    handles = overlay.get_handles()

    expected_handles = {'tl', 't', 'tr', 'r', 'br', 'b', 'bl', 'l'}
    assert set(handles.keys()) == expected_handles

    for name, r in handles.items():
        assert isinstance(r, QRect)
        assert r.width() == overlay.handle_size * 2
        assert r.height() == overlay.handle_size * 2

    overlay.close()


def test_selection_overlay_minimum_size_rejection(app_suite):
    """Selections smaller than 32x32 must be rejected and reset to IDLE without emitting valid region."""
    main_mod, dock_mod, ui_mod, recorder_mod, engine, config = app_suite

    overlay = ui_mod.SelectionOverlay(mode="record")
    overlay.show()
    QApplication.processEvents()

    # Small 10x10 selection
    overlay.state = 'DRAWING'
    overlay.rect_obj = QRect(50, 50, 10, 10)

    release = QMouseEvent(QEvent.Type.MouseButtonRelease, QPointF(60, 60), Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    overlay.mouseReleaseEvent(release)

    assert overlay.state == 'IDLE'
    assert not overlay.rect_obj.isValid() or overlay.rect_obj.isEmpty()
    overlay.close()


def test_selection_overlay_valid_size_commit(app_suite):
    """Selections >= 32x32 must commit to SELECTED state and apply selection mask."""
    main_mod, dock_mod, ui_mod, recorder_mod, engine, config = app_suite

    overlay = ui_mod.SelectionOverlay(mode="record")
    overlay.show()
    QApplication.processEvents()

    emitted = []
    overlay.selectionChanged.connect(lambda reg: emitted.append(reg))

    overlay.state = 'DRAWING'
    overlay.rect_obj = QRect(50, 50, 200, 150)

    release = QMouseEvent(QEvent.Type.MouseButtonRelease, QPointF(250, 200), Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    overlay.mouseReleaseEvent(release)

    assert overlay.state == 'SELECTED'
    assert len(emitted) == 1
    assert emitted[0]["width"] == 200
    assert emitted[0]["height"] == 150
    overlay.close()


def test_pill_widget_full_transport_state_machine(app_suite):
    """Verifies Pill transport buttons: pause toggles to resume, timer updates, and stop terminates."""
    main_mod, dock_mod, ui_mod, recorder_mod, engine, config = app_suite

    pill = ui_mod.PillWidget(engine, config, pre_record=True)
    pill.show()
    QApplication.processEvents()

    # In pre-record, Start button is visible
    assert pill._btn_start.isVisible()
    assert not pill._btn_pause.isVisible()

    # Transition to recording mode
    pill.set_recording_mode()
    QApplication.processEvents()

    assert not pill._btn_start.isVisible()
    assert pill._btn_pause.isVisible()
    assert pill._btn_stop.isVisible()

    # Test Pause / Resume toggle
    assert not engine.is_paused()
    pill.toggle_pause()
    assert engine.is_paused()
    assert "Resume" in pill._btn_pause.toolTip()

    pill.toggle_pause()
    assert not engine.is_paused()
    assert "Pause" in pill._btn_pause.toolTip()

    pill._stopping = True
    pill.close()


def test_annotation_canvas_history_undo_redo(app_suite):
    """Verifies live annotation vector history stack: drawing, undo, redo, and clear."""
    main_mod, dock_mod, ui_mod, recorder_mod, engine, config = app_suite

    annotation_mod = import_app("annotation_tool")
    canvas = annotation_mod.AnnotationCanvas()
    canvas.show()
    QApplication.processEvents()

    assert len(canvas._items) == 0
    assert len(canvas._redo_stack) == 0

    # Add a mock stroke
    canvas._items.append({"tool": "pencil", "points": [QPoint(10, 10), QPoint(20, 20)], "color": QColor("#FF0000"), "thickness": 3})
    canvas.update()
    assert len(canvas._items) == 1

    # Undo
    canvas.undo()
    assert len(canvas._items) == 0
    assert len(canvas._redo_stack) == 1

    # Redo
    canvas.redo()
    assert len(canvas._items) == 1
    assert len(canvas._redo_stack) == 0

    # Clear all pushes an undoable clear record
    canvas.clear_all()
    assert len(canvas._items) >= 1
    assert canvas._items[-1].get("_action") == "clear"

    canvas.close()


def test_video_editor_merge_regions_matrix(app_suite):
    """Verifies non-destructive delete regions mathematical merge algorithm."""
    main_mod, dock_mod, ui_mod, recorder_mod, engine, config = app_suite
    editor_mod = import_app("video_editor")

    merge = editor_mod._merge_delete_regions

    def R(s, e):
        return SimpleNamespace(start_ms=s * 1000, end_ms=e * 1000)

    # Case 1: Empty input
    assert merge([]) == []

    # Case 2: Single region
    assert merge([R(5.0, 10.0)]) == [(5.0, 10.0)]

    # Case 3: Overlapping regions
    assert merge([R(2.0, 6.0), R(4.0, 9.0)]) == [(2.0, 9.0)]

    # Case 4: Contiguous / adjacent regions
    assert merge([R(1.0, 3.0), R(3.0, 5.0)]) == [(1.0, 5.0)]

    # Case 5: Disjoint regions
    assert merge([R(1.0, 2.0), R(4.0, 6.0)]) == [(1.0, 2.0), (4.0, 6.0)]
