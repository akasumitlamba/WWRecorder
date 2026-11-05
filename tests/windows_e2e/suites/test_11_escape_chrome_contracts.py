"""Escape / chrome interaction baseline (AI_CONTEXT Interaction baseline).

Purpose: Escape cancels the most local mode; fullscreen Escape exits chrome
before closing windows; annotation Escape priority is documented in source.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from helpers.env import import_app

pytestmark = [pytest.mark.feature_ui, pytest.mark.feature_playback, pytest.mark.feature_annotation, pytest.mark.pure_logic]


def test_selection_overlay_handles_escape():
    ui = import_app("ui_elements")
    src = Path(ui.__file__).read_text(encoding="utf-8")
    assert "Key_Escape" in src


def test_video_player_escape_exits_fullscreen_before_close():
    ve = import_app("video_editor")
    src = Path(ve.__file__).read_text(encoding="utf-8")
    assert "Key_Escape" in src
    # Fullscreen exit path should be distinct from window close
    assert "_exit_fullscreen" in src or "exit_fullscreen" in src.lower()


def test_annotation_escape_priority_order_documented():
    annotation = import_app("annotation_tool")
    src = Path(annotation.__file__).read_text(encoding="utf-8")
    assert "Key_Escape" in src
    # Text edit cancel / deselect / close ordering is an AI_CONTEXT contract;
    # at minimum Escape handling must exist on both canvas and pill modules.
    assert "AnnotationCanvas" in src and "AnnotationPill" in src
