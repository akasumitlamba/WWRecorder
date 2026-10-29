"""Security remediation: actual consent UI, child lifetime and native artifact gates."""
import importlib.util
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import threading
import time

import pytest
from PyQt6.QtWidgets import QMessageBox
from PyQt6.QtTest import QTest
from helpers.env import import_app
from helpers.action_matrix import FakeRecordingEngine

pytestmark = [pytest.mark.pure_logic, pytest.mark.adversarial]
ROOT = Path(__file__).resolve().parents[3]


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_pill():
    return import_app('ui_elements').PillWidget(FakeRecordingEngine(), {}, pre_record=True)


@pytest.mark.feature_keycast
@pytest.mark.parametrize('remember', [False, True])
def test_keycast_warning_acceptance_is_explicit_and_remembered(qapp, remember):
    pill = make_pill()
    persisted = []
    pill.keycast_consent_changed.connect(persisted.append)
    pill._btn_keycast.setChecked(True)
    box = pill._keycast_warning
    assert box is not None and not pill._btn_keycast.isChecked()
    assert pill._keycast.session is None
    assert 'visible in the recording' in box.text()
    assert 'passwords' in box.informativeText() and 'outside' in box.informativeText()
    assert not box.checkBox().isChecked()
    box.checkBox().setChecked(remember)
    next(b for b in box.buttons() if b.text() == 'Enable Keycast').click()
    QTest.qWait(10)
    assert pill._btn_keycast.isChecked()
    assert persisted == ([True] if remember else [])
    assert pill._config.get('keycast_warning_dismissed', False) == remember
    pill._btn_keycast.setChecked(False)
    pill._btn_keycast.setChecked(True)
    assert (pill._keycast_warning is None) == remember
    if pill._keycast_warning:
        pill._keycast_warning.reject()
    pill.close()


@pytest.mark.feature_keycast
def test_cancel_does_not_enable_or_remember_keycast(qapp):
    pill = make_pill()
    pill._btn_keycast.setChecked(True)
    box = pill._keycast_warning
    box.checkBox().setChecked(True)
    box.button(QMessageBox.StandardButton.Cancel).click()
    QTest.qWait(10)
    assert not pill._btn_keycast.isChecked()
    assert not pill._config.get('keycast_warning_dismissed', False)
    assert pill._keycast.session is None
    pill.close()


@pytest.mark.feature_keycast
def test_saved_consent_and_administrator_disablement(qapp, monkeypatch):
    pill = make_pill()
    pill._config['keycast_warning_dismissed'] = True
    policy = import_app('enterprise_policy')
    monkeypatch.setattr(policy, 'disabled', lambda name: name == 'Keycast')
    pill._btn_keycast.setChecked(True)
    assert not pill._btn_keycast.isChecked()
    assert pill._keycast_warning is None and pill._keycast.session is None
    pill.close()


