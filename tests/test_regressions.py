import os
import subprocess
import sys
import time
import warnings
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

import pytest
import main as main_module
from PyQt6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt, QEvent, QThreadPool
from PyQt6.QtWidgets import QApplication, QWidget, QAbstractButton, QSizePolicy, QMessageBox

from annotation_tool import (
    AnnotationCanvas, AnnotationPill, _DrawingArea, _TextEditBar,
    _ThicknessButton, _arrow_head_size, _atomic_save_image, _clamp_popup_position,
    _fit_default_text_box, _text_editor_top_left,
)
from dock_widget import DockWidget, RecentFilesSidebar, SettingsSidebar, SidebarPanel, _CollapsibleAccordion, _FileRow
from main import (
    WWRecorderApp, HotkeyListener, _SavingPopup, _acquire_single_instance_mutex,
    _available_media_path, _is_safe_media_path, _normalized_capture_plan,
    _screen_for_anchor, validate_hotkey,
)
from PyQt6.QtGui import QCloseEvent, QImage, QMouseEvent, QPainter
from PyQt6.QtTest import QTest
from PyQt6.QtMultimedia import QMediaPlayer
import recorder
from recorder import (
    RecordingEngine, TEMP_PREFIX, TEMP_RETENTION_SECONDS,
    _audio_filter_graph, _next_frame_deadline, _read_audio_chunk,
    _video_timing_filter, _process_survived_startup, CURSOR_CANVAS_SIZE,
    _acquire_cursor_surface, _recording_temp_dir,
)
from ui_elements import PillWidget, SelectionOverlay, _clamp_window_top_left
from video_editor import (
    VideoPlayerWindow, NoScrollDoubleSpinBox, NoScrollSpinBox,
    _ExportWorker, _VideoGraphicsView, _delete_region_at_playhead,
    _text_overlay_range_at_playhead, _merge_delete_regions, _drawtext_filter,
    _available_output_path, _overlay_font_file,
)
from updater import UpdateChecker
from display_geometry import ScreenTransform, build_capture_plan, compose_frozen_desktop
from user_messages import friendly_error


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


def test_selection_emits_virtual_desktop_coordinates(app):
    overlay = SelectionOverlay(mode="record")
    overlay.setGeometry(-900, -120, 800, 600)
    overlay.rect_obj = QRect(25, 30, 200, 100)
    emitted = []
    overlay.selectionChanged.connect(emitted.append)

    overlay._emit_change()

    assert emitted == [{"top": -90, "left": -875, "width": 200, "height": 100}]
    overlay._cancel_emitted = True
    overlay.close()


def test_tiny_capture_plan_is_rejected_before_ffmpeg_and_valid_plan_is_even():
    assert _normalized_capture_plan({'width': 1, 'height': 100}) is None
    assert _normalized_capture_plan({'width': 100, 'height': 1}) is None
    normalized = _normalized_capture_plan({'left': -3, 'top': 2, 'width': 101, 'height': 99})
    assert normalized == {'left': -3, 'top': 2, 'width': 100, 'height': 98}


def test_notification_screen_uses_capture_anchor_including_negative_coordinates(monkeypatch):
    secondary = object()
    primary = object()
    class Screens:
        @staticmethod
        def screenAt(point):
            return secondary if point.x() < 0 else None
        @staticmethod
        def primaryScreen():
            return primary
    monkeypatch.setitem(_screen_for_anchor.__globals__, 'QApplication', Screens)
    assert _screen_for_anchor(QPoint(-700, 300)) is secondary
    assert _screen_for_anchor(QPoint(300, 300)) is primary


def test_cursor_surface_setup_failure_releases_desktop_dc(monkeypatch):
    released = []
    monkeypatch.setattr(recorder.win32gui, 'GetDC', lambda _hwnd: 73)
    monkeypatch.setattr(recorder.win32gui, 'ReleaseDC', lambda hwnd, dc: released.append((hwnd, dc)))
    monkeypatch.setattr(
        recorder, '_create_cursor_surface',
        lambda _dc: (_ for _ in ()).throw(RuntimeError('DIB failed')),
    )
    with pytest.raises(RuntimeError, match='DIB failed'):
        _acquire_cursor_surface()
    assert released == [(0, 73)]


def test_recording_work_files_use_selected_output_folder(tmp_path):
    work = _recording_temp_dir(str(tmp_path))
    assert work == tmp_path / '.wwr_temp'
    assert work.is_dir()


def test_new_annotation_text_can_be_cancelled(app):
    canvas = AnnotationCanvas()
    canvas._text_input_active = True
    canvas._editing_text_backup = None

    canvas._cancel_text()

    assert canvas._text_input_active is False
    canvas.close()


def test_new_image_annotation_text_can_be_cancelled(app, tmp_path):
    image_path = tmp_path / "source.png"
    image = QImage(64, 64, QImage.Format.Format_ARGB32)
    image.fill(0xFFFFFFFF)
    assert image.save(str(image_path))
    canvas = _DrawingArea(str(image_path))
    canvas._text_input_active = True
    canvas._editing_text_backup = None

    canvas._cancel_text()

    assert canvas._text_input_active is False
    canvas.close()


def test_dock_is_fully_initialized_before_first_show(app):
    class Engine:
        def is_recording(self):
            return False

    dock = DockWidget(Engine(), {"dock_edge": "right"})
    assert dock._panel is not None
    assert dock._topmost_timer.isActive()
    dock.close()


def test_failed_mux_keeps_recoverable_sources(tmp_path, monkeypatch):
    engine = RecordingEngine()
    video = tmp_path / "session.mkv"
    system_audio = tmp_path / "system.wav"
    mic_audio = tmp_path / "mic.wav"
    output = tmp_path / "output.mkv"
    for path in (video, system_audio, mic_audio):
        path.write_bytes(b"recoverable-media")
    engine._temp_vid_path = str(video)
    engine._sys_wav_path = str(system_audio)
    engine._mic_wav_path = str(mic_audio)
    engine._output_path = str(output)
    engine._finalizing = True

    def fail_mux(*args, **kwargs):
        raise subprocess.CalledProcessError(1, args[0])

    monkeypatch.setattr(subprocess, "run", fail_mux)

    with pytest.raises(RuntimeError):
        engine.mux_and_save()

    assert video.exists()
    assert system_audio.exists()
    assert mic_audio.exists()
    assert engine.is_busy() is False


def test_finalizing_engine_rejects_new_prepare(tmp_path):
    engine = RecordingEngine()
    engine._finalizing = True

    assert engine.prepare(
        {"top": 0, "left": 0, "width": 100, "height": 100}, str(tmp_path)
    ) is False


def test_startup_cleanup_keeps_recent_recovery_media(tmp_path, monkeypatch):
    recent = tmp_path / f"{TEMP_PREFIX}recent.mkv"
    stale = tmp_path / f"{TEMP_PREFIX}stale.mkv"
    recent.write_bytes(b"recent")
    stale.write_bytes(b"stale")
    old = time.time() - TEMP_RETENTION_SECONDS - 60
    os.utime(stale, (old, old))
    monkeypatch.setattr(recorder.tempfile, "gettempdir", lambda: str(tmp_path))
    engine = RecordingEngine()

    worker = engine.cleanup_temp_dir()
    worker.join(timeout=3)

    assert recent.exists()
    assert not stale.exists()


def test_recording_transition_reenables_live_controls(app):
    class Engine:
        def get_system_audio(self): return True
        def get_mic(self): return False
        def set_system_audio(self, _enabled): pass
        def set_mic(self, _enabled): pass
        def is_paused(self): return False

    pill = PillWidget(Engine(), {}, pre_record=True)
    app.processEvents()
    assert pill._topmost_timer.isActive()

    chosen_position = QPoint(260, 180)
    pill.move(chosen_position)
    pill._user_positioned = True
    pill.set_preparing(True)
    assert not pill._btn_discard.isEnabled()
    app.processEvents()

    pill.set_recording_mode()
    app.processEvents()

    assert pill.pos() == chosen_position

    for button in (pill._btn_discard, pill._btn_sys, pill._btn_mic,
                   pill._btn_mic_menu, pill._btn_annotate):
        assert button.isEnabled()
    pill._stopping = True
    pill.close()
    assert not pill._topmost_timer.isActive()


def test_resized_pill_clamps_only_when_user_position_would_be_offscreen():
    available = QRect(-1200, 0, 1200, 800)
    assert _clamp_window_top_left(QPoint(-1100, 100), QSize(400, 80), available) == QPoint(-1100, 100)
    assert _clamp_window_top_left(QPoint(-100, 760), QSize(400, 80), available) == QPoint(-400, 720)


def test_recording_and_dock_controls_keep_legible_icon_scale(app):
    class Engine:
        def get_system_audio(self): return True
        def get_mic(self): return True
        def set_system_audio(self, _enabled): pass
        def set_mic(self, _enabled): pass
        def is_paused(self): return False

    pill = PillWidget(Engine(), {}, pre_record=False)
    dock = DockWidget(Engine(), {"dock_edge": "right"})
    pill.show()
    app.processEvents()
    assert pill._btn_pause.iconSize().width() >= 22
    assert pill._btn_pause.width() >= 38
    assert pill._lbl_time.width() >= 68
    assert pill._status_badge.width() >= 95
    assert pill._status_badge.geometry().right() < pill._sep_timer.geometry().left()
    assert dock._btn_record.iconSize().width() >= 18
    assert dock._btn_record.width() >= 32
    pill._stopping = True
    pill.close()
    dock.close()


