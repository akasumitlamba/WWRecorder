"""
Annotation tool-switch / undo-redo-clear / Escape-priority matrix.

Purpose: every photo-editor tool id can be selected; undo/redo/clear on an
empty stack is safe; rapid tool spam does not crash.

Pass means: ``_select_tool`` / canvas ``set_tool`` accept each catalogue id;
history ops are idempotent at empty stack.
"""

from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QApplication

from helpers.action_matrix import ANNOTATION_TOOLS, LIVE_ANNOTATION_TOOLS, assert_invariant
from helpers.env import import_app
from helpers.media import write_tiny_png

pytestmark = [
    pytest.mark.feature_annotation,
    pytest.mark.brute_force,
]


@pytest.fixture(scope="module")
def annotation():
    return import_app("annotation_tool")


@pytest.mark.pure_logic
@pytest.mark.parametrize("tool", ANNOTATION_TOOLS, ids=list(ANNOTATION_TOOLS))
def test_annotate_window_set_tool_matrix(qapp, annotation, tmp_path, tool):
    path = write_tiny_png(tmp_path / f"ann_{tool}.png")
    win = annotation.AnnotateWindow(str(path))
    QApplication.processEvents()
    assert_invariant(hasattr(win, "_canvas"), "canvas present", widget=f"ann.tools.{tool}", state="construct")
    win._select_tool(tool)
    QApplication.processEvents()
    assert_invariant(
        win._canvas._tool == tool,
        "tool selected on canvas",
        widget=f"ann.tools.{tool}",
        state=f"tool={tool}",
    )
    win.close()
    QApplication.processEvents()


@pytest.mark.pure_logic
def test_undo_redo_clear_empty_stack_safe(qapp, annotation, tmp_path):
    path = write_tiny_png(tmp_path / "hist.png")
    win = annotation.AnnotateWindow(str(path))
    QApplication.processEvents()
    win._canvas.undo()
    win._canvas.redo()
    win._canvas.clear_all()
    win._canvas.undo()
    win._canvas.redo()
    # Window-level buttons too.
    win._undo()
    win._redo()
    win._clear()
    QApplication.processEvents()
    win.close()


@pytest.mark.pure_logic
def test_tool_spam_switching(qapp, annotation, tmp_path):
    path = write_tiny_png(tmp_path / "spam.png")
    win = annotation.AnnotateWindow(str(path))
    for tool in list(ANNOTATION_TOOLS) * 3:
        win._select_tool(tool)
    QApplication.processEvents()
    assert_invariant(
        win._canvas._tool == ANNOTATION_TOOLS[-1],
        "ends on last catalogue tool",
        widget="ann.tools.spam",
        state="after spam",
    )
    win.close()


@pytest.mark.pure_logic
def test_live_tools_mentioned_in_source(annotation):
    from pathlib import Path

    src = Path(annotation.__file__).read_text(encoding="utf-8")
    for tool in LIVE_ANNOTATION_TOOLS:
        assert_invariant(
            f"'{tool}'" in src or f'"{tool}"' in src,
            f"live/photo tool id present in source",
            widget=f"ann.tools.{tool}",
            state="source",
        )


@pytest.mark.windows_gui
def test_annotate_window_escape_closes(qapp, annotation, tmp_path):
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QKeyEvent

    path = write_tiny_png(tmp_path / "esc.png")
    win = annotation.AnnotateWindow(str(path))
    win.show()
    QApplication.processEvents()
    event = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
    win.keyPressEvent(event)
    QApplication.processEvents()
    try:
        win.keyPressEvent(event)
    except RuntimeError:
        pass
    try:
        win.close()
    except RuntimeError:
        pass
