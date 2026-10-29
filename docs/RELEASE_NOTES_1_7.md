# WWRecorder v1.7.1 — changes since v1.6

This is the cumulative 1.7 family changelog relative to the published v1.6
(1.6.3) release. This release includes the features, interface improvements and fixes below.

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
  keep capture thumbnail, filename, status and useful actions with one small
  dismiss control. Processing explicitly says Compressing video and audio and
  stays responsive while work continues. Saved media is available in Recent Files.
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

- Kept preview speaker mute independent from Export Audio; disabled audio tracks
  no longer open capture devices, and microphone recovery is reported only after
  the device actually starts successfully.
- Made file rename retries asynchronous and single-flight, retained edit state
  across failures, and improved audio/export errors without discarding useful
  diagnostics. Odd-sized source videos export safely with minimal even padding.
- Serialized prepare/stop/mux/discard ownership, preserved recovery media when
  workers cannot stop, and guarded cleanup against later recording sessions.
- Preserved focused-text Escape cancellation in live and screenshot annotation.

## Additional security and compact-layout improvements

- Patched the standalone FFmpeg encoder and Qt's independent playback libraries;
  build gates verify approved native binaries and locked dependencies.
- Keycast retains full typing and adds a warning that input, including passwords
  and typing outside the capture area, may be visible in the recording. Users
  can remember their acknowledgement. Optional IT policy can disable Keycast or
  automatic clipboard copying without changing ordinary users' defaults.
- Added stalled-export supervision, bounded diagnostics, safer uninstall behavior
  and release component inventories/provenance. Original recordings remain safe.
- Saved notifications use one small dismiss action, retain thumbnails/actions and
  identify Recent Files. Processing explicitly mentions video/audio compression.
- Vertical panel headers no longer crowd section labels against the wordmark;
  horizontal panels retain Recent Files/Settings headings. The same compact dock
  now displays WWRec, with discovery and recording blink states distinguished.
- Annotation strips retain responsive controls but cap length and thickness on
  ultrawide displays, including the Close control.

## Testing and distribution

- Expanded behavior-based Qt, state-machine, real FFmpeg export/decoder,
  capture/audio, settings, geometry, icon and packaging regressions.
- Windows one-click test entrypoint runs unattended and generates HTML, JSON,
  Markdown and JUnit reports. No test-time user input is required.
- EXE and MSIX build from one validated sanitized payload. EXE uses the official
  GitHub update channel; MSIX does not query or launch the EXE updater.
- The EXE is a direct Windows installer and remains unsigned. The production-identity
  MSIX is a Store submission package, not a signed sideload installer; Microsoft
  signs Store distribution after submission and certification. Store availability
  must be verified independently. Historical preview MSIX kits are not this release.


## Website and enterprise information

- Published For enterprise guidance with administrator policies for Keycast and
  automatic clipboard, data handling, recovery, deployment and update integrity.
- Privacy policy covers recording visibility, EXE/MSIX storage and network
  behavior, clipboard exposure, diagnostics and website requests.
- A dismissible site notice links to the FFmpeg-patched 1.7.1 release.

## Automated validation

- Windows: 1,152 passed, three desktop-only cases skipped in offscreen CI.
- Portable application suite: 976 passed, 31 Windows-only cases skipped.
- Website: eight navigation/policy tests and eight real desktop/mobile browser
  checks passed, including dismissal, blocked storage, release lookup failure,
  exact installer selection and fingerprint feedback.
- Required compilation, unattended bootstrap/report generation, frozen Qt/startup,
  dependency/native-media integrity and EXE/MSIX packaging gates passed.
- Physical hardware, installed-desktop acceptance and Store certification/delivery
  remain separate from these automated checks.

Final public-export validation: 984 portable tests passed (including eight website navigation/policy tests), 31 Windows-only skips, zero failures/errors. Eight browser interaction checks passed. Core/build source matched the validated installer source; staged privacy and secret scans passed.
