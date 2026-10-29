# Verification status

## Desktop feedback preview 1.7.0.13

- Sanitized public source: 871 passed, 29 Windows-only skips, no failures.
- Windows CI: 1045 passed, three desktop-only skips, no failures.
- Fresh-source one-click dependency/bootstrap and reporting check passed.
- Real decoded preview frame verified before seekbar release.
- Native Qt validation, frozen startup, EXE compilation and signed local-test MSIX packaging passed.


## Preview package 1.7.0.12
- Automated Linux source run: 821 passed, 29 Windows-only skips, zero failures.
- Generated audio exports decoded to verify mute sections with trim and cuts.
- UI tests exercise actual widgets, section selection, dirty state and layout.
- Runner regression checks verify pass/failure/crashed-child reports and no input.
- Native Qt dependency checks and frozen startup probe gate both package formats.
- Windows CI: 995 passed, 3 desktop-only skipped; no failures. Both installer builds and frozen startup probe passed.
- Packaged runtime, hashes, assets and MSIX identity/signature containers verified.
- Release privacy scan: 1212 items, zero findings.
- Real USB/Bluetooth microphone fidelity, Windows DPI/animation acceptance and
  installed EXE/MSIX interactive acceptance still require Windows verification.

Resolved defects include missing frozen Qt detection, media-safe live recording
close, eraser zoom hit-testing, updater origin validation, popup/worker lifecycle,
selective-audio retiming, control alignment, and shell icon corner transparency.
No automated source suite alone certifies physical device or installed-package behavior.

The Windows one-click bootstrap was executed successfully: fresh virtual
environment, noninteractive dependency setup and HTML/JSON/JUnit output. Full
Windows source tests remain 992 passed / 3 headless desktop skips.

Fresh-source Windows bootstrap also verified automatic missing-FFmpeg setup.
Application packages are the same validated 1.7.0.12 payload; final changes only
extend test setup. No manual input is required during the tests.

## Desktop feedback corrections — 2026-10-28


- Player/editor filename and edit state appear only in the native window title.
- Trim summary is read-only. Timeline handles and numeric fields own the range;
  repeated enabling preserves it. Reset restores the source range.
- Shared timeline snapping selects the nearest edge within eight logical pixels,
  including trim, delete, text and mute boundaries, playhead and source ends.
  Dragged regions exclude their own edges; body moves preserve duration. Zoom
  shrinks the temporal tolerance. Alt temporarily bypasses snapping.
- Mute bands support endpoint and body dragging with synchronized numeric rows.
- Scrubbing coalesces latest positions at 33ms and waits for frame delivery
  (200ms fallback) rather than flooding the decoder; final release seeks exactly
  and resumes playback only if it was playing before the drag.
- Player focus does not retain an outline. Speaker geometry remains fixed with
  one/two/three arcs; mute uses the same speaker body.
- Screenshot editor groups stay on one row. Narrow windows can scroll the row
  horizontally instead of wrapping controls. Clear uses a separate brush icon;
  deletion retains its trash icon. Laser has a centered, tight layered glow.
- Dock recording icon updates its normal/hover caches together, preventing a
  hover from reverting Stop to Camera. Gallery action reads Open in editor.
- Settings title matches the wordmark height, font selector and dock selector
  share a 144x32 footprint with six-pixel corners, Quit power artwork is red,
  and horizontal footer credit/rating sits immediately before Save.
- Keycast chords render a shared tile with modifier glyphs, preserving Unicode
  letter case. Windows, media and F1–F24 keys have raw-VK handling without OS
  suppression. A hardware Fn key that emits no Windows event is not observable.
- Capture notifications retain thumbnails/actions/status and hide/minimize/close
  controls while dropping repeated explanatory rows. Dismissal never cancels
  recording finalization. Installer branding uses native icon/text controls,
  with the R in WWRecorder red; welcome copy no longer repeats Next.

## Dock home ownership correction — 2026-10-28


