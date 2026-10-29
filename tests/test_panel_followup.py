"""Draft settings, attached dock controls and selection paint regressions."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import sys
from types import SimpleNamespace
import pytest
from PyQt6.QtWidgets import QApplication, QBoxLayout, QPushButton
from PyQt6.QtCore import QRect, QPoint
from PyQt6.QtGui import QColor
from PyQt6.QtTest import QTest
from dock_widget import SettingsSidebar, RecentFilesSidebar, DockWidget, SidebarPanel
from ui_elements import SelectionOverlay

@pytest.fixture(scope='module')
def app(): return QApplication.instance() or QApplication([])

def test_settings_drafts_save_once_and_reset_is_pending(app, monkeypatch):
    monkeypatch.setitem(sys.modules,'main',SimpleNamespace(validate_hotkey=lambda v:(True,'')))
    config={'dock_edge':'right','font_size':'Default','hotkey':'<shift>+<home>','hotkey_screenshot':'<ctrl>+c'}
    panel=SettingsSidebar(config,default_config=config)
    saved=[]; moved=[]
    panel.settings_saved.connect(lambda value:saved.append(dict(value)))
    panel.dock_position_changed.connect(moved.append)
    panel._cmb_dock_position.setCurrentIndex(2)
    panel._seg_font.setValue('Large');panel._on_font_toggle_changed('Large')
    assert config['dock_edge']=='right' and panel.get_config()['font_size']=='Default'
    assert not saved and not moved and panel._btn_save.isEnabled()
    panel._save()
    assert len(saved)==1 and saved[0]['dock_edge']=='top' and saved[0]['font_size']=='Large'
    assert not panel._btn_save.isEnabled()
    panel._reset()
    assert len(saved)==1 and panel.get_config()['dock_edge']=='top'
    assert panel._cmb_dock_position.currentData()=='right' and panel._btn_save.isEnabled()
    panel.close()

@pytest.mark.parametrize('edge',['left','right','top','bottom'])
def test_external_dock_visible_aligned_and_pinned(app,monkeypatch,edge):
    screen=QRect(-1366,0,1366,768)
    monkeypatch.setattr(SidebarPanel,'_panel_screen_geo',lambda self:screen)
    monkeypatch.setattr(DockWidget,'_screen_geo',lambda self:screen)
    dock=DockWidget(object(),{'dock_edge':edge})
    panel=SettingsSidebar({'dock_edge':edge,'close_on_focus_loss':False},edge=edge)
    panel.show();QTest.qWait(80);dock.set_panel_anchor(panel);app.processEvents()
    seen=[];dock.screenshot_requested.connect(lambda:seen.append(True))
    dock._dock_buttons[0].click();assert seen==[True]
    assert dock.isVisible() and dock._expanded
    assert not dock.geometry().intersects(panel.geometry())
    assert screen.contains(dock.geometry())
    p=panel.geometry();d=dock.geometry()
    if edge=='left': assert d.left()==p.right()+1
    if edge=='right': assert d.right()==p.left()-1
    if edge=='top': assert d.top()==p.bottom()+1
    if edge=='bottom': assert d.bottom()==p.top()-1
    dock._collapse();assert dock._expanded
    for button in dock._dock_buttons:
        assert button.isVisible()
        assert not panel.isAncestorOf(button)
    panel.close();dock.set_panel_anchor(None)
    assert not dock._expanded
    dock.close()

def test_settings_gallery_action_has_plain_folder(app):
    panel=SettingsSidebar({})
    button=next(b for b in panel.findChildren(QPushButton) if b.toolTip()=='Open Recent Files')
    assert not button.icon().isNull()
    assert button.icon().pixmap(20,20).toImage()!=RecentFilesSidebar._explorer_icon().pixmap(20,20).toImage()
    panel.close()

@pytest.mark.parametrize('state',['SELECTED','MOVING','RESIZING'])
def test_selected_recording_has_no_dark_band(app,state):
    overlay=SelectionOverlay(mode='record');overlay.resize(500,350)
    overlay.rect_obj=QRect(100,90,200,150);overlay.state=state
    overlay._hint.hide();image=overlay.grab().toImage()
    assert image.pixelColor(97,140).alpha()==0
    assert image.pixelColor(120,89).alpha()==0
    overlay._cancel_emitted=True;overlay.close()

@pytest.mark.parametrize('edge',['left','right','top','bottom'])
def test_external_dock_follows_panel_resize_without_header_changes(app,monkeypatch,edge):
    screen=QRect(0,0,1366,768)
    monkeypatch.setattr(SidebarPanel,'_panel_screen_geo',lambda self:screen)
    monkeypatch.setattr(DockWidget,'_screen_geo',lambda self:screen)
    dock=DockWidget(object(),{'dock_edge':edge})
    panel=SettingsSidebar({'dock_edge':edge,'close_on_focus_loss':False},edge=edge)
    panel.show();QTest.qWait(100);dock.set_panel_anchor(panel)
    assert panel._heading_container.height() >= 44
    before_heading_height = panel._heading_container.height()
    if edge in ('top','bottom'):
        panel._panel_height=panel.height()+20
        panel._position_sidebar(height=panel._panel_height)
    else: panel._position_sidebar(width=panel.width()+20)
    app.processEvents()
    assert panel._heading_container.height() == before_heading_height
    assert not dock.geometry().intersects(panel.geometry())
    if edge in ('top','bottom'): assert abs(dock.geometry().center().x()-panel.geometry().center().x())<=1
    else: assert abs(dock.geometry().center().y()-panel.geometry().center().y())<=1
    panel.close();dock.set_panel_anchor(None);dock.close()


def test_settings_action_icon_padding(app):
    from pathlib import Path
    from PIL import Image
    for name in ('reset','share','power'):
        from icon_theme import asset_path
        im=Image.open(asset_path(f'panel-{name}.png')).convert('RGBA')
        assert im.size==(64,64)
        # All sides must retain a transparent guard band when Qt scales them.
        for x,y in [(0,0),(63,0),(0,63),(63,63)]: assert im.getpixel((x,y))[3]==0
    panel=SettingsSidebar({})
    for button in (panel._btn_reset,panel._btn_share,panel._btn_quit): assert not button.icon().isNull()
    panel.close()

@pytest.mark.parametrize('mode',['Default','Large'])
def test_horizontal_sections_end_together_without_blank_capture_card(app,monkeypatch,mode):
    monkeypatch.setattr(SidebarPanel,'_panel_screen_geo',lambda self:QRect(0,0,1366,768))
    panel=SettingsSidebar({'font_size':mode,'close_on_focus_loss':False},edge='top')
    panel.show();QTest.qWait(100)
    capture,dock,audio,shortcuts,advanced=panel._settings_cards
    assert abs(shortcuts.geometry().bottom()-advanced.geometry().bottom())<=2
    assert capture.height()<=capture._card_layout.minimumSize().height()+2
    panel.close()


def test_saved_edge_reaches_coordinator_without_overwriting_live_mic(app,tmp_path):
    import ast
    from pathlib import Path
    tree=ast.parse((Path(__file__).resolve().parents[1]/'app/main.py').read_text(encoding='utf-8'))
    cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='WWRecorderApp')
    method=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='_on_settings_saved')
    defaults={'microphone_id':'','microphone_name':'','dock_x':-1,'dock_y':-1,'panel_height':0,'hotkey':'x','hotkey_screenshot':'y'}
    namespace={'DEFAULT_CONFIG':defaults,'Path':Path}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[method],type_ignores=[])),'settings-coordinator','exec'),namespace)
    config={**defaults,'dock_edge':'right','font_size':'Default','output_folder':str(tmp_path),'start_on_boot':False,'microphone_id':'live-usb','hotkey':'x','hotkey_screenshot':'y'}
    dock=DockWidget(object(),config)
    changes=[]
    owner=SimpleNamespace(config=config,dock=dock,_recent_panel=None,_settings_sidebar=None,_save_config=lambda:None,_on_dock_position_changed=lambda:changes.append(dock._edge))
    submitted={**config,'dock_edge':'bottom','microphone_id':'stale'}
    namespace['_on_settings_saved'](owner,submitted)
    assert owner.config['dock_edge']=='bottom' and dock._edge=='bottom'
    assert changes==['bottom'] and owner.config['microphone_id']=='live-usb'
    dock.close()

@pytest.mark.parametrize('edge', ['left', 'right', 'top', 'bottom'])
@pytest.mark.parametrize('kind', ['gallery', 'settings'])
def test_header_brand_and_label_are_compact_only_on_vertical(app, tmp_path, edge, kind):
    from PyQt6.QtWidgets import QLabel
    panel = (SettingsSidebar({}, edge=edge) if kind == 'settings'
             else RecentFilesSidebar(str(tmp_path), edge=edge))
    labels = panel._heading_container.findChildren(QLabel)
    titles = [label for label in labels if label.text() in ('Recent Files', 'Settings')]
    assert len(titles) == (1 if edge in ('top', 'bottom') else 0)
    if titles: assert '24px' in titles[0].styleSheet()
    height = 24 if edge in ('top', 'bottom') else 18
    brand = next(label for label in labels if not label.pixmap().isNull())
    assert brand.pixmap().height() == height
    panel.close()
