"""Synthetic endpoint lifecycle tests; physical WASAPI listening is separate."""
import threading
import time
from types import SimpleNamespace

import numpy as np
import pytest
from helpers.env import import_app

pytestmark = [pytest.mark.feature_audio, pytest.mark.pure_logic]


@pytest.fixture
def engine(monkeypatch):
    rec = import_app('recorder')
    monkeypatch.setattr(rec.RecordingEngine, 'cleanup_temp_dir', lambda *_: None)
    return rec.RecordingEngine()


def endpoint(identifier, name=None, loopback=False):
    return SimpleNamespace(id=identifier, name=name or identifier, isloopback=loopback)


def test_multiple_inputs_excludes_loopback_and_resolves_by_id(engine, monkeypatch):
    rec = import_app('recorder')
    devices = [endpoint('usb1', 'USB mic'), endpoint('usb2', 'USB mic'), endpoint('output', loopback=True)]
    monkeypatch.setattr(rec.sc, 'all_microphones', lambda **_: devices)
    assert engine.list_microphones() == [('usb1', 'USB mic'), ('usb2', 'USB mic')]
    engine.set_microphone('usb2', 'USB mic')
    assert engine._resolve_audio_device(False) is devices[1]
    monkeypatch.setattr(rec.sc, 'default_microphone', lambda: devices[0])
    engine.set_microphone()
    assert engine._resolve_audio_device(False) is devices[0]


@pytest.mark.parametrize('missing', [False, True])
def test_remembered_selection_or_missing_reset_on_first_open(engine, monkeypatch, tmp_path, missing):
    rec = import_app('recorder'); capture = import_app('microphone_capture')
    chosen, default = endpoint('usb'), endpoint('windows')
    engine.set_microphone('usb', 'USB mic'); engine.set_mic(True)
    engine._running = True
    monkeypatch.setattr(rec.sc, 'all_microphones', lambda **_: [] if missing else [chosen, default])
    monkeypatch.setattr(rec.sc, 'default_microphone', lambda: default)
    monkeypatch.setattr(engine, '_get_native_samplerate', lambda *_: 48000)
    opened = []
    class Stream:
        def __enter__(self): return self
        def __exit__(self, *_): pass
    monkeypatch.setattr(capture, 'native_microphone_recorder', lambda device, *_: (opened.append(device.id) or Stream(), 48000))
    def read(*_):
        engine._running = False
        return np.zeros((256, 2), np.float32), 0
    monkeypatch.setattr(rec, '_read_audio_chunk', read)
    engine._audio_worker(False, str(tmp_path/'mic.wav'))
    assert opened == ['windows' if missing else 'usb']
    assert engine._microphone_id == ('' if missing else 'usb')
    events = engine.drain_runtime_events()
    assert ('microphone_selection_reset', 'usb') in events if missing else not events


def test_disconnect_does_not_switch_take_and_reconnect_recovers_same_mic(engine, monkeypatch, tmp_path):
    rec = import_app('recorder'); capture = import_app('microphone_capture')
    chosen = endpoint('usb', 'USB mic'); devices = [chosen]
    engine.set_microphone('usb', 'USB mic'); engine.set_mic(True); engine._running = True
    monkeypatch.setattr(rec.sc, 'all_microphones', lambda **_: list(devices))
    monkeypatch.setattr(rec.sc, 'default_microphone', lambda: pytest.fail('Must not switch this take'))
    monkeypatch.setattr(engine, '_get_native_samplerate', lambda *_: 48000)
    opened = []
    class Stream:
        def __enter__(self): return self
        def __exit__(self, *_): pass
    monkeypatch.setattr(capture, 'native_microphone_recorder', lambda device, *_: (opened.append(device.id) or Stream(), 48000))
    def read(*_):
        if len(opened) == 1:
            devices.clear()
            raise OSError('USB unplugged')
        engine._running = False
        return np.zeros((256, 2), np.float32), 0
    monkeypatch.setattr(rec, '_read_audio_chunk', read)
    worker = threading.Thread(target=engine._audio_worker, args=(False, str(tmp_path/'mic.wav')))
    worker.start(); events = []
    try:
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            events.extend(engine.drain_runtime_events())
            if any(kind == 'audio_error' for kind, _ in events): break
            time.sleep(.01)
        assert ('microphone_selection_reset', 'usb') in events
        assert engine._microphone_failed
        assert any('USB mic' in message and 'continues' in message for kind, message in events if kind == 'audio_error')
        assert engine._microphone_id == 'usb' and opened == ['usb']
        devices.append(chosen)
        worker.join(3)
        assert not worker.is_alive() and opened == ['usb', 'usb']
    finally:
        engine._running = False; worker.join(3)


