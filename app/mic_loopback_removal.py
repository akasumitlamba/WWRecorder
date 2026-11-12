"""Remove system audio that the microphone picked up a second time.

WWRecorder records PC playback directly (WASAPI loopback) and records the
microphone separately. When the microphone also hears that playback, the final
mix contains the same system sound twice, offset by the device and room delay:
an audible echo. Two cases are handled:

* direct: a USB podcast microphone that mixes playback into its own capture
  signal (hardware monitor mix). The copy is short and almost exact.
* acoustic: laptop or desk speakers heard by a built-in or nearby microphone.
  The copy is coloured by the speaker, smeared by room reflections for a few
  hundred milliseconds, slightly distorted, and can drift as the two device
  clocks differ.

This module runs after capture, off the GUI thread, on the session WAV files.
It never modifies the original microphone WAV. It first measures whether the
microphone contains a clear, predictable copy of the system track; ordinary
microphones that do not hear the playback are left untouched. Only then does
it write a cleaned microphone WAV, estimated block by block in the frequency
domain from the system track. For acoustic echo a residual stage additionally
attenuates the echo that a linear model cannot predict, but only where the
microphone holds little besides that echo, so speech is kept.
"""
import os
import struct

import numpy as np

FRAME = 2048                 # STFT frame (about 43 ms at 48 kHz)
HOP = FRAME // 2
BLOCK_FRAMES = 192           # processing block (about 4 s at 48 kHz)
FORGET = 0.8                 # pooled leak statistics fade over about 20 s
REGULARIZE = 1e-2            # relative diagonal loading of the leak solve
PATH_TAPS = 256              # direct leak impulse response after alignment (about 5 ms)
ECHO_FRAMES = 12             # acoustic model: room echo over 12 hops (about 0.25 s past the lead)
ECHO_LEAD = HOP              # acoustic model starts one hop before the measured delay
MAX_LAG_SECONDS = 0.75       # search range for the mic/system offset
PROBE_SECONDS = 6.0
MAX_PROBES = 8
TRACK_MAX_SECONDS = 0.012     # larger per-block jumps are treated as spurious
MAX_DRIFT = 300e-6           # device clocks differ by far less than 300 ppm
MIN_LEAK_SHARE = 0.05        # leak must explain >= 5% of mic energy (about -13 dB)
MIN_PREDICTION = 0.6         # and its held-out prediction must be mostly real
ACOUSTIC_MEAN_SHARE = 1e-3   # acoustic solve: share of the all-bin average in the floor
ROBUST_ECHO_SHARE = 0.3      # robust weights: echo power counted as residual
RES_QUANTILE = 0.2           # echo-only frames used to measure the non-linear leftover
RES_OVER = 4.0               # residual echo over-estimation
RES_FLOOR = 0.1              # residual stage attenuates at most 20 dB
RES_MAX_LEFTOVER = 0.3       # leftover never assumed above -5 dB of the predicted echo
_WINDOW = np.sqrt(np.hanning(FRAME + 1)[:FRAME]).astype(np.float64)
_WINDOW32 = _WINDOW.astype(np.float32)


class _Model:
    """Leak model: frame taps, alignment lead and stages for one coupling type."""

    def __init__(self, name, taps, lead, project, suppress, track_step, forget, robust, warp):
        self.name, self.taps, self.lead = name, taps, lead
        self.project, self.suppress, self.track_step = project, suppress, track_step
        self.forget, self.robust, self.warp = forget, robust, warp


