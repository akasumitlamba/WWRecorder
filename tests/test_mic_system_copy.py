"""Microphones that mix PC playback into their own signal must not cause echo."""
import numpy as np
import pytest

import mic_loopback_removal as removal

RATE = 48000


def _write(path, samples):
    samples = np.asarray(samples, np.float32)
    with open(path, 'wb') as handle:
        removal._write_header(handle, samples.shape[1], RATE, samples.nbytes)
        handle.write(samples.tobytes())


def _signals(seconds=40, leak_gain=0.6, delay_samples=1790):
    rng = np.random.default_rng(7)
    n = int(RATE * seconds)
    t = np.arange(n) / RATE
    system = np.stack([np.sin(2 * np.pi * (220 + 110 * np.sin(0.3 * t)) * t) * 0.3,
                       np.sin(2 * np.pi * 330 * t) * 0.2], 1) + 0.1 * rng.standard_normal((n, 2))
    system *= np.clip(np.sin(2 * np.pi * 0.05 * t) + 0.3, 0, 1)[:, None]
    system[:3 * RATE] = 0
    voice = np.convolve(rng.standard_normal(n), np.hanning(40) / 20, 'same')
    voice *= (np.sin(2 * np.pi * 1.7 * t) > 0.3) * 0.4
    mono = system.mean(axis=1)
    leak = np.zeros(n)
    leak[delay_samples:] = leak_gain * np.convolve(mono, [0.6, 0.3, 0.1], 'same')[:-delay_samples]
    mic = np.stack([voice + leak + 1e-3 * rng.standard_normal(n)] * 2, 1)
    return system, mic, voice, leak, mono


def test_duplicated_system_sound_is_removed_and_voice_is_kept(tmp_path):
    system, mic, voice, leak, mono = _signals()
    _write(tmp_path / 'sys.wav', system)
    _write(tmp_path / 'mic.wav', mic)
    result = removal.remove_system_copy(str(tmp_path / 'mic.wav'), str(tmp_path / 'sys.wav'),
                                        str(tmp_path / 'clean.wav'))
    assert result == str(tmp_path / 'clean.wav')
    cleaned = removal.FloatWav(result)
    assert (cleaned.frames, cleaned.channels, cleaned.rate) == (len(mic), 2, RATE)
    output = np.asarray(cleaned.data[:, 0], np.float64)
    active = np.abs(mono) > 0.01
    reduction = 10 * np.log10(np.sum(leak[active] ** 2) / np.sum((output - voice)[active] ** 2))
    assert reduction > 12
    speaking = voice != 0
    assert np.corrcoef(output[speaking], voice[speaking])[0, 1] > 0.995
    # The original microphone recording is never modified.
    assert np.array_equal(removal.FloatWav(str(tmp_path / 'mic.wav')).data, mic.astype(np.float32))


@pytest.mark.parametrize('leak_gain', [0.0, 0.02])
def test_ordinary_microphone_is_left_untouched(tmp_path, leak_gain):
    system, mic, *_ = _signals(seconds=30, leak_gain=leak_gain)
    _write(tmp_path / 'sys.wav', system)
    _write(tmp_path / 'mic.wav', mic)
    assert removal.remove_system_copy(str(tmp_path / 'mic.wav'), str(tmp_path / 'sys.wav'),
                                      str(tmp_path / 'clean.wav')) is None
    assert not (tmp_path / 'clean.wav').exists()


def test_silent_system_track_and_mismatched_rates_are_skipped(tmp_path):
    _, mic, *_ = _signals(seconds=10)
    _write(tmp_path / 'mic.wav', mic)
    _write(tmp_path / 'sys.wav', np.zeros_like(mic))
    assert removal.remove_system_copy(str(tmp_path / 'mic.wav'), str(tmp_path / 'sys.wav'),
                                      str(tmp_path / 'clean.wav')) is None
    with open(tmp_path / 'other.wav', 'wb') as handle:
        removal._write_header(handle, 2, 44100, 0)
    assert removal.remove_system_copy(str(tmp_path / 'mic.wav'), str(tmp_path / 'other.wav'),
                                      str(tmp_path / 'clean.wav')) is None


def test_recorder_falls_back_to_original_microphone_on_any_failure(tmp_path):
    from tests.windows_e2e.helpers.env import import_app
    recorder = import_app('recorder')
    (tmp_path / 'mic.wav').write_bytes(b'not a wav file')
    (tmp_path / 'sys.wav').write_bytes(b'not a wav file')
    assert recorder._remove_mic_system_copy(str(tmp_path / 'mic.wav'), str(tmp_path / 'sys.wav')) is None
    assert not (tmp_path / 'mic_clean.wav').exists()