def test_annotation_snap_uses_nearest_edge_and_vertical_tie(app):
    pill = AnnotationPill()
    screen = QRect(0, 0, 1000, 1000)

    assert pill._nearest_edge(QPoint(100, 500), screen) == "left"
    assert pill._nearest_edge(QPoint(500, 100), screen) == "top"
    assert pill._nearest_edge(QPoint(100, 100), screen) == "left"
    pill.close()


def test_annotation_toolbar_fits_compact_laptop_available_area(app):
    pill = AnnotationPill()
    pill._screen_geometry = lambda point=None: QRect(0, 0, 600, 600)

    pill._apply_orientation("vertical")
    vertical = pill.sizeHint()
    pill._apply_orientation("horizontal")
    horizontal = pill.sizeHint()

    # 600 logical pixels leaves room for the Windows taskbar on compact,
    # scaled laptop displays while preserving the existing toolbar layouts.
    assert vertical.height() <= 600
    assert horizontal.width() <= 600
    assert pill._tool_btns["pencil"].width() == 24
    assert pill._tool_btns["pencil"].iconSize().width() == 17
    pill.close()


def test_annotation_toolbar_keeps_readable_icons_and_action_tooltips(app):
    pill = AnnotationPill()
    pill._screen_geometry = lambda point=None: QRect(0, 0, 1920, 1040)
    pill._apply_orientation("horizontal")

    assert pill._tool_btns["pencil"].iconSize().width() == 29
    assert not pill._tool_btns["laser"].icon().isNull()
    assert "transient" in pill._tool_btns["laser"].toolTip().lower()
    assert pill._btn_pin.width() == 40
    assert "Pause annotation" in pill._btn_pause.toolTip()
    assert pill._btn_clear.toolTip() == "Clear all annotations"
    assert "Undo" in pill._btn_undo.toolTip()
    assert "Redo" in pill._btn_redo.toolTip()
    # Empty-history actions remain hoverable so their explanatory tooltips work.
    assert pill._btn_undo.isEnabled()
    assert pill._btn_redo.isEnabled()

    for button in pill._pill.findChildren(QAbstractButton):
        assert button.toolTip().strip(), f"Missing tooltip: {button.objectName() or type(button).__name__}"

    pill._on_pause_toggled(True)
    assert "Resume annotation" in pill._btn_pause.toolTip()
    pill.close()


def test_annotation_toolbar_does_not_raise_above_active_popup(app):
    pill = AnnotationPill()
    pill.show()
    app.processEvents()
    raised = []
    pill._has_active_popup = lambda: True
    pill.raise_ = lambda: raised.append(True)

    pill._enforce_topmost()

    assert raised == []
    pill.close()


def test_recording_and_dock_controls_keep_legible_icon_scale(app):
    class Engine:
        def get_system_audio(self): return True
        def get_mic(self): return True
        def set_system_audio(self, _enabled): pass
        def set_mic(self, _enabled): pass
        def is_paused(self): return False

    pill = PillWidget(Engine(), {}, pre_record=False)
    dock = DockWidget(Engine(), {'dock_edge': 'right'})
    pill.show()
    app.processEvents()
    assert pill._btn_pause.iconSize().width() >= 22
    assert pill._btn_pause.width() >= 38
    assert pill._lbl_time.width() >= 68
    assert pill._status_badge.width() >= 95
    assert pill._status_badge.geometry().right() < pill._sep_timer.geometry().left()
    assert dock._btn_record.iconSize().width() >= 18
    assert dock._btn_record.width() >= 32
    pill._stopping = True
    pill.close()
    dock.close()


def test_expanded_dock_compacts_on_small_available_screens(app):
    class Engine:
        def get_system_audio(self): return True
        def get_mic(self): return True

    dock = DockWidget(Engine(), {'dock_edge': 'right'})
    dock._screen_geo = lambda: QRect(0, 0, 1366, 768)
    dock._set_expanded_geo(animate=False)
    assert dock.size().width() == DockWidget.COMPACT_EXPANDED_W
    assert dock.size().height() == DockWidget.COMPACT_EXPANDED_H
    assert all(button.width() == 36 for button in dock._dock_buttons)
    assert all(button.iconSize().width() == 20 for button in dock._dock_buttons)

    dock._screen_geo = lambda: QRect(0, 0, 1920, 1080)
    dock._set_expanded_geo(animate=False)
    assert dock.size().width() == DockWidget.EXPANDED_W
    assert dock.size().height() == DockWidget.EXPANDED_H
    assert all(button.width() == 40 for button in dock._dock_buttons)
    dock.close()


def test_screenshot_collapse_is_immediate_and_only_reports_a_real_change(app):
    class Engine:
        def get_system_audio(self): return True
        def get_mic(self): return True

    dock = DockWidget(Engine(), {'dock_edge': 'right'})
    dock._screen_geo = lambda: QRect(0, 0, 1920, 1080)
    dock._set_expanded_geo(animate=False)

    assert dock.collapse_for_screenshot()
    assert not dock._expanded
    assert not dock._panel.isVisible()
    assert dock.width() == DockWidget.GRABBER_W
    assert not dock.collapse_for_screenshot()
    dock.close()


def test_screenshot_request_waits_for_dock_repaint_only_when_collapsed(monkeypatch):
    class Engine:
        def is_busy(self): return False

    class Dock:
        def __init__(self, changed): self.changed = changed
        def collapse_for_screenshot(self): return self.changed

    scheduled = []
    monkeypatch.setattr(
        main_module, "QTimer",
        type("FakeTimer", (), {
            "singleShot": staticmethod(
                lambda delay, callback: scheduled.append((delay, callback))
            )
        }),
    )

    owner = object.__new__(WWRecorderApp)
    owner.engine = Engine()
    owner._recording_prepare_in_progress = False
    owner._screenshot_in_progress = False
    owner._overlay = None
    owner._is_hotkey_listening = lambda: False
    owner._dismiss_success_notification = lambda: None
    freezes = []
    owner._perform_screenshot_freeze = lambda: freezes.append(True)
    owner.dock = Dock(True)

    owner._on_screenshot_requested()
    assert freezes == []
    assert scheduled[0][0] == 100
    scheduled.pop()[1]()
    assert freezes == [True]

    owner._screenshot_in_progress = False
    owner.dock = Dock(False)
    owner._on_screenshot_requested()
    assert freezes == [True, True]
    assert scheduled == []


def test_sidebar_defaults_are_their_minimum_widths(app):
    normal = SidebarPanel(font_size_mode="Default")
    large = SidebarPanel(font_size_mode="Large")

    assert (normal.DEFAULT_WIDTH, normal.MIN_WIDTH) == (380, 380)
    assert (large.DEFAULT_WIDTH, large.MIN_WIDTH) == (480, 480)

    normal.close()
    large.close()


def test_settings_version_hides_patch_component(app):
    sidebar = SettingsSidebar({"current_version": "1.6.2"})

    assert sidebar._lbl_version.text() == "Version 1.6"

    sidebar.close()


def test_right_dock_and_sidebar_end_exactly_on_the_screen_edge(app):
    class Engine:
        def get_system_audio(self): return True
        def get_mic(self): return True

    screen = QRect(0, 0, 1366, 768)
    dock = DockWidget(Engine(), {'dock_edge': 'right'})
    dock._screen_geo = lambda: screen
    dock._dock_y = 200
    dock._set_collapsed_geo(animate=False)
    assert dock.geometry().right() == screen.right()
    dock._set_expanded_geo(animate=False)
    assert dock.geometry().right() == screen.right()
    dock.close()

    sidebar = SidebarPanel(edge='right')
    sidebar._position_sidebar(400)
    assert sidebar.geometry().right() == QApplication.primaryScreen().availableGeometry().right()
    sidebar.close()


def test_advanced_accordion_uses_bundled_up_and_down_arrow_assets(app):
    accordion = _CollapsibleAccordion('Advanced')
    assert not accordion.lbl_arrow.pixmap().isNull()
    down_key = accordion.lbl_arrow.pixmap().cacheKey()
    accordion.toggle()
    assert not accordion.lbl_arrow.pixmap().isNull()
    assert accordion.lbl_arrow.pixmap().cacheKey() != down_key
    accordion.close()


def test_annotation_toolbar_has_balanced_targets_tooltips_and_single_strip(app):
    pill = AnnotationPill()

    buttons = pill._pill.findChildren(QAbstractButton)
    assert buttons
    assert all(button.toolTip().strip() for button in buttons)
    assert all(button.width() >= 24 and button.height() >= 24 for button in buttons)
    assert all(button.width() in (27, 32) for button in pill._tool_btns.values())
    assert all(button.iconSize().width() in (20, 23) for button in pill._tool_btns.values())

    pill._apply_orientation('vertical')
    assert pill._pill_layout.direction().name == 'TopToBottom'
    pill._apply_orientation('horizontal')
    assert pill._pill_layout.direction().name == 'LeftToRight'
    assert pill._group_specs == []
    pill.close()


def test_mixed_dpi_plan_maps_negative_secondary_without_global_dpr_error():
    screens = [
        ScreenTransform('left125', -1536, 0, 1536, 864, -1920, 0, 1920, 1080),
        ScreenTransform('primary', 0, 0, 1920, 1080, 0, 0, 1920, 1080),
    ]
    plan = build_capture_plan({'left': -1400, 'top': 100, 'width': 400, 'height': 200}, screens)
    seg = plan['segments'][0]
    assert seg['src_left'] == -1750  # local offset 136 * 1.25 from native -1920
    assert seg['src_top'] == 125
    assert plan['width'] == 500 and plan['height'] == 250


