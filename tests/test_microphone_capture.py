"""Portable checks; native endpoint listening is a separate Windows gate."""
from types import SimpleNamespace, ModuleType
import sys
import numpy as np
import pytest
from microphone_capture import native_microphone_recorder, microphone_stereo


@pytest.mark.parametrize('tag', [3, 0xFFFE])
def test_native_mix_format_is_preserved_and_resources_are_released(monkeypatch, tag):
    wave = SimpleNamespace(nSamplesPerSec=16000, nChannels=1, wBitsPerSample=32,
                           nBlockAlign=4, wFormatTag=tag)
    mix = SimpleNamespace(Format=wave)
    allocation = [[mix]]
    calls = []
    class VTable:
        def GetMixFormat(self, ptr, output):
            calls.append('format')
            return 0
        def Initialize(self, ptr, mode, flags, duration, periodicity, fmt, session):
            assert wave.nChannels == 1
            assert wave.nSamplesPerSec == 16000
            assert wave.nBlockAlign == 4
            assert flags == 0
            calls.append('initialize')
            return 0
    ptr = [[SimpleNamespace(lpVtbl=VTable())]]
    class Stream:
        def __enter__(self):
            raise RuntimeError('Endpoint Start failed')
    backend = SimpleNamespace(
        _ffi=SimpleNamespace(new=lambda kind: allocation, NULL=None,
            cast=lambda kind, value: value,
            buffer=lambda ptr, size: bytes(24) + bytes.fromhex('0300000000001000800000aa00389b71')),
        _com=SimpleNamespace(check_error=lambda result: None, release=lambda ptr: calls.append('release')),
        _ole32=SimpleNamespace(AUDCLNT_SHAREMODE_SHARED=0, CoTaskMemFree=lambda fmt: calls.append('free')),
        _Recorder=Stream)
    module = ModuleType('soundcard')
    module.mediafoundation = backend
    monkeypatch.setitem(sys.modules, 'soundcard', module)
    stream, rate = native_microphone_recorder(SimpleNamespace(_audio_client=lambda: ptr))
    assert rate == 16000 and stream.channelmap == [0]
    assert calls == ['format', 'initialize', 'free']
    with pytest.raises(RuntimeError, match='Endpoint Start failed'):
        stream.__enter__()
    assert calls[-1] == 'release'


@pytest.mark.parametrize('data,expected', [
    ([[.25], [-.5]], [[.25, .25], [-.5, -.5]]),
    ([[.25, 0], [-.5, 0]], [[.25, .25], [-.5, -.5]]),
    ([[0, .25], [0, -.5]], [[.25, .25], [-.5, -.5]]),
    ([[.25, .5], [-.5, -.25]], [[.25, .5], [-.5, -.25]]),
])
def test_mono_and_single_sided_voice_remain_audible(data, expected):
    np.testing.assert_array_equal(microphone_stereo(data), np.array(expected, dtype=np.float32))
