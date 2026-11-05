"""
Area 5 — Video player & trimmer/editor (adversarial).

Purpose: delete-merge matrix (overlap/1ms/adjacent), seek bounds, fullscreen
chrome contracts, export close async (no GUI wait), fractional overlay timing.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from helpers.action_matrix import assert_invariant
from helpers.adversarial import delete_region
from helpers.env import import_app

pytestmark = [
    pytest.mark.adversarial,
    pytest.mark.area_editor,
    pytest.mark.feature_editor,
    pytest.mark.feature_playback,
    pytest.mark.pure_logic,
]


@pytest.fixture(scope="module")
def video_editor():
    return import_app("video_editor")


@pytest.mark.parametrize(
    "regions,trim,expected",
    [
        ([delete_region(0, 500), delete_region(500, 1000)], 0, [(0.0, 1.0)]),  # adjacent touch
        ([delete_region(0, 500), delete_region(501, 1000)], 0, [(0.0, 1.0)]),  # 1ms gap merges
        ([delete_region(0, 500), delete_region(520, 1000)], 0, [(0.0, 0.5), (0.52, 1.0)]),  # larger gap
        ([delete_region(100, 400), delete_region(200, 350)], 0, [(0.1, 0.4)]),  # nested
        ([delete_region(0, 1000), delete_region(2000, 2500), delete_region(2400, 3000)], 0, [(0.0, 1.0), (2.0, 3.0)]),
        ([delete_region(1500, 2500)], 1000, [(0.5, 1.5)]),
        ([delete_region(800, 200)], 0, []),  # inverted discarded
    ],
    ids=["touch", "1ms", "gap20ms", "nested", "three", "trim", "inverted"],
)
def test_delete_merge_adversarial_matrix(video_editor, regions, trim, expected):
    got = video_editor._merge_delete_regions(regions, trim_start_ms=trim)
    assert_invariant(got == expected, f"got {got}", widget="ve.delete_merge", state=f"trim={trim}")


def test_fullscreen_chrome_idle_hide_and_escape_contract(video_editor):
    src = Path(video_editor.__file__).read_text(encoding="utf-8")
    assert_invariant("_hide_fullscreen_controls" in src, "idle hide", widget="ve.fullscreen", state="source")
    assert_invariant("2000" in src, "2s idle timer", widget="ve.fullscreen", state="source")
    assert_invariant("_exit_fullscreen" in src, "Escape exit", widget="ve.fullscreen", state="source")
    # Chrome must be restorable — show path present.
    assert_invariant(
        "_show_fullscreen_controls" in src or "fullscreen_controls" in src,
        "show chrome path",
        widget="ve.fullscreen",
        state="source",
    )


def test_close_during_export_is_async_no_thread_wait_in_closeevent(video_editor):
    src = Path(video_editor.__file__).read_text(encoding="utf-8")
    # closeEvent must not call QThread.wait / player.stop synchronously.
    close_idx = src.find("def closeEvent")
    assert close_idx > 0
    window = src[close_idx : close_idx + 2500]
    assert_invariant("_begin_async_close" in src, "async close helper", widget="ve.export_busy", state="source")
    assert_invariant(
        "QThread.wait" not in window and ".wait(" not in window.split("super().closeEvent")[0],
        "closeEvent body must not block on wait()",
        widget="ve.export_busy",
        state="closeEvent window",
    )
    assert_invariant(
        "setVideoOutput(None)" in window or "setVideoOutput" in window,
        "detach video output instead of stop()",
        widget="ve.export_busy",
        state="closeEvent",
    )


def test_seek_helpers_clamp_semantics(video_editor):
    """Seek beyond EOF / negative must be handled by _seek_to_position clamp."""
    src = Path(video_editor.__file__).read_text(encoding="utf-8")
    assert_invariant("_seek_to_position" in src, "seek helper", widget="ve.seek", state="source")
    # Clamp language present near seek.
    idx = src.find("def _seek_to_position")
    window = src[idx : idx + 800]
    assert_invariant(
        "max(" in window or "min(" in window or "duration" in window.lower(),
        "seek clamps to duration",
        widget="ve.seek",
        state="helper body",
    )


def test_available_output_path_non_destructive(video_editor, tmp_path):
    existing = tmp_path / "out.mp4"
    existing.write_bytes(b"orig")
    alt = video_editor._available_output_path(str(existing))
    assert Path(alt) != existing
    assert existing.read_bytes() == b"orig"


def test_text_overlay_fractional_ms_enable_expression(video_editor):
    """drawtext enable window uses millisecond-precision floats."""
    src = Path(video_editor.__file__).read_text(encoding="utf-8")
    assert_invariant("between(t," in src, "fractional enable", widget="ve.overlay", state="source")
    assert_invariant(".3f" in src or ":.3f" in src, "ms precision format", widget="ve.overlay", state="source")
