# AI / maintainer context — Windows E2E Testing

This file is the durable handoff for humans and models working on
`tests/windows_e2e/`. Product behavior truth remains `docs/AI_CONTEXT.md`;
this document explains **how the tests are written, mapped, run, and updated**.

## Why this suite exists

Existing `tests/test_*.py` modules are valuable regressions. This package adds:

1. A **named Windows E2E Testing area** with heavy comments and feature tags
2. A **one-click sequential runner** + QA-verifiable reports
3. Distribution updater coverage (EXE verified download + Inno; MSIX Store-only)
4. Helpers that refuse silent false greens (platform guards, media safety)

## How tests are written

### Layers

| Layer | Location | Rules |
| --- | --- | --- |
| Harness | `helpers/`, `conftest.py`, `test_00_*` | Must stay green; clear failures; no product mutations |
| Pure logic | `@pytest.mark.pure_logic` | Import app modules; stub Windows APIs only on non-Windows for *import*; assert contracts |
| Native | `@pytest.mark.windows_native` | Real win32 / WASAPI / WinRT; auto-skip off Windows |
| GUI | `@pytest.mark.windows_gui` | Interactive desktop widgets; auto-skip off Windows; skip if forced offscreen when fidelity matters |

### Comment contract (required)

Every suite module starts with purpose / preconditions / pass means.
Helpers document Windows-only notes. Skips must say `WINDOWS-ONLY:` or
`BEHAVIOR QUESTION BQ-…`.

### Sync style

Prefer `helpers.waits.wait_until(predicate)` over fixed sleeps as the only
sync. Short paced waits that still `processEvents()` are allowed for pacing,
never as the sole correctness condition.

### Media safety

Use `helpers.media.isolated_output_root`. Never delete the only playable copy
silently (`safe_rmtree` refuses when playable files remain).

### Qt ownership

Session-scoped `qapp` fixture (see QA_AUDIT: recreating QApplication between
modules caused native AVs). Close widgets at end of each test. Do not call
blocking `QThread.wait` forever without a timeout.

### Markers

Registered in `conftest.py`. Feature tags become JUnit `features` properties
for the QA report. Default run-all does not filter markers.

## Brute-force / combinatorial matrices

Goal: cover **every meaningful control × save/cancel/Escape × busy state**,
not only happy-path smoke. Authoring pattern:

1. Inventory the action in [`ACTION_INVENTORY.md`](ACTION_INVENTORY.md)
   (covered / partial / gap).
2. Add a catalogue row in `helpers/action_matrix.py` (`SETTINGS_TOGGLES`,
   `DOCK_ACTIONS`, `PILL_TOGGLE_ATTRS`, `ANNOTATION_TOOLS`, `EXIT_PATHS`,
   `BUSY_STATES`, `CAPTURE_PLAN_CASES`, …).
3. Parametrize a suite under `suites/test_3*_*.py` with markers
   `brute_force`, and when relevant `settings_matrix` / `parallel_actions`.
4. Failures must name **widget/action id + state** via
   `helpers.action_matrix.assert_invariant`.
5. Prefer shared helpers (`make_settings_sidebar`, `apply_settings_exit`,
   `make_pill`, `spam_clicks`) so matrices stay maintainable.
6. Suspected product defects →
   `docs/QA_AUDIT.md` with a reproducible test. Use failing asserts when
   the invariant is documented; `xfail`/`skip` only with a findings ticket id.

One-click `run_all` still runs everything. Selective:

```powershell
.\tests\windows_e2e\run_all.ps1 -Markers "brute_force"
.\tests\windows_e2e\run_all.ps1 -Markers "settings_matrix"
.\tests\windows_e2e\run_all.ps1 -Markers "parallel_actions"
.\tests\windows_e2e\run_all.ps1 -Markers "adversarial"
.\tests\windows_e2e\run_all.ps1 -Markers "area_dock or area_selection or area_transport"
```

### Adversarial suites (`test_50`–`test_54`)

Hostile matrices for dock/selection/pill/annotator/editor. Prefer real widgets
and helpers in `helpers/adversarial.py`. Document findings in
`ADVERSARIAL_AUDIT_REPORT.md`. Clear product defects vs documented contracts may
be fixed in the same PR; ambiguous UX stays fail+report.

