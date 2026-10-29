"""Reproduce reported defects and preserve deliberately rejected code paths.

Portable tests exercise real Qt events, worker ownership, WAV writers and
FFmpeg exports with synthetic endpoints. No physical Windows device claim.
"""
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import numpy as np
import pytest
from PyQt6.QtCore import QCoreApplication, QEvent, QObject, QPointF, QProcess, Qt, pyqtSignal
from PyQt6.QtGui import QImage
from PyQt6.QtTest import QTest
from helpers.env import import_app
from helpers.action_matrix import FakeRecordingEngine

pytestmark = [pytest.mark.pure_logic, pytest.mark.adversarial]


def wait_for(condition, seconds=4):
    deadline = time.monotonic() + seconds
    while not condition() and time.monotonic() < deadline:
        QTest.qWait(10)
    assert condition()


@pytest.mark.parametrize('reason', [
    'Stream #0:1: Audio: opus\nError initializing filter: invalid dimensions',
    'Cannot delete voice.wav: unknown filesystem failure',
    'ffmpeg failed with exit code 1: invalid filter graph',
    'No such microphone file in this export'])
@pytest.mark.feature_files
def test_free_text_failures_are_not_misclassified(reason):
    assert import_app('user_messages').friendly_error(reason) == reason


@pytest.mark.feature_editor
def test_export_audio_switch_does_not_change_preview(qapp, monkeypatch):
    ve = import_app('video_editor');window = ve.VideoPlayerWindow('')
    window._thumbnails_loaded = True
    window._toggle_edit_mode()
    before = window._btn_vol.icon().pixmap(64, 64).toImage()
    QTest.mouseClick(window._toggle_audio,Qt.MouseButton.LeftButton)
    assert window._mute_on_export
    assert not window._audio_output.isMuted()
    assert window._btn_vol.icon().pixmap(64, 64).toImage() == before
    window._toggle_mute()
    QTest.mouseClick(window._toggle_audio,Qt.MouseButton.LeftButton)
    assert window._audio_output.isMuted()
    window._force_exit_edit_mode();window.close()


@pytest.mark.parametrize('system', [False, True])
@pytest.mark.feature_audio
def test_disabled_track_never_opens_endpoint_and_enable_disable_releases_it(qapp, tmp_path, monkeypatch, system):
    rec = import_app('recorder');mic = import_app('microphone_capture')
    monkeypatch.setattr(rec.RecordingEngine, 'cleanup_temp_dir', lambda *a: None)
    engine = rec.RecordingEngine();engine._running = True;engine._pause_event.clear()
    calls = [];released = threading.Event()
    class Stream:
        channelmap = [0, 1]
        def __enter__(self): return self
        def __exit__(self, *a): released.set()
    stream = Stream()
    device = SimpleNamespace(id='test', name='Synthetic', recorder=lambda **kw: stream)
    monkeypatch.setattr(engine, '_get_native_samplerate', lambda *_: pytest.fail('Disabled native-rate query'))
    monkeypatch.setattr(engine, '_resolve_audio_device', lambda *_: (calls.append('open') or device))
    monkeypatch.setattr(mic, 'native_microphone_recorder', lambda *a: (stream, 48000))
    def read(*_):
        (engine.set_system_audio if system else engine.set_mic)(False)
        return np.zeros((256, 2), np.float32), 0
    monkeypatch.setattr(rec, '_read_audio_chunk', read)
    ready = engine._sys_audio_ready if system else engine._mic_audio_ready
    worker = threading.Thread(target=engine._audio_worker, args=(system, str(tmp_path/'audio.wav')))
    worker.start()
    try:
        assert ready.wait(1)
        QTest.qWait(100)
        assert calls == []
        (engine.set_system_audio if system else engine.set_mic)(True)
        assert released.wait(2)
        QTest.qWait(100)
        assert calls == ['open']
    finally:
        engine._running = False;worker.join(3)
    assert not worker.is_alive()
    assert not any(t.is_alive() for t in engine._audio_writer_threads.values())
    assert not engine.drain_runtime_events()


