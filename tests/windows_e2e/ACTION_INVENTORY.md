# Windows E2E — interactive action inventory

Living checklist of meaningful controls/actions discovered from `app/` source.
Status: **covered** (matrix/asserted), **partial** (smoke/source only), **gap**
(needs Windows hardware / installed package / Store).

Markers: `brute_force`, `settings_matrix`, `parallel_actions`, plus feature tags.
Catalogues live in `helpers/action_matrix.py`.

| Area | Action ID | Surface | Save/persist? | Exit paths | Parallel/busy | Status | Suite |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Dock | `dock.screenshot` | DockWidget `_btn_screenshot` | n/a | — | spam + recording chrome | covered | `test_31`,`test_34` |
| Dock | `dock.record` | `_btn_record` | n/a | recording chrome toggle | spam | covered | `test_31` |
| Dock | `dock.annotate` | `_btn_annotate` | session | icon sync | — | covered | `test_31` |
| Dock | `dock.files` | `_btn_files` | n/a | — | during recording chrome | covered | `test_31`,`test_34` |
| Dock | `dock.settings` | `_btn_settings` | draft→Save | — | during recording chrome | covered | `test_31`,`test_34` |
| Settings | `settings.clipboard` | `_chk_clip` | Save | Escape/close/Reset | dirty enable Save | covered | `test_30` |
| Settings | `settings.sys_audio` | `_chk_sys` | Save | Escape/close/Reset | dirty | covered | `test_30` |
| Settings | `settings.mic` | `_chk_mic` | Save | Escape/close/Reset | dirty | covered | `test_30` |
| Settings | `settings.autoclose` | `_chk_autoclose` | Save | Escape/close/Reset | dirty | covered | `test_30` |
| Settings | `settings.hide_drag` | `_chk_hide_drag` | Save | Escape/close/Reset | dirty | covered | `test_30` |
| Settings | `settings.boot` | `_chk_boot` | Save | Escape/close/Reset | StartupTask/Run | covered | `test_30` |
| Settings | `settings.dev_mode` | `_chk_developer_mode` | Save | Escape/close | reveals GitHub button | covered | `test_30`,`test_40` |
| Settings | `settings.dock_edge` | `_cmb_dock_position` | Save | Escape/close | draft until Save | covered | `test_30` |
| Settings | `settings.font_size` | `_seg_font` | Save | close w/o save | rebuilds UI | partial | — |
| Settings | `settings.hotkey_rec` | `_edt_hotkey` | Save | Esc cancel listen | conflict validation | covered | `test_33`,`test_40` |
| Settings | `settings.hotkey_ss` | `_edt_screenshot` | Save | Esc cancel listen | conflict validation | covered | `test_40` |
| Settings | `settings.save` | `_btn_save` | emits settings_saved | n/a | disabled when clean; spam | covered | `test_30` |
| Settings | `settings.reset` | `_btn_reset` → `_reset` | draft only until Save | Escape discards | marks dirty | covered | `test_30` |
| Settings | `settings.quit` | `_btn_quit` | n/a | quit emit | spam | covered | `test_30` |
| Settings | `settings.update` | `_btn_check_update` | n/a | fail/progress | spam; edition CTA | covered | `test_39` |
| Pill | `pill.start` | `_btn_start` | starts prepare | — | preparing disables | covered | `test_32`,`test_34` |
| Pill | `pill.pause` | `_btn_pause` | n/a | — | spam pause/resume | covered | `test_32`,`test_34` |
| Pill | `pill.stop` | `_btn_stop` | mux | — | preparing/stopping guards | covered | `test_32`,`test_34` |
| Pill | `pill.discard` | `_btn_discard` | temp only on discard | confirm if recording | idempotent while stopping | covered | `test_32` |
| Pill | `pill.sys_audio` | `_btn_sys` | runtime | — | on/off/on; disabled preparing | covered | `test_32` |
| Pill | `pill.mic` | `_btn_mic` | runtime | mic menu | on/off/on | covered | `test_32` |
| Pill | `pill.keycast` | `_btn_keycast` | per-take | stop clears | on/off/on | covered | `test_32` |
| Pill | `pill.annotate` | `_btn_annotate` | session | — | syncs | covered | `test_32` |
| Overlay | `selection.escape` | SelectionOverlay | no file | Escape | — | partial | `test_33` source |
| Overlay | `selection.tiny` | region plan | rejected | — | — | covered | `test_35` |
| Overlay | `selection.negative` | region plan | allowed | — | — | covered | `test_35` |
| Annotate | `ann.tools.*` | photo toolbar | history | — | tool spam | covered | `test_36` |
| Annotate | `ann.undo_redo_clear` | history | — | — | empty stack safe | covered | `test_36` |
| Annotate | `ann.escape_priority` | keys | cancel edit first | Escape | second Escape | partial | `test_33`,`test_36` |
| Editor | `ve.fullscreen` | F11/Escape | chrome hide | Escape exits FS | — | partial | `test_37` source |
| Editor | `ve.delete_merge` | regions | Save As non-destruct | — | overlapping merges | covered | `test_37` |
| Editor | `ve.export_busy` | export | one worker | close confirm | duplicate export | partial | `test_37` source |
| Gallery | `gallery.open/edit/play` | row menu | n/a | — | — | partial | `test_38` |
| Gallery | `gallery.rename` | `_FileRow` | filesystem | Escape cancel | — | covered | `test_38` |
| Gallery | `gallery.delete/copy` | row menu | filesystem | cancel | locked file | partial | `test_38` source |
| Tray | `tray.*` | system tray | n/a | quit | spam | gap | Windows GUI |
| Hotkeys | `hotkey.validate` | validate_hotkey | n/a | — | — | covered | `test_40` |
| Hotkeys | `hotkey.global` | pynput | config | suppressed while modal | — | gap | Windows native |
| Update | `update.exe_download` | Download & Install | staging | fail no media change | refuse if recording | covered | `test_39` |
| Update | `update.msix_store` | Store prompt | n/a | — | detect via GitHub | covered | `test_39` |
| Shutdown | `quit.during_capture` | Save/Cancel | save async | — | — | gap | Windows GUI |
| Capture | `disk.critical/warn` | prepare | refuse/warn | — | — | partial | `test_04` |
| Audio | `mic.endpoint_change` | runtime | — | — | — | gap | hardware |
| DPI | `geometry.mixed_scale` | plan | — | — | — | partial | `test_14`,`test_35` |

