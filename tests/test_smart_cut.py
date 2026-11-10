"""Fast trim/delete saving must keep every remaining frame and stay in sync."""
import re
import shutil
import subprocess
from fractions import Fraction
from pathlib import Path

import numpy as np
import pytest

import smart_cut

W, H, FRAMES, RATE = 160, 96, 600, 48000
FLASHES = [45, 200, 333, 480]


def _ffmpeg():
    path = shutil.which('ffmpeg') or str(Path(__file__).resolve().parents[1] / 'app/ffmpeg.exe')
    if not Path(path).is_file():
        pytest.skip('Real encoder unavailable')
    return path


def _frame(index):
    frame = np.zeros((H, W, 4), np.uint8)
    frame[..., 3] = 255
    for bit in range(10):
        if (index >> bit) & 1:
            frame[:48, bit * 16:(bit + 1) * 16, :3] = 255
    frame[56:, :, :3] = 255 if index in FLASHES else (index * 7) % 60
    return frame


@pytest.fixture(scope='module')
def recording(tmp_path_factory):
    """A source made exactly like a WWRecorder take: live x264 + Opus MKV."""
    ffmpeg = _ffmpeg()
    folder = tmp_path_factory.mktemp('smartcut')
    live = folder / 'live.mkv'
    process = subprocess.Popen([ffmpeg, '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'bgra',
                                '-s', f'{W}x{H}', '-r', '30', '-i', '-', *smart_cut.ENCODE_ARGS, str(live)],
                               stdin=subprocess.PIPE)
    for index in range(FRAMES):
        process.stdin.write(_frame(index).tobytes())
    process.stdin.close()
    assert process.wait(timeout=120) == 0
    audio = np.zeros(int(FRAMES / 30 * RATE), np.float32)
    for index in FLASHES:
        start = int(index / 30 * RATE)
        audio[start:start + 1440] = 0.5 * np.sin(2 * np.pi * 1000 * np.arange(1440) / RATE)
    raw = folder / 'beeps.f32'
    audio.astype('<f4').tofile(raw)
    source = folder / 'Recording.mkv'
    subprocess.run([ffmpeg, '-v', 'error', '-y', '-i', str(live), '-f', 'f32le', '-ar', str(RATE),
                    '-ac', '1', '-i', str(raw), '-map', '0:v', '-map', '1:a', '-c:v', 'copy',
                    '-c:a', 'libopus', '-b:a', '112k', '-t', str(FRAMES / 30), str(source)],
                   check=True, timeout=120)
    return ffmpeg, source


def _decode(ffmpeg, path):
    result = subprocess.run([ffmpeg, '-hide_banner', '-i', str(path), '-map', '0:v', '-vf', 'showinfo',
                             '-f', 'rawvideo', '-pix_fmt', 'gray', '-'], capture_output=True, timeout=120)
    frames = np.frombuffer(result.stdout, np.uint8).reshape(-1, H, W)
    indices = [sum(1 << bit for bit in range(10) if frames[k, :48, bit * 16 + 3:(bit + 1) * 16 - 3].mean() > 128)
               for k in range(len(frames))]
    times = [float(x) for x in re.findall(r'pts_time:([-\d.]+)', result.stderr.decode(errors='replace'))]
    flashes = [times[k] for k in range(len(frames))
               if frames[k, 60:].mean() > 180 and (k == 0 or frames[k - 1, 60:].mean() <= 180)]
    audio = np.frombuffer(subprocess.run(
        [ffmpeg, '-v', 'error', '-i', str(path), '-map', '0:a', '-af', 'aresample=async=1:first_pts=0',
         '-f', 'f32le', '-ac', '1', '-ar', str(RATE), '-'], capture_output=True, timeout=120).stdout, '<f4')
    loud = np.abs(audio) > 0.1
    onsets = np.flatnonzero(loud & ~np.r_[False, loud[:-1]]) / RATE
    beeps = [x for i, x in enumerate(onsets) if i == 0 or x - onsets[i - 1] > 0.2]
    return indices, flashes, beeps


def _first_pts(ffmpeg, path):
    out = subprocess.run([ffmpeg, '-v', 'error', '-i', str(path), '-map', '0:v', '-c', 'copy',
                          '-f', 'framecrc', '-'], capture_output=True, text=True, timeout=60).stdout
    return int(next(l for l in out.splitlines() if not l.startswith('#')).split(',')[2]) / 1000


@pytest.mark.parametrize('keep,mute', [
    ([(0.2, 1.0), (1.5, 3.0), (3.1, 3.3), (5.0, 8.9), (8.95, 9.3), (10.0, 19.99)], [(6.0, 7.0)]),
    ([(0.0, 20.0)], [(1.0, 2.0)]),
    ([(2.0, 8.3335)], []),
])
def test_smart_cut_keeps_exact_frames_and_audio_alignment(recording, tmp_path, keep, mute):
    ffmpeg, source = recording
    output = tmp_path / 'edited.mkv'
    smart_cut.SmartCutter(ffmpeg, str(source), str(output), workdir=str(tmp_path)).export(keep, mute)
    offset = _first_pts(ffmpeg, source)
    ranges = smart_cut.keep_frame_ranges([(a - offset, b - offset) for a, b in keep], Fraction(30), FRAMES)
    expected = [i for a, b in ranges for i in range(a, b)]
    indices, flashes, beeps = _decode(ffmpeg, output)
    assert indices == expected  # nothing deleted survives, nothing kept is lost
    audible = [flash for flash, frame in zip(flashes, [i for i in expected if i in FLASHES])
               if not any(a <= (frame / 30) < b for a, b in mute)]
    assert len(beeps) == len(audible)
    for flash, beep in zip(audible, beeps):
        assert abs(flash - beep) < 0.004
    assert not list(tmp_path.glob('wwr_edit_*'))


def test_video_from_another_encoder_requires_full_reencode(recording, tmp_path):
    ffmpeg, source = recording
    other = tmp_path / 'other.mkv'
    subprocess.run([ffmpeg, '-v', 'error', '-y', '-i', str(source), '-c:v', 'libx264', '-preset', 'fast',
                    '-crf', '23', '-c:a', 'copy', str(other)], check=True, timeout=120)
    output = tmp_path / 'edited.mkv'
    with pytest.raises(smart_cut.SmartCutUnavailable):
        smart_cut.SmartCutter(ffmpeg, str(other), str(output), workdir=str(tmp_path)).export([(2.0, 5.0)])
    assert not output.exists()


def test_plan_copies_only_whole_gops_inside_kept_ranges():
    keyframes = [0, 250, 500, 600]
    pieces = smart_cut.plan_pieces([(10, 300), (310, 320), (450, 750)], keyframes, 750)
    assert pieces == [('encode', 10, 300), ('encode', 310, 320),
                      ('encode', 450, 500), ('copy', 500, 750)]
    assert smart_cut.plan_pieces([(0, 750)], keyframes, 750) == [('copy', 0, 750)]
    assert smart_cut.plan_pieces([(0, 520)], keyframes, 750) == [('copy', 0, 500), ('encode', 500, 520)]
