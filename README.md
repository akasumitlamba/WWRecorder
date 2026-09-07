# WWRecorder

WWRecorder is a lightweight, open-source screen recorder and screenshot tool for Windows. Record a selected area, capture system and microphone audio, annotate while you work, and make quick edits without leaving the app.

[Website](https://akasumitlamba.github.io/WWRecorder/) · [Download](https://akasumitlamba.github.io/WWRecorder/download.html) · [Microsoft Store](https://aka.ms/AA1364bx) · [Report an issue](https://github.com/akasumitlamba/WWRecorder/issues)

## Highlights

- Record a selected screen area to H.264 video in a recoverable MKV container.
- Capture system audio, microphone audio, or both, with controls available while recording.
- Pause and resume a recording without creating separate clips.
- Take region screenshots and save them as PNG files.
- Draw live with pencil, highlighter, shapes, text, and a temporary laser pointer.
- Annotate, crop, rotate, and flip screenshots in the built-in image editor.
- Play videos and make quick edits such as trimming, removing sections, muting audio, adding timed text, and saving video frames.
- Find, preview, rename, copy, drag, and delete captures from the Recent Files panel.
- Use the floating edge dock, system tray, configurable global shortcuts, and optional Start with Windows setting.
- Keep captures on your device: media processing is local and no WWRecorder account is required.

## Requirements

- Windows 10 version 2004 or later, or Windows 11
- 64-bit Windows

Windows 10 version 2004 or later is recommended so Windows can exclude WWRecorder's floating controls from supported screen-capture APIs.

## Install

Choose either the [Microsoft Store version](https://aka.ms/AA1364bx) or a standalone installer from [GitHub Releases](https://github.com/akasumitlamba/WWRecorder/releases).

For standalone installers, download only from the official WWRecorder repository and review the release details before running the file.

## Getting started

1. Launch WWRecorder. It stays available from the system tray and floating edge dock.
2. Choose **Record**, then drag to select the area you want to capture.
3. Enable system audio or microphone audio as needed, then start recording.
4. Use the recording controls to pause, resume, annotate, stop and save, or discard.

The default shortcuts are:

| Action | Shortcut |
| --- | --- |
| Start a recording selection | `Shift+Backspace` |
| Take a region screenshot | `Shift+Home` |

You can change both shortcuts in Settings. By default, captures are saved to `%USERPROFILE%\Videos\WWRecorder`.

## Run from source

WWRecorder is built with Python 3.13, PyQt6, and FFmpeg.

```powershell
git clone https://github.com/akasumitlamba/WWRecorder.git
cd WWRecorder

python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
python main.py
```

The application expects `ffmpeg.exe` in the repository root or FFmpeg to be available on `PATH`.

## Tests

```powershell
pytest -q
python -m py_compile main.py recorder.py ui_elements.py dock_widget.py video_editor.py annotation_tool.py updater.py
```

## Build for Windows

Create the application bundle with PyInstaller:

```powershell
pyinstaller --clean wwrecorder.spec
```

The output is written to `dist\WWRecorder`. To create the Windows installer, install [Inno Setup 6](https://jrsoftware.org/isinfo.php) and compile `installer_config.iss`:

```powershell
iscc installer_config.iss
```

Unofficial builds must not be presented as endorsed by or affiliated with WWRecorder.

## Privacy

Recording, screenshot, annotation, and export processing happens on your Windows device. WWRecorder does not require an account and does not include advertising or usage-analytics telemetry. It may connect to GitHub over HTTPS to check for public updates.

See the [WWRecorder Privacy Policy](https://akasumitlamba.github.io/WWRecorder/privacy-policy.html) for details about local files, settings, diagnostics, update checks, and retention.

## Contributing

Bug reports, feature requests, and pull requests are welcome. Please search [existing issues](https://github.com/akasumitlamba/WWRecorder/issues) before opening a new one, and include clear reproduction steps for bugs. Run the tests and compilation check before submitting code changes.

Do not attach private recordings, screenshots, audio, access tokens, or unreviewed diagnostic logs to a public issue.

## License

WWRecorder's original application source code is available under the [MIT License](LICENSE).

The MIT License does not grant rights to the WWRecorder name, logo, or other trademarks. Bundled third-party components remain subject to their own licenses.
