# Windows E2E Testing

Exhaustive, feature-tagged automated suite for the Windows WWRecorder app
(EXE + MSIX shared source). Display name: **Windows E2E Testing**.

> **Run this on Windows.** The suite is authorable from Linux, but
> `windows_gui` / `windows_native` cases skip off Windows. A green Linux
> collect/compile run is **not** a Windows GUI E2E pass.

## One-click run (Windows)

Install Python 3.13 once, then double-click **RUN_TESTS.cmd** in the repository
root. It creates/reuses `.venv`, installs dependencies without prompts, runs all
root regressions and E2E modules sequentially in isolated processes, then opens
`artifacts/windows_e2e/summary.html`. JSON, JUnit XML and console logs are saved
beside it. Unexpected dialogs fail instead of waiting for your input; every test
has a 60-second deadline. A crashed child produces an error report and remaining
modules still run. No manual clicks/keyboard input are part of these tests.

From the repository root in PowerShell:

```powershell
# Optional first time:
# python -m pip install -r requirements-dev.txt
# python -m pip install -r requirements.txt

.\tests\windows_e2e\run_all.ps1
```

Useful variants:

```powershell
.\tests\windows_e2e\run_all.ps1 -InstallDeps
.\tests\windows_e2e\run_all.ps1 -Markers "feature_recording and not windows_gui"
.\tests\windows_e2e\run_all.ps1 -Markers "brute_force"
.\tests\windows_e2e\run_all.ps1 -Markers "settings_matrix"
.\tests\windows_e2e\run_all.ps1 -Markers "parallel_actions"
.\tests\windows_e2e\run_all.ps1 -CollectOnly
.\tests\windows_e2e\run_all.ps1 -DryReport
.\tests\windows_e2e\run_all.ps1 -ForceOffscreen   # headless Windows agents only
```

Action inventory + coverage: `ACTION_INVENTORY.md`, `COVERAGE_MAP.md`.
Matrix authoring: `AI_TEST_CONTEXT.md` (brute-force section) + `helpers/action_matrix.py`.


Python equivalent:

```powershell
python tests\windows_e2e\run_all.py
python tests\windows_e2e\run_all.py --markers "feature_annotation"
```

## Reports (QA)

Default output directory: `artifacts/windows_e2e/`

| File | Purpose |
| --- | --- |
| `junit.xml` | Machine-readable JUnit |
| `summary.json` | Machine-readable totals + per-case + feature tags |
| `summary.md` | Human QA Markdown (pass/fail/skip, durations, failures) |
| `summary.html` | Lightweight HTML mirror |
| `pytest-*.log` | Console capture |

Regenerate summaries from an existing JUnit file:

```powershell
python tests\windows_e2e\generate_report.py --junit artifacts\windows_e2e\junit.xml --report-dir artifacts\windows_e2e
```

## Layout

```
tests/windows_e2e/
  README.md                 ← you are here
  AI_TEST_CONTEXT.md        ← how tests are written / updated
  COVERAGE_MAP.md           ← feature ↔ docs ↔ suite map
  run_all.ps1 / run_all.py  ← one-click sequential runner
  generate_report.py
  conftest.py               ← markers, stubs, session QApplication
  helpers/                  ← env, waits, media, reporting
  suites/                   ← feature-tagged tests
  reports/                  ← optional in-tree samples (generated artifacts go under artifacts/)
```

## Selective tags

Markers include `feature_recording`, `feature_screenshot`, `feature_audio`,
`feature_annotation`, `feature_editor`, `feature_playback`, `feature_hotkeys`,
`feature_ui`, `feature_settings`, `feature_distribution`, `feature_startup`,
`feature_keycast`, `feature_geometry`, `feature_icons`, `feature_processing`,
`feature_files`, `pure_logic`, `windows_gui`, `windows_native`, `harness`,
`behavior_question`.

Default run-all is **sequential** (no pytest-xdist).

## AI / maintainer context

Read [`AI_TEST_CONTEXT.md`](AI_TEST_CONTEXT.md) before extending the suite.
Coverage inventory: [`COVERAGE_MAP.md`](COVERAGE_MAP.md).
Product contracts: `docs/AI_CONTEXT.md`, `docs/DISTRIBUTION.md`, `docs/QA_AUDIT.md`.

Use Python runner `--e2e-only` for only the E2E catalogue. Default is the full suite.
Linux reports explicitly skip Windows API/import cases; rerun the same launcher
on Windows for the complete supported suite. Source tests do not certify physical
microphone fidelity or an installed package merely by running source widgets.

The Windows bootstrap prepares missing source FFmpeg automatically from the
imageio-ffmpeg development wheel, preserving any existing app/ffmpeg.exe.
