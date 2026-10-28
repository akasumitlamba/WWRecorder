import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import pytest
import distribution
import dock_widget
import updater
from startup_integration import PackagedStartup
from PyQt6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


def test_settings_import_is_one_time_and_preserves_source_and_unknown_fields(tmp_path):
    source = tmp_path / "exe.json"
    target = tmp_path / "package" / "config.json"
    raw = b'{"hotkey":"<ctrl>+<shift>+r", "output_folder":"D:/captures", "future_setting":23}'
    source.write_bytes(raw)
    assert distribution.migrate_legacy_config(target, source)
    assert source.read_bytes() == target.read_bytes() == raw
    assert target.with_name("config.imported-exe.json").read_bytes() == raw
    target.write_text('{"future_setting":24}')
    assert not distribution.migrate_legacy_config(target, source)
    assert json.loads(target.read_text())["future_setting"] == 24
    assert source.read_bytes() == raw


@pytest.mark.parametrize("raw", ["broken", "[]", "null"])
def test_bad_legacy_settings_are_not_imported_or_deleted(tmp_path, raw):
    source, target = tmp_path / "exe.json", tmp_path / "package.json"
    source.write_text(raw)
    with pytest.raises(ValueError):
        distribution.migrate_legacy_config(target, source)
    assert source.read_text() == raw
    assert not target.exists()


