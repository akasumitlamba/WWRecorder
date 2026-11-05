"""JUnit/JSON/Markdown report post-processing for QA.

Purpose
-------
After pytest writes JUnit XML (and optional JSON via the runner), produce a
human QA summary with pass/fail/skip, durations, feature tags, and failures.

Pass means
----------
``write_qa_summary`` creates Markdown (+ optional HTML) under the report dir
and returns the Markdown path. Missing input XML is a hard error (no silent
empty-green report).
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional


FEATURE_TAG_RE = re.compile(r"feature_([a-z0-9_]+)")


@dataclass
class CaseResult:
    name: str
    classname: str
    time_s: float
    status: str  # passed | failed | skipped | error
    message: str = ""
    features: list[str] = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.features is None:
            self.features = []


def _features_from_properties(case: ET.Element) -> list[str]:
    features: list[str] = []
    for prop in case.findall("properties/property"):
        name = prop.attrib.get("name", "")
        value = prop.attrib.get("value", "")
        if name == "marker" and value.startswith("feature_"):
            features.append(value[len("feature_") :])
        if name == "features":
            features.extend(v.strip() for v in value.split(",") if v.strip())
    # Also scrape classname/name for feature_ markers pytest may encode
    blob = f"{case.attrib.get('classname', '')} {case.attrib.get('name', '')}"
    features.extend(FEATURE_TAG_RE.findall(blob))
    # Dedupe preserving order
    seen = set()
    ordered = []
    for item in features:
        if item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


def parse_junit(xml_path: Path) -> list[CaseResult]:
    xml_path = Path(xml_path)
    if not xml_path.is_file():
        raise FileNotFoundError(f"JUnit XML not found: {xml_path}")
    root = ET.parse(xml_path).getroot()
    # pytest may emit <testsuites><testsuite> or a single <testsuite>
    suites = []
    if root.tag == "testsuites":
        suites = list(root.findall("testsuite"))
    elif root.tag == "testsuite":
        suites = [root]
    else:
        raise ValueError(f"Unrecognized JUnit root tag: {root.tag}")

    results: list[CaseResult] = []
    for suite in suites:
        for case in suite.findall("testcase"):
            status = "passed"
            message = ""
            if case.find("failure") is not None:
                status = "failed"
                node = case.find("failure")
                message = (node.attrib.get("message") or "") + "\n" + (node.text or "")
            elif case.find("error") is not None:
                status = "error"
                node = case.find("error")
                message = (node.attrib.get("message") or "") + "\n" + (node.text or "")
            elif case.find("skipped") is not None:
                status = "skipped"
                node = case.find("skipped")
                message = node.attrib.get("message") or (node.text or "")
            results.append(
                CaseResult(
                    name=case.attrib.get("name", ""),
                    classname=case.attrib.get("classname", ""),
                    time_s=float(case.attrib.get("time", "0") or 0),
                    status=status,
                    message=message.strip(),
                    features=_features_from_properties(case),
                )
            )
    return results


def summarize(results: Iterable[CaseResult]) -> dict:
    results = list(results)
    counts = {"passed": 0, "failed": 0, "skipped": 0, "error": 0}
    by_feature: dict[str, dict[str, int]] = {}
    for case in results:
        counts[case.status] = counts.get(case.status, 0) + 1
        tags = case.features or ["untagged"]
        for tag in tags:
            bucket = by_feature.setdefault(tag, {"passed": 0, "failed": 0, "skipped": 0, "error": 0})
            bucket[case.status] = bucket.get(case.status, 0) + 1
    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "totals": counts,
        "total_cases": len(results),
        "total_duration_s": round(sum(c.time_s for c in results), 3),
        "by_feature": by_feature,
        "cases": [asdict(c) for c in results],
    }


def write_qa_summary(
    junit_xml: Path,
    report_dir: Path,
    *,
    title: str = "WWRecorder Windows E2E — QA Summary",
    extra_notes: Optional[list[str]] = None,
) -> dict[str, Path]:
    """Write JSON + Markdown (+ simple HTML) summaries. Returns output paths."""
    report_dir = Path(report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    results = parse_junit(junit_xml)
    summary = summarize(results)
    if extra_notes:
        summary["notes"] = list(extra_notes)

    json_path = report_dir / "summary.json"
    md_path = report_dir / "summary.md"
    html_path = report_dir / "summary.html"

    json_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    totals = summary["totals"]
    lines = [
        f"# {title}",
        "",
        f"Generated (UTC): `{summary['generated_at_utc']}`",
        "",
        "## Totals",
        "",
        f"| Passed | Failed | Error | Skipped | Duration (s) |",
        f"| ---: | ---: | ---: | ---: | ---: |",
        f"| {totals.get('passed', 0)} | {totals.get('failed', 0)} | {totals.get('error', 0)} | "
        f"{totals.get('skipped', 0)} | {summary['total_duration_s']} |",
        "",
        "## By feature tag",
        "",
        "| Feature | Passed | Failed | Error | Skipped |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for feature, bucket in sorted(summary["by_feature"].items()):
        lines.append(
            f"| `{feature}` | {bucket.get('passed', 0)} | {bucket.get('failed', 0)} | "
            f"{bucket.get('error', 0)} | {bucket.get('skipped', 0)} |"
        )
    lines += ["", "## Failures and errors", ""]
    problems = [c for c in results if c.status in {"failed", "error"}]
    if not problems:
        lines.append("_None._")
    else:
        for case in problems:
            lines.append(f"### `{case.classname}::{case.name}` ({case.status})")
            lines.append("")
            lines.append("```")
            lines.append(case.message or "(no message)")
            lines.append("```")
            lines.append("")
    lines += ["", "## Skips (sample)", ""]
    skips = [c for c in results if c.status == "skipped"]
    if not skips:
        lines.append("_None._")
    else:
        for case in skips[:80]:
            reason = (case.message or "").replace("\n", " ")
            lines.append(f"- `{case.name}` — {reason}")
        if len(skips) > 80:
            lines.append(f"- … and {len(skips) - 80} more")
    if extra_notes:
        lines += ["", "## Notes", ""]
        lines.extend(f"- {note}" for note in extra_notes)

    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # Minimal HTML mirror for browsers that do not render MD.
    html = [
        "<!DOCTYPE html><html><head><meta charset='utf-8'>",
        f"<title>{title}</title>",
        "<style>body{font-family:Segoe UI,sans-serif;margin:24px;} table{border-collapse:collapse;}"
        "td,th{border:1px solid #ccc;padding:6px 10px;} pre{background:#111;color:#eee;padding:12px;}</style>",
        "</head><body>",
        f"<h1>{title}</h1>",
        f"<p>See also <code>{md_path.name}</code> and <code>{json_path.name}</code>.</p>",
        "<pre>" + json.dumps(summary["totals"], indent=2) + "</pre>",
        "<h2>Failures</h2>",
    ]
    if not problems:
        html.append("<p><em>None.</em></p>")
    else:
        for case in problems:
            html.append(f"<h3>{case.classname}::{case.name}</h3>")
            html.append("<pre>" + (case.message or "").replace("<", "&lt;") + "</pre>")
    html.append("</body></html>")
    html_path.write_text("\n".join(html), encoding="utf-8")

    return {"json": json_path, "markdown": md_path, "html": html_path, "junit": Path(junit_xml)}
