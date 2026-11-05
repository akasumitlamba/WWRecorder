"""Exercise editor dragging, scrubbing and dock state regressions."""
from types import SimpleNamespace
import pytest
from PyQt6.QtCore import Qt, QPoint
from PyQt6.QtTest import QTest
from video_editor import FrameTimelineWidget, VideoPlayerWindow, _DeleteRegionItem, _TextOverlayItem

@pytest.fixture
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])

@pytest.fixture
def timeline(app):
    widget = FrameTimelineWidget()
    widget.resize(1000, 160)
    widget.set_duration(100000)
    widget._position_ms = 90000
    widget.set_trim_enabled(True)
    widget._trim_start_ms, widget._trim_end_ms = 10000, 80000
    yield widget
    widget.close()

@pytest.mark.parametrize('kind', ['ov_start_0', 'ov_end_0', 'mute_start_0', 'mute_end_0', 'del_start_0', 'del_end_0'])
def test_each_region_endpoint_snaps_to_other_kind_and_excludes_itself(timeline, kind):
    timeline._text_overlays = [SimpleNamespace(start_ms=20000,end_ms=50000)]
    timeline._mute_regions = [_DeleteRegionItem(20000,50000)]
    timeline._delete_regions = [_DeleteRegionItem(20000,50000)]
    timeline._dragging = kind
    target = 10000 if 'start' in kind else 80000
    timeline._apply_drag(timeline._ms_to_x(target) + 3)
    collection = {'ov':timeline._text_overlays,'mute':timeline._mute_regions,'del':timeline._delete_regions}[kind.split('_')[0]]
    assert getattr(collection[0], 'start_ms' if 'start' in kind else 'end_ms') == target

@pytest.mark.parametrize('kind', ['ov_lane_0','mute_lane_0'])
def test_moving_region_preserves_duration_and_snaps_trailing_edge(timeline,kind):
    timeline._text_overlays=[SimpleNamespace(start_ms=20000,end_ms=25000)]
    timeline._mute_regions=[_DeleteRegionItem(20000,25000)]
    timeline._dragging=kind
    timeline._drag_lane_offset_ms=1000
    timeline._apply_drag(timeline._ms_to_x(76000)+2)
    region=(timeline._text_overlays if kind.startswith('ov') else timeline._mute_regions)[0]
    assert (region.start_ms,region.end_ms)==(75000,80000)


def test_snap_tolerance_shrinks_with_zoom_and_uses_nearest_target(timeline):
    timeline._dragging='mute_start_0'
    timeline._mute_regions=[_DeleteRegionItem(20000,50000)]
    assert timeline._snap_time(10500)==10000
    timeline._zoom=10
    assert timeline._snap_time(10500)==10500
    assert timeline._snap_time(10040)==10000
    timeline._delete_regions=[_DeleteRegionItem(10030,20000)]
    assert timeline._snap_time(10025)==10030


def test_alt_bypasses_snap(timeline,monkeypatch):
    from PyQt6.QtWidgets import QApplication
    monkeypatch.setattr(QApplication,'keyboardModifiers',lambda:Qt.KeyboardModifier.AltModifier)
    assert timeline._snap_time(10001)==10001


def test_mute_band_hit_test_and_change_signal(timeline):
    timeline._mute_regions=[_DeleteRegionItem(20000,50000)]
    pos=QPoint(int(timeline._ms_to_x(20000)),timeline._filmstrip_rect().bottom()-10)
    assert timeline._handle_at(pos)=='mute_start_0'
    calls=[]
    timeline.mute_time_changed.connect(lambda:calls.append(True))
    timeline._dragging='mute_end_0'
    timeline._apply_drag(timeline._ms_to_x(80000))
    assert calls and timeline._mute_regions[0].end_ms==80000


