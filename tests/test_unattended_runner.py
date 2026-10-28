"""Run the actual report wrapper against controlled successful/failed/crashed children."""
import importlib.util
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[1]

@pytest.mark.parametrize('code,write_junit', [(0,True),(1,True),(7,False)])
def test_wrapper_always_reports_and_preserves_child_failure(tmp_path,monkeypatch,code,write_junit):
    spec=importlib.util.spec_from_file_location('runner_under_test',ROOT/'tests/windows_e2e/run_all.py')
    runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
    report=tmp_path/'report'
    monkeypatch.setattr(runner, '_test_modules', lambda root: [ROOT/'tests/test_app_icon.py'])
    class Child:
        stdout=iter(['controlled child output\n'])
        def __init__(self,command,**kwargs):
            assert str(ROOT/'tests/test_app_icon.py') in command
            assert kwargs['stdin'] == runner.subprocess.DEVNULL
            assert '--timeout=60' in command
            if write_junit:
                Path(next(arg.split('=',1)[1] for arg in command if arg.startswith('--junitxml='))).write_text('<testsuite tests="1"><testcase name="controlled">'+('<failure message="controlled failure"/>' if code else '')+'</testcase></testsuite>',encoding='utf-8')
        def wait(self):return code
    monkeypatch.setattr(runner.subprocess,'Popen',Child)
    original=Path.cwd()
    try:
        result=runner.main(['--report-dir',str(report)])
    finally:
        import os
        os.chdir(original)
    assert result == (0 if code == 0 else 1)
    assert all((report/name).is_file() for name in ('junit.xml','summary.md','summary.json','summary.html'))
    if not write_junit:
        assert 'pytest_process' in (report/'junit.xml').read_text(encoding='utf-8')


def test_windows_launcher_has_no_pause_or_interactive_dependency_install():
    batch=(ROOT/'RUN_TESTS.cmd').read_text(encoding='utf-8').lower()
    script=(ROOT/'tests/windows_e2e/run_all.ps1').read_text(encoding='utf-8').lower()
    assert '-installdeps' in batch and '-executionpolicy bypass' in batch
    assert 'pause' not in batch and 'read-host' not in script
    assert '--no-input' in script
