"""Decode actual editor exports to verify audible/silent sections and cut timing."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pytest
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QObject, pyqtSignal
import video_editor as ve

_APP = None


def test_mute_ranges_clip_merge_and_offset():
    regions = [SimpleNamespace(start_ms=a, end_ms=b) for a,b in
               [(0, 1500), (1400, 2500), (4000, 9000), (3200, 3100)]]
    filters = ve._mute_audio_filters(regions, 1000, 5000)
    assert filters == ["volume=0:enable='gte(t,0.000)*lt(t,1.500)'",
                       "volume=0:enable='gte(t,3.000)*lt(t,4.000)'"]


@pytest.mark.parametrize('size', ['32x32', '33x33'])
@pytest.mark.parametrize('cut', [False, True, 'middle'])
def test_actual_editor_export_silences_source_times_before_delete_retiming(tmp_path, monkeypatch, cut, size):
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        bundled = Path(__file__).resolve().parents[1] / 'app/ffmpeg.exe'
        if not bundled.exists():
            pytest.skip('FFmpeg is required for decoded audio export verification')
        ffmpeg = str(bundled)
    source = tmp_path / 'source.mkv'
    subprocess.run([ffmpeg, '-v', 'error', '-y', '-f', 'lavfi', '-i', f'testsrc=size={size}:rate=30:duration=4',
                    '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=4',
                    '-c:v', 'libx264', '-pix_fmt', 'yuv444p', '-c:a', 'pcm_s16le', str(source)], check=True, timeout=20)
    global _APP
    _APP = QApplication.instance() or QApplication([])
    app = _APP
    window = ve.VideoPlayerWindow(str(source))
    captured = []
    class Worker(QObject):
        progress = pyqtSignal(int)
        export_finished = pyqtSignal(str)
        error = pyqtSignal(str)
        def __init__(self, cmd, *args, **kwargs):
            super().__init__()
            captured.append(cmd)
        def start(self): pass
        def isRunning(self): return False
    monkeypatch.setattr(ve, '_ExportWorker', Worker)
    monkeypatch.setattr(ve, '_get_ffmpeg', lambda: ffmpeg)
    monkeypatch.setattr(window._player, 'duration', lambda: 4000)
    window._chk_trim.setChecked(True)
    window._timeline.set_duration(4000)
    window._timeline._trim_start_ms = 1000
    window._timeline._trim_end_ms = 4000
    window._mute_regions = [ve._DeleteRegionItem(2000, 3000)]
    if cut:
        window._delete_regions = [ve._DeleteRegionItem(1500, 2000) if cut == 'middle' else ve._DeleteRegionItem(1000, 1500)]
    output = tmp_path / 'edited.mp4'
    try:
        window._save_edited(str(output))
        assert captured
        exported = subprocess.run(captured[0], timeout=30, capture_output=True)
        assert exported.returncode == 0, exported.stderr.decode(errors="replace")
        actual = Path(captured[0][-1])
        from PIL import Image
        from io import BytesIO
        dimensions = subprocess.run([ffmpeg,'-v','error','-i',str(actual),'-frames:v','1','-f','image2pipe','-c:v','png','-'],capture_output=True,check=True,timeout=20).stdout
        assert Image.open(BytesIO(dimensions)).size == ((34,34) if size=='33x33' else (32,32))
        raw = subprocess.run([ffmpeg, '-v', 'error', '-i', str(actual), '-map', '0:a:0',
                              '-f', 'f32le', '-ac', '1', '-ar', '48000', '-'],
                             check=True, timeout=20, capture_output=True).stdout
        samples = np.frombuffer(raw, dtype='<f4')
        shift = .5 if cut else 0
        def rms(start, end):
            section = samples[int(start*48000):int(end*48000)]
            assert len(section) > 100
            return np.sqrt(np.mean(section ** 2))
        assert rms(.1, .3) > .03
        assert rms(1.2-shift, 1.8-shift) < .002
        assert rms(2.2-shift, 2.7-shift) > .03
        assert abs(len(samples)/48000 - (3-shift)) < .15
    finally:
        window._export_worker = None
        window.close()
        app.processEvents()
