"""EXE / MSIX distribution seams (docs/DISTRIBUTION.md).

Purpose: assert package detection, config isolation, update URL routing, and
MSIX never querying the EXE GitHub feed — without requiring Store install.
Pass means: documented parity hooks hold under monkeypatched identities.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from helpers.env import import_app
from helpers.assertions import assert_eq, assert_doc_contract

pytestmark = [pytest.mark.feature_distribution, pytest.mark.pure_logic]


@pytest.fixture
def distribution():
    return import_app("distribution")


@pytest.fixture
def updater():
    return import_app("updater")


def test_update_url_routes_exe_to_github_releases(distribution, monkeypatch):
    monkeypatch.setattr(distribution, "package_family_name", lambda: "")
    assert_eq(
        distribution.update_url(),
        distribution.RELEASES_URL,
        because="EXE builds must open the official GitHub releases page (DISTRIBUTION.md)",
    )


def test_update_url_routes_msix_to_store_product(distribution, monkeypatch, tmp_path):
    monkeypatch.setattr(distribution, "package_family_name", lambda: "akasumitlamba.WWRecorder_45ed26xvm8kc2")
    monkeypatch.setattr(distribution, "is_packaged", lambda: True)
    (tmp_path / "distribution.json").write_text(
        json.dumps({"store_product_id": "9PBS5VDWFXND"}), encoding="utf-8"
    )
    monkeypatch.setattr(distribution.sys, "executable", str(tmp_path / "WWRecorder.exe"))
    assert_eq(
        distribution.package_metadata().get("store_product_id"),
        "9PBS5VDWFXND",
        because="MSIX distribution.json beside the executable must load store_product_id",
    )
    url = distribution.update_url()
    assert_doc_contract(
        url == "ms-windows-store://pdp/?ProductId=9PBS5VDWFXND",
        contract="MSIX update_url uses Store product page, never GitHub EXE feed",
        evidence=url,
    )


def test_config_directory_isolated_for_msix(distribution, monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    monkeypatch.setattr(distribution, "package_family_name", lambda: "Fam.Test_123")
    path = distribution.config_directory()
    assert "Packages" in path.parts
    assert path.name == "WWRecorder"
    monkeypatch.setattr(distribution, "package_family_name", lambda: "")
    exe_path = distribution.config_directory()
    assert exe_path == tmp_path / "roaming" / "WWRecorder"


def test_settings_import_is_one_time_and_preserves_bytes(distribution, tmp_path):
    source = tmp_path / "exe.json"
    target = tmp_path / "package" / "config.json"
    raw = b'{"hotkey":"<ctrl>+r","output_folder":"D:/cap","future":1}'
    source.write_bytes(raw)
    assert distribution.migrate_legacy_config(target, source) is True
    assert source.read_bytes() == raw
    assert target.read_bytes() == raw
    assert target.with_name("config.imported-exe.json").read_bytes() == raw
    target.write_text('{"future":2}', encoding="utf-8")
    assert distribution.migrate_legacy_config(target, source) is False
    assert json.loads(target.read_text(encoding="utf-8"))["future"] == 2


@pytest.mark.parametrize("raw", ["broken", "[]", "null", "1"])
def test_invalid_legacy_settings_are_not_destroyed(distribution, tmp_path, raw):
    source, target = tmp_path / "exe.json", tmp_path / "pkg.json"
    source.write_text(raw, encoding="utf-8")
    with pytest.raises(ValueError):
        distribution.migrate_legacy_config(target, source)
    assert source.read_text(encoding="utf-8") == raw
    assert not target.exists()


def test_packaged_update_checker_delegates_store_without_network(updater, monkeypatch):
    """MSIX never uses EXE release data to establish Store availability."""
    import json

    monkeypatch.setattr(updater, "is_packaged", lambda: True)
    monkeypatch.setattr(updater, "store_url", lambda: "ms-windows-store://pdp/?ProductId=9PBS5VDWFXND")
    payload = {
        "tag_name": "v1.8.0",
        "assets": [
            {
                "name": "WWRecorder_Setup_1.8.0.exe",
                "browser_download_url": "https://github.com/akasumitlamba/WWRecorder/releases/download/v1.8.0/WWRecorder_Setup_1.8.0.exe",
            }
        ],
    }

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps(payload).encode()

    monkeypatch.setattr(updater.urllib.request, "urlopen", lambda *a, **k: pytest.fail("MSIX queried GitHub"))
    worker = updater.UpdateChecker("1.7.0")
    worker._packaged = True
    successes, failures = [], []
    worker.check_finished.connect(lambda *a: successes.append(a))
    worker.check_failed.connect(failures.append)
    worker.run()
    assert successes and not failures
    available, version, action, download = successes[0]
    assert available is False
    assert version == ""
    assert download == ""
    assert "ms-windows-store" in action


def test_application_icon_path_points_at_app_icon_ico(distribution):
    path = Path(distribution.application_icon_path())
    assert path.name == "icon.ico"
    assert path.is_file(), f"canonical icon missing: {path}"
