"""capture_frames.py composition helpers (AI_CONTEXT 2026-10-26)."""

from __future__ import annotations

from pathlib import Path

import pytest

from helpers.env import import_app

pytestmark = [pytest.mark.feature_recording, pytest.mark.feature_geometry, pytest.mark.pure_logic]


def test_capture_frames_module_imports():
    mod = import_app("capture_frames")
    src = Path(mod.__file__).read_text(encoding="utf-8")
    assert "mss" in src.lower() or "BGRA" in src or "bgra" in src.lower()
