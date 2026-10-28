"""Harness self-checks — must stay green or the suite is untrustworthy.

Purpose
-------
Validate imports, paths, markers, report helpers, and wait utilities before
any product assertion. A red harness means QA cannot trust later results.

Preconditions: repository layout intact; pytest collected this package.
Pass means: every check below succeeds without stubs pretending to be Windows GUI.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

from helpers.env import (
    APP_DIR,
    E2E_ROOT,
    REPO_ROOT,
    DEFAULT_REPORT_DIR,
    is_windows,
    prepare_process_environment,
    qt_importable,
)
from helpers.reporting import parse_junit, summarize, write_qa_summary
from helpers.waits import wait_until, WaitTimeout

pytestmark = [pytest.mark.harness, pytest.mark.pure_logic]


def test_repo_layout_paths_exist():
    assert REPO_ROOT.joinpath("AGENTS.md").is_file()
    assert APP_DIR.joinpath("main.py").is_file()
    assert E2E_ROOT.joinpath("README.md").is_file()
    assert E2E_ROOT.joinpath("run_all.ps1").is_file()
    assert E2E_ROOT.joinpath("run_all.py").is_file()
    assert E2E_ROOT.joinpath("AI_TEST_CONTEXT.md").is_file()
    assert (E2E_ROOT / "helpers" / "env.py").is_file()
    assert (E2E_ROOT / "suites").is_dir()


def test_prepare_process_environment_is_idempotent():
    first = prepare_process_environment()
    second = prepare_process_environment()
    assert isinstance(first, dict) and isinstance(second, dict)
    assert str(APP_DIR) in sys.path


def test_wait_until_succeeds_and_times_out_clearly():
    flag = {"ok": False}

    def flip():
        flag["ok"] = True
        return True

    wait_until(flip, timeout_s=1.0, interval_s=0.01, message="should pass", pump_qt=False)
    with pytest.raises(WaitTimeout, match="never-true"):
        wait_until(lambda: False, timeout_s=0.15, interval_s=0.05, message="never-true", pump_qt=False)


def test_report_pipeline_roundtrip(tmp_path):
    import xml.etree.ElementTree as ET

    junit = tmp_path / "junit.xml"
    suite = ET.Element("testsuite", name="t", tests="3", failures="1", skipped="1", errors="0", time="0.2")
    passed = ET.SubElement(suite, "testcase", classname="a.B", name="ok", time="0.05")
    props = ET.SubElement(passed, "properties")
    ET.SubElement(props, "property", name="features", value="recording,audio")
    failed = ET.SubElement(suite, "testcase", classname="a.B", name="bad", time="0.1")
    ET.SubElement(failed, "failure", message="boom").text = "traceback"
    skipped = ET.SubElement(suite, "testcase", classname="a.B", name="skip", time="0.01")
    ET.SubElement(skipped, "skipped", message="WINDOWS-ONLY")
    ET.ElementTree(suite).write(junit, encoding="utf-8", xml_declaration=True)

    results = parse_junit(junit)
    summary = summarize(results)
    assert summary["totals"]["passed"] == 1
    assert summary["totals"]["failed"] == 1
    assert summary["totals"]["skipped"] == 1
    assert "recording" in summary["by_feature"]
    paths = write_qa_summary(junit, tmp_path / "out", extra_notes=["harness roundtrip"])
    assert paths["markdown"].is_file()
    assert paths["json"].is_file()
    assert paths["html"].is_file()
    text = paths["markdown"].read_text(encoding="utf-8")
    assert "boom" in text
    assert "WINDOWS-ONLY" in text


def test_suite_modules_parse_cleanly():
    """Static syntax check for every suite/helper module (no execution)."""
    roots = [E2E_ROOT / "helpers", E2E_ROOT / "suites", E2E_ROOT]
    files = []
    for root in roots:
        files.extend(sorted(root.glob("*.py")))
        if root.name in {"helpers", "suites"}:
            files.extend(sorted(root.glob("**/*.py")))
    assert files, "no python files found under windows_e2e"
    for path in files:
        source = path.read_text(encoding="utf-8")
        try:
            ast.parse(source, filename=str(path))
        except SyntaxError as exc:
            raise AssertionError(f"Syntax error in harness file {path}: {exc}") from exc


def test_qt_availability_is_reported_not_faked(e2e_env_info):
    ok, detail = qt_importable()
    # On this agent we expect Qt after libEGL install; either way must be explicit.
    assert isinstance(ok, bool)
    assert detail
    assert e2e_env_info["is_windows"] is is_windows()


def test_default_report_dir_is_under_artifacts():
    assert "artifacts" in DEFAULT_REPORT_DIR.parts
    assert DEFAULT_REPORT_DIR.name == "windows_e2e"