@pytest.mark.parametrize('failure_stage', ['initialize', 'start'])
@pytest.mark.feature_audio
def test_failed_selected_mic_switch_names_device_and_continuing_take(qapp, tmp_path, monkeypatch, failure_stage):
    rec = import_app('recorder');mic = import_app('microphone_capture')
    monkeypatch.setattr(rec.RecordingEngine, 'cleanup_temp_dir', lambda *a: None)
    engine = rec.RecordingEngine();engine._running = True;engine.set_mic(True)
    engine.set_microphone('good', 'Good mic')
    monkeypatch.setattr(engine, '_get_native_samplerate', lambda *_: 48000)
    monkeypatch.setattr(engine, 'list_microphones', lambda: [('good','Good mic'),('bad','Blocked USB')])
    monkeypatch.setattr(engine, '_resolve_audio_device', lambda *_: SimpleNamespace(id=engine._microphone_id, name=engine._microphone_name))
    class Stream:
        def __enter__(self): return self
        def __exit__(self, *a): pass
    def open_mic(device, *_):
        if device.id == 'bad':
            if failure_stage == 'initialize': raise PermissionError('Exclusive endpoint')
            class FailsAtStart(Stream):
                def __enter__(self): raise PermissionError('Endpoint Start failed')
            return FailsAtStart(), 48000
        return Stream(), 48000
    monkeypatch.setattr(mic, 'native_microphone_recorder', open_mic)
    def read(*_):
        engine.set_microphone('bad', 'Blocked USB')
        return np.zeros((256, 2),np.float32), 0
    monkeypatch.setattr(rec, '_read_audio_chunk', read)
    worker = threading.Thread(target=engine._audio_worker, args=(False,str(tmp_path/'mic.wav')))
    worker.start();events=[]
    try:
        def got_error():
            events.extend(engine.drain_runtime_events())
            return any(kind=='audio_error' for kind,_ in events)
        wait_for(got_error)
        QTest.qWait(750)
        events.extend(engine.drain_runtime_events())
        errors=[message for kind,message in events if kind=='audio_error']
        assert len(errors)==1 and 'Blocked USB' in errors[0] and 'continues' in errors[0]
        assert engine._microphone_failed
    finally:
        engine._running=False;worker.join(3)
    assert not worker.is_alive()


@pytest.mark.parametrize('owner', ['frame', 'mic', 'writer'])
@pytest.mark.feature_recording
def test_discard_preserves_files_and_ownership_while_any_writer_alive(tmp_path, monkeypatch, owner):
    rec=import_app('recorder')
    monkeypatch.setattr(rec.RecordingEngine,'cleanup_temp_dir',lambda *a:None)
    engine=rec.RecordingEngine();path=tmp_path/'recoverable.mkv';path.write_bytes(b'only media')
    engine._temp_vid_path=str(path)
    alive=SimpleNamespace(is_alive=lambda:True)
    if owner=='writer':engine._audio_writer_threads[False]=alive
    else:setattr(engine, '_frame_thread' if owner=='frame' else '_mic_thread', alive)
    assert engine.discard() is False
    assert path.read_bytes()==b'only media' and engine.is_busy()
    assert engine.drain_runtime_events()[0][0]=='capture_error'


