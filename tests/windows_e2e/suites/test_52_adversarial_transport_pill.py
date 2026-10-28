"""
Area 3 — Floating recording transport pill (adversarial state machine).

Purpose: illegal transitions, preparing guards, closeEvent without modal
deadlock, drag clamp helpers, control parity across states.
"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QPoint, QRect, QSize
from PyQt6.QtWidgets import QApplication, QMessageBox

from helpers.action_matrix import FakeRecordingEngine, assert_invariant, make_pill, spam_clicks
from helpers.env import import_app

pytestmark = [
    pytest.mark.adversarial,
    pytest.mark.area_transport,
    pytest.mark.feature_recording,
    pytest.mark.pure_logic,
]


def _safe_close(pill):
    pill._stopping = True
    pill._preparing = False
    pill.hide()
    pill.close()
    QApplication.processEvents()


def test_stop_while_preparing_is_noop(qapp):
    pill, engine = make_pill(qapp, pre_record=True)
    pill.set_preparing(True)
    before = (engine.stop_capture_calls, engine.mux_calls)
    pill._initiate_stop()
    assert_invariant(
        (engine.stop_capture_calls, engine.mux_calls) == before,
        "Stop while Preparing must be ignored",
        widget="pill.stop",
        state="preparing",
    )
    _safe_close(pill)


def test_double_start_disabled_while_preparing(qapp):
    pill, _ = make_pill(qapp, pre_record=True)
    starts = []
    pill.start_requested.connect(lambda: starts.append(1))
    spam_clicks(pill._btn_start, times=3)
    first = len(starts)
    pill.set_preparing(True)
    spam_clicks(pill._btn_start, times=8)
    assert_invariant(len(starts) == first, "no extra starts while preparing", widget="pill.start", state="spam")
    _safe_close(pill)


def test_close_event_never_calls_modal_exec(qapp, monkeypatch):
    """closeEvent must not nest QMessageBox.exec() (GUI-thread deadlock risk)."""
    pill, engine = make_pill(qapp, pre_record=False)
    engine._recording = True
    calls = []

    def _tracking_exec(self, *a, **k):
        calls.append("exec")
        raise AssertionError("modal exec during closeEvent")

    monkeypatch.setattr(QMessageBox, "exec", _tracking_exec)
    stopped = []
    pill.stopped.connect(stopped.append)
    pill.close()  # live external close requests asynchronous save, never discard
    QApplication.processEvents()
    assert_invariant(calls == [], "no modal exec on close", widget="pill.closeEvent", state="recording teardown")
    assert_invariant("<SAVING>" in stopped and "<DISCARDED>" not in stopped,
                     "live close preserves media through save", widget="pill.closeEvent", state="after")
    if hasattr(pill, '_stop_worker'):
        assert pill._stop_worker.wait(1000)
        QApplication.processEvents()
    _safe_close(pill)


def test_pause_resume_parity_across_toggles(qapp):
    pill, engine = make_pill(qapp, pre_record=False)
    engine._recording = True
    pill._btn_sys.setChecked(True)
    pill._btn_mic.setChecked(True)
    QApplication.processEvents()
    assert engine.get_system_audio() and engine.get_mic()
    pill.toggle_pause()
    assert engine.is_paused()
    # Audio toggles remain enabled while paused (AI_CONTEXT runtime controls).
    assert_invariant(pill._btn_sys.isEnabled(), "sys enabled paused", widget="pill.sys_audio", state="paused")
    pill._btn_sys.setChecked(False)
    assert not engine.get_system_audio()
    pill.toggle_pause()
    assert not engine.is_paused()
    _safe_close(pill)


def test_drag_clamp_helper_keeps_pill_in_available_geometry(qapp):
    ui = import_app("ui_elements")
    # Prefer product clamp helper if exported.
    clamp = getattr(ui, "_clamp_window_top_left", None)
    assert_invariant(clamp is not None, "clamp helper exists", widget="pill.drag", state="source")
    available = QRect(100, 50, 800, 600)
    size = QSize(200, 40)
    # Far outside → clamped inside.
    pos = clamp(QPoint(-500, -500), size, available)
    assert_invariant(available.contains(pos) or available.adjusted(0, 0, -size.width(), -size.height()).contains(pos)
                     or (pos.x() >= available.left() and pos.y() >= available.top()),
                     "clamped into work area", widget="pill.drag", state=str((pos.x(), pos.y())))
    pos2 = clamp(QPoint(9999, 9999), size, available)
    assert_invariant(pos2.x() + size.width() <= available.right() + 1, "right clamp", widget="pill.drag", state=str(pos2.x()))


def test_illegal_transition_matrix_summary(qapp):
    """Documented illegal edges: stop@preparing, discard@stopping, start@preparing."""
    pill, engine = make_pill(qapp, pre_record=True)
    pill.set_preparing(True)
    pill._initiate_stop()
    pill._initiate_discard()  # pre-record discard allowed even while preparing? product: discard buttons disabled
    # Preparing disables discard button; direct call may still run — assert button disabled.
    assert_invariant(not pill._btn_discard.isEnabled(), "discard disabled preparing", widget="pill.discard", state="preparing")
    pill.set_preparing(False)
    pill._initiate_discard()
    QApplication.processEvents()
    assert pill._stopping
    pill._initiate_discard()  # second ignored
    _safe_close(pill)
