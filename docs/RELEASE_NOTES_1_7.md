# WWRecorder 1.7 preview — changes since stable v1.6

This is the cumulative 1.7 preview changelog relative to the published v1.6
(1.6.3) release. Package revisions are replacements within the same preview;
they do not define the scope of these notes. Include only implemented changes,
reconcile merged contributors' work against source/tests, and update validation
and download details after each build. Do not repeat fixes already listed in
v1.6 unless a further defect was corrected.

## New features

- Choose a real microphone from the recording pill, or use **Same as Windows**.
  Remember the choice, report an unavailable device by name, and keep a named
  microphone selected throughout a take. USB/Bluetooth microphone capture uses
  native device formats and avoids Windows SoundCard's broken mono path.
- **Keycast**, an optional recording control, displays recent keys and shortcuts
  inside the capture and mouse-button/scroll feedback near the pointer. It
  preserves letter case, groups modifier chords, handles Windows/media/function
  keys, and retains precision-touchpad scroll deltas. Feedback fades and adapts
  to narrow areas. Hardware Fn keys without Windows events cannot be observed.
- Position the dock on any screen edge. Top/bottom panels use a horizontal
  gallery and two-column Settings; left/right retain a vertical panel. Expanded
  dock actions remain accessible alongside the panel. Optionally hide the panel
  while dragging files.
- Add multiple independent audio-mute sections in the editor. Yellow timeline
  bands, fields and mute indicators stay synchronized; preview and exported
  audio respect the sections together with trim/delete operations.
- Shared Windows application available as both EXE and full-trust MSIX, with
  equivalent recording, screenshots, annotation, playback and editing features.
  Install/update/startup/storage integrations follow each distribution model.

## Interface and usability

- Refreshed recording pill, microphone split button, menus, settings controls,
  dock, gallery, annotation/player/editor artwork and Windows application icon.
  Settings moves off the pill; Annotate remains alongside Keycast and audio.
- Compact, responsive gallery cards retain thumbnail, name, size and actions.
  Search and Explorer sit beside Settings; internal Gallery navigation remains
  distinct from opening Windows File Explorer. Context action is Open in editor.
- Settings groups Dock & Appearance, Capture & Output, Shortcuts, Audio Defaults
  and Advanced settings meaningfully. Changes apply on Save. Horizontal footer
  puts secondary actions left and Save right. Vertical Advanced can scroll with
  comfortable spacing; vertical branding is compact.
- Cleaner player controls, centered Play/Pause, compact speedometer rate selector,
  stable speaker geometry with three volume arcs, and filename in the native
  title only. Editor uses Trim/Delete/Text/Audio sections and explicit Save/Save
  As/Cancel while retaining the functional multi-lane timeline.
- Modern compact Processing/Saved/feedback notifications replace the cat GIF;
  keep capture thumbnail, filename, status and useful actions with dismiss/hide
  controls. Processing feedback stays responsive while work continues.
- Branded dark Windows installer with corrected checkbox spacing, welcome art,
  app logo and wordmark. Clear annotations uses a readable brush; Delete keeps
  its trash icon. Eraser and arrow tools use a plain crosshair cursor.

## Capture and editing fixes

- Improved text/detail recording quality and preserved native lossless PNG
  screenshots. Avoided redundant capture-frame copies.
- Fixed recording-area movement before Start, click-through interactions,
  inconsistent selection handles and outline visibility; use thin visible red
  indicators without a dark selected-area surround.
- Fixed microphone menu ownership/topmost behavior, explicit-device failures,
  mono/left-channel handling and automatic default-device switching overriding
  the chosen microphone. Bluetooth hands-free quality changes remain controlled
  by Windows and are explained as a hint.
- Fixed dock position drift after stale settings refreshes, interrupted gestures,
  work-area changes and panel transitions. Stop artwork updates during recording.
- Fixed annotation text caret/commit alignment, zoomed eraser hit testing, huge
  highlighter erasing, stale translucent drawing backing and laser rendering.
- Fixed trim summary clicks resetting the range and stale numeric summaries.
  Unified trim/delete/text/mute snapping, duration-preserving region movement,
  zoom-dependent precision and Alt bypass.
- Fixed continuous seekbar preview starvation and retained the final video frame
  at end of playback. Source switches clear old frame state.
- Fixed caption Edit/Delete controls scaling with text, deleted captions leaving
  preview remnants, and paused caption-time changes not updating visibility.
- Fixed lingering button outlines, inconsistent dropdowns, multiple gallery menu
  highlights and screenshot-editor controls wrapping into separate rows.
- Preserved asynchronous recording finalization on pill closure, bounded worker
  shutdown, safe temporary media on failure and export/source protection.
- Repaired incomplete packaged Qt dependencies that caused startup failures;
  validate native Qt files and frozen startup before either installer is built.

## Testing and distribution

- Expanded behavior-based Qt, state-machine, real FFmpeg export/decoder,
  capture/audio, settings, geometry, icon and packaging regressions.
- Windows one-click test entrypoint runs unattended and generates HTML, JSON,
  Markdown and JUnit reports. No test-time user input is required.
- EXE and MSIX build from one validated sanitized payload. EXE uses the official
  GitHub update channel; MSIX does not query or launch the EXE updater.
- This remains a prerelease. Physical microphones, installed Windows DPI,
  multi-monitor gestures and native installer acceptance need Windows testing.
  The downloadable MSIX kit uses a local-test certificate/identity, not a Store
  production package. The direct EXE is unsigned.

## Automated validation for the current preview

- Windows: 1,062 tests passed; three desktop-only cases skipped in offscreen CI.
- Linux portable/public-source suite: 888 passed; 29 Windows-only cases skipped.
- Required compilation, unattended test bootstrap and report generation passed.
- Frozen Qt payload/startup gates and both distribution builds passed.
- Physical hardware and installed-desktop acceptance are separate from these checks.