@pytest.mark.feature_recording
def test_discard_waits_for_mux_owner_instead_of_deleting_concurrently(qapp,tmp_path):
    ui=import_app('ui_elements');main=import_app('main')
    entered=threading.Event();release=threading.Event();trace=[]
    source=tmp_path/'input.tmp';source.write_bytes(b'capture');output=tmp_path/'output.mkv'
    class Engine(FakeRecordingEngine):
        def stop_capture(self): trace.append(('stop',threading.get_ident()))
        def mux_and_save(self):
            trace.append(('mux',threading.get_ident()));entered.set();release.wait(3)
            assert source.exists();output.write_bytes(b'output');return str(output)
        def discard(self):
            trace.append(('discard',threading.get_ident()));source.unlink(missing_ok=True)
    pill=ui.PillWidget(Engine(),dict(main.DEFAULT_CONFIG),pre_record=False)
    saved=[];pill.save_completed.connect(saved.append)
    pill._initiate_stop();assert entered.wait(2)
    pill._initiate_discard(confirm=False)
    assert source.exists() and not any(kind=='discard' for kind,_ in trace)
    release.set();wait_for(lambda:not pill._stop_worker.isRunning());QTest.qWait(50)
    assert [kind for kind,_ in trace]==['stop','mux','discard']
    assert len({thread for _,thread in trace})==1
    assert not source.exists() and not output.exists() and not saved
    pill.close()


@pytest.mark.feature_recording
def test_discard_reentrant_before_worker_start_still_stops_capture(qapp):
    ui=import_app('ui_elements');main=import_app('main');engine=FakeRecordingEngine()
    pill=ui.PillWidget(engine,dict(main.DEFAULT_CONFIG),pre_record=False)
    pill.stopped.connect(lambda result:pill._initiate_discard(confirm=False) if result=='<SAVING>' else None)
    pill._initiate_stop();wait_for(lambda:not pill._stop_worker.isRunning());QTest.qWait(30)
    assert engine.stop_capture_calls==1 and engine.mux_calls==0
    pill.close()


@pytest.mark.feature_files
def test_locked_rename_is_asynchronous_and_acknowledged_only_after_success(qapp,tmp_path,monkeypatch):
    main=import_app('main');controller=main.WWRecorderApp.__new__(main.WWRecorderApp)
    old=tmp_path/'old.mkv';new=tmp_path/'new.mkv';old.write_bytes(b'video')
    restored=[];failures=[];calls=[]
    player=SimpleNamespace(_filepath=str(old),_player=SimpleNamespace(setSource=lambda *_:None),restore_source_after_rename=restored.append)
    controller.app=qapp;controller._video_player_windows=[player];controller._success_notif=None
    controller._recent_panel=None;controller._last_saved_filepath=str(old)
    controller._show_rename_error=failures.append
    rename=os.rename
    def locked(a,b):
        calls.append((a,b))
        if len(calls)<3:raise PermissionError('File still locked')
        rename(a,b)
    monkeypatch.setattr(main.os,'rename',locked)
    controller._safe_rename(str(old),str(new))
    assert calls==[] and old.exists() and not restored
    controller._safe_rename(str(old),str(new))  # duplicate must not own another retry timer
    wait_for(lambda:new.exists())
    assert len(calls)==3 and restored==[str(new)] and not failures
    assert controller._last_saved_filepath==str(new)


@pytest.mark.parametrize('photo', [False,True])
@pytest.mark.feature_annotation
def test_escape_reaches_focused_text_field_and_cancels_without_commit(qapp,tmp_path,photo):
    ann=import_app('annotation_tool')
    if photo:
        image=QImage(100,100,QImage.Format.Format_RGB32);image.fill(Qt.GlobalColor.white)
        path=tmp_path/'image.png';image.save(str(path))
        canvas=ann._DrawingArea(str(path));canvas.show();canvas._start_text_input(QPointF(20,20))
    else:
        canvas=ann.AnnotationCanvas();canvas.show();canvas._start_text_input((20,20))
    canvas._text_edit.setFocus();QTest.qWait(20)
    QTest.keyClicks(canvas._text_edit,'cancel this')
    QTest.keyClick(canvas._text_edit,Qt.Key.Key_Escape)
    assert not canvas._text_input_active
    assert not any(item.get('type')=='text' for item in canvas._items if isinstance(item,dict))
    canvas.close()


