import os
import sys
import time
import subprocess
import threading
import warnings
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

        self._sys_audio_enabled = False
        self._mic_audio_enabled = False

        self._region = {}
        self._output_path = ""
        self._temp_vid_path = ""
        self._sys_wav_path = ""
        self._mic_wav_path = ""

    def is_recording(self):
        return self._running

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

    def start(self, region, output_folder, audio_config=None):
        if self._running:
            return False

        if audio_config:
            self._sys_audio_enabled = audio_config.get("system_audio", True)
            self._mic_audio_enabled = audio_config.get("mic", False)

        # ✅ FORCE EVEN DIMENSIONS (CRITICAL FIX)
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
        self._temp_vid_path = os.path.join(output_folder, f"temp_vid_{timestamp}.mkv")
        self._sys_wav_path = os.path.join(output_folder, f"temp_sys_{timestamp}.wav")
        self._mic_wav_path = os.path.join(output_folder, f"temp_mic_{timestamp}.wav")

        ffmpeg = get_ffmpeg_path()

        cmd = [
            ffmpeg,
            "-y",
            "-f", "rawvideo",
            "-vcodec", "rawvideo",
            "-pix_fmt", "bgr24",
            "-s", f"{w}x{h}",
            "-r", str(TARGET_FPS),
            "-i", "pipe:0",
            "-c:v", "libx264",
            "-preset", "superfast",   # slightly slower than ultrafast, massively better file size
            "-crf", "28",             # lower quality, much smaller size
            "-pix_fmt", "yuv420p",
            self._temp_vid_path,
        ]

        try:
            self._ffmpeg_proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
            )
        except Exception as e:
            print("FFmpeg error:", e)
            return False

        self._running = True
        self._paused = False
        self._pause_event.set()

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

        return True

    def stop(self):
        if not self._running:
            return ""

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
                self._ffmpeg_proc.wait(timeout=5)
        except:
            pass

        # === MUX AUDIO AND VIDEO ===
        ffmpeg = get_ffmpeg_path()
        merge_cmd = [ffmpeg, "-y", "-i", self._temp_vid_path]

        has_sys = os.path.exists(self._sys_wav_path) and os.path.getsize(self._sys_wav_path) > 100
        has_mic = os.path.exists(self._mic_wav_path) and os.path.getsize(self._mic_wav_path) > 100

        if has_sys:
            merge_cmd.extend(["-i", self._sys_wav_path])
        if has_mic:
            merge_cmd.extend(["-i", self._mic_wav_path])

        if has_sys and has_mic:
            # Both audio streams present
            # normalize=0 prevents amix from reducing the total volume!
            merge_cmd.extend([
                "-filter_complex", "[1:a][2:a]amix=inputs=2:duration=longest:normalize=0[a]",
                "-map", "0:v", "-map", "[a]",
                "-c:v", "copy", "-c:a", "aac", "-b:a", "192k"
            ])
        elif has_sys or has_mic:
            # Only one audio stream present (it will be input index 1)
            merge_cmd.extend([
                "-map", "0:v", "-map", "1:a",
                "-c:v", "copy", "-c:a", "aac", "-b:a", "192k"
            ])
        else:
            # No audio streams
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

    def pause(self):
        self._paused = True
        self._pause_event.clear()

    def resume(self):
        self._paused = False
        self._pause_event.set()

    def _audio_worker(self, is_system: bool, out_path: str):
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

            with mic_device.recorder(samplerate=48000, channels=2) as mic, \
                 wave.open(out_path, 'wb') as wf:
                 
                wf.setnchannels(2)
                wf.setsampwidth(2)
                wf.setframerate(48000)
                
                while self._running:
                    # Record seamlessly in small chunks without strict manual blocking sizes
                    data = mic.record(numframes=2400)
                    
                    if not self._pause_event.is_set():
                        continue
                        
                    is_enabled = self._sys_audio_enabled if is_system else self._mic_audio_enabled
                    if not is_enabled:
                        data = np.zeros_like(data)
                    else:
                        if not is_system:
                            # Boost microphone
                            data = data * 2.5
                        data = np.clip(data, -1.0, 1.0)
                        
                    data_int16 = (data * 32767.0).astype(np.int16)
                    wf.writeframes(data_int16.tobytes())
                    
        except Exception as e:
            import traceback
            print(f"Audio Error ({'System' if is_system else 'Mic'}):", e)
            traceback.print_exc()

    def _frame_worker(self):
        monitor = {
            "top": self._region["top"],
            "left": self._region["left"],
            "width": self._region["width"],
            "height": self._region["height"],
        }
        
        # Only record native cursor if pywin32 is loaded natively
        # Note: We draw the hardware cursor onto the raw frame pixels

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
                    bgra = np.array(img, dtype=np.uint8)
                    
                    try:
                        cursor_flags, hcursor, (cx, cy) = win32gui.GetCursorInfo()
                        if cursor_flags == win32con.CURSOR_SHOWING and hdc_screen is not None:
                            rx = cx - monitor["left"]
                            ry = cy - monitor["top"]
                            
                            if 0 <= rx < monitor["width"] and 0 <= ry < monitor["height"]:
                                info = win32gui.GetIconInfo(hcursor)
                                hx, hy = info[1], info[2]
                                
                                hw_b = hdc_b.GetSafeHdc()
                                hw_w = hdc_w.GetSafeHdc()
                                
                                win32gui.FillRect(hw_b, (0, 0, 64, 64), brush_b)
                                win32gui.FillRect(hw_w, (0, 0, 64, 64), brush_w)
                                
                                win32gui.DrawIconEx(hw_b, 0, 0, hcursor, 0, 0, 0, None, 0x0003)
                                win32gui.DrawIconEx(hw_w, 0, 0, hcursor, 0, 0, 0, None, 0x0003)
                                
                                B = np.frombuffer(bmp_b.GetBitmapBits(True), dtype=np.uint8).reshape((64, 64, 4))
                                W = np.frombuffer(bmp_w.GetBitmapBits(True), dtype=np.uint8).reshape((64, 64, 4))
                                
                                B_f = B[:, :, :3].astype(np.float32)
                                W_f = W[:, :, :3].astype(np.float32)
                                
                                inv_alpha = (W_f - B_f) / 255.0
                                
                                start_y, start_x = ry - hy, rx - hx
                                
                                y1 = max(0, start_y)
                                y2 = min(monitor["height"], start_y + 64)
                                x1 = max(0, start_x)
                                x2 = min(monitor["width"], start_x + 64)
                                
                                if x1 < x2 and y1 < y2:
                                    cy1, cy2 = y1 - start_y, y2 - start_y
                                    cx1, cx2 = x1 - start_x, x2 - start_x
                                    
                                    b_patch = B_f[cy1:cy2, cx1:cx2]
                                    inv_a_patch = inv_alpha[cy1:cy2, cx1:cx2]
                                    bg_patch = bgra[y1:y2, x1:x2, :3].astype(np.float32)
                                    
                                    out = b_patch + bg_patch * inv_a_patch
                                    bgra[y1:y2, x1:x2, :3] = np.clip(out, 0, 255).astype(np.uint8)

                                if info[3]: win32gui.DeleteObject(info[3])
                                if info[4]: win32gui.DeleteObject(info[4])
                                    
                    except Exception:
                        pass
                        
                    # Drop the Alpha channel for x264
                    frame = bgra[:, :, :3]
                    raw = frame.tobytes()

                    self._ffmpeg_proc.stdin.write(raw)
                    
                    # Prevent video/audio desync: If frame capture/encoding took too long,
                    # feed duplicate frames to keep the timeline perfectly in sync with the wall clock.
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
