"""Popup stacking, compact settings and capture-header regressions."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from types import SimpleNamespace
import pytest
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QRect,Qt,QPoint
from PyQt6.QtTest import QTest
import ui_elements
from dock_widget import SidebarPanel,SettingsSidebar,RecentFilesSidebar,_FileRow

@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


def test_mic_popup_keeps_topmost_ownership_and_pill_resumes_after_close(app,monkeypatch):
    native=[];raised=[];excluded=[]
    monkeypatch.setattr(ui_elements,'_user32',SimpleNamespace(SetWindowPos=lambda *args:native.append(args)))
    monkeypatch.setattr(ui_elements,'_exclude_from_capture',lambda handle:excluded.append(handle))
    engine=SimpleNamespace(get_mic=lambda:False,get_system_audio=lambda:False,is_paused=lambda:False)
    pill=ui_elements.PillWidget(engine,{},pre_record=True)
    pill.show();app.processEvents()
    monkeypatch.setattr(pill,'underMouse',lambda:False)
    monkeypatch.setattr(pill,'raise_',lambda:raised.append(True))
    pill._open_microphone_menu([('usb','USB microphone')],'')
    menu=pill._mic_menu
    assert menu.isVisible()
    assert menu.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
    assert native[-1][0]==int(menu.winId()) and int(menu.winId()) in excluded
    native.clear();raised.clear()
    for _ in range(3):pill._enforce_topmost()
    assert not native and not raised and menu.isVisible()
    menu.close()
    assert pill._mic_menu is None
    pill._enforce_topmost()
    assert native[-1][0]==int(pill.winId()) and raised
    pill._stopping=True;pill.close()


@pytest.mark.parametrize('edge',['left','right','top','bottom'])
@pytest.mark.parametrize('font',['Default','Large'])
@pytest.mark.parametrize('height',[720,1040])
def test_default_settings_fit_with_advanced_expanded_and_footer_pinned(app,monkeypatch,edge,font,height):
    monkeypatch.setattr(SidebarPanel,'_panel_screen_geo',lambda self:QRect(0,0,1366,height))
    panel=SettingsSidebar({'font_size':font,'close_on_focus_loss':False},edge=edge)
    panel.show();app.processEvents()
    QTest.qWait(250);app.processEvents()
    assert panel._settings_scroll.verticalScrollBar().maximum()==0
    assert panel._settings_scroll.widget().width() <= panel._settings_scroll.viewport().width()
    assert not panel._settings_scroll.isAncestorOf(panel._btn_save)
    for control in (panel._btn_save,panel._btn_quit,panel._btn_reset,panel._chk_developer_mode):
        assert panel.rect().contains(QRect(control.mapTo(panel,QPoint()),control.size()))
    panel.close()


@pytest.mark.parametrize('edge',['right','bottom'])
def test_capture_header_groups_folder_search_settings_and_preserves_actions(app,tmp_path,monkeypatch,edge):
    monkeypatch.setattr(RecentFilesSidebar,'_load_files',lambda self:None)
    opened=[];settings=[]
    monkeypatch.setattr(RecentFilesSidebar,'_open_folder',lambda self:opened.append(True))
    panel=RecentFilesSidebar(str(tmp_path),edge=edge,close_on_focus_loss=False)
    panel.settings_requested.connect(lambda:settings.append(True))
    panel.show();app.processEvents()
    buttons=(panel._btn_folder,panel._btn_search,panel._btn_settings)
    assert len({button.mapTo(panel,QPoint()).y() for button in buttons})==1
    assert all(button.width()==32 and not button.text() for button in buttons)
    assert not panel._btn_folder.icon().isNull()
    panel._btn_folder.click();panel._btn_settings.click()
    assert opened and settings
    panel._btn_search.click();assert not panel._edt_search.isHidden()
    panel._btn_search.click();assert panel._edt_search.isHidden()
    panel.close()


@pytest.mark.parametrize('font,height,thumb',[('Default',167,216),('Large',189,240)])
def test_compact_grid_card_keeps_thumbnail_filename_and_menu_inside(app,tmp_path,font,height,thumb):
    row=_FileRow(str(tmp_path/'capture.mp4'),font,defer_load=True,grid=True)
    row.resize(228 if font=='Default' else 252,height);row.show();app.processEvents()
    assert row.height()==height and row._thumb.width()==row.width()-12
    for control in (row._thumb,row._lbl_name,row._btn_menu):
        assert row.rect().contains(QRect(control.mapTo(row,QPoint()),control.size()))
    assert [a.text() for a in row._build_actions_menu().actions() if not a.isSeparator()]==['Play','Edit','Copy','Rename','Delete']
    row.close()


def test_microphone_hint_is_not_a_device_and_selection_fade_is_stable(app,monkeypatch):
    from PyQt6.QtWidgets import QWidgetAction
    monkeypatch.setattr(ui_elements,'_exclude_from_capture',lambda handle:None)
    engine=SimpleNamespace(get_mic=lambda:False,get_system_audio=lambda:False,is_paused=lambda:False,
        _microphone_id='usb',set_microphone=lambda *args:None)
    pill=ui_elements.PillWidget(engine,{},pre_record=True);pill.show();app.processEvents()
    long_name='Very long microphone name '*8
    pill._open_microphone_menu([('usb','USB microphone'),('bt',long_name)],'')
    menu=pill._mic_menu;app.processEvents();position=menu.pos()
    choices=[a for a in menu.actions() if a.isCheckable()]
    assert len(choices)==3 and choices[1].isChecked()
    assert choices[2].toolTip()==long_name and len(choices[2].text())<len(long_name)
    hint=[a for a in menu.actions() if isinstance(a,QWidgetAction)]
    assert len(hint)==1 and not hint[0].isEnabled() and not hint[0].isCheckable()
    assert 'Bluetooth mic' in hint[0].defaultWidget().text()
    assert '10px' in hint[0].defaultWidget().styleSheet()
    assert pill._btn_mic_menu.property('menuOpen') is True
    QTest.qWait(160)
    assert menu._fade.duration()==120 and menu.windowOpacity()==1
    assert menu.pos()==position
    choices[2].trigger()
    assert choices[2].isChecked() and not choices[1].isChecked()
    menu.close()
    assert pill._btn_mic_menu.property('menuOpen') is False
    pill._stopping=True;pill.close()


def test_settings_small_screen_keeps_actions_reachable_while_content_scrolls(app,monkeypatch):
    monkeypatch.setattr(SidebarPanel,'_panel_screen_geo',lambda self:QRect(0,0,1024,440))
    panel=SettingsSidebar({'close_on_focus_loss':False},edge='right')
    panel.show();QTest.qWait(250);app.processEvents()
    assert panel._settings_scroll.verticalScrollBar().maximum()>0
    for control in (panel._btn_save,panel._btn_quit):
        assert panel.rect().contains(QRect(control.mapTo(panel,QPoint()),control.size()))
    assert 'QComboBox::drop-down' in panel._cmb_dock_position.styleSheet()
    assert 'QComboBox::down-arrow' in panel._cmb_dock_position.styleSheet()
    assert panel._cmb_dock_position.count()==4
    panel.close()


def test_switching_file_menus_clears_previous_card_button_and_native_hover(app,tmp_path):
    from PyQt6.QtWidgets import QWidget,QHBoxLayout
    owner=QWidget();layout=QHBoxLayout(owner)
    rows=[_FileRow(str(tmp_path/name),defer_load=True,grid=True) for name in ('photo.png','video.mp4')]
    for row in rows:layout.addWidget(row)
    owner.show();app.processEvents()
    first,second=rows
    first._show_actions_menu()
    first_menu=first._actions_menu
    first.setAttribute(Qt.WidgetAttribute.WA_UnderMouse,True)
    first._btn_menu.setAttribute(Qt.WidgetAttribute.WA_UnderMouse,True)
    first._btn_menu.setDown(True)
    assert first.property('menuOpen') is True
    second._show_actions_menu()
    assert not first_menu.isVisible()
    assert first.property('menuOpen') is False and first._btn_menu.property('menuOpen') is False
    assert not first.underMouse() and not first._btn_menu.underMouse() and not first._btn_menu.isDown()
    assert second.property('menuOpen') is True and owner._active_file_menu is second._actions_menu
    second._actions_menu.close()
    assert owner._active_file_menu is None and second.property('menuOpen') is False
    owner.close()

@pytest.mark.parametrize('font',['Default','Large'])
def test_compact_shortcut_keycaps_keep_readable_text_width(app,font):
    from PyQt6.QtWidgets import QLabel
    panel=SettingsSidebar({'font_size':font,'close_on_focus_loss':False,
        'hotkey':'<shift>+<backspace>','hotkey_screenshot':'<ctrl>+<alt>+c'})
    panel.show();app.processEvents()
    title=panel._advanced_section.lbl_title
    assert title.width()>=title.fontMetrics().horizontalAdvance(title.text())
    for field in (panel._edt_hotkey,panel._edt_screenshot):
        for label in field._keys_container.findChildren(QLabel):
            assert label.width()>=label.fontMetrics().horizontalAdvance(label.text())
    panel.close()


def test_refresh_deleting_open_menu_row_releases_panel_owner(app,tmp_path):
    from PyQt6.QtWidgets import QWidget,QVBoxLayout
    from PyQt6.QtCore import QCoreApplication,QEvent
    owner=QWidget();layout=QVBoxLayout(owner)
    first=_FileRow(str(tmp_path/'photo.png'),defer_load=True,grid=True)
    second=_FileRow(str(tmp_path/'video.mp4'),defer_load=True,grid=True)
    layout.addWidget(first);layout.addWidget(second);owner.show();app.processEvents()
    first._show_actions_menu();first.deleteLater()
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    assert owner._active_file_menu is None
    second._show_actions_menu()
    assert second._actions_menu.isVisible()
    second._actions_menu.close();owner.close()