def test_spanning_100_and_150_percent_composes_correct_pixels():
    from PIL import Image
    screens = [
        ScreenTransform('left', -100, 0, 100, 100, -100, 0, 100, 100),
        ScreenTransform('right', 0, 0, 100, 100, 0, 0, 150, 150),
    ]
    plan = build_capture_plan({'left': -50, 'top': 0, 'width': 100, 'height': 50}, screens)
    desktop = Image.new('RGB', (250, 150), 'red')
    desktop.paste(Image.new('RGB', (150, 150), 'blue'), (100, 0))
    result = compose_frozen_desktop(desktop, (-100, 0), plan)
    assert result.size == (150, 75)
    assert result.getpixel((10, 10)) == (255, 0, 0)
    assert result.getpixel((140, 10)) == (0, 0, 255)


@pytest.mark.parametrize('scale', [1.0, 1.25, 1.5])
def test_single_monitor_capture_plan_at_supported_scales(scale):
    logical_w, logical_h = 800, 600
    screen = ScreenTransform('display', -800, -200, logical_w, logical_h,
                             round(-800 * scale), round(-200 * scale),
                             round(logical_w * scale), round(logical_h * scale))
    plan = build_capture_plan({'left': -700, 'top': -100, 'width': 320, 'height': 180}, [screen])
    assert plan['width'] == round(320 * scale)
    assert plan['height'] == round(180 * scale)
    assert len(plan['segments']) == 1


def test_ffmpeg_startup_wait_detects_delayed_failure(monkeypatch):
    class Process:
        def __init__(self): self.calls = 0
        def poll(self):
            self.calls += 1
            return 1 if self.calls >= 4 else None
    monkeypatch.setattr(recorder.time, 'sleep', lambda _value: None)
    ticks = iter([0.0, 0.01, 0.02, 0.03, 0.31])
    monkeypatch.setattr(recorder.time, 'monotonic', lambda: next(ticks, 0.31))
    assert _process_survived_startup(Process()) is False


def test_engine_runtime_audio_errors_are_delivered_once():
    engine = RecordingEngine()
    engine._report_runtime_event('audio_error', 'Mic disconnected')
    assert engine.drain_runtime_events() == [('audio_error', 'Mic disconnected')]
    assert engine.drain_runtime_events() == []


def test_audio_disconnect_event_is_shown_to_user(monkeypatch):
    class Engine:
        def drain_runtime_events(self):
            return [('audio_error', 'Microphone failed — USB microphone. Recording continues without this microphone.')]
    class Tray:
        def __init__(self): self.messages = []
        def icon(self): return object()
        def showMessage(self, *args): self.messages.append(args)
    owner = object.__new__(WWRecorderApp)
    owner.engine = Engine(); owner.tray = Tray()
    WWRecorderApp._poll_engine_events(owner)
    assert len(owner.tray.messages) == 1
    assert owner.tray.messages[0][0] == 'Audio device disconnected'
    assert 'USB microphone' in owner.tray.messages[0][1]


def test_audio_reconnect_event_is_shown_to_user():
    class Engine:
        def drain_runtime_events(self):
            return [('audio_reconnected', 'Mic switched to the current Windows default device.')]
    class Tray:
        def __init__(self): self.messages = []
        def icon(self): return object()
        def showMessage(self, *args): self.messages.append(args)
    owner = object.__new__(WWRecorderApp)
    owner.engine = Engine(); owner.tray = Tray()
    WWRecorderApp._poll_engine_events(owner)
    assert owner.tray.messages[0][0] == 'Audio device changed'


def test_replacement_audio_endpoint_layout_is_normalized():
    mono = recorder.np.array([[0.25], [-0.5]], dtype=recorder.np.float32)
    stereo = RecordingEngine._normalize_audio_channels(mono, 2)
    assert stereo.shape == (2, 2)
    assert recorder.np.allclose(stereo[:, 0], stereo[:, 1])
    downmixed = RecordingEngine._normalize_audio_channels(stereo, 1)
    assert downmixed.shape == (2, 1)


def test_video_player_follows_windows_default_audio_output():
    class Audio:
        def __init__(self): self.device = None
        def isMuted(self): return True
        def volume(self): return 0.65
        def setDevice(self, device): self.device = device
        def setVolume(self, value): self.restored_volume = value
        def setMuted(self, value): self.restored_muted = value
    class Toast:
        def __init__(self): self.messages = []
        def show_message(self, *args): self.messages.append(args)
    class Device:
        def description(self): return 'USB Headphones'
    owner = VideoPlayerWindow.__new__(VideoPlayerWindow)
    owner._audio_output = Audio(); owner._toast = Toast()
    VideoPlayerWindow._on_default_audio_output_changed(owner, Device())
    assert owner._audio_output.device.description() == 'USB Headphones'
    assert owner._audio_output.restored_volume == 0.65
    assert owner._audio_output.restored_muted is True
    assert 'USB Headphones' in owner._toast.messages[0][0]


def test_accessibility_cursor_canvas_allows_very_large_pointer():
    assert CURSOR_CANVAS_SIZE >= 512


def test_click_created_text_box_stays_visible_at_bottom_right_edge():
    assert _fit_default_text_box(495, 295, 200, 40, 500, 300) == (300.0, 260.0, 200.0, 40.0)
    assert _fit_default_text_box(5, 5, 200, 40, 80, 30) == (0.0, 0.0, 80.0, 30.0)
    assert _text_editor_top_left(100, 80) == (90, 72)
    assert _text_editor_top_left(3, 2) == (-7, -6)  # Clip chrome, never move the text origin.


def test_automatic_save_and_notification_names_do_not_overwrite(tmp_path):
    existing = tmp_path / 'Recording.mkv'
    second = tmp_path / 'Recording_2.mkv'
    existing.write_bytes(b'original')
    second.write_bytes(b'second')
    expected = str(tmp_path / 'Recording_3.mkv')
    assert _available_media_path(str(existing)) == expected
    assert _available_output_path(str(existing)) == expected
    assert existing.read_bytes() == b'original'
    assert second.read_bytes() == b'second'


def test_clear_all_undo_restores_exact_z_order(app):
    canvas = AnnotationCanvas()
    original = [{'type': 'pencil', 'points': []}, {'type': 'rect', 'start': (0, 0), 'end': (2, 2)}]
    canvas._items = list(original)
    canvas.clear_all()
    assert canvas._items[0]['_action'] == 'clear'
    canvas.undo()
    assert canvas._items == original
    canvas.close()


def test_thickness_popup_is_clamped_on_all_edges():
    pos = _clamp_popup_position(QRect(590, 570, 30, 30), QSize(180, 200), QRect(0, 0, 600, 600))
    assert pos.x() == 420
    assert pos.y() == 365


def test_atomic_image_save_replaces_complete_file(app, tmp_path):
    path = tmp_path / 'image.png'
    path.write_bytes(b'old image remains until commit')
    image = QImage(32, 32, QImage.Format.Format_ARGB32)
    image.fill(0xFF00FF00)
    assert _atomic_save_image(image, str(path))
    loaded = QImage(str(path))
    assert not loaded.isNull() and loaded.pixelColor(0, 0).green() == 255


def test_merge_adjacent_and_overlapping_delete_regions():
    class R:
        def __init__(self, start, end): self.start_ms, self.end_ms = start, end
    assert _merge_delete_regions([R(2000, 4000), R(4000, 6000), R(5500, 7000)]) == [(2.0, 7.0)]


def test_one_millisecond_delete_gap_is_one_cut_but_larger_gap_is_preserved():
    class R:
        def __init__(self, start, end): self.start_ms, self.end_ms = start, end
    assert _merge_delete_regions([R(1000, 2000), R(2001, 3000)]) == [(1.0, 3.0)]
    assert _merge_delete_regions([R(1000, 2000), R(2002, 3000)]) == [(1.0, 2.0), (2.002, 3.0)]


def test_export_caption_scales_with_output_and_uses_font_style():
    class Overlay:
        x_percent = 50; y_percent = 50; font_size = 54; color = 'white'
        bold = True; italic = True; underline = False
    value = _drawtext_filter(Overlay(), 'C\\:/Temp/text.txt', 0, 2, 1080)
    assert "arialbi.ttf" in value
    assert "fontsize=h*0.05000000" in value


def test_export_worker_always_removes_caption_temp_files(tmp_path):
    temp = tmp_path / 'caption.txt'; temp.write_text('caption')
    worker = _ExportWorker(['missing-ffmpeg', str(tmp_path / 'out.mp4')], str(tmp_path / 'out.mp4'), [str(temp)])
    worker.run()
    assert not temp.exists()


def test_cancelled_export_worker_removes_partial_output(tmp_path):
    partial = tmp_path / 'cancelled.partial.mkv'
    partial.write_bytes(b'incomplete')
    worker = _ExportWorker(['missing-ffmpeg', str(partial)], str(partial))
    worker._is_stopped = True
    worker.run()
    assert not partial.exists()


def test_hotkey_state_reset_clears_stale_modifiers():
    class HK:
        def __init__(self): self._state = {'ctrl', 'shift'}
    listener = HotkeyListener('x', 'y'); a, b = HK(), HK(); listener._hotkeys = (a, b)
    listener.reset_state()
    assert a._state == set() and b._state == set()


def test_single_instance_mutex_uses_non_elevated_local_namespace():
    class Kernel:
        def __init__(self): self.name = None
        def CreateMutexW(self, _a, _b, name): self.name = name; return 7
        def GetLastError(self): return 183
    kernel = Kernel()
    assert _acquire_single_instance_mutex(kernel) == (7, True)
    assert kernel.name.startswith('Local\\')


