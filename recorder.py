import os
import sys
import time
import queue
import struct
import subprocess
import threading
import warnings
import tempfile
import ctypes
from ctypes import wintypes
from datetime import datetime
from pathlib import Path

import mss
import numpy as np
import soundcard as sc

import win32gui
import win32ui
import win32con

TARGET_FPS = 30
FRAME_INTERVAL = 1.0 / TARGET_FPS
CURSOR_CANVAS_SIZE = 512
LIVE_AUDIO_CHUNK_SECONDS = 0.05
AUDIO_DEVICE_BUFFER_SECONDS = 0.50

TEMP_PREFIX = "WWRecorder_temp_"
THREAD_JOIN_TIMEOUT = 5
TEMP_RETENTION_SECONDS = 7 * 24 * 60 * 60


def _enter_audio_mmcss():
    """Register the current Windows capture thread with MMCSS.

    MMCSS gives time-sensitive audio work priority during short CPU/GPU load
    spikes without making the Python process globally high priority. Failure is
    harmless on unsupported Windows configurations.
    """
    if sys.platform != 'win32':
        return None
    try:
        avrt = ctypes.WinDLL("avrt", use_last_error=True)
        avrt.AvSetMmThreadCharacteristicsW.argtypes = [
            ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_ulong)
        ]
        avrt.AvSetMmThreadCharacteristicsW.restype = ctypes.c_void_p
        task_index = ctypes.c_ulong(0)
        handle = avrt.AvSetMmThreadCharacteristicsW("Audio", ctypes.byref(task_index))
        return (avrt, handle) if handle else None
    except Exception:
        return None


def _leave_audio_mmcss(registration) -> None:
    if not registration:
        return
    avrt, handle = registration
    try:
        avrt.AvRevertMmThreadCharacteristics.argtypes = [ctypes.c_void_p]
        avrt.AvRevertMmThreadCharacteristics.restype = ctypes.c_bool
        avrt.AvRevertMmThreadCharacteristics(handle)
    except Exception:
        pass


def _read_audio_chunk(recorder, chunk_frames: int):
    """Read exactly one SoundCard chunk and report real WASAPI glitches.

    SoundCard buffers until ``numframes`` contiguous frames are available.
    Callback wall-clock lateness must not be converted into inserted silence;
    only WASAPI's DATA_DISCONTINUITY flag represents an actual device glitch.
    """
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", sc.SoundcardRuntimeWarning)
        data = recorder.record(numframes=chunk_frames)
    discontinuities = sum(
        1 for warning in caught
        if issubclass(warning.category, sc.SoundcardRuntimeWarning)
        and "data discontinuity" in str(warning.message).lower()
    )
    return data, discontinuities


def _next_frame_deadline(deadline: float, now: float) -> tuple[float, int]:
    """Advance a capture clock without creating a duplicate-frame backlog.

    Returning the number of missed slots gives us diagnostics, while moving the
    next deadline into the future ensures a temporary stall cannot trigger the
    old feedback loop that repeatedly pushed one stale frame through a blocked
    FFmpeg pipe.
    """
    next_deadline = deadline + FRAME_INTERVAL
    if now < next_deadline:
        return next_deadline, 0
    # The next capture is already due, so run it immediately. Count only whole
    # additional slots lost behind that due capture; do not sleep for another
    # interval, which would unnecessarily halve FPS when a grab takes ~34 ms.
    missed = int((now - next_deadline) / FRAME_INTERVAL)
    return now, missed