@pytest.mark.feature_geometry
def test_odd_normalized_capture_crops_mapping_without_rescaling_or_black_edge(qapp):
    main=import_app('main');capture=import_app('capture_frames')
    pixels=np.zeros((33,241,4),np.uint8);pixels[:,:,:3]=[41,153,219];pixels[:,:,3]=255
    calls=[]
    class Grab:
        def grab(self,region):calls.append(region);return SimpleNamespace(raw=pixels.tobytes())
    segment=dict(src_left=-50,src_top=10,src_width=241,src_height=33,dst_left=0,dst_top=0,dst_width=241,dst_height=33)
    plan=main._normalized_capture_plan({'width':241,'height':33,'segments':[segment]})
    image=capture.capture_bgra_frame(Grab(),plan['segments'],plan['width'],plan['height'])
    assert image.shape==(32,240,4)
    assert np.array_equal(image,pixels[:32,:240])
    assert calls[0]['width']==241  # Existing fast path rejects mismatched dimensions.


class Response(io.BytesIO):
    def __init__(self,data,url='https://release-assets.githubusercontent.com/asset',length=None):
        super().__init__(data);self.url=url
        self.headers={} if length is None else {'Content-Length':str(length)}
    def geturl(self):return self.url


@pytest.mark.parametrize('failure', ['truncated','checksum','redirect'])
@pytest.mark.feature_distribution
def test_installer_rejects_incomplete_tampered_or_foreign_download(qapp,tmp_path,monkeypatch,failure):
    updater=import_app('updater');data=b'MZverified'
    monkeypatch.setattr(updater,'is_packaged',lambda:False)
    monkeypatch.setattr(updater,'update_staging_directory',lambda:tmp_path)
    monkeypatch.setattr(updater,'_installer_metadata',lambda *_:(hashlib.sha256(data).hexdigest(),len(data)))
    payload=data[:-2] if failure=='truncated' else b'X'*len(data) if failure=='checksum' else data
    response=Response(payload,url='https://example.com/setup.exe' if failure=='redirect' else 'https://release-assets.githubusercontent.com/asset',length=len(data))
    monkeypatch.setattr(updater.urllib.request,'build_opener',lambda *a:SimpleNamespace(open=lambda *a,**k:response))
    worker=updater.InstallerDownloader('https://github.com/akasumitlamba/WWRecorder/releases/download/v1.7/WWRecorder_Setup.exe')
    failed=[];saved=[];worker.download_failed.connect(failed.append);worker.download_finished.connect(saved.append)
    worker.run()
    assert failed and not saved and not list(tmp_path.iterdir())


@pytest.mark.feature_distribution
def test_redirect_hops_are_checked_before_following():
    updater=import_app('updater')
    from urllib.request import Request
    with pytest.raises(ValueError,match='redirect'):
        updater._OfficialRedirects().redirect_request(Request('https://github.com/asset'),None,302,'Found',{},'http://example.com/setup.exe')


@pytest.mark.feature_distribution
def test_verified_installer_is_rechecked_before_launch(qapp,tmp_path,monkeypatch):
    updater=import_app('updater');payload=b'MZverified'
    monkeypatch.setattr(updater,'is_packaged',lambda:False)
    monkeypatch.setattr(updater,'update_staging_directory',lambda:tmp_path)
    monkeypatch.setattr(updater,'_installer_metadata',lambda *_:(hashlib.sha256(payload).hexdigest(),len(payload)))
    monkeypatch.setattr(updater,'_open_update_url',lambda *_:Response(payload,length=len(payload)))
    worker=updater.InstallerDownloader('https://github.com/akasumitlamba/WWRecorder/releases/download/v1.7/WWRecorder_Setup.exe')
    saved=[];worker.download_finished.connect(saved.append);worker.run();assert saved
    launches=[];monkeypatch.setattr(updater.subprocess,'Popen',lambda args,**kw:launches.append(args))
    updater.launch_inno_installer(saved[0]);assert len(launches)==1
    Path(saved[0]).write_bytes(b'MZtampered')
    with pytest.raises(PermissionError,match='integrity'):updater.launch_inno_installer(saved[0])
    assert len(launches)==1


