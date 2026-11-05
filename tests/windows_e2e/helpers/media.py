"""Isolated temporary media helpers.

Purpose
-------
Recording/screenshot/editor tests must never touch the user's real Videos
folder or silently delete the only playable copy of a capture.

Contract (mirrors product rules in docs/AI_CONTEXT.md)
------------------------------------------------------
Every recording path ends in exactly one of: saved, explicitly discarded, or
recoverable temporary media. Helpers keep temp trees under pytest's ``tmp_path``
and refuse destructive cleanup when a sole playable artifact would be lost.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Iterable, Optional


PLAYABLE_SUFFIXES = {".mkv", ".mp4", ".wav", ".png", ".jpg", ".jpeg", ".webp"}


def isolated_output_root(tmp_path: Path, name: str = "wwr_e2e_out") -> Path:
    """Create a fresh output folder under pytest tmp (never the real Videos path)."""
    root = Path(tmp_path) / name
    root.mkdir(parents=True, exist_ok=True)
    return root


def list_playable(root: Path) -> list[Path]:
    root = Path(root)
    if not root.exists():
        return []
    return sorted(
        p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in PLAYABLE_SUFFIXES
    )


def assert_playable_preserved(before: Iterable[Path], after: Iterable[Path], *, context: str) -> None:
    """Fail if any previously playable path vanished without an explicit replacement set."""
    before_set = {Path(p).resolve() for p in before}
    after_set = {Path(p).resolve() for p in after}
    missing = sorted(before_set - after_set)
    if missing:
        raise AssertionError(
            f"{context}: playable media disappeared without an explicit test discard/save: {missing}"
        )


def safe_rmtree(path: Path, *, require_empty_playable: bool = True) -> None:
    """Delete a temp tree only when it contains no orphaned sole playable files policy allows.

    When ``require_empty_playable`` is True, refuse to delete if playable files remain —
    callers must first assert saved/discarded outcomes. This prevents harness bugs from
    wiping the only copy of a failed-mux temp recording.
    """
    path = Path(path)
    if not path.exists():
        return
    remaining = list_playable(path)
    if require_empty_playable and remaining:
        raise RuntimeError(
            f"Refusing to delete {path}: playable media still present {remaining}. "
            "Mark the outcome (saved/discarded) in the test before cleanup."
        )
    shutil.rmtree(path, ignore_errors=False)


def write_tiny_png(path: Path, color=(32, 64, 128, 255)) -> Path:
    """Write a 16x16 PNG for annotation/gallery tests without capturing the desktop."""
    from PyQt6.QtGui import QImage, QColor

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    image = QImage(16, 16, QImage.Format.Format_ARGB32)
    image.fill(QColor(*color))
    if not image.save(str(path), "PNG"):
        raise RuntimeError(f"Failed to write fixture PNG: {path}")
    return path


def touch_fake_mkv(path: Path, payload: bytes = b"FAKE_MKV_FOR_PATH_TESTS_ONLY") -> Path:
    """Create a non-decodable placeholder MKV for path/collision tests (not playback)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path
