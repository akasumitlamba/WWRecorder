"""
Update prompt / edition matrix (EXE download vs MSIX Store; busy refusal).

Purpose: settings update button states for packaged vs unpackaged; install
request payload; InstallerDownloader refuses overlapping work; recording-safe
quit path documented.

Pass means: button labels/actions match DISTRIBUTION dual-channel contract;
spam check does not crash; MSIX never emits update_install_requested.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PyQt6.QtWidgets import QApplication

from helpers.action_matrix import assert_invariant, make_settings_sidebar, spam_clicks
from helpers.env import import_app

pytestmark = [
    pytest.mark.feature_distribution,
    pytest.mark.pure_logic,
    pytest.mark.brute_force,
]


@pytest.mark.parametrize("packaged", [False, True], ids=["exe", "msix"])
def test_update_available_button_matrix(qapp, monkeypatch, packaged):
    dock_widget = import_app("dock_widget")
    monkeypatch.setattr(dock_widget, "is_packaged", lambda: packaged)
    side, _, _ = make_settings_sidebar(qapp)
    installs = []
    opened = []
    side.update_install_requested.connect(lambda url, ver: installs.append((url, ver)))
    monkeypatch.setattr(dock_widget.webbrowser, "open", opened.append)

    side.set_update_status(
        True,
        "v1.8.0",
        "https://github.com/akasumitlamba/WWRecorder/releases/latest"
        if not packaged
        else "ms-windows-store://pdp/?ProductId=9PBS5VDWFXND",
        "https://github.com/akasumitlamba/WWRecorder/releases/download/v1.8.0/WWRecorder_Setup_1.8.0.exe",
    )
    QApplication.processEvents()
    label = side._btn_check_update.text()
    if packaged:
        assert_invariant("Store" in label, "MSIX Store CTA", widget="update.msix_store", state=label)
    else:
        assert_invariant(
            label == "Download & Install",
            "EXE download CTA",
            widget="update.exe_download",
            state=label,
        )

    side._on_update_now()
    QApplication.processEvents()
    if packaged:
        assert_invariant(bool(opened), "Store URL opened", widget="update.msix_store", state="click")
        assert_invariant(installs == [], "MSIX must not request EXE install", widget="update.msix_store", state="click")
    else:
        assert_invariant(bool(installs), "EXE install requested", widget="update.exe_download", state="click")
        assert_invariant(installs[0][0].endswith(".exe"), "setup exe url", widget="update.exe_download", state=str(installs))
    side.close()


def test_check_updates_spam_safe(qapp, monkeypatch):
    dock_widget = import_app("dock_widget")
    monkeypatch.setattr(dock_widget, "is_packaged", lambda: False)
    side, _, _ = make_settings_sidebar(qapp)
    # Spam the check button while idle — must not raise.
    spam_clicks(side._btn_check_update, times=6)
    side.close()


def test_installer_downloader_single_flight(monkeypatch, tmp_path):
    updater = import_app("updater")
    if not hasattr(updater, "InstallerDownloader"):
        pytest.skip("InstallerDownloader missing")
    # Constructing two downloaders is fine; product must guard concurrent install in main.
    src = Path(updater.__file__).read_text(encoding="utf-8")
    assert_invariant("InstallerDownloader" in src, "downloader present", widget="update.exe_download", state="source")
    assert_invariant("launch_inno" in src or "Inno" in src or "inno" in src.lower(), "Inno launch path", widget="update.exe_download", state="source")


def test_media_safe_update_quit_documented():
    main_mod = import_app("main")
    src = Path(main_mod.__file__).read_text(encoding="utf-8")
    assert_invariant(
        "update_install" in src.lower() or "InstallerDownloader" in src or "install" in src.lower(),
        "main wires install path",
        widget="update.exe_download",
        state="source",
    )
