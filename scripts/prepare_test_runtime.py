"""Prepare missing test FFmpeg from the development wheel; preserve existing tools."""
from pathlib import Path
import shutil
import subprocess
import tempfile


def prepare_ffmpeg(root, finder=None):
    target = Path(root) / 'app' / 'ffmpeg.exe'
    target.parent.mkdir(parents=True, exist_ok=True)
    def validate(executable):
        result = subprocess.run([str(executable), '-version'], capture_output=True,
                                text=True, timeout=15)
        if result.returncode or not result.stdout.startswith('ffmpeg version'):
            raise RuntimeError('Test FFmpeg did not pass its version probe')
    if target.is_file():
        validate(target)
        return target
    if finder is None:
        from imageio_ffmpeg import get_ffmpeg_exe
        finder = get_ffmpeg_exe
    with tempfile.NamedTemporaryFile(dir=target.parent, prefix='.ffmpeg-', suffix='.exe', delete=False) as file:
        temporary = Path(file.name)
    try:
        shutil.copy2(finder(), temporary)
        validate(temporary)
        if not target.exists():
            temporary.replace(target)
        else:
            validate(target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


if __name__ == '__main__':
    result = prepare_ffmpeg(Path(__file__).resolve().parents[1])
    print('Test FFmpeg ready:', result.name)
