"""Opening and saving long videos must not decode or re-encode the whole file."""
import shutil
import subprocess
import time
from pathlib import Path

import pytest


def _ffmpeg():
    path = shutil.which('ffmpeg') or str(Path(__file__).resolve().parents[1] / 'app/ffmpeg.exe')
    if not Path(path).is_file():
        pytest.skip('Real encoder unavailable')
    return path


@pytest.fixture
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope='module')
def long_video(tmp_path_factory):
    ffmpeg = _ffmpeg()
    path = tmp_path_factory.mktemp('long') / 'Recording.mkv'
    subprocess.run([ffmpeg, '-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc2=s=160x90:r=30:d=240',
                    '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '25', '-pix_fmt', 'yuv420p',
                    str(path)], check=True, timeout=300)
    return ffmpeg, path


def test_long_filmstrip_seeks_instead_of_decoding_every_frame(qapp, long_video, monkeypatch):
    ffmpeg, path = long_video
    import video_editor
    monkeypatch.setattr(video_editor, '_get_ffmpeg', lambda: ffmpeg)
    calls = []
    real_popen = subprocess.Popen

    def recording_popen(cmd, *args, **kwargs):
        calls.append(cmd)
        return real_popen(cmd, *args, **kwargs)
    monkeypatch.setattr(video_editor.subprocess, 'Popen', recording_popen)
    extractor = video_editor._ThumbnailExtractor(str(path), num_frames=40, thumb_height=56)
    received = []
    extractor.thumbnails_ready.connect(lambda images, start, fps: received.append((images, start, fps)))
    errors = []
    extractor.error.connect(errors.append)
    started = time.monotonic()
    extractor.run()
    assert not errors and received
    images, start, fps = received[0]
    assert len(images) == 40 and all(not image.isNull() for image in images)
    assert start == 0 and abs(fps - 40 / 240) < 0.01
    decodes = [cmd for cmd in calls if '-frames:v' in cmd]
    # One single-frame keyframe decode per thumbnail; never an fps= pass over the file.
    assert len(decodes) == 40 and all(cmd[cmd.index('-frames:v') + 1] == '1' for cmd in decodes)
    assert not any('fps=' in ' '.join(cmd) for cmd in calls)
    assert time.monotonic() - started < 60


def test_short_filmstrip_keeps_dense_extraction(qapp, long_video, monkeypatch, tmp_path):
    ffmpeg, path = long_video
    import video_editor
    monkeypatch.setattr(video_editor, '_get_ffmpeg', lambda: ffmpeg)
    extractor = video_editor._ThumbnailExtractor(str(path), thumb_height=56, start_sec=10, end_sec=14,
                                                 target_fps=5)
    received = []
    extractor.thumbnails_ready.connect(lambda images, start, fps: received.append(images))
    extractor.run()
    assert received and 18 <= len(received[0]) <= 21


def _run_export(video_editor, cmd, output, smart):
    worker = video_editor._ExportWorker(cmd, str(output), duration_ms=240000, smart_cut=smart)
    done, errors = [], []
    worker.export_finished.connect(done.append)
    worker.error.connect(errors.append)
    worker.run()
    return done, errors


def test_save_copies_unchanged_video_for_trim_and_delete(qapp, long_video, monkeypatch, tmp_path):
    ffmpeg, path = long_video
    import video_editor
    monkeypatch.setattr(video_editor, '_get_ffmpeg', lambda: ffmpeg)
    output = tmp_path / 'edited.mkv'
    smart = {'source': str(path), 'keep': [(10.0, 100.0), (130.0, 200.0)], 'mute': [],
             'include_audio': True, 'workdir': str(tmp_path / '.wwr_temp')}
    # The full re-encode command must not run when the fast path succeeds.
    done, errors = _run_export(video_editor, [ffmpeg, '-invalid-option', str(output)], output, smart)
    assert done == [str(output)] and not errors
    frames = subprocess.run([ffmpeg, '-v', 'error', '-i', str(output), '-map', '0:v', '-c', 'copy',
                             '-f', 'framecrc', '-'], capture_output=True, text=True).stdout
    assert sum(1 for line in frames.splitlines() if line and not line.startswith('#')) == (90 + 70) * 30
    assert not list((tmp_path / '.wwr_temp').glob('wwr_edit_*'))


def test_save_falls_back_to_full_reencode_when_copy_is_unsafe(qapp, long_video, monkeypatch, tmp_path):
    ffmpeg, path = long_video
    import video_editor
    monkeypatch.setattr(video_editor, '_get_ffmpeg', lambda: ffmpeg)
    output = tmp_path / 'edited.mp4'  # unsupported by the copy path
    cmd = [ffmpeg, '-y', '-ss', '10', '-to', '12', '-i', str(path), '-c:v', 'libx264', '-preset',
           'veryfast', '-crf', '25', str(output)]
    smart = {'source': str(path), 'keep': [(10.0, 12.0)], 'mute': [], 'include_audio': True,
             'workdir': str(tmp_path / '.wwr_temp')}
    done, errors = _run_export(video_editor, cmd, output, smart)
    assert done == [str(output)] and not errors and output.stat().st_size > 0