def test_security_allows_only_existing_media(tmp_path):
    image = tmp_path / 'safe.png'; image.write_bytes(b'x')
    script = tmp_path / 'unsafe.cmd'; script.write_bytes(b'echo unsafe')
    assert _is_safe_media_path(str(image))
    assert not _is_safe_media_path(str(script))


def test_plain_language_errors_hide_windows_codes():
    err = PermissionError(13, '[WinError 32] sharing violation')
    message = friendly_error(err)
    assert 'WinError' not in message and 'Close any player' in message


def test_file_exists_error_has_specific_plain_language_message():
    message = friendly_error(FileExistsError(17, 'already exists'))
    assert 'already exists' in message and 'different name' in message


def test_recent_files_load_first_fifteen_then_defer(app, tmp_path):
    files = []
    for index in range(20):
        path = tmp_path / f'image_{index:02d}.png'
        image = QImage(8, 8, QImage.Format.Format_ARGB32); image.fill(0xFFFFFFFF)
        assert image.save(str(path)); files.append((str(path), float(1000 - index)))
    sidebar = RecentFilesSidebar(str(tmp_path))
    sidebar._on_files_scanned(files, sidebar._scan_generation)
    rows = [sidebar._file_layout.itemAt(i).widget() for i in range(sidebar._file_layout.count() - 1)]
    rows = [row for row in rows if isinstance(row, _FileRow)]
    assert len(rows) == 20
    assert all(row._loaded for row in rows[:15])
    assert all(not row._loaded for row in rows[15:])
    QThreadPool.globalInstance().waitForDone(5000)
    app.processEvents()
    sidebar.close()


def test_processing_popup_constructs_and_incomplete_file_is_not_playable(app, tmp_path):
    popup = _SavingPopup()
    popup.show_saving(QPoint(100, 100))
    app.processEvents()
    assert popup.isVisible()

    incomplete = tmp_path / "Recording_processing.mkv"
    incomplete.write_bytes(b"still being muxed")
    sidebar = RecentFilesSidebar(str(tmp_path))
    sidebar.set_processing_file(incomplete.name)
    sidebar._on_files_scanned(
        [(str(incomplete), incomplete.stat().st_mtime)], sidebar._scan_generation
    )
    rows = [
        sidebar._file_layout.itemAt(i).widget()
        for i in range(sidebar._file_layout.count() - 1)
    ]
    assert not any(isinstance(row, _FileRow) for row in rows)
    assert sidebar._processing_widget is not None

    popup.hide_saving()
    popup.close()
    sidebar.close()


def test_processing_file_lockout_survives_popup_failure(app, tmp_path, monkeypatch):
    expected = tmp_path / "Recording_in_progress.mkv"

    class Action:
        def setEnabled(self, _enabled): pass
        def setText(self, text): self.text = text

    class Tray:
        def setToolTip(self, _text): pass
        def showMessage(self, *_args): pass
        def icon(self): return None

    class Panel:
        def __init__(self): self.processing = None
        def isVisible(self): return True
        def set_processing_file(self, filename): self.processing = filename

    class Dock:
        def set_recording_state(self, _active): pass

    class BrokenPopup:
        def __init__(self): raise RuntimeError("popup construction failed")

    owner = object.__new__(WWRecorderApp)
    owner.border_widget = None
    owner._overlay = None
    owner._act_record = Action()
    owner._destroy_annotation_canvas = lambda: None
    owner.pill = None
    owner.dock = Dock()
    owner.tray = Tray()
    owner.engine = type("Engine", (), {"_output_path": str(expected)})()
    owner._recent_panel = Panel()
    owner._saving_popup = None
    owner._last_capture_anchor = QPoint(20, 20)
    owner._processing_filename = None
    monkeypatch.setattr("main._SavingPopup", BrokenPopup)

    WWRecorderApp._on_recording_stopped(owner, "<SAVING>")

    assert owner._processing_filename == expected.name
    assert owner._recent_panel.processing == expected.name
    assert owner._saving_popup is None


def test_settings_reset_restores_default_font_mode(app):
    config = {'font_size': 'Large', 'output_folder': '', 'hotkey': '<shift>+<backspace>',
              'hotkey_screenshot': '<shift>+<home>'}
    defaults = dict(config, font_size='Default')
    sidebar = SettingsSidebar(config, defaults)
    sidebar._reset()
    assert sidebar._seg_font.value() == 'Default'
    assert sidebar._btn_save.isEnabled()
    sidebar.close()


def test_rename_collision_keeps_inline_editor_and_text(app, tmp_path, monkeypatch):
    source = tmp_path / 'one.png'; source.write_bytes(b'one')
    target = tmp_path / 'taken.png'; target.write_bytes(b'taken')
    row = _FileRow(str(source), defer_load=True)
    warnings_seen = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: warnings_seen.append(args))
    row._start_rename()
    row._rename_edit.setText('taken')
    row._finish_rename()
    assert warnings_seen and row._is_renaming
    assert not row._rename_edit.isHidden() and row._rename_edit.text() == 'taken'
    assert source.read_bytes() == b'one' and target.read_bytes() == b'taken'
    row.close()


def test_editor_close_poll_has_hard_deadline(app, monkeypatch):
    class Timer:
        def __init__(self): self.stopped = False
        def stop(self): self.stopped = True
    class Overlay:
        def hide(self): pass
    class Fake:
        _close_deadline = 0.0; _closing = True; _close_ready = False
        _close_poll_timer = Timer(); _loading_overlay = Overlay()
        def _active_close_workers(self): return [object()]
        def setEnabled(self, _enabled): pass
    warnings = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: warnings.append(args))
    VideoPlayerWindow._poll_close_workers(Fake())
    assert Fake._close_poll_timer.stopped and warnings


def test_rename_source_restore_preserves_edit_lists(tmp_path):
    class Player:
        def setSource(self, value): self.source = value
        def pause(self): pass
    class Button:
        def setEnabled(self, _value): pass
    class Timeline(Button): pass
    class Fake:
        _player = Player(); _btn_play = Button(); _timeline = Timeline()
        _text_overlays = [object()]; _delete_regions = [object()]
        def setWindowTitle(self, _value): pass
        def _refresh_video_list(self): pass
    fake = Fake(); target = str(tmp_path / 'renamed.mkv')
    VideoPlayerWindow.restore_source_after_rename(fake, target)
    assert len(fake._text_overlays) == 1 and len(fake._delete_regions) == 1
    assert fake._filepath == target


def test_switching_video_with_unsaved_edits_requires_confirmation(tmp_path, monkeypatch):
    class Fake:
        _filepath = str(tmp_path / 'first.mkv')
        def _has_unsaved_edits(self): return True
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.No)
    assert VideoPlayerWindow._confirm_video_switch(Fake(), str(tmp_path / 'second.mkv')) is False
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
    assert VideoPlayerWindow._confirm_video_switch(Fake(), str(tmp_path / 'second.mkv')) is True


def test_media_error_disables_play_and_timeline():
    class Control:
        def setEnabled(self, value): self.enabled = value
    class Player:
        def errorString(self): return 'damaged'
    class Fake:
        _player = Player(); _btn_play = Control(); _timeline = Control()
    VideoPlayerWindow._on_media_error(Fake(), QMediaPlayer.Error.ResourceError, 'damaged')
    assert Fake._btn_play.enabled is False and Fake._timeline.enabled is False


def test_update_rate_limit_is_not_reported_as_latest(monkeypatch):
    import urllib.error
    checker = UpdateChecker('1.0')
    failures, finished = [], []
    checker.check_failed.connect(failures.append)
    checker.check_finished.connect(lambda *args: finished.append(args))
    monkeypatch.setattr('updater._make_ssl_context', lambda: None)
    def fail(*_args, **_kwargs):
        raise urllib.error.HTTPError('https://example.invalid', 403, 'rate', {}, None)
    monkeypatch.setattr('updater.urllib.request.urlopen', fail)
    checker.run()
    assert failures and 'rate-limited' in failures[0]
    assert finished == []


@pytest.mark.parametrize(('current', 'candidate', 'expected'), [
    ('1.7.0', '1.7.0-beta.1', False),
    ('1.6.3', '1.7.0-rc.1', False),
    ('1.7.0-beta.1', '1.7.0', True),
    ('1.6.3', '1.7.0', True),
    ('1.6.3', 'not-a-version', False),
])
def test_update_comparison_never_promotes_prereleases(current, candidate, expected):
    assert UpdateChecker(current)._is_newer(candidate) is expected


def test_caption_font_uses_windows_directory_environment(monkeypatch):
    class Overlay:
        bold = False
        italic = False
    monkeypatch.setenv('WINDIR', r'D:\Windows')
    assert _overlay_font_file(Overlay()) == 'D\\:/Windows/Fonts/arial.ttf'


def test_screenshot_editor_uses_a_compact_non_overlapping_thickness_control(app, tmp_path):
    image_path = tmp_path / "toolbar.png"
    image = QImage(320, 180, QImage.Format.Format_ARGB32)
    image.fill(0xFF202020)
    assert image.save(str(image_path))
    from annotation_tool import AnnotateWindow

    window = AnnotateWindow(str(image_path))
    window.show()
    app.processEvents()

    assert window.btn_thickness.width() == window.btn_thickness.height() == 34
    assert window.btn_thickness._compact is True
    assert window.btn_thickness._gauge_center_x() == 17.0
    window.close()


def test_annotation_toolbar_yields_topmost_to_open_popup(app):
    pill = AnnotationPill()
    raised = []
    pill._has_active_popup = lambda: True
    pill.raise_ = lambda: raised.append(True)

    pill._enforce_topmost()

    assert raised == []
    pill.close()


