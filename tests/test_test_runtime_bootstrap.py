"""Missing/existing/bad FFmpeg bootstrap paths preserve source tools and fail clearly."""
from pathlib import Path
import importlib.util
from types import SimpleNamespace
import pytest
ROOT=Path(__file__).resolve().parents[1]


def module():
    spec=importlib.util.spec_from_file_location('test_runtime_bootstrap', ROOT/'scripts/prepare_test_runtime.py')
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result);return result


def test_bootstrap_adds_missing_runtime_after_successful_probe(tmp_path,monkeypatch):
    runtime=module();source=tmp_path/'wheel-ffmpeg.exe';source.write_bytes(b'wheel runtime')
    monkeypatch.setattr(runtime.subprocess,'run',lambda *a,**kw:SimpleNamespace(returncode=0,stdout='ffmpeg version test'))
    result=runtime.prepare_ffmpeg(tmp_path,lambda:source)
    assert result.read_bytes()==source.read_bytes()
    assert not list(result.parent.glob('.ffmpeg-*'))


def test_bootstrap_never_replaces_existing_runtime(tmp_path,monkeypatch):
    runtime=module();target=tmp_path/'app/ffmpeg.exe';target.parent.mkdir();target.write_bytes(b'existing')
    monkeypatch.setattr(runtime.subprocess,'run',lambda *a,**kw:SimpleNamespace(returncode=0,stdout='ffmpeg version test'))
    assert runtime.prepare_ffmpeg(tmp_path,lambda:pytest.fail('Existing runtime replaced')) == target
    assert target.read_bytes()==b'existing'


def test_bootstrap_rejects_bad_runtime_and_cleans_partial_tool(tmp_path,monkeypatch):
    runtime=module();source=tmp_path/'bad.exe';source.write_bytes(b'bad')
    monkeypatch.setattr(runtime.subprocess,'run',lambda *a,**kw:SimpleNamespace(returncode=1,stdout='bad'))
    with pytest.raises(RuntimeError,match='version probe'):runtime.prepare_ffmpeg(tmp_path,lambda:source)
    assert not (tmp_path/'app/ffmpeg.exe').exists()
    assert not list((tmp_path/'app').glob('.ffmpeg-*'))
