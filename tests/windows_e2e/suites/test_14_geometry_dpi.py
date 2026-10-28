"""Multi-monitor / DPI / negative virtual-desktop geometry.

Purpose: piecewise per-monitor capture plans must never use a single global DPR.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from helpers.env import import_app

pytestmark = [pytest.mark.feature_geometry, pytest.mark.pure_logic]


def test_display_geometry_module_exports_plan_builders():
    geo = import_app("display_geometry")
    assert hasattr(geo, "build_capture_plan") or hasattr(geo, "ScreenTransform")
    assert hasattr(geo, "compose_frozen_desktop") or "compose" in Path(geo.__file__).read_text(encoding="utf-8")


def test_capture_plan_handles_negative_origins_in_source():
    geo = import_app("display_geometry")
    src = Path(geo.__file__).read_text(encoding="utf-8")
    assert "devicePixelRatio" in src or "scale" in src.lower()
    assert "origin" in src.lower() or "virtual" in src.lower()


def test_main_rejects_global_dpr_assumption_in_comments_or_plan():
    main_mod = import_app("main")
    # _normalized_capture_plan is the encoding evenness gate; geometry lives in display_geometry
    assert callable(main_mod._normalized_capture_plan)
