"""Remove a copy of the system-audio track that leaked into the microphone track.

Some USB podcast microphones double as the PC's playback device and mix the
computer's playback back into their own capture signal (hardware "loopback" or
monitor mix). WWRecorder also records that playback separately through WASAPI
loopback, so the final mix would contain the same system sound twice, offset by
the device latency: an audible echo.

This module runs after capture, off the GUI thread, on the session WAV files.
It never modifies the original microphone WAV. It first probes whether the
microphone track contains a strong, linearly predictable copy of the system
track. Only then does it write a cleaned microphone WAV, using a block-wise
frequency-domain Wiener estimate of the leak path driven by the system track.
Ordinary microphones, which carry no such copy, are left untouched.
"""
import os
import struct

import numpy as np

FRAME = 2048                 # STFT frame (about 43 ms at 48 kHz)
HOP = FRAME // 2
BLOCK_FRAMES = 192           # processing block (about 4 s at 48 kHz)
FORGET = 0.8                 # pooled leak statistics fade over about 20 s
REGULARIZE = 1e-2             # relative diagonal loading of the leak solve
PATH_TAPS = 256              # leak impulse response after alignment (about 5 ms)
MAX_LAG_SECONDS = 0.75       # search range for the mic/system offset
PROBE_SECONDS = 6.0
MAX_PROBES = 8
MIN_LEAK_SHARE = 0.05        # leak must explain >= 5% of mic energy (about -13 dB)
MIN_PREDICTION = 0.6         # and its held-out prediction must be mostly real
_WINDOW = np.sqrt(np.hanning(FRAME + 1)[:FRAME]).astype(np.float64)


class FloatWav:
    """Memory-mapped view of a 32-bit IEEE float WAV written by the recorder."""

    def __init__(self, path):
        with open(path, 'rb') as handle:
            header = handle.read(12)
            if len(header) < 12 or header[:4] != b'RIFF' or header[8:12] != b'WAVE':
                raise ValueError('not a RIFF/WAVE file')
            fmt = None
            offset = 12
            while True:
                chunk = handle.read(8)
                if len(chunk) < 8:
                    raise ValueError('WAV data chunk not found')
                name, size = struct.unpack('<4sI', chunk)
                offset += 8
                if name == b'fmt ':
                    fmt = struct.unpack('<HHIIHH', handle.read(16))
                    handle.seek(size - 16, os.SEEK_CUR)
                elif name == b'data':
                    data_offset = offset
                    break
                else:
                    handle.seek(size + (size & 1), os.SEEK_CUR)
                offset += size + (size & 1)
        if fmt is None or fmt[0] != 3 or fmt[5] != 32:
            raise ValueError('WAV is not 32-bit float')
        self.channels, self.rate = int(fmt[1]), int(fmt[2])
        # The recorder clamps the header size at 4 GB; the file length is
        # authoritative for very long takes.
        frames = (os.path.getsize(path) - data_offset) // (4 * self.channels)
        self.frames = max(0, frames)
        self.data = (np.memmap(path, dtype='<f4', mode='r', offset=data_offset,
                               shape=(self.frames, self.channels))
                     if self.frames else np.zeros((0, self.channels), np.float32))

    def read(self, start, count):
        """Return frames [start, start+count) as float64, zero-padded outside."""
        out = np.zeros((count, self.channels), np.float64)
        lo, hi = max(0, start), min(self.frames, start + count)
        if hi > lo:
            out[lo - start:hi - start] = self.data[lo:hi]
        return out


def _write_header(handle, channels, rate, data_bytes):
    data_bytes = min(data_bytes, 0xFFFFFFFF - 36)
    handle.seek(0)
    handle.write(struct.pack('<4sI4s', b'RIFF', 36 + data_bytes, b'WAVE'))
    handle.write(struct.pack('<4sIHHIIHH', b'fmt ', 16, 3, channels, rate,
                             rate * channels * 4, channels * 4, 32))
    handle.write(struct.pack('<4sI', b'data', data_bytes))


def _mono(block):
    return block.mean(axis=1) if block.ndim == 2 else block


def _gcc_phat_lag(reference, target, max_lag):
    """Lag (samples) by which target trails reference, and peak sharpness."""
    n = 1
    while n < len(reference) + len(target):
        n *= 2
    spectrum = np.fft.rfft(target, n) * np.conj(np.fft.rfft(reference, n))
    spectrum /= np.maximum(np.abs(spectrum), 1e-12)
    correlation = np.fft.irfft(spectrum, n)
    window = np.concatenate((correlation[-max_lag:], correlation[:max_lag + 1]))
    peak = int(np.argmax(window))
    sharpness = float(window[peak] / (np.mean(np.abs(window)) + 1e-12))
    return peak - max_lag, sharpness