def child(code):
    return subprocess.Popen([sys.executable, '-u', '-c', code],
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


@pytest.mark.feature_editor
@pytest.mark.parametrize('duration', [0, 1000])
def test_silent_stalled_export_times_out_and_reaps(duration):
    supervise = import_app('export_process').supervise_export
    process = child('import time; time.sleep(30)')
    started = time.monotonic()
    with pytest.raises(TimeoutError, match='original recording is unchanged'):
        supervise(process, duration, lambda: False, lambda _: None,
                  inactivity_seconds=0.15, total_seconds=2)
    assert process.poll() is not None and time.monotonic() - started < 5


@pytest.mark.feature_editor
def test_noisy_export_and_endless_lines_have_bounded_diagnostics():
    supervise = import_app('export_process').supervise_export
    process = child('import sys; sys.stderr.write("x"*1000000+"\\n"); '
                    '[sys.stderr.write("diagnostic %d\\n"%i) for i in range(10000)]')
    result = supervise(process, 0, lambda: False, lambda _: None, inactivity_seconds=5)
    assert process.returncode == 0 and len(result) < 21000
    assert 'diagnostic 9999' in result and 'diagnostic 0\n' not in result


@pytest.mark.feature_editor
def test_advancing_export_is_not_mistaken_for_a_stall():
    supervise = import_app('export_process').supervise_export
    process = child('import sys,time\nfor i in range(12):\n '
                    'sys.stderr.write("out_time_us=%d\\n"%(i*100000)); '
                    'sys.stderr.flush(); time.sleep(.05)')
    progress = []
    supervise(process, 2000, lambda: False, progress.append, inactivity_seconds=.4, total_seconds=3)
    assert process.returncode == 0 and len(progress) == 12 and progress[-1] == 55


@pytest.mark.feature_editor
def test_continuously_noisy_child_cannot_evade_whole_operation_deadline():
    supervise = import_app('export_process').supervise_export
    process = child('import sys,time\ni=0\nwhile True:\n '
                    'sys.stderr.write("out_time_us=%d\\n"%i); sys.stderr.flush(); i+=1; time.sleep(.02)')
    with pytest.raises(TimeoutError):
        supervise(process, 1000, lambda: False, lambda _: None,
                  inactivity_seconds=2, total_seconds=.2)
    assert process.poll() is not None


@pytest.mark.feature_editor
def test_cancel_reaps_a_child_that_never_outputs():
    supervise = import_app('export_process').supervise_export
    process = child('import time; time.sleep(30)')
    cancel = threading.Event()
    timer = threading.Timer(.1, cancel.set)
    timer.start()
    try:
        supervise(process, 0, cancel.is_set, lambda _: None)
        assert process.poll() is not None
    finally:
        timer.join()


@pytest.mark.feature_distribution
def test_media_gate_rejects_missing_tampered_and_legacy_dlls(tmp_path):
    gate = load_script('security_release')
    binary = b'approved codec bytes'
    expected = hashlib.sha256(binary).hexdigest()
    manifest = {'ffmpeg': {'exe_sha256': expected}, 'qt': {'dll_sha256': {'avcodec-63.dll': expected}}}
    (tmp_path / 'ffmpeg.exe').write_bytes(binary)
    with pytest.raises(ValueError, match='missing media binary'):
        gate.verify_media(tmp_path, manifest)
    codec = tmp_path / 'avcodec-63.dll'
    codec.write_bytes(binary)
    assert len(gate.verify_media(tmp_path, manifest)) == 2
    codec.write_bytes(b'tampered')
    with pytest.raises(ValueError): gate.verify_media(tmp_path, manifest)
    codec.write_bytes(binary)
    (tmp_path / 'avcodec-61.dll').write_bytes(binary)
    with pytest.raises(ValueError, match='legacy'): gate.verify_media(tmp_path, manifest)


@pytest.mark.feature_distribution
def test_actual_approved_encoder_hash_and_patch_record():
    gate = load_script('security_release')
    manifest = json.loads((ROOT / 'packaging/shared/media-security.json').read_text())
    executable = ROOT / 'app/ffmpeg.exe'
    assert executable.exists()
    assert gate.sha256(executable) == manifest['ffmpeg']['exe_sha256']
    assert manifest['ffmpeg']['version'] == '9.0.2'
    assert manifest['qt']['ffmpeg_version'] == '9.0.1'
    assert 'avcodec-63.dll' in manifest['qt']['dll_sha256']


@pytest.mark.feature_distribution
@pytest.mark.windows_native
def test_installed_build_qt_codec_bytes_match_approved_wheel():
    from PyQt6.QtCore import QLibraryInfo
    gate = load_script('security_release')
    manifest = json.loads((ROOT / 'packaging/shared/media-security.json').read_text())
    directory = Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.BinariesPath))
    for name, digest in manifest['qt']['dll_sha256'].items():
        assert gate.sha256(directory / name) == digest


@pytest.mark.feature_processing
def test_native_crash_log_rotation_keeps_recent_diagnostics(tmp_path):
    main = import_app('main')
    path = tmp_path / 'wwrecorder-crash.log'
    path.write_bytes(b'current failure')
    main._rotate_native_crash_log(path, limit=100)
    assert path.read_bytes() == b'current failure'
    main._rotate_native_crash_log(path, limit=4)
    assert not path.exists() and path.with_suffix('.log.1').read_bytes() == b'current failure'
    path.write_bytes(b'new failure')
    main._rotate_native_crash_log(path, limit=4)
    assert path.with_suffix('.log.1').read_bytes() == b'new failure'


