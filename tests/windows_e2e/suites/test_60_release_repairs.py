"""User-facing popup lifecycle, actual policy enforcement, thumbnails and native upgrade bridge."""
import sys
from types import SimpleNamespace
import pytest
from PyQt6.QtCore import Qt,QSize
from PyQt6.QtWidgets import QApplication,QMessageBox
from PyQt6.QtGui import QImage,QColor
from PyQt6.QtTest import QTest
from helpers.env import import_app
from helpers.action_matrix import FakeRecordingEngine

pytestmark=[pytest.mark.pure_logic,pytest.mark.feature_ui]


def test_discard_is_centered_modal_and_does_not_get_covered_or_duplicate(qapp,monkeypatch):
    pill=import_app('ui_elements').PillWidget(FakeRecordingEngine(),{},pre_record=False)
    pill.show();pill._initiate_discard();QTest.qWait(20)
    box=pill._discard_dialog;assert box.isVisible() and not pill._stopping
    assert QApplication.activeModalWidget() is box
    assert (box.geometry().center()-pill.screen().availableGeometry().center()).manhattanLength()<=35
    raised=[];monkeypatch.setattr(pill,'raise_',lambda:raised.append(True))
    pill._enforce_topmost();assert not raised
    pill._initiate_discard();assert pill._discard_dialog is box
    box.button(QMessageBox.StandardButton.Cancel).click();QTest.qWait(10)
    assert pill._discard_dialog is None and not pill._stopping
    pill._pre_record=True;pill.close()


@pytest.mark.parametrize('exit_action',['escape','close'])
def test_keycast_warning_has_clear_icon_and_cancel_never_remembers(qapp,exit_action):
    pill=import_app('ui_elements').PillWidget(FakeRecordingEngine(),{},pre_record=True)
    pill._btn_keycast.setChecked(True);box=pill._keycast_warning;QTest.qWait(10)
    assert not box.iconPixmap().isNull()
    assert box.iconPixmap().deviceIndependentSize().width() <= 64
    assert 'passwords' in box.informativeText().lower() and 'outside the selected area' in box.informativeText()
    assert box.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
    box.checkBox().setChecked(True)
    if exit_action=='escape':QTest.keyClick(box,Qt.Key.Key_Escape)
    else:box.close()
    QTest.qWait(10)
    assert pill._keycast_warning is None and not pill._btn_keycast.isChecked()
    assert not pill._config.get('keycast_warning_dismissed',False)
    pill.close()


def test_real_machine_policy_reader_blocks_keycast_and_automatic_frame_copy(qapp,monkeypatch):
    policy=import_app('enterprise_policy');seen=[]
    class Key:
        def __enter__(self):return self
        def __exit__(self,*args):return False
    def query(key,name):seen.append(name);return 1,4
    registry=SimpleNamespace(HKEY_LOCAL_MACHINE=1,KEY_READ=2,KEY_WOW64_64KEY=4,REG_DWORD=4,OpenKey=lambda *args:Key(),QueryValueEx=query)
    monkeypatch.setitem(sys.modules,'winreg',registry)
    monkeypatch.setattr(policy,'sys',SimpleNamespace(platform='win32'))
    pill=import_app('ui_elements').PillWidget(FakeRecordingEngine(),{'keycast_warning_dismissed':True},pre_record=True)
    pill._btn_keycast.setChecked(True)
    assert not pill._btn_keycast.isChecked() and pill._keycast_warning is None and pill._keycast.session is None
    editor=import_app('video_editor');qapp.clipboard().setText('unchanged sensitive clipboard')
    fake=SimpleNamespace(_btn_screenshot=SimpleNamespace(setEnabled=lambda _:None,setToolTip=lambda _:None),_toast=SimpleNamespace(show_message=lambda *_:None))
    editor.VideoPlayerWindow._on_screenshot_done(fake,'fixture.png')
    assert qapp.clipboard().text()=='unchanged sensitive clipboard'
    assert {'DisableKeycast','DisableAutomaticClipboard'}<=set(seen)
    pill.close()


def test_native_update_bridge_delivers_close_request_without_force_kill(qapp):
    bridge=import_app('main')._InstallerBridge();requested=[];bridge.shutdown_requested.connect(lambda:requested.append(True))
    if sys.platform=='win32':
        import ctypes
        from ctypes import wintypes
        message=wintypes.MSG();message.message=0x8047
        assert bridge.nativeEvent(b'windows_generic_MSG',ctypes.addressof(message))==(True,0)
        assert requested==[True]
        message.message=0x0000
        assert bridge.nativeEvent(b'windows_generic_MSG',ctypes.addressof(message))==(False,0)
        assert requested==[True]
    assert bridge.windowTitle()=='WWRecorder Update Bridge'
    bridge.close()


@pytest.mark.windows_native
def test_installer_finds_hidden_bridge_and_requests_quit_across_processes(tmp_path):
    import json,os,subprocess,time,ctypes
    from pathlib import Path
    ready=tmp_path/'ready.json';closed=tmp_path/'closed.json'
    root=Path(__file__).resolve().parents[3]
    code='''import sys,json,traceback,faulthandler
faulthandler.enable()
sys.excepthook=lambda *args: traceback.print_exception(*args,file=sys.stderr)
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer
print('Starting native Qt application',flush=True)
app=QApplication([]);app.setQuitOnLastWindowClosed(False)
print('Native Qt application created',flush=True)
from main import _InstallerBridge
bridge=_InstallerBridge()
print('Native bridge created',flush=True)
def close_requested():
 Path(sys.argv[3]).write_text('{"closed":true}')
 app.quit()
bridge.shutdown_requested.connect(close_requested)
Path(sys.argv[2]).write_text(json.dumps({'hwnd':int(bridge.winId())}))
QTimer.singleShot(10000,app.quit)
app.exec()
'''
    env=dict(os.environ,QT_QPA_PLATFORM='windows')
    child=subprocess.Popen([sys.executable,'-u','-c',code,str(root/'app'),str(ready),str(closed)],env=env,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    try:
        deadline=time.monotonic()+8
        while not ready.exists() and child.poll() is None and time.monotonic()<deadline:time.sleep(.02)
        if not ready.exists():
            if child.poll() is None:child.kill()
            stdout,stderr=child.communicate(timeout=5)
            pytest.fail('Native update bridge startup failed (exit '+str(child.returncode)+'): '+stderr.decode(errors='replace')+' '+stdout.decode(errors='replace'))
        user=ctypes.windll.user32
        user.FindWindowW.argtypes=[ctypes.c_wchar_p,ctypes.c_wchar_p];user.FindWindowW.restype=ctypes.c_void_p
        user.PostMessageW.argtypes=[ctypes.c_void_p,ctypes.c_uint,ctypes.c_size_t,ctypes.c_ssize_t]
        hwnd=user.FindWindowW(None,'WWRecorder Update Bridge')
        assert hwnd==json.loads(ready.read_text())['hwnd']
        assert user.PostMessageW(hwnd,0x8047,0,0)
        stdout,stderr=child.communicate(timeout=10)
        assert child.returncode==0,stderr.decode(errors='replace')
        assert json.loads(closed.read_text())['closed']
    finally:
        if child.poll() is None:child.kill();child.communicate(timeout=5)
