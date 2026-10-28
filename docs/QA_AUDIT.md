# Verification status

## Preview package 1.7.0.12
- Automated Linux source run: 818 passed, 29 Windows-only skips, zero failures.
- Generated audio exports decoded to verify mute sections with trim and cuts.
- UI tests exercise actual widgets, section selection, dirty state and layout.
- Runner regression checks verify pass/failure/crashed-child reports and no input.
- Native Qt dependency checks and frozen startup probe gate both package formats.
- Windows CI: 992 passed, 3 desktop-only skipped; no failures. Both installer builds and frozen startup probe passed.
- Packaged runtime, hashes, assets and MSIX identity/signature containers verified.
- Release privacy scan: 1212 items, zero findings.
- Real USB/Bluetooth microphone fidelity, Windows DPI/animation acceptance and
  installed EXE/MSIX interactive acceptance still require Windows verification.

Resolved defects include missing frozen Qt detection, media-safe live recording
close, eraser zoom hit-testing, updater origin validation, popup/worker lifecycle,
selective-audio retiming, control alignment, and shell icon corner transparency.
No automated source suite alone certifies physical device or installed-package behavior.
