"""Verify source/build resource paths after workspace relocation."""
import json
from pathlib import Path
import runpy
import subprocess
import sys
from types import ModuleType, SimpleNamespace
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]


def test_shared_spec_resolves_sources_and_resources_from_another_directory(monkeypatch, tmp_path):
    hooks = ModuleType('PyInstaller.utils.hooks')
    hooks.collect_data_files = lambda name: []
    hooks.collect_dynamic_libs = lambda name: []
    monkeypatch.setitem(sys.modules, 'PyInstaller.utils.hooks', hooks)
    monkeypatch.chdir(tmp_path)
    analyses = []

    def analysis(sources, **options):
        analyses.append((sources, options))
        return SimpleNamespace(binaries=[], pure=[], zipped_data=[], scripts=[], zipfiles=[], datas=[])

    executable_options = []

    def executable(*args, **options):
        executable_options.append(options)
        return object()

    spec = ROOT / 'packaging/shared/wwrecorder.spec'
    runpy.run_path(str(spec), init_globals={
        'SPECPATH': str(spec.parent), 'Analysis': analysis,
        'PYZ': lambda *args, **kwargs: object(), 'EXE': executable,
        'COLLECT': lambda *args, **kwargs: object(),
    })
    sources, options = analyses[0]
    assert sources == [str(ROOT / 'app/main.py')]
    assert options['pathex'] == [str(ROOT / 'app')]
    assert {'pynput.mouse', 'pynput.mouse._win32'} <= set(options['hiddenimports'])
    assert any(Path(source).name == '*.svg' for source, _ in options['datas'])
    assert any(Path(source).name == '*.txt' for source, _ in options['datas'])
    assert options['binaries'] == [(str(ROOT / 'app/ffmpeg.exe'), '.')]
    for source, destination in options['datas']:
        assert list(Path(source).parent.glob(Path(source).name)), source
    assert [(Path(source).name, destination) for source, destination in options['datas']][:3] == [
        ('icon.ico', '.'), ('icon.ico', 'assets'), ('icon.ico', 'icons'),
    ]
    assert Path(executable_options[0]['icon']).is_file()
    assert Path(executable_options[0]['version']).is_file()


def test_msix_stage_uses_shared_icon_and_retains_payload(tmp_path):
    payload = tmp_path / 'payload'
    payload.mkdir()
    executable = payload / 'WWRecorder.exe'
    executable.write_bytes(b'packaging-path-test')
    stage = tmp_path / 'stage'
    result = subprocess.run([
        sys.executable, str(ROOT / 'packaging/msix/stage_msix.py'),
        '--payload', str(payload), '--stage', str(stage),
        '--identity', str(ROOT / 'packaging/msix/test-identity.json'),
        '--version', '1.7.0.99',
    ], cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert (stage / 'WWRecorder.exe').read_bytes() == executable.read_bytes()
    identity = json.loads((stage / 'distribution.json').read_text())
    assert identity['channel'] == 'local-test'
    manifest = ET.parse(stage / 'AppxManifest.xml')
    namespace = {'m': 'http://schemas.microsoft.com/appx/manifest/foundation/windows10'}
    assert manifest.find('m:Identity', namespace).attrib['Version'] == '1.7.0.99'
    assert all((stage / 'Assets' / f'{name}.png').is_file() for name in (
        'StoreLogo', 'Square44x44Logo', 'Square150x150Logo',
    ))
    from PIL import Image
    for size in (16,24,32,48,64,96,256):
        for suffix in ('', '_altform-unplated', '_altform-lightunplated'):
            image = Image.open(stage / 'Assets' / f'Square44x44Logo.targetsize-{size}{suffix}.png').convert('RGBA')
            assert image.size == (size,size)
            assert image.getpixel((0,0)) == (0,0,0,0)



def test_unplated_assets_have_transparent_edges_and_real_sizes(tmp_path):
    import importlib.util
    from PIL import Image
    path = ROOT / 'packaging/shared/build_icon_assets.py'
    spec = importlib.util.spec_from_file_location('icon_builder', path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    source = Image.open(ROOT / 'packaging/shared/icon-source.png')
    for size in module.TARGET_SIZES:
        image = module.render_icon(source, size)
        assert image.size == (size,size)
        assert image.getpixel((0,0)) == (0,0,0,0)
        assert image.getpixel((size-1,size-1)) == (0,0,0,0)
    # PNG compression can differ across zlib/Pillow builds. Check deterministic
    # encoding within one runtime and decoded artwork across build hosts.
    import hashlib
    from PIL import ImageChops, ImageStat
    icon = tmp_path / 'icon.ico'; module.write_ico(source, icon)
    second = tmp_path / 'second.ico'; module.write_ico(source, second)
    assert hashlib.sha256(icon.read_bytes()).digest() == hashlib.sha256(second.read_bytes()).digest()
    deployed = Image.open(ROOT / 'app/icon.ico')
    for size in module.ICON_SIZES:
        actual = deployed.ico.getimage((size,size)).convert('RGBA')
        expected = module.render_icon(source, size)
        assert max(ImageStat.Stat(ImageChops.difference(actual, expected)).mean) < 1



import pytest

@pytest.mark.parametrize('names,accepted', [
    (['WWRecorder_1.7.0.10_x64.msix'], True),
    (['WWRecorder_1.7.0.10_x64_local-test.msix'], True),
    ([], False),
    (['first.msix','second.msix'], False),
])
def test_msix_install_helper_discovers_normal_names_and_rejects_ambiguity(tmp_path,names,accepted):
    import shutil
    shell = shutil.which('pwsh') or shutil.which('powershell.exe')
    if not shell:
        pytest.skip('Requires PowerShell; exercised on Windows CI')
    for name in names:
        (tmp_path/name).write_bytes(b'package-discovery-fixture')
    helper=(ROOT/'packaging/msix/Install-Test.ps1').read_text()
    start=helper.index('    $packages =')
    end=helper.index('    $signature =',start)
    discovery=helper[start:end]
    # Execute the real helper discovery block, without importing certificates
    # or deploying a package. Signature/manifest validation remains mandatory.
    script=tmp_path/'discovery.ps1'
    script.write_text("$ErrorActionPreference='Stop'\n"+discovery+"\nWrite-Output $packages[0].Name\n")
    result=subprocess.run([shell,'-NoProfile','-File',str(script)],capture_output=True,text=True,timeout=20)
    assert (result.returncode==0) is accepted, result.stderr
    if accepted:
        assert names[0] in result.stdout
    else:
        assert 'exactly one MSIX' in result.stderr
    assert '$signature.SignerCertificate.Thumbprint -ne $certificate.Thumbprint' in helper
    assert "$identity.Name -ne 'WWRecorder.LocalTest'" in helper
