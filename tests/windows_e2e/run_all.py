#!/usr/bin/env python3
"""One-click sequential runner for Windows E2E Testing.

Usage (from repo root)::

    python tests/windows_e2e/run_all.py
    python tests/windows_e2e/run_all.py --markers feature_recording
    python tests/windows_e2e/run_all.py --dry-report

Exit codes
----------
0 = pytest succeeded (skips allowed)
1 = pytest failures/errors OR report generation failed
2 = harness precondition failure (bad paths / missing pytest)

This script never claims Windows GUI E2E passed when running on non-Windows;
it prints an explicit environment banner for the QA report notes.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
E2E = Path(__file__).resolve().parent
DEFAULT_REPORTS = ROOT / "artifacts" / "windows_e2e"


def _banner(report_dir: Path) -> list[str]:
    notes = [
        f"platform={sys.platform}",
        f"report_dir={report_dir}",
        f"repo_root={ROOT}",
    ]
    if sys.platform != "win32":
        notes.append(
            "NON-WINDOWS HOST: windows_gui/windows_native cases are skipped by design. "
            "Do NOT treat this run as a Windows GUI E2E pass."
        )
    else:
        if os.environ.get("QT_QPA_PLATFORM") == "offscreen":
            notes.append(
                "QT_QPA_PLATFORM=offscreen on Windows: GUI interaction fidelity is limited."
            )
        else:
            notes.append("Windows host with desktop Qt platform (interactive GUI eligible).")
    return notes


def _test_modules(root):
    return sorted(root.rglob('test_*.py'))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run WWRecorder Windows E2E suite sequentially")
    parser.add_argument("--e2e-only", action="store_true", help="Run only the E2E catalogue instead of all regressions")
    parser.add_argument("--markers", default="", help="pytest -m expression (optional)")
    parser.add_argument(
        "--report-dir",
        default=str(DEFAULT_REPORTS),
        help="Directory for JUnit/JSON/Markdown/HTML reports",
    )
    parser.add_argument(
        "--dry-report",
        action="store_true",
        help="Generate sample report tooling check without running the full suite",
    )
    parser.add_argument(
        "--collect-only",
        action="store_true",
        help="Only collect tests (harness sanity)",
    )
    parser.add_argument("pytest_args", nargs="*", help="Extra args forwarded to pytest")
    args = parser.parse_args(argv)

    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    os.environ["WWR_E2E_REPORT_DIR"] = str(report_dir)
    junit_path = report_dir / "junit.xml"
    notes = _banner(report_dir)
    if sys.platform != "win32":
        notes.append("Windows-only import modules excluded: test_regressions.py, test_voice_player_ux.py. Run them on Windows.")

    # Ensure repo root is cwd-sensitive safe for imports
    os.chdir(ROOT)
    sys.path.insert(0, str(E2E))
    sys.path.insert(0, str(ROOT / "app"))

    if args.dry_report:
        from helpers.reporting import CaseResult, write_qa_summary, summarize
        import json
        from datetime import datetime, timezone
        import xml.etree.ElementTree as ET

        # Minimal synthetic JUnit to prove the report pipeline
        suite = ET.Element(
            "testsuite",
            name="dry-report",
            tests="2",
            failures="0",
            skipped="1",
            errors="0",
            time="0.01",
        )
        c1 = ET.SubElement(suite, "testcase", classname="dry.Harness", name="pipeline_ok", time="0.005")
        props = ET.SubElement(c1, "properties")
        ET.SubElement(props, "property", name="features", value="harness")
        c2 = ET.SubElement(suite, "testcase", classname="dry.Harness", name="skipped_example", time="0.001")
        ET.SubElement(c2, "skipped", message="dry-run example skip")
        tree = ET.ElementTree(suite)
        tree.write(junit_path, encoding="utf-8", xml_declaration=True)
        paths = write_qa_summary(
            junit_path,
            report_dir,
            title="WWRecorder Windows E2E — DRY REPORT (tooling check)",
            extra_notes=notes + ["dry-report mode: no product tests executed"],
        )
        print("Dry report written:")
        for key, path in paths.items():
            print(f"  {key}: {path}")
        return 0

    try:
        import pytest
    except ImportError:
        print("ERROR: pytest is not installed. Run: python -m pip install -r requirements-dev.txt", file=sys.stderr)
        return 2

    stamp = time.strftime("%Y%m%d-%H%M%S")
    html_pytest = report_dir / f"pytest-{stamp}.log"
    cmd = [
        str(E2E / "suites") if args.e2e_only else str(ROOT / "tests"),
        "--timeout=60", "--timeout-method=thread",
        "-vv",
        "--tb=short",
        f"--junitxml={junit_path}",
    ]
    # Sequential and stable: disable xdist if present; never add -n auto here.
    if args.collect_only:
        cmd.append("--collect-only")
    if args.markers:
        cmd.extend(["-m", args.markers])
    cmd.extend(args.pytest_args)

    print("=== WWRecorder Windows E2E ===")
    for note in notes:
        print(f"NOTE: {note}")
    print("pytest", " ".join(cmd))
    print(f"JUnit -> {junit_path}")

    # Run modules sequentially in separate processes. Qt native caches, hooks and
    # pending deleted widgets cannot leak between unrelated feature modules.
    import xml.etree.ElementTree as ET
    report_dir = report_dir.resolve()
    junit_path = report_dir / 'junit.xml'
    junit_path.unlink(missing_ok=True)
    environment = os.environ.copy()
    environment['PYTHONUTF8'] = '1'
    environment['PYTHONIOENCODING'] = 'utf-8'
    aggregate = ET.Element('testsuites')
    code = 0
    modules = _test_modules(E2E / 'suites' if args.e2e_only else ROOT / 'tests')
    with html_pytest.open('w', encoding='utf-8') as log:
        for index, module in enumerate(modules):
            if sys.platform != 'win32' and module.name in ('test_regressions.py', 'test_voice_player_ux.py'):
                suite = ET.SubElement(aggregate, 'testsuite', name=module.stem, tests='1', skipped='1')
                case = ET.SubElement(suite, 'testcase', name='windows_only_module')
                ET.SubElement(case, 'skipped', message='WINDOWS-ONLY: collection requires pythoncom/SoundCard')
                continue
            child_junit = report_dir / f'module-{index:03d}.xml'
            child_junit.unlink(missing_ok=True)
            child_cmd = [str(module), *[arg for arg in cmd[1:] if not arg.startswith('--junitxml=')],
                         f'--junitxml={child_junit}']
            process = subprocess.Popen([sys.executable, '-m', 'pytest', *child_cmd],
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding='utf-8', errors='replace', env=environment)
            for line in process.stdout:
                print(line, end='', flush=True)
                log.write(line)
                log.flush()
            child_code = process.wait()
            neutral_empty = child_code == 5 and bool(args.markers)
            if child_code and not neutral_empty:
                code = 1
            if child_junit.is_file():
                child_tree = ET.parse(child_junit).getroot()
                for suite in list(child_tree) if child_tree.tag == 'testsuites' else [child_tree]:
                    aggregate.append(suite)
            if (not child_junit.is_file() or
                (child_code and not neutral_empty and not any(c.tag in ('failure', 'error') for c in aggregate.iter()))):
                suite = ET.SubElement(aggregate, 'testsuite', name=module.stem, tests='1', errors='1')
                case = ET.SubElement(suite, 'testcase', classname='runner', name='pytest_process')
                error = ET.SubElement(case, 'error', message=f'pytest exited {child_code}; inspect console log')
                error.text = 'Native crash, test timeout, or harness error. This is a failed run, never a pass.'
                code = 1
            # Write after every module, retaining completed results even if interrupted.
            ET.ElementTree(aggregate).write(junit_path, encoding='utf-8', xml_declaration=True)

    # Always attempt QA summary when JUnit exists (including failed runs)
    if junit_path.is_file() and not args.collect_only:
        from helpers.reporting import write_qa_summary

        paths = write_qa_summary(
            junit_path,
            report_dir,
            title="WWRecorder Windows E2E — QA Summary",
            extra_notes=notes + [f"pytest_exit_code={code}", f"console_log={html_pytest}"],
        )
        print("QA reports:")
        for key, path in paths.items():
            print(f"  {key}: {path}")
    elif args.collect_only:
        print("collect-only complete; no JUnit summary written")
    else:
        print(f"ERROR: JUnit XML missing at {junit_path}", file=sys.stderr)
        return 1

    return 0 if code == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
