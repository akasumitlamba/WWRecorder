"""Video editor / playback / fullscreen chrome contracts.

Purpose: non-destructive Save As paths, delete-region merge, fullscreen idle
chrome timer (2s), edit-mode blocks fullscreen.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from helpers.env import import_app
from helpers.assertions import assert_eq, assert_doc_contract

pytestmark = [pytest.mark.feature_editor, pytest.mark.feature_playback]


@pytest.fixture(scope="module")
def video_editor():
    return import_app("video_editor")


@pytest.mark.pure_logic
def test_available_output_path_is_non_destructive(video_editor, tmp_path):
    path = tmp_path / "clip.mkv"
    path.write_bytes(b"x")
    alt = Path(video_editor._available_output_path(str(path)))
    assert alt != path
    assert not alt.exists()


@pytest.mark.pure_logic
def test_merge_delete_regions_merges_touching_and_overlapping(video_editor):
    R = lambda a, b: SimpleNamespace(start_ms=a, end_ms=b)
    assert_eq(
        video_editor._merge_delete_regions([R(2000, 4000), R(4000, 6000), R(5500, 7000)]),
        [(2.0, 7.0)],
        because="touching/overlapping cuts must merge before export",
    )
    assert_eq(
        video_editor._merge_delete_regions([R(1000, 2000), R(2001, 3000)]),
        [(1.0, 3.0)],
        because="1ms gap merges (integer ms timeline)",
    )
    assert_eq(
        video_editor._merge_delete_regions([R(1000, 2000), R(2002, 3000)]),
        [(1.0, 2.0), (2.002, 3.0)],
        because=">1ms gap stays separate",
    )


@pytest.mark.pure_logic
def test_fullscreen_idle_timer_is_two_seconds(video_editor):
    src = Path(video_editor.__file__).read_text(encoding="utf-8")
    assert "_fullscreen_controls_timer.setInterval(2000)" in src
    assert_doc_contract(
        "_hide_fullscreen_controls" in src and "_fullscreen_chrome_has_pointer" in src,
        contract="AI_CONTEXT: fullscreen chrome hides after 2 idle seconds unless pointer over chrome",
        evidence="timer + hide + pointer guard present",
    )


@pytest.mark.pure_logic
def test_edit_mode_blocks_fullscreen_with_explanation(video_editor):
    src = Path(video_editor.__file__).read_text(encoding="utf-8")
    assert "Exit Edit mode before entering fullscreen" in src


@pytest.mark.pure_logic
def test_seek_helper_exists_as_single_owner(video_editor):
    assert hasattr(video_editor.VideoPlayerWindow, "_seek_to_position")


@pytest.mark.windows_gui
def test_player_constructs_with_missing_file_without_crash(qapp, video_editor, tmp_path):
    # Constructor may require a path; use a non-decodable placeholder.
    path = tmp_path / "missing_or_fake.mkv"
    path.write_bytes(b"NOT_A_REAL_VIDEO")
    # Some builds open via factory; try common constructors.
    try:
        win = video_editor.VideoPlayerWindow(str(path))
    except TypeError:
        win = video_editor.VideoPlayerWindow()
        if hasattr(win, "load_file"):
            win.load_file(str(path))
    qapp.processEvents()
    win.close()
    qapp.processEvents()
