"""Panel transitions must not move the user's saved dock or compete for geometry."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import pytest
from PyQt6.QtCore import Qt, QRect, QPoint, QPointF, QEvent, QObject, pyqtSignal
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest
from dock_widget import DockWidget, SidebarPanel, SettingsSidebar, RecentFilesSidebar, _FileRow

@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])

@pytest.mark.parametrize('edge',['top','bottom'])
def test_horizontal_settings_secondary_actions_left_save_right(app, monkeypatch, edge):
    monkeypatch.setattr(SidebarPanel,'_panel_screen_geo',lambda self:QRect(0,0,1366,768))
    panel=SettingsSidebar({'close_on_focus_loss':False},edge=edge)
    panel.show();QTest.qWait(50)
    buttons=[panel._btn_quit,panel._btn_reset,panel._btn_share,panel._btn_save]
    assert [b.x() for b in buttons]==sorted(b.x() for b in buttons)
    assert panel._btn_save.geometry().right()>=panel.width()-1-panel.layout().contentsMargins().right()
    assert panel._btn_quit.x()<=20
    panel.close()

@pytest.mark.parametrize('edge',['left','right','top','bottom'])
def test_panel_motion_hides_companion_and_restores_exact_home(app,monkeypatch,edge):
    screen=QRect(-1366,-80,1366,768)
    monkeypatch.setattr(SidebarPanel,'_panel_screen_geo',lambda self:screen)
    monkeypatch.setattr(DockWidget,'_screen_geo',lambda self:screen)
    config={'dock_edge':edge,'dock_x':-1040,'dock_y':210}
    dock=DockWidget(object(),config);dock.show();app.processEvents()
    dock._set_collapsed_geo(animate=False);original=QRect(dock.geometry());coords=(dock._dock_x,dock._dock_y)
    panel=SettingsSidebar({'close_on_focus_loss':False},edge=edge)
    panel.open_panel();dock.set_panel_anchor(panel)
    assert panel._transition_state=='opening' and not dock.isVisible()
    QTest.qWait(120)
    assert not dock.isVisible() and (dock._dock_x,dock._dock_y)==coords
    QTest.qWait(300)
    assert panel._transition_state=='open' and dock.isVisible() and dock._expanded
    assert not dock.geometry().intersects(panel.geometry())
    # Screenshot freeze temporarily collapses the dock. Reattaching the same
    # visible panel must restore its controls, even without an anchor change.
    dock.collapse_for_screenshot();dock.set_panel_anchor(panel)
    assert dock._expanded
    panel.close_panel();animation=panel._anim
    panel.close_panel();assert panel._anim is animation
    assert not dock.isVisible()
    QTest.qWait(330);dock.set_panel_anchor(None)
    assert dock.geometry()==original and (dock._dock_x,dock._dock_y)==coords
    assert config=={'dock_edge':edge,'dock_x':-1040,'dock_y':210}
    dock.close();panel.close()

@pytest.mark.parametrize('edge',['left','right','top','bottom'])
def test_reversing_close_continues_from_current_position(app,monkeypatch,edge):
    monkeypatch.setattr(SidebarPanel,'_panel_screen_geo',lambda self:QRect(0,0,1366,768))
    panel=SettingsSidebar({'close_on_focus_loss':False},edge=edge)
    panel.open_panel();QTest.qWait(380)
    panel.close_panel();QTest.qWait(90);mid=QRect(panel.geometry())
    panel.open_panel()
    assert panel._anim.startValue()==mid
    QTest.qWait(380)
    assert panel._transition_state=='open' and panel.isVisible()
    panel.close_panel(animate=False)

@pytest.mark.parametrize('edge',['left','right','top','bottom'])
def test_switching_panel_ignores_old_transition_signals(app,monkeypatch,edge):
    screen=QRect(0,0,1366,768)
    monkeypatch.setattr(SidebarPanel,'_panel_screen_geo',lambda self:screen)
    monkeypatch.setattr(DockWidget,'_screen_geo',lambda self:screen)
    dock=DockWidget(object(),{'dock_edge':edge})
    first=SettingsSidebar({'close_on_focus_loss':False},edge=edge)
    second=SettingsSidebar({'close_on_focus_loss':False},edge=edge)
    first.show();dock.set_panel_anchor(first)
    first.close_panel(animate=False)
    second.open_panel();dock.set_panel_anchor(second)
    for _ in range(60):
        if second._transition_state == 'open' and dock.isVisible():
            break
        QTest.qWait(10)
    assert dock.isVisible()
    first.closing.emit();first.opened.emit()
    assert dock.isVisible() and dock._panel_anchor is second
    second.close_panel(animate=False);dock.set_panel_anchor(None)
    dock.close();first.close();second.close()

class Screen(QObject):
    availableGeometryChanged=pyqtSignal(QRect)
    def __init__(self,rect):super().__init__();self.rect=rect
    def availableGeometry(self):return QRect(self.rect)


def test_programmatic_window_monitor_does_not_change_home_or_clamp_position(app,monkeypatch):
    home=Screen(QRect(-1600,-900,1600,860));other=Screen(QRect(0,0,1920,1080))
    monkeypatch.setattr(QApplication,'screens',lambda:[home,other])
    monkeypatch.setattr(QApplication,'primaryScreen',lambda:other)
    monkeypatch.setattr(QApplication,'screenAt',lambda point:home if home.rect.contains(point) else other)
    config={'dock_edge':'left','dock_x':-1250,'dock_y':-700}
    dock=DockWidget(object(),config)
    assert dock._dock_screen is home
    monkeypatch.setattr(dock,'screen',lambda:other)
    for _ in range(4):
        dock._set_expanded_geo(animate=False);dock._position_on_edge()
        dock.update_config(dict(config))
    assert dock._screen_geo()==home.rect
    assert dock._dock_y==-700 and dock._dock_x==-1250
    dock.close()

@pytest.mark.parametrize('edge,point', [('left',(-1600,-500)),('right',(-1,-500)),('top',(-800,-900)),('bottom',(-800,-41))])
def test_drop_centres_grabber_on_pointer_and_reload_is_stable(app,monkeypatch,edge,point):
    screen=QRect(-1600,-900,1600,860)
    monkeypatch.setattr(DockWidget,'_screen_geo',lambda self:screen)
    config={'dock_edge':'right','dock_x':-1200,'dock_y':-700}
    dock=DockWidget(object(),config);dock._is_dragging=True
    event=QMouseEvent(QEvent.Type.MouseButtonRelease,QPointF(0,0),QPointF(*point),Qt.MouseButton.LeftButton,Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier)
    dock.mouseReleaseEvent(event)
    assert dock._edge==edge
    g=dock.geometry()
    assert abs((g.center().x() if dock._horizontal else g.center().y())-(point[0] if dock._horizontal else point[1]))<=1
    reloaded=DockWidget(object(),config)
    assert reloaded.geometry()==g
    dock.close();reloaded.close()

@pytest.mark.parametrize('mode,old_width,old_height',[('Default',188,186),('Large',216,210)])
def test_smaller_grid_preserves_metadata_and_increases_capacity(app,tmp_path,monkeypatch,mode,old_width,old_height):
    width,height,_=_FileRow.grid_metrics(mode)
    assert .88<=width/old_width<=.91 and .88<=height/old_height<=.91
    path=tmp_path/'a-long-capture-file-name.png';path.write_bytes(b'x'*2048)
    row=_FileRow(str(path),mode,defer_load=True,grid=True)
    row.resize(width,height);row.show();app.processEvents()
    assert row.rect().contains(row._btn_menu.geometry())
    assert row._btn_menu.height()==26
    assert row._lbl_size_text.isVisible() and row._lbl_name.isVisible()
    assert row._lbl_name.geometry().bottom()<row._lbl_size_text.geometry().top()
    row.close()
    monkeypatch.setattr(SidebarPanel,'_panel_screen_geo',lambda self:QRect(0,0,1366,768))
    panel=RecentFilesSidebar(str(tmp_path),font_size_mode=mode,edge='top',close_on_focus_loss=False)
    panel.show();QTest.qWait(100);panel._reflow_grids()
    assert panel._grid_groups
    group,grid=panel._grid_groups[0]
    capacity=(panel._scroll.viewport().width()+8)//(width+8)
    old_capacity=min(6,(panel._scroll.viewport().width()+8)//(old_width+8))
    assert capacity>old_capacity
    assert grid.columnCount()>=capacity
    assert group.height()==height+8
    panel.close()


def test_undo_redo_assets_both_use_modern_family(app):
    from icon_theme import asset_path
    from PIL import Image
    for name in ('undo','redo'):
        path=Path(asset_path(name+'.png'))
        assert path.parent.name=='modern'
        im=Image.open(path).convert('RGBA')
        assert im.size==(64,64) and im.getpixel((0,0))[3]==0
        assert any(r>180 and r>g*1.25 and a>150 for r,g,b,a in [im.getpixel((x,y)) for y in range(64) for x in range(64)])
