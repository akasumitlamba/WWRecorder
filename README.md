# WWRecorder — World Wide Recorder

High-performance, lightweight screen recorder for Windows optimised for
low-end hardware (Intel i3, integrated graphics). Produces compact, crash-
resilient `.mkv` files via FFmpeg.

---

## Features

| Feature         | Detail                                                                            |
| --------------- | --------------------------------------------------------------------------------- |
| Codec           | H.264 `libx264` · `ultrafast` preset · CRF 23                                     |
| Container       | `.mkv` (recoverable if app/system crashes)                                        |
| Frame rate      | Hard-coded 30 FPS (stable on old CPUs)                                            |
| System audio    | WASAPI loopback via `soundcard`                                                   |
| Microphone      | Default mic via `soundcard`                                                       |
| Audio toggle    | Real-time · no restart · zero-latency mute                                        |
| Pause           | Frozen-frame technique — single continuous file, A/V sync preserved               |
| Pill UI         | Borderless, always-on-top, invisible to screen capture (`WDA_EXCLUDEFROMCAPTURE`) |
| Global hotkey   | `Shift+Backspace` (configurable) — works when minimised                           |
| Auto-start      | Windows Registry `HKCU\...\Run`                                                   |
| Single instance | Named mutex guard                                                                 |
| Installer       | Inno Setup 6 · per-user · no UAC prompt                                           |

---

## Project Structure

```
WWRecorder/
├── main.py               # App entry: tray, hotkeys, registry, orchestration
├── recorder.py           # Engine: mss → FFmpeg pipe, AudioMixer, A/V merge
├── ui_elements.py        # SelectionOverlay, PillWidget, SettingsWindow
├── wwrecorder.spec       # PyInstaller spec
├── installer_config.iss  # Inno Setup 6 installer script
├── requirements.txt
└── assets/
    ├── icon.ico          # ← You must provide this (256×256 recommended)
    └── icon.png          # Optional
```

---

## Quick Start (Development)

### 1 — Install dependencies

```powershell
pip install -r requirements.txt
```

### 2 — Obtain FFmpeg

Download a static Windows build from https://ffmpeg.org/download.html  
and place `ffmpeg.exe` in the project root **or** on your system PATH.

### 3 — Run

```powershell
python main.py
```

WWRecorder appears in the system tray.  
Double-click the tray icon **or** press `Shift+Backspace` to start.

---

## Building a Distributable

### Step 1 — PyInstaller

```powershell
# Ensure ffmpeg.exe is in the project root
pyinstaller wwrecorder.spec
```

Output: `dist\WWRecorder\WWRecorder.exe` + all runtime files.

### Step 2 — Inno Setup

1. Install [Inno Setup 6](https://jrsoftware.org/isinfo.php)
2. Compile:
   ```powershell
   iscc installer_config.iss
   ```
3. Find the installer at `installer_output\WWRecorder_Setup_1.0.0.exe`

---

## Architecture Deep-Dive

### Frame Pipeline

```
mss.grab(region) → BGRA numpy array
    │  strip alpha (fast slice)
    ▼
BGR24 bytes → FFmpeg stdin pipe
    │
    ▼  [libx264, ultrafast, crf 23, yuv420p]
temp_video.mkv
```

**Pause technique:** when paused, `_frame_worker` re-sends `_last_raw_frame`
at exactly 30 FPS so FFmpeg's clock keeps ticking. This means video length
equals wall-clock time, and the final A/V merge with `-shortest` stays in
sync without any timestamp arithmetic.

### Audio Pipeline

```
soundcard WASAPI loopback ──► float32 chunks ──┐
                                               ├─► AudioMixer thread
soundcard default mic ─────► float32 chunks ──┘      │
                                                      │  mix + clip to [-1,1]
                                                      ▼
                                               int16 PCM → temp_audio.wav
```

On stop:

```
FFmpeg: temp_video.mkv + temp_audio.wav → final Recording_YYYY-MM-DD_HH-MM-SS.mkv
        (-c:v copy · -c:a aac 128k · -shortest)
```

### Pill Invisibility

```python
# After the HWND is valid (~150 ms after show):
ctypes.windll.user32.SetWindowDisplayAffinity(hwnd, 0x00000011)
#                                                    ^^^^^^^^^^
#                                                    WDA_EXCLUDEFROMCAPTURE
```

This is a Windows 10 2004+ API. On older systems the call is silently
ignored (the Pill will appear in recordings, but everything else works).

---

## Configuration

Stored at `%APPDATA%\WWRecorder\config.json`:

```json
{
  "output_folder": "C:\\Users\\You\\Videos\\WWRecorder",
  "hotkey": "<shift>+<backspace>",
  "default_system_audio": true,
  "default_mic": false,
  "start_on_boot": false
}
```

Hotkey syntax follows [pynput key names](https://pynput.readthedocs.io/en/latest/keyboard.html#key-classes).

---

## Known Limitations / TODOs

- `WDA_EXCLUDEFROMCAPTURE` requires Windows 10 version 2004 (build 19041+).
- Audio capture requires `soundcard` 0.4+ and Windows WASAPI. If no
  loopback device is found, recording continues silently (video only).
- The A/V merge step adds ~1–3 s after clicking Stop for long recordings.
- Multi-monitor support: the region picker covers all screens; mss captures
  whichever physical pixels are in the selected rect.

---

## License

MIT — see LICENSE file.
