"""State-machine-aware waits — prefer predicates over fixed sleeps.

Purpose
-------
GUI and worker flows in WWRecorder are asynchronous (prepare, mux, panel
transitions, fullscreen chrome). Tests must wait for *conditions*, not for a
magic number of milliseconds as the only sync mechanism.

Pass means
----------
``wait_until`` returns when ``predicate()`` is truthy before ``timeout_s``.
On timeout it raises ``AssertionError`` with the last failure detail — never
returns a soft failure that looks green.

Windows-only notes
------------------
Pump the Qt event loop while waiting so GUI-thread timers and signals advance.
Do not call blocking ``time.sleep`` alone on the GUI thread in tests that own
widgets.
"""

from __future__ import annotations

import time
from typing import Callable, Optional


class WaitTimeout(AssertionError):
    """Raised when a wait predicate never becomes true."""


def wait_until(
    predicate: Callable[[], bool],
    *,
    timeout_s: float = 5.0,
    interval_s: float = 0.05,
    message: str = "condition not met",
    pump_qt: bool = True,
) -> None:
    """Poll ``predicate`` until true or raise ``WaitTimeout``.

    Preconditions: predicate must be side-effect safe to call repeatedly.
    When ``pump_qt`` is True and a QApplication exists, process events each tick.
    """
    deadline = time.monotonic() + timeout_s
    last_error: Optional[BaseException] = None
    qapp = None
    if pump_qt:
        try:
            from PyQt6.QtWidgets import QApplication

            qapp = QApplication.instance()
        except Exception:
            qapp = None

    while time.monotonic() < deadline:
        try:
            if predicate():
                return
        except Exception as exc:  # surface intermittent predicate bugs clearly
            last_error = exc
        if qapp is not None:
            qapp.processEvents()
        time.sleep(interval_s)

    detail = f"{message} (timeout={timeout_s}s)"
    if last_error is not None:
        detail = f"{detail}; last predicate error: {type(last_error).__name__}: {last_error}"
    raise WaitTimeout(detail)


def wait_thread_finished(thread, *, timeout_s: float = 10.0, message: str = "QThread still running") -> None:
    """Wait for a QThread to finish without hanging the suite forever."""
    if thread is None:
        return
    wait_until(
        lambda: not thread.isRunning(),
        timeout_s=timeout_s,
        message=message,
        pump_qt=True,
    )