def test_delete_region_starts_at_exact_playhead():
    assert _delete_region_at_playhead(12_345, 30_000) == (12_345, 14_345)
    assert _delete_region_at_playhead(29_500, 30_000) == (29_500, 30_000)


def test_annotation_snap_uses_cursor_tip(app):
    pill = AnnotationPill()
    cursor_tip = QPoint(17, 23)
    seen = []
    pill._screen_geometry = lambda point=None: QRect(0, 0, 100, 100)
    pill._nearest_edge = lambda point, _screen=None: seen.append(point) or "left"

    pill._snap_after_drag(cursor_tip)

    assert seen == [cursor_tip]
    assert pill._orientation == "vertical"
    pill.close()


def test_dock_startup_indicator_waits_for_discovery_then_stops(app):
    class Engine:
        def is_recording(self): return False

    dock = DockWidget(Engine(), {"dock_edge": "right"})
    for _ in range(30):
        dock._on_first_blink_tick()

    assert dock._first_blink_timer.isActive()
    assert dock._is_first_launch is True

    dock._acknowledge_startup_indicator()

    assert dock._first_blink_timer.isActive() is False
    assert dock._is_first_launch is False
    assert dock._blink_on is False
    dock.close()


def test_stale_success_notification_is_safely_forgotten():
    class DeletedNotification:
        def isVisible(self):
            raise RuntimeError("wrapped C/C++ object has been deleted")

    owner = object.__new__(WWRecorderApp)
    owner._success_notif = DeletedNotification()

    owner._dismiss_success_notification()

    assert owner._success_notif is None


def test_file_row_has_one_combined_image_action_and_drag_preview(app, tmp_path):
    filepath = tmp_path / "capture.png"
    image = QImage(48, 32, QImage.Format.Format_ARGB32)
    image.fill(0xFF336699)
    assert image.save(str(filepath))
    row = _FileRow(str(filepath), defer_load=True)

    menu = row._build_actions_menu()
    assert [action.text() for action in menu.actions()] == [
        "Open & Edit", "Copy", "Rename", "Delete"
    ]
    assert hasattr(row, '_btn_menu')
    assert row._btn_menu.text() == ""
    assert not row._btn_menu.icon().isNull()
    assert not hasattr(row, '_btn_rename')
    assert not hasattr(row, '_btn_delete')

    preview = row._build_drag_pixmap()
    assert not preview.isNull()
    assert preview.hasAlphaChannel()

    routed = []
    row.edit_requested.connect(lambda path: routed.append(("edit", path)))
    menu.actions()[0].trigger()
    assert routed == [("edit", str(filepath))]


def test_file_row_video_menu_has_play_and_edit_in_requested_order(app, tmp_path):
    filepath = tmp_path / "capture.mp4"
    filepath.write_bytes(b"placeholder")
    row = _FileRow(str(filepath), defer_load=True)

    menu = row._build_actions_menu()
    assert [action.text() for action in menu.actions()] == [
        "Play", "Edit", "Copy", "Rename", "Delete"
    ]

    routed = []
    row.play_video_requested.connect(lambda path: routed.append(("play", path)))
    row.edit_requested.connect(lambda path: routed.append(("edit", path)))
    menu.actions()[0].trigger()
    menu.actions()[1].trigger()
    assert routed == [("play", str(filepath)), ("edit", str(filepath))]


def test_video_file_primary_menu_action_is_play(app, tmp_path):
    filepath = tmp_path / "capture.mkv"
    filepath.write_bytes(b"not-media")
    row = _FileRow(str(filepath), defer_load=True)
    menu = row._build_actions_menu()
    assert menu.actions()[0].text() == "Play"
    routed = []
    row.play_video_requested.connect(routed.append)
    menu.actions()[0].trigger()
    assert routed == [str(filepath)]
    row.close()


def test_developer_mode_details_wrap_inside_settings_sidebar(app, tmp_path):
    config = {
        "output_folder": str(tmp_path),
        "developer_mode": True,
        "current_version": "1.6.2",
        "font_size": "Default",
    }
    sidebar = SettingsSidebar(config, default_config=config)
    sidebar.resize(380, 700)
    sidebar.show()
    app.processEvents()

    assert sidebar._lbl_dev_mode_info.wordWrap()
    assert sidebar._lbl_dev_mode_info.minimumWidth() == 0
    assert sidebar._btn_dev_releases.text() == "GitHub Releases"
    assert sidebar._btn_dev_releases.minimumWidth() == 0
    assert sidebar._btn_dev_releases.width() <= sidebar._dev_mode_details.width()
    sidebar.close()


def test_recent_sidebar_tips_describe_verified_actions(app, tmp_path):
    tips = ' '.join(RecentFilesSidebar.TIPS)
    assert 'Export Audio' in tips and 'Delete Segments' in tips
    assert 'Trim & adjusts' not in tips

    for mode, width in (("Default", 380), ("Large", 480)):
        sidebar = RecentFilesSidebar(str(tmp_path), font_size_mode=mode)
        sidebar.resize(width, 700)
        sidebar.show()
        app.processEvents()

        label = sidebar._lbl_drag_info
        metrics = label.fontMetrics()
        assert not label.wordWrap()
        assert label.height() == metrics.height() + 4
        assert sidebar.layout().contentsMargins().bottom() == 0
        sidebar.close()


def test_live_laser_trail_is_transient_and_not_annotation_history(app):
    canvas = AnnotationCanvas()
    canvas.set_tool('laser')
    redo_marker = {'type': 'rect'}
    canvas._redo_stack = [redo_marker]

    press = QMouseEvent(
        QEvent.Type.MouseButtonPress, QPointF(40, 50), QPointF(40, 50), QPointF(40, 50),
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
    )
    move = QMouseEvent(
        QEvent.Type.MouseMove, QPointF(140, 100), QPointF(140, 100), QPointF(140, 100),
        Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
    )
    release = QMouseEvent(
        QEvent.Type.MouseButtonRelease, QPointF(140, 100), QPointF(140, 100), QPointF(140, 100),
        Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
    )
    canvas.mousePressEvent(press)
    canvas.mouseMoveEvent(move)
    canvas.mouseReleaseEvent(release)

    assert canvas._items == []
    assert canvas._redo_stack == [redo_marker]
    assert len(canvas._laser_trails) == 1
    assert len(canvas._laser_trails[0]['points']) > 2
    assert canvas._laser_fade_timer.isActive()
    first_deadline = canvas._laser_expires_at

    # Starting another gesture during the grace period pauses expiry and makes
    # every earlier stroke fully visible again.
    canvas._laser_trails[0]['opacity'] = 0.2
    second_press = QMouseEvent(
        QEvent.Type.MouseButtonPress, QPointF(60, 120), QPointF(60, 120), QPointF(60, 120),
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
    )
    second_release = QMouseEvent(
        QEvent.Type.MouseButtonRelease, QPointF(60, 120), QPointF(60, 120), QPointF(60, 120),
        Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
    )
    canvas.mousePressEvent(second_press)
    assert canvas._laser_fade_at is None
    assert canvas._laser_expires_at is None
    assert canvas._laser_trails[0]['opacity'] == 1.0
    assert not canvas._laser_fade_timer.isActive()
    canvas._advance_laser_trails()
    assert len(canvas._laser_trails) == 1
    canvas.mouseReleaseEvent(second_release)
    assert len(canvas._laser_trails) == 2
    assert canvas._laser_expires_at >= first_deadline
    assert canvas._laser_fade_timer.isActive()

    canvas._laser_fade_at = time.monotonic() - 0.1
    canvas._laser_expires_at = time.monotonic() + 0.1
    canvas._advance_laser_trails()
    assert all(0.0 < trail['opacity'] < 1.0 for trail in canvas._laser_trails)
    assert canvas._laser_trails[0]['opacity'] == canvas._laser_trails[1]['opacity']
    canvas._laser_expires_at = time.monotonic() - 0.1
    canvas._advance_laser_trails()
    assert canvas._laser_trails == []
    assert not canvas._laser_fade_timer.isActive()
    canvas.close()


def test_live_laser_trail_has_a_soft_glow(app):
    from annotation_tool import draw_annotation_item

    image = QImage(80, 60, QImage.Format.Format_ARGB32)
    image.fill(0x00000000)
    painter = QPainter(image)
    draw_annotation_item(painter, {
        'type': 'laser', 'points': [(10.0, 30.0), (70.0, 30.0)],
        'color': '#FF3B30', 'width': 5.0, 'opacity': 1.0,
    })
    painter.end()

    core_alpha = image.pixelColor(40, 30).alpha()
    glow_alpha = image.pixelColor(40, 34).alpha()
    assert core_alpha > glow_alpha > 0


def test_laser_control_is_not_added_to_photo_editor(app, tmp_path):
    from annotation_tool import AnnotateWindow

    image_path = tmp_path / 'photo-editor-no-laser.png'
    image = QImage(80, 60, QImage.Format.Format_ARGB32)
    image.fill(0xFFFFFFFF)
    assert image.save(str(image_path))
    editor = AnnotateWindow(str(image_path))
    assert 'laser' not in editor._tool_buttons
    editor.close()


def test_record_request_dismisses_visible_sidebars_before_selection(app):
    class Engine:
        def is_busy(self):
            return False

    class Panel:
        def __init__(self):
            self.visible = True
            self.close_calls = []

        def isVisible(self):
            return self.visible

        def close_panel(self, animate=True):
            self.close_calls.append(animate)
            self.visible = False

    owner = object.__new__(WWRecorderApp)
    owner.engine = Engine()
    owner._screenshot_in_progress = False
    owner._recording_prepare_in_progress = False
    owner._overlay = None
    owner._settings_sidebar = Panel()
    owner._recent_panel = Panel()

    owner._on_start_recording()

    assert owner._settings_sidebar.close_calls == [False]
    assert owner._recent_panel.close_calls == [False]
    assert owner._overlay.isVisible()
    owner._overlay._cancel_emitted = True
    owner._overlay.close()


