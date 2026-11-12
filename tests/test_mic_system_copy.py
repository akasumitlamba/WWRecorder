"""Microphones that mix PC playback into their own signal must not cause echo."""
import struct
import time

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


# ── Laptop speakers heard by the built-in microphone (acoustic echo) ──────────

def _speechlike(rng, n, syllable=0.18):
    t = np.arange(n) / RATE
    phase = 2 * np.pi * np.cumsum(120 + 30 * np.sin(2 * np.pi * 0.4 * t)) / RATE
    voiced = sum(np.sin(k * phase) / k for k in range(1, 25))
    noise = np.convolve(rng.standard_normal(n), np.hanning(12) / 6, 'same')
    envelope = ((np.sin(2 * np.pi * t / (2 * syllable)) > -0.2)
                & (np.abs(np.sin(2 * np.pi * 0.23 * t)) > 0.25)).astype(float)
    envelope = np.convolve(envelope, np.hanning(960) / 480, 'same')
    return (0.6 * voiced + 0.4 * noise) * envelope


def _laptop(seconds=40, echo_gain=0.5, drift_ppm=0.0, delay=0.035):
    """System sound played by a small speaker, a reflective room, and a talking user."""
    rng = np.random.default_rng(3)
    n = int(seconds * RATE)
    t = np.arange(n) / RATE
    music = (np.sin(2 * np.pi * 196 * t) * 0.15 + np.sin(2 * np.pi * 294 * t + np.sin(3 * t)) * 0.1
             + np.convolve(rng.standard_normal(n), np.ones(5) / 5, 'same') * 0.05)
    music *= 0.5 + 0.5 * np.abs(np.sin(2 * np.pi * 2.1 * t))
    played = np.where((t // 10) % 2 == 0, music, 0.25 * _speechlike(rng, n, 0.15)) + 0.3 * music
    played[:2 * RATE] = 0
    played *= ~(((t - 12) % 16) < 4) | (t < 12)          # system sound pauses
    system = np.stack([played, played * 0.9], 1)
    speaker = system.mean(1)
    speaker = np.tanh(2.0 * (speaker - np.convolve(speaker, np.ones(200) / 200, 'same'))) / 2.0
    room = np.random.default_rng(99).standard_normal(int(0.25 * RATE))
    room *= 0.05 * np.exp(-23 * np.arange(len(room)) / RATE)
    room[0] += 1.0
    room[149] += 0.5
    room[355] -= 0.3
    size = 1 << int(np.ceil(np.log2(n + len(room))))
    echo = np.fft.irfft(np.fft.rfft(speaker, size) * np.fft.rfft(room, size), size)[:n] * echo_gain
    source = np.arange(n) - int(delay * RATE) - np.floor(np.arange(n) * drift_ppm * 1e-6).astype(np.int64)
    echo = np.where(source >= 0, echo[np.clip(source, 0, n - 1)], 0.0)
    voice = 0.3 * _speechlike(np.random.default_rng(13), n) * ((t % 23) > 9)
    mic = voice + echo + 2e-3 * rng.standard_normal(n)
    return system, np.stack([mic, mic], 1), voice, echo


def _clean(tmp_path, system, mic):
    _write(tmp_path / 'sys.wav', system)
    _write(tmp_path / 'mic.wav', mic)
    result = removal.remove_system_copy(str(tmp_path / 'mic.wav'), str(tmp_path / 'sys.wav'),
                                        str(tmp_path / 'clean.wav'))
    assert result == str(tmp_path / 'clean.wav')
    return np.asarray(removal.FloatWav(result).data[:, 0], np.float64)


def _smoothed(signal, width=4800):
    return np.convolve(signal ** 2, np.ones(width) / width, 'same')


def _scores(output, voice, echo):
    echo_power, voice_power = _smoothed(echo), _smoothed(voice)
    echo_only = (voice_power < 1e-8) & (echo_power > 1e-5)
    double_talk = (voice_power > 1e-4) & (echo_power > 1e-5)
    voice_alone = (voice_power > 1e-4) & (echo_power < 1e-9)
    error = output - voice
    removed = 10 * np.log10(np.sum(echo[echo_only] ** 2) / np.sum(error[echo_only] ** 2))
    return (removed, np.corrcoef(output[double_talk], voice[double_talk])[0, 1],
            np.corrcoef(output[voice_alone], voice[voice_alone])[0, 1], double_talk)


@pytest.mark.parametrize('echo_gain', [0.5, 0.1])
def test_laptop_speaker_echo_is_removed_and_speech_is_kept(tmp_path, echo_gain):
    system, mic, voice, echo = _laptop(echo_gain=echo_gain)
    output = _clean(tmp_path, system, mic)
    removed, talking, alone, double_talk = _scores(output, voice, echo)
    before = np.corrcoef(mic[double_talk, 0], voice[double_talk])[0, 1]
    assert removed > 12                    # echo while the user is silent
    assert talking > max(before, 0.97)     # talking over system sound gets clearer
    assert alone > 0.9995                  # speech without system sound is untouched


def test_echo_is_followed_when_device_clocks_drift(tmp_path):
    system, mic, voice, echo = _laptop(seconds=150, drift_ppm=40)  # 6 ms over the take
    removed, talking, *_ = _scores(_clean(tmp_path, system, mic), voice, echo)
    assert removed > 12 and talking > 0.95


def test_acoustic_tracking_measures_offset_around_the_model_lead():
    # Regression: the expected peak of a one-hop lead sat on the circular edge
    # and every other block jumped by a whole frame.
    rng = np.random.default_rng(1)
    signal = rng.standard_normal(removal.FRAME * 40)
    model = removal.ACOUSTIC
    first = (model.taps - 1) * removal.HOP
    for shift in (0, 37, -50):
        mic = np.roll(signal, model.lead + shift)[first:, None]
        ref = removal._stft(signal[:, None])
        mic_bins = removal._stft(mic)
        assert removal._track_offset(ref, mic_bins[:, :ref.shape[1] - model.taps + 1], model) == shift


def test_float_wav_accepts_extensible_float_header(tmp_path):
    samples = np.random.default_rng(2).standard_normal((1000, 2)).astype(np.float32)
    fmt = (struct.pack('<HHIIHH', 0xFFFE, 2, RATE, RATE * 8, 8, 32)
           + struct.pack('<HHI', 22, 32, 3) + struct.pack('<H', 3) + b'\x00\x00\x00\x00\x10\x00\x80\x00\x00\xaa\x00\x38\x9b\x71')
    body = b'WAVE' + b'fmt ' + struct.pack('<I', len(fmt)) + fmt + b'data' + struct.pack('<I', samples.nbytes)
    (tmp_path / 'ext.wav').write_bytes(b'RIFF' + struct.pack('<I', len(body) + samples.nbytes) + body
                                       + samples.tobytes())
    wav = removal.FloatWav(str(tmp_path / 'ext.wav'))
    assert (wav.channels, wav.rate, wav.frames) == (2, RATE, 1000)
    assert np.array_equal(wav.data, samples)


def test_recorder_resamples_system_track_when_device_rates_differ(tmp_path):
    import shutil
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        pytest.skip('Real encoder unavailable')
    from tests.windows_e2e.helpers.env import import_app
    recorder = import_app('recorder')
    system, mic, voice, echo = _laptop(seconds=30)
    # The microphone runs at 44.1 kHz; the speaker (and loopback) at 48 kHz.
    mic_rate = 44100
    positions = np.arange(int(len(mic) * mic_rate / RATE)) * RATE / mic_rate
    mic44 = np.stack([np.interp(positions, np.arange(len(mic)), mic[:, 0])] * 2, 1)
    _write(tmp_path / 'sys.wav', system)
    with open(tmp_path / 'mic.wav', 'wb') as handle:
        removal._write_header(handle, 2, mic_rate, mic44.astype(np.float32).nbytes)
        handle.write(mic44.astype(np.float32).tobytes())
    assert removal.remove_system_copy(str(tmp_path / 'mic.wav'), str(tmp_path / 'sys.wav'),
                                      str(tmp_path / 'x.wav')) is None   # needs one clock
    cleaned = recorder._remove_mic_system_copy(str(tmp_path / 'mic.wav'), str(tmp_path / 'sys.wav'), ffmpeg)
    assert cleaned == str(tmp_path / 'mic_clean.wav')
    output = np.asarray(removal.FloatWav(cleaned).data[:, 0], np.float64)
    assert len(output) == len(mic44)
    echo44 = np.interp(positions, np.arange(len(echo)), echo)
    voice44 = np.interp(positions, np.arange(len(voice)), voice)
    quiet = (np.convolve(voice44 ** 2, np.ones(4410) / 4410, 'same') < 1e-8) & \
            (np.convolve(echo44 ** 2, np.ones(4410) / 4410, 'same') > 1e-5)
    assert 10 * np.log10(np.sum(echo44[quiet] ** 2) / np.sum((output - voice44)[quiet] ** 2)) > 12
    for _ in range(20):   # the temporary 44.1 kHz system copy is removed
        if not (tmp_path / 'sys_ref.wav').exists():
            break
        time.sleep(0.1)
    assert not (tmp_path / 'sys_ref.wav').exists()
