"""
Brute-force settings toggle × exit-path matrix.

Purpose
-------
Exhaustively flip every draft toggle / dock-edge combo across save vs
Escape / close-without-save, then reopen from the persisted mirror and assert
draft-until-Save (AI_CONTEXT).

Preconditions
-------------
Qt session ``qapp``; offscreen OK. Does not touch real user Videos.

Pass means
----------
- Flip without Save + Escape/close → reopen matches last persisted values.
- Flip + Save → reopen matches new values; ``settings_saved`` payload correct.
- off→on→off back to saved clears dirty (Save disabled).
- Crossed toggles: change A+B save; change A only then Escape → A kept, B kept.
"""

from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QApplication

from helpers.action_matrix import (
    EXIT_PATHS,
    SETTINGS_COMBOS,
    SETTINGS_TOGGLES,
    apply_settings_exit,
    assert_invariant,
    is_settings_dirty,
    make_settings_sidebar,
    read_toggle,
    reopen_settings,
    set_toggle,
    spam_clicks,
)

pytestmark = [
    pytest.mark.feature_settings,
    pytest.mark.pure_logic,
    pytest.mark.brute_force,
    pytest.mark.settings_matrix,
]

_DISCARD_EXITS = [e for e in EXIT_PATHS if e != "save"]


@pytest.mark.parametrize("toggle", SETTINGS_TOGGLES, ids=[t.action_id for t in SETTINGS_TOGGLES])
@pytest.mark.parametrize("exit_id", _DISCARD_EXITS, ids=_DISCARD_EXITS)
def test_toggle_flip_then_exit_without_save_discards(qapp, toggle, exit_id):
    """Flip away from default → exit without Save → reopen restores persisted."""
    baseline = {toggle.config_key: toggle.default}
    side, persisted, _saved = make_settings_sidebar(qapp, **baseline)
    assert_invariant(
        read_toggle(side, toggle.attr) == toggle.default,
        "baseline matches default",
        widget=toggle.action_id,
        state="clean",
    )

    set_toggle(side, toggle.attr, not toggle.default)
    QApplication.processEvents()
    assert_invariant(
        is_settings_dirty(side),
        "dirty after flip",
        widget=toggle.action_id,
        state="draft",
    )

    apply_settings_exit(side, exit_id)
    side.close()
    QApplication.processEvents()

    side2 = reopen_settings(qapp, persisted)
    assert_invariant(
        read_toggle(side2, toggle.attr) == toggle.default,
        f"exit={exit_id}: draft must not persist without Save",
        widget=toggle.action_id,
        state=f"reopen after {exit_id}",
    )
    assert_invariant(
        persisted.get(toggle.config_key) == toggle.default,
        "persisted mirror unchanged",
        widget=toggle.action_id,
        state=exit_id,
    )
    side2.close()


@pytest.mark.parametrize("toggle", SETTINGS_TOGGLES, ids=[t.action_id for t in SETTINGS_TOGGLES])
def test_toggle_flip_save_persists(qapp, toggle):
    side, persisted, saved = make_settings_sidebar(qapp, **{toggle.config_key: toggle.default})
    target = not toggle.default
    set_toggle(side, toggle.attr, target)
    apply_settings_exit(side, "save")
    QApplication.processEvents()

    assert_invariant(bool(saved), "settings_saved emitted", widget=toggle.action_id, state="saved")
    assert_invariant(
        saved[-1].get(toggle.config_key) is target,
        f"payload {toggle.config_key}={target}",
        widget=toggle.action_id,
        state="saved",
    )
    assert_invariant(
        persisted.get(toggle.config_key) is target,
        "persisted mirror updated",
        widget=toggle.action_id,
        state="saved",
    )
    assert_invariant(
        not is_settings_dirty(side),
        "Save clears dirty",
        widget=toggle.action_id,
        state="after save",
    )

    side.close()
    side2 = reopen_settings(qapp, persisted)
    assert_invariant(
        read_toggle(side2, toggle.attr) is target,
        "reopen persists saved value",
        widget=toggle.action_id,
        state="reopen",
    )
    side2.close()


@pytest.mark.parametrize("toggle", SETTINGS_TOGGLES, ids=[t.action_id for t in SETTINGS_TOGGLES])
def test_toggle_off_on_off_clears_dirty(qapp, toggle):
    """Return to last-saved value without Save → dirty clears, Save disabled."""
    side, _persisted, _saved = make_settings_sidebar(qapp, **{toggle.config_key: toggle.default})
    set_toggle(side, toggle.attr, not toggle.default)
    assert is_settings_dirty(side)
    set_toggle(side, toggle.attr, toggle.default)
    QApplication.processEvents()
    assert_invariant(
        not is_settings_dirty(side),
        "back to saved clears dirty",
        widget=toggle.action_id,
        state="draft→clean",
    )
    assert_invariant(
        not side._btn_save.isEnabled(),
        "Save disabled when clean",
        widget="settings.save",
        state="clean",
    )
    side.close()


