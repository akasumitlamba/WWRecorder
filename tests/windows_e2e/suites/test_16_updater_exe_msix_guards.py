"""Updater version compare and EXE-only feed access.

Purpose: prerelease handling, failure vs no-update separation, packaged guard.
"""

from __future__ import annotations

import pytest

from helpers.env import import_app

pytestmark = [pytest.mark.feature_distribution, pytest.mark.pure_logic]


@pytest.fixture(scope="module")
def updater():
    return import_app("updater")


@pytest.mark.parametrize(
    "current,latest,expect",
    [
        ("1.7.0", "1.7.1", True),
        ("1.7.0", "1.7.0", False),
        ("1.7.0", "1.6.9", False),
        ("1.7.0", "1.8.0-beta", False),  # prerelease label ignored as upgrade target
        ("1.7.0-rc1", "1.7.0", True),  # leaving prerelease for stable
    ],
)
def test_is_newer_semver_rules(updater, current, latest, expect):
    worker = updater.UpdateChecker(current)
    assert worker._is_newer(latest) is expect


def test_check_failed_signal_exists_separate_from_finished(updater):
    assert hasattr(updater.UpdateChecker, "check_failed")
    assert hasattr(updater.UpdateChecker, "check_finished")
