"""Shared helpers for the Windows E2E Testing area.

Import leaf helpers explicitly (``from tests.windows_e2e.helpers.env import ...``)
or via the short paths used inside this package. Keep this module free of
side effects so collection cannot silently mutate the process environment.
"""

__all__ = [
    "env",
    "waits",
    "media",
    "qt_session",
    "assertions",
    "reporting",
]
