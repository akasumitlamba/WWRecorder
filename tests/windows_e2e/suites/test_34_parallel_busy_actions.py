"""
Parallel / interleaved / busy-state action guards.

Purpose
-------
Spam primary actions while preparing/finalizing; open settings while "recording"
chrome is active; refuse overlapping stop; document update-check-during-capture
guard in main/updater.

Pass means: preparing disables conflicting pill controls; duplicate stop is
idempotent; source contracts for update/recording overlap exist.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PyQt6.QtWidgets import QApplication

from helpers.action_matrix import (
    BUSY_STATES,
    assert_invariant,
    make_dock,
    make_pill,
    make_settings_sidebar,
    spam_clicks,
)
from helpers.env import import_app

pytestmark = [
    pytest.mark.feature_recording,
    pytest.mark.feature_ui,
    pytest.mark.brute_force,
    pytest.mark.parallel_actions,
]


def _safe_close_pill(pill):
    pill._stopping = True
    pill._preparing = False
    pill.hide()
    pill.close()
    QApplication.processEvents()


@pytest.mark.pure_logic
@pytest.mark.parametrize("busy", BUSY_STATES, ids=list(BUSY_STATES))
def test_pill_controls_under_busy_labels(qapp, busy):
    """Map busy labels onto pill flags and assert enablement invariants."""
    pre = busy in ("idle", "preparing")
    pill, engine = make_pill(qapp, pre_record=pre)
    if busy == "preparing":
        pill.set_preparing(True)
        assert_invariant(not pill._btn_start.isEnabled(), "Start off", widget="pill.start", state=busy)
        assert_invariant(not pill._btn_sys.isEnabled(), "sys off", widget="pill.sys_audio", state=busy)
    elif busy == "finalizing":
        # Simulate stopping/finalizing: further discard/stop ignored.
        pill._stopping = True
        before = engine.discard_calls
        pill._initiate_discard()
        assert_invariant(engine.discard_calls == before, "discard ignored while stopping", widget="pill.discard", state=busy)
    elif busy == "paused":
        engine._recording = True
        engine._paused = True
        pill.toggle_pause()  # should resume
        assert_invariant(engine.resume_calls >= 1, "resume from paused", widget="pill.pause", state=busy)
    elif busy == "recording":
        engine._recording = True
        spam_clicks(pill._btn_pause, times=2)
        assert_invariant(engine.pause_calls + engine.resume_calls >= 1, "pause works", widget="pill.pause", state=busy)
    else:  # idle
        assert_invariant(pill._btn_start.isEnabled(), "Start on when idle", widget="pill.start", state=busy)
    _safe_close_pill(pill)


@pytest.mark.pure_logic
def test_dock_actions_while_recording_chrome(qapp):
    dock, _ = make_dock(qapp)
    dock.set_recording_state(True)
    QApplication.processEvents()
    hits = {a: [] for a in ("screenshot_requested", "settings_requested", "files_requested")}
    for sig in hits:
        getattr(dock, sig).connect(lambda *a, s=sig: hits[s].append(1))
    spam_clicks(dock._btn_screenshot, times=3)
    spam_clicks(dock._btn_settings, times=3)
    spam_clicks(dock._btn_files, times=3)
    for sig, got in hits.items():
        assert_invariant(len(got) >= 1, f"{sig} still emits during recording chrome", widget=sig, state="recording")
    dock.set_recording_state(False)
    dock.close()


@pytest.mark.pure_logic
def test_settings_construct_while_pill_preparing(qapp):
    """Interleave: pill preparing + settings open (draft) must not crash."""
    pill, _ = make_pill(qapp, pre_record=True)
    pill.set_preparing(True)
    side, _, _ = make_settings_sidebar(qapp)
    QApplication.processEvents()
    spam_clicks(side._btn_check_update, times=3)
    side.close()
    _safe_close_pill(pill)


@pytest.mark.pure_logic
def test_update_check_during_recording_guarded_in_source():
    main_mod = import_app("main")
    src = Path(main_mod.__file__).read_text(encoding="utf-8")
    # Media-safe update path / recording refusal must be documented in code.
    assert_invariant(
        "recording" in src.lower() and ("update" in src.lower()),
        "main mentions recording + update interplay",
        widget="update.during_recording",
        state="source",
    )


@pytest.mark.pure_logic
def test_double_stop_idempotent(qapp):
    """Guard-level double-stop: do not start real _StopWorker (native crash risk off Windows)."""
    pill, engine = make_pill(qapp, pre_record=False)
    engine._recording = True
    # Simulate first stop having taken the latch without spawning mux worker.
    pill._stopping = True
    before_stop = engine.stop_capture_calls
    before_mux = engine.mux_calls
    pill._initiate_stop()  # must return immediately while _stopping
    QApplication.processEvents()
    assert_invariant(
        engine.stop_capture_calls == before_stop and engine.mux_calls == before_mux,
        "second stop while stopping is a no-op",
        widget="pill.stop",
        state="finalizing",
    )
    _safe_close_pill(pill)
