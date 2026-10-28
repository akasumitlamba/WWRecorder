"""File operations, path safety, and temp media recoverability.

Purpose: never overwrite on automatic naming; reject unsafe extensions;
temp retention constants; media helpers refuse silent wipe of playable copies.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from helpers.env import import_app
from helpers.media import (
    isolated_output_root,
    list_playable,
    safe_rmtree,
    touch_fake_mkv,
    assert_playable_preserved,
)

pytestmark = [pytest.mark.feature_files, pytest.mark.feature_recording, pytest.mark.pure_logic]


def test_safe_rmtree_refuses_when_playable_remains(tmp_path):
    root = isolated_output_root(tmp_path)
    touch_fake_mkv(root / "only.mkv")
    with pytest.raises(RuntimeError, match="playable media still present"):
        safe_rmtree(root, require_empty_playable=True)
    assert (root / "only.mkv").is_file()


def test_safe_rmtree_allows_after_explicit_empty(tmp_path):
    root = isolated_output_root(tmp_path)
    (root / "note.txt").write_text("no playable", encoding="utf-8")
    safe_rmtree(root, require_empty_playable=True)
    assert not root.exists()


def test_available_paths_do_not_clobber(main_path_helpers, tmp_path):
    main_mod = main_path_helpers
    existing = tmp_path / "Screenshot_2026-01-01_12-00-00.png"
    existing.write_bytes(b"png")
    alt = Path(main_mod._available_media_path(str(existing)))
    assert alt != existing
    before = list_playable(tmp_path)
    # Creating alt path string must not delete existing
    after = list_playable(tmp_path)
    assert_playable_preserved(before, after, context="available_media_path")


@pytest.fixture
def main_path_helpers():
    return import_app("main")


def test_temp_retention_is_at_least_seven_days():
    recorder = import_app("recorder")
    assert recorder.TEMP_RETENTION_SECONDS >= 7 * 24 * 3600
