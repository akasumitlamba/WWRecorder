"""Icon theme routing and tool cursor contrast contracts."""

from __future__ import annotations

from pathlib import Path

import pytest

from helpers.env import import_app, APP_DIR

pytestmark = [pytest.mark.feature_icons, pytest.mark.pure_logic]


def test_icon_theme_module_imports():
    theme = import_app("icon_theme")
    assert theme is not None
    src = Path(theme.__file__).read_text(encoding="utf-8")
    assert "modern" in src.lower() or "alias" in src.lower()


def test_tool_cursors_module_imports():
    cursors = import_app("tool_cursors")
    assert cursors is not None


def test_modern_icon_directory_exists():
    modern = APP_DIR / "icons" / "modern"
    assert modern.is_dir()
    pngs = list(modern.glob("*.png"))
    assert len(pngs) >= 10, f"expected modern icon family, found {len(pngs)}"


def test_canonical_icon_ico_exists():
    assert (APP_DIR / "icon.ico").is_file()