Destructive sequences (if added later) must use explicit markers and be
documented in `ACTION_INVENTORY.md` — never default-on silent disk wipes.

## Coverage map

See [`COVERAGE_MAP.md`](COVERAGE_MAP.md) and [`ACTION_INVENTORY.md`](ACTION_INVENTORY.md).
When you add a product feature:

1. Classify shared vs distribution (per `docs/DISTRIBUTION.md`)
2. Add/extend a suite module under `suites/` with the right `feature_*` marker
3. Update `COVERAGE_MAP.md` / `ACTION_INVENTORY.md` and, if architecture changed, `docs/AI_CONTEXT.md`
4. If you discover a defect, update `docs/QA_AUDIT.md` and findings file when from matrices
5. If live code contradicts docs, add a `behavior_question` skip — **do not
   silently change product code** in this suite’s mandate

## How to update end-to-end when the product changes

1. Read `docs/AI_CONTEXT.md` state machines for the changed flow
2. Find the matching row in `COVERAGE_MAP.md`
3. Update or add assertions for the new contract
4. Run on Windows: `.\tests\windows_e2e\run_all.ps1 -Markers "feature_<area>"`
5. Run full: `.\tests\windows_e2e\run_all.ps1`
6. Attach `artifacts/windows_e2e/summary.md` in QA notes
7. If a test fails because the **doc** is wrong, open a behavior question
   rather than weakening the assertion without user input

## Running without claiming false greens

| Host | What you may claim |
| --- | --- |
| Linux cloud agent | Collection, py_compile, harness, pure_logic (with stubs). **Not** Windows GUI E2E pass |
| Windows offscreen | Limited widget construct; note offscreen in report |
| Windows desktop | Full suite including `windows_gui` / `windows_native` |

The runner always prints an environment banner into the QA summary notes.

## Report pipeline

`run_all.py` → pytest `--junitxml` → `helpers.reporting.write_qa_summary` →
`summary.json` / `summary.md` / `summary.html`.

Dry-run the reporter: `python tests/windows_e2e/run_all.py --dry-report`.

## Relationship to root pytest

Root `pytest.ini` still collects `tests/` (including this package). One-click
Windows E2E intentionally targets `tests/windows_e2e/suites` only so reports
stay scoped. Existing regression modules remain the day-to-day unit suite.

### Reviewing changed behavior from a non-Windows host

Portable collection excludes test_regressions.py and test_voice_player_ux.py.
When a visible contract/string changes, search those modules for old literals
and assertions before dispatching Windows CI. Update expectations only when the
product contract actually changed; never ignore or disable a failing regression.
Combined-audit validation: 930 portable / 1104 Windows passed, zero failures.

Security update 2026-10-29: suite 58 owns consent dialog tests. General Keycast
transport fixtures explicitly acknowledge first-use warning; do not weaken the
product warning to satisfy those fixtures. Windows CPython 3.13 x64 installs
requirements-windows.lock with hashes, including pytest 9.2.0; media preparation
uses the same pinned encoder as installers. Never restore imageio's old FFmpeg
fallback. Installed/build Qt DLL byte hashes are checked on Windows. Passing
these automated cases does not establish Store signing, corporate endpoint
policy, physical capture/audio or exploit resistance.

1.7.1: Suite 59 verifies compact notification/header/dock/annotation behavior and
production Store staging. Version assertion follows APP_VERSION 1.7.1. Hidden
notifications still finalize media. Store MSIX is prepared for Microsoft signing;
local-test signature assertions belong only to the test channel.

Validation: 976 portable tests passed (31 Windows-only skips); 1152 Windows tests passed (three desktop-only skips). Both package formats, frozen startup, dependency/media checks and unattended reports passed.

Recording/installer repair regressions cover active-clock video sampling, decoded
system/microphone timing, centered discard and Keycast cancellation/policies,
Windows icon resources and cross-process native update requests. The native bridge
case uses the Windows Qt backend; Linux skips it explicitly. No input is required.
