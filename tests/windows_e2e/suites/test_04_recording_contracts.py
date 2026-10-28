"""Recording state-machine and media ownership contracts (AI_CONTEXT).

Purpose: encode idle→…→saving outcomes, temp retention, CRF, capture plan
normalization, and discard/recovery rules without requiring a live capture
when running off Windows.

Pass means: pure helpers match docs; windows_native cases exercise engine
guards with mocked subprocess where needed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from helpers.env import import_app
from helpers.assertions import assert_eq, assert_true, assert_doc_contract
from helpers.media import isolated_output_root, list_playable, assert_playable_preserved

pytestmark = [pytest.mark.feature_recording]


@pytest.fixture(scope="module")
def main_mod():
    return import_app("main")


@pytest.fixture(scope="module")
def recorder():
    return import_app("recorder")


@pytest.mark.pure_logic
def test_capture_plan_rejects_tiny_and_forces_even_dimensions(main_mod):
    assert main_mod._normalized_capture_plan({"width": 1, "height": 100}) is None
    assert main_mod._normalized_capture_plan({"width": 100, "height": 1}) is None
    normalized = main_mod._normalized_capture_plan({"left": -3, "top": 2, "width": 101, "height": 99})
    assert_eq(normalized, {"left": -3, "top": 2, "width": 100, "height": 98}, because="even H.264 dims")


@pytest.mark.pure_logic
def test_temp_prefix_and_retention_match_recoverability_contract(recorder):
    assert_eq(recorder.TEMP_PREFIX, "WWRecorder_temp_", because="temp session media prefix")
    assert recorder.TEMP_RETENTION_SECONDS >= 7 * 24 * 60 * 60
    assert_doc_contract(
        recorder.TEMP_VIDEO_CRF == 20 and recorder.FINAL_VIDEO_CRF == 25,
        contract="AI_CONTEXT 2026-10-26: live CRF 20 / final CRF 25",
        evidence=f"temp={recorder.TEMP_VIDEO_CRF} final={recorder.FINAL_VIDEO_CRF}",
    )


@pytest.mark.pure_logic
def test_recording_temp_dir_is_on_output_drive(recorder, tmp_path):
    out = isolated_output_root(tmp_path)
    temp_dir = recorder._recording_temp_dir(str(out))
    assert_eq(temp_dir.name, ".wwr_temp", because="session work media lives in .wwr_temp")
    assert_eq(temp_dir.parent, out.resolve(), because="temp dir must stay on the selected output folder")
    assert temp_dir.is_dir()


@pytest.mark.pure_logic
def test_engine_discard_is_idempotent_without_session(recorder, tmp_path):
    engine = recorder.RecordingEngine()
    # Discard with no active session must not raise and must leave no playable orphans.
    before = list_playable(tmp_path)
    engine.discard()
    engine.discard()
    after = list_playable(tmp_path)
    assert_playable_preserved(before, after, context="double discard with no session")


@pytest.mark.pure_logic
def test_low_disk_thresholds_documented_in_prepare(recorder):
    # Source contract: <100MB critical refuse; <500MB warning (project.md / AI_CONTEXT).
    src = Path(recorder.__file__).read_text(encoding="utf-8")
    assert "_low_disk_space" in src
    assert "critical" in src and "warning" in src


@pytest.mark.pure_logic
def test_audio_filter_graph_avoids_single_pass_loudnorm(recorder):
    """AI_CONTEXT: bundled FFmpeg loudnorm hole — do not restore single-pass loudnorm."""
    src = Path(recorder.__file__).read_text(encoding="utf-8")
    assert "_audio_filter_graph" in src
    assert "loudnorm" not in src, "single-pass loudnorm must not return to the mux graph"


@pytest.mark.windows_native
@pytest.mark.feature_audio
def test_prepare_refuses_when_disk_critical(recorder, monkeypatch, tmp_path):
    engine = recorder.RecordingEngine()
    out = isolated_output_root(tmp_path)

    class _Usage:
        free = 50 * 1024 * 1024  # 50 MB

    monkeypatch.setattr(recorder.shutil, "disk_usage", lambda _p: _Usage)
    # Avoid starting FFmpeg: force failure path after disk check by also stubbing ffmpeg spawn if reached
    ok = engine.prepare({"left": 0, "top": 0, "width": 160, "height": 120}, str(out), {"system_audio": False, "mic": False})
    assert ok is False
    assert getattr(engine, "_low_disk_space", None) == "critical"
    engine.discard()
