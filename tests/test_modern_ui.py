"""Approved icon visibility, cursor precision, processing lifecycle and player fit."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
import json
import pytest
from PIL import Image
from PyQt6.QtCore import Qt, QPoint, QRect
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest
from icon_theme import asset_path, ALIASES, wordmark_pixmap
from processing_notice import ProcessingNotice, ActivityRing
from tool_cursors import tool_cursor
from dock_widget import RecentFilesSidebar
from annotation_tool import _AnnotationToolBtn
from video_editor import VideoPlayerWindow

ROOT=Path(__file__).resolve().parents[1]

@pytest.fixture(scope='module')
def app(): return QApplication.instance() or QApplication([])


def test_all_generated_assets_are_padded_transparent_and_complete():
    root=ROOT/'app/icons/modern'
    manifest=json.loads((root/'manifest.json').read_text())
    names=[i['name'] for i in manifest['icons']]+manifest['cursors']
    assert len(names)==len(set(names))==70
    for name in names:
        image=Image.open(root/(name+'.png')).convert('RGBA')
        assert image.size==(64,64)
        assert image.getchannel('A').getextrema()[1]>=230
        for p in [(x,y) for x in range(64) for y in (0,1,62,63)]+[(x,y) for x in (0,1,62,63) for y in range(64)]:
            assert image.getpixel(p)[3]==0,name
        bounds=image.getchannel('A').point(lambda a:255 if a>64 else 0).getbbox()
        assert bounds and 6<=bounds[0]<bounds[2]<=58 and 6<=bounds[1]<bounds[3]<=58,name


def test_shared_aliases_and_frozen_paths(monkeypatch,tmp_path):
    for name,target in ALIASES.items(): assert Path(asset_path(name+'.png')).name==target+'.png'
    assert Path(asset_path('windows-explorer.svg')).parent.name=='icons'
    assert Path(asset_path('wwrecorder.png')).parent.name=='icons'
    import sys
    root=tmp_path/'icons/modern';root.mkdir(parents=True)
    (root/'play.png').write_bytes(b'placeholder')
    monkeypatch.setattr(sys,'_MEIPASS',str(tmp_path),raising=False)
    assert asset_path('ve_play.png')==str(root/'play.png')


def test_wordmark_visible_art_fills_its_declared_height(app):
    pixmap=wordmark_pixmap(24)
    assert pixmap.height()==24 and pixmap.width()>130
    image=pixmap.toImage()
    rows=[y for y in range(image.height()) if any(image.pixelColor(x,y).alpha()>128 for x in range(image.width()))]
    assert max(rows)-min(rows)>=22


def test_annotation_buttons_keep_active_icons_and_disable_visually(app):
    button=_AnnotationToolBtn('pencil.png','Pencil',size=34,icon_size=18)
    active=button.icon().cacheKey()
    assert button.iconSize().width()>=22
    assert 'background: #202633' in button.styleSheet()
    button.set_available(False)
    assert button.isEnabled() and button.icon().cacheKey()!=active
    button.set_available(True)
    assert button.icon().cacheKey()==active
    button.close()


def test_processing_is_indeterminate_and_stops_animation_when_hidden(app):
    popup=ProcessingNotice();popup.show_saving(QPoint(20,20));app.processEvents()
    before=popup._activity._angle
    QTest.qWait(100)
    assert popup._activity._angle!=before and popup._activity._timer.isActive()
    assert popup._status_lbl.text()=='Finishing your recording'
    assert '%' not in popup._status_lbl.text() and 'Gallery' in popup._message.text()
    assert not hasattr(popup,'_movie')
    popup._btn_hide.click();app.processEvents()
    assert not popup.isVisible() and not popup._activity._timer.isActive()
    popup.show_saving();app.processEvents();assert popup._activity._timer.isActive()
    popup.close();app.processEvents();assert not popup._activity._timer.isActive()


def test_processing_notification_respects_negative_monitor_origin(app,monkeypatch):
    bounds=QRect(-1280,-200,1280,720)
    class Screen:
        def availableGeometry(self):return bounds
    monkeypatch.setattr(QApplication,'screenAt',lambda point:Screen())
    popup=ProcessingNotice();popup.show_saving(QPoint(-600,40));app.processEvents()
    assert bounds.contains(popup.geometry())
    popup.close()


def test_gallery_processing_uses_same_live_indicator(app,tmp_path,monkeypatch):
    monkeypatch.setattr(RecentFilesSidebar,'_load_files',lambda self:None)
    panel=RecentFilesSidebar(str(tmp_path),close_on_focus_loss=False)
    panel.set_processing_file('Recording.mkv');panel.show();app.processEvents()
    activity=panel._processing_widget.findChild(ActivityRing)
    assert activity is not None and activity._timer.isActive()
    panel.clear_processing_file();assert not activity._timer.isActive()
    panel.close()


@pytest.mark.parametrize('name',['text','crosshair','arrow','crop','move','resize_h','resize_v','resize_d1','resize_d2','eraser'])
def test_cursors_have_valid_hotspots_and_distinct_art(app,name):
    cursor=tool_cursor(name)
    assert not cursor.pixmap().isNull()
    assert cursor.pixmap().rect().contains(cursor.hotSpot())
    if name=='text':assert cursor.hotSpot()==QPoint(16,16)
    if name=='arrow': assert cursor.pixmap().toImage()!=tool_cursor('move').pixmap().toImage()


@pytest.mark.parametrize('tool,width',[('pencil',2),('pencil',12),('highlighter',12),('highlighter',44)])
def test_stroke_cursor_preview_is_not_clipped(app,tool,width):
    cursor=tool_cursor(tool,'#FF5264',width)
    image=cursor.pixmap().toImage();hotspot=cursor.hotSpot()
    radius=width/2
    assert hotspot.x()-radius>=1 and hotspot.y()-radius>=1
    assert hotspot.x()+radius<image.width()-1 and hotspot.y()+radius<image.height()-1
    assert image.pixelColor(hotspot).alpha()>0


@pytest.mark.parametrize('width',[720,900,1280,1440])
def test_player_groups_fit_and_resize_without_losing_actions(app,width):
    window=VideoPlayerWindow('');window.setWindowState(Qt.WindowState.WindowNoState)
    window.resize(width,640);window.show();app.processEvents();window._refresh_controls_geometry()
    assert window._player_controls_wide==(width>=1100)
    controls=window._controls_widget
    for button in (window._btn_play,window._btn_back_30,window._btn_fwd_30,window._btn_vol,window._btn_fullscreen,window._btn_screenshot,window._btn_edit):
        assert button.isVisible()
        rect=QRect(button.mapTo(controls,QPoint()),button.size())
        assert controls.rect().contains(rect),(width,button.toolTip(),rect,controls.rect())
        assert not button.icon().isNull()
    for group in (window._player_left,window._player_transport,window._player_audio,window._player_file_actions):
        assert controls.rect().contains(QRect(group.mapTo(controls,QPoint()),group.size()))
    window.close();app.processEvents()


def test_player_jump_buttons_keep_correct_behavior_with_new_art(app):
    window=VideoPlayerWindow('');values=[]
    window._seek_relative=lambda delta:values.append(delta)
    window._btn_back_30.click();window._btn_fwd_30.click()
    assert values==[-30000,30000]
    assert window._btn_back_30.icon().pixmap(24,24).toImage()!=window._btn_fwd_30.icon().pixmap(24,24).toImage()
    window.close();app.processEvents()


@pytest.mark.parametrize('size',[16,24,32,44,48,50,64,96,150,256])
def test_taskbar_and_msix_variants_are_centered_and_clean(size):
    import importlib.util
    spec=importlib.util.spec_from_file_location('icon_builder',ROOT/'packaging/shared/build_icon_assets.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    im=module.render_icon(Image.open(ROOT/'packaging/shared/icon-source.png'),size)
    bounds=im.getchannel('A').point(lambda a:255 if a>=100 else 0).getbbox()
    l,t,r,b=bounds
    assert abs(l-(size-r))<=1 and abs(t-(size-b))<=1
    assert im.getpixel((0,0))==(0,0,0,0) and im.getpixel((size-1,size-1))==(0,0,0,0)
    assert im.getpixel((size//2,size//2))[3]==255


def test_editor_keeps_transport_and_file_actions_available(app,monkeypatch):
    monkeypatch.setattr(VideoPlayerWindow,'_extract_thumbnails',lambda self:None)
    window=VideoPlayerWindow('');window.setWindowState(Qt.WindowState.WindowNoState)
    window.resize(900,700);window.show();window._toggle_edit_mode();app.processEvents()
    assert window._edit_mode and window._btn_play.isVisible() and window._btn_vol.isVisible()
    assert window._btn_edit.isVisible() and window._btn_screenshot.isVisible()
    assert all(not w.isVisible() for w in window._playback_only_widgets)
    assert not window._btn_save_as.icon().isNull()
    window._close_ready=True;window.close();app.processEvents()