def test_escape_cancels_sidebar_inline_rename(app, tmp_path):
    filepath = tmp_path / "capture.png"
    filepath.write_bytes(b"x")
    row = _FileRow(str(filepath), defer_load=True)
    renamed = []
    row.rename_requested.connect(lambda *args: renamed.append(args))
    row._start_rename()
    row._rename_edit.setText("changed")
    QTest.keyClick(row._rename_edit, Qt.Key.Key_Escape)
    assert not row._is_renaming
    assert not row._lbl_name.isHidden()
    assert renamed == []
    row.close()

    row._copy_file()
    assert row._btn_menu.text() == "✓"
    assert Path(QApplication.clipboard().mimeData().urls()[0].toLocalFile()) == filepath
    row._restore_menu_dots()
    assert row._btn_menu.text() == ""
    row.close()

def test_recent_file_open_and_edit_stay_inside_wwrecorder(app, tmp_path):
    image_path = tmp_path / "capture.png"
    video_path = tmp_path / "capture.mkv"
    image_path.touch()
    video_path.touch()

    sidebar = RecentFilesSidebar.__new__(RecentFilesSidebar)
    QWidget.__init__(sidebar)
    routed = []
    sidebar.annotate_file_requested.connect(lambda path: routed.append(("image-open", path)))
    sidebar.play_video_requested.connect(lambda path: routed.append(("video-open", path)))
    sidebar.edit_file_requested.connect(lambda path: routed.append(("edit", path)))

    sidebar._open_file(str(image_path))
    sidebar._open_file(str(video_path))
    sidebar._edit_file(str(image_path))
    sidebar._edit_file(str(video_path))

    assert routed == [
        ("image-open", str(image_path)),
        ("video-open", str(video_path)),
        ("edit", str(image_path)),
        ("edit", str(video_path)),
    ]
    sidebar.close()


def test_export_worker_stop_never_waits_on_gui_caller():
    class Process:
        def __init__(self): self.killed = False
        def kill(self): self.killed = True
        def wait(self, *_args, **_kwargs):
            raise AssertionError("stop() must not synchronously wait")

    worker = _ExportWorker(["ffmpeg", "out.mkv"], "out.mkv")
    process = Process()
    worker._process = process

    worker.stop()

    assert process.killed is True
    assert worker._is_stopped is True


def test_player_close_does_not_stop_media_backend_synchronously(app):
    class Timer:
        def stop(self):
            pass

    class Player:
        def __init__(self):
            self.detached = False

        def setVideoOutput(self, output):
            assert output is None
            self.detached = True

        def stop(self):
            raise AssertionError("closeEvent must not synchronously stop QMediaPlayer")

    window = VideoPlayerWindow.__new__(VideoPlayerWindow)
    QWidget.__init__(window)
    window._closing = False
    window._close_ready = True
    window._edit_mode = False
    window._close_poll_timer = Timer()
    window._thumb_extractor = None
    window._zoom_extractor = None
    window._export_worker = None
    window._ss_worker = None
    window._player = Player()
    window._video_view = None
    closed = []
    window.closed.connect(lambda value: closed.append(value))

    event = QCloseEvent()
    window.closeEvent(event)

    assert event.isAccepted()
    assert window._player.detached is True
    assert closed == [window]
    window.deleteLater()


def test_edit_mode_keeps_preview_transport_controls_visible(app, tmp_path, monkeypatch):
    video_path = tmp_path / "preview.mkv"
    video_path.touch()
    monkeypatch.setattr(VideoPlayerWindow, "_extract_thumbnails", lambda self: None)

    window = VideoPlayerWindow(str(video_path), str(tmp_path))
    window.show()
    window._toggle_edit_mode()
    app.processEvents()

    assert window._edit_mode is True
    assert window._btn_row_widget.isVisible()
    assert window._btn_play.isVisible()
    assert window._btn_vol.isVisible()
    assert window._sld_volume.isVisible()
    assert all(not widget.isVisible() for widget in window._playback_only_widgets)

    window._close_ready = True
    window.close()
    window.deleteLater()


def test_player_uses_bottom_right_file_actions_without_a_duplicate_title_row(app, tmp_path, monkeypatch):
    video_path = tmp_path / "layout.mkv"
    video_path.touch()
    monkeypatch.setattr(VideoPlayerWindow, "_extract_thumbnails", lambda self: None)

    window = VideoPlayerWindow(str(video_path), str(tmp_path))
    window.resize(1280, 720)
    window.show()
    app.processEvents()

    assert not window._top_bar.isVisible()  # fullscreen-only chrome takes no normal layout space
    assert window._btn_screenshot.parentWidget() is window._btn_edit.parentWidget()
    assert window._btn_screenshot.x() < window._btn_edit.x()
    assert window._btn_edit.mapTo(window, window._btn_edit.rect().center()).y() > window.height() // 2

    window._close_ready = True
    window.close()
    window.deleteLater()


def test_player_speed_label_is_outside_a_filled_speed_selector_and_play_is_red(app, tmp_path, monkeypatch):
    video_path = tmp_path / "speed.mkv"
    video_path.touch()
    monkeypatch.setattr(VideoPlayerWindow, "_extract_thumbnails", lambda self: None)

    window = VideoPlayerWindow(str(video_path), str(tmp_path))
    window.show()
    app.processEvents()

    assert window._lbl_speed.text() == "Speed"
    assert window._lbl_speed.parentWidget() is not window._speed_control
    assert window._cmb_speed.parentWidget() is window._speed_control
    assert window._cmb_speed.width() >= window._speed_control.width() - 4
    style = window._btn_play.styleSheet()
    assert "#B91C1C" in style and "#FF4055" not in style

    window._close_ready = True
    window.close()
    window.deleteLater()


def test_annotation_pause_announces_its_state_in_the_screen_center(app):
    canvas = AnnotationCanvas()
    canvas.resize(1000, 700)
    canvas.show()
    app.processEvents()

    canvas.set_annotation_paused(True)
    assert canvas._interactive is False
    assert canvas._toast_widget.isVisible()
    assert "Annotation paused" in canvas._toast_widget.text_label.text()
    assert canvas._toast_widget.y() == (canvas.height() - canvas._toast_widget.height()) // 2

    canvas.set_annotation_paused(False)
    assert canvas._interactive is True
    assert "Annotation is active" in canvas._toast_widget.text_label.text()
    canvas.close()


def test_photo_text_selection_uses_image_coordinates_after_fit(app, tmp_path):
    image_path = tmp_path / "offset.png"
    image = QImage(200, 100, QImage.Format.Format_ARGB32)
    image.fill(0xFFFFFFFF)
    assert image.save(str(image_path))
    canvas = _DrawingArea(str(image_path))
    canvas.resize(700, 500)
    canvas.show()
    app.processEvents()
    item = {
        "type": "text", "start": (40.0, 25.0), "end": (120.0, 55.0),
        "text": "Select me", "color": "#FF3B30", "font_size": 16,
        "bold": False, "italic": False, "underline": False,
    }
    canvas._items = [item]
    canvas.set_tool("text")
    target = QPoint(
        round(70 * canvas._scale + canvas._offset_x),
        round(40 * canvas._scale + canvas._offset_y),
    )
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=target)
    assert canvas._selected_shape_idx == 0
    canvas.close()


def _crop_move_event(x, y, modifiers=Qt.KeyboardModifier.NoModifier):
    point = QPointF(float(x), float(y))
    return QMouseEvent(
        QEvent.Type.MouseMove, point, point, point,
        Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, modifiers,
    )


def test_photo_crop_is_free_by_default_and_ctrl_locks_current_ratio(app, tmp_path):
    image_path = tmp_path / "crop.png"
    image = QImage(240, 200, QImage.Format.Format_ARGB32)
    image.fill(0xFFFFFFFF)
    assert image.save(str(image_path))
    canvas = _DrawingArea(str(image_path))
    canvas._scale = 1.0
    canvas._offset_x = canvas._offset_y = 0.0
    canvas._tool = "crop"
    canvas._crop_rect = QRectF(10, 10, 100, 100)
    canvas._crop_orig_rect = QRectF(canvas._crop_rect)
    canvas._crop_start_pos = canvas._crop_rect.bottomRight()
    canvas._crop_drag = "br"
    canvas._drawing = True
    canvas.mouseMoveEvent(_crop_move_event(160, 130))
    assert round(canvas._crop_rect.width()) == 150
    assert round(canvas._crop_rect.height()) == 120

    canvas._crop_rect = QRectF(10, 10, 100, 100)
    canvas._crop_orig_rect = QRectF(canvas._crop_rect)
    canvas._crop_start_pos = canvas._crop_rect.bottomRight()
    canvas._crop_drag = "br"
    canvas.mouseMoveEvent(_crop_move_event(160, 130, Qt.KeyboardModifier.ControlModifier))
    assert round(canvas._crop_rect.width()) == round(canvas._crop_rect.height())
    canvas.close()


def test_structural_transform_invalidates_old_crop_geometry(app, tmp_path):
    image_path = tmp_path / "rotate.png"
    image = QImage(120, 80, QImage.Format.Format_ARGB32)
    image.fill(0xFFFFFFFF)
    assert image.save(str(image_path))
    canvas = _DrawingArea(str(image_path))
    canvas.set_tool("crop")
    assert canvas._crop_rect is not None
    canvas.rotate_90()
    assert canvas._crop_rect is None
    canvas.set_tool("crop")
    assert canvas._crop_rect.size() == QRectF(0, 0, 80, 120).size()
    canvas.close()


