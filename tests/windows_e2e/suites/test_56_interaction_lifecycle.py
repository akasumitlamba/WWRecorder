"""
Interaction lifecycle bugs: open a mode, then leave it; discard while save runs.

Pass means
----------
- Escape on the live canvas and photo canvas cancels an in-progress text edit
  and does not commit the text.
- A second Escape after that cancel asks the annotator to close.
- Discard while Stop/mux is in flight does not emit save_completed, and a file
  the mux managed to write is removed.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from helpers.action_matrix import FakeRecordingEngine, assert_invariant
from helpers.env import import_app

pytestmark = [
    pytest.mark.adversarial,
    pytest.mark.pure_logic,
    pytest.mark.feature_annotation,
    pytest.mark.feature_recording,
]


def _escape():
    return QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)


@pytest.mark.area_annotator
def test_live_escape_cancels_text_and_second_escape_requests_close(qapp):
    ann = import_app("annotation_tool")
    canvas = ann.AnnotationCanvas()
    closes = []
    canvas.close_requested.connect(lambda: closes.append(1))
    canvas._text_input_active = True
    canvas._text_buffer = "should not commit"
    canvas._text_pos = (20, 20)
    canvas.keyPressEvent(_escape())
    QApplication.processEvents()
    assert_invariant(not canvas._text_input_active, "text edit cancelled", widget="ann.text", state="escape")
    assert_invariant(
        not any(i.get("type") == "text" for i in canvas._items),
        "cancelled text was not added",
        widget="ann.text",
        state="after escape",
    )
    canvas.keyPressEvent(_escape())
    QApplication.processEvents()
    assert_invariant(bool(closes), "second Escape requests close", widget="ann.escape", state="idle")
    canvas._stopping = True if hasattr(canvas, "_stopping") else None
    canvas.close()


@pytest.mark.area_annotator
def test_photo_escape_cancels_text_without_commit(qapp, tmp_path):
    from helpers.media import write_tiny_png

    ann = import_app("annotation_tool")
    path = write_tiny_png(tmp_path / "shot.png")
    canvas = ann._DrawingArea(str(path))
    canvas._text_input_active = True
    canvas._text_buffer = "leave me out"
    canvas._text_pos = (4, 4)
    canvas.keyPressEvent(_escape())
    QApplication.processEvents()
    assert_invariant(not canvas._text_input_active, "photo text cancelled", widget="ann.photo.text", state="escape")
    assert_invariant(
        not any(isinstance(i, dict) and i.get("type") == "text" for i in canvas._items),
        "photo text not committed",
        widget="ann.photo.text",
        state="after escape",
    )
    canvas.close()


class _SlowEngine(FakeRecordingEngine):
    def __init__(self, output: Path):
        super().__init__()
        self._output = output
        self._recording = True

    def stop_capture(self):
        self.stop_capture_calls += 1
        self._recording = False

    def mux_and_save(self):
        time.sleep(0.35)
        self._output.write_bytes(b"not-a-real-video")
        self.mux_calls += 1
        return str(self._output)

    def is_recording(self):
        return self._recording


@pytest.mark.area_transport
def test_discard_during_mux_does_not_publish_save(qapp, tmp_path):
    ui = import_app("ui_elements")
    main_mod = import_app("main")
    output = tmp_path / "late-save.mkv"
    engine = _SlowEngine(output)
    pill = ui.PillWidget(engine, dict(main_mod.DEFAULT_CONFIG), pre_record=False)
    saved = []
    stopped = []
    pill.save_completed.connect(saved.append)
    pill.stopped.connect(stopped.append)
    pill._initiate_stop()
    pill._initiate_discard(confirm=False)
    QTest.qWait(800)
    QApplication.processEvents()
    assert_invariant(
        any(m == "<DISCARDED>" for m in stopped),
        "discard emitted while mux was in flight",
        widget="pill.discard",
        state="finalizing",
    )
    assert_invariant(saved == [], "late mux must not emit save_completed", widget="pill.stop", state="aborted")
    assert_invariant(not output.exists(), "aborted mux output removed", widget="pill.discard", state=str(output))
    pill._stopping = True
    pill.close()
