import os,time
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import pytest
from PyQt6.QtWidgets import QApplication,QBoxLayout
from PyQt6.QtCore import QRect,QPointF,QEvent,Qt
from PyQt6.QtGui import QImage,QColor,QMouseEvent
from dock_widget import SidebarPanel,SettingsSidebar,RecentFilesSidebar,_FileRow

@pytest.fixture(scope='module')
def app():return QApplication.instance() or QApplication([])

@pytest.mark.parametrize('edge',['left','right','top','bottom'])
@pytest.mark.parametrize('screen',[QRect(0,0,1366,720),QRect(-1600,-900,1600,850)])
def test_panel_geometry_animation_and_resize_edge(app,edge,screen,monkeypatch):
    monkeypatch.setattr(SidebarPanel,'_panel_screen_geo',lambda self:screen)
    panel=SidebarPanel(edge,False)
    panel._position_sidebar()
    rect=panel.geometry()
    assert screen.contains(rect)
    if edge in ('top','bottom'):
        assert rect.width()==screen.width() and rect.height()<screen.height()
        pos=panel.rect().bottomLeft() if edge=='top' else panel.rect().topLeft()
        assert panel._is_on_resize_edge(pos)
        hidden=panel._hidden_rect(rect)
        assert not hidden.intersects(screen)
    else:assert rect.height()==screen.height() and rect.width()<screen.width()
    panel.open_panel()
    assert panel._anim.endValue()==rect
    panel._anim.stop();panel.setGeometry(rect)
    panel.close_panel(False)
    assert not panel.isVisible()
    panel.close()


def test_settings_reorientation_preserves_pending_edits(app):
    panel=SettingsSidebar({'dock_edge':'right','output_folder':'original'})
    panel._edt_folder.setText('unsaved folder')
    panel._edt_hotkey.setText('<ctrl>+<alt>+r')
    panel.set_panel_edge('bottom')
    assert sum(column.count() for column in panel._settings_columns)==5
    assert panel._settings_actions_layout.direction()==QBoxLayout.Direction.LeftToRight
    assert panel._edt_folder.text()=='unsaved folder' and panel._btn_save.isEnabled()
    panel.set_panel_edge('left')
    assert sum(column.count() for column in panel._settings_columns)==0
    assert panel._edt_hotkey.text()=='<ctrl>+<alt>+r'
    assert panel._settings_actions_layout.direction()==QBoxLayout.Direction.TopToBottom
    panel.close()


@pytest.mark.parametrize('edge',['top','bottom','left','right'])
def test_capture_grid_search_and_processing_keep_all_actions(app,tmp_path,edge,monkeypatch):
    monkeypatch.setattr(RecentFilesSidebar,'_load_files',lambda self:None)
    paths=[]
    for i in range(8):
        path=tmp_path/f'capture_{i}.png'
        image=QImage(32,32,QImage.Format.Format_RGB32);image.fill(QColor('red'));image.save(str(path))
        paths.append((path,time.time()))
    panel=RecentFilesSidebar(str(tmp_path),edge=edge,close_on_focus_loss=False)
    panel._on_files_scanned(paths)
    panel.show();app.processEvents();panel._reflow_grids();app.processEvents()
    rows=[w for w in panel._iter_file_widgets() if isinstance(w,_FileRow)]
    assert len(rows)==8
    assert all(row._grid_card == (edge in ('top','bottom')) for row in rows)
    if edge in ('top','bottom'):
        grid=panel._grid_groups[0][1]
        assert grid.getItemPosition(0)[0]==grid.getItemPosition(1)[0]
        assert rows[0]._thumb.width()>150
    expected=['Open & Edit','Copy','Rename','Delete']
    assert [a.text() for a in rows[0]._build_actions_menu().actions() if not a.isSeparator()]==expected
    panel._filter_files('capture_3')
    assert sum(not row.isHidden() for row in rows)==1
    panel._filter_files('not a match')
    assert not panel._lbl_empty.isHidden()
    panel.set_processing_file('new.mkv')
    panel._filter_files('not a match')
    assert not panel._scroll.isHidden() and panel._lbl_empty.isHidden()
    panel._filter_files('')
    assert sum(not row.isHidden() for row in rows)==8
    panel.close()


@pytest.mark.parametrize('edge,dy',[('top',60),('bottom',-60)])
def test_horizontal_resize_emits_height_not_width(app,edge,dy):
    panel=SidebarPanel(edge,False);panel._position_sidebar()
    heights=[];widths=[]
    panel.height_changed.connect(heights.append);panel.width_changed.connect(widths.append)
    start=panel.height()
    panel._resizing=True;panel._resize_start_x=300;panel._resize_start_w=start
    move=QMouseEvent(QEvent.Type.MouseMove,QPointF(5,5),QPointF(200,300+dy),Qt.MouseButton.NoButton,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier)
    panel.mouseMoveEvent(move)
    release=QMouseEvent(QEvent.Type.MouseButtonRelease,QPointF(5,5),QPointF(200,300+dy),Qt.MouseButton.LeftButton,Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier)
    panel.mouseReleaseEvent(release)
    assert heights==[panel.height()] and not widths
    assert panel.height()>=start
    panel.close()

@pytest.mark.parametrize('edge',['top','bottom'])
def test_horizontal_panel_paints_and_cards_start_below_date(app,tmp_path,edge,monkeypatch):
    monkeypatch.setattr(SidebarPanel,'_panel_screen_geo',lambda self:QRect(0,0,1366,768))
    monkeypatch.setattr(RecentFilesSidebar,'_load_files',lambda self:None)
    panel=RecentFilesSidebar(str(tmp_path),edge=edge,close_on_focus_loss=False)
    paths=[]
    for i in range(12):
        path=tmp_path/f'capture{i}.png'
        image=QImage(32,32,QImage.Format.Format_RGB32);image.fill(QColor('red'));image.save(str(path))
        paths.append((path,time.time()))
    panel._on_files_scanned(paths);panel.show();app.processEvents()
    panel._reflow_grids();app.processEvents()
    group,grid=panel._grid_groups[0]
    first=group.file_rows[0]
    assert first.y()<16
    assert first._thumb.y()<16
    assert group.height()>=2*first.height()
    assert not panel.grab().isNull()
    settings=SettingsSidebar({'dock_edge':edge},edge=edge)
    settings.show();app.processEvents()
    assert not settings.grab().isNull()
    assert settings._btn_save.width()>=140
    panel.close();settings.close()