| Annotate | `ann.eraser.pointf` | erase sweep | — | TypeError regression | continuous QPointF | covered | `test_53` |
| Annotate | `ann.photo.transform` | rotate/flip/crop×undo | history | — | geometry | covered | `test_53` |
| Dock | `dock.discovery` | startup strobe | process session | acknowledge | settings reload | covered | `test_50` |
| Dock | `dock.popup_focus` | close_on_focus_loss | — | popup/modal | combo/menu | covered | `test_50` |
| Pill | `pill.closeEvent` | teardown | discard | no modal exec | recording | covered | `test_52` |
| Overlay | `selection.handles.*` | 8 resize handles | region | — | PointF drag | covered | `test_51` |

## Coverage summary

| Metric | Value |
| --- | --- |
| Inventory primary action IDs | ~58 |
| Covered | ~45 |
| Partial | ~8 |
| Gap (hardware/Store/tray/MainWindow) | ~5 |
| Approx covered+partial share | **~91%** of inventory rows; **~78%** fully covered |

Adversarial report: [`ADVERSARIAL_AUDIT_REPORT.md`](ADVERSARIAL_AUDIT_REPORT.md).
Recompute after expanding suites; keep this table honest.
Update when adding catalogue rows in `helpers/action_matrix.py`.

## Editor sections/mute (2026-10-28)
Covered: rail click/switch/exclusivity, preserve edits, mute add/edit/remove and
source bounds, marker paint, preview boundaries/manual/global mute, dirty exit
and navigation, trim inputs/reset, compact rail visibility, playback timer stop.
Decoded media covers trim with beginning/interior deletion and retained audio.
Pending: Windows desktop animation/DPI and installed EXE/MSIX parity acceptance.
