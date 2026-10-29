# WWRecorder adversarial UI / lifecycle audit

**Date:** 2026-10-27
**Harness:** `tests/windows_e2e/` (`adversarial`, `area_*` markers)
**Linux verification:** 344 collected → **331 passed, 13 skipped, 0 failed**

This audit drives real dock / selection / pill / annotation / editor paths with
hostile input (spam, illegal transitions, QPointF/QRect coercion, popup focus
loss, teardown). External OS/FFmpeg/network seams stay thin; behavior under test
is not faked away.

---

## Severity-ordered findings

### ADV-001 — CRITICAL (fixed) — Eraser `QRect.contains(QPointF)` TypeError

- **Surface:** Live `AnnotationCanvas` + photo `_DrawingArea` `_hit_test` / `_erase_at`
- **Repro:** Continuous eraser sweep (`QPointF`) over `rect` or `text` items
- **Symptom:** Unhandled `TypeError` mid-gesture; stroke may partially erase then crash the erase path
- **Root cause:** PyQt6 `QRect.contains` rejects `QPointF`; eraser always passes `QPointF`
- **Fix:** Use `QRectF` + `QPointF` for contains; accept both point types
- **Tests:** `test_53_adversarial_annotator.py::test_eraser_pointf_sweep_hits_all_object_types[*]`

### ADV-002 — HIGH (fixed) — Huge highlighter ink outside 12px radius missed

- **Surface:** Eraser hit radius vs `THICKNESS_LEVELS['highlighter']['huge']=44`
- **Symptom:** Visible highlighter ink not erasable when cursor is off the centerline by >12px
- **Fix:** Threshold = `max(12, stroke/2 + 2)` (scaled for photo editor)
- **Tests:** `test_huge_highlighter_radius_is_erasable_off_centerline`

### ADV-003 — HIGH (fixed) — Sidebar focus-loss dismisses on QComboBox/QMenu popups

- **Surface:** `SidebarPanel._check_should_close` with `close_on_focus_loss=True`
- **Symptom:** Opening dock-edge combo / context menus can dismiss the panel (popup is not a descendant window)
- **Fix:** Bail out when `QApplication.activePopupWidget()` or `activeModalWidget()` is set
- **Tests:** `test_focus_loss_ignored_while_active_popup`

### ADV-004 — HIGH (fixed) — Pill `closeEvent` nested `QMessageBox.exec()` deadlock risk

- **Surface:** `PillWidget.closeEvent` → `_initiate_discard` → modal confirm
- **Symptom:** Closing the pill while a recording exists could nest a modal loop on the GUI thread during teardown
- **Fix:** `_initiate_discard(confirm=...)`; `closeEvent` uses `confirm=False`
- **Tests:** `test_close_event_never_calls_modal_exec`

### ADV-005 — MEDIUM (documented) — Discovery strobe is process-session only

- **Surface:** `DockWidget._is_first_launch` always `True` on construct; not persisted in config
- **Contract (AI_CONTEXT):** Blink until first hover/action, then steady **for that process session**
- **Audit ask:** Must not repeat forever after settings reload / simulated restarts
- **Result:** Same-instance settings/edge reload correctly keeps strobe off (tested). **Cold process restart re-enables blink by design.** Persisting discovery across cold starts would need a config flag — open product decision if desired.
- **Tests:** `test_discovery_strobe_stops_after_acknowledge_survives_settings_reload`

### ADV-006 — MEDIUM (gap) — Mixed-DPI multi-monitor physical paint bleed

- Offscreen DPI scale paint does not crash (tested). Pixel-perfect border clipping under real 1.0/1.25/1.5/2.0 mixed monitors still needs Windows desktop capture review.
- **Marker:** `windows_gui` / HW gap

### ADV-007 — MEDIUM (gap) — Global hotkeys while modal / tray spam

- Not constructible without Windows shell + pynput desktop session.
- **Marker:** `windows_native` / HW gap

### ADV-008 — LOW (covered by source contract) — Export close async

- `VideoPlayerWindow.closeEvent` already uses `_begin_async_close` and avoids `QThread.wait` / `player.stop()` in the close path (asserted).

### ADV-009 — LOW (covered) — Selection handle matrix / tiny reject / Escape

- All 8 handles engaged; inverted drag normalizes; `<32` rejected; Escape emits `{}`.

---

## Product fixes included in this PR

| ID | Module | Change |
| --- | --- | --- |
| ADV-001/002 | `app/annotation_tool.py` | `_hit_test` QPointF-safe + stroke-aware radius (live + photo) |
| ADV-003 | `app/dock_widget.py` | Popup/modal guard in `_check_should_close` |
| ADV-004 | `app/ui_elements.py` | Non-modal teardown discard from `closeEvent` |

---

## Suite map

| Area | Module | Marker |
| --- | --- | --- |
| 1 Dock/sidebars | `test_50_adversarial_dock_sidebars.py` | `area_dock` |
| 2 Selection | `test_51_adversarial_selection_overlay.py` | `area_selection` |
| 3 Transport pill | `test_52_adversarial_transport_pill.py` | `area_transport` |
| 4 Annotator | `test_53_adversarial_annotator.py` | `area_annotator` |
| 5 Video editor | `test_54_adversarial_video_editor.py` | `area_editor` |

Helpers: `helpers/adversarial.py`. Selective run:

```powershell
.\tests\windows_e2e\run_all.ps1 -Markers "adversarial"
```

---

## HW-only gaps remaining

1. Mixed-DPI multi-monitor visual clipping / DWM popup activation on real desktop
2. Tray menu spam + quit-during-capture Save/Cancel MainWindow dialog
3. Global hotkey while settings/annotate modal open
4. Live gdigrab + WASAPI endpoint hotplug during pill state matrix
5. Fullscreen chrome idle-hide timing under real compositor
6. FFmpeg export cancel under load (worker race) on Windows

These are marked in `ACTION_INVENTORY.md` / `COVERAGE_MAP.md` — not silent greens.
