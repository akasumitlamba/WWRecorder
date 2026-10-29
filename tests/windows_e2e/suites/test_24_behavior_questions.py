"""Owner-decided contracts (2026-10-27) — assert live code matches docs.

Former BQ-001…BQ-005 skips are removed: decisions were applied in product code
and governing docs. These tests lock the chosen behaviors.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from helpers.env import import_app, REPO_ROOT
from helpers.assertions import assert_eq

pytestmark = [pytest.mark.pure_logic, pytest.mark.feature_distribution]


def _read(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8", errors="replace")


def test_mutex_is_local_not_global():
    main_mod = import_app("main")
    src = Path(main_mod.__file__).read_text(encoding="utf-8")
    assert "Local\\" in src or 'Local\\' in src
    assert "Global\\WWRecorder_mutex" not in _read("docs/project.md")
    assert "Local\\\\WWRecorder_mutex" in _read("docs/DISTRIBUTION.md") or "Local\\WWRecorder_mutex" in _read(
        "docs/DISTRIBUTION.md"
    )


def test_recording_crf_is_20_live_and_25_final():
    recorder = import_app("recorder")
    assert_eq(recorder.TEMP_VIDEO_CRF, 20, because="owner decision: live CRF 20")
    assert_eq(recorder.FINAL_VIDEO_CRF, 25, because="owner decision: final CRF 25")
    project = _read("docs/project.md").lower()
    assert "crf 23" not in project or "editor export" in project  # editor export may cite 23
    assert "ultrafast crf 20" in project
    assert "crf 25" in project


def test_processing_notice_not_waiting_gif():
    main_src = Path(import_app("main").__file__).read_text(encoding="utf-8")
    pn_src = Path(import_app("processing_notice").__file__).read_text(encoding="utf-8")
    assert "from processing_notice import ProcessingNotice as _SavingPopup" in main_src
    assert "waiting.gif" not in pn_src
    assert "cat.gif" not in pn_src
    project = _read("docs/project.md")
    assert "waiting.gif" not in project or "removed" in project.lower()


def test_exe_updater_exposes_silent_download_helpers():
    updater = import_app("updater")
    assert hasattr(updater, "InstallerDownloader")
    assert hasattr(updater, "launch_inno_installer")
    assert hasattr(updater, "select_installer_asset")
    assert hasattr(updater, "parse_github_release")


def test_select_installer_asset_prefers_setup_over_local_test():
    updater = import_app("updater")
    url = updater.select_installer_asset(
        [
            {"name": "notes.txt", "browser_download_url": "https://github.com/x/notes.txt"},
            {
                "name": "WWRecorder_Setup_1.7.0_local-test.exe",
                "browser_download_url": "https://github.com/x/local.exe",
            },
            {
                "name": "WWRecorder_Setup_1.7.0.exe",
                "browser_download_url": "https://github.com/x/setup.exe",
            },
        ]
    )
    assert_eq(url, "https://github.com/x/setup.exe", because="prefer official Setup over local-test")


def test_parse_github_release_exe_includes_download_url():
    updater = import_app("updater")
    available, version, action, download = updater.parse_github_release(
        {
            "tag_name": "v1.8.0",
            "assets": [
                {
                    "name": "WWRecorder_Setup_1.8.0.exe",
                    "browser_download_url": "https://github.com/akasumitlamba/WWRecorder/releases/download/v1.8.0/WWRecorder_Setup_1.8.0.exe",
                }
            ],
        },
        "1.7.0",
        packaged=False,
    )
    assert available is True
    assert version == "v1.8.0"
    assert download.endswith("WWRecorder_Setup_1.8.0.exe")
    assert "github.com" in action


def test_parse_github_release_msix_has_store_action_no_download(monkeypatch):
    updater = import_app("updater")
    monkeypatch.setattr(updater, "store_url", lambda: "ms-windows-store://pdp/?ProductId=9PBS5VDWFXND")
    available, version, action, download = updater.parse_github_release(
        {
            "tag_name": "v1.8.0",
            "assets": [
                {
                    "name": "WWRecorder_Setup_1.8.0.exe",
                    "browser_download_url": "https://github.com/x/WWRecorder_Setup_1.8.0.exe",
                }
            ],
        },
        "1.7.0",
        packaged=True,
    )
    assert available is False
    assert version == ""
    assert download == ""
    assert action.startswith("ms-windows-store://")


def test_installer_downloader_refuses_when_packaged(monkeypatch, qapp):
    updater = import_app("updater")
    monkeypatch.setattr(updater, "is_packaged", lambda: True)
    worker = updater.InstallerDownloader("https://github.com/akasumitlamba/WWRecorder/releases/download/v1.8.0/WWRecorder_Setup_1.8.0.exe")
    failures = []
    worker.download_failed.connect(failures.append)
    worker.download_finished.connect(lambda *_: pytest.fail("MSIX must not finish an EXE download"))
    worker.run()
    assert failures and "Store" in failures[0]


def test_installer_downloader_refuses_non_github_host(monkeypatch, qapp):
    updater = import_app("updater")
    monkeypatch.setattr(updater, "is_packaged", lambda: False)
    worker = updater.InstallerDownloader("https://evil.example/setup.exe")
    failures = []
    worker.download_failed.connect(failures.append)
    worker.run()
    assert failures and "official" in failures[0].lower()


def test_packaged_update_checker_never_queries_github(monkeypatch, qapp):
    """A packaged check must not contact the EXE feed or infer Store availability."""
    import json

    updater = import_app("updater")
    monkeypatch.setattr(updater, "is_packaged", lambda: True)
    payload = {
        "tag_name": "v9.9.9",
        "assets": [
            {
                "name": "WWRecorder_Setup_9.9.9.exe",
                "browser_download_url": "https://github.com/akasumitlamba/WWRecorder/releases/download/v9.9.9/WWRecorder_Setup_9.9.9.exe",
            }
        ],
    }

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self, *_args):
            return json.dumps(payload).encode()

    opened = []

    def fake_urlopen(req, context=None, timeout=10):
        opened.append(req.full_url if hasattr(req, "full_url") else req)
        return FakeResp()

    monkeypatch.setattr(updater.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(updater, "store_url", lambda: "ms-windows-store://pdp/?ProductId=9PBS5VDWFXND")
    worker = updater.UpdateChecker("1.7.0")
    worker._packaged = True
    successes, failures = [], []
    worker.check_finished.connect(lambda *a: successes.append(a))
    worker.check_failed.connect(failures.append)
    worker.run()
    assert not opened, "MSIX must never query the EXE release feed"
    assert successes and not failures
    available, version, action, download = successes[0]
    assert available is False
    assert version == ""
    assert download == ""
    assert "ms-windows-store" in action


def test_exe_update_checker_returns_download_url(monkeypatch, qapp):
    import json

    updater = import_app("updater")
    monkeypatch.setattr(updater, "is_packaged", lambda: False)
    payload = {
        "tag_name": "v9.9.9",
        "assets": [
            {
                "name": "WWRecorder_Setup_9.9.9.exe",
                "browser_download_url": "https://github.com/akasumitlamba/WWRecorder/releases/download/v9.9.9/WWRecorder_Setup_9.9.9.exe",
            }
        ],
    }

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self, *_args):
            return json.dumps(payload).encode()

    monkeypatch.setattr(updater.urllib.request, "urlopen", lambda *a, **k: FakeResp())
    worker = updater.UpdateChecker("1.7.0")
    worker._packaged = False
    successes = []
    worker.check_finished.connect(lambda *a: successes.append(a))
    worker.run()
    assert successes
    available, version, action, download = successes[0]
    assert available is True
    assert download.endswith("WWRecorder_Setup_9.9.9.exe")


def test_msix_distribution_contract_uses_store_authority():
    dist = _read('docs/DISTRIBUTION.md').lower()
    assert 'must never query' in dist
    assert 'microsoft store' in dist
