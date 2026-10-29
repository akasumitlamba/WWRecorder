# WWRecorder

**Record, capture, annotate, and make quick edits—all on your device.**

WWRecorder is a lightweight desktop screen recorder and screenshot tool for Windows, with archived Linux development. Capture a selected area, include computer sound and microphone audio, draw while you explain, and finish your recording or screenshot in the built-in editors.

[Website](https://akasumitlamba.github.io/WWRecorder/) · [Downloads](https://akasumitlamba.github.io/WWRecorder/download.html) · [GitHub Releases](https://github.com/akasumitlamba/WWRecorder/releases) · [Report an issue](https://github.com/akasumitlamba/WWRecorder/issues)

## Version and download status

**WWRecorder v1.7.1** includes the update for [CVE-2026-8461](https://akasumitlamba.github.io/WWRecorder/release-notes.html#security), covering both recording/export and playback media components. Update older installations before opening untrusted videos.

GitHub currently labels v1.7.1 as a **prerelease** and v1.6 as **Latest**. Use the explicit v1.7.1 download below for this security update.

| Distribution | Download | Status |
| --- | --- | --- |
| Windows EXE 1.7.1 | [Official installer](https://github.com/akasumitlamba/WWRecorder/releases/download/v1.7.1/WWRecorder_Setup_1.7.1.1.exe) | Direct installer; unsigned. Verify the release SHA-256. |
| Microsoft Store | [Production product](https://apps.microsoft.com/detail/9PBS5VDWFXND) | Open the Store listing to check the available version and updates. |

[Release notes and security advisory](https://akasumitlamba.github.io/WWRecorder/release-notes.html) ·
[For enterprise](https://akasumitlamba.github.io/WWRecorder/enterprise.html) ·
[Privacy policy](https://akasumitlamba.github.io/WWRecorder/privacy-policy.html)

Historical releases remain available, but earlier packages do not contain the
current FFmpeg patch. Linux is archived; this release updates Windows only.

## Features

### Screen recording and audio

- Select a rectangular screen area and record H.264 video in an MKV container.
- Capture computer sound, microphone audio, both, or neither, with source controls available during recording.
- Select a microphone or follow the Windows default, and retain the choice for the take.
- Enable **Keycast** to show keys, shortcuts, mouse clicks and scroll feedback inside the recording. Review the privacy warning before displaying sensitive typing.
- Pause and resume within the same recording; stop to save or explicitly discard the session.
- Keep a visible recording state through floating controls and the desktop dock.
- Preserve temporary media when final processing fails, with feedback about the failure.

### Screenshots and annotation

- Capture a selected region as PNG, with optional clipboard copying.
- Draw live with pencil, highlighter, arrows, rectangles, circles, and text; use an eraser and undo/redo.
- Point things out with a temporary laser trail that fades after use.
- Open saved images in the image editor to annotate, crop, rotate, flip, zoom, and save another copy.

### Playback and quick video edits

- Play recordings with seeking, playback speed, volume, fullscreen controls, and still-frame capture.
- Trim the beginning/end, remove sections, add timed text overlays and mute multiple selected audio sections.
- Include or remove sound from an exported video. The **Export Audio** switch controls sound inclusion; it is not an audio-only file exporter.
- Use **Save As** to keep the original, or explicitly save a completed replacement.

### Everyday desktop tools

- A floating edge dock, tray access, and configurable global shortcuts.
- Recent Files with previews, playback/editing, rename, copy, drag, and delete actions.
- Configurable output folder, interface sizing, audio defaults, and startup preferences.
- Local media processing with no WWRecorder account required.

Live desktop annotation and some capture controls differ on Wayland; see the Linux preview notes below.

## Getting started on Windows

Use 64-bit Windows 10 version 2004 or later, or Windows 11.

1. Install a published Windows EXE from [GitHub Releases](https://github.com/akasumitlamba/WWRecorder/releases).
2. Launch WWRecorder. Look for the edge dock and tray icon rather than a conventional main window.
3. Choose **Record**, then drag to select the capture area.
4. Enable computer sound and/or microphone audio if needed, then press **Start**. Both audio sources are off by default.
5. Pause/resume as needed, then **Stop** to save. Allow final processing to finish before opening the result.
6. Open **Recent Files** to play, edit, rename, copy, or manage your captures.

Choose **Screenshot** to capture an image, or open a saved screenshot to annotate it.

| Default shortcut | Action |
| --- | --- |
| `Shift + Backspace` | Start recording selection |
| `Shift + Home` | Take a region screenshot |
| `Escape` | Cancel the current selection or dismiss the current local mode |

Both global shortcuts can be changed in Settings. Captures default to `%USERPROFILE%\Videos\WWRecorder`; choose another folder in Settings.

## Windows EXE and MSIX

EXE and full-trust MSIX provide **the same Windows application**. Capture, audio, annotation, playback, editing, and settings controls are shared. Installation-specific integrations differ:

| Integration | EXE | MSIX |
| --- | --- | --- |
| Updates | Checks the official GitHub stable-release feed and opens the release page | Managed through Microsoft Store |
| Startup | Windows user startup registration | Windows StartupTask |
| Settings | `%APPDATA%\WWRecorder` | Package-private `LocalState\WWRecorder` |
| Initial preferences | Uses existing EXE settings | Can import existing EXE settings once when no packaged configuration exists |

After the initial import, preferences are independent. Saved media remains in the selected output folder.

## Linux Flatpak preview

The Linux preview targets **x86_64 Kubuntu / KDE Plasma** and reuses the recording, audio-processing, image-editing, and video-editing core.

On **Wayland**, the desktop asks permission to share a screen or window. Choose the source, then select an area in the preview or use the whole source. Desktop-approved shortcut bindings take precedence. On **X11**, capture and shortcuts use the corresponding desktop integrations.

Current Wayland preview limitations:

- Live desktop drawing and a global capture border are unavailable.
- Recording controls are not automatically excluded from monitor captures. Move them outside the selected crop or share a target window.
- Saved-image annotation and video text editing remain available.

Linux startup is opt-in. This is a preview, not a claim of full Windows feature parity or an available Flathub release. Installation instructions will accompany a published Linux bundle.

## How it works

```text
Dock / tray / shortcut
        ↓
Selection and recording controls
        ↓
Screen frames + separate computer/microphone audio
        ↓
Temporary media → FFmpeg timing, compression, and mixing
        ↓
Saved recording → Recent Files → playback / editing / export
```

The application uses Python and PyQt6 for the desktop interface, MSS and NumPy for Windows/X11 screen frames, SoundCard/WASAPI for Windows audio, and FFmpeg for media processing. The Wayland preview uses desktop portals, PipeWire, and GStreamer for authorized capture.

Capture and processing run in the background. Recording supports multiple monitors with different display scaling.

See the [engineering overview](https://akasumitlamba.github.io/WWRecorder/specs.html) for more background.

## Source and development

This repository contains the current Windows application source, tests, dependency
locks, build definitions and website. Shared runtime source is in `app/`;
packaging is in `packaging/` and `scripts/`. Historical Linux work is archived
separately and is not updated by this Windows release.

## Privacy and file safety

Recording, screenshots, annotation, and editing are processed locally. WWRecorder does not require an account and does not include advertising or usage-analytics telemetry. EXE update checks contact GitHub over HTTPS; Store delivery and opened external links use their respective services.

Recovery files are kept in `.wwr_temp` under the selected output folder. If saving fails, preserve the reported recovery files and recover useful media promptly; temporary-file cleanup is not permanent archival storage.

See the [Privacy Policy](https://akasumitlamba.github.io/WWRecorder/privacy-policy.html) for local storage, settings, diagnostics, update checks, and retention details.

## Feedback and contributions

[Bug reports and feature requests](https://github.com/akasumitlamba/WWRecorder/issues) are welcome. Include:

- App version and installation type: EXE, MSIX, or Linux preview.
- Windows version or Linux desktop/session type, especially X11 versus Wayland.
- Steps to reproduce, expected behavior, and what actually happened.
- Relevant display scaling and audio-device details for capture issues.

Do not attach private recordings, screenshots, audio, access tokens, or unreviewed diagnostic logs to a public issue. For source contributions, describe the target version and required files so changes can be checked against the appropriate development snapshot.

## License

See [LICENSE](LICENSE) and the [legal notices](https://akasumitlamba.github.io/WWRecorder/legal.html) for application-source, website, and third-party terms. The WWRecorder name, logo, and other marks do not grant permission to imply endorsement or affiliation. Bundled third-party components retain their own licenses.


## Run from source on Windows

Use Windows CPython 3.13 x64:

```powershell
git clone https://github.com/akasumitlamba/WWRecorder.git
cd WWRecorder
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --require-hashes -r requirements-windows.lock
python scripts/prepare_media_runtime.py
python app/main.py
```

The media preparation command downloads and verifies the approved FFmpeg encoder. `Run-WWRecorder.cmd` also prepares it before startup. Windows does not use an arbitrary FFmpeg from PATH.

Contributors can run `python -m pytest`; the lock file includes test dependencies. See the [architecture](docs/AI_CONTEXT.md) and [build guide](docs/DISTRIBUTION.md) for implementation and packaging details.

## Administrator controls

Version 1.7.1 adds machine policies to disable Keycast or automatic clipboard copying. See [administrator instructions](https://akasumitlamba.github.io/WWRecorder/enterprise.html#managed-controls) for `DisableKeycast` and `DisableAutomaticClipboard`.