def _stft(signal):
    """Frames of a (samples, channels) signal: (frames, bins, channels)."""
    count = 1 + max(0, (len(signal) - FRAME) // HOP)
    index = np.arange(FRAME)[None, :] + HOP * np.arange(count)[:, None]
    frames = signal[index] * _WINDOW[None, :, None]
    return np.fft.rfft(frames, axis=1)


def _leak_stats(ref_spec, mic_spec):
    """Per-bin Gram and cross-spectral sums for the leak-path least squares."""
    conj_ref = np.conj(ref_spec)
    gram = np.einsum('tfi,tfj->fij', conj_ref, ref_spec)
    cross = np.einsum('tfi,tfj->fij', conj_ref, mic_spec)
    return gram, cross


def _solve_leak(gram, cross):
    """Leak path H (bins, refs, mics) with mic ~= ref @ H.

    The physical/digital path from the playback mix into a microphone is short
    after the common delay is removed, so the per-bin estimate is projected
    onto a short impulse response. That averages estimation noise from speech
    across frequency instead of trusting each bin independently.
    """
    refs = gram.shape[1]
    load = np.trace(gram, axis1=1, axis2=2).real / refs
    # Bins where the system track was nearly silent must not get large gains:
    # regularize against the average power as well as the bin's own.
    floor = REGULARIZE * (load + (float(load.mean()) if load.size else 0.0)) + 1e-20
    h = np.linalg.solve(gram + floor[:, None, None] * np.eye(refs)[None], cross)
    impulse = np.fft.irfft(h, FRAME, axis=0)
    keep = np.zeros(FRAME)
    keep[:PATH_TAPS] = 1.0
    keep[-PATH_TAPS // 4:] = 1.0     # small negative residual offsets
    impulse *= keep[:, None, None]
    return np.fft.rfft(impulse, axis=0)


def _leak_filter(ref_spec, mic_spec):
    return _solve_leak(*_leak_stats(ref_spec, mic_spec))


def _residual(ref_spec, mic_spec, h):
    return mic_spec - np.einsum('tfi,fij->tfj', ref_spec, h)


def _reference_layout(ref, starts, length):
    """True when every sampled system window is effectively mono."""
    if ref.channels == 1:
        return True
    for start in starts:
        block = ref.read(int(start), length)
        if not np.allclose(block[:, 0], block[:, 1:].T, atol=1e-6):
            return False
    return True


def _reference(block, mono):
    """System reference channels: one channel for duplicated mono audio."""
    if mono:
        return block[:, :1]
    if block.shape[1] > 2:
        # Surround mixes reach a stereo microphone loopback as front channels.
        return block[:, :2]
    return block


def probe_leak(mic, ref, lag, mono=False):
    """Held-out leak measurement on the loudest system-audio windows.

    The leak path is fitted on the first half of each window and used to
    predict the second half. Returns (share, accuracy): the fraction of the
    microphone energy that the prediction explains, and how much of the
    predicted energy is actually present. Speech lowers the share but does not
    make an unrelated signal predictable, so accuracy stays near zero for an
    ordinary microphone.
    """
    probe = int(PROBE_SECONDS * mic.rate)
    usable = max(0, min(mic.frames, ref.frames + lag) - probe)
    if usable <= 0:
        return 0.0, 0.0
    starts = np.linspace(0, usable, num=MAX_PROBES * 4, dtype=np.int64)
    scored = []
    for start in starts:
        sys_block = ref.read(int(start) - lag, probe)
        scored.append((float(np.mean(sys_block ** 2)), int(start)))
    scored = [item for item in sorted(scored, reverse=True) if item[0] > 1e-8][:MAX_PROBES]
    pairs = []
    gram = cross = None
    for _, start in scored:
        mic_spec = _stft(mic.read(start, probe))
        ref_spec = _stft(_reference(ref.read(start - lag, probe), mono))
        half = len(mic_spec) // 2
        g, c = _leak_stats(ref_spec[:half], mic_spec[:half])
        gram, cross = (g, c) if gram is None else (gram + g, cross + c)
        pairs.append((ref_spec[half:], mic_spec[half:]))
    if gram is None:
        return 0.0, 0.0
    h = _solve_leak(gram, cross)
    mic_energy = predicted_energy = explained = 0.0
    for ref_held, held in pairs:
        predicted = np.einsum('tfi,fij->tfj', ref_held, h)
        mic_energy += float(np.sum(np.abs(held) ** 2))
        predicted_energy += float(np.sum(np.abs(predicted) ** 2))
        explained += float(np.sum((np.conj(predicted) * held).real))
    if mic_energy <= 0 or predicted_energy <= 0:
        return 0.0, 0.0
    return max(0.0, explained / mic_energy), max(0.0, explained / predicted_energy)


def estimate_lag(mic, ref):
    """Common offset between the leaked copy and the system track, or None."""
    max_lag = int(MAX_LAG_SECONDS * mic.rate)
    window = int(PROBE_SECONDS * mic.rate)
    total = min(mic.frames, ref.frames)
    if total < window:
        window = total
    if window < FRAME * 4:
        return None
    starts = np.linspace(0, total - window, num=MAX_PROBES * 4, dtype=np.int64)
    energies = sorted(((float(np.mean(ref.read(int(s), window) ** 2)), int(s)) for s in starts),
                      reverse=True)
    lags = []
    for energy, start in energies[:MAX_PROBES]:
        if energy <= 1e-8:
            continue
        lag, sharpness = _gcc_phat_lag(_mono(ref.read(start, window)),
                                       _mono(mic.read(start, window)), max_lag)
        if sharpness >= 8.0:
            lags.append(lag)
    active = sum(1 for energy, _ in energies[:MAX_PROBES] if energy > 1e-8)
    if not lags or len(lags) < min(2, active):
        return None
    lags = np.asarray(lags)
    median = int(np.median(lags))
    agreeing = np.sum(np.abs(lags - median) <= max(2, mic.rate // 1000))
    if agreeing < max(1, (len(lags) + 1) // 2):
        return None
    return median


def remove_system_copy(mic_path, sys_path, out_path, cancelled=None):
    """Write a cleaned microphone WAV and return its path, or None if unneeded.

    Returns None when the files are incompatible, the system track is silent,
    or the microphone does not contain a clear copy of the system sound.
    """
    mic, ref = FloatWav(mic_path), FloatWav(sys_path)
    if mic.rate != ref.rate or mic.frames < FRAME * 4 or ref.frames < FRAME * 4:
        return None
    lag = estimate_lag(mic, ref)
    if lag is None:
        return None
    window = int(PROBE_SECONDS * mic.rate)
    samples = np.linspace(0, max(0, ref.frames - window), num=MAX_PROBES, dtype=np.int64)
    mono = _reference_layout(ref, samples, min(window, ref.frames))
    share, accuracy = probe_leak(mic, ref, lag, mono)
    if share < MIN_LEAK_SHARE or accuracy < MIN_PREDICTION:
        return None

    channels = mic.channels
    block_samples = BLOCK_FRAMES * HOP
    total = mic.frames
    written = 0
    tail = np.zeros((HOP, channels), np.float64)
    pooled = None
    with open(out_path, 'wb') as handle:
        _write_header(handle, channels, mic.rate, 0)
        # Analysis starts HOP before 0 so the first output sample is fully covered.
        position = -HOP
        while position < total:
            if cancelled is not None and cancelled():
                raise RuntimeError('Microphone cleanup was cancelled.')
            span = block_samples + FRAME - HOP
            mic_block = mic.read(position, span)
            ref_block = ref.read(position - lag, span)
            identical_mic = channels > 1 and np.allclose(mic_block[:, 0], mic_block[:, 1:].T, atol=1e-7)
            mic_used = mic_block[:, :1] if identical_mic else mic_block
            mic_spec = _stft(mic_used)
            ref_spec = _stft(_reference(ref_block, mono))
            g, c = _leak_stats(ref_spec, mic_spec)
            if pooled is not None and pooled[1].shape == c.shape:
                g, c = g + FORGET * pooled[0], c + FORGET * pooled[1]
            pooled = (g, c)
            h = _solve_leak(g, c)
            residual = _residual(ref_spec, mic_spec, h)
            # Never make a block worse (for example a block of pure speech).
            if np.sum(np.abs(residual) ** 2) > np.sum(np.abs(mic_spec) ** 2):
                residual = mic_spec
            frames = np.fft.irfft(residual, FRAME, axis=1) * _WINDOW[None, :, None]
            out = np.zeros((HOP * (len(frames) + 1), frames.shape[2]), np.float64)
            for index in range(len(frames)):
                out[index * HOP:index * HOP + FRAME] += frames[index]
            if tail.shape[1] == out.shape[1]:
                out[:HOP] += tail
            else:  # mic channels changed between identical and distinct
                out[:HOP] += tail.mean(axis=1, keepdims=True) if out.shape[1] == 1 else tail[:, :1]
            tail = out[block_samples:block_samples + HOP].copy()
            ready = out[:block_samples]
            # Drop the leading half-frame that precedes sample 0.
            if position < 0:
                ready = ready[-position:]
            begin = max(position, 0)
            ready = ready[:max(0, total - begin)]
            if identical_mic:
                ready = np.repeat(ready, channels, axis=1)
            handle.write(np.ascontiguousarray(ready, dtype='<f4').tobytes())
            written += len(ready)
            position += block_samples
        _write_header(handle, channels, mic.rate, written * channels * 4)
    return out_path
