"""Global hotkey ownership and validation.

Purpose: pynput owns the listener thread (not nested QThread); validation
requires modifier+key; defaults match product.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from helpers.env import import_app
from helpers.assertions import assert_eq, assert_true

pytestmark = [pytest.mark.feature_hotkeys, pytest.mark.pure_logic]


@pytest.fixture(scope="module")
def main_mod():
    return import_app("main")


def test_defaults_match_documented_shortcuts(main_mod):
    assert_eq(main_mod.DEFAULT_CONFIG["hotkey"], "<shift>+<backspace>", because="record hotkey default")
    assert_eq(main_mod.DEFAULT_CONFIG["hotkey_screenshot"], "<shift>+<home>", because="screenshot hotkey default")


def test_hotkey_listener_is_qobject_not_qthread_subclass(main_mod):
    from PyQt6.QtCore import QObject, QThread

    assert issubclass(main_mod.HotkeyListener, QObject)
    assert not issubclass(main_mod.HotkeyListener, QThread)
    src = Path(main_mod.__file__).read_text(encoding="utf-8")
    assert "pynput owns the native listener thread" in src or "pynput" in src.lower()


def test_validate_rejects_modifier_only(main_mod):
    ok, msg = main_mod.validate_hotkey("<ctrl>")
    assert ok is False
    assert msg


def test_validate_accepts_shift_backspace(main_mod):
    ok, msg = main_mod.validate_hotkey("<shift>+<backspace>")
    assert_true(ok, because=msg)
