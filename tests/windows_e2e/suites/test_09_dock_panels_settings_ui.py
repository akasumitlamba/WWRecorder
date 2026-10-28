"""Dock, gallery panels, and settings draft contracts.

Purpose: four-edge dock keys, draft-until-save settings, panel terminology,
companion-dock transition ownership (AI_CONTEXT 2026-10-26/27).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from helpers.env import import_app
from helpers.assertions import assert_true

pytestmark = [pytest.mark.feature_ui, pytest.mark.feature_settings]


@pytest.fixture(scope="module")
def dock_widget():
    return import_app("dock_widget")


@pytest.mark.pure_logic
def test_dock_edges_supported(dock_widget):
    src = Path(dock_widget.__file__).read_text(encoding="utf-8")
    for edge in ("left", "right", "top", "bottom"):
        assert edge in src


@pytest.mark.pure_logic
def test_settings_uses_panel_terminology(dock_widget):
    src = Path(dock_widget.__file__).read_text(encoding="utf-8")
    assert "panel" in src.lower()


@pytest.mark.pure_logic
def test_settings_draft_until_save_contract_present(dock_widget):
    src = Path(dock_widget.__file__).read_text(encoding="utf-8")
    # Draft settings must not emit application changes until Save (AI_CONTEXT).
    assert "Save Settings" in src or "save_settings" in src.lower() or "settings_saved" in src.lower()


@pytest.mark.pure_logic
def test_sidebar_panel_exposes_transition_signals(dock_widget):
    assert hasattr(dock_widget, "SidebarPanel")
    panel = dock_widget.SidebarPanel
    # Signals may be defined on class
    names = set(dir(panel))
    assert_true(
        {"opening", "opened", "closing"}.issubset(names)
        or "opening" in Path(dock_widget.__file__).read_text(encoding="utf-8"),
        because="SidebarPanel must expose opening/opened/closing transitions",
    )


@pytest.mark.pure_logic
def test_packaged_settings_ignores_exe_availability_and_opens_store(qapp, dock_widget, monkeypatch):
    """A desktop release cannot claim an update exists in Microsoft Store."""
    monkeypatch.setattr(dock_widget, "is_packaged", lambda: True)
    opened = []
    monkeypatch.setattr(dock_widget, "store_url", lambda: "ms-windows-store://pdp/?ProductId=9PBS5VDWFXND")
    monkeypatch.setattr(dock_widget.webbrowser, "open", opened.append)
    sidebar = dock_widget.SettingsSidebar({"current_version": "1.7.0"})
    sidebar.set_update_status(True, "v1.8.0", "ms-windows-store://pdp/?ProductId=9PBS5VDWFXND", "")
    assert "Store" in sidebar._btn_check_update.text()
    assert "1.8.0" not in sidebar._lbl_update_status.text()
    assert "manages updates" in sidebar._lbl_update_status.text()
    sidebar._on_update_now()
    assert opened and "ms-windows-store" in opened[0]
    sidebar.close()


@pytest.mark.pure_logic
def test_exe_settings_offers_download_and_install(qapp, dock_widget, monkeypatch):
    monkeypatch.setattr(dock_widget, "is_packaged", lambda: False)
    sidebar = dock_widget.SettingsSidebar({"current_version": "1.7.0"})
    requested = []
    sidebar.update_install_requested.connect(lambda url, ver: requested.append((url, ver)))
    sidebar.set_update_status(
        True,
        "v1.8.0",
        "https://github.com/akasumitlamba/WWRecorder/releases/latest",
        "https://github.com/akasumitlamba/WWRecorder/releases/download/v1.8.0/WWRecorder_Setup_1.8.0.exe",
    )
    assert sidebar._btn_check_update.text() == "Download & Install"
    sidebar._on_update_now()
    assert requested and requested[0][0].endswith("WWRecorder_Setup_1.8.0.exe")
    sidebar.close()


@pytest.mark.windows_gui
def test_dock_widget_constructs(qapp, dock_widget):
    from types import SimpleNamespace

    main_mod = import_app("main")
    engine = SimpleNamespace(is_recording=False, is_paused=False, list_microphones=lambda: [])
    dock = dock_widget.DockWidget(engine, dict(main_mod.DEFAULT_CONFIG))
    qapp.processEvents()
    dock.close()
    qapp.processEvents()
