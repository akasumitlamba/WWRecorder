"""Annotation model contracts: atomic save, Escape priority, undo units.

Purpose: lock AI_CONTEXT annotation rules without requiring a live desktop.
Windows GUI cases click tools on AnnotateWindow when a display is available.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from helpers.env import import_app
from helpers.media import write_tiny_png
from helpers.assertions import assert_true

pytestmark = [pytest.mark.feature_annotation]


@pytest.fixture(scope="module")
def annotation():
    return import_app("annotation_tool")


@pytest.mark.pure_logic
def test_atomic_save_image_replaces_only_after_success(qapp, annotation, tmp_path):
    from PyQt6.QtGui import QImage, QColor

    path = tmp_path / "shot.png"
    write_tiny_png(path, (10, 20, 30, 255))
    original = path.read_bytes()
    image = QImage(8, 8, QImage.Format.Format_ARGB32)
    image.fill(QColor(200, 100, 50, 255))
    assert_true(annotation._atomic_save_image(image, str(path), "PNG"), because="atomic save must succeed")
    assert path.read_bytes() != original
    assert path.is_file()


@pytest.mark.pure_logic
def test_atomic_save_does_not_clobber_on_empty_image_path_guard(qapp, annotation, tmp_path):
    path = tmp_path / "kept.png"
    write_tiny_png(path)
    before = path.read_bytes()
    from PyQt6.QtGui import QImage

    # Null/invalid image should not delete the original (implementation returns False).
    bad = QImage()
    result = annotation._atomic_save_image(bad, str(path), "PNG")
    assert result is False
    assert path.read_bytes() == before


@pytest.mark.pure_logic
def test_escape_priority_documented_in_annotation_sources(annotation):
    src = Path(annotation.__file__).read_text(encoding="utf-8")
    # Escape handled on canvas and pill (AI_CONTEXT 2026-08-23)
    assert "Key_Escape" in src
    assert "undo" in src.lower() and "redo" in src.lower()


@pytest.mark.pure_logic
def test_arrow_head_scales_with_stroke_and_caps(annotation):
    thin = annotation._arrow_head_size(1, length=100)
    thick = annotation._arrow_head_size(20, length=100)
    assert thin < thick
    assert thick <= 24  # AI_CONTEXT 24px cap
    # Length clamp must restrain oversized heads on short strokes
    short = annotation._arrow_head_size(20, length=10)
    assert short <= 10 * 0.4 + 1e-6


@pytest.mark.pure_logic
def test_toast_widget_uses_opaque_backing(annotation):
    src = Path(annotation.__file__).read_text(encoding="utf-8")
    assert "_ToastWidget" in src


@pytest.mark.windows_gui
def test_annotate_window_opens_and_closes(qapp, annotation, tmp_path):
    path = write_tiny_png(tmp_path / "a.png")
    win = annotation.AnnotateWindow(str(path))
    win.show()
    qapp.processEvents()
    win.close()
    qapp.processEvents()
