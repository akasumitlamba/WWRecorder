"""
Gallery / recent-files row action matrix (rename cancel, delete guards).

Purpose: construct RecentFilesSidebar; rename Escape cancels; menu actions
documented; constructing gallery must not delete fixture media.

Pass means: sidebar builds against temp folder; Escape cancel path exists;
fixture PNG survives construct/close.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import QApplication

from helpers.action_matrix import assert_invariant
from helpers.env import import_app
from helpers.media import isolated_output_root, write_tiny_png

pytestmark = [
    pytest.mark.feature_files,
    pytest.mark.feature_ui,
    pytest.mark.brute_force,
]


@pytest.fixture(scope="module")
def dock_widget():
    return import_app("dock_widget")


@pytest.mark.pure_logic
def test_recent_files_sidebar_constructs(qapp, dock_widget, tmp_path):
    out = isolated_output_root(tmp_path)
    write_tiny_png(out / "shot.png")
    side = dock_widget.RecentFilesSidebar(str(out))
    QApplication.processEvents()
    side.close()
    QApplication.processEvents()


@pytest.mark.pure_logic
def test_file_row_rename_escape_cancels(qapp, dock_widget, tmp_path):
    out = isolated_output_root(tmp_path)
    path = write_tiny_png(out / "clip.png")
    renames = []
    row = dock_widget._FileRow(str(path))
    row.rename_requested.connect(lambda old, new: renames.append((old, new)))
    QApplication.processEvents()
    row._start_rename()
    QApplication.processEvents()
    row._rename_edit.setText("should_not_apply")
    esc = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
    row._rename_edit.keyPressEvent(esc)
    QApplication.processEvents()
    assert_invariant(renames == [], "Escape must not emit rename_requested", widget="gallery.rename", state="escape")
    assert_invariant(path.exists(), "file still present after cancel", widget="gallery.rename", state="after esc")
    row.deleteLater()
    QApplication.processEvents()


@pytest.mark.pure_logic
def test_gallery_menu_actions_documented(dock_widget):
    src = Path(dock_widget.__file__).read_text(encoding="utf-8")
    for token in ("Rename", "Delete", "Copy", "Open", "Edit"):
        assert_invariant(token in src, f"gallery menu has {token}", widget=f"gallery.{token.lower()}", state="source")


@pytest.mark.pure_logic
def test_delete_does_not_silently_remove_without_handler(qapp, dock_widget, tmp_path):
    out = isolated_output_root(tmp_path)
    path = write_tiny_png(out / "keep.png")
    before = path.read_bytes()
    side = dock_widget.RecentFilesSidebar(str(out))
    QApplication.processEvents()
    side.close()
    assert_invariant(
        path.exists() and path.read_bytes() == before,
        "media preserved",
        widget="gallery.delete",
        state="construct only",
    )