DIRECT = _Model('direct', 1, 0, True, False, 0.001, FORGET, False, False)
# Room echo is estimated with cells weighted towards those without speech,
# so talking over system sound does not bias the echo path.
# The system track follows the fitted clock drift with sub-sample precision so
# the echo path stays fixed for the estimator; track_step is the jump size
# (an audio glitch) that re-aligns it.
ACOUSTIC = _Model('acoustic', ECHO_FRAMES, ECHO_LEAD, False, True, 0.002, FORGET, True, True)


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
                    body = handle.read(size)
                    fmt = list(struct.unpack('<HHIIHH', body[:16]))
                    if fmt[0] == 0xFFFE and len(body) >= 26:
                        # WAVE_FORMAT_EXTENSIBLE: the sub-format GUID starts at byte 24.
                        fmt[0] = struct.unpack('<H', body[24:26])[0]
                    if size & 1:
                        handle.seek(1, os.SEEK_CUR)
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
    """Bin-major frames of a (samples, channels) signal: (bins, frames, channels)."""
    signal = np.asarray(signal, np.float32)
    count = 1 + max(0, (len(signal) - FRAME) // HOP)
    index = np.arange(FRAME)[None, :] + HOP * np.arange(count)[:, None]
    frames = signal[index] * _WINDOW32[None, :, None]
    return np.ascontiguousarray(np.fft.rfft(frames, axis=1).transpose(1, 0, 2))


def _istft_add(spec):
    """Overlap-add synthesis of bin-major frames: (HOP * (frames + 1), channels)."""
    frames = np.fft.irfft(spec.transpose(1, 0, 2), FRAME, axis=1) * _WINDOW[None, :, None]
    out = np.zeros((HOP * (len(frames) + 1), frames.shape[2]), np.float64)
    for index in range(len(frames)):
        out[index * HOP:index * HOP + FRAME] += frames[index]
    return out


def _read_reference(ref, start, count, lag, model, mono):
    """System spectrum for mic samples [start, start+count), with taps-1 earlier frames."""
    extra = (model.taps - 1) * HOP
    block = ref.read(start - (lag - model.lead) - extra, count + extra)
    return _stft(_reference(block, mono))


def _regressors(ref_bins, count, taps):
    """Current and taps-1 earlier reference frames: (bins, count, refs * taps).

    ref_bins holds taps-1 extra leading frames. Regressor k*refs + i is
    reference channel i delayed by k frames.
    """
    if taps == 1:
        return ref_bins[:, :count]
    first = taps - 1
    return np.concatenate([ref_bins[:, first - k:first - k + count] for k in range(taps)], axis=2)


def _warped_reference(ref, start, count, delay, model, mono):
    """System spectrum aligned to a continuously drifting delay.

    delay(sample) gives the exact (fractional) mic-minus-system delay at a mic
    sample. The block is read at the nearest whole-sample delay of its centre;
    each frame then gets the remaining sub-sample delay as a phase shift, which
    is exact for the tiny within-frame drift of two device clocks.
    """
    base = int(round(delay(start + count / 2.0)))
    spec = _read_reference(ref, start, count, base, model, mono)
    extra = (model.taps - 1) * HOP
    centres = start - extra + HOP * np.arange(spec.shape[1]) + FRAME / 2.0
    fraction = np.asarray([delay(c) for c in centres]) - base
    bins = np.arange(spec.shape[0])[:, None]
    shift = np.exp(-2j * np.pi * bins * fraction[None, :] / FRAME).astype(spec.dtype)
    return spec * shift[:, :, None]


def _leak_stats(ref_bins, mic_bins, taps=1, weights=None, regressors=None):
    """Per-bin Gram and cross-spectral sums for the leak-path least squares.

    ref_bins (bins, frames + taps - 1, refs) holds taps-1 earlier frames than
    mic_bins (bins, frames, mics). Optional weights (bins, frames) emphasise
    cells that hold little besides the leaked copy.
    """
    count = mic_bins.shape[1]
    if regressors is None:
        regressors = _regressors(ref_bins, count, taps)
    adjoint = np.conj(regressors).transpose(0, 2, 1)
    if weights is not None:
        weights = weights.astype(np.float32)[:, :, None]
        regressors = regressors * weights
        mic_bins = mic_bins * weights
    gram = np.matmul(adjoint, regressors).astype(np.complex128)
    cross = np.matmul(adjoint, mic_bins).astype(np.complex128)
    return gram, cross


def _solve_leak(gram, cross, project=True):
    """Leak path H (bins, regressors, mics) with mic ~= ref @ H.

    A direct (digital) leak is short after the common delay is removed, so its
    per-bin estimate is projected onto a short impulse response. That averages
    estimation noise from speech across frequency instead of trusting each bin
    independently. Acoustic paths are long; their frame taps carry the room.
    """
    refs = gram.shape[1]
    load = np.trace(gram, axis1=1, axis2=2).real / refs
    # Bins where the system track was nearly silent must not get large gains:
    # regularize against the average power as well as the bin's own. Room
    # echo needs its quieter high bins (speech, sibilants), so the acoustic
    # model counts only a small share of the average.
    share = 1.0 if project else ACOUSTIC_MEAN_SHARE
    floor = REGULARIZE * (load + share * (float(load.mean()) if load.size else 0.0)) + 1e-20
    h = np.linalg.solve(gram + floor[:, None, None] * np.eye(refs)[None], cross)
    if not project:
        return h
    impulse = np.fft.irfft(h, FRAME, axis=0)
    keep = np.zeros(FRAME)
    keep[:PATH_TAPS] = 1.0
    keep[-PATH_TAPS // 4:] = 1.0     # small negative residual offsets
    impulse *= keep[:, None, None]
    return np.fft.rfft(impulse, axis=0)


def _predict(ref_bins, h, count, taps=1, regressors=None):
    """Predicted leak (bins, count, mics) from the reference and leak path."""
    if regressors is None:
        regressors = _regressors(ref_bins, count, taps)
    return np.matmul(regressors, h.astype(ref_bins.dtype))


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


def probe_leak(mic, ref, windows, mono=False, model=DIRECT):
    """Held-out leak measurement on the loudest system-audio windows.

    windows lists (start, lag): mic sample where each probe window starts and
    the delay measured there, so clock drift between windows does not blur the
    shared leak estimate. The leak path is fitted on the first half of each
    window and used to predict the second half. Returns (share, accuracy): the
    fraction of the microphone energy that the prediction explains, and how
    much of the predicted energy is actually present. Speech lowers the share
    but does not make an unrelated signal predictable, so accuracy stays near
    zero for an ordinary microphone.
    """
    probe = int(PROBE_SECONDS * mic.rate)
    pairs = []
    gram = cross = None
    for start, lag in windows:
        mic_spec = _stft(mic.read(start, probe))
        ref_spec = _read_reference(ref, start, probe, lag, model, mono)
        count = mic_spec.shape[1]
        half = count // 2
        g, c = _leak_stats(ref_spec, mic_spec[:, :half], model.taps)
        gram, cross = (g, c) if gram is None else (gram + g, cross + c)
        pairs.append((ref_spec[:, half:], mic_spec[:, half:]))
    if gram is None:
        return 0.0, 0.0
    h = _solve_leak(gram, cross, model.project)
    mic_energy = predicted_energy = explained = 0.0
    for ref_held, held in pairs:
        predicted = _predict(ref_held, h, held.shape[1], model.taps)
        mic_energy += float(np.sum(np.abs(held) ** 2))
        predicted_energy += float(np.sum(np.abs(predicted) ** 2))
        explained += float(np.sum((np.conj(predicted) * held).real))
    if mic_energy <= 0 or predicted_energy <= 0:
        return 0.0, 0.0
    return max(0.0, explained / mic_energy), max(0.0, explained / predicted_energy)


def choose_model(mic, ref, windows, mono=False):
    """Return (model, share, accuracy) for the coupling found, or (None, ...)."""
    best = (None, 0.0, 0.0)
    for model in (DIRECT, ACOUSTIC):
        share, accuracy = probe_leak(mic, ref, windows, mono, model)
        if share < MIN_LEAK_SHARE or accuracy < MIN_PREDICTION:
            continue
        # The longer acoustic model must explain clearly more than the direct
        # one to be worth its extra freedom.
        if best[0] is None or share > best[1] * 1.05 + 0.01:
            best = (model, share, accuracy)
    return best


class Alignment:
    """Delay of the leaked copy behind the system track, following clock drift.

    The delay is measured independently in several loud windows and fitted
    with a straight line (two device clocks drift at a nearly constant rate).
    """

    def __init__(self, windows, offset, slope):
        self.windows, self.offset, self.slope = windows, offset, slope

    def at(self, sample):
        return int(round(self.exact(sample)))

    def exact(self, sample):
        return self.offset + self.slope * sample


def estimate_alignment(mic, ref):
    """Alignment of the leaked copy, or None when no consistent copy is found."""
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
    measured = []
    for energy, start in energies[:MAX_PROBES]:
        if energy <= 1e-8:
            continue
        lag, sharpness = _gcc_phat_lag(_mono(ref.read(start, window)),
                                       _mono(mic.read(start, window)), max_lag)
        if sharpness >= 8.0:
            # The mic window starts lag samples later than its system window.
            measured.append((start + lag + window / 2.0, lag))
    active = sum(1 for energy, _ in energies[:MAX_PROBES] if energy > 1e-8)
    if not measured or len(measured) < min(2, active):
        return None
    times = np.asarray([t for t, _ in measured])
    lags = np.asarray([lag for _, lag in measured], np.float64)
    slope = 0.0
    if len(measured) >= 3:
        # Theil-Sen: median of pairwise slopes, robust to a stray echo peak.
        pairs = [(lags[j] - lags[i]) / (times[j] - times[i])
                 for i in range(len(times)) for j in range(i + 1, len(times))
                 if abs(times[j] - times[i]) > mic.rate]
        if pairs:
            slope = float(np.clip(np.median(pairs), -MAX_DRIFT, MAX_DRIFT))
    offset = float(np.median(lags - slope * times))
    fitted = offset + slope * times
    agreeing = np.abs(lags - fitted) <= max(2, mic.rate // 1000)
    if np.sum(agreeing) < max(1, (len(lags) + 1) // 2):
        return None
    windows = [(int(t - window / 2.0), int(lag)) for (t, lag), ok in zip(measured, agreeing) if ok]
    return Alignment(windows, offset, slope)


def estimate_lag(mic, ref):
    """Delay at the start of the take (kept for callers that need one value)."""
    alignment = estimate_alignment(mic, ref)
    return None if alignment is None else alignment.at(0)


def _track_offset(ref_bins, mic_bins, model, rate=48000):
    """Samples by which the leak moved from its expected alignment in this block.

    GCC-PHAT over the block's own STFT frames: the frame-averaged cross
    spectrum gives the offset within half a frame (about 21 ms), far more than
    two device clocks drift apart in one block. Returns None when unclear.
    """
    first = model.taps - 1
    count = mic_bins.shape[1]
    current = ref_bins[:, first:first + count].mean(axis=2)
    if float(np.mean(np.abs(current) ** 2)) <= 1e-8 * FRAME:
        return None
    spectrum = np.sum(np.conj(current) * mic_bins.mean(axis=2), axis=1).astype(np.complex128)
    spectrum /= np.maximum(np.abs(spectrum), 1e-20)
    correlation = np.fft.irfft(spectrum, FRAME)
    # Search around the expected position (the model lead), not around zero.
    centred = np.roll(correlation, FRAME // 2 - model.lead)
    peak = int(np.argmax(centred))
    sharpness = float(centred[peak] / (np.mean(np.abs(centred)) + 1e-20))
    delta = peak - FRAME // 2
    if sharpness >= 8.0 and abs(delta) <= TRACK_MAX_SECONDS * rate:
        return delta
    return None


def _robust_weights(ref_bins, mic_bins, h, taps, regressors=None):
    """Per-cell weights that keep speech from biasing the echo-path estimate.

    With the previous estimate, a cell whose residual is small holds mostly
    echo (informative); a cell with a large residual holds the user's voice or
    other sound (down-weighted). Weights are normalised per bin to mean 1.
    """
    predicted = _predict(ref_bins, h, mic_bins.shape[1], taps, regressors)
    near = np.mean(np.abs(mic_bins - predicted) ** 2, axis=2)
    echo = np.mean(np.abs(predicted) ** 2, axis=2)
    floor = 1e-3 * np.mean(np.mean(np.abs(mic_bins) ** 2, axis=2), axis=1, keepdims=True) + 1e-12
    # The echo term bounds the weights: when the path drifts and the previous
    # estimate leaves more residual, echo-dominated cells keep their influence
    # instead of locking the estimate in place.
    weights = 1.0 / (near + ROBUST_ECHO_SHARE * echo + floor)
    return weights / np.mean(weights, axis=1, keepdims=True)


class _ResidualSuppressor:
    """Attenuate echo the linear model could not predict, where echo dominates.

    The leftover is measured as a per-bin fraction of the predicted echo on the
    frames where the residual is smallest relative to the prediction (system
    sound playing, user silent). The gain closes only where that expected
    leftover is a large part of what remains; speech raises the residual and
    keeps the gain open. Gains open instantly and close smoothly.
    """

    def __init__(self):
        self.leftover = None
        self.gain = None

    def apply(self, predicted, residual):
        """predicted and residual are bin-major spectra (bins, frames, mics)."""
        echo = np.abs(predicted) ** 2
        rest = np.abs(residual) ** 2
        active = echo > 0.1 * np.mean(echo, axis=1, keepdims=True) + 1e-12
        ratio = np.where(active, rest / (echo + 1e-20), np.inf)
        counts = np.sum(active, axis=1)
        ordered = np.sort(ratio, axis=1)
        index = np.clip((RES_QUANTILE * (counts - 1)).astype(np.int64), 0, ratio.shape[1] - 1)
        measured = np.take_along_axis(ordered, index[:, None, :], axis=1)[:, 0, :]
        measured = np.where(counts >= 8, measured, np.nan)
        if self.leftover is None or self.leftover.shape != measured.shape:
            self.leftover = measured
        else:
            known = ~np.isnan(self.leftover)
            self.leftover = np.where(np.isnan(measured), self.leftover,
                                     np.where(known, 0.5 * self.leftover + 0.5 * measured, measured))
        leftover = np.clip(np.nan_to_num(self.leftover, nan=0.0), 0.0, RES_MAX_LEFTOVER)
        gain = np.clip(1.0 - RES_OVER * leftover[:, None, :] * echo / (rest + 1e-20), RES_FLOOR, 1.0)
        # Smooth across neighbouring bins against isolated "musical" holes.
        padded = np.concatenate((gain[:1], gain, gain[-1:]), axis=0)
        gain = 0.25 * padded[:-2] + 0.5 * padded[1:-1] + 0.25 * padded[2:]
        smooth = np.empty_like(gain)
        previous = (self.gain if self.gain is not None and self.gain.shape == gain[:, 0].shape
                    else gain[:, 0])
        for index in range(gain.shape[1]):
            current = gain[:, index]
            previous = np.where(current > previous, current, 0.6 * previous + 0.4 * current)
            smooth[:, index] = previous
        self.gain = previous
        return residual * smooth


def remove_system_copy(mic_path, sys_path, out_path, cancelled=None):
    """Write a cleaned microphone WAV and return its path, or None if unneeded.

    Returns None when the files are incompatible, the system track is silent,
    or the microphone does not contain a clear copy of the system sound. The
    system WAV must use the microphone's sample rate (the recorder resamples
    it first when the devices differ).
    """
    mic, ref = FloatWav(mic_path), FloatWav(sys_path)
    if mic.rate != ref.rate or mic.frames < FRAME * 4 or ref.frames < FRAME * 4:
        return None
    alignment = estimate_alignment(mic, ref)
    if alignment is None:
        return None
    window = int(PROBE_SECONDS * mic.rate)
    samples = np.linspace(0, max(0, ref.frames - window), num=MAX_PROBES, dtype=np.int64)
    mono = _reference_layout(ref, samples, min(window, ref.frames))
    model, _, _ = choose_model(mic, ref, alignment.windows, mono)
    if model is None:
        return None
    lag = alignment.at(0)

    channels = mic.channels
    block_samples = BLOCK_FRAMES * HOP
    total = mic.frames
    written = 0
    tail = np.zeros((HOP, channels), np.float64)
    pooled = pending = None
    jump = 0
    suppressor = _ResidualSuppressor() if model.suppress else None
    with open(out_path, 'wb') as handle:
        _write_header(handle, channels, mic.rate, 0)
        # Analysis starts HOP before 0 so the first output sample is fully covered.
        position = -HOP
        while position < total:
            if cancelled is not None and cancelled():
                raise RuntimeError('Microphone cleanup was cancelled.')
            span = block_samples + FRAME - HOP
            mic_block = mic.read(position, span)
            identical_mic = channels > 1 and np.allclose(mic_block[:, 0], mic_block[:, 1:].T, atol=1e-7)
            mic_used = mic_block[:, :1] if identical_mic else mic_block
            mic_spec = _stft(mic_used)
            if model.warp:
                # Exact drift line plus any measured jump (audio glitch).
                ref_spec = _warped_reference(ref, position, span,
                                             lambda sample: alignment.exact(sample) + jump, model, mono)
            else:
                ref_spec = _read_reference(ref, position, span, lag, model, mono)
            # A measured move is accepted when two consecutive blocks agree,
            # so one spurious correlation peak cannot misalign the model.
            step = max(1, int(model.track_step * mic.rate))
            measured = _track_offset(ref_spec, mic_spec, model, mic.rate)
            moved = None
            if measured is None:
                if not model.warp:
                    fitted = alignment.at(position + span // 2)
                    moved = fitted - lag if abs(fitted - lag) >= step else None
            elif abs(measured) >= step:
                if pending is not None and abs(measured - pending) <= max(1, mic.rate // 1000):
                    moved = measured
                pending = measured
            else:
                pending = None
            if moved is not None:
                pooled, pending = None, None   # old statistics describe the old alignment
                if model.warp:
                    jump += moved
                    ref_spec = _warped_reference(ref, position, span,
                                                 lambda sample: alignment.exact(sample) + jump, model, mono)
                else:
                    lag += moved
                    ref_spec = _read_reference(ref, position, span, lag, model, mono)
            count = mic_spec.shape[1]
            regressors = _regressors(ref_spec, count, model.taps)   # built once per block
            weights = None
            if model.robust and pooled is not None and pooled[2] is not None \
                    and pooled[2].shape[2] == mic_spec.shape[2]:
                weights = _robust_weights(ref_spec, mic_spec, pooled[2], model.taps, regressors)
            g, c = _leak_stats(ref_spec, mic_spec, model.taps, weights, regressors)
            if pooled is not None and pooled[1].shape == c.shape:
                g, c = g + model.forget * pooled[0], c + model.forget * pooled[1]
            h = _solve_leak(g, c, model.project)
            pooled = (g, c, h)
            predicted = _predict(ref_spec, h, count, model.taps, regressors)
            residual = mic_spec - predicted
            # Never make a block worse (for example a block of pure speech).
            if np.sum(np.abs(residual) ** 2) > np.sum(np.abs(mic_spec) ** 2):
                residual = mic_spec
            elif suppressor is not None:
                residual = suppressor.apply(predicted, residual)
            out = _istft_add(residual)
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