Reproduced unexpected center-to-bottom movement through two independent routes:
a same-edge config refresh applied cached coordinates, and interrupted mouse
press/drag state survived hiding, panel attachment or a missing release. Runtime
home now changes only through completed user drags or an explicit edge setting.
Config refreshes preserve home and update the replacement mapping. Hide, loss of
mouse grab, deactivation, unpressed motion and panel attachment cancel gestures;
an interrupted active drag restores its original anchor. Temporary screen work
area clamps affect presentation only, preserving the home for later restoration.
Regression coverage includes both pending and active gestures, each interruption,
stale config refreshes, transient work areas, all edges and existing monitor tests.

## Preview consistency and asset ownership — 2026-10-28

Live Laser uses approved modern artwork without color changes replacing it.
Removed 59 superseded root PNGs; shared aliases resolve all those action names
to modern runtime images. Original Camera/wordmark and SVG-to-PNG geometric
source pairs are intentional. Vertical brand/title are 18px; horizontal remains
24px. Caption Edit/Delete controls keep a fixed screen footprint independent
of font size and video fit. Removal disconnects callbacks, immediately hides
and destroys scene items, removes the row and timeline/model entry; timing
changes refresh visibility while paused. No geometry mutation occurs in paint.
Scrubbing uses one asynchronous FFmpeg preview process at a time (latest queued
position, 3s deadline, bounded cancellation), avoiding repeated Qt seek decoder
interruption. Release seeks the actual player exactly and restores prior play
state. A cached decoded frame remains visible when Qt clears its EOF surface;
source changes clear it. Portable functional regressions cover these paths.
Package revision 1.7.0.14 passed Windows validation and the shared EXE/MSIX build. Public asset verification is recorded separately.
Release notes must be cumulative against stable v1.6, reconciled with shipped
source and merged changes, rather than a list of latest package increments.

Portable release-gate result: 886 passed, 29 Windows-only skipped, zero failures.
Required seven-module compilation and diff whitespace check passed. Windows
CI, frozen validation and both installer builds remain pending.

## Final preview consistency verification — revision 1.7.0.14

Windows: 1062 passed, zero failures, three desktop-only skips. Sanitized public
source on Linux: 888 passed, zero failures, 29 Windows-only skips. Required
compilation, unattended bootstrap/report generation, frozen Qt payload/startup
validation and shared EXE/MSIX packaging passed. Physical/installed acceptance
remains separate.

The Windows gate caught both a partial-initialization cleanup assumption and a
hardware video-surface lifetime crash in repeated EOF/seek/close cases. Cleanup
now tolerates missing preview state; EOF retains an owned QImage pixel copy,
never a decoder-owned hardware QVideoFrame. The frame callback is disconnected
and pixels cleared before video-output teardown. Native decoder cases passed
after the repair. Scrub time labels follow the pointer while decoding.

Scrub state: press pauses and records prior playing state; one asynchronous
FFmpeg process finishes a preview while movement replaces the pending target.
Release cancels/reaps with a 100ms bound, performs the exact native seek and
resumes only if previously playing. Each extraction has a three-second deadline.
Source changes cancel requests and clear old image/position state.

Caption removal blocks row signals, removes the model before focus callbacks,
hides/disconnects/destroys the graphics item and removes row/timeline state in
one GUI operation. Paused timing edits update visibility immediately. Action
chrome has fixed screen dimensions; geometry never changes inside paint.
Cumulative release notes are maintained in RELEASE_NOTES_1_7.md against the
published v1.6 baseline, including merged feature and reliability work.

## Version 1.7.1 security and compact UI

The encoder is FFmpeg 9.0.2. Qt/PyQt 6.12.0 playback independently uses patched
FFmpeg 9.0.1 DLLs. scripts/prepare_media_runtime.py fetches the pinned encoder;
app/ffmpeg.exe is generated, not tracked. Use requirements-windows.lock for
Windows CPython 3.13 x64. Build checks generate dependency/native/payload
inventories and verify exact media hashes and frozen startup.

