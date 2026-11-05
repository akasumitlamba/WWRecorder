"""Recording pill / capture border source contracts."""

from __future__ import annotations

from pathlib import Path

import pytest

from helpers.env import import_app

pytestmark = [pytest.mark.feature_recording, pytest.mark.feature_ui, pytest.mark.pure_logic]


def test_pill_has_discard_annotate_audio_and_keycast_controls():
    ui = import_app("ui_elements")
    src = Path(ui.__file__).read_text(encoding="utf-8")
    for token in ("Discard", "Annotate", "_btn_keycast", "set_preparing"):
        assert token in src, f"missing pill contract token {token}"


def test_capture_border_widget_exists():
    ui = import_app("ui_elements")
    assert hasattr(ui, "CaptureBorderWidget")


def test_pill_timer_badge_dimensions_documented():
    # AI_CONTEXT: fixed 38px badge / 68px timer field
    ui = import_app("ui_elements")
    src = Path(ui.__file__).read_text(encoding="utf-8")
    assert "38" in src and "68" in src