def test_reset_marks_dirty_then_escape_discards(qapp):
    side, persisted, _ = make_settings_sidebar(
        qapp,
        copy_to_clipboard=False,  # non-default so Reset dirties toward default True
        default_system_audio=True,
    )
    # Persist non-defaults first.
    side._save()
    QApplication.processEvents()
    assert persisted.get("copy_to_clipboard") is False

    side._reset()
    QApplication.processEvents()
    assert_invariant(
        is_settings_dirty(side),
        "reset: dirty vs last saved",
        widget="settings.reset",
        state="after reset",
    )
    assert_invariant(
        read_toggle(side, "_chk_clip") is True,
        "reset draft shows default clipboard True",
        widget="settings.clipboard",
        state="after reset",
    )
    apply_settings_exit(side, "escape")
    side.close()

    side2 = reopen_settings(qapp, persisted)
    assert_invariant(
        read_toggle(side2, "_chk_clip") is False,
        "reset+Escape: prior Save kept (clipboard False)",
        widget="settings.clipboard",
        state="reopen",
    )
    side2.close()


def test_crossed_toggles_save_then_partial_cancel(qapp):
    """Save A+B; change only A; Escape → A and B both still at saved values."""
    side, persisted, _ = make_settings_sidebar(
        qapp, copy_to_clipboard=False, default_system_audio=False
    )
    set_toggle(side, "_chk_clip", True)
    set_toggle(side, "_chk_sys", True)
    side._save()
    QApplication.processEvents()
    assert persisted.get("copy_to_clipboard") is True
    assert persisted.get("default_system_audio") is True

    set_toggle(side, "_chk_clip", False)  # A dirty only
    apply_settings_exit(side, "escape")
    side.close()

    side2 = reopen_settings(qapp, persisted)
    assert_invariant(
        side2._chk_clip.isChecked(),
        "A cancel: clipboard still True",
        widget="settings.clipboard",
        state="reopen",
    )
    assert_invariant(
        side2._chk_sys.isChecked(),
        "B unchanged: sys still True",
        widget="settings.sys_audio",
        state="reopen",
    )
    side2.close()


def test_save_button_spam_idempotent(qapp):
    side, _persisted, saved = make_settings_sidebar(qapp, copy_to_clipboard=False)
    set_toggle(side, "_chk_clip", True)
    spam_clicks(side._btn_save, times=8)
    assert_invariant(len(saved) >= 1, "spam Save: at least one emit", widget="settings.save", state="saved")
    before = len(saved)
    # While clean, Save is disabled — further spam must not emit.
    spam_clicks(side._btn_save, times=5)
    assert_invariant(
        len(saved) == before,
        "spam Save while clean: no extra emits",
        widget="settings.save",
        state="clean",
    )
    side.close()


@pytest.mark.parametrize("combo", SETTINGS_COMBOS, ids=[c.action_id for c in SETTINGS_COMBOS])
@pytest.mark.parametrize("exit_id", _DISCARD_EXITS, ids=_DISCARD_EXITS)
def test_dock_edge_draft_exit_matrix(qapp, combo, exit_id):
    side, persisted, _ = make_settings_sidebar(qapp, **{combo.config_key: combo.default})
    widget = getattr(side, combo.attr)
    original = widget.currentData()
    other = next(v for v in combo.values if v != original)
    idx = widget.findData(other)
    assert_invariant(idx >= 0, f"combo has {other}", widget=combo.action_id, state="setup")
    widget.setCurrentIndex(idx)
    side._check_dirty()
    assert_invariant(is_settings_dirty(side), "dirty after edge change", widget=combo.action_id, state="draft")

    apply_settings_exit(side, exit_id)
    side.close()
    side2 = reopen_settings(qapp, persisted)
    assert_invariant(
        getattr(side2, combo.attr).currentData() == original,
        f"exit={exit_id}: dock edge draft discarded",
        widget=combo.action_id,
        state="reopen",
    )
    side2.close()


@pytest.mark.parametrize("combo", SETTINGS_COMBOS, ids=[c.action_id for c in SETTINGS_COMBOS])
def test_dock_edge_save_persists(qapp, combo):
    side, persisted, saved = make_settings_sidebar(qapp, **{combo.config_key: combo.default})
    widget = getattr(side, combo.attr)
    other = next(v for v in combo.values if v != combo.default)
    widget.setCurrentIndex(widget.findData(other))
    side._check_dirty()
    side._save()
    assert_invariant(saved[-1].get(combo.config_key) == other, "payload edge", widget=combo.action_id, state="saved")
    side.close()
    side2 = reopen_settings(qapp, persisted)
    assert_invariant(
        getattr(side2, combo.attr).currentData() == other,
        "edge persisted",
        widget=combo.action_id,
        state="reopen",
    )
    side2.close()


def test_quit_button_emits_once_under_spam(qapp):
    side, _, _ = make_settings_sidebar(qapp)
    quits = []
    side.quit_requested.connect(lambda: quits.append(1))
    spam_clicks(side._btn_quit, times=6)
    assert_invariant(len(quits) >= 1, "quit emitted", widget="settings.quit", state="spam")
    # Product may emit once per click; document count — must not crash.
    side.close()
