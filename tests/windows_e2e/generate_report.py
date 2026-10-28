#!/usr/bin/env python3
"""Regenerate QA Markdown/JSON/HTML from an existing JUnit XML file."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

E2E = Path(__file__).resolve().parent
sys.path.insert(0, str(E2E))

from helpers.reporting import write_qa_summary  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--junit", required=True, type=Path)
    parser.add_argument("--report-dir", required=True, type=Path)
    parser.add_argument("--note", action="append", default=[])
    args = parser.parse_args(argv)
    if not args.junit.is_file():
        print(f"ERROR: JUnit not found: {args.junit}", file=sys.stderr)
        return 2
    paths = write_qa_summary(args.junit, args.report_dir, extra_notes=args.note)
    for key, path in paths.items():
        print(f"{key}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