@pytest.mark.feature_distribution
def test_official_metadata_requires_matching_asset_and_sha256(qapp,monkeypatch):
    updater=import_app('updater');url='https://github.com/akasumitlamba/WWRecorder/releases/download/v1.7/WWRecorder_Setup.exe'
    data={'assets':[{'browser_download_url':url,'digest':'sha256:'+'a'*64,'size':7}]}
    monkeypatch.setattr(updater,'_open_update_url',lambda *a,**kw:Response(json.dumps(data).encode()))
    assert updater._installer_metadata(url)==('a'*64,7)
    data['assets'][0]['digest']=None
    with pytest.raises(ValueError,match='integrity'):updater._installer_metadata(url)


@pytest.mark.feature_playback
def test_late_scrub_process_finishes_after_window_deletion_without_widget_access(qapp,monkeypatch):
    ve=import_app('video_editor')
    from PyQt6 import sip
    class SlowProcess(QProcess):
        def start(self,*_):
            super().start(sys.executable,['-c','import time;time.sleep(0.35)'])
        def kill(self): pass  # Simulate a child that does not exit within the reap bound.
        def waitForFinished(self,*_): return False
    monkeypatch.setattr(ve,'QProcess',SlowProcess)
    monkeypatch.setattr(ve,'_get_ffmpeg',lambda:sys.executable)
    errors=[];monkeypatch.setattr(sys,'excepthook',lambda *args:errors.append(args))
    window=ve.VideoPlayerWindow('');window._seekbar_dragging=True
    window._decode_scrub_preview(100)
    process=window._scrub_process
    window._close_ready=True;window.close();window.deleteLater()
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    assert sip.isdeleted(window)
    wait_for(lambda:sip.isdeleted(process))
    assert errors==[]


@pytest.mark.feature_audio
def test_audio_gap_clock_excludes_paused_intervals(monkeypatch):
    rec=import_app('recorder');monkeypatch.setattr(rec.RecordingEngine,'cleanup_temp_dir',lambda *a:None)
    engine=rec.RecordingEngine();engine._capture_clock_start=100
    engine._pause_intervals=[(0,2),(5,8)];engine._pause_started_at=None
    assert engine._active_elapsed(110)==5
    engine._pause_started_at=109
    assert engine._active_elapsed(111)==4


@pytest.mark.feature_audio
def test_audio_issue_tray_title_does_not_claim_disconnection(qapp):
    main=import_app('main');controller=main.WWRecorderApp.__new__(main.WWRecorderApp)
    messages=[]
    controller.engine=SimpleNamespace(drain_runtime_events=lambda:[('audio_error','Blocked mic. Recording continues.')])
    controller.tray=SimpleNamespace(showMessage=lambda *args:messages.append(args),icon=lambda:None)
    controller._poll_engine_events()
    assert messages[0][0]=='Audio capture issue' and 'continues' in messages[0][1]


@pytest.mark.feature_recording
def test_stale_saving_cannot_reset_discard_latch(qapp):
    main=import_app('main');controller=main.WWRecorderApp.__new__(main.WWRecorderApp)
    controller._capture_discarded=True
    controller.engine=SimpleNamespace(is_recording=lambda:False)
    controller.pill=None;controller.border_widget=None;controller._overlay=None
    controller._act_record=SimpleNamespace(setEnabled=lambda *_:None,setText=lambda *_:None)
    controller._destroy_annotation_canvas=lambda:None
    controller.dock=SimpleNamespace(set_recording_state=lambda *_:None)
    titles=[];controller.tray=SimpleNamespace(setToolTip=titles.append,showMessage=lambda *_:None,icon=lambda:None)
    controller._saving_popup=None;controller._recent_panel=None
    controller._on_recording_stopped('<DISCARDED>')
    controller._on_recording_stopped('<SAVING>')
    assert controller._capture_discarded and controller._processing_filename is None
    assert not any('Processing' in title for title in titles)


