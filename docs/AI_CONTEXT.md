# WWRecorder architecture

Windows desktop screen recorder using shared PyQt6 source in app/. Capture,
audio and encoding workers signal the GUI thread. Recording ends saved,
explicitly discarded, or recoverable; never remove the only playable media copy.
Qt logical coordinates and physical capture pixels are distinct on mixed-DPI
and negative-origin desktops.

EXE and full-trust MSIX share one validated frozen payload. Only distribution,
startup and update delivery differ. Build both using scripts/build-distributions.ps1.
Native Qt components and a bounded frozen launch probe are required before packaging.

Player supports speed selection, screenshots and sectioned editing. Trim,
delete and captions retain the established timeline. Audio supports multiple
source-time mute ranges; silence is applied before retained-span audio concat
so trim/delete retiming remains aligned. Mute-only edits are unsaved changes.

Tests: double-click RUN_TESTS.cmd on Windows with Python 3.13 installed. It sets
up dependencies and runs root/E2E tests without input. Unexpected dialogs fail;
module isolation prevents Qt caches/hooks leaking across unrelated tests. HTML,
JSON, Markdown and JUnit reports go to artifacts/windows_e2e/. Windows-only
coverage is explicitly skipped on other hosts. Real audio-device listening,
installed-package and native DPI/visual acceptance are separate checks.

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
