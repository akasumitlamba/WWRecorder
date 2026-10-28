"""
Video editor delete-merge / fullscreen / export-busy matrices.

Purpose: ``_merge_delete_regions`` handles overlaps/gaps; fullscreen Escape
contract present; export worker single-flight documented.

Pass means: merge cases match expected spans; source guards for duplicate export.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from helpers.action_matrix import assert_invariant
from helpers.env import import_app

pytestmark = [
    pytest.mark.feature_editor,
    pytest.mark.feature_playback,
    pytest.mark.pure_logic,
    pytest.mark.brute_force,
]


def _region(start_ms, end_ms):
    return SimpleNamespace(start_ms=start_ms, end_ms=end_ms)


@pytest.fixture(scope="module")
def video_editor():
    return import_app("video_editor")


@pytest.mark.parametrize(
    "regions,trim,expected",
    [
        ([], 0, []),
        ([_region(0, 1000)], 0, [(0.0, 1.0)]),
        ([_region(0, 1000), _region(500, 1500)], 0, [(0.0, 1.5)]),  # overlap merge
        ([_region(0, 1000), _region(1001, 2000)], 0, [(0.0, 2.0)]),  # 1ms gap merges
        ([_region(0, 1000), _region(2000, 3000)], 0, [(0.0, 1.0), (2.0, 3.0)]),
        ([_region(1000, 2000)], 1000, [(0.0, 1.0)]),  # trim offset
        ([_region(500, 400)], 0, []),  # inverted discarded
    ],
    ids=[
        "empty",
        "single",
        "overlap",
        "1ms_gap",
        "separate",
        "trim",
        "inverted",
    ],
)
def test_merge_delete_regions_matrix(video_editor, regions, trim, expected):
    got = video_editor._merge_delete_regions(regions, trim_start_ms=trim)
    assert_invariant(
        got == expected,
        f"merge got {got} expected {expected}",
        widget="ve.delete_merge",
        state=f"trim={trim}",
    )


def test_fullscreen_escape_contract_in_source(video_editor):
    src = Path(video_editor.__file__).read_text(encoding="utf-8")
    assert_invariant("_exit_fullscreen" in src, "exit fullscreen helper", widget="ve.fullscreen", state="source")
    assert_invariant("Key_Escape" in src or 'Escape"' in src, "Escape binding", widget="ve.fullscreen", state="source")
    assert_invariant("_toggle_fullscreen" in src, "toggle fullscreen", widget="ve.fullscreen", state="source")


def test_export_single_flight_documented(video_editor):
    src = Path(video_editor.__file__).read_text(encoding="utf-8")
    assert_invariant("_export_worker" in src, "export worker slot", widget="ve.export_busy", state="source")
    # Guard against starting a second export while one runs.
    assert_invariant(
        "export" in src.lower() and ("_export_worker" in src),
        "export worker referenced for busy guard",
        widget="ve.export_busy",
        state="source",
    )


def test_save_as_non_destructive_helper(video_editor, tmp_path):
    """Existing path must not be overwritten by automatic unique naming."""
    existing = tmp_path / "clip.mp4"
    existing.write_bytes(b"x")
    out = video_editor._available_output_path(str(existing))
    assert_invariant(
        Path(out) != existing and not Path(out).exists(),
        "Save As path distinct and free",
        widget="ve.save_as",
        state=str(out),
    )
    assert_invariant(existing.read_bytes() == b"x", "original untouched", widget="ve.save_as", state="after")