@pytest.mark.feature_hotkeys
def test_qt_hotkey_signal_from_python_thread_delivers_on_gui(qapp):
    # This is the same QObject/AutoConnection pattern used by HotkeyListener.
    from PyQt6.QtCore import QThread, pyqtSlot
    main=import_app('main')
    class Receiver(QObject):
        @pyqtSlot()
        def receive(self): delivered.append(QThread.currentThread())
    bridge=main.HotkeyListener('<shift>+<home>', '<shift>+<end>');receiver=Receiver();delivered=[]
    bridge.record_triggered.connect(receiver.receive)
    sender=threading.Thread(target=bridge.record_triggered.emit);sender.start();sender.join()
    assert delivered==[]
    wait_for(lambda:bool(delivered))
    assert delivered==[qapp.thread()]


@pytest.mark.feature_editor
def test_actual_caption_rect_has_zero_origin(qapp):
    ve=import_app('video_editor');view=ve._VideoGraphicsView()
    model=ve._TextOverlayItem();item=ve.DraggableTextItem(model,view.video_item)
    view.gfx_scene.addItem(item)
    for size in (12,32,140):
        model.font_size=size;model.bold=True;model.italic=True;item.update_style()
        assert item.boundingRect().topLeft()==QPointF(0,0)
    view.close()


@pytest.mark.feature_recording
def test_late_discard_cannot_touch_a_newer_session(tmp_path, monkeypatch):
    rec=import_app('recorder');monkeypatch.setattr(rec.RecordingEngine,'cleanup_temp_dir',lambda *a:None)
    engine=rec.RecordingEngine();engine._session_generation=2
    path=tmp_path/'new-take.tmp';path.write_bytes(b'new session')
    engine._temp_vid_path=str(path)
    assert engine.discard(expected_generation=1)=='<DISCARDED>'
    assert path.read_bytes()==b'new session'


@pytest.mark.feature_editor
def test_export_error_preserves_reason_and_media_safety_context(qapp):
    ve=import_app('video_editor');window=ve.VideoPlayerWindow('')
    window._on_export_error('Stream Audio: opus\nNo such filter: invalid_filter')
    message=window._toast.text()
    assert 'original recording is unchanged' in message and 'invalid_filter' in message
    assert 'Reconnect' not in message
    window.close()


@pytest.mark.feature_files
def test_rename_failure_restores_original_source_and_does_not_claim_new_name(qapp,tmp_path,monkeypatch):
    main=import_app('main');controller=main.WWRecorderApp.__new__(main.WWRecorderApp)
    old=tmp_path/'original.mkv';old.write_bytes(b'original')
    new=tmp_path/'target.mkv';new.write_bytes(b'existing')
    restored=[];errors=[]
    controller.app=qapp;controller._video_player_windows=[SimpleNamespace(_filepath=str(old),_player=SimpleNamespace(setSource=lambda *_:None),restore_source_after_rename=restored.append)]
    controller._success_notif=None;controller._recent_panel=None;controller._last_saved_filepath=str(old)
    controller._show_rename_error=errors.append
    controller._safe_rename(str(old),str(new));wait_for(lambda:bool(errors))
    assert restored==[str(old)] and controller._last_saved_filepath==str(old)
    assert old.read_bytes()==b'original' and new.read_bytes()==b'existing'


