# Architecture and behavior contracts

WWRecorder is a Windows PyQt6 application. Shared runtime source is in `app/`; run `python app/main.py`. Both distribution formats use this same source and frozen payload.

## Ownership
- `main.py`: application lifecycle, global shortcuts, capture coordination and completion notifications.
- `recorder.py`, `microphone_capture.py`, `capture_frames.py`: capture workers, native microphone formats, audio mixing and frame handling.
- `dock_widget.py`: dock placement, gallery, settings drafts and panel lifecycle.
- `ui_elements.py`: recording controls, selection overlays and microphone menu.
- `annotation_tool.py`, `tool_cursors.py`: drawing, text editing and visible tool cursors.
- `video_editor.py`: player and reversible media editing/export.
- `keycast.py`: input display, keyboard case and mouse/wheel indicators.
- `icon_theme.py`, `processing_notice.py`: consistent icon surfaces and animated finalization status.
- `distribution.py`, `startup_integration.py`, `updater.py`: centralized distribution-specific OS integration.

## Required contracts
Qt widgets are owned by the GUI thread. Workers report through signals. Long capture, filesystem and FFmpeg work must stay off that thread; shutdown and subprocess waits need bounded error paths.

Treat selection, recording, annotation, export and shutdown as explicit state transitions. Ignore duplicate clicks and late signals. Every recording ends saved, explicitly discarded, or with recoverable temporary media. Never remove the only playable copy after export failure.

Keep logical Qt coordinates separate from native physical pixels and image-local coordinates. Windows monitor origins can be negative. Selected regions remain fixed during ordinary pointer movement. Selection outlines and handles are consistently visible red; no extra dark recording band.

Microphone choices exclude loopbacks. Remember a named device; fall back with an explicit message if absent on the next take. Only Same as Windows follows default-device changes. Capture the device native format and normalize for the existing stereo 48 kHz mix; avoid SoundCard's Windows single-channel recording path. Preserve voice from a single active channel. Failed microphone capture identifies the device while computer audio continues. Device selection does not enable the microphone. Bluetooth quality guidance is a hint. Keep popup windows above recording controls and excluded from capture.

Settings are drafts until Save, including dock position and font size. Dock and Appearance owns placement/font controls; Advanced Settings owns drag-hide. Vertical advanced settings may scroll without a visible scrollbar. Panels anchor expanded dock controls outside the panel, along its edge; close/focus behavior must account for that companion window.

Annotation text preview and committed glyphs share metrics and placement. Tool cursors use contrasting light and dark strokes rather than assuming a desktop color. Keep visible button surfaces and icon padding at all supported sizes. Keycast displays case-sensitive characters, modifiers, mouse buttons and both wheel directions, with bounded lifetime and region-aware layout.

Finalization uses honest indeterminate activity. Hiding its notification does not cancel processing. Playback controls reflow at narrow widths without hiding core transport or file actions.

After behavior changes, update this guide and QA_AUDIT.md. Preserve EXE/MSIX feature parity; see DISTRIBUTION.md.

## Panel and dock motion

The hanging dock owns its home monitor and saved long-axis position. Programmatic panel/hover motion must not change that monitor. Explicit drag/drop can select a monitor and centres the grabber at the nearest edge. Companion controls stay hidden during panel opening/closing, then appear outside its final edge. Detach old transition signals when switching panels; repeated close clicks are ignored and reopening reverses from the current geometry. Restore the hanging dock position exactly after closing.

Horizontal Settings places Quit/Reset/Share left and Save Settings right. Vertical ordering is retained. Horizontal gallery cards use shared construction/reflow metrics of 169x167 Default and 194x189 Large, retaining two-line metadata and the action target. Columns follow viewport capacity. Undo/Redo use a matching padded white/coral pair.
