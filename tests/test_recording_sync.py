"""Decoded saved-file event alignment under uneven capture stalls, not just track duration."""
import shutil,subprocess,wave
from pathlib import Path
import numpy as np
import pytest
from tests.windows_e2e.helpers.env import import_app


def test_sample_clock_holds_old_screen_without_moving_next_event():
    clock=import_app('recorder')._VideoSampleClock()
    assert list(clock.append(b'dark',0))==[b'dark']
    assert list(clock.append(b'flash',1))==[b'dark']*29+[b'flash']
    assert list(clock.append(b'same-slot',1.001))==[]
    assert list(clock.append(b'dark',1.1))==[b'flash']*2+[b'dark']


def test_saved_system_and_microphone_events_match_screen_after_uneven_stalls(tmp_path,monkeypatch):
    recorder=import_app('recorder')
    ffmpeg=shutil.which('ffmpeg') or str(Path(__file__).resolve().parents[1]/'app/ffmpeg.exe')
    if not Path(ffmpeg).is_file():pytest.skip('Real encoder unavailable')
    def run(args):
        result=subprocess.run([ffmpeg,'-v','error','-y',*args],capture_output=True,timeout=60)
        assert result.returncode==0,result.stderr.decode(errors='replace')
        return result.stdout
    # Drive the real capture worker with a deterministic OS capture seam. The
    # actual stdin bytes, rather than a separately implemented frame generator,
    # are encoded and muxed below.
    from types import SimpleNamespace
    clock=SimpleNamespace(now=0.)
    frames=[];samples=[];engine=recorder.RecordingEngine()
    engine._running=True;engine._capture_clock_start=0;engine._pause_event.set()
    engine._region={'width':96,'height':64}
    engine._capture_segments=[{'src_top':0,'src_left':0,'src_width':96,'src_height':64,
        'dst_top':0,'dst_left':0,'dst_width':96,'dst_height':64}]
    engine._ffmpeg_proc=SimpleNamespace(stdin=SimpleNamespace(write=frames.append))
    class Capture:
        def __enter__(self):return self
        def __exit__(self,*args):return False
        def grab(self,region):
            if .2<=clock.now<.9:clock.now=.9
            if 1.7<=clock.now<2.45:clock.now=2.45
            if clock.now>=4-1e-6:engine._running=False
            flash=1.2-1e-6<=clock.now<1.4 or 2.8-1e-6<=clock.now<3
            raw=np.full((64,96,4),255 if flash else 0,np.uint8);raw[:,:,3]=255
            if engine._running:samples.append((clock.now,flash))
            return SimpleNamespace(raw=raw.tobytes())
    with monkeypatch.context() as capture_patch:
        capture_patch.setattr(recorder,'time',SimpleNamespace(perf_counter=lambda:clock.now,sleep=lambda value:setattr(clock,'now',clock.now+max(0,value))))
        capture_patch.setattr(recorder.mss,'mss',Capture)
        capture_patch.setattr(recorder,'_acquire_cursor_surface',lambda:(None,None,None,None,None))
        engine._frame_worker()
    assert len(frames)==120
    # The previous uniform-stretch scheme moves these exact visible transitions.
    first=next(i for i,(_,flash) in enumerate(samples) if flash)
    assert abs(first/len(samples)*4-1.2)>.2
    source=tmp_path/'frames.rgb';source.write_bytes(b''.join(frames))
    video=tmp_path/'capture.mkv'
    run(['-f','rawvideo','-pix_fmt','bgra','-s','96x64','-r','30','-i',str(source),'-c:v','libx264','-preset','ultrafast','-crf','18',str(video)])
    paths=[];rate=48000
    for label,start,frequency in [('sys',1.2,1000),('mic',2.8,700)]:
        audio=np.zeros(rate*4,np.float32);start_i=round(start*rate);count=round(.18*rate)
        audio[start_i:start_i+count]=.5*np.sin(2*np.pi*frequency*np.arange(count)/rate)
        path=tmp_path/(label+'.wav')
        with wave.open(str(path),'wb') as wav:
            wav.setnchannels(2);wav.setsampwidth(2);wav.setframerate(rate)
            wav.writeframes(np.repeat((audio*32767).astype('<i2')[:,None],2,axis=1).tobytes())
        paths.append(path)
    engine._finalizing=True
    engine._temp_vid_path=str(video);engine._sys_wav_path=str(paths[0]);engine._mic_wav_path=str(paths[1]);engine._output_path=str(tmp_path/'saved.mkv')
    engine._capture_clock_start=100;engine._capture_stopped_at=105.5
    engine._pause_intervals=[(0,1),(2.5,3)];engine._captured_frames=len(samples)
    monkeypatch.setattr(recorder,'get_ffmpeg_path',lambda:ffmpeg)
    saved=engine.mux_and_save();assert Path(saved).is_file()
    pixels=np.frombuffer(run(['-i',saved,'-an','-f','rawvideo','-pix_fmt','gray','pipe:1']),np.uint8).reshape(-1,64,96)
    visible=np.mean(pixels,axis=(1,2))>100
    visual_onsets=np.flatnonzero(visible & ~np.r_[False,visible[:-1]])/30
    audio=np.frombuffer(run(['-i',saved,'-vn','-ac','1','-ar',str(rate),'-f','f32le','pipe:1']),'<f4')
    energy=np.max(np.abs(audio[:len(audio)//480*480].reshape(-1,480)),axis=1)>.04
    sound_onsets=np.flatnonzero(energy & ~np.r_[False,energy[:-1]])*.01
    assert len(visual_onsets)==len(sound_onsets)==2,(visual_onsets,sound_onsets)
    assert np.max(np.abs(visual_onsets-sound_onsets))<.05,(visual_onsets,sound_onsets)
