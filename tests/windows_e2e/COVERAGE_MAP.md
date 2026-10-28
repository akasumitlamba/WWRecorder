# Windows E2E coverage map

Maps product docs/contracts → suite modules. “Partial” means pure/source
contracts covered; hardware/Store acceptance still open (see Known gaps).

| Feature area (docs) | Primary contracts | Suite module(s) | Markers | Depth |
| --- | --- | --- | --- | --- |
| Recording state machine | AI_CONTEXT Recording | `test_04`, `test_23`, `test_12` | `feature_recording` | Partial (engine guards + source); live gdigrab = Windows smoke / recording_smoke |
| Screenshot flow | AI_CONTEXT Screenshot | `test_05` | `feature_screenshot` | Partial (coords/overlay); freeze/DWM = Windows GUI |
| Audio / mic / WASAPI | AI_CONTEXT 2026-10-24, DISTRIBUTION | `test_06`, `test_22` | `feature_audio` | Partial; real endpoints = `windows_native` |
| Annotation live + photo | AI_CONTEXT Annotation | `test_07`, `test_11` | `feature_annotation` | Partial; drawing gestures = GUI |
| Video editor / export | AI_CONTEXT Video editing | `test_08` | `feature_editor` | Partial; FFmpeg export = Windows + ffmpeg |
| Playback / fullscreen | AI_CONTEXT fullscreen chrome | `test_08`, `test_11` | `feature_playback` | Partial (timer/source); OS fullscreen = GUI |
| Hotkeys | AI_CONTEXT / project | `test_10` | `feature_hotkeys` | Defaults + validation; listener thread = Windows |
| Dock / panels / settings UI | AI_CONTEXT 2026-10-26/27 | `test_09`, `test_20` | `feature_ui`, `feature_settings` | Construct + Store button; layout animation = GUI |
| Settings schema | DEFAULT_CONFIG | `test_03` | `feature_settings` | Strong (pure) |
| Distribution EXE/MSIX | DISTRIBUTION.md | `test_02`, `test_16` | `feature_distribution` | Strong for seams; Store install = manual |
| Startup integration | DISTRIBUTION / startup_integration | `test_15` | `feature_startup` | Source + construct; WinRT enable = native |
| Keycast | AI_CONTEXT 2026-10-26 | `test_13` | `feature_keycast` | Source contracts; hooks = native GUI |
| Geometry / DPI | AI_CONTEXT Coordinate spaces | `test_14`, `test_21` | `feature_geometry` | Source; mixed-DPI hardware = manual |
| Icons / cursors | AI_CONTEXT 2026-10-27 | `test_18` | `feature_icons` | Assets present; contrast pixels = existing unit tests |
| Processing notice | AI_CONTEXT 2026-10-27 | `test_17` | `feature_processing` | Strong (construct + alias) |
| File ops / recovery | AI_CONTEXT media ownership | `test_12`, `test_19` | `feature_files` | Strong path safety |
| Escape / chrome baseline | AI_CONTEXT Interaction | `test_11` | `feature_ui` | Source |
| Harness | this package | `test_00`, `test_01` | `harness` | Strong |
| Dual-channel updater decisions | DISTRIBUTION 2026-10-27 | `test_24`, `test_02`, `test_09`, `test_16` | `feature_distribution` | Strong (mocked network); real download/Inno = Windows acceptance |
| Settings toggle × exit matrix | AI_CONTEXT draft-until-Save | `test_30` | `settings_matrix`, `brute_force` | Strong (widget construct + persist mirror) |
| Dock action spam | AI_CONTEXT dock | `test_31` | `brute_force` | Strong construct; tray = gap |
| Pill toggles / preparing guards | Recording state machine | `test_32`, `test_34` | `brute_force`, `parallel_actions` | Strong with FakeRecordingEngine |
| Escape exit paths | Interaction baseline | `test_33` | `brute_force` | Strong settings Escape; tray quit = gap |
| Capture plan boundaries | Geometry / screenshot | `test_35` | `brute_force` | Strong pure; mixed-DPI HW = gap |
| Annotation tool matrix | Annotation | `test_36` | `brute_force` | Strong photo tools; live laser gestures = GUI |
| Editor merge / fullscreen / export | Video editing | `test_37` | `brute_force` | Strong merge pure; FFmpeg export = Windows |
| Gallery rename/delete guards | Files | `test_38` | `brute_force` | Partial (construct + Escape rename) |
| Update prompt edition matrix | DISTRIBUTION dual-channel | `test_39` | `brute_force` | Strong mocked; real Inno/Store = Windows |
| Hotkey conflict matrix | Hotkeys / settings Save | `test_40` | `brute_force` | Strong validate + Save conflict |

| Adversarial Area 1 dock | Edge snap, discovery, anim spam, popup focus | `test_50` | `adversarial`, `area_dock` | Strong + ADV fixes |
| Adversarial Area 2 selection | 8 handles, tiny/inverted, Escape, PointF | `test_51` | `adversarial`, `area_selection` | Strong pure |
| Adversarial Area 3 transport | Illegal transitions, closeEvent no modal | `test_52` | `adversarial`, `area_transport` | Strong + ADV-004 |
| Adversarial Area 4 annotator | Eraser PointF matrix, photo rotate/crop undo | `test_53` | `adversarial`, `area_annotator` | Strong + ADV-001/002 |
| Adversarial Area 5 editor | Merge matrix, fullscreen/export contracts | `test_54` | `adversarial`, `area_editor` | Strong pure |

Interactive action checklist: [`ACTION_INVENTORY.md`](ACTION_INVENTORY.md).
Adversarial findings: [`ADVERSARIAL_AUDIT_REPORT.md`](ADVERSARIAL_AUDIT_REPORT.md).

## Known gaps (explicit)

- Full gdigrab recording + pause/resume + mux decode matrix (use
  `WWRecorder.exe --recording-smoke-test` / `--recording-qa-test` on installed builds)
- Real microphone/system-audio endpoint hotplug
- Mixed-DPI multi-monitor physical acceptance
- Microsoft Store delivery / WACK / certification
- Tray icon / shell integration visuals + tray quit spam
- Global hotkey listener while modal open (needs Windows desktop)
- Quit-during-capture Save/Cancel dialog (full MainWindow)
- Endurance long-capture
- Installed EXE↔MSIX settings migration on a real machine (automated helpers cover source paths)
- Late worker signals after cancel (needs threaded capture fakes beyond FakeRecordingEngine)

These gaps are intentional: they need Windows hardware or Store identity, not
silent mocks that look green.

## Sectioned editor / selective audio (2026-10-28)
`test_55_editor_sections_mute.py`: real section buttons/time controls, exclusive
selection, edit preservation, range preview, manual/global mute, source bounds,
unsaved navigation/discard, trim/reset, compact rail and timer lifecycle.
`tests/test_selective_audio_export.py`: actual editor command on generated media,
decoded silence/audible spans and trim/delete duration. Suites 08/37/54 remain
enabled. Portable widget checks do not replace Windows animation/DPI acceptance.

## Desktop feedback regressions

`tests/test_editor_feedback.py`: cross-kind endpoint/body snaps, zoom/Alt precision,
read-only trim summary, native-title uniqueness, speaker pixel invariance,
unattended scrub coalescing and real decoded seek frame before release.
`tests/test_feedback_panels.py`: single-row screenshot tool/action layout at
700/1024/1440px, horizontal footer order, uniform selectors, dock hover-state
icons, centered laser alpha profile and red Quit/annotation-only brush assets.
`tests/test_keycast.py`: raw Windows/media/F-key mapping and held-Shift chord case.