def test_trim_summary_is_not_clickable_and_native_title_is_unique(app):
    window=VideoPlayerWindow('Capture.mkv')
    window._thumbnails_loaded=True
    window._toggle_edit_mode()
    window._timeline.set_duration(30000)
    window._timeline._trim_start_ms=4000
    window._timeline._trim_end_ms=20000
    window._chk_trim.setChecked(True)
    QTest.mouseClick(window._chk_trim,Qt.MouseButton.LeftButton)
    assert window._timeline.get_trim()==(4000,20000)
    assert window._chk_trim.isChecked()
    window._sync_trim_fields()
    assert '00:04 → 00:20' in window._chk_trim.text()
    assert window._edit_heading.isHidden()
    assert window.windowTitle()=='Capture.mkv  |  Edit mode'
    window._force_exit_edit_mode();window.close()


def test_volume_speaker_pixels_stable_and_three_levels_distinct(app):
    window=VideoPlayerWindow('')
    initial=window._btn_vol.icon().pixmap(64,64).toImage()
    window._update_volume_icon()
    assert initial==window._btn_vol.icon().pixmap(64,64).toImage()
    images=[]
    for value in (20,50,90):
        window._sld_volume.setValue(value)
        window._update_volume_icon()
        images.append(window._btn_vol.icon().pixmap(64,64).toImage())
    for x in range(0,29):
        for y in range(64):
            assert images[0].pixel(x,y)==images[1].pixel(x,y)==images[2].pixel(x,y)
    assert images[0]!=images[1] and images[1]!=images[2]
    window._edit_mode=True
    window._mute_on_export=True
    window._update_volume_icon()
    export_disabled=window._btn_vol.icon().pixmap(64,64).toImage()
    assert export_disabled == images[-1]
    window._mute_on_export=False
    window._preview_user_muted=True
    window._update_volume_icon()
    assert export_disabled != window._btn_vol.icon().pixmap(64,64).toImage()
    window._edit_mode=False
    window.close()


def test_scrubbing_flushes_before_release_and_preserves_paused_state(app,monkeypatch):
    window=VideoPlayerWindow('')
    seeks=[]
    monkeypatch.setattr(window,'_seek_to_position',lambda value,**kw:seeks.append((value,kw)))
    window._seekbar.setRange(0,10000)
    window._on_seekbar_pressed()
    window._on_seekbar_moved(1000)
    window._on_seekbar_moved(2500)
    window._flush_scrub_preview()
    assert seeks==[(2500,{'preview':True})]
    assert window._seekbar_dragging
    window._seekbar.setValue(3000)
    window._on_seekbar_released()
    assert seeks[-1]==(3000,{'preview':True})
    assert not window._scrub_timer.isActive()
    window.close()


def test_scrubbing_decodes_a_frame_before_mouse_release(app,tmp_path,monkeypatch):
    import shutil, subprocess, time
    from pathlib import Path
    ffmpeg=shutil.which('ffmpeg') or str(Path(__file__).resolve().parents[1]/'app/ffmpeg.exe')
    monkeypatch.setattr('video_editor._get_ffmpeg', lambda: ffmpeg)
    video=tmp_path/'scrub.mkv'
    subprocess.run([ffmpeg,'-v','error','-y','-f','lavfi','-i','testsrc2=size=1280x720:rate=30:duration=4','-c:v','libx264','-g','120',str(video)],check=True,timeout=30)
    window=VideoPlayerWindow(str(video))
    frames=[]
    window._video_view.video_item.videoSink().videoFrameChanged.connect(lambda frame:frames.append(frame.startTime()))
    def wait_for(predicate):
        deadline=time.monotonic()+8
        while not predicate() and time.monotonic()<deadline:
            QTest.qWait(25)
        assert predicate()
    try:
        wait_for(lambda:window._player.duration()>0 and window._player.isSeekable())
        window._on_seekbar_pressed()
        frames.clear()
        window._on_seekbar_moved(2200)
        wait_for(lambda:window._scrub_preview_position == 2200)
        assert window._video_view._held_frame.isVisible()
        # Keep moving: multiple distinct decoded images must arrive before release.
        observed = set()
        for position in range(400, 3400, 100):
            window._on_seekbar_moved(position)
            QTest.qWait(100)
            if window._scrub_preview_position is not None:
                observed.add(window._scrub_preview_position)
        assert len(observed) >= 3
        assert window._seekbar_dragging
        window._on_seekbar_released()
    finally:
        window._scrub_timer.stop()
        window._player.stop()
        window.close()

