"""
Recording pill toggle / transport / preparing-guard matrix.

Purpose
-------
Brute-force pill audio/keycast/annotate toggles (on→off→on), Start spam while
preparing, pause/resume spam, and discard/stop guards.

Pass means
----------
Engine setters mirror button state; preparing disables Start/toggles; stop while
preparing is a no-op; discard from pre-record does not require confirm dialog.
"""

from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QApplication

from helpers.action_matrix import (
    PILL_TOGGLE_ATTRS,
    assert_invariant,
    make_pill,
    spam_clicks,
)

pytestmark = [
    pytest.mark.feature_recording,
    pytest.mark.feature_ui,
    pytest.mark.pure_logic,
    pytest.mark.brute_force,
]


def _safe_close_pill(pill):
    """Avoid discard confirmation dialogs on teardown."""
    pill._stopping = True
    pill._preparing = False
    pill.hide()
    pill.close()
    QApplication.processEvents()


@pytest.mark.parametrize("action_id,attr", PILL_TOGGLE_ATTRS, ids=[a[0] for a in PILL_TOGGLE_ATTRS])
def test_pill_toggle_on_off_on(qapp, action_id, attr):
    pill, engine = make_pill(qapp, pre_record=True)
    btn = getattr(pill, attr)
    if not btn.isCheckable():
        _safe_close_pill(pill)
        pytest.skip(f"{action_id} not checkable")

    for target in (True, False, True):
        btn.setChecked(target)
        QApplication.processEvents()
        assert_invariant(
            btn.isChecked() is target,
            f"toggle → {target}",
            widget=action_id,
            state=f"pre_record target={target}",
        )
        if attr == "_btn_sys":
            assert_invariant(
                engine.get_system_audio() is target,
                "engine sys audio mirrors pill",
                widget=action_id,
                state=str(target),
            )
        if attr == "_btn_mic":
            assert_invariant(
                engine.get_mic() is target,
                "engine mic mirrors pill",
                widget=action_id,
                state=str(target),
            )
    _safe_close_pill(pill)


def test_pill_start_spam_while_preparing_disabled(qapp):
    pill, _ = make_pill(qapp, pre_record=True)
    starts = []
    pill.start_requested.connect(lambda: starts.append(1))
    pill.set_preparing(True)
    QApplication.processEvents()
    assert_invariant(not pill._btn_start.isEnabled(), "Start disabled while preparing", widget="pill.start", state="preparing")
    spam_clicks(pill._btn_start, times=8)
    assert_invariant(
        len(starts) == 0,
        "disabled Start must not emit under spam",
        widget="pill.start",
        state="preparing spam",
    )
    pill.set_preparing(False)
    spam_clicks(pill._btn_start, times=3)
    assert_invariant(len(starts) >= 1, "Start emits when idle", widget="pill.start", state="idle")
    _safe_close_pill(pill)


def test_pill_pause_resume_spam(qapp):
    pill, engine = make_pill(qapp, pre_record=False)
    engine._recording = True
    spam_clicks(pill._btn_pause, times=6)
    QApplication.processEvents()
    assert_invariant(
        engine.pause_calls + engine.resume_calls >= 1,
        "pause/resume invoked",
        widget="pill.pause",
        state="recording spam",
    )
    _safe_close_pill(pill)


def test_pill_stop_ignored_while_preparing(qapp):
    """Stop path is hidden in pre-record; set_preparing only applies there."""
    pill, engine = make_pill(qapp, pre_record=True)
    pill.set_preparing(True)
    before = engine.stop_capture_calls + engine.mux_calls
    # Even if stop were visible, _initiate_stop guards preparing.
    pill._initiate_stop()
    QApplication.processEvents()
    assert_invariant(
        engine.stop_capture_calls + engine.mux_calls == before,
        "stop while preparing is no-op",
        widget="pill.stop",
        state="preparing",
    )
    _safe_close_pill(pill)


def test_pill_discard_pre_record_no_confirm(qapp):
    pill, engine = make_pill(qapp, pre_record=True)
    stopped = []
    pill.stopped.connect(lambda msg: stopped.append(msg))
    pill._initiate_discard()
    QApplication.processEvents()
    assert_invariant(
        any(m == "<DISCARDED>" for m in stopped),
        "pre-record discard emits <DISCARDED>",
        widget="pill.discard",
        state="pre_record",
    )
    # Background thread may still be running discard — wait briefly via processEvents.
    for _ in range(20):
        QApplication.processEvents()
        if engine.discard_calls:
            break
    assert_invariant(engine.discard_calls >= 1, "engine.discard called", widget="pill.discard", state="after")
    _safe_close_pill(pill)


def test_pill_double_discard_guard(qapp):
    pill, engine = make_pill(qapp, pre_record=True)
    pill._initiate_discard()
    QApplication.processEvents()
    first = engine.discard_calls
    pill._initiate_discard()  # _stopping True → return
    QApplication.processEvents()
    assert_invariant(
        engine.discard_calls == first,
        "second discard while stopping is ignored",
        widget="pill.discard",
        state="stopping",
    )
    _safe_close_pill(pill)
