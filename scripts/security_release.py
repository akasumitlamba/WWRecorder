"""Fail-closed native media gate and release component evidence (no signing claim)."""
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def verify_media(payload, manifest=None):
    manifest = manifest or json.loads((ROOT / 'packaging/shared/media-security.json').read_text())
    files = [p for p in Path(payload).rglob('*') if p.is_file()]
    expected = {'ffmpeg.exe': manifest['ffmpeg']['exe_sha256'], **manifest['qt']['dll_sha256']}
    found = {}
    for name, digest in expected.items():
        matches = [p for p in files if p.name.lower() == name.lower()]
        if not matches or any(sha256(p) != digest for p in matches):
            raise ValueError('Unapproved or missing media binary: ' + name)
        found[name] = digest
    # Refuse a mixed payload retaining older decoder DLLs alongside the approved ones.
    for p in files:
        if re.fullmatch(r'(avcodec|avformat|avutil|swresample|swscale)-\d+\.dll', p.name.lower()):
            if p.name not in expected:
                raise ValueError('Unexpected legacy media library: ' + p.name)
    return found


def source_identity(git_executable='git'):
    revision = subprocess.check_output([git_executable, 'rev-parse', 'HEAD'], cwd=ROOT,
                                       text=True, timeout=15).strip()
    dirty = bool(subprocess.check_output([git_executable, 'status', '--porcelain'], cwd=ROOT,
                                        text=True, timeout=15).strip())
    return revision, dirty


def write_evidence(payload, output, git_executable='git'):
    payload, output = Path(payload), Path(output)
    output.mkdir(parents=True, exist_ok=True)
    media = verify_media(payload)
    locked = {}
    for line in (ROOT / 'requirements-windows.lock').read_text().splitlines():
        if not line or line.startswith('#'):
            continue
        name, version = line.split(' --hash=', 1)[0].split('==')
        actual = importlib.metadata.version(name)
        if actual != version:
            raise ValueError(f'Build dependency drift: {name} expected {version}, installed {actual}')
        locked[name] = version
    components = [{'type': 'library', 'name': name, 'version': version,
                   'purl': f'pkg:pypi/{name}@{version}',
                   'properties': [{'name': 'wwrecorder:scope', 'value': 'build-environment; not necessarily shipped'}]}
                  for name, version in sorted(locked.items())]
    components.append({'type': 'application', 'name': 'CPython', 'version': platform.python_version()})
    for name, digest in media.items():
        components.append({'type': 'library', 'name': name,
                           'hashes': [{'alg': 'SHA-256', 'content': digest}]})
    # Inventory every payload file, including native dependencies not represented
    # by Python package metadata. Do not mistake an unknown native version for clearance.
    inventory = [{'path': p.relative_to(payload).as_posix(), 'sha256': sha256(p), 'bytes': p.stat().st_size}
                 for p in sorted(payload.rglob('*')) if p.is_file()]
    import pefile
    native_versions = []
    for item in inventory:
        path = payload / item['path']
        if path.suffix.lower() not in ('.dll', '.exe', '.pyd'):
            continue
        version = None
        try:
            with pefile.PE(str(path), fast_load=False) as pe:
                info = getattr(pe, 'VS_FIXEDFILEINFO', [])
                if info:
                    value = info[0]
                    version = '.'.join(map(str, (value.FileVersionMS >> 16, value.FileVersionMS & 65535,
                                                value.FileVersionLS >> 16, value.FileVersionLS & 65535)))
        except pefile.PEFormatError:
            pass
        native_versions.append({'path': item['path'], 'file_version': version, 'sha256': item['sha256']})
        components.append({'type': 'file', 'name': item['path'],
                           **({'version': version} if version else {}),
                           'hashes': [{'alg': 'SHA-256', 'content': item['sha256']}]})
    revision, dirty = source_identity(git_executable)
    sbom = {'bomFormat': 'CycloneDX', 'specVersion': '1.6', 'version': 1,
            'components': components}
    (output / 'components.cdx.json').write_text(json.dumps(sbom, indent=2))
    (output / 'payload-inventory.json').write_text(json.dumps(inventory, indent=2))
    (output / 'native-components.json').write_text(json.dumps(native_versions, indent=2))
    (output / 'media-security.json').write_text((ROOT / 'packaging/shared/media-security.json').read_text())
    encoder = next(p for p in payload.rglob('ffmpeg.exe') if p.is_file())
    for option, name in (('-version', 'ffmpeg-version.txt'), ('-buildconf', 'ffmpeg-buildconf.txt')):
        probe = subprocess.run([str(encoder), option], capture_output=True, text=True, timeout=15)
        if probe.returncode:
            raise ValueError('Approved encoder failed its native provenance probe')
        (output / name).write_text(probe.stdout + probe.stderr)
    evidence = {'source_revision': revision, 'source_dirty': dirty,
                'python': platform.python_version(), 'media': media,
                'lock_sha256': sha256(ROOT / 'requirements-windows.lock'),
                'inventory_sha256': sha256(output / 'payload-inventory.json'),
                'sbom_sha256': sha256(output / 'components.cdx.json'),
                'signature': 'unsigned build evidence; production MSIX trust is provided by Microsoft Store',
                'native_version_review': 'See media-security.json and native component register; hashes alone are not SCA clearance'}
    (output / 'build-provenance.json').write_text(json.dumps(evidence, indent=2))
    return evidence


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('payload')
    parser.add_argument('--output')
    parser.add_argument('--git-executable', default='git')
    args = parser.parse_args()
    print(json.dumps(write_evidence(args.payload, args.output, args.git_executable) if args.output else verify_media(args.payload)))