def test_crop_undo_redo_rotate_then_crop_uses_current_image_bounds(app, tmp_path):
    image_path = tmp_path / "crop-history.png"
    image = QImage(200, 120, QImage.Format.Format_ARGB32)
    image.fill(0xFFFFFFFF)
    assert image.save(str(image_path))
    canvas = _DrawingArea(str(image_path))
    canvas.set_tool("crop")
    canvas._crop_rect = QRectF(20, 10, 100, 80)
    canvas.commit_crop()
    assert (canvas._original.width(), canvas._original.height()) == (100, 80)
    canvas.undo()
    canvas.redo()
    canvas.rotate_90()
    assert (canvas._original.width(), canvas._original.height()) == (80, 100)
    canvas.set_tool("crop")
    assert canvas._crop_rect == QRectF(0, 0, 80, 100)
    canvas.close()


def test_photo_eraser_is_one_undoable_gesture_at_fit_scale(app, tmp_path):
    image_path = tmp_path / "erase.png"
    image = QImage(1000, 600, QImage.Format.Format_ARGB32)
    image.fill(0xFFFFFFFF)
    assert image.save(str(image_path))
    canvas = _DrawingArea(str(image_path))
    canvas._scale = 0.25
    stroke = {
        "type": "pencil", "points": [(100.0, 100.0), (300.0, 100.0)],
        "color": "#FF3B30", "width": 4.0, "opacity": 1.0,
    }
    canvas._items = [stroke]
    canvas._tool = "eraser"
    canvas._drawing = True
    canvas._erase_action_items = []
    canvas._erase_at(QPointF(200.0, 120.0))  # 20 image px = 5 screen px
    release = QMouseEvent(
        QEvent.Type.MouseButtonRelease, QPointF(0, 0), QPointF(0, 0), QPointF(0, 0),
        Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
    )
    canvas.mouseReleaseEvent(release)
    assert canvas._items[-1].get("_action") == "erase"
    canvas.undo()
    assert stroke in canvas._items
    canvas.close()


def test_live_eraser_sweeps_fast_drag_and_undoes_as_one_gesture(app):
    canvas = AnnotationCanvas()
    first = {
        "type": "pencil", "points": [(40.0, 80.0)],
        "color": "#FF3B30", "width": 4.0, "opacity": 1.0,
    }
    second = {
        "type": "pencil", "points": [(200.0, 80.0)],
        "color": "#FF3B30", "width": 4.0, "opacity": 1.0,
    }
    history_marker = {"_action": "clear", "_cleared_items": []}
    canvas._items = [first, history_marker, second]
    canvas._tool = "eraser"
    canvas._drawing = True
    canvas._erase_action_items = []
    canvas._erase_original_indexes = {id(first): 0, id(history_marker): 1, id(second): 2}
    canvas._erase_last_pos = QPointF(0.0, 80.0)
    canvas._erase_sweep(canvas._erase_last_pos, QPointF(240.0, 80.0))

    release = QMouseEvent(
        QEvent.Type.MouseButtonRelease, QPointF(240, 80), QPointF(240, 80),
        QPointF(240, 80), Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    canvas.mouseReleaseEvent(release)
    assert len(canvas._items) == 2
    assert canvas._items[-1].get("_action") == "erase"
    assert len(canvas._items[-1]["_erased_items"]) == 2
    canvas.undo()
    assert canvas._items == [first, history_marker, second]
    canvas.close()


def test_arrow_heads_scale_with_thickness_but_remain_restrained():
    sizes = [_arrow_head_size(width, 200) for width in (2, 4, 8, 14)]
    assert sizes == sorted(sizes)
    assert len(set(sizes)) == 4
    assert sizes[-1] <= 24


def test_text_size_and_video_spin_controls_use_png_arrow_assets(app):
    bar = _TextEditBar()
    integer = NoScrollSpinBox()
    decimal = NoScrollDoubleSpinBox()
    assert "spn_down.png" in bar._combo_size.styleSheet()
    assert "image: none" not in bar._combo_size.styleSheet()
    for widget in (integer, decimal):
        assert "spn_up.png" in widget.styleSheet()
        assert "spn_down.png" in widget.styleSheet()
    bar.close()
    integer.close()
    decimal.close()


def test_screenshot_editor_thickness_preview_does_not_overlap_its_label(app):
    button = _ThicknessButton('Stroke Thickness', size=34, icon_size=18)
    assert button.width() == 86
    assert button._gauge_center_x() == 17.0
    button.set_compact(True)
    assert button._gauge_center_x() == button.width() / 2.0
    button.close()


def test_fullscreen_controls_auto_hide_and_restore_on_activity(app, tmp_path, monkeypatch):
    video_path = tmp_path / "fullscreen.mkv"
    video_path.touch()
    monkeypatch.setattr(VideoPlayerWindow, "_extract_thumbnails", lambda self: None)

    window = VideoPlayerWindow(str(video_path), str(tmp_path))
    window.show()
    window._toggle_fullscreen()
    app.processEvents()

    assert window.isFullScreen()
    assert not window._top_bar.isVisible()
    assert window._controls_widget.isVisible()
    assert window._fullscreen_controls_timer.isActive()

    monkeypatch.setattr(window, "_fullscreen_chrome_has_pointer", lambda: False)
    window._hide_fullscreen_controls()
    app.processEvents()
    assert not window._controls_widget.isVisible()

    window._show_fullscreen_controls()
    app.processEvents()
    assert not window._top_bar.isVisible()
    assert window._controls_widget.isVisible()
    assert window._fullscreen_controls_timer.isActive()

    window._exit_fullscreen()
    window._close_ready = True
    window.close()
    window.deleteLater()


def test_capture_scheduler_never_builds_duplicate_frame_backlog():
    deadline, missed = _next_frame_deadline(0.0, 0.040)
    assert deadline == pytest.approx(0.040)
    assert missed == 0

    deadline, missed = _next_frame_deadline(deadline, 2.040)
    assert deadline == pytest.approx(2.040)
    assert missed > 50


def test_audio_callback_jitter_does_not_inject_silence():
    class JitteryRecorder:
        def record(self, numframes):
            # Simulate ordinary scheduler delay and a real WASAPI diagnostic.
            time.sleep(0.015)
            warnings.warn("data discontinuity in recording", recorder.sc.SoundcardRuntimeWarning)
            return recorder.np.ones((numframes, 2), dtype=recorder.np.float32)

    data, discontinuities = _read_audio_chunk(JitteryRecorder(), 4800)

    # The backend guarantees exactly numframes. Wall-clock delay is not an
    # unknown gap and must never add synthetic silence or alter the samples.
    assert data.shape == (4800, 2)
    assert recorder.np.all(data == 1.0)
    assert discontinuities == 1


def test_final_audio_graph_uses_only_low_latency_mic_cleanup():
    mixed = _audio_filter_graph(True, True)
    system_only = _audio_filter_graph(True, False)
    mic_only = _audio_filter_graph(False, True)

    assert "loudnorm" not in mixed + system_only + mic_only
    assert "dynaudnorm" not in mixed + system_only + mic_only
    assert "volume=2" in mixed and "volume=2" in mic_only
    assert "volume=" not in system_only
    assert "afftdn" not in mixed + system_only + mic_only
    assert "highpass=f=70" in mixed and "highpass=f=70" in mic_only
    assert "agate=" not in mixed + system_only + mic_only
    assert "normalize=0" in mixed
    assert "alimiter=limit=0.95:level=false:latency=true" in mixed
    assert "sample_rates=48000" in mixed


def test_shift_letter_hotkeys_are_valid_and_ambiguous_bindings_are_rejected():
    assert validate_hotkey("<shift>+m") == (True, "")
    assert validate_hotkey("<shift>+k") == (True, "")
    assert not validate_hotkey("k")[0]
    assert not validate_hotkey("<shift>")[0]


def test_exe_update_checker_opens_official_release_page():
    checker = UpdateChecker("1.6.2")
    assert checker.website_url == "https://github.com/akasumitlamba/WWRecorder/releases/latest"


def test_exe_settings_exposes_download_update_and_opt_in_preview_link(app):
    sidebar = SettingsSidebar({"current_version": "1.6.2", "developer_mode": False})
    assert not hasattr(sidebar, "_chk_auto_update")
    assert sidebar._dev_mode_details.isHidden()
    assert sidebar._lbl_dev_mode_info.wordWrap()
    assert sidebar._btn_dev_releases.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Expanding
    sidebar.set_update_status(True, "v1.6.3", "https://github.com/akasumitlamba/WWRecorder/releases/latest")
    assert sidebar._btn_check_update.text() == "Open download page"
    sidebar._chk_developer_mode.setChecked(True)
    assert not sidebar._dev_mode_details.isHidden()
    assert not sidebar._btn_dev_releases.isHidden()
    sidebar.close()


def test_text_overlay_starts_at_exact_subsecond_playhead():
    assert _text_overlay_range_at_playhead(12_734, 30_000) == (12_734, 17_734)
    assert _text_overlay_range_at_playhead(29_800, 30_000) == (29_800, 30_000)


def test_single_click_on_video_surface_emits_playback_toggle(app):
    view = _VideoGraphicsView()
    emitted = []
    view.clicked.connect(lambda: emitted.append(True))
    point = QPointF(20, 20)
    event = QMouseEvent(
        QEvent.Type.MouseButtonPress, point, point, point,
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    view.mousePressEvent(event)
    assert emitted == [True]
    view.close()


def test_final_video_filter_removes_pause_gaps_and_restores_cfr():
    filter_text = _video_timing_filter([(2.0, 4.5)], 8.0)

    assert "gte(PTS*TB\\,4.500000)*2.500000/TB" in filter_text
    assert "fps=30" in filter_text
    assert "tpad=stop_mode=clone" in filter_text


def test_initial_prerecord_pause_is_not_subtracted_twice():
    filter_text = _video_timing_filter([(0.0, 0.6), (3.0, 4.0)], 6.0)

    assert "between(t\\,0.000000\\,0.600000)" in filter_text
    assert "gte(PTS*TB\\,0.600000)" not in filter_text
    assert "gte(PTS*TB\\,4.000000)*1.000000/TB" in filter_text


def test_video_timing_filter_stretches_dropped_frames_to_audio_wall_clock():
    # Ten seconds captured at an overloaded 20 fps still occupies ten seconds;
    # surviving raw frames must not be played as a 6.7-second 30-fps stream.
    filter_text = _video_timing_filter([], 10.0, source_frame_count=200)
    scale_text = filter_text.split("setpts='(PTS-STARTPTS)*", 1)[1].split("'", 1)[0]
    assert float(scale_text) == pytest.approx(1.502512563, rel=1e-6)
    assert "fps=30" in filter_text


def test_rect_annotation_uses_miter_join(app):
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QImage, QPainter
    from annotation_tool import draw_annotation_item
    img = QImage(100, 100, QImage.Format.Format_ARGB32)
    p = QPainter(img)
    item = {'type': 'rect', 'color': '#FF0000', 'width': 6, 'start': (10, 10), 'end': (90, 90)}
    draw_annotation_item(p, item)
    pen = p.pen()
    assert pen.joinStyle() == Qt.PenJoinStyle.MiterJoin
    assert pen.miterLimit() >= 10.0
    p.end()


def test_pause_toggled_switches_icon_to_play_and_pause(app):
    pill = AnnotationPill()
    # Initially unpaused
    assert "Pause" in pill._btn_pause.toolTip()

    # Toggle to paused
    pill._btn_pause.setChecked(True)
    assert "Resume" in pill._btn_pause.toolTip()

    # Toggle back to active
    pill._btn_pause.setChecked(False)
    assert "Pause" in pill._btn_pause.toolTip()
    pill.close()


def test_annotation_shortcuts_trigger_actions(app):
    from PyQt6.QtGui import QKeyEvent
    from PyQt6.QtCore import QEvent, Qt
    from annotation_tool import AnnotationCanvas
    canvas = AnnotationCanvas()
    actions = []
    canvas.undo = lambda: actions.append('undo')
    canvas.redo = lambda: actions.append('redo')
    canvas.pause_requested.connect(lambda: actions.append('pause'))

    # Press Space
    event_space = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier)
    canvas.keyPressEvent(event_space)
    assert 'pause' in actions

    # Press Ctrl+Z
    event_ctrl_z = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    canvas.keyPressEvent(event_ctrl_z)
    assert 'undo' in actions

    # Press Ctrl+Y
    event_ctrl_y = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Y, Qt.KeyboardModifier.ControlModifier)
    canvas.keyPressEvent(event_ctrl_y)
    assert 'redo' in actions

    # Press Esc (when idle) -> emit close_requested
    canvas.close_requested.connect(lambda: actions.append('close'))
    event_esc = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)


