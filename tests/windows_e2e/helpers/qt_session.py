"""Session-scoped QApplication ownership for Windows E2E.

Purpose
-------
Docs/QA_AUDIT note that destroying/recreating QApplication between modules
can trigger native access violations on Windows. Prefer one session app.

Pass means
----------
``qapp`` fixture returns a live ``QApplication`` (or skips with a clear reason).
Widgets created in tests must be closed before the test ends.
"""

from __future__ import annotations

import os

import pytest

from .env import is_windows, prepare_process_environment, qt_importable, require_qt


def _ensure_platform_plugin() -> None:
    prepare_process_environment()
    # On Windows interactive runs, allow the real desktop platform unless the
    # operator forced offscreen for CI-like headless Windows agents.
    if is_windows() and os.environ.get("WWR_E2E_FORCE_OFFSCREEN", "").strip() in {"1", "true", "yes"}:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"


@pytest.fixture(scope="session")
def qapp():
    """Session-wide QApplication for the Windows E2E package."""
    _ensure_platform_plugin()
    require_qt()
    from PyQt6.QtWidgets import QApplication

    existing = QApplication.instance()
    if existing is not None:
        yield existing
        return
    app = QApplication([])
    app.setApplicationName("WWRecorder-Windows-E2E")
    yield app
    # Do not call app.quit()/deleteLater in a way that races other session fixtures;
    # process exit tears down Qt. Explicit shutdown caused historical AVs (QA_AUDIT).


@pytest.fixture
def qtbot_compat(qapp):
    """Minimal stand-in when pytest-qt is not installed.

    Provides ``waitUntil`` / ``wait`` / ``mouseClick``-free helpers so suites do
    not hard-require pytest-qt (which pulled broken EGL imports on some agents).
    """
    from PyQt6.QtTest import QTest
    from PyQt6.QtCore import QPoint, Qt
    from .waits import wait_until

    class _Bot:
        def waitUntil(self, callback, timeout=5000):
            wait_until(callback, timeout_s=timeout / 1000.0, message="qtbot_compat.waitUntil")

        def wait(self, ms: int):
            # Paced wait that still pumps Qt events. Prefer waitUntil(predicate).
            import time
            from PyQt6.QtWidgets import QApplication

            deadline = time.monotonic() + (ms / 1000.0)
            app = QApplication.instance()
            while time.monotonic() < deadline:
                if app is not None:
                    app.processEvents()
                time.sleep(0.01)

        def mouseClick(self, widget, button=None, pos=None):
            button = button or Qt.MouseButton.LeftButton
            point = pos or QPoint(max(1, widget.width() // 2), max(1, widget.height() // 2))
            QTest.mouseClick(widget, button, Qt.KeyboardModifier.NoModifier, point)

        def keyClick(self, widget, key, modifier=None):
            modifier = modifier or Qt.KeyboardModifier.NoModifier
            QTest.keyClick(widget, key, modifier)

    return _Bot()