Keycast retains typing and warns that passwords/private input, including outside
the recording area, may be visible in the video. Remembered acknowledgement is
optional. HKLM policies can block Keycast or automatic clipboard (manual Copy is
separate). See ENTERPRISE_DEPLOYMENT.md for documented limits and operations.
Exports have bounded supervision/error tails, preserve original media and use
FFmpeg 9 fps_mode cfr. Lifecycle ownership is serialized across preparation,
stop/mux/discard with session generation guards. Disabled audio tracks do not
open devices. Export Audio is independent of preview speaker mute.

Saved notifications have one small close, thumbnail/actions and Recent Files hint;
processing says Compressing video and audio. Vertical headers omit section labels,
horizontal headers retain Recent Files/Settings. WWRec replaces the collapsed
dock dots/lines within the same footprint. Discovery blinks whole text; recording
blinks Rec only. Annotation strip caps are 720px horizontal / 840px vertical with
20–36px controls and screen-fit reduction, including Close.

Windows automated suite: 1152 passed, three desktop-only skips. Portable suite:
976 passed, 31 Windows-only skips. Website has eight static and eight browser
checks. EXE/MSIX, bootstrap/report, frozen startup and security gates passed.
Store certification and installed hardware acceptance remain separate.

Final public-export validation: 984 portable tests passed (including eight website navigation/policy tests), 31 Windows-only skips, zero failures/errors. Eight browser interaction checks passed. Core/build source matched the validated installer source; staged privacy and secret scans passed.

## Recording synchronization and interface repairs

Capture fills missed active-clock frame slots with the previous screen, preserving
individual event timing instead of uniformly stretching surviving frames. Decoded
FFmpeg regressions compare microphone/system tones with visible events after
uneven capture stalls and pause/preparation accounting (less than 50ms skew).
Native hardware acceptance remains a separate check.

The original compact dock handle is retained. Thumbnail play symbols are blue;
headers render crisp high-DPI artwork. Discard is centered/modal, and floating
controls yield to modal dialogs. Keycast warns that private typing may appear in
the recording, with explicit cancellation and administrator policy coverage.
Installer branding is composed once for Welcome/Finish. Windows PE icon extraction
is validated, and a hidden native bridge requests normal media-safe Quit without
force-killing recordings. Older installed builds can need one manual quit.
Website screenshots retain the existing dark walkthrough content and show current
controls. Keycast has a dedicated feature section with synthetic sample input.

### Precision-touchpad Keycast feedback

Keycast supplements low-level mouse wheel events with a passive touchpad-only
Raw Input listener. The owned Windows message thread reads per-device HID
capabilities and complete contact frames; two-finger common motion produces
up/down/left/right feedback. Single-finger motion, pinches, palms and button
drags do not produce scroll feedback. Windows scrolling direction is respected.
Registration is serialized across stop/restart; input is never suppressed or
injected. No contacts or typing are written to a log. Native registration and
shutdown are tested independently of physical gesture acceptance.

## Remaining physical Windows acceptance

- In a browser and File Explorer, verify two-finger up/down/left/right scrolling
  displays the matching Keycast direction; ordinary mouse wheels still work.
  Confirm one-finger pointing, pinch zoom and button dragging do not display scroll.
- Disable/re-enable Keycast and stop/discard capture: no lingering contact feedback
  or interruption to other applications' gestures. Test administrator restrictions.
- Compare visible events with microphone/system sound in a saved recording using
  another player, including pause/resume and sustained capture load. Repeat with
  built-in, USB and Bluetooth microphones in both distribution formats.
- Install/update on a desktop, inspect Explorer/taskbar icons and Welcome/Finish
  branding, and verify safe shutdown does not destroy active capture/edit work.

Automated release checks: 1,177 Windows passed (three headless desktop skips),
999 portable passed (33 Windows-only skips), nine desktop/mobile browser checks.
These counts do not stand in for physical device or installed Store acceptance.