def test_package_config_is_isolated_from_exe(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    monkeypatch.setattr(distribution, "package_family_name", lambda: "test_family")
    assert distribution.config_directory() == tmp_path / "local/Packages/test_family/LocalState/WWRecorder"
    monkeypatch.setattr(distribution, "package_family_name", lambda: "")
    assert distribution.config_directory() == tmp_path / "roaming/WWRecorder"


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig"])
def test_imported_settings_are_loaded_without_losing_preferences(monkeypatch, tmp_path, encoding):
    import main
    source, target = tmp_path / "exe.json", tmp_path / "package/config.json"
    preferences = {"output_folder": "D:/Captures/日本語", "default_mic": True,
                   "start_on_boot": False, "font_size": "Large",
                   "hotkey": "<ctrl>+<shift>+r"}
    source.write_text(json.dumps(preferences), encoding=encoding)
    original = source.read_bytes()
    assert distribution.migrate_legacy_config(target, source)
    monkeypatch.setattr(main, "CONFIG_FILE", target)
    loaded = main.WWRecorderApp._load_config(None)
    assert all(loaded[key] == value for key, value in preferences.items())
    assert source.read_bytes() == target.read_bytes() == original


def test_packaged_updater_never_queries_github_and_delegates_store(monkeypatch, app):
    """Only Microsoft Store can establish availability for packaged installs."""
    monkeypatch.setattr(updater, "is_packaged", lambda: True)
    monkeypatch.setattr(updater, "store_url", lambda: distribution.STORE_LIBRARY_URL)
    payload = {
        "tag_name": "v1.8.0",
        "assets": [{
            "name": "WWRecorder_Setup_1.8.0.exe",
            "browser_download_url": "https://github.com/akasumitlamba/WWRecorder/releases/download/v1.8.0/WWRecorder_Setup_1.8.0.exe",
        }],
    }

    class FakeResp:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def read(self):
            return json.dumps(payload).encode()

    monkeypatch.setattr(updater.urllib.request, "urlopen", lambda *a, **k: pytest.fail("MSIX queried GitHub"))
    worker = updater.UpdateChecker("1.6.3")
    worker._packaged = True
    failures, successes = [], []
    worker.check_failed.connect(failures.append)
    worker.check_finished.connect(lambda *args: successes.append(args))
    worker.run()
    assert successes and not failures
    available, version, action, download = successes[0]
    assert available is False
    assert version == ""
    assert download == ""
    assert action == distribution.STORE_LIBRARY_URL


def test_packaged_update_button_ignores_exe_version_and_opens_store(monkeypatch, app):
    monkeypatch.setattr(dock_widget, "is_packaged", lambda: True)
    opened = []
    monkeypatch.setattr(dock_widget, "store_url", lambda: distribution.STORE_LIBRARY_URL)
    monkeypatch.setattr(dock_widget.webbrowser, "open", opened.append)
    sidebar = dock_widget.SettingsSidebar({"current_version": "1.6.3"})
    sidebar.set_update_status(True, "v1.8.0", distribution.STORE_LIBRARY_URL, "")
    sidebar._on_update_now()
    assert opened == [distribution.STORE_LIBRARY_URL]
    assert "Store" in sidebar._btn_check_update.text()
    assert "1.8.0" not in sidebar._lbl_update_status.text()
    assert "manages updates" in sidebar._lbl_update_status.text()
    sidebar.close()


def test_packaged_installer_downloader_is_blocked(monkeypatch, app):
    monkeypatch.setattr(updater, "is_packaged", lambda: True)
    worker = updater.InstallerDownloader("https://github.com/akasumitlamba/WWRecorder/releases/download/v1/WWRecorder_Setup_1.exe")
    failures = []
    worker.download_failed.connect(failures.append)
    worker.run()
    assert failures


class Operation:
    status = 1
    def __init__(self, value):
        self.value = value
        self.cancelled = False
    def get_results(self):
        return self.value
    def cancel(self):
        self.cancelled = True


class Task:
    def __init__(self, state):
        self.state = state
        self.enable_calls = 0
    def request_enable_async(self):
        self.enable_calls += 1
        self.state = 2
        return Operation(2)
    def disable(self):
        self.state = 0


def run_startup(monkeypatch, app, task, desired):
    from winrt.windows import applicationmodel
    monkeypatch.setattr(applicationmodel, "StartupTask", SimpleNamespace(get_async=lambda _: Operation(task)))
    controller = PackagedStartup()
    results = []
    controller.finished.connect(lambda *args: results.append(args))
    controller.sync(desired)
    controller._poll()
    if controller._operation is not None:
        controller._poll()
    return results


def test_user_disabled_startup_cannot_be_overridden(monkeypatch, app):
    task = Task(1)
    results = run_startup(monkeypatch, app, task, True)
    assert results[0][0] is False
    assert "Windows Settings" in results[0][1]
    assert task.enable_calls == 0


def test_startup_read_does_not_reenable_external_disable(monkeypatch, app):
    task = Task(0)
    assert run_startup(monkeypatch, app, task, None) == [(False, "")]
    assert task.enable_calls == 0


@pytest.mark.parametrize("state,desired,expected", [(0, True, True), (2, False, False), (4, False, True), (3, True, False)])
def test_startup_reports_actual_state(monkeypatch, app, state, desired, expected):
    result = run_startup(monkeypatch, app, Task(state), desired)
    assert result[0][0] == expected
    assert bool(result[0][1]) == (state in (3, 4))


def test_startup_timeout_cancels_operation(app):
    controller = PackagedStartup()
    operation = Operation(None)
    operation.status = 0
    controller._operation = operation
    controller._deadline = 0
    results = []
    controller.finished.connect(lambda *args: results.append(args))
    controller._poll()
    assert operation.cancelled
    assert results[0][0] is None and "timed out" in results[0][1]


def test_packaged_startup_never_writes_run_registry(monkeypatch, app):
    import main
    calls = []
    monkeypatch.setattr(main, "is_packaged", lambda: True)
    monkeypatch.setattr(main.winreg, "OpenKey", lambda *a, **kw: pytest.fail("MSIX touched EXE Run key"))
    fake = SimpleNamespace(config={"start_on_boot": True}, _packaged_startup=SimpleNamespace(sync=calls.append))
    main.WWRecorderApp._sync_registry(fake)
    assert calls == [True]


def test_packaged_manual_check_opens_store_without_starting_worker(monkeypatch,app):
    monkeypatch.setattr(dock_widget, 'is_packaged', lambda: True)
    monkeypatch.setattr(dock_widget, 'store_url', lambda: distribution.STORE_LIBRARY_URL)
    opened=[]
    monkeypatch.setattr(dock_widget.webbrowser, 'open', opened.append)
    monkeypatch.setattr(dock_widget, 'UpdateChecker', lambda *a: pytest.fail('Store check started GitHub worker'))
    sidebar=dock_widget.SettingsSidebar({'current_version':'1.7.0'})
    sidebar._on_check_updates()
    assert opened == [distribution.STORE_LIBRARY_URL]
    assert not sidebar._update_status['available']
    sidebar.close()
