# WWRecorder 1.7.1

Changes since v1.6 (installer 1.6.3), including Windows installer revision 1.7.1.4.

**Prerelease downloads:** [EXE installer](https://github.com/akasumitlamba/WWRecorder/releases/download/v1.7.1/WWRecorder_Setup_1.7.1.4.exe) · [MSIX package](https://github.com/akasumitlamba/WWRecorder/releases/download/v1.7.1/WWRecorder_1.7.1.4_x64.msix) · [MSIX install kit](https://github.com/akasumitlamba/WWRecorder/releases/download/v1.7.1/WWRecorder_MSIX_Install_Kit_1.7.1.4.zip).

## Security update — update older installations

This release addresses **CVE-2026-8461** in FFmpeg's MagicYUV decoder. A specially crafted video can crash an application or, in some circumstances, run malicious code when decoded by vulnerable libraries. Both recording/export (FFmpeg 9.0.2) and playback (FFmpeg 9.0.1 through Qt 6.12.0) components are updated.

Versions before 1.7.1 do not include this security update. Install the EXE attached to this release before opening untrusted videos. Store users should check Microsoft Store for updates and review their installed version.

References: [FFmpeg security advisories](https://ffmpeg.org/security.html), [Ubuntu CVE notice](https://ubuntu.com/security/CVE-2026-8461).

## New features

- Choose a microphone or follow the Windows default; keep that choice throughout a take.
- Show keys, shortcuts, mouse clicks and scroll feedback with optional Keycast. Its activation warning explains that passwords and typing outside the recording area may be visible. Keycast does not mask passwords.
- Administrators can disable Keycast or automatic clipboard copying using `DisableKeycast` and `DisableAutomaticClipboard`, introduced in 1.7.1. [Policy instructions](https://akasumitlamba.github.io/WWRecorder/enterprise.html#managed-controls).
- Place the dock on any screen edge.
- Mute multiple sections of a video alongside trimming, cuts and timed captions.
- Windows EXE and Microsoft Store editions provide the same recording and editing features.

## Interface improvements

- Refreshed recording, playback, editing and annotation controls.
- Compact Recent Files cards, clearer file actions and reorganized Settings.
- Smaller processing and saved notifications with thumbnails and useful actions.
- Clearer Keycast privacy warning with a compact warning illustration.
- Annotation controls fit more screen sizes.
- Updated Windows installer artwork and icons.

## Fixes

- Fixed a stale microphone list when wireless devices connect. The list now refreshes while open, and a missing device name no longer hides other inputs.

- Remember a connected microphone; after it disconnects, keep the current take on that input and use Windows default for the next take. The microphone list refreshes automatically while open, including during recording.

- Fixed confirmations, dropdowns and tooltips appearing behind floating controls, including Delete File and Discard Recording.

- Fixed audio/video timing during uneven capture load by holding the previous screen image during missed frame slots.
- Fixed microphone selection changing unexpectedly, unavailable-device feedback and some USB/Bluetooth recording failures.
- Fixed recording-area movement, selection outlines and click-through controls.
- Fixed dock position changes after settings refreshes or interrupted drags.
- Fixed annotation text placement, erasing when zoomed, lingering drawings and laser rendering.
- Fixed trim summaries and movement of trim, cut, caption and mute sections.
- Fixed slow timeline previews and missing final playback frames.
- Fixed deleted captions remaining visible and paused caption edits not updating.
- Fixed failed saves losing recovery files and overlapping actions affecting another recording.
- Fixed startup failures on some Windows installations.
- Fixed rename failures losing edits, and exports failing on odd-sized videos.
- Fixed installer shutdown handling. Quit older running versions manually once before updating if prompted.

## Installation

Download `WWRecorder_Setup_1.7.1.4.exe` and compare its SHA-256 with the attached checksum. The standalone EXE is unsigned.

For MSIX sideloading, download and extract the install kit, then run `Install-Test.cmd`. It verifies the package signature and asks permission to trust the included public certificate. This preview uses the separate **WWRecorder (MSIX Test)** identity and is not a certified Microsoft Store package. No private signing key is included. Use the EXE for the normal standalone installation.

Microsoft Store installs update through the Store; the standalone EXE updates from GitHub. This release is currently labeled prerelease on GitHub. Store users can check the [Store listing](https://apps.microsoft.com/detail/9PBS5VDWFXND) for their available version.

SHA-256:

- EXE: `d0c7cf976cd9656c60b9e938e9abc11f72990afd610495b28f845643bea3fdf0`
- MSIX: `ac38b7ed8054c8593e9f9fb318f7dc8c1f60ed40ead64bc82ef35644cc4be000`
- MSIX install kit: `29b6037de10af6b2c151f7496170f0e0067cebf1ca0037a56ba93ce2b6702152`

[Source matching this installer](https://github.com/akasumitlamba/WWRecorder/tree/dd0848b201e1a899cbfeb1f388ef75b6d899c8f3). The release tag identifies the original release source; this installer revision uses the linked source.