@pytest.mark.feature_recording
def test_live_writer_blocks_discard_until_thread_has_exited(qapp,tmp_path,monkeypatch):
    rec=import_app('recorder');monkeypatch.setattr(rec.RecordingEngine,'cleanup_temp_dir',lambda *a:None)
    engine=rec.RecordingEngine();release=threading.Event()
    writer=threading.Thread(target=release.wait,daemon=True);writer.start()
    path=tmp_path/'still-open.wav';path.write_bytes(b'recoverable audio')
    engine._mic_wav_path=str(path);engine._audio_writer_threads[False]=writer
    try:
        assert engine.discard() is False and path.exists()
    finally:
        release.set();writer.join(2)
    assert engine.discard()=='<DISCARDED>'
    wait_for(lambda:not path.exists())
    assert not engine.is_busy()


@pytest.mark.feature_recording
def test_discard_during_real_ffmpeg_mux_retains_inputs_until_completion(qapp,tmp_path,monkeypatch):
    import shutil
    rec=import_app('recorder');ui=import_app('ui_elements');main=import_app('main')
    ffmpeg=shutil.which('ffmpeg') or str(Path(rec.__file__).with_name('ffmpeg.exe'))
    assert Path(ffmpeg).is_file(),'FFmpeg is required for live mux ownership verification'
    source=tmp_path/'capture.mkv';output=tmp_path/'final.mkv'
    subprocess.run([ffmpeg,'-v','error','-f','lavfi','-i','testsrc2=size=64x64:rate=30:duration=1','-c:v','libx264',str(source)],check=True,timeout=20)
    monkeypatch.setattr(rec.RecordingEngine,'cleanup_temp_dir',lambda *a:None)
    engine=rec.RecordingEngine();engine._session_generation=1
    engine._temp_vid_path=str(source);engine._sys_wav_path=str(tmp_path/'absent-system.wav')
    engine._mic_wav_path=str(tmp_path/'absent-mic.wav');engine._output_path=str(output)
    engine._capture_clock_start=time.perf_counter()-1;engine._capture_stopped_at=engine._capture_clock_start+1
    engine._captured_frames=30;engine._pause_intervals=[];engine._finalizing=True
    monkeypatch.setattr(rec,'get_ffmpeg_path',lambda:ffmpeg)
    original_run=subprocess.run;entered=threading.Event()
    def real_time_mux(command,*args,**kwargs):
        command=list(command);index=command.index('-i');command.insert(index,'-re')
        entered.set()
        return original_run(command,*args,**kwargs)
    monkeypatch.setattr(rec.subprocess,'run',real_time_mux)
    pill=ui.PillWidget(engine,dict(main.DEFAULT_CONFIG),pre_record=False)
    saved=[];pill.save_completed.connect(saved.append)
    pill._initiate_stop();assert entered.wait(3)
    pill._initiate_discard(confirm=False)
    assert source.exists() and not saved
    wait_for(lambda:not pill._stop_worker.isRunning(),seconds=10)
    wait_for(lambda:not source.exists() and not output.exists())
    assert saved==[] and not engine.is_busy()
    pill.close()


@pytest.mark.feature_files
def test_notification_keeps_original_name_until_async_rename_acknowledges(qapp,tmp_path,monkeypatch):
    main=import_app('main');controller=main.WWRecorderApp.__new__(main.WWRecorderApp)
    old=tmp_path/'original.mkv';old.write_bytes(b'media')
    notice=main._SuccessNotification(str(old),'Saved',old.name)
    controller.app=qapp;controller._video_player_windows=[];controller._success_notif=notice
    controller._recent_panel=None;controller._last_saved_filepath=str(old)
    errors=[];controller._show_rename_error=errors.append
    notice.rename_needed.connect(controller._safe_rename)
    notice._toggle_rename();notice._rename_edit.setText('changed')
    def fail(*_):raise OSError('Filesystem unavailable')
    monkeypatch.setattr(main.os,'rename',fail)
    notice._commit_rename()
    assert notice._filepath==str(old) and not notice._btn_rename.isEnabled()
    wait_for(lambda:bool(errors))
    assert notice._filepath==str(old) and old.exists() and notice._btn_rename.isEnabled()
    assert notice._is_renaming
    controller._success_notif=None;notice.close()
