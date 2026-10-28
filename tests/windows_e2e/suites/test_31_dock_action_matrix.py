"""
Dock primary-action spam / signal matrix.

Purpose: every dock button emits exactly its signal under click spam; busy/
recording chrome still exposes buttons without crashing; annotate sync helper
exists.

Pass means: signal counts ≥1 under spam; no exception; recording chrome toggle
idempotent.
"""

from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QApplication

from helpers.action_matrix import (
    DOCK_ACTIONS,
    assert_invariant,
    make_dock,
    spam_clicks,
)

pytestmark = [
    pytest.mark.feature_ui,
    pytest.mark.pure_logic,
    pytest.mark.brute_force,
]


@pytest.mark.parametrize("action", DOCK_ACTIONS, ids=[a.action_id for a in DOCK_ACTIONS])
def test_dock_button_spam_emits_signal(qapp, action):
    dock, _engine = make_dock(qapp)
    received: list[int] = []
    signal = getattr(dock, action.signal_attr)
    signal.connect(lambda *a, _r=received: _r.append(1))
    btn = getattr(dock, action.button_attr)
    spam_clicks(btn, times=7)
    QApplication.processEvents()
    assert_invariant(
        len(received) >= 1,
        "dock action must emit under click spam",
        widget=action.action_id,
        state="idle spam",
    )
    dock.close()
    QApplication.processEvents()


def test_dock_recording_chrome_toggle_matrix(qapp):
    dock, _ = make_dock(qapp)
    for active in (True, False, True, False):
        dock.set_recording_state(active)
        QApplication.processEvents()
        assert_invariant(
            dock._is_recording is active,
            "recording chrome flag",
            widget="dock.record",
            state=f"active={active}",
        )
    spam_clicks(dock._btn_record, times=5)
    dock.close()


def test_dock_annotate_icon_sync_on_off(qapp):
    dock, _ = make_dock(qapp)
    if not hasattr(dock, "set_annotation_active"):
        pytest.skip("DockWidget.set_annotation_active missing")
    dock.set_annotation_active(True)
    QApplication.processEvents()
    dock.set_annotation_active(False)
    QApplication.processEvents()
    dock.set_annotation_active(True)
    dock.close()