@pytest.mark.parametrize('newer_choice', [False, True])
def test_reset_persists_windows_without_overwriting_newer_manual_choice(newer_choice):
    main = import_app('main'); saved = []
    coordinator = SimpleNamespace(config={'microphone_id': 'other' if newer_choice else 'usb'},
        engine=SimpleNamespace(drain_runtime_events=lambda: [('microphone_selection_reset', 'usb')]),
        _on_microphone_selected=lambda *args: saved.append(args))
    main.WWRecorderApp._poll_engine_events(coordinator)
    assert saved == ([] if newer_choice else [('', 'Same as Windows')])


def test_new_mic_is_listed_when_menu_reopened_during_recording(qapp, engine):
    ui = import_app('ui_elements')
    pill = ui.PillWidget(engine, {}, pre_record=False); pill.show()
    try:
        pill._open_microphone_menu([('usb1', 'First mic')], '')
        assert 'First mic' in [action.text() for action in pill._mic_menu.actions()]
        pill._mic_menu.close()
        pill._open_microphone_menu([('usb1', 'First mic'), ('usb2', 'Connected during take')], '')
        assert 'Connected during take' in [action.text() for action in pill._mic_menu.actions()]
        assert not engine.get_mic()  # Listing/selection must not enable recording.
    finally:
        if pill._mic_menu: pill._mic_menu.close()
        pill._stopping = True; pill.close()


def test_one_wireless_name_failure_does_not_hide_other_inputs(engine, monkeypatch):
    rec = import_app('recorder')
    class Connecting:
        id = 'connecting'
        @property
        def name(self): raise OSError('Endpoint properties still arriving')
    monkeypatch.setattr(rec.sc, 'all_microphones', lambda **_: [endpoint('first'), Connecting(), endpoint('second'), endpoint('first')])
    assert engine.list_microphones() == [('first', 'first'), ('connecting', 'Microphone (name temporarily unavailable)'), ('second', 'second')]


def test_open_menu_refreshes_in_place_and_preserves_selection(qapp, engine):
    ui = import_app('ui_elements'); engine.set_microphone('first', 'First')
    pill = ui.PillWidget(engine, {}, pre_record=False); pill.show()
    try:
        pill._open_microphone_menu([('first', 'First')], '')
        menu = pill._mic_menu; action = menu._microphone_actions[1]
        menu.setActiveAction(action)
        assert pill._mic_refresh_timer.isActive()
        pill._apply_microphone_refresh(menu, [('first', 'First'), ('wireless', 'New wireless')], '')
        assert pill._mic_menu is menu and menu.isVisible()
        assert [a.data() for a in menu._microphone_actions] == ['', 'first', 'wireless']
        assert menu._microphone_actions[1].isChecked()
        assert menu.activeAction().data() == 'first'
        assert engine._microphone_id == 'first'
        pill._apply_microphone_refresh(menu, [], 'Temporarily busy')
        assert [a.data() for a in menu._microphone_actions] == ['', 'first', 'wireless']
        assert menu._microphone_error is not None
        pill._apply_microphone_refresh(menu, [('first', 'First')], '')
        assert menu._microphone_error is None
        menu.close()
        assert not pill._mic_refresh_timer.isActive()
        pill._apply_microphone_refresh(menu, [('late', 'Late callback')], '')
        assert pill._mic_menu is None
    finally:
        pill._stopping = True; pill.close()


def test_async_refresh_lists_delayed_wireless_input_without_bt_settings(qapp, engine, monkeypatch):
    from PyQt6.QtTest import QTest
    # Finish the preceding popup's queued hide/deletion before opening another.
    QTest.qWait(30)
    ui = import_app('ui_elements'); calls = []
    def enumerate_inputs():
        calls.append(threading.get_ident())
        return [('first', 'First'), ('wireless', 'Delayed wireless')]
    monkeypatch.setattr(engine, 'list_microphones', enumerate_inputs)
    pill = ui.PillWidget(engine, {}, pre_record=False); pill.show()
    QTest.qWait(30)  # A real click occurs after the owner has activated.
    try:
        pill._open_microphone_menu([('first', 'First')], '')
        menu = pill._mic_menu
        pill._refresh_microphone_menu()
        deadline = time.monotonic()+3
        while len(menu._microphone_actions) != 3 and time.monotonic()<deadline: QTest.qWait(10)
        assert [a.data() for a in menu._microphone_actions] == ['', 'first', 'wireless']
        assert calls and all(identifier != threading.get_ident() for identifier in calls)
        menu.close()
        pill._mic_menu_worker.wait(2000)
    finally:
        pill._stopping = True; pill.close()
