"""Explicit local hardware test, also usable through the installed MSIX entrypoint.

Never runs automatically. Captures a 160x120 screen region and short audio
samples into the caller's directory; does not modify app settings.
"""
import faulthandler
import json
import os
from pathlib import Path
import subprocess
import threading
import time


def run(output_dir, thorough=False):
    from distribution import package_family_name
    from recorder import RecordingEngine, get_ffmpeg_path
    from soundcard import mediafoundation as backend

    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    report = {"package_family": package_family_name(), "status": "running", "recordings": [],
              "propvariant_allocation": backend._PropVariant._wwr_native_size}
    report_path = output / "recording-smoke.json"

    def save():
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    def timeout():
        report["status"] = "timeout"
        save()
        os._exit(124)  # Diagnostic process only; retain all work media.

    watchdog = threading.Timer(300 if thorough else 90, timeout)
    watchdog.daemon = True
    watchdog.start()
    crash_log = (output / "native-crash.log").open("a", encoding="utf-8")
    faulthandler.enable(crash_log, all_threads=True)
    save()
    try:
        modes = [
            {"system_audio": True, "mic": True},
            {"system_audio": False, "mic": True},
            {"system_audio": True, "mic": False},
        ]
        if thorough:
            modes += [{"system_audio": False, "mic": False},
                      {"system_audio": True, "mic": True}]
        for index, audio in enumerate(modes):
            engine = RecordingEngine()
            folder = output / f"capture-{index + 1}"
            folder.mkdir(exist_ok=True)
            region = {"top": 0, "left": 0, "width": 640 if thorough else 160,
                      "height": 360 if thorough else 120}
            if not engine.start(region, str(folder), audio):
                raise RuntimeError("Recording preparation failed")
            active_seconds = 60 if thorough and index == 4 else (6 if thorough else 2)
            cycles = 3 if thorough else 1
            for _ in range(cycles):
                time.sleep(active_seconds / (cycles * 2))
                engine.pause()
                time.sleep(0.3)
                engine.resume()
                time.sleep(active_seconds / (cycles * 2))
            saved = engine.stop()
            events = engine.drain_runtime_events()
            if any(kind == "audio_error" for kind, _ in events):
                raise RuntimeError(f"Audio endpoint error: {events}")
            result = subprocess.run([get_ffmpeg_path(), "-v", "error", "-i", saved,
                                     "-progress", "pipe:1", "-f", "null", "-"],
                                    capture_output=True, timeout=45, creationflags=subprocess.CREATE_NO_WINDOW)
            if result.returncode:
                raise RuntimeError("Saved recording failed FFmpeg decoding: " + result.stderr.decode(errors="replace"))
            report["recordings"].append({"path": saved, "bytes": Path(saved).stat().st_size,
                                        "audio": audio, "region": region, "active_seconds": active_seconds,
                                        "pause_resume_cycles": cycles,
                                        "decode_progress": result.stdout.decode(errors="replace"),
                                        "decode_exit": result.returncode, "events": events})
            save()
        report["status"] = "passed"
        save()
        return 0
    except Exception as exc:
        report["status"] = "failed"
        report["error"] = str(exc)
        save()
        return 1
    finally:
        watchdog.cancel()
        faulthandler.disable()
        crash_log.close()
