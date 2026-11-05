"""Processing notice / finalization UI (no fake percentage; dismiss != cancel).

Purpose: AI_CONTEXT 2026-10-27 processing_notice ownership.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from helpers.env import import_app

pytestmark = [pytest.mark.feature_processing]


@pytest.mark.pure_logic
def test_processing_notice_module_has_activity_ring_not_percent():
    pn = import_app("processing_notice")
    assert hasattr(pn, "ProcessingNotice")
    assert hasattr(pn, "ActivityRing")
    src = Path(pn.__file__).read_text(encoding="utf-8")
    assert "percentage" in src.lower() or "deliberately not a percentage" in src.lower()
    assert "waiting.gif" not in src
    assert "cat.gif" not in src


@pytest.mark.pure_logic
def test_main_aliases_processing_notice_as_saving_popup():
    main_mod = import_app("main")
    src = Path(main_mod.__file__).read_text(encoding="utf-8")
    assert "from processing_notice import ProcessingNotice as _SavingPopup" in src


@pytest.mark.pure_logic
def test_processing_notice_constructs_offscreen(qapp):
    pn = import_app("processing_notice")
    notice = pn.ProcessingNotice()
    notice.show()
    qapp.processEvents()
    # Dismiss must not claim to cancel mux — just hide UI
    notice.hide()
    qapp.processEvents()
    notice.close()