def _process_survived_startup(process, timeout: float = 0.30, interval: float = 0.01) -> bool:
    """Give FFmpeg enough time to report delayed startup failures."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return False
        time.sleep(interval)
    return process.poll() is None


class _BitmapInfoHeader(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long),
        ("biHeight", ctypes.c_long), ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class _BitmapInfo(ctypes.Structure):
    _fields_ = [("bmiHeader", _BitmapInfoHeader), ("bmiColors", wintypes.DWORD)]


def _create_cursor_surface(screen_dc: int):
    """Create a reusable top-down BGRA DIB for native cursor composition."""
    size = CURSOR_CANVAS_SIZE
    info = _BitmapInfo()
    info.bmiHeader.biSize = ctypes.sizeof(_BitmapInfoHeader)
    info.bmiHeader.biWidth = size
    info.bmiHeader.biHeight = -size  # top-down, matching MSS BGRA rows
    info.bmiHeader.biPlanes = 1
    info.bmiHeader.biBitCount = 32
    info.bmiHeader.biCompression = 0  # BI_RGB
    bits = ctypes.c_void_p()
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    gdi32.CreateDIBSection.argtypes = [
        wintypes.HDC, ctypes.POINTER(_BitmapInfo), wintypes.UINT,
        ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD,
    ]
    gdi32.CreateDIBSection.restype = wintypes.HBITMAP
    bitmap = gdi32.CreateDIBSection(screen_dc, ctypes.byref(info), 0, ctypes.byref(bits), None, 0)
    if not bitmap or not bits.value:
        raise ctypes.WinError(ctypes.get_last_error())
    dc = previous = None
    try:
        dc = win32gui.CreateCompatibleDC(screen_dc)
        previous = win32gui.SelectObject(dc, bitmap)
        pixels = np.ctypeslib.as_array(
            (ctypes.c_ubyte * (size * size * 4)).from_address(bits.value)
        ).reshape((size, size, 4))
        return dc, bitmap, previous, pixels
    except Exception:
        if dc is not None:
            try:
                if previous is not None:
                    win32gui.SelectObject(dc, previous)
                win32gui.DeleteDC(dc)
            except Exception:
                pass
        try:
            win32gui.DeleteObject(bitmap)
        except Exception:
            pass
        raise


def _acquire_cursor_surface():
    """Acquire the desktop DC and release it immediately if DIB setup fails."""
    screen_dc = win32gui.GetDC(0)
    try:
        return (screen_dc, *_create_cursor_surface(screen_dc))
    except Exception:
        try:
            win32gui.ReleaseDC(0, screen_dc)
        except Exception:
            pass
        raise


def _recording_temp_dir(output_folder: str) -> Path:
    """Keep large session media on the drive selected for final output."""
    temp_dir = Path(output_folder) / ".wwr_temp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        try:
            ctypes.windll.kernel32.SetFileAttributesW(str(temp_dir), 0x02)
        except Exception:
            pass
    return temp_dir


def _video_timing_filter(
    pause_intervals: list[tuple[float, float]],
    duration: float,
    source_frame_count: int | None = None,
) -> str:
    """Create a stable wall-clock 30-fps timeline and remove pause gaps.

    Rawvideo pipes contain no per-frame timestamps. When capture skips slots
    under load, FFmpeg otherwise labels the surviving frames as consecutive
    30-fps frames and visible motion runs ahead of real-time audio. Stretch the
    captured frame timeline back to the measured active wall duration before
    converting to CFR.
    """
    expression = "PTS-STARTPTS"
    excluded = []
    for start, end in pause_intervals:
        pause_duration = max(0.0, end - start)
        if pause_duration > 0:
            excluded.append(f"between(t\\,{start:.6f}\\,{end:.6f})")
            # STARTPTS already absorbs a leading pre-record pause because the
            # select stage removes those frames before setpts sees its first
            # input. Subtracting that interval again creates negative PTS and
            # silently drops the first video frames. Later user pauses still
            # leave timeline gaps and must be compressed explicitly.
            if start > 1e-6:
                # Commas belong to gte(), so escape them for FFmpeg's parser.
                expression += f"-(gte(PTS*TB\\,{end:.6f})*{pause_duration:.6f}/TB)"
    if source_frame_count is not None and not excluded and source_frame_count > 1:
        source_last_pts = (source_frame_count - 1) / TARGET_FPS
        target_last_pts = max(0.0, float(duration) - FRAME_INTERVAL)
        scale = target_last_pts / max(source_last_pts, FRAME_INTERVAL)
        expression = f"(PTS-STARTPTS)*{scale:.9f}"

    pad_duration = max(1.0, float(duration) + 1.0)
    stages = []
    if excluded:
        stages.append(f"select='not({'+'.join(excluded)})'")
    stages.extend([
        f"setpts='{expression}'",
        f"fps={TARGET_FPS}",
        f"tpad=stop_mode=clone:stop_duration={pad_duration:.6f}",
    ])
    return ",".join(stages)


def _audio_filter_graph(has_sys: bool, has_mic: bool) -> str:
    """Voice-first mix: no speech gate, spectral denoise, or silent-track ducking.

    Bounded mic gain lifts quiet speech; mic-only compression reins in loud
    speech without letting system audio control it. Accept some breath rather
    than cutting syllables. The shared limiter only prevents summed clipping.
    """
    if not (has_sys or has_mic):
        return ""
    timeline = "aresample=48000:async=1:min_hard_comp=0.100:first_pts=0"
    mic_stages = (
        "highpass=f=70,volume=2,"
        "acompressor=threshold=0.125:ratio=2.5:attack=10:release=180:makeup=1.3"
    )
    final_stages = (
        "alimiter=limit=0.95:level=false:latency=true,"
        "aformat=sample_rates=48000:sample_fmts=fltp,apad[a]"
    )
    if has_sys and has_mic:
        return (
            f"[1:a]{timeline}[sys];"
            f"[2:a]{timeline},{mic_stages}[mic];"
            "[sys][mic]amix=inputs=2:duration=longest:normalize=0[mix];"
            f"[mix]{final_stages}"
        )
    source_filter = f",{mic_stages}" if has_mic else ""
    return f"[1:a]{timeline}{source_filter},{final_stages}"


def get_ffmpeg_path():
    base = os.path.dirname(os.path.abspath(__file__))
    ffmpeg = os.path.join(base, "ffmpeg.exe")
    return ffmpeg if os.path.isfile(ffmpeg) else "ffmpeg"


def _unique_media_path(folder: str, prefix: str, suffix: str) -> str:
    Path(folder).mkdir(parents=True, exist_ok=True)
    base = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    path = os.path.join(folder, f"{prefix}_{base}{suffix}")
    counter = 2
    while os.path.exists(path):
        path = os.path.join(folder, f"{prefix}_{base}_{counter}{suffix}")
        counter += 1
    return path


def _remove_file_later(path: str, attempts: int = 6, delay: float = 0.25) -> None:
    for _ in range(attempts):
        try:
            if os.path.exists(path):
                os.remove(path)
            return
        except (PermissionError, OSError):
            time.sleep(delay)
    try:
        print(f"[WWRecorder] Could not remove temp file: {path}")
    except Exception:
        pass


class _Float32WavWriter:
    """Write IEEE 754 float32 WAV files (WAVE_FORMAT_IEEE_FLOAT, tag 0x0003).

    Python's built-in ``wave`` module only supports integer PCM formats.
    This minimal writer produces a standard RIFF/WAVE file with 32-bit float
    samples so we can hand the full-fidelity WASAPI capture to FFmpeg without
    any lossy int16 truncation.
    """

    def __init__(self, path: str, channels: int = 2, samplerate: int = 48000):
        self._f = open(path, 'wb')
        self._channels = channels
        self._samplerate = samplerate
        self._data_bytes = 0
        # Write a 44-byte placeholder header; updated in close()
        self._f.write(b'\x00' * 44)

    def writeframes(self, raw_bytes: bytes):
        self._f.write(raw_bytes)
        self._data_bytes += len(raw_bytes)

    def close(self):
        self._f.seek(0)
        bits = 32
        block_align = self._channels * (bits // 8)
        byte_rate = self._samplerate * block_align

        # Clamp to 4GB WAV limit to prevent struct.pack overflow on long recordings
        max_data = 0xFFFFFFFF - 36
        safe_data_bytes = min(self._data_bytes, max_data)

        hdr  = struct.pack('<4sI4s', b'RIFF', 36 + safe_data_bytes, b'WAVE')
        fmt  = struct.pack('<4sIHHIIHH',
            b'fmt ', 16,
            3,                  # wFormatTag = WAVE_FORMAT_IEEE_FLOAT
            self._channels,
            self._samplerate,
            byte_rate,
            block_align,
            bits,
        )
        data = struct.pack('<4sI', b'data', safe_data_bytes)
        self._f.write(hdr + fmt + data)
        self._f.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


# ─────────────────────────────────────────────────────────────────────────────
#  Mic Noise Processor — real-time noise gate + high-pass + spectral subtraction
# ─────────────────────────────────────────────────────────────────────────────

class _MicNoiseProcessor:
    """Lightweight real-time mic audio cleaner.

    Three stages applied per chunk (all numpy, no scipy dependency):

    1. **High-pass filter (80 Hz)** — removes low-frequency rumble from desk
       vibrations, HVAC hum, etc.  Implemented as a 2nd-order Butterworth IIR
       using pre-computed coefficients.

    2. **Spectral noise subtraction** — estimates the noise floor from the
       first ~1 s of mic input (assumes the user isn't speaking yet), then
       subtracts it from every subsequent chunk via FFT/IFFT.

    3. **Noise gate** — zeroes any chunk whose RMS energy falls below a
       calibrated threshold (kills residual hiss).  Uses soft attack/release
       ramps to avoid clicks.
    """

    # ── Tunables ──
    NOISE_PROFILE_SECS = 1.0      # seconds of audio used to estimate noise floor
    GATE_THRESHOLD_DB  = -40.0    # RMS below this → gate closes (in dB)
    GATE_RAMP_SAMPLES  = 128      # fade in/out length for soft gate transitions
    HIGHPASS_FREQ      = 80.0     # Hz — cutoff for rumble removal
    SPECTRAL_STRENGTH  = 1.5      # how aggressively to subtract noise (1.0 = exact)
    SPECTRAL_FLOOR     = 0.01     # minimum magnitude after subtraction (prevents musical noise)

    def __init__(self, samplerate: int, channels: int = 2):
        self._sr = samplerate
        self._ch = channels
        self._gate_open = False

        # ── High-pass IIR coefficients (2nd-order Butterworth) ──
        # Pre-warped bilinear transform: s → z
        w0 = 2.0 * np.pi * self.HIGHPASS_FREQ / samplerate
        alpha = np.sin(w0) / (2.0 * (1.0 / np.sqrt(2.0)))  # Q = 1/√2 for Butterworth
        cos_w0 = np.cos(w0)
        b0 = (1.0 + cos_w0) / 2.0
        b1 = -(1.0 + cos_w0)
        b2 = (1.0 + cos_w0) / 2.0
        a0 = 1.0 + alpha
        a1 = -2.0 * cos_w0
        a2 = 1.0 - alpha
        # Normalise
        self._b = np.array([b0 / a0, b1 / a0, b2 / a0], dtype=np.float64)
        self._a = np.array([a1 / a0, a2 / a0], dtype=np.float64)
        # Filter state (per channel): [z1, z2]
        self._hp_state = np.zeros((channels, 2), dtype=np.float64)

        # ── Spectral noise profile ──
        self._noise_profile = None    # estimated noise magnitude spectrum
        self._noise_buf = []          # accumulates chunks during calibration
        self._noise_frames_needed = int(self.NOISE_PROFILE_SECS * samplerate)
        self._noise_frames_collected = 0

        # ── Gate state ──
        self._gate_thresh_linear = 10.0 ** (self.GATE_THRESHOLD_DB / 20.0)

    # ── Public API ──────────────────────────────────────────────────────────

    def process(self, data: np.ndarray) -> np.ndarray:
        """Process a chunk of float32 mic audio in-place. Shape: (N, channels)."""
        # 1. High-pass filter (removes rumble)
        data = self._apply_highpass(data)

        # 2. Spectral noise subtraction
        if self._noise_profile is None:
            # Still calibrating — accumulate samples and use the chunk as-is
            self._noise_buf.append(data.copy())
            self._noise_frames_collected += len(data)
            if self._noise_frames_collected >= self._noise_frames_needed:
                self._build_noise_profile()
        else:
            data = self._subtract_noise(data)

        # 3. Noise gate
        data = self._apply_gate(data)

        return data

    # ── Internals ───────────────────────────────────────────────────────────

    def _apply_highpass(self, data: np.ndarray) -> np.ndarray:
        """Apply 2nd-order Butterworth high-pass filter (vectorized).

        Uses scipy.signal.lfilter when available (fast C implementation).
        Falls back to a manual Direct Form II transposed loop otherwise.
        """
        out = np.empty_like(data, dtype=np.float32)
        b_full = self._b
        a_full = np.array([1.0, self._a[0], self._a[1]], dtype=np.float64)

        try:
            from scipy.signal import lfilter, lfilter_zi
            for ch in range(min(self._ch, data.shape[1])):
                x = data[:, ch].astype(np.float64)
                # Convert stored state [z1, z2] to scipy's zi format
                zi = self._hp_state[ch].copy()
                y, zf = lfilter(b_full, a_full, x, zi=zi)
                self._hp_state[ch] = zf
                out[:, ch] = y.astype(np.float32)
        except ImportError:
            # Pure-numpy fallback — still runs the IIR but in Python
            for ch in range(min(self._ch, data.shape[1])):
                x = data[:, ch].astype(np.float64)
                y = np.empty_like(x)
                z1, z2 = self._hp_state[ch]
                b0, b1, b2 = self._b
                a1, a2 = self._a
                for i in range(len(x)):
                    xi = x[i]
                    yi = b0 * xi + z1
                    z1 = b1 * xi - a1 * yi + z2
                    z2 = b2 * xi - a2 * yi
                    y[i] = yi
                self._hp_state[ch] = [z1, z2]
                out[:, ch] = y.astype(np.float32)
        return out

    def _build_noise_profile(self):
        """Compute average magnitude spectrum from the calibration buffer."""
        all_data = np.concatenate(self._noise_buf, axis=0)
        # Use mono mix for spectral estimation
        mono = np.mean(all_data, axis=1)
        # Windowed FFT in overlapping segments for a smooth estimate
        seg_len = min(2048, len(mono))
        hop = seg_len // 2
        window = np.hanning(seg_len)
        spectra = []
        pos = 0
        while pos + seg_len <= len(mono):
            seg = mono[pos:pos + seg_len] * window
            mag = np.abs(np.fft.rfft(seg))
            spectra.append(mag)
            pos += hop
        if spectra:
            self._noise_profile = np.mean(spectra, axis=0)
        else:
            # Not enough data — use a flat minimal floor
            self._noise_profile = np.full(seg_len // 2 + 1, self.SPECTRAL_FLOOR, dtype=np.float32)
        self._noise_buf = []  # free memory

    def _subtract_noise(self, data: np.ndarray) -> np.ndarray:
        """Spectral subtraction on each channel."""
        out = np.empty_like(data)
        n_fft = (len(self._noise_profile) - 1) * 2
        for ch in range(data.shape[1]):
            x = data[:, ch].astype(np.float32)
            # Process in n_fft-sized segments
            result = np.zeros_like(x)
            pos = 0
            while pos < len(x):
                end = min(pos + n_fft, len(x))
                seg = np.zeros(n_fft, dtype=np.float32)
                seg[:end - pos] = x[pos:end]
                S = np.fft.rfft(seg)
                mag = np.abs(S)
                phase = np.angle(S)
                # Subtract scaled noise profile
                clean_mag = mag - self.SPECTRAL_STRENGTH * self._noise_profile
                # Apply spectral floor to prevent "musical noise" artifacts
                clean_mag = np.maximum(clean_mag, self.SPECTRAL_FLOOR)
                clean_S = clean_mag * np.exp(1j * phase)
                clean_seg = np.fft.irfft(clean_S, n=n_fft)
                length = end - pos
                result[pos:end] = clean_seg[:length]
                pos += n_fft
            out[:, ch] = result
        return out.astype(np.float32)

    def _apply_gate(self, data: np.ndarray) -> np.ndarray:
        """Noise gate with soft ramp transitions."""
        rms = np.sqrt(np.mean(data ** 2))
        should_open = rms > self._gate_thresh_linear

        if should_open and not self._gate_open:
            # Gate opening — ramp up from silence
            self._gate_open = True
            ramp_len = min(self.GATE_RAMP_SAMPLES, len(data))
            ramp = np.linspace(0.0, 1.0, ramp_len, dtype=np.float32)
            data[:ramp_len] *= ramp[:, np.newaxis]
        elif not should_open and self._gate_open:
            # Gate closing — ramp down to silence
            self._gate_open = False
            ramp_len = min(self.GATE_RAMP_SAMPLES, len(data))
            ramp = np.linspace(1.0, 0.0, ramp_len, dtype=np.float32)
            data[-ramp_len:] *= ramp[:, np.newaxis]
        elif not should_open and not self._gate_open:
            # Gate stays closed — silence
            data = np.zeros_like(data)

        return data


class RecordingEngine:
    def __init__(self):
        self._state_lock = threading.RLock()
        self._running = False
        self._paused = False
        self._pause_event = threading.Event()
        self._pause_event.set()

        self._ffmpeg_proc = None
        self._stdin_lock = threading.Lock()  # BUG-004: protect stdin writes
        self._frame_thread = None
        self._sys_thread = None
        self._mic_thread = None
        self._sys_audio_ready = threading.Event()
        self._mic_audio_ready = threading.Event()
        with self._state_lock:
            self._is_prewarming = False
            self._preparing = False
            self._finalizing = False

        self._sys_audio_enabled = False
        self._mic_audio_enabled = False

        self._region = {}
        self._output_path = ""
        self._temp_vid_path = ""
        self._sys_wav_path = ""
        self._mic_wav_path = ""
        self._last_error = ""
        self._capture_clock_start = None
        self._capture_stopped_at = None
        self._pause_started_at = None
        self._pause_intervals = []
        self._captured_frames = 0
        self._dropped_frame_slots = 0
        self._capture_failed = False
        # Raw frames are omitted while paused, so pause intervals must not be
        # removed a second time during final muxing.
        self._capture_mode = "raw_frames_pause_omitted"
        self._runtime_events: queue.Queue = queue.Queue()
        self._sys_audio_discontinuities = 0
        self._mic_audio_discontinuities = 0

        self.cleanup_temp_dir()

    def is_recording(self):
        with self._state_lock:
            return self._running and not self._is_prewarming

    def is_prewarming(self):
        with self._state_lock:
            return self._is_prewarming or self._preparing

    def is_busy(self):
        """True while a session owns mutable engine resources."""
        with self._state_lock:
            return self._running or self._preparing or self._finalizing

    def reset_failed_prepare(self):
        """Return to idle after an unexpected exception during preparation."""
        with self._state_lock:
            self._preparing = False
            self._is_prewarming = False
            self._running = False
        proc = self._ffmpeg_proc
        if proc and proc.poll() is None:
            try:
                proc.kill()
                proc.wait(timeout=2)
            except Exception:
                pass

    def is_paused(self):
        with self._state_lock:
            return self._paused
    # --- ADD THIS BELOW existing methods ---

    def set_system_audio(self, enabled: bool):
        self._sys_audio_enabled = enabled

    def get_system_audio(self) -> bool:
        return self._sys_audio_enabled

    def set_mic(self, enabled: bool):
        self._mic_audio_enabled = enabled

    def _report_runtime_event(self, kind: str, message) -> None:
        self._runtime_events.put((kind, str(message)))

    def drain_runtime_events(self) -> list[tuple[str, str]]:
        events = []
        while True:
            try:
                events.append(self._runtime_events.get_nowait())
            except queue.Empty:
                return events

    def get_mic(self) -> bool:
        return self._mic_audio_enabled

    @staticmethod
    def grab_full_desktop():
        """Capture the entire virtual desktop as a PIL Image."""
        from PIL import Image
        with mss.mss() as sct:
            # monitors[0] is the entire virtual desktop
            img = sct.grab(sct.monitors[0])
            return Image.frombytes("RGB", img.size, img.rgb)

    @staticmethod
    def take_screenshot(region: dict, output_folder: str) -> str:
        """Capture a region of the screen and save as PNG. Returns the file path."""
        from PIL import Image
        out_path = _unique_media_path(output_folder, "Screenshot", ".png")

        with mss.mss() as sct:
            segments = region.get("segments")
            if segments:
                pil_img = Image.new("RGB", (region["width"], region["height"]), "black")
                for seg in segments:
                    monitor = {"top": seg["src_top"], "left": seg["src_left"],
                               "width": seg["src_width"], "height": seg["src_height"]}
                    img = sct.grab(monitor)
                    part = Image.frombytes("RGB", img.size, img.rgb)
                    target = (seg["dst_width"], seg["dst_height"])
                    if part.size != target:
                        part = part.resize(target, Image.Resampling.LANCZOS)
                    pil_img.paste(part, (seg["dst_left"], seg["dst_top"]))
            else:
                monitor = {k: region[k] for k in ("top", "left", "width", "height")}
                img = sct.grab(monitor)
                pil_img = Image.frombytes("RGB", img.size, img.rgb)
            pil_img.save(out_path, "PNG")

        return out_path

    @staticmethod
    def take_screenshot_image(image, output_folder: str) -> str:
        """Save an already captured PIL image to a collision-proof path."""
        out_path = _unique_media_path(output_folder, "Screenshot", ".png")
        image.save(out_path, "PNG")
        if not os.path.isfile(out_path) or os.path.getsize(out_path) == 0:
            raise RuntimeError("The screenshot could not be written to disk.")
        return out_path

    def prepare(self, region, output_folder, audio_config=None):
        """
        Background initialization: Finds FFmpeg, opens audio streams,
        and starts threads in a PAUSED state. This eliminates lag when 
        the user finally clicks 'Start'.
        """
        with self._state_lock:
            if self._running or self._preparing or self._finalizing:
                return False
            self._preparing = True
            self._last_error = ""

        if audio_config:
            self._sys_audio_enabled = audio_config.get("system_audio", True)
            self._mic_audio_enabled = audio_config.get("mic", False)

        # ✅ FORCE EVEN DIMENSIONS 
        w = int(region.get("width", 0))
        h = int(region.get("height", 0))
        if w < 32 or h < 32:
            print(f"[WWRecorder] Invalid capture region: {region}")
            with self._state_lock:
                self._preparing = False
            return False
        w = w if w % 2 == 0 else w - 1
        h = h if h % 2 == 0 else h - 1

        self._region = {
            "top": int(region.get("top", 0)),
            "left": int(region.get("left", 0)),
            "width": w,
            "height": h,
        }
        self._capture_segments = list(region.get("segments") or [{
            "src_top": self._region["top"], "src_left": self._region["left"],
            "src_width": w, "src_height": h,
            "dst_top": 0, "dst_left": 0, "dst_width": w, "dst_height": h,
        }])

        try:
            output_folder = str(Path(output_folder).expanduser())
            Path(output_folder).mkdir(parents=True, exist_ok=True)
        except Exception as e:
            print(f"[WWRecorder] Invalid output folder: {e}")
            with self._state_lock:
                self._preparing = False
            return False

        # UX-002: Check disk space before recording
        try:
            import shutil
            disk_usage = shutil.disk_usage(output_folder)
            free_mb = disk_usage.free / (1024 * 1024)
            if free_mb < 100:
                print(f"[WWRecorder] Insufficient disk space: {free_mb:.0f} MB free")
                self._low_disk_space = "critical"
                with self._state_lock:
                    self._preparing = False
                return False  # Refuse to record with <100MB
            elif free_mb < 500:
                self._low_disk_space = "warning"
                print(f"[WWRecorder] Low disk space warning: {free_mb:.0f} MB free")
            else:
                self._low_disk_space = None
        except Exception:
            self._low_disk_space = None

        self._output_path = _unique_media_path(output_folder, "Recording", ".mkv")

        with self._state_lock:
            self._capture_clock_start = None
            self._capture_stopped_at = None
            self._pause_started_at = None
            self._pause_intervals = []
            self._captured_frames = 0
            self._dropped_frame_slots = 0
            self._capture_failed = False
            self._sys_audio_discontinuities = 0
            self._mic_audio_discontinuities = 0
            self._sys_audio_ready.clear()
            self._mic_audio_ready.clear()
        
        try:
            temp_dir = _recording_temp_dir(output_folder)
        except Exception as e:
            print(f"[WWRecorder] Could not create recording work folder: {e}")
            with self._state_lock:
                self._preparing = False
            return False
        self.cleanup_temp_dir(temp_dir)
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S_%f")
        self._temp_vid_path = str(temp_dir / f"{TEMP_PREFIX}vid_{timestamp}.mkv")
        self._sys_wav_path = str(temp_dir / f"{TEMP_PREFIX}sys_{timestamp}.wav")
        self._mic_wav_path = str(temp_dir / f"{TEMP_PREFIX}mic_{timestamp}.wav")

        ffmpeg = get_ffmpeg_path()
        cmd = [
            ffmpeg, "-y",
            "-f", "rawvideo", "-pix_fmt", "bgra",
            "-s", f"{w}x{h}", "-r", str(TARGET_FPS),
            "-i", "-",
            "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency",
            "-crf", "23", "-pix_fmt", "yuv420p",
            self._temp_vid_path,
        ]

        try:
            capture_flags = 0
            if os.name == 'nt':
                capture_flags = (
                    subprocess.CREATE_NO_WINDOW
                    | getattr(subprocess, 'ABOVE_NORMAL_PRIORITY_CLASS', 0x00008000)
                )
            self._ffmpeg_proc = subprocess.Popen(
                cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=capture_flags,
            )
        except FileNotFoundError as e:
            print(f"[WWRecorder] FFmpeg not found: {e}")
            with self._state_lock:
                self._preparing = False
            return False
        except Exception as e:
            print("[WWRecorder] FFmpeg prep error:", e)
            with self._state_lock:
                self._preparing = False
            return False

        if not _process_survived_startup(self._ffmpeg_proc):
            print("[WWRecorder] Screen capture failed to start.")
            with self._state_lock:
                self._preparing = False
            return False

        with self._state_lock:
            capture_started_at = time.perf_counter()
            self._capture_clock_start = capture_started_at
            self._pause_started_at = capture_started_at
            self._running = True
            self._paused = True
            self._is_prewarming = True
            self._preparing = False
            self._pause_event.clear()

        self._frame_thread = threading.Thread(
            target=self._frame_worker, daemon=True
        )
        self._frame_thread.start()

        self._sys_thread = threading.Thread(
            target=self._audio_worker, args=(True, self._sys_wav_path), daemon=True
        )
        self._sys_thread.start()

        self._mic_thread = threading.Thread(
            target=self._audio_worker, args=(False, self._mic_wav_path), daemon=True
        )
        self._mic_thread.start()

        # Do not expose Start until both WASAPI clients have opened and drained
        # at least one paused chunk. Without this barrier an immediate click can
        # begin video hundreds of milliseconds before a slower microphone.
        for label, ready_event in (
            ("System", self._sys_audio_ready), ("Mic", self._mic_audio_ready)
        ):
            if not ready_event.wait(timeout=3.0):
                print(f"[WWRecorder] {label} audio did not become ready before recording start")

        self._prepared = True
        return True

    def start(self, region, output_folder, audio_config=None):
        """Start a fresh recording. Discards any leftover pre-warm state first."""
        with self._state_lock:
            self._is_prewarming = False

        # Always start clean — discard any stale pre-warm or prior state
        if self.is_recording() or self.is_prewarming():
            self.discard()
            
        if not self.prepare(region, output_folder, audio_config):
            return False
        with self._state_lock:
            self._is_prewarming = False  # Ensure we're in active mode after prepare
        self.resume()
        return True

    def stop_capture(self):
        """Phase 1: Stop all capture threads and close FFmpeg pipe. Fast — safe to call from UI."""
        stopped_at = time.perf_counter()
        with self._state_lock:
            if not self._running:
                return
            self._capture_stopped_at = stopped_at
            if self._pause_started_at is not None and self._capture_clock_start is not None:
                self._pause_intervals.append((
                    max(0.0, self._pause_started_at - self._capture_clock_start),
                    max(0.0, stopped_at - self._capture_clock_start),
                ))
                self._pause_started_at = None
            self._running = False
            self._is_prewarming = False
            self._finalizing = True
            self._pause_event.set()

        frame_thread_stopped = True
        if self._frame_thread:
            self._frame_thread.join(timeout=THREAD_JOIN_TIMEOUT)
            if self._frame_thread.is_alive():
                print("[WWRecorder] Frame pipe is blocked; terminating FFmpeg to unblock it.")
                if self._ffmpeg_proc and self._ffmpeg_proc.poll() is None:
                    try:
                        self._ffmpeg_proc.kill()
                    except Exception:
                        pass
                self._frame_thread.join(timeout=2)
            frame_thread_stopped = not self._frame_thread.is_alive()

        audio_threads_stopped = True
        if self._sys_thread:
            self._sys_thread.join(timeout=20)
            audio_threads_stopped = audio_threads_stopped and not self._sys_thread.is_alive()

        if self._mic_thread:
            self._mic_thread.join(timeout=20)
            audio_threads_stopped = audio_threads_stopped and not self._mic_thread.is_alive()

        try:
            if self._ffmpeg_proc:
                acquired = self._stdin_lock.acquire(timeout=2)
                if acquired:
                    try:
                        if self._ffmpeg_proc.stdin:
                            self._ffmpeg_proc.stdin.close()
                    except Exception as e:
                        print(f"[WWRecorder] FFmpeg stdin close failed: {e}")
                    finally:
                        self._stdin_lock.release()
                elif self._ffmpeg_proc.poll() is None:
                    self._ffmpeg_proc.kill()
                try:
                    self._ffmpeg_proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._ffmpeg_proc.kill()
                    self._ffmpeg_proc.wait(timeout=2)
                except Exception as e:
                    print(f"[WWRecorder] FFmpeg kill/wait failed: {e}")
        except Exception as e:
            print(f"[WWRecorder] Stop failed: {e}")
            try:
                if self._ffmpeg_proc:
                    self._ffmpeg_proc.kill()
            except Exception as kill_err:
                print(f"[WWRecorder] Forced FFmpeg kill failed: {kill_err}")

        if not frame_thread_stopped or not audio_threads_stopped:
            with self._state_lock:
                self._finalizing = False
            raise RuntimeError(
                "Capture workers did not stop safely. Recovery files were preserved."
            )

        with self._state_lock:
            started_at = self._capture_clock_start
            pauses = list(self._pause_intervals)
            captured = self._captured_frames
            dropped = self._dropped_frame_slots
            capture_failed = self._capture_failed
        if capture_failed:
            raise RuntimeError("Screen capture stopped unexpectedly. Recovery files were preserved.")
        if started_at is not None:
            wall_duration = max(0.0, stopped_at - started_at)
            paused_duration = sum(max(0.0, end - start) for start, end in pauses)
            active_duration = max(0.0, wall_duration - paused_duration)
            effective_fps = captured / active_duration if active_duration > 0 else 0.0
            print(
                f"[WWRecorder] Capture stats: {captured} frames, "
                f"{dropped} scheduler slots skipped, {active_duration:.3f}s active, "
                f"{effective_fps:.2f} captured fps"
            )

    def mux_and_save(self) -> str:
        """Phase 2: Mux audio+video into final compressed file.

        Re-encodes video with -preset veryfast -crf 28 for fast processing + small file size.
        Audio is encoded with Opus 128k from float32 WAV for transparent quality.
        """
        with self._state_lock:
            if not self._finalizing:
                raise RuntimeError("No recording is ready to finalize.")
            temp_vid_path = self._temp_vid_path
            sys_wav_path = self._sys_wav_path
            mic_wav_path = self._mic_wav_path
            output_path = self._output_path
            capture_started_at = self._capture_clock_start
            capture_stopped_at = self._capture_stopped_at
            pause_intervals = list(self._pause_intervals)
            captured_frames = self._captured_frames

        if capture_started_at is None or capture_stopped_at is None:
            with self._state_lock:
                self._finalizing = False
            raise RuntimeError("Recording timing metadata is incomplete; recovery files were preserved.")
        wall_duration = max(0.0, capture_stopped_at - capture_started_at)
        paused_duration = sum(max(0.0, end - start) for start, end in pause_intervals)
        active_duration = max(0.001, wall_duration - paused_duration)

        ffmpeg = get_ffmpeg_path()
        merge_cmd = [ffmpeg, "-y", "-i", temp_vid_path]

        has_sys = os.path.exists(sys_wav_path) and os.path.getsize(sys_wav_path) > 100
        has_mic = os.path.exists(mic_wav_path) and os.path.getsize(mic_wav_path) > 100

        if has_sys:
            merge_cmd.extend(["-i", sys_wav_path])
        if has_mic:
            merge_cmd.extend(["-i", mic_wav_path])

        # ── Compression strategy ──
        # PERF-013: Use veryfast preset (2-3x faster than fast with <1% quality loss at crf 28).
        # -threads 0: Use all available CPU cores for parallel encoding.
        # The temp video is already x264/ultrafast, so re-encode is fast.
        # Paused raw frames were never sent to FFmpeg; applying pause ranges
        # here would shorten the video twice.
        video_filter = _video_timing_filter([], active_duration, captured_frames)
        video_encode = ["-vf", video_filter,
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "28",
                        "-pix_fmt", "yuv420p", "-threads", "0"]
        audio_encode = ["-c:a", "libopus", "-b:a", "112k"]

        if has_sys and has_mic:
            filter_complex = _audio_filter_graph(True, True)
            merge_cmd.extend([
                "-filter_complex", filter_complex,
                "-map", "0:v", "-map", "[a]",
            ] + video_encode + audio_encode)
        elif has_sys or has_mic:
            filter_single = _audio_filter_graph(has_sys, has_mic)
            merge_cmd.extend([
                "-filter_complex", filter_single,
                "-map", "0:v", "-map", "[a]",
            ] + video_encode + audio_encode)
        else:
            merge_cmd.extend(video_encode)

        # Bound every stream to the active (pause-excluded) recording timeline.
        # Video is padded only at the tail when the final capture arrived a few
        # milliseconds early; audio is gap-corrected/resampled and padded above.
        merge_cmd.extend(["-t", f"{active_duration:.6f}", output_path])

        try:
            # PERF-013: Run FFmpeg at below-normal priority so it doesn't starve the UI
            creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            if sys.platform == 'win32':
                creation_flags |= 0x00004000  # BELOW_NORMAL_PRIORITY_CLASS
            subprocess.run(merge_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           creationflags=creation_flags, check=True, timeout=60 * 60)
        except Exception as e:
            print("Muxing error:", e)
            with self._state_lock:
                self._finalizing = False
            raise RuntimeError("Recording could not be finalized.") from e

        if not os.path.isfile(output_path) or os.path.getsize(output_path) == 0:
            with self._state_lock:
                self._finalizing = False
            raise RuntimeError("Recording could not be finalized.")

        # Delete source media only after a playable output has been proven.
        for path in [temp_vid_path, sys_wav_path, mic_wav_path]:
            if path:
                _remove_file_later(path)
        with self._state_lock:
            self._finalizing = False
        return output_path

    @staticmethod
    def extract_thumbnail(filepath: str, size: int = 64) -> bytes:
        """Extract a small JPEG thumbnail from a video file. Returns raw JPEG bytes or b''."""
        try:
            ffmpeg = get_ffmpeg_path()
            cmd = [
                ffmpeg, "-y", "-v", "quiet", "-ss", "0", "-i", filepath,
                "-vframes", "1", "-f", "image2pipe", "-vcodec", "mjpeg",
                "-vf", f"scale={size}:{size}:force_original_aspect_ratio=decrease",
                "-",
            ]
            res = subprocess.run(
                cmd, capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0,
                timeout=15,
            )
            return res.stdout if res.returncode == 0 else b''
        except Exception:
            return b''

    def stop(self):
        """Legacy combined stop: capture + mux. Used by discard/quit paths."""
        if not self._running:
            return ""
        self.stop_capture()
        return self.mux_and_save()

    def discard(self):
        with self._state_lock:
            if not self._running:
                return "<DISCARDED>"
            self._running = False
            self._is_prewarming = False
            self._preparing = False
            self._pause_event.set()

        if self._frame_thread:
            self._frame_thread.join(timeout=THREAD_JOIN_TIMEOUT)
            if self._frame_thread.is_alive():
                print("[WWRecorder] Frame thread did not stop cleanly during discard.")
        
        if self._sys_thread:
            self._sys_thread.join(timeout=2)
            
        if self._mic_thread:
            self._mic_thread.join(timeout=2)

        try:
            if self._ffmpeg_proc:
                if self._ffmpeg_proc.stdin:
                    self._ffmpeg_proc.stdin.close()
                try:
                    self._ffmpeg_proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    pass
                # Always kill on discard - we don't need the output
                try:
                    self._ffmpeg_proc.kill()
                    self._ffmpeg_proc.wait(timeout=2)
                except Exception:
                    pass
        except Exception as e:
            print(f"[WWRecorder] Discard failed: {e}")
            try:
                if self._ffmpeg_proc:
                    self._ffmpeg_proc.kill()
            except Exception as kill_err:
                print(f"[WWRecorder] Forced FFmpeg kill failed: {kill_err}")

        # Cleanup temporary files
        for p in [self._temp_vid_path, self._sys_wav_path, self._mic_wav_path]:
            if p:
                _remove_file_later(p)

        with self._state_lock:
            self._is_prewarming = False
            self._finalizing = False
        self._prepared = False
        return "<DISCARDED>"

    def pause(self):
        with self._state_lock:
            if self._paused:
                return
            self._paused = True
            if self._capture_clock_start is not None:
                self._pause_started_at = time.perf_counter()
            self._pause_event.clear()

    def resume(self):
        with self._state_lock:
            now = time.perf_counter()
            if self._paused and self._pause_started_at is not None and self._capture_clock_start is not None:
                self._pause_intervals.append((
                    max(0.0, self._pause_started_at - self._capture_clock_start),
                    max(0.0, now - self._capture_clock_start),
                ))
                self._pause_started_at = None
            self._paused = False
            self._pause_event.set()

    def cleanup_temp_dir(self, additional_dir=None):
        """Remove only stale orphaned files, retaining recent recovery media.
        Runs in a background thread to avoid blocking app startup."""
        def _cleanup():
            roots = [Path(tempfile.gettempdir())]
            if additional_dir is not None:
                roots.append(Path(additional_dir))
            for temp_dir in dict.fromkeys(roots):
                try:
                    for path in temp_dir.iterdir():
                        if path.name.startswith(TEMP_PREFIX):
                            try:
                                age = time.time() - path.stat().st_mtime
                            except OSError:
                                continue
                            if age >= TEMP_RETENTION_SECONDS:
                                _remove_file_later(str(path), attempts=1)
                except Exception as e:
                    print(f"[WWRecorder] Cleanup error in {temp_dir}: {e}")
        
        t = threading.Thread(target=_cleanup, daemon=True)
        t.start()
        return t

    def _get_native_samplerate(self, is_system: bool) -> int:
        """Query the actual native sample rate of the audio device to avoid resampling artifacts."""
        try:
            if is_system:
                # On Windows, the loopback device's native rate matches the speaker output format.
                # We can query it via the speaker's default samplerate if soundcard exposes it,
                # or fall back to a safe default.
                speaker = sc.default_speaker()
                # soundcard exposes the default sample rate on some backends
                if hasattr(speaker, 'default_samplerate') and speaker.default_samplerate:
                    return int(speaker.default_samplerate)
            else:
                mic = sc.default_microphone()
                if hasattr(mic, 'default_samplerate') and mic.default_samplerate:
                    return int(mic.default_samplerate)
        except Exception:
            pass
        # Safe fallback: 48kHz is universally supported as a request rate
        return 48000

    @staticmethod
    def _audio_device_key(device) -> str:
        """Return a stable-enough endpoint identity for default-device changes."""
        return str(getattr(device, 'id', '') or getattr(device, 'name', '') or repr(device))

    def _resolve_audio_device(self, is_system: bool):
        """Resolve the current Windows default input or output-loopback device."""
        if not is_system:
            return sc.default_microphone()
        speaker = sc.default_speaker()
        try:
            return sc.get_microphone(id=speaker.id, include_loopback=True)
        except Exception:
            loopbacks = sc.all_microphones(include_loopback=True)
            match = next(
                (item for item in loopbacks
                 if getattr(item, 'isloopback', False) and item.name == speaker.name),
                None,
            )
            if match is None:
                match = next((item for item in loopbacks if getattr(item, 'isloopback', False)), None)
            if match is None:
                raise RuntimeError(f"No loopback device is available for {speaker.name}")
            return match

    @staticmethod
    def _normalize_audio_channels(data, channels: int):
        """Keep one WAV layout even if a replacement endpoint has another layout."""
        array = np.asarray(data, dtype=np.float32)
        if array.ndim == 1:
            array = array[:, None]
        if array.shape[1] == channels:
            return array
        if channels == 1:
            return np.mean(array, axis=1, keepdims=True, dtype=np.float32)
        if array.shape[1] == 1:
            return np.repeat(array, channels, axis=1)
        if array.shape[1] > channels:
            return array[:, :channels]
        padding = np.zeros((len(array), channels - array.shape[1]), dtype=np.float32)
        return np.concatenate((array, padding), axis=1)

    def _audio_worker(self, is_system: bool, out_path: str):
        label = "System" if is_system else "Mic"
        ready_event = self._sys_audio_ready if is_system else self._mic_audio_ready
        mmcss_registration = _enter_audio_mmcss()
        # BUG-012: COM must be initialized per-thread for WASAPI on Windows
        com_initialized = False
        if sys.platform == 'win32':
            try:
                import pythoncom
                pythoncom.CoInitializeEx(pythoncom.COINIT_MULTITHREADED)
                com_initialized = True
            except Exception:
                pass  # Non-fatal: soundcard may still work via CFFI
        try:
            native_rate = self._get_native_samplerate(is_system)

            def _open_current_device(required_rate=None):
                device = self._resolve_audio_device(is_system)
                last_error = None
                candidates = (
                    ((required_rate, 2), (required_rate, None))
                    if required_rate is not None
                    else ((native_rate, 2), (48000, 2), (native_rate, None))
                )
                for rate, channels in candidates:
                    try:
                        opened = device.recorder(
                            samplerate=rate, channels=channels,
                            blocksize=max(1024, int(rate * AUDIO_DEVICE_BUFFER_SECONDS)),
                        )
                        return device, opened, rate
                    except Exception as exc:
                        last_error = exc
                raise RuntimeError(f"Cannot open {label.lower()} endpoint: {last_error}")

            mic_device = recorder = None
            try:
                mic_device, recorder, native_rate = _open_current_device()
            except Exception as initial_error:
                print(f"[WWRecorder] {label} endpoint unavailable at start: {initial_error}")

            actual_channels = (
                len(set(getattr(recorder, 'channelmap', [0, 1]))) if recorder is not None else 2
            )
            # Short WASAPI reads reduce device-buffer overrun risk and keep
            # mute/unmute changes responsive.  The former 400ms read plus
            # real-time spectral DSP could monopolize this capture thread.
            chunk_frames = max(256, int(native_rate * LIVE_AUDIO_CHUNK_SECONDS))

            write_queue: queue.Queue = queue.Queue(maxsize=50)
            write_done = threading.Event()
            writer_errors = []

            def _wav_writer():
                try:
                    with _Float32WavWriter(out_path, channels=actual_channels, samplerate=native_rate) as wf:
                        while not (write_done.is_set() and write_queue.empty()):
                            try:
                                raw_bytes = write_queue.get(timeout=0.05)
                                wf.writeframes(raw_bytes)
                            except queue.Empty:
                                continue
                except Exception as exc:
                    writer_errors.append(exc)
                    write_done.set()

            wav_thread = threading.Thread(target=_wav_writer, daemon=False)
            wav_thread.start()

            def _enqueue_audio(raw_bytes: bytes):
                if writer_errors:
                    raise RuntimeError(f"{label} WAV writer failed: {writer_errors[0]}")
                try:
                    write_queue.put(raw_bytes, timeout=2.0)
                except queue.Full as exc:
                    raise RuntimeError(f"{label} WAV writer could not keep up") from exc

            total_frames_written = 0
            discontinuity_count = 0

            try:
                unavailable_since = None
                unavailable_notified = False
                connected_once = recorder is not None
                active_device_key = self._audio_device_key(mic_device) if mic_device is not None else ''
                next_default_check = time.perf_counter() + 1.0
                ready_event.set()

                while self._running:
                    if recorder is None:
                        # Preparation and user-paused time is removed from both
                        # video and audio. Measure replacement silence only
                        # while the active recording clock is running.
                        if self._pause_event.is_set():
                            if unavailable_since is None:
                                unavailable_since = time.perf_counter()
                        else:
                            unavailable_since = None
                        if not unavailable_notified:
                            enabled = self._sys_audio_enabled if is_system else self._mic_audio_enabled
                            if enabled:
                                self._report_runtime_event(
                                    'audio_error',
                                    f"{label} audio device disconnected. Waiting for a Windows default device.",
                                )
                            unavailable_notified = True
                        time.sleep(0.35)
                        try:
                            mic_device, recorder, replacement_rate = _open_current_device(native_rate)
                            active_device_key = self._audio_device_key(mic_device)
                            if unavailable_since is not None and self._pause_event.is_set():
                                gap_frames = max(0, int((time.perf_counter() - unavailable_since) * native_rate))
                                if gap_frames:
                                    _enqueue_audio(np.zeros((gap_frames, actual_channels), dtype=np.float32).tobytes())
                                    total_frames_written += gap_frames
                            was_unavailable = unavailable_notified
                            if connected_once or was_unavailable:
                                self._report_runtime_event(
                                    'audio_reconnected',
                                    f"{label} audio switched to the current Windows default device.",
                                )
                            connected_once = True
                            unavailable_since = None
                            unavailable_notified = False
                            next_default_check = time.perf_counter() + 1.0
                        except Exception:
                            recorder = None
                        continue

                    switch_to_default = False
                    try:
                        with recorder as mic:
                            while self._running:
                                try:
                                    data, glitches = _read_audio_chunk(mic, chunk_frames)
                                    discontinuity_count += glitches
                                except Exception as dev_err:
                                    print(f"[WWRecorder] {label} audio device error: {dev_err}")
                                    unavailable_since = time.perf_counter()
                                    break

                                now = time.perf_counter()
                                if now >= next_default_check:
                                    next_default_check = now + 1.0
                                    try:
                                        current_default = self._resolve_audio_device(is_system)
                                        if self._audio_device_key(current_default) != active_device_key:
                                            switch_to_default = True
                                            unavailable_since = now
                                            break
                                    except Exception:
                                        pass

                                if not self._pause_event.is_set():
                                    continue

                                is_enabled = self._sys_audio_enabled if is_system else self._mic_audio_enabled
                                data = self._normalize_audio_channels(data, actual_channels)
                                if not is_enabled:
                                    data = np.zeros_like(data)
                                _enqueue_audio(data.tobytes())
                                total_frames_written += len(data)
                    finally:
                        recorder = None
                    if switch_to_default:
                        print(f"[WWRecorder] {label} Windows default endpoint changed; reopening capture.")
                        unavailable_notified = True

            finally:
                if is_system:
                    self._sys_audio_discontinuities = discontinuity_count
                else:
                    self._mic_audio_discontinuities = discontinuity_count
                print(
                    f"[WWRecorder] {label} audio finished: "
                    f"{total_frames_written} frames, {discontinuity_count} WASAPI discontinuities"
                )
                write_done.set()
                wav_thread.join(timeout=15)
                if wav_thread.is_alive():
                    raise RuntimeError(f"{label} WAV writer did not stop")
                if writer_errors:
                    raise RuntimeError(f"{label} WAV writer failed: {writer_errors[0]}")

        except Exception as e:
            import traceback
            print(f"Audio Error ({label}):", e)
            enabled = self._sys_audio_enabled if is_system else self._mic_audio_enabled
            if enabled:
                self._report_runtime_event('audio_error', f"{label} audio error: {e}")
            traceback.print_exc()
        finally:
            # Never strand prepare() if a device is absent or fails to open.
            ready_event.set()
            _leave_audio_mmcss(mmcss_registration)
            # BUG-012: Release COM resources
            if com_initialized:
                try:
                    import pythoncom
                    pythoncom.CoUninitialize()
                except Exception:
                    pass

    def _frame_worker(self):
        segments = self._capture_segments
        monitor = {"top": segments[0]["src_top"], "left": segments[0]["src_left"],
                   "width": segments[0]["src_width"], "height": segments[0]["src_height"]}

        # Render the cursor into a native BGRA DIB. Windows then applies its
        # own AND/XOR/alpha rules directly to the captured pixels; attempting
        # to infer those masks from two screenshots corrupted every cursor.
        hdc_screen = None
        cursor_dc = cursor_bitmap = cursor_previous = cursor_pixels = None
        try:
            hdc_screen, cursor_dc, cursor_bitmap, cursor_previous, cursor_pixels = _acquire_cursor_surface()
        except Exception:
            pass

        with mss.mss() as sct:
            deadline = time.perf_counter()

            while self._running:
                now = time.perf_counter()

                sleep_time = deadline - now
                if sleep_time > 0:
                    time.sleep(sleep_time)

                if not self._pause_event.is_set():
                    deadline += FRAME_INTERVAL
                    continue

                with self._state_lock:
                    if self._capture_clock_start is None:
                        self._capture_clock_start = time.perf_counter()

                try:
                    canvas = np.zeros((self._region["height"], self._region["width"], 4), dtype=np.uint8)
                    for seg in segments:
                        src_monitor = {"top": seg["src_top"], "left": seg["src_left"],
                                       "width": seg["src_width"], "height": seg["src_height"]}
                        img = sct.grab(src_monitor)
                        part = np.frombuffer(img.raw, dtype=np.uint8).reshape(
                            (seg["src_height"], seg["src_width"], 4)
                        )
                        if (seg["src_width"], seg["src_height"]) != (seg["dst_width"], seg["dst_height"]):
                            yi = np.minimum((np.arange(seg["dst_height"]) * seg["src_height"] / seg["dst_height"]).astype(int), seg["src_height"] - 1)
                            xi = np.minimum((np.arange(seg["dst_width"]) * seg["src_width"] / seg["dst_width"]).astype(int), seg["src_width"] - 1)
                            part = part[yi[:, None], xi]
                        x1, y1 = seg["dst_left"], seg["dst_top"]
                        x2 = min(self._region["width"], x1 + part.shape[1])
                        y2 = min(self._region["height"], y1 + part.shape[0])
                        canvas[y1:y2, x1:x2] = part[:y2-y1, :x2-x1]
                    img = None
                    # MSS already owns a writable BGRA byte buffer.  A view avoids
                    # copying the entire desktop once before cursor composition;
                    # tobytes() below performs the one unavoidable pipe copy.
                    bgra = canvas

                    # Composite native cursor if it's inside the capture region
                    try:
                        cursor_flags, hcursor, (ccx, ccy) = win32gui.GetCursorInfo()
                        if cursor_flags == win32con.CURSOR_SHOWING and hdc_screen is not None:
                            # Cursor position is mapped through the native
                            # segment containing it into output-canvas pixels.
                            cursor_seg = next((s for s in segments if
                                s["src_left"] <= ccx < s["src_left"] + s["src_width"] and
                                s["src_top"] <= ccy < s["src_top"] + s["src_height"]), None)
                            if cursor_seg:
                                rx = cursor_seg["dst_left"] + round((ccx - cursor_seg["src_left"]) * cursor_seg["dst_width"] / cursor_seg["src_width"])
                                ry = cursor_seg["dst_top"] + round((ccy - cursor_seg["src_top"]) * cursor_seg["dst_height"] / cursor_seg["src_height"])
                            else:
                                rx = ry = -1

                            if 0 <= rx < self._region["width"] and 0 <= ry < self._region["height"]:
                                cursor_size = CURSOR_CANVAS_SIZE
                                mask_bitmap = color_bitmap = None
                                try:
                                    _icon, hx, hy, mask_bitmap, color_bitmap = win32gui.GetIconInfo(hcursor)
                                    start_y, start_x = ry - hy, rx - hx
                                    y1, x1 = max(0, start_y), max(0, start_x)
                                    y2 = min(self._region["height"], start_y + cursor_size)
                                    x2 = min(self._region["width"], start_x + cursor_size)
                                    if x1 < x2 and y1 < y2:
                                        cy1, cy2 = y1 - start_y, y2 - start_y
                                        cx1, cx2 = x1 - start_x, x2 - start_x
                                        cursor_pixels.fill(0)
                                        cursor_pixels[cy1:cy2, cx1:cx2] = bgra[y1:y2, x1:x2]
                                        win32gui.DrawIconEx(cursor_dc, 0, 0, hcursor, 0, 0, 0, None, 0x0003)
                                        bgra[y1:y2, x1:x2] = cursor_pixels[cy1:cy2, cx1:cx2]
                                finally:
                                    if mask_bitmap: win32gui.DeleteObject(mask_bitmap)
                                    if color_bitmap: win32gui.DeleteObject(color_bitmap)

                    except Exception:
                        pass

                    # Send BGRA frame (contiguous numpy array — fast tobytes)
                    raw = bgra.tobytes()

                    # BUG-004: Thread-safe stdin write with graceful broken pipe handling
                    with self._stdin_lock:
                        if not self._running:
                            break
                        try:
                            self._ffmpeg_proc.stdin.write(raw)
                        except (BrokenPipeError, OSError, ValueError):
                            with self._state_lock:
                                self._capture_failed = self._running
                            break

                    with self._state_lock:
                        self._captured_frames += 1

                    # Never catch up here by injecting the same stale frame.
                    # Rawvideo has no timestamps, so finalization stretches the
                    # captured-frame timeline to the measured active wall time
                    # before producing CFR 30. Skip missed scheduler slots and
                    # capture the newest screen state next.
                    deadline, missed = _next_frame_deadline(deadline, time.perf_counter())
                    if missed:
                        with self._state_lock:
                            self._dropped_frame_slots += missed

                except Exception as e:
                    print("Frame error:", e)
                    with self._state_lock:
                        self._capture_failed = self._running
                        self._last_error = str(e)
                    break

            if hdc_screen is not None:
                try:
                    win32gui.ReleaseDC(0, hdc_screen)
                except Exception:
                    pass
            if cursor_dc is not None:
                try:
                    win32gui.SelectObject(cursor_dc, cursor_previous)
                    win32gui.DeleteDC(cursor_dc)
                except Exception:
                    pass
            if cursor_bitmap is not None:
                try:
                    win32gui.DeleteObject(cursor_bitmap)
                except Exception:
                    pass
