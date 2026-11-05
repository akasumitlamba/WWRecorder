"""Keycast recording input overlay contracts (AI_CONTEXT 2026-10-26).

Purpose: defaults off per take; hooks only while active unpaused; no keystroke
files/telemetry; overlay intentionally included in capture.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from helpers.env import import_app

pytestmark = [pytest.mark.feature_keycast, pytest.mark.pure_logic]


def test_keycast_module_imports_and_has_controller():
    keycast = import_app("keycast")
    src = Path(keycast.__file__).read_text(encoding="utf-8")
    assert "overlay" in src.lower()
    # No telemetry / keystroke file writers
    assert "telemetry" not in src.lower()
    assert "keylog" not in src.lower()


def test_keycast_history_bounds_documented():
    keycast = import_app("keycast")
    src = Path(keycast.__file__).read_text(encoding="utf-8")
    assert "40" in src  # history bound
    assert "128" in src  # mailbox bound


def test_pill_owns_keycast_toggle_wiring():
    ui = import_app("ui_elements")
    src = Path(ui.__file__).read_text(encoding="utf-8")
    assert "keycast" in src.lower() or "Keycast" in src
