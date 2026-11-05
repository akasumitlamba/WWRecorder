"""Bounded, cancellable encoder supervision, independent of the GUI thread."""
from collections import deque
import subprocess
import threading
import time


def supervise_export(process, duration_ms, cancelled, progress, *,
                     inactivity_seconds=900, total_seconds=None):
    # A healthy long export may run for hours. Only advancing encoder time
    # resets the stall watchdog; repeated diagnostics cannot keep it alive.
    total_seconds = total_seconds or max(21600, duration_ms / 1000 * 30 + 900)
    diagnostics = deque(maxlen=64)
    state = {'advanced': time.monotonic(), 'position': -1}
    lock = threading.Lock()
    finished = threading.Event()

    def consume():
        pending = b''
        try:
            while True:
                block = getattr(process.stderr, 'read1', process.stderr.read)(4096)
                if not block:
                    break
                pending += block
                while b'\n' in pending:
                    line, pending = pending.split(b'\n', 1)
                    text = line[-2048:].decode(errors='replace').strip()
                    with lock:
                        diagnostics.append(text)
                        if text.startswith('out_time_us='):
                            try:
                                position = int(text.split('=', 1)[1])
                                if position > state['position']:
                                    state.update(position=position, advanced=time.monotonic())
                                    if duration_ms > 0:
                                        progress(max(0, min(99, int(position / (duration_ms * 10)))))
                            except ValueError:
                                pass
                # Even a child emitting an endless line has bounded memory.
                pending = pending[-4096:]
            if pending:
                with lock:
                    diagnostics.append(pending[-2048:].decode(errors='replace'))
        finally:
            finished.set()

    reader = threading.Thread(target=consume, name='export-diagnostics', daemon=True)
    reader.start()
    started = time.monotonic()
    failure = None
    try:
        while process.poll() is None:
            if cancelled():
                break
            now = time.monotonic()
            with lock:
                stalled = now - state['advanced'] >= inactivity_seconds
            if stalled or now - started >= total_seconds:
                failure = TimeoutError('Export stopped because processing stopped making progress '
                                       'or exceeded its time limit. Your original recording is unchanged.')
                break
            time.sleep(0.05)
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
        reader.join(timeout=2)
        if reader.is_alive():
            raise RuntimeError('Export diagnostics did not close. Your original recording is unchanged.')
    if failure:
        raise failure
    with lock:
        return '\n'.join(list(diagnostics)[-10:]) or 'Unknown encoder error'
