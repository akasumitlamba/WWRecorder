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