def test_rect_annotation_uses_miter_join(app):
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QImage, QPainter
    from annotation_tool import draw_annotation_item
    img = QImage(100, 100, QImage.Format.Format_ARGB32)
    p = QPainter(img)
    item = {'type': 'rect', 'color': '#FF0000', 'width': 6, 'start': (10, 10), 'end': (90, 90)}
    draw_annotation_item(p, item)
    pen = p.pen()
    assert pen.joinStyle() == Qt.PenJoinStyle.MiterJoin
    assert pen.miterLimit() >= 10.0
    p.end()


def test_pause_toggled_switches_icon_to_play_and_pause(app):
    pill = AnnotationPill()
    # Initially unpaused
    assert "Pause" in pill._btn_pause.toolTip()

    # Toggle to paused
    pill._btn_pause.setChecked(True)
    assert "Resume" in pill._btn_pause.toolTip()

    # Toggle back to active
    pill._btn_pause.setChecked(False)
    assert "Pause" in pill._btn_pause.toolTip()
    pill.close()


def test_annotation_shortcuts_trigger_actions(app):
    from PyQt6.QtGui import QKeyEvent
    from PyQt6.QtCore import QEvent, Qt
    from annotation_tool import AnnotationCanvas
    canvas = AnnotationCanvas()
    actions = []
    canvas.undo = lambda: actions.append('undo')
    canvas.redo = lambda: actions.append('redo')
    canvas.pause_requested.connect(lambda: actions.append('pause'))

    # Press Space
    event_space = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier)
    canvas.keyPressEvent(event_space)
    assert 'pause' in actions

    # Press Ctrl+Z
    event_ctrl_z = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    canvas.keyPressEvent(event_ctrl_z)
    assert 'undo' in actions

    # Press Ctrl+Y
    event_ctrl_y = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Y, Qt.KeyboardModifier.ControlModifier)
    canvas.keyPressEvent(event_ctrl_y)
    assert 'redo' in actions

    # Press Esc (when idle) -> emit close_requested
    canvas.close_requested.connect(lambda: actions.append('close'))
    event_esc = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
    canvas.keyPressEvent(event_esc)
    assert 'close' in actions
    canvas.close()


def test_thickness_picker_uses_circular_radio_dot(app):
    from PyQt6.QtGui import QColor, QImage, QPainter
    from annotation_tool import _ThicknessRowWidget, _RadioDot
    row = _ThicknessRowWidget('normal', 'pencil', QColor('#FF3B30'))
    assert isinstance(row.radio, _RadioDot)
    assert not row.radio.isChecked()

    row.radio.setChecked(True)
    assert row.radio.isChecked()

    img = QImage(row.sizeHint(), QImage.Format.Format_ARGB32)
    p = QPainter(img)
    row.render(p)
    p.end()
    row.close()


def test_settings_share_copies_website_url(app):
    from dock_widget import SettingsSidebar
    from ui_elements import SettingsWindow

    expected_url = "https://akasumitlamba.github.io/WWRecorder/"

    sidebar = SettingsSidebar({"current_version": "1.6.2", "developer_mode": False})
    sidebar._copy_link()
    assert QApplication.clipboard().text() == expected_url
    sidebar.close()

    dlg = SettingsWindow({"output_folder": "", "hotkey": "<shift>+<backspace>"})
    dlg._copy_app_link()
    assert QApplication.clipboard().text() == expected_url
    dlg.close()

# End of focused regression tests.


def test_named_microphone_never_resolves_default_or_loopback(monkeypatch):
    from types import SimpleNamespace
    engine = RecordingEngine.__new__(RecordingEngine)
    engine.set_microphone('usb', 'USB microphone')
    real = SimpleNamespace(id='usb', name='USB microphone', isloopback=False)
    loopback = SimpleNamespace(id='speakers', name='Speakers', isloopback=True)
    monkeypatch.setattr(recorder.sc, 'all_microphones', lambda **kwargs: [loopback, real])
    def forbidden():
        raise AssertionError('Pinned microphone must not resolve the default')
    monkeypatch.setattr(recorder.sc, 'default_microphone', forbidden)
    assert engine._resolve_audio_device(False) is real
    assert engine.list_microphones() == [('usb', 'USB microphone')]
    engine.set_microphone('missing', 'Unplugged USB microphone')
    with pytest.raises(RuntimeError, match='Unplugged USB microphone'):
        engine._resolve_audio_device(False)


def test_tray_cannot_stop_a_take_that_is_still_preparing():
    owner = object.__new__(WWRecorderApp)
    owner._recording_prepare_in_progress = True
    messages = []
    owner.tray = type('Tray', (), {'icon': lambda self: None,
        'showMessage': lambda self, *args: messages.append(args)})()
    # No engine access should occur before preparation owns a stable take.
    owner._tray_record_action()
    assert 'still starting' in messages[0][1]


def test_dock_position_change_is_saved_and_synced_without_recursive_settings_signal(app):
    from types import SimpleNamespace
    owner = object.__new__(WWRecorderApp)
    owner.config = {'dock_edge':'right'}
    owner.dock = SimpleNamespace(_edge='bottom',_dock_x=200,_dock_y=100)
    owner._settings_sidebar = SettingsSidebar(owner.config)
    saved=[]; updates=[]
    owner._save_config=lambda: saved.append(dict(owner.config))
    owner._settings_sidebar.dock_position_changed.connect(updates.append)
    owner._on_dock_position_changed()
    assert saved == [{'dock_edge':'bottom','dock_x':200,'dock_y':100}]
    assert owner._settings_sidebar._cmb_dock_position.currentData() == 'bottom'
    assert not updates
    owner._settings_sidebar.close()


@pytest.mark.parametrize('edge',['left','right','top','bottom'])
def test_saved_dock_edge_and_offset_survive_config_reload(tmp_path, monkeypatch, edge):
    import json
    config=tmp_path/'config.json'
    config.write_text(json.dumps({'dock_edge':edge,'dock_x':-700,'dock_y':-300}))
    monkeypatch.setattr(main_module,'CONFIG_FILE',config)
    owner=object.__new__(WWRecorderApp)
    restored=owner._load_config()
    assert restored['dock_edge']==edge
    assert restored['dock_x']==-700 and restored['dock_y']==-300