@pytest.mark.feature_distribution
def test_dependency_checker_records_advisories_without_hiding_them():
    import io
    audit = load_script('audit_dependencies')
    calls = []
    def open_response(request, **kwargs):
        calls.append(json.loads(request.data))
        return io.BytesIO(json.dumps({'vulns': [{'id': 'GHSA-test-test-test'}]}).encode())
    result = audit.check_package('Pillow', '13.0.0', opener=open_response)
    assert result['advisories'] == ['GHSA-test-test-test']
    assert calls[0]['version'] == '13.0.0'


@pytest.mark.feature_distribution
def test_oversized_release_metadata_is_rejected(qapp, monkeypatch):
    import io
    updater = import_app('updater')
    monkeypatch.setattr(updater.urllib.request, 'urlopen', lambda *a, **k: io.BytesIO(b'x' * (2 * 1024 * 1024 + 1)))
    worker = updater.UpdateChecker('1.7.0')
    worker._packaged = False
    failures = []
    worker.check_failed.connect(failures.append)
    worker.run()
    assert failures and 'incomplete response' in failures[0]


@pytest.mark.feature_settings
@pytest.mark.parametrize('value,kind,expected', [(1,4,True),(0,4,False),(1,1,False)])
def test_machine_policy_is_read_from_admin_location(monkeypatch, value, kind, expected):
    from types import SimpleNamespace
    policy = import_app('enterprise_policy')
    calls = []
    class Key:
        def __enter__(self): return self
        def __exit__(self,*args): return False
    registry = SimpleNamespace(HKEY_LOCAL_MACHINE=1, KEY_READ=2, KEY_WOW64_64KEY=4, REG_DWORD=4,
        OpenKey=lambda *args: (calls.append(args), Key())[1], QueryValueEx=lambda *_: (value,kind))
    monkeypatch.setitem(sys.modules, 'winreg', registry)
    monkeypatch.setattr(policy, 'sys', SimpleNamespace(platform='win32'))
    assert policy.disabled('AutomaticClipboard') is expected
    assert calls[0][0] == registry.HKEY_LOCAL_MACHINE
    assert calls[0][1] == r'SOFTWARE\Policies\WWRecorder'
    assert not policy.disabled('NotAnApprovedPolicy')


@pytest.mark.feature_settings
def test_admin_policy_also_prevents_automatic_player_frame_copy(qapp, monkeypatch):
    from types import SimpleNamespace
    policy = import_app('enterprise_policy')
    monkeypatch.setattr(policy, 'disabled', lambda name: name == 'AutomaticClipboard')
    editor = import_app('video_editor')
    saved = []
    fake = SimpleNamespace(_btn_screenshot=SimpleNamespace(setEnabled=lambda _: None, setToolTip=lambda _: None),
        _toast=SimpleNamespace(show_message=lambda *args: saved.append(args)))
    qapp.clipboard().setText('existing clipboard')
    editor.VideoPlayerWindow._on_screenshot_done(fake, 'synthetic.png')
    assert saved and qapp.clipboard().text() == 'existing clipboard'


@pytest.mark.feature_distribution
def test_source_provenance_works_with_sanitized_build_path(monkeypatch):
    import re
    import shutil
    executable = shutil.which('git')
    assert executable, 'Git is required for release source provenance'
    gate = load_script('security_release')
    monkeypatch.setenv('PATH', '')
    revision, dirty = gate.source_identity(executable)
    assert re.fullmatch('[0-9a-f]{40}', revision) and type(dirty) is bool


@pytest.mark.feature_distribution
@pytest.mark.windows_native
def test_one_click_source_launcher_prepares_encoder_and_starts_without_input(tmp_path):
    receipt = tmp_path / 'source-startup.json'
    result = subprocess.run(['cmd.exe', '/c', str(ROOT / 'Run-WWRecorder.cmd'),
                             '--distribution-smoke-test', str(receipt)],
                            cwd=ROOT, stdin=subprocess.DEVNULL, capture_output=True,
                            text=True, timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(receipt.read_text())['ok'] is True
