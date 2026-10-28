"""Settings schema defaults and validation (AI_CONTEXT / DEFAULT_CONFIG).

Purpose: freeze the shared EXE/MSIX settings contract and hotkey rules.
Pass means: DEFAULT_CONFIG keys/types match the documented baseline and
validate_hotkey accepts only modifier+key shapes used by pynput.
"""

from __future__ import annotations

import pytest

from helpers.env import import_app
from helpers.assertions import assert_keys_include, assert_eq, assert_true, assert_false

pytestmark = [pytest.mark.feature_settings, pytest.mark.pure_logic]

# Keys required by DISTRIBUTION parity + recent panel/dock work (AI_CONTEXT 2026-10).
REQUIRED_KEYS = [
    "output_folder",
    "hotkey",
    "hotkey_screenshot",
    "default_system_audio",
    "default_mic",
    "microphone_id",
    "microphone_name",
    "start_on_boot",
    "copy_to_clipboard",
    "sidebar_width",
    "panel_height",
    "close_on_focus_loss",
    "hide_panel_on_drag",
    "developer_mode",
    "ignored_update_version",
    "font_size",
    "dock_edge",
    "dock_y",
    "dock_x",
]


@pytest.fixture(scope="module")
def main_mod():
    return import_app("main")


def test_default_config_contains_required_keys(main_mod):
    assert_keys_include(main_mod.DEFAULT_CONFIG, REQUIRED_KEYS, because="DEFAULT_CONFIG schema drift")


def test_default_audio_toggles_are_off_until_user_enables(main_mod):
    # Documented: audio is opt-in per take / settings; empty mic id => Same as Windows.
    assert_false(main_mod.DEFAULT_CONFIG["default_system_audio"], because="default system audio should be False")
    assert_false(main_mod.DEFAULT_CONFIG["default_mic"], because="default mic should be False")
    assert_eq(main_mod.DEFAULT_CONFIG["microphone_id"], "", because="empty microphone_id means Same as Windows")
    assert "Windows" in main_mod.DEFAULT_CONFIG["microphone_name"]


def test_default_hide_panel_on_drag_is_false(main_mod):
    assert_false(
        main_mod.DEFAULT_CONFIG["hide_panel_on_drag"],
        because="AI_CONTEXT: hide_panel_on_drag defaults false",
    )


def test_default_dock_edge_is_right(main_mod):
    assert_eq(main_mod.DEFAULT_CONFIG["dock_edge"], "right", because="historical default edge")


def test_app_version_is_1_7_0(main_mod):
    assert_eq(main_mod.APP_VERSION, "1.7.0", because="active application version per AI_CONTEXT")


@pytest.mark.parametrize(
    "hotkey,ok",
    [
        ("<shift>+<backspace>", True),
        ("<shift>+<home>", True),
        ("<ctrl>+<alt>+r", True),
        ("", False),
        ("a", False),
        ("<ctrl>", False),
    ],
)
def test_validate_hotkey_rules(main_mod, hotkey, ok):
    valid, message = main_mod.validate_hotkey(hotkey)
    assert_eq(valid, ok, because=f"validate_hotkey({hotkey!r}) message={message!r}")


def test_safe_media_path_rejects_executables(main_mod, tmp_path):
    good = tmp_path / "clip.mkv"
    good.write_bytes(b"x")
    bad = tmp_path / "evil.exe"
    bad.write_bytes(b"x")
    assert_true(main_mod._is_safe_media_path(str(good)), because="mkv must be safe")
    assert_false(main_mod._is_safe_media_path(str(bad)), because="exe must be rejected (QA release notes)")
    assert_false(main_mod._is_safe_media_path(str(tmp_path / "missing.png")), because="missing file unsafe")


def test_available_media_path_never_overwrites(main_mod, tmp_path):
    from pathlib import Path

    target = tmp_path / "Recording_2026-01-01_12-00-00.mkv"
    target.write_bytes(b"1")
    alt = Path(main_mod._available_media_path(str(target)))
    assert alt != target
    assert not alt.exists()
    assert alt.name.startswith(target.stem)
