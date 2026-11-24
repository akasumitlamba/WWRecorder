"""Bounded memory, visible failures and complete media under bad conditions."""
import os
import shutil
import struct
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtGui import QImage
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from tests.windows_e2e.helpers.env import import_app

recorder = import_app('recorder')
annotation_tool = import_app('annotation_tool')
video_editor = import_app('video_editor')
WWRecorderApp = import_app('main').WWRecorderApp


@pytest.fixture(scope='module')
def app():
    yield QApplication.instance() or QApplication([])


def _ffmpeg():
    path = shutil.which('ffmpeg') or str(Path(recorder.__file__).with_name('ffmpeg.exe'))
    if not os.path.isfile(path):
        pytest.skip('Real encoder unavailable')
    return path


def test_player_output_has_no_per_frame_receivers(app):
    # Each queued frame signal keeps a full picture alive while the GUI is busy.
    window = video_editor.VideoPlayerWindow('')
    sink = window._video_view.player_sink
    assert window._player.videoSink() is sink
    assert sink.receivers(sink.videoFrameChanged) == 0
    assert window._player.videoOutput() is None
    window.close()


def test_frozen_interface_does_not_accumulate_video_frames(app, tmp_path):
    if not os.path.exists('/proc/self/status'):
        pytest.skip('Reads process memory from /proc')
    video = tmp_path / 'freeze.mkv'
    subprocess.run([_ffmpeg(), '-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc2=s=1920x1080:r=30:d=8',
                    '-c:v', 'libx264', '-preset', 'ultrafast', str(video)], check=True, timeout=60)
    def memory():
        with open('/proc/self/status') as status:
            return next(int(line.split()[1]) // 1024 for line in status if line.startswith('VmRSS'))
    window = video_editor.VideoPlayerWindow(str(video)); window.show()
    try:
        deadline = time.monotonic() + 10
        while window._player.position() < 1000 and time.monotonic() < deadline:
            QTest.qWait(50)
        assert window._player.position() >= 1000
        before = memory()
        time.sleep(4)  # about 120 frames, over 350 MB if they were queued
        assert memory() - before < 150
    finally:
        window._player.stop(); window.close()


def test_player_frame_sampling_is_throttled_until_near_the_end(app, monkeypatch):
    view = video_editor._VideoGraphicsView()
    view._frame_timer.stop()
    clock = [100.0]
    monkeypatch.setattr(video_editor.time, 'monotonic', lambda: clock[0])
    kept, shown = [], []
    monkeypatch.setattr(view, '_remember_frame', kept.append)
    current = [0]
    frame = SimpleNamespace(isValid=lambda: True, startTime=lambda: current[0])
    view.player_sink = SimpleNamespace(videoFrame=lambda: frame)
    view._video_item = SimpleNamespace(videoSink=lambda: SimpleNamespace(setVideoFrame=shown.append))
    for _ in range(30):
        current[0] += 33; clock[0] += 0.033
        view._sample_frame()
    assert 3 <= len(kept) <= 5 and len(shown) == 30  # every picture is displayed
    view.set_frame_precision(True); kept.clear()
    for _ in range(10):
        current[0] += 33; clock[0] += 0.033
        view._sample_frame()
    assert len(kept) == 10


def test_video_list_accepts_brackets_and_vanishing_files(tmp_path, monkeypatch):
    folder = tmp_path / 'rec [work]'; folder.mkdir()
    for index, name in enumerate(('old.mkv', 'new.MP4', 'note.txt')):
        (folder / name).write_bytes(b'x'); os.utime(folder / name, (index + 1, index + 1))
    assert [os.path.basename(p) for p in video_editor._list_videos(str(folder))] == ['new.MP4', 'old.mkv']
    assert video_editor._list_videos(str(tmp_path / 'missing')) == []


def _area(app, image):
    return annotation_tool._DrawingArea(image)


def _picture():
    image = QImage(40, 20, QImage.Format.Format_ARGB32)
    for x in range(40):
        for y in range(20):
            image.setPixelColor(x, y, annotation_tool.QColor(x * 6, y * 12, 90))
    return image


def test_rotate_and_flip_keep_no_pictures_and_undo_exactly(app):
    area = _area(app, _picture())
    original = QImage(area._original)
    steps = ['rotate_90', 'flip_h', 'flip_v'] * 20
    for action in steps:
        area._apply_structural_transform(action)
    final = QImage(area._original)
    record = area._items[0]
    while record:
        assert record['old_image'] is None and record['new_image'] is None
        record = next((i for i in record['old_items'] if i.get('type') == 'transform'), None)
    for _ in steps:
        area.undo()
    fmt = QImage.Format.Format_ARGB32
    assert area._original.convertToFormat(fmt) == original.convertToFormat(fmt)
    assert not area._items
    for _ in steps:
        area.redo()
    assert area._original.convertToFormat(fmt) == final.convertToFormat(fmt)


def test_crop_undo_pictures_are_bounded_but_latest_step_undoes(app, monkeypatch):
    monkeypatch.setattr(annotation_tool, 'MAX_TRANSFORM_UNDO_BYTES', 8000)
    area = _area(app, _picture())
    for _ in range(12):
        before = QImage(area._original)
        area._crop_rect = annotation_tool.QRectF(0, 0, area._original.width() - 1, area._original.height())
        area._apply_structural_transform('crop')
    depth, record = 0, area._items[0]
    while record:
        depth += 1
        record = next((i for i in record['old_items'] if i.get('type') == 'transform'), None)
    assert 1 <= depth < 12
    area.undo()
    assert area._original == before


def test_long_silence_is_written_in_small_blocks(tmp_path, monkeypatch):
    sizes = []
    path = tmp_path / 'a.wav'
    with recorder._Float32WavWriter(str(path), channels=2, samplerate=48000) as writer:
        real = writer.writeframes
        writer.writeframes = lambda raw: (sizes.append(len(raw)), real(raw))
        writer.write_silence(48000 * 20 + 7)
    assert max(sizes) <= 1024 * 1024
    assert path.stat().st_size == 44 + (48000 * 20 + 7) * 8


def test_wav_past_its_header_size_is_read_to_the_end(tmp_path):
    # Stands in for the 4 GB header clamp without writing 4 GB.
    ffmpeg = _ffmpeg(); path = tmp_path / 'long.wav'
    with recorder._Float32WavWriter(str(path), channels=2, samplerate=48000) as writer:
        writer.write_silence(48000 * 3)
    with path.open('r+b') as handle:
        handle.seek(40); handle.write(struct.pack('<I', 48000 * 8))
    def seconds(*options):
        out = subprocess.run([ffmpeg, '-v', 'error', *options, '-i', str(path), '-f', 'f32le', '-'],
                             capture_output=True, timeout=30, check=True).stdout
        return len(out) / 8 / 48000
    assert seconds() == pytest.approx(1)
    assert seconds(*recorder.WAV_INPUT) == pytest.approx(3)


def _frame_engine(tmp_path, monkeypatch, write):
    monkeypatch.setattr(recorder.RecordingEngine, 'cleanup_temp_dir', lambda *a: None)
    engine = recorder.RecordingEngine()
    engine._running = True; engine._capture_clock_start = time.perf_counter(); engine._pause_event.set()
    engine._temp_vid_path = str(tmp_path / 'v.mkv')
    engine._region = {'width': 8, 'height': 8}
    engine._capture_segments = [{'src_top': 0, 'src_left': 0, 'src_width': 8, 'src_height': 8,
                                 'dst_top': 0, 'dst_left': 0, 'dst_width': 8, 'dst_height': 8}]
    engine._ffmpeg_proc = SimpleNamespace(stdin=SimpleNamespace(write=write))
    class Capture:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def grab(self, region): return SimpleNamespace(raw=bytes(8 * 8 * 4))
    monkeypatch.setattr(recorder.mss, 'mss', Capture)
    monkeypatch.setattr(recorder, '_acquire_cursor_surface', lambda: (None,) * 5)
    return engine


def test_encoder_death_is_reported_during_recording(tmp_path, monkeypatch):
    def broken(_): raise BrokenPipeError()
    engine = _frame_engine(tmp_path, monkeypatch, broken)
    engine._frame_worker()
    events = engine.drain_runtime_events()
    assert [kind for kind, _ in events] == ['recording_interrupted']
    assert str(tmp_path) in events[0][1]


def test_nearly_full_drive_requests_one_stop(tmp_path, monkeypatch):
    frames = []
    engine = _frame_engine(tmp_path, monkeypatch, lambda raw: (frames.append(1), setattr(engine, '_running', len(frames) < 8)))
    monkeypatch.setattr(recorder, 'DISK_CHECK_SECONDS', 0.0)
    monkeypatch.setattr(recorder.shutil, 'disk_usage', lambda _: SimpleNamespace(free=1024))
    engine._frame_worker()
    assert [kind for kind, _ in engine.drain_runtime_events()] == ['recording_interrupted']
    assert not engine._capture_failed  # a normal Stop and save follows


def test_interrupted_recording_stops_the_take():
    owner = object.__new__(WWRecorderApp)
    stops, shown = [], []
    owner.engine = SimpleNamespace(drain_runtime_events=lambda: [('recording_interrupted', 'why')], is_recording=lambda: True)
    owner.tray = SimpleNamespace(showMessage=lambda *a: shown.append(a), icon=lambda: None)
    owner.pill = SimpleNamespace(_initiate_stop=lambda: stops.append(1))
    owner._poll_engine_events()
    assert stops == [1] and shown[0][1] == 'why'


def test_system_sleep_is_excluded_but_capture_stalls_are_not(monkeypatch):
    monkeypatch.setattr(recorder.RecordingEngine, 'cleanup_temp_dir', lambda *a: None)
    engine = recorder.RecordingEngine(); engine._capture_clock_start = 100.0
    base = engine._exclude_sleep(None, 110.0, 50.0)
    base = engine._exclude_sleep(base, 3710.0, 50.0 + 0.5)   # slept ~an hour
    assert engine._active_elapsed(3710.0) == pytest.approx(10.5)
    base = engine._exclude_sleep(base, 3770.0, 110.5)         # 60 s stall, awake
    assert engine._active_elapsed(3770.0) == pytest.approx(70.5)
    engine._pause_started_at = 3770.0                         # paused during sleep
    engine._exclude_sleep(base, 9999.0, 111.0)
    assert engine._active_elapsed(9999.0) == pytest.approx(70.5)
    assert engine._exclude_sleep(base, 1.0, None) is None


def test_device_popup_matches_annotator_and_never_takes_input(app):
    toast = annotation_tool.DeviceToast()
    toast.show_device('Microphone connected — Headset.', QPoint(400, 300))
    assert isinstance(toast, annotation_tool._ToastWidget) and toast.isVisible()
    flags = toast.windowFlags()
    assert flags & Qt.WindowType.WindowTransparentForInput
    assert flags & Qt.WindowType.WindowDoesNotAcceptFocus
    assert toast.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    assert toast.grab().toImage().pixelColor(toast.width() // 2, 3).name() == '#151923'
    area = QApplication.primaryScreen().availableGeometry()
    toast.show_device('Microphone connected — ' + 'Very long device name ' * 20, QPoint(400, 300))
    assert area.contains(toast.geometry())
    toast.show_device('Short', None, duration_ms=30)
    assert toast.width() < 300
    QTest.qWait(120)
    assert not toast.isVisible()
