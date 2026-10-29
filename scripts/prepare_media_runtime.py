"""Fetch the approved Windows encoder with archive and executable integrity checks."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def prepare_ffmpeg(root, finder=None):
    target = Path(root) / 'app' / 'ffmpeg.exe'
    target.parent.mkdir(parents=True, exist_ok=True)
    approved = json.loads((ROOT / 'packaging/shared/media-security.json').read_text())['ffmpeg']

    def validate(executable):
        result = subprocess.run([str(executable), '-version'], capture_output=True,
                                text=True, timeout=15)
        if result.returncode or not result.stdout.startswith('ffmpeg version'):
            raise RuntimeError('Test FFmpeg did not pass its version probe')

    if target.is_file() and (finder is not None or digest(target) == approved['exe_sha256']):
        validate(target)
        return target
    with tempfile.TemporaryDirectory(prefix='.ffmpeg-', dir=target.parent) as directory:
        directory = Path(directory)
        executable = directory / 'ffmpeg.exe'
        if finder is not None:  # Injected fixture; release gate never accepts this exemption.
            shutil.copy2(finder(), executable)
        else:
            archive = directory / 'runtime.zip'
            with urllib.request.urlopen(approved['url'], timeout=60) as response, archive.open('wb') as out:
                count = 0
                while block := response.read(1024 * 1024):
                    count += len(block)
                    if count > 256 * 1024 * 1024:
                        raise ValueError('Encoder download exceeds its allowed size')
                    out.write(block)
            if digest(archive) != approved['archive_sha256']:
                raise ValueError('Encoder archive integrity check failed')
            with zipfile.ZipFile(archive) as bundle:
                names = [n for n in bundle.namelist() if n.endswith('/bin/ffmpeg.exe')]
                if len(names) != 1 or bundle.getinfo(names[0]).file_size > 256 * 1024 * 1024:
                    raise ValueError('Unexpected encoder archive contents')
                with bundle.open(names[0]) as source, executable.open('wb') as out:
                    shutil.copyfileobj(source, out)
            if digest(executable) != approved['exe_sha256']:
                raise ValueError('Encoder executable integrity check failed')
        validate(executable)
        executable.replace(target)
    return target


if __name__ == '__main__':
    print('Verified media runtime:', prepare_ffmpeg(ROOT).name)
