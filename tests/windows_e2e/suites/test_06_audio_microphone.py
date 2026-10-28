"""Microphone / system-audio contracts (AI_CONTEXT 2026-10-24 review).

Purpose: pin Same-as-Windows empty id, stereo adaptation, and WASAPI repair.
Real device open is windows_native only.
"""

from __future__ import annotations

import numpy as np
import pytest

from helpers.env import import_app
from helpers.assertions import assert_eq

pytestmark = [pytest.mark.feature_audio]


@pytest.fixture(scope="module")
def mic():
    return import_app("microphone_capture")


@pytest.fixture(scope="module")
def wasapi():
    return import_app("wasapi_compat")


@pytest.mark.pure_logic
def test_default_config_empty_microphone_id_means_same_as_windows():
    main_mod = import_app("main")
    assert_eq(main_mod.DEFAULT_CONFIG["microphone_id"], "", because="empty id => Same as Windows")
    assert "Windows" in main_mod.DEFAULT_CONFIG["microphone_name"]


@pytest.mark.pure_logic
@pytest.mark.parametrize(
    "data,expected",
    [
        ([[0.25], [-0.5]], [[0.25, 0.25], [-0.5, -0.5]]),
        ([[0.25, 0], [-0.5, 0]], [[0.25, 0.25], [-0.5, -0.5]]),
        ([[0, 0.25], [0, -0.5]], [[0.25, 0.25], [-0.5, -0.5]]),
        ([[0.25, 0.5], [-0.5, -0.25]], [[0.25, 0.5], [-0.5, -0.25]]),
    ],
)
def test_microphone_stereo_adapts_mono_and_one_sided_voice(mic, data, expected):
    np.testing.assert_array_equal(mic.microphone_stereo(data), np.array(expected, dtype=np.float32))


@pytest.mark.pure_logic
def test_wasapi_compat_exposes_repair_entry_point(wasapi):
    assert callable(wasapi.repair_soundcard_propvariant)
    src = open(wasapi.__file__, encoding="utf-8").read()
    assert "24" in src  # native PROPVARIANT BLOB size from AI_CONTEXT


@pytest.mark.pure_logic
def test_recorder_imports_and_applies_wasapi_compat():
    recorder = import_app("recorder")
    src = open(recorder.__file__, encoding="utf-8").read()
    assert "wasapi_compat" in src
    assert "repair_soundcard_propvariant" in src


@pytest.mark.windows_native
def test_native_microphone_helper_is_importable_on_windows(mic):
    assert callable(mic.native_microphone_recorder)
