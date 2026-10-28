"""Readable assertion helpers with feature-tag context strings."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable


def assert_eq(actual: Any, expected: Any, *, because: str) -> None:
    if actual != expected:
        raise AssertionError(f"{because}\n  expected: {expected!r}\n  actual:   {actual!r}")


def assert_true(value: Any, *, because: str) -> None:
    if not value:
        raise AssertionError(f"{because}\n  value was falsy: {value!r}")


def assert_false(value: Any, *, because: str) -> None:
    if value:
        raise AssertionError(f"{because}\n  value was truthy: {value!r}")


def assert_keys_include(mapping: dict, keys: Iterable[str], *, because: str) -> None:
    missing = [k for k in keys if k not in mapping]
    if missing:
        raise AssertionError(f"{because}\n  missing keys: {missing}\n  present: {sorted(mapping)}")


def assert_path_exists(path: Path | str, *, because: str) -> None:
    path = Path(path)
    if not path.exists():
        raise AssertionError(f"{because}\n  missing path: {path}")


def assert_doc_contract(condition: bool, *, contract: str, evidence: str) -> None:
    """Assert a documented AI_CONTEXT / DISTRIBUTION contract."""
    if not condition:
        raise AssertionError(
            f"Documented contract failed: {contract}\n  evidence: {evidence}"
        )
