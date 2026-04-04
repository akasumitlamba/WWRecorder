import os
import sys
import time
import subprocess
import threading
import warnings
import tempfile
from datetime import datetime
from pathlib import Path

import mss
import numpy as np
import soundcard as sc
import wave

# Suppress harmless soundcard discontinuity warnings (happens often on Windows WASAPI loopback during silence)
warnings.filterwarnings("ignore", message="data discontinuity in recording")

import win32gui
import win32ui
import win32con

TARGET_FPS = 30
FRAME_INTERVAL = 1.0 / TARGET_FPS

TEMP_PREFIX = "WWRecorder_temp_"


def get_ffmpeg_path():
    base = os.path.dirname(os.path.abspath(__file__))
    ffmpeg = os.path.join(base, "ffmpeg.exe")
    return ffmpeg if os.path.isfile(ffmpeg) else "ffmpeg"


class RecordingEngine:
    def __init__(self):
        self._running = False
        self._paused = False
        self._pause_event = threading.Event()
        self._pause_event.set()

        self._ffmpeg_proc = None
        self._frame_thread = None
        self._sys_thread = None
        self._mic_thread = None
        self._is_prewarming = False

        self._sys_audio_enabled = False
        self._mic_audio_enabled = False

        self._region = {}
        self._output_path = ""
        self._temp_vid_path = ""
        self._sys_wav_path = ""
        self._mic_wav_path = ""

        self.cleanup_temp_dir()

    def is_recording(self):
        return self._running and not self._is_prewarming

    def is_prewarming(self):
        return self._is_prewarming

    def is_paused(self):
        return self._paused
    # --- ADD THIS BELOW existing methods ---

    def set_system_audio(self, enabled: bool):
        self._sys_audio_enabled = enabled

    def get_system_audio(self) -> bool:
        return self._sys_audio_enabled

    def set_mic(self, enabled: bool):
        self._mic_audio_enabled = enabled

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
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        Path(output_folder).mkdir(parents=True, exist_ok=True)
        out_path = os.path.join(output_folder, f"Screenshot_{timestamp}.png")

        monitor = {
            "top": region["top"],
            "left": region["left"],
            "width": region["width"],
            "height": region["height"],
        }

        with mss.mss() as sct:
            img = sct.grab(monitor)
            # Convert BGRA to RGB PIL Image and save
            pil_img = Image.frombytes("RGB", img.size, img.rgb)
            pil_img.save(out_path, "PNG")

        return out_path

    def prepare(self, region, output_folder, audio_config=None):
        """
        Background initialization: Finds FFmpeg, opens audio streams,
        and starts threads in a PAUSED state. This eliminates lag when 
        the user finally clicks 'Start'.
        """
        if self._running:
            if self._is_prewarming:
                self.discard() # Cleanup former pre-warm state
            else:
                return False

        if audio_config:
            self._sys_audio_enabled = audio_config.get("system_audio", True)
            self._mic_audio_enabled = audio_config.get("mic", False)

        # ✅ FORCE EVEN DIMENSIONS 
        w = region["width"] if region["width"] % 2 == 0 else region["width"] - 1
        h = region["height"] if region["height"] % 2 == 0 else region["height"] - 1

        self._region = {
            "top": region["top"],
            "left": region["left"],
            "width": w,
            "height": h,
        }

        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        Path(output_folder).mkdir(parents=True, exist_ok=True)

        self._output_path = os.path.join(output_folder, f"Recording_{timestamp}.mkv")
        
        temp_dir = tempfile.gettempdir()
        self._temp_vid_path = os.path.join(temp_dir, f"{TEMP_PREFIX}vid_{timestamp}.mkv")
        self._sys_wav_path = os.path.join(temp_dir, f"{TEMP_PREFIX}sys_{timestamp}.wav")
        self._mic_wav_path = os.path.join(temp_dir, f"{TEMP_PREFIX}mic_{timestamp}.wav")

        ffmpeg = get_ffmpeg_path()
        cmd = [
            ffmpeg, "-y", "-f", "rawvideo", "-vcodec", "rawvideo", "-pix_fmt", "bgr24",
            "-s", f"{w}x{h}", "-r", str(TARGET_FPS), "-i", "pipe:0",
            # ── Highly Compressed Live Encode ──
            # veryfast + crf 30 + keyint=120 achieves tiny file sizes (down to 15-20% of ultrafast)
            # while remaining fast enough not to lag the recording thread.
            "-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency", 
            "-crf", "30", "-x264opts", "keyint=120:min-keyint=30", "-pix_fmt", "yuv420p",
            self._temp_vid_path,
        ]

        try:
            self._ffmpeg_proc = subprocess.Popen(
                cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
            )
        except Exception as e:
            print("[WWRecorder] FFmpeg prep error:", e)
            return False

        self._running = True
        self._paused = True
        self._is_prewarming = True
        self._pause_event.clear()

        # Start background workers (they will idle while _pause_event is clear)
        self._frame_thread = threading.Thread(target=self._frame_worker, daemon=True)
        self._frame_thread.start()

        self._sys_thread = threading.Thread(
            target=self._audio_worker, args=(True, self._sys_wav_path), daemon=True
        )
        self._sys_thread.start()

        self._mic_thread = threading.Thread(
            target=self._audio_worker, args=(False, self._mic_wav_path), daemon=True
        )
        self._mic_thread.start()

        self._prepared = True
        return True

    def start(self, region, output_folder, audio_config=None):
        """Start a fresh recording. Discards any leftover pre-warm state first."""
        self._is_prewarming = False

        # Always start clean — discard any stale pre-warm or prior state
        if self._running:
            self.discard()
            
        if not self.prepare(region, output_folder, audio_config):
            return False
        self._is_prewarming = False  # Ensure we're in active mode after prepare
        self.resume()
        return True

    def stop_capture(self):
        """Phase 1: Stop all capture threads and close FFmpeg pipe. Fast — safe to call from UI."""
        if not self._running:
            return

        self._running = False
        self._pause_event.set()

        if self._frame_thread:
            self._frame_thread.join()

        if self._sys_thread:
            self._sys_thread.join(timeout=2)

        if self._mic_thread:
            self._mic_thread.join(timeout=2)

        try:
            if self._ffmpeg_proc:
                self._ffmpeg_proc.stdin.close()
                try:
                    self._ffmpeg_proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._ffmpeg_proc.kill()
                    self._ffmpeg_proc.wait(timeout=2)
        except Exception:
            try:
                if self._ffmpeg_proc:
                    self._ffmpeg_proc.kill()
            except Exception:
                pass

    def mux_and_save(self) -> str:
        """Phase 2: Mux audio+video into final file. Slow — run in a background thread."""
        ffmpeg = get_ffmpeg_path()
        merge_cmd = [ffmpeg, "-y", "-i", self._temp_vid_path]

        has_sys = os.path.exists(self._sys_wav_path) and os.path.getsize(self._sys_wav_path) > 100
        has_mic = os.path.exists(self._mic_wav_path) and os.path.getsize(self._mic_wav_path) > 100

        if has_sys:
            merge_cmd.extend(["-i", self._sys_wav_path])
        if has_mic:
            merge_cmd.extend(["-i", self._mic_wav_path])

        if has_sys and has_mic:
            merge_cmd.extend([
                "-filter_complex", "[1:a][2:a]amix=inputs=2:duration=longest:normalize=0[a]",
                "-map", "0:v", "-map", "[a]",
                "-c:v", "copy", "-c:a", "aac", "-b:a", "96k"
            ])
        elif has_sys or has_mic:
            merge_cmd.extend([
                "-map", "0:v", "-map", "1:a",
                "-c:v", "copy", "-c:a", "aac", "-b:a", "96k"
            ])
        else:
            merge_cmd.extend(["-c", "copy"])

        merge_cmd.append(self._output_path)

        try:
            subprocess.run(merge_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW if sys.platform=='win32' else 0)
        except Exception as e:
            print("Muxing error:", e)

        # Cleanup temporary files
        for p in [self._temp_vid_path, self._sys_wav_path, self._mic_wav_path]:
            if os.path.exists(p):
                try:
                    os.remove(p)
                except:
                    pass

        return self._output_path

    def stop(self):
        """Legacy combined stop: capture + mux. Used by discard/quit paths."""
        if not self._running:
            return ""
        self.stop_capture()
        return self.mux_and_save()

    def discard(self):
        if not self._running:
            return "<DISCARDED>"

        self._running = False
        self._pause_event.set()

        if self._frame_thread:
            self._frame_thread.join()
        
        if self._sys_thread:
            self._sys_thread.join(timeout=2)
            
        if self._mic_thread:
            self._mic_thread.join(timeout=2)

        try:
            if self._ffmpeg_proc:
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
        except Exception:
            try:
                if self._ffmpeg_proc:
                    self._ffmpeg_proc.kill()
            except Exception:
                pass

        # Cleanup temporary files
        for p in [self._temp_vid_path, self._sys_wav_path, self._mic_wav_path]:
            if os.path.exists(p):
                try:
                    os.remove(p)
                except:
                    pass

        self._is_prewarming = False
        self._prepared = False
        return "<DISCARDED>"

    def pause(self):
        self._paused = True
        self._pause_event.clear()

    def resume(self):
        self._paused = False
        self._pause_event.set()

    def cleanup_temp_dir(self):
        """Removes all orphaned temporary files from previous sessions."""
        temp_dir = tempfile.gettempdir()
        try:
            for filename in os.listdir(temp_dir):
                if filename.startswith(TEMP_PREFIX):
                    try:
                        os.remove(os.path.join(temp_dir, filename))
                    except:
                        pass
        except Exception as e:
            print(f"[WWRecorder] Cleanup error: {e}")

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

    def _audio_worker(self, is_system: bool, out_path: str):
        label = "System" if is_system else "Mic"
        try:
            if is_system:
                speaker = sc.default_speaker()
                # Safe loopback retrieval: Try ID match first, fallback to name match
                try:
                    mic_device = sc.get_microphone(id=speaker.id, include_loopback=True)
                except Exception:
                    mics = sc.all_microphones(include_loopback=True)
                    mic_device = next((m for m in mics if m.isloopback and m.name == speaker.name), None)
                    if not mic_device:
                        # Sometimes loopback names have extra decorations
                        mic_device = next((m for m in mics if m.isloopback), None)
                        
                if not mic_device:
                    print(f"[WWRecorder] No system loopback device found for speaker: {speaker.name}")
                    return
            else:
                mic_device = sc.default_microphone()

            # ── Multi-Tier Fallback Mechanism for Audio Hardware Support ──
            native_rate = self._get_native_samplerate(is_system)
            recorder = None
            try:
                # 1. Try absolute native rate
                recorder = mic_device.recorder(samplerate=native_rate, channels=2)
            except Exception as e_native:
                print(f"[WWRecorder] Native rate failed ({native_rate}Hz): {e_native}. Trying 48000Hz fallback.")
                try:
                    # 2. Try standard 48kHz
                    recorder = mic_device.recorder(samplerate=48000, channels=2)
                    native_rate = 48000
                except Exception as e_standard:
                    print(f"[WWRecorder] Standard rate failed: {e_standard}. Trying default settings.")
                    # 3. Try OS absolute default
                    recorder = mic_device.recorder()
                    # Query actual sample rate post-initialization if possible
                    native_rate = getattr(recorder, 'samplerate', 48000)

            # Chunk size: ~100ms worth of frames (balanced: resilient to GIL stalls without latency)
            chunk_frames = int(native_rate * 0.1)

            with recorder as mic, wave.open(out_path, 'wb') as wf:
                 
                wf.setnchannels(2)
                wf.setsampwidth(2)
                wf.setframerate(native_rate)

                wall_clock_start = None  # Set when recording actually begins
                total_frames_written = 0
                
                while self._running:
                    # ── Capture audio (may block during silence on WASAPI loopback) ──
                    try:
                        data = mic.record(numframes=chunk_frames)
                    except Exception as dev_err:
                        # Device disconnected or errored — write silence for remaining time and exit
                        print(f"[WWRecorder] {label} audio device error: {dev_err}")
                        if wall_clock_start is not None:
                            elapsed = time.perf_counter() - wall_clock_start
                            expected_frames = int(elapsed * native_rate)
                            missing = expected_frames - total_frames_written
                            if missing > 0:
                                silence = np.zeros((missing, 2), dtype=np.int16)
                                wf.writeframes(silence.tobytes())
                        break
                    
                    # ── DISCARD if we are in pre-warm / paused state ──
                    if not self._pause_event.is_set():
                        # Keep wall_clock completely paused by shifting the start time forward
                        if wall_clock_start is not None:
                            wall_clock_start = time.perf_counter() - (total_frames_written / native_rate)
                        continue

                    # Track wall-clock time from first active frame
                    if wall_clock_start is None:
                        wall_clock_start = time.perf_counter()

                    # ── Real-Time WASAPI Silence Padding (Fixes Audio Sync) ──
                    # WASAPI physically drops packets (blocks) when no sound plays.
                    # We compare time.perf_counter() to total frames written.
                    # If we fell behind, WASAPI blocked during silence. We must insert
                    # the exact missing timeline gap BEFORE writing the new data chunk.
                    now = time.perf_counter()
                    expected_total = int((now - wall_clock_start) * native_rate)
                    missing = expected_total - total_frames_written - len(data)

                    # Only pad if gap > 1 chunk (to avoid micro-jitter corrections)
                    if missing > chunk_frames:
                        silence = np.zeros((missing, 2), dtype=np.int16)
                        wf.writeframes(silence.tobytes())
                        total_frames_written += missing

                    # ── Muting (Dynamic Recording Toggle) ──
                    is_enabled = self._sys_audio_enabled if is_system else self._mic_audio_enabled
                    if not is_enabled:
                        data = np.zeros_like(data)
                    else:
                        # ── Transparent Linear Gain ──
                        gain = 1.8 if is_system else 2.5
                        data = data * gain
                        np.clip(data, -1.0, 1.0, out=data)

                    data_int16 = (data * 32767.0).astype(np.int16)
                    wf.writeframes(data_int16.tobytes())
                    total_frames_written += len(data)

                # End padding just to perfectly cap off the file boundary
                if wall_clock_start is not None:
                    elapsed = time.perf_counter() - wall_clock_start
                    expected_frames = int(elapsed * native_rate)
                    missing = expected_frames - total_frames_written
                    if missing > 0:
                        silence = np.zeros((missing, 2), dtype=np.int16)
                        wf.writeframes(silence.tobytes())
                    
        except Exception as e:
            import traceback
            print(f"Audio Error ({label}):", e)
            traceback.print_exc()

    def _frame_worker(self):
        monitor = {
            "top": self._region["top"],
            "left": self._region["left"],
            "width": self._region["width"],
            "height": self._region["height"],
        }

        # Only record native cursor if pywin32 is loaded natively
        hdc_screen = None
        try:
            hdc_screen = win32gui.GetDC(0)
            hdc = win32ui.CreateDCFromHandle(hdc_screen)

            hdc_b = hdc.CreateCompatibleDC()
            bmp_b = win32ui.CreateBitmap()
            bmp_b.CreateCompatibleBitmap(hdc, 64, 64)
            hdc_b.SelectObject(bmp_b)

            hdc_w = hdc.CreateCompatibleDC()
            bmp_w = win32ui.CreateBitmap()
            bmp_w.CreateCompatibleBitmap(hdc, 64, 64)
            hdc_w.SelectObject(bmp_w)

            brush_b = win32gui.GetStockObject(win32con.BLACK_BRUSH)
            brush_w = win32gui.GetStockObject(win32con.WHITE_BRUSH)
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

                try:
                    img = sct.grab(monitor)
                    # Native BGRA buffer from mss — fast numpy view via __array_interface__
                    bgra = np.array(img, dtype=np.uint8)

                    # Check if cursor is in the capture region
                    try:
                        cursor_flags, hcursor, (ccx, ccy) = win32gui.GetCursorInfo()
                        if cursor_flags == win32con.CURSOR_SHOWING and hdc_screen is not None:
                            rx = ccx - monitor["left"]
                            ry = ccy - monitor["top"]

                            if 0 <= rx < monitor["width"] and 0 <= ry < monitor["height"]:
                                info = win32gui.GetIconInfo(hcursor)
                                hx, hy = info[1], info[2]

                                hw_b = hdc_b.GetSafeHdc()
                                hw_w = hdc_w.GetSafeHdc()

                                win32gui.FillRect(hw_b, (0, 0, 64, 64), brush_b)
                                win32gui.FillRect(hw_w, (0, 0, 64, 64), brush_w)

                                win32gui.DrawIconEx(hw_b, 0, 0, hcursor, 0, 0, 0, None, 0x0003)
                                win32gui.DrawIconEx(hw_w, 0, 0, hcursor, 0, 0, 0, None, 0x0003)

                                # ── Integer-only alpha blend (no float32) ──
                                B = np.frombuffer(bmp_b.GetBitmapBits(True), dtype=np.uint8).reshape((64, 64, 4))
                                W = np.frombuffer(bmp_w.GetBitmapBits(True), dtype=np.uint8).reshape((64, 64, 4))

                                # Keep in BGR space — matches bgr24 pipe
                                B3 = B[:, :, :3]
                                W3 = W[:, :, :3]

                                # Alpha per pixel: a = 255 - (W - B)
                                alpha = (255 - (W3.astype(np.int16) - B3.astype(np.int16))).astype(np.uint8)

                                start_y, start_x = ry - hy, rx - hx
                                y1 = max(0, start_y)
                                y2 = min(monitor["height"], start_y + 64)
                                x1 = max(0, start_x)
                                x2 = min(monitor["width"], start_x + 64)

                                if x1 < x2 and y1 < y2:
                                    cy1, cy2 = y1 - start_y, y2 - start_y
                                    cx1, cx2 = x1 - start_x, x2 - start_x

                                    a = alpha[cy1:cy2, cx1:cx2].astype(np.uint16)
                                    b = B3[cy1:cy2, cx1:cx2].astype(np.uint16)
                                    bg = bgra[y1:y2, x1:x2, :3].astype(np.uint16)

                                    inv_a = 255 - a
                                    out = b + (bg * inv_a + 127) // 255
                                    bgra[y1:y2, x1:x2, :3] = np.clip(out, 0, 255).astype(np.uint8)

                                if info[3]: win32gui.DeleteObject(info[3])
                                if info[4]: win32gui.DeleteObject(info[4])

                    except Exception:
                        pass

                    # Drop Alpha channel → BGR for bgr24 pipe
                    raw = bgra[:, :, :3].tobytes()

                    self._ffmpeg_proc.stdin.write(raw)

                    # Prevent video/audio desync: feed duplicate frames if we fell behind
                    deadline += FRAME_INTERVAL
                    while time.perf_counter() > deadline and self._running and self._pause_event.is_set():
                        self._ffmpeg_proc.stdin.write(raw)
                        deadline += FRAME_INTERVAL

                except Exception as e:
                    print("Frame error:", e)
                    break

            if hdc_screen is not None:
                try: win32gui.ReleaseDC(0, hdc_screen)
                except: pass
