# Project guide

WWRecorder provides area recording, lossless screenshots, system/microphone audio, drawing/text annotation, Keycast input visualization, a capture gallery and reversible image/video editing.

The dock supports left, right, top and bottom placement. Vertical panels use a list-oriented layout; horizontal panels use a compact thumbnail grid. Settings have Capture and Output, Dock and Appearance, Shortcuts, Audio Defaults and Advanced Settings sections. Save applies draft changes. Gallery's Explorer button opens the capture folder in Windows; Settings' folder button returns to the in-app gallery.

Recording controls keep speaker and microphone toggles separate from the microphone chooser, with Annotate and Keycast available during capture. Modern transparent icons sit on contrasting control surfaces. Annotation cursors use light and dark edges. The finalization card shows animated activity without promising an invented percentage.

## Source map
- `app/`: shared runtime and assets
- `tests/`, `pytest.ini`: regression suite, with app import path configured
- `packaging/`: shared payload, EXE and MSIX definitions
- `scripts/build-distributions.ps1`: Windows packaging entry point
- `docs/AI_CONTEXT.md`: ownership and behavioral contracts
- `docs/QA_AUDIT.md`: verification and remaining manual checks
- `docs/DISTRIBUTION.md`: edition parity and build rules

Install dependencies from requirements.txt and launch `python app/main.py`. Run tests with `python -m pytest`. Windows-specific suites require a Windows host and dependencies; Linux offscreen results are partial verification only.

Current panel refinement: stable dock monitor/location through panel interactions, sequential panel/companion motion, horizontal Settings secondary actions left and Save right, approximately 10% smaller gallery cards, and matching Undo/Redo. Download filenames use normal application names. MSIX keeps its existing local-test identity/signing; naming does not imply Store certification.

## Current capture and editing behavior
Live capture uses ultrafast CRF 20, with final recording compression at CRF 25.
The player offers five playback speeds, frame screenshots and a sectioned editor
for trim, deletion, captions and multiple source-time mute ranges. The existing
timeline retains caption lanes and zoom. Both Windows packages share this code.

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

## Final desktop feedback verification — revision 1.7.0.13

- Linux sanitized source: 871 passed, 29 Windows-only skips, zero failures.
- Windows source: 1045 passed, three offscreen desktop skips, zero failures.
- Fresh-source unattended bootstrap/report check passed.
- Frozen Qt payload/startup validation, EXE and signed local-test MSIX builds passed.
- Real decoded scrub preview and dock stale-config/interrupted-gesture regressions passed.
- Physical microphone and installed DPI/animation acceptance remain separate Windows checks.

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
