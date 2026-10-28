"""
Selection / capture-plan boundary matrix (tiny, odd, negative virtual-desktop).

Purpose: brute-force region dicts through ``_normalized_capture_plan``.
Pass means: cases in CAPTURE_PLAN_CASES accept/reject as expected; negative
origins survive when large enough; odd dims evened.
"""

from __future__ import annotations

import pytest

from helpers.action_matrix import CAPTURE_PLAN_CASES, assert_invariant
from helpers.env import import_app

pytestmark = [
    pytest.mark.feature_geometry,
    pytest.mark.feature_recording,
    pytest.mark.feature_screenshot,
    pytest.mark.pure_logic,
    pytest.mark.brute_force,
]


@pytest.fixture(scope="module")
def main_mod():
    return import_app("main")


@pytest.mark.parametrize("region,expect_ok", CAPTURE_PLAN_CASES, ids=[
    f"w{c[0]['width']}h{c[0]['height']}_l{c[0]['left']}_ok{c[1]}" for c in CAPTURE_PLAN_CASES
])
def test_capture_plan_case(main_mod, region, expect_ok):
    plan = main_mod._normalized_capture_plan(dict(region))
    if expect_ok:
        assert_invariant(plan is not None, "plan accepted", widget="selection.region", state=str(region))
        assert_invariant(plan["width"] % 2 == 0 and plan["height"] % 2 == 0, "even dims", widget="selection.region", state=str(plan))
        assert_invariant(plan["width"] >= 32 and plan["height"] >= 32, "min 32", widget="selection.region", state=str(plan))
        assert_invariant(plan["left"] == region["left"] and plan["top"] == region["top"], "origin preserved", widget="selection.negative", state=str(plan))
    else:
        assert_invariant(plan is None, "plan rejected", widget="selection.tiny", state=str(region))


@pytest.mark.parametrize("w,h", [(0, 0), (-10, 100), (100, -10), (2, 2), (30, 100), (100, 30)])
def test_more_rejected_boundaries(main_mod, w, h):
    plan = main_mod._normalized_capture_plan({"left": 0, "top": 0, "width": w, "height": h})
    assert_invariant(plan is None, "invalid size rejected", widget="selection.tiny", state=f"{w}x{h}")


@pytest.mark.parametrize("left,top", [(-1920, 0), (0, -1080), (-500, -500), (10_000, -200)])
def test_negative_and_far_origins_when_large_enough(main_mod, left, top):
    plan = main_mod._normalized_capture_plan({"left": left, "top": top, "width": 200, "height": 120})
    assert_invariant(plan is not None, "large region with exotic origin ok", widget="selection.negative", state=f"{left},{top}")
    assert plan["left"] == left and plan["top"] == top
