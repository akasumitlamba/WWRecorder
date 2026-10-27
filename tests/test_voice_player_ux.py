"""Voice-first mixing and player/footer regressions, including real FFmpeg/Qt media."""
import os
import subprocess
import sys
import wave
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

import numpy as np
import pytest
from PyQt6.QtCore import QCoreApplication, QEvent, QPointF, Qt, QThread, QThreadPool, pyqtSlot
from PyQt6.QtGui import QFocusEvent, QMouseEvent, QShortcut
from PyQt6.QtMultimedia import QMediaPlayer
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

import dock_widget
import recorder
from dock_widget import RecentFilesSidebar, SettingsSidebar, _CreditRatingLink, _FileScanTask
from video_editor import VideoPlayerWindow


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


def wait_for(predicate, timeout=5000):
    for _ in range(timeout // 20):
        if predicate():
            return
        QTest.qWait(20)
    assert predicate(), "Timed out waiting for media/UI state"


@pytest.mark.parametrize("prefix,suffix", [("Recording", ".mkv"), ("Screenshot", ".png"), ("Frame", ".png")])
def test_capture_names_are_readable_and_collisions_preserve_files(tmp_path, monkeypatch, prefix, suffix):
    monkeypatch.setattr(recorder, "datetime", SimpleNamespace(now=lambda: datetime(2026, 8, 26, 12, 34, 56, 123456)))
    for number in range(1, 4):
        path = Path(recorder._unique_media_path(str(tmp_path), prefix, suffix))
        count = "" if number == 1 else f"_{number}"
        assert path.name == f"{prefix}_2026-08-26_12-34-56{count}{suffix}"
        assert not path.exists()
        path.write_bytes(bytes([number]))
    assert [p.read_bytes() for p in sorted(tmp_path.iterdir())] == [b"\x01", b"\x02", b"\x03"]


@pytest.mark.parametrize("mode,width", [("Default", 380), ("Large", 480)])
def test_footer_cycles_in_one_slot_and_pauses_during_interaction(app, monkeypatch, mode, width):
    sidebar = SettingsSidebar({"font_size": mode, "close_on_focus_loss": False})
    sidebar.resize(width, 760)
    sidebar.show()
    app.processEvents()
    link = sidebar._credit_link
    link.clearFocus()
    monkeypatch.setattr(link, "underMouse", lambda: False)
    monkeypatch.setattr(link, "hasFocus", lambda: False)
    opened = []
    monkeypatch.setattr(dock_widget.webbrowser, "open", opened.append)
    geometry = link.geometry()
    assert link._cycle_timer.isActive()
    assert link.text() == "Made by akasumitlamba"
    link.click()
    link._advance()
    QTest.qWait(450)
    assert link.text() == "Rate us ★★★★★"
    assert link.accessibleName() == link.text()
    link.click()
    assert opened == [entry[1] for entry in _CreditRatingLink.LINKS]
    assert link.geometry() == geometry
    assert link.fontMetrics().horizontalAdvance(link.text()) < link.width()
    monkeypatch.setattr(link, "underMouse", lambda: True)
    link._advance()
    QTest.qWait(450)
    assert link.text() == "Rate us ★★★★★"
    monkeypatch.setattr(link, "underMouse", lambda: False)
    monkeypatch.setattr(link, "hasFocus", lambda: True)
    link._advance()
    QTest.qWait(450)
    assert link.text() == "Rate us ★★★★★"
    monkeypatch.setattr(link, "hasFocus", lambda: False)
    link._advance()
    QTest.qWait(450)
    assert link.text() == "Made by akasumitlamba"
    sidebar.hide()
    assert not link._cycle_timer.isActive()
    assert link._opacity.opacity() == 1.0
    sidebar.close()
    sidebar.deleteLater()


@pytest.mark.parametrize("mode,width,height", [
    ("Default", 380, 600), ("Default", 380, 900),
    ("Large", 480, 600), ("Large", 480, 900),
])
def test_settings_footer_has_no_stacked_blank_space(app, mode, width, height):
    sidebar = SettingsSidebar({"font_size": mode, "close_on_focus_loss": False})
    sidebar.resize(width, height)
    sidebar.show()
    app.processEvents()
    credit, quit_button = sidebar._credit_link, sidebar._btn_quit
    assert credit.height() == 22
    assert credit.y() - (quit_button.y() + quit_button.height()) == 4
    assert credit.parentWidget() is sidebar  # Footer is pinned outside scrolling content.
    assert sidebar.height() - credit.geometry().bottom() - 1 == sidebar.layout().contentsMargins().bottom()
    assert sidebar.layout().contentsMargins().bottom() == 6
    assert credit.fontMetrics().height() <= credit.height()
    sidebar.close()
    sidebar.deleteLater()


@pytest.mark.parametrize("state,preview,expected", [
    (QMediaPlayer.PlaybackState.StoppedState, False, ["pause", 500]),
    (QMediaPlayer.PlaybackState.PausedState, False, [500]),
    (QMediaPlayer.PlaybackState.PlayingState, False, [500]),
    (QMediaPlayer.PlaybackState.PlayingState, True, ["pause", 500]),
])
def test_seek_uses_paused_decoder_after_stop_without_starting_playback(state, preview, expected):
    calls = []
    player = SimpleNamespace(duration=lambda: 2400, isSeekable=lambda: True,
                             playbackState=lambda: state, pause=lambda: calls.append("pause"),
                             setPosition=calls.append)
    VideoPlayerWindow._seek_to_position(SimpleNamespace(_player=player), 500, preview=preview)
    assert calls == expected


@pytest.mark.parametrize("duration,seekable,target,expected", [
    (0, True, 500, []), (2400, False, 500, []),
    (2400, True, -100, [0]), (2400, True, 3000, [2399]),
])
def test_seeking_clamps_to_valid_frames_and_ignores_unready_media(duration, seekable, target, expected):
    calls = []
    player = SimpleNamespace(duration=lambda: duration, isSeekable=lambda: seekable,
                             playbackState=lambda: QMediaPlayer.PlaybackState.PausedState,
                             setPosition=calls.append)
    VideoPlayerWindow._seek_to_position(SimpleNamespace(_player=player), target)
    assert calls == expected


def test_file_scan_delivers_generation_on_gui_thread_and_ignores_deleted_receiver(app, tmp_path):
    received = []

    class ObservedSidebar(RecentFilesSidebar):
        @pyqtSlot(list, int)
        def _on_files_scanned(self, files, generation=None):
            received.append((generation, QThread.currentThread() == app.thread()))
            super()._on_files_scanned(files, generation)

    sidebar = ObservedSidebar(str(tmp_path))
    assert QThreadPool.globalInstance().waitForDone(5000)
    app.processEvents()
    assert received == [(1, True)]
    # Old scans must not rebuild a newer list.
    sidebar._scan_generation = 2
    sidebar._on_files_scanned([(str(tmp_path / "stale.png"), 0)], 1)
    assert sidebar._file_layout.count() == 1
    # A queued worker result must be harmless after its QWidget is destroyed.
    task = _FileScanTask(str(tmp_path), generation=3)
    task.signals.finished.connect(sidebar._on_files_scanned)
    sidebar.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QThreadPool.globalInstance().start(task)
    assert QThreadPool.globalInstance().waitForDone(5000)
    app.processEvents()
    assert [generation for generation, _ in received] == [1, 1]


@pytest.fixture(scope="module", params=["mkv", "mp4"])
def color_video(tmp_path_factory, request):
    path = tmp_path_factory.mktemp("seek-media") / f"colors.{request.param}"
    command = [recorder.get_ffmpeg_path(), "-v", "error", "-y"]
    for color in ("red", "lime", "blue"):
        command += ["-f", "lavfi", "-i", f"color={color}:s=320x180:r=25:d=0.8"]
    command += ["-filter_complex", "[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]",
                "-map", "[v]", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)]
    subprocess.run(command, check=True, capture_output=True, timeout=20,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return path


@pytest.fixture
def player_window(app, color_video, monkeypatch):
    monkeypatch.setattr(VideoPlayerWindow, "_extract_thumbnails", lambda self: None)
    window = VideoPlayerWindow(str(color_video), str(color_video.parent))
    window.show()
    QTest.qWait(400)  # let the normal initial autoplay callback run
    wait_for(lambda: window._player.isSeekable())
    yield window
    window._exit_fullscreen()
    window._player.pause()
    window._close_ready = True
    window.close()
    window.deleteLater()
    app.processEvents()


def test_real_decoder_shows_correct_frames_after_end_and_repeated_seeks(player_window):
    window = player_window
    player = window._player
    sink = window._video_view.video_item.videoSink()
    wait_for(lambda: player.mediaStatus() == QMediaPlayer.MediaStatus.EndOfMedia)
    assert player.playbackState() == QMediaPlayer.PlaybackState.StoppedState
    # Exercise both playback slider and editor timeline entry points after EOF.
    for index, (position, channel) in enumerate(((1200, 1), (0, 0), (2000, 2), (500, 0))):
        if index % 2:
            window._on_timeline_seek(position)
        else:
            window._on_seekbar_pressed()
            window._seekbar.setValue(position)
            window._on_seekbar_moved(position)
            window._on_seekbar_released()
        wait_for(lambda: sink.videoFrame().isValid() and
                 abs(sink.videoFrame().startTime() / 1000 - position) <= 60)
        color = sink.videoFrame().toImage().pixelColor(160, 90)
        assert (color.red(), color.green(), color.blue())[channel] > 200
        assert player.playbackState() == QMediaPlayer.PlaybackState.PausedState
    for position in (1600, 0, 800, 2000, 1200):
        window._on_timeline_preview(position)
    wait_for(lambda: abs(sink.videoFrame().startTime() / 1000 - 1200) <= 60)
    player.play()
    window._seek_to_position(400)
    assert player.playbackState() == QMediaPlayer.PlaybackState.PlayingState


def test_fullscreen_top_edge_controls_and_keyboard_escape(player_window, app, monkeypatch):
    window = player_window
    window._toggle_fullscreen()
    app.processEvents()
    assert window.isFullScreen()
    assert not window._top_bar.isVisible()
    viewport = window._video_view.viewport()
    position = viewport.mapFrom(window, window.rect().topLeft())
    event = QMouseEvent(QEvent.Type.MouseMove, QPointF(position),
                        QPointF(viewport.mapToGlobal(position)), Qt.MouseButton.NoButton,
                        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(viewport, event)
    assert window._top_bar.isVisible()
    assert [b.text() for b in (window._btn_exit_fullscreen, window._btn_minimize,
                               window._btn_close_player)] == ["Exit fullscreen", "Minimize", "Close player"]
    assert len([s for s in window.findChildren(QShortcut) if s.key().toString() == "Esc"]) == 1
    for bar in (window._top_bar, window._controls_widget):
        monkeypatch.setattr(bar, "underMouse", lambda: False)
    window._btn_exit_fullscreen.setFocus(Qt.FocusReason.TabFocusReason)
    app.processEvents()
    window._hide_fullscreen_controls()
    assert window._top_bar.isVisible()
    QApplication.sendEvent(window._btn_exit_fullscreen, QFocusEvent(QEvent.Type.FocusIn, Qt.FocusReason.MouseFocusReason))
    window._hide_fullscreen_controls()
    assert not window._top_bar.isVisible()
    window._show_fullscreen_controls(reveal_top=True)
    window._btn_exit_fullscreen.click()
    assert not window.isFullScreen()
    window._toggle_fullscreen()
    window._btn_minimize.click()
    assert window.isMinimized() and not window.isFullScreen()
    window.showNormal()
    window._toggle_fullscreen()
    window.activateWindow()
    QTest.keyClick(window, Qt.Key.Key_Escape)
    app.processEvents()
    assert not window.isFullScreen()
    window._close_ready = True
    window._btn_close_player.click()
    assert not window.isVisible()


def render_audio(tmp_path, system=None, mic=None):
    command = [recorder.get_ffmpeg_path(), "-v", "error", "-f", "lavfi", "-i", "color=s=16x16:d=1"]
    for name, samples in (("sys", system), ("mic", mic)):
        if samples is None:
            continue
        path = tmp_path / f"{name}.wav"
        with wave.open(str(path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(48000)
            wav.writeframes((samples * 32767).astype("<i2").tobytes())
        command += ["-i", str(path)]
    command += ["-filter_complex", recorder._audio_filter_graph(system is not None, mic is not None),
                "-map", "[a]", "-t", "1", "-f", "f32le", "pipe:1"]
    result = subprocess.run(command, check=True, capture_output=True, timeout=15,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return np.frombuffer(result.stdout, dtype="<f4")


def test_real_audio_preserves_quiet_speech_and_silent_system_does_not_duck_it(tmp_path):
    time = np.arange(48000) / 48000
    voice = 0.005 * np.sin(2 * np.pi * 220 * time)
    voice[:2400] = 0
    voice[38400:] = 0
    mic = render_audio(tmp_path, mic=voice)
    mixed = render_audio(tmp_path, system=np.zeros(48000), mic=voice)
    assert len(mic) == len(mixed) == 48000
    np.testing.assert_allclose(mic, mixed, atol=1e-6)
    rms = lambda x: np.sqrt(np.mean(x[4800:36000] ** 2))
    assert 2.3 < rms(mic) / rms(voice) < 2.7
    first_audible = np.flatnonzero(np.abs(mic) > 0.001)[0]
    assert abs(first_audible - 2400) < 480  # no added 4–5-second delay or swallowed onset


def test_real_audio_keeps_system_at_unity_and_limits_loud_simultaneous_sources(tmp_path):
    time = np.arange(48000) / 48000
    system = 0.1 * np.sin(2 * np.pi * 440 * time)
    output = render_audio(tmp_path, system=system)
    np.testing.assert_allclose(output[1000:-1000], system[1000:-1000], atol=0.0001)
    loud = render_audio(tmp_path, system=0.8 * np.sin(2 * np.pi * 220 * time),
                        mic=0.8 * np.sin(2 * np.pi * 220 * time))
    assert np.isfinite(loud).all()
    assert 0.7 < np.max(np.abs(loud)) <= 0.951


def test_real_mux_keeps_three_second_video_system_and_mic_timelines_aligned(tmp_path):
    ffmpeg = recorder.get_ffmpeg_path()
    temp_video = tmp_path / 'raw_video.mkv'
    system_wav = tmp_path / 'system.wav'
    mic_wav = tmp_path / 'mic.wav'
    output = tmp_path / 'final.mkv'
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    subprocess.run([
        ffmpeg, '-y', '-v', 'error', '-f', 'lavfi',
        '-i', 'testsrc2=s=160x90:r=30:d=3', '-frames:v', '90',
        '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p', str(temp_video),
    ], check=True, timeout=30, creationflags=flags)

    sample_rate = 48_000
    seconds = np.arange(sample_rate * 3) / sample_rate
    system = np.zeros(sample_rate * 3)
    mic = np.zeros(sample_rate * 3)
    system_start = int(0.25 * sample_rate)
    mic_start = int(0.50 * sample_rate)
    system[system_start:] = 0.08 * np.sin(2 * np.pi * 600 * seconds[:len(system) - system_start])
    mic[mic_start:] = 0.02 * np.sin(2 * np.pi * 200 * seconds[:len(mic) - mic_start])
    for path, samples in ((system_wav, system), (mic_wav, mic)):
        with wave.open(str(path), 'wb') as wav:
            wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(sample_rate)
            wav.writeframes((samples * 32767).astype('<i2').tobytes())

    engine = recorder.RecordingEngine()
    engine._temp_vid_path = str(temp_video)
    engine._sys_wav_path = str(system_wav)
    engine._mic_wav_path = str(mic_wav)
    engine._output_path = str(output)
    engine._capture_clock_start = 10.0
    engine._capture_stopped_at = 13.0
    engine._pause_intervals = []
    engine._captured_frames = 90
    engine._finalizing = True
    assert engine.mux_and_save() == str(output)
    assert output.stat().st_size > 10_000

    video = subprocess.run([
        ffmpeg, '-v', 'error', '-i', str(output), '-map', '0:v:0',
        '-f', 'rawvideo', '-pix_fmt', 'rgb24', 'pipe:1',
    ], check=True, capture_output=True, timeout=30, creationflags=flags).stdout
    assert len(video) // (160 * 90 * 3) == 90
    audio = subprocess.run([
        ffmpeg, '-v', 'error', '-i', str(output), '-map', '0:a:0',
        '-ac', '1', '-ar', str(sample_rate), '-f', 'f32le', 'pipe:1',
    ], check=True, capture_output=True, timeout=30, creationflags=flags).stdout
    decoded = np.frombuffer(audio, dtype='<f4')
    assert abs(len(decoded) - sample_rate * 3) <= 960

    block = 960  # 20 ms: exact FFT bins for 200 Hz and 600 Hz.
    frames = decoded[:len(decoded) // block * block].reshape(-1, block)
    spectrum = np.abs(np.fft.rfft(frames, axis=1))
    freqs = np.fft.rfftfreq(block, 1 / sample_rate)
    energy_200 = spectrum[:, np.argmin(np.abs(freqs - 200))]
    energy_600 = spectrum[:, np.argmin(np.abs(freqs - 600))]
    onset_200 = np.flatnonzero(energy_200 > energy_200.max() * 0.25)[0] * 0.02
    onset_600 = np.flatnonzero(energy_600 > energy_600.max() * 0.25)[0] * 0.02
    assert abs(onset_200 - 0.50) <= 0.04
    assert abs(onset_600 - 0.25) <= 0.04
    steady_ratio = np.median(energy_200[40:120]) / np.median(energy_600[40:120])
    assert 0.35 < steady_ratio < 0.85
