# WWRecorder 1.6.3

WWRecorder 1.6.3 is a reliability and usability update focused on accurate multi-monitor capture, safer file handling, clearer feedback, and a more predictable editor.

## Bug fixes

- Fixed recordings and screenshots being shifted or blurred on monitors with different Windows scaling, including screens positioned to the left or above the primary display.
- Fixed pause handling so a paused section is removed exactly once and audio stays aligned with video.
- Added a visible warning when an active microphone or system-audio device disconnects during recording.
- Improved FFmpeg startup detection so recording does not appear ready when the recorder has already failed to start.
- Prevented extra-large Windows accessibility cursors from being clipped and ensured temporary Windows cursor resources are always released.
- Fixed Clear All undo/redo so drawings return in their original layer order.
- Kept the annotation thickness menu fully inside the current screen.
- Made image Save and Save As atomic, protecting the original image if a write fails and avoiding duplicate same-path saves.
- Prevented the dock from jumping when screen resolution, monitor, or taskbar geometry changes during an animation.
- Fixed Reset to Defaults so it also restores the default text size.
- Fixed failed file deletion being silent and protected unsaved captions and cuts when a rename fails or succeeds.
- Disabled the video timeline when damaged media cannot be decoded.
- Prevented the Windows auto-hide taskbar from covering fullscreen playback controls.
- Merged touching and overlapping cut ranges before export to prevent tiny stutters or audio drift.
- Matched exported caption size and bold/italic styling more closely to the editor preview on HD, 1440p, and 4K videos.
- Ensured caption temporary files are removed after successful, failed, or cancelled exports.
- Kept video-editor shutdown bounded when an export or media worker cannot stop normally.
- Prevented multiple copies of WWRecorder from running at the same time without requiring administrator permission.
- Cleared stuck shortcut modifier keys after returning from a Windows security or UAC screen.
- Moved Processing and Saved notifications to the monitor where the capture was made.
- Separated update-server failures from the genuine “latest version” result.
- Blocked unknown scripts and executables from being launched through Recent Files or save notifications.
- Replaced common technical error codes with clearer, actionable messages and improved Tab-key navigation.
- Fixed the dock Record button intermittently doing nothing while a sidebar was open.
- Fixed startup on other PCs by removing an incompatible ICU DLL that had leaked into the previous package from the build environment.

## Enhancements

- Photos now use one clear action set: Open & Edit, Copy, Rename, and Delete.
- Videos now provide Play, Edit, Copy, Rename, and Delete as separate actions.
- Recent Files generates the first 15 previews immediately, then loads more as they approach the visible scroll area using a limited background pool.
- Developer-mode information and its button now wrap correctly inside the Settings sidebar.
- Recent Files tips now describe the real photo, video, search, and preview-loading behavior.
- Mixed-DPI capture uses a per-monitor pixel map instead of assuming the entire desktop has one scale.

## Verification

- 139 automated regression tests passed before packaging.
- Multi-monitor logic was tested with synthetic 100%, 125%, and 150% scaling, negative monitor coordinates, and cross-monitor pixel composition.
- All application modules compiled successfully and the frozen application completed a startup smoke test.

## Installation note

This installer is an in-place update for earlier WWRecorder 1.6 versions and keeps the existing application identity and settings.

## Installer verification

- File: `WWRecorder_Setup_1.6.3.exe`
- Size: 73,866,869 bytes (70.44 MiB)
- SHA-256: `283ECCC39D17B35D9300FD441605D6C3F5413CE313D026E3AA4BFC87AE7B0FCC`
- Authenticode: Unsigned. Windows may show a SmartScreen warning until a trusted code-signing certificate is added.
