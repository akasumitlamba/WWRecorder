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
