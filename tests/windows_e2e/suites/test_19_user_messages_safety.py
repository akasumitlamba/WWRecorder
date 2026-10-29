"""Friendly error rewriting and path-safety messaging."""

from __future__ import annotations

import errno

import pytest

from helpers.env import import_app

pytestmark = [pytest.mark.feature_files, pytest.mark.pure_logic]


@pytest.fixture(scope="module")
def messages():
    return import_app("user_messages")


def test_friendly_error_maps_disk_full(messages):
    err = OSError(errno.ENOSPC, "No space left on device")
    text = messages.friendly_error(err)
    assert "full" in text.lower() or "space" in text.lower()


def test_friendly_error_preserves_ffmpeg_reason(messages):
    reason = 'ffmpeg exit code 1: Stream Audio; No such filter: bad_filter'
    assert messages.friendly_error(RuntimeError(reason)) == reason


def test_friendly_error_maps_permission(messages):
    text = messages.friendly_error(PermissionError(13, "denied"))
    assert "close" in text.lower() or "using" in text.lower() or "Windows" in text


def test_friendly_error_passthrough_unknown(messages):
    text = messages.friendly_error(RuntimeError("unique-xyz-failure"))
    assert "unique-xyz-failure" in text
