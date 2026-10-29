"""One-click tests use the same pinned encoder as the production payload."""
from pathlib import Path
import subprocess  # Compatibility seam for existing test probes.
try:
    from scripts.prepare_media_runtime import prepare_ffmpeg
except ModuleNotFoundError:
    from prepare_media_runtime import prepare_ffmpeg

if __name__ == '__main__':
    print('Test FFmpeg ready:', prepare_ffmpeg(Path(__file__).resolve().parents[1]).name)