@pytest.mark.parametrize('inline', [False, True])
def test_text_remove_immediately_destroys_preview_and_timeline(app, monkeypatch, inline):
    from PyQt6 import sip
    from video_editor import DraggableTextItem
    window = VideoPlayerWindow('')
    window._thumbnails_loaded = True
    monkeypatch.setattr(window._player, 'duration', lambda: 10000)
    window._toggle_edit_mode()
    window._add_text_overlay()
    row = window._text_overlays_container.itemAt(0).widget()
    overlay = row.item
    graphics = overlay._gfx_item
    if inline:
        graphics._start_editing()
    # Use the real sidebar removal signal, not just the controller method.
    row.removed.emit(row)
    assert not window._text_overlays
    assert not window._timeline._text_overlays
    assert window._text_overlays_container.count() == 0
    assert overlay._gfx_item is None and sip.isdeleted(graphics)
    assert not any(isinstance(item, DraggableTextItem) for item in window._video_view.gfx_scene.items())
    assert row.isHidden()
    window._force_exit_edit_mode()
    window.close()


def test_caption_action_buttons_do_not_resize_with_caption(app):
    from video_editor import DraggableTextItem, _VideoGraphicsView
    view = _VideoGraphicsView()
    model = _TextOverlayItem()
    graphics = DraggableTextItem(model, view.video_item)
    view.gfx_scene.addItem(graphics)
    original = graphics._action_bar.boundingRect()
    for font_size in (12, 32, 80, 140, 24):
        model.font_size = font_size
        graphics.update_style()
        assert graphics._action_bar.boundingRect() == original
    view.close()


def test_video_surface_holds_last_frame_at_eof_and_clears_for_new_source(app):
    from PyQt6.QtGui import QImage, QColor
    from PyQt6.QtMultimedia import QVideoFrame
    from video_editor import _VideoGraphicsView
    view = _VideoGraphicsView()
    image = QImage(160, 90, QImage.Format.Format_RGB32)
    image.fill(QColor('#18a340'))
    frame = QVideoFrame(image)
    view._remember_frame(frame)
    # The cache owns pixels, not a hardware decoder surface or mapped frame.
    assert view._last_frame_image is not image
    view._remember_frame(QVideoFrame())
    assert view._held_frame.isVisible()
    assert view._held_frame.pixmap().toImage().pixelColor(80, 45).green() > 140
    view._remember_frame(frame)
    assert not view._held_frame.isVisible()
    view._remember_frame(QVideoFrame())
    view.clear_held_frame()
    assert not view._held_frame.isVisible()
    assert view._held_frame.pixmap().isNull()
    view.close()


def test_caption_time_changes_update_preview_without_playback(app, monkeypatch):
    window = VideoPlayerWindow('')
    window._thumbnails_loaded = True
    monkeypatch.setattr(window._player, 'duration', lambda: 10000)
    monkeypatch.setattr(window._player, 'position', lambda: 2000)
    window._toggle_edit_mode()
    window._add_text_overlay()
    row = window._text_overlays_container.itemAt(0).widget()
    graphics = row.item._gfx_item
    assert graphics.isVisible()
    row.set_start_time(3000)
    assert not graphics.isVisible()
    row.set_start_time(1000)
    assert graphics.isVisible()
    window._remove_text_overlay(row)
    window._force_exit_edit_mode()
    window.close()


def test_scrub_cleanup_accepts_partial_initialization(app):
    window = VideoPlayerWindow('')
    del window._scrub_process
    window._cancel_scrub_decoder()
    assert window._scrub_process is None
    window.close()


def test_scrub_time_label_tracks_pointer_before_decoder_completes(app, monkeypatch):
    window = VideoPlayerWindow('')
    monkeypatch.setattr(window._player, 'duration', lambda: 10000)
    monkeypatch.setattr(window._player, 'position', lambda: 1000)
    window._seekbar.setRange(0, 10000)
    window._on_seekbar_pressed()
    window._seekbar.setValue(7000)
    window._on_seekbar_moved(7000)
    assert window._lbl_time.text() == '00:07 / 00:10'
    window._scrub_timer.stop()
    window.close()
