"""Portable geometry and Settings tests; no native screen capture required."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import pytest
from PyQt6.QtCore import QRect, QEvent, QPointF, Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QApplication, QBoxLayout
from dock_widget import DockWidget, SettingsSidebar

@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])

@pytest.mark.parametrize('edge', ['left', 'right', 'top', 'bottom'])
@pytest.mark.parametrize('screen', [QRect(0,0,1920,1080), QRect(-1600,-900,1600,860), QRect(0,0,800,560)])
def test_dock_collapsed_expanded_and_reloaded_at_each_edge(app, edge, screen, monkeypatch):
    monkeypatch.setattr(DockWidget, "_screen_geo", lambda self: screen)
    config = {'dock_edge': 'right'}
    dock = DockWidget(object(), config)
    dock._screen_geo = lambda: screen
    dock.set_dock_edge(edge)
    dock._position_on_edge()
    horizontal = edge in ('top','bottom')
    assert dock.size().width() == (48 if horizontal else 12)
    assert screen.contains(dock.geometry())
    dock._set_expanded_geo(animate=False)
    assert screen.contains(dock.geometry())
    assert (dock.width() > dock.height()) == horizontal
    direction = QBoxLayout.Direction.LeftToRight if horizontal else QBoxLayout.Direction.TopToBottom
    assert dock._panel_layout.direction() == direction
    for button in dock._dock_buttons:
        assert dock._panel.rect().contains(button.geometry())
    dock._save_dock_position()
    again = DockWidget(object(), config)
    again._screen_geo = lambda: screen
    again._position_on_edge()
    dock._set_collapsed_geo(animate=False)
    assert again.geometry() == dock.geometry()
    assert again._edge == edge
    dock.close(); again.close()


def test_settings_selection_stays_pending_and_unrelated_updates_keep_live_mapping(app):
    config = {'dock_edge': 'right'}
    dock = DockWidget(object(), config)
    sidebar = SettingsSidebar(config)
    saved = []
    dock.position_changed.connect(lambda: saved.append(dict(config)))
    sidebar.dock_position_changed.connect(dock.set_dock_edge)
    assert [sidebar._cmb_dock_position.itemData(i) for i in range(4)] == ['left','right','top','bottom']
    sidebar._cmb_dock_position.setCurrentIndex(sidebar._cmb_dock_position.findData('bottom'))
    assert saved == []
    assert sidebar.get_config()['dock_edge'] == 'right'
    assert sidebar._btn_save.isEnabled()
    new = dict(config)
    dock.update_config(new)
    dock.set_dock_edge('left')
    assert new['dock_edge'] == 'left'
    assert dock._config is new
    dock.close(); sidebar.close()


@pytest.mark.parametrize('edge,point', [('left',(0,300)),('right',(799,300)),('top',(400,0)),('bottom',(400,599))])
def test_drag_release_snaps_to_nearest_edge_and_persists(app, edge, point):
    config = {'dock_edge': 'right'}
    dock = DockWidget(object(), config)
    dock._screen_geo = lambda: QRect(0,0,800,600)
    dock._is_dragging = True
    event = QMouseEvent(QEvent.Type.MouseButtonRelease, QPointF(0,0), QPointF(*point),
        Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
    dock.mouseReleaseEvent(event)
    assert config['dock_edge'] == edge
    assert dock._screen_geo().contains(dock.geometry())
    dock.close()


def test_invalid_edge_is_ignored_and_horizontal_sidebars_remain_usable(app):
    dock = DockWidget(object(), {'dock_edge':'right'})
    changes=[]; dock.position_changed.connect(lambda: changes.append(True))
    dock.set_dock_edge('diagonal')
    assert dock._edge == 'right' and not changes
    for edge in ('top','bottom'):
        sidebar=SettingsSidebar({'dock_edge':edge}, edge=edge)
        assert sidebar._edge == edge
        assert sidebar._cmb_dock_position.currentData() == edge
        sidebar.close()
    dock.close()


def test_horizontal_drag_updates_x_without_losing_horizontal_shape(app):
    dock=DockWidget(object(), {'dock_edge':'top','dock_x':100,'dock_y':100})
    dock._screen_geo=lambda: QRect(0,0,800,600)
    press=QMouseEvent(QEvent.Type.MouseButtonPress,QPointF(2,2),QPointF(100,0),
        Qt.MouseButton.LeftButton,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier)
    dock.mousePressEvent(press)
    move=QMouseEvent(QEvent.Type.MouseMove,QPointF(2,2),QPointF(260,0),
        Qt.MouseButton.NoButton,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier)
    dock.mouseMoveEvent(move)
    assert dock._dock_x == 260 and dock.width() == 48 and dock.height() == 12
    dock.close()


def test_unrelated_config_refresh_cannot_restore_stale_dock_coordinates(app,monkeypatch):
    monkeypatch.setattr(DockWidget,'_screen_geo',lambda self:QRect(0,0,1920,1040))
    dock=DockWidget(object(),{'dock_edge':'right','dock_x':960,'dock_y':480})
    original=dock.geometry()
    stale={'dock_edge':'right','dock_x':1872,'dock_y':992,'font_size':'Large'}
    dock.update_config(stale)
    dock._set_collapsed_geo(animate=False)
    assert dock.geometry()==original
    assert stale['dock_y']==480 and stale['dock_x']==960
    dock.close()

@pytest.mark.parametrize('interruption',['hide','move_without_button','panel','ungrab','deactivate'])
@pytest.mark.parametrize('already_dragging',[False,True])
def test_interrupted_press_does_not_turn_next_mouse_motion_into_a_drag(app,monkeypatch,interruption,already_dragging):
    monkeypatch.setattr(DockWidget,'_screen_geo',lambda self:QRect(0,0,1920,1040))
    dock=DockWidget(object(),{'dock_edge':'right','dock_x':960,'dock_y':480})
    dock.show();app.processEvents();dock._set_collapsed_geo(animate=False)
    original=(dock._dock_x,dock._dock_y,dock._edge)
    pos=dock.geometry().center()
    press=QMouseEvent(QEvent.Type.MouseButtonPress,QPointF(5,20),QPointF(pos),Qt.MouseButton.LeftButton,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier)
    dock.mousePressEvent(press)
    if already_dragging:
        move=QMouseEvent(QEvent.Type.MouseMove,QPointF(5,20),QPointF(pos.x(),pos.y()+80),Qt.MouseButton.NoButton,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier)
        dock.mouseMoveEvent(move)
        assert dock._is_dragging
    panel=None
    if interruption in ('ungrab','deactivate'):
        QApplication.sendEvent(dock,QEvent(QEvent.Type.UngrabMouse if interruption=='ungrab' else QEvent.Type.WindowDeactivate))
    elif interruption=='hide':
        dock.hide();dock.show();app.processEvents()
    elif interruption=='move_without_button':
        move=QMouseEvent(QEvent.Type.MouseMove,QPointF(5,20),QPointF(pos),Qt.MouseButton.NoButton,Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier)
        dock.mouseMoveEvent(move)
    else:
        panel=SettingsSidebar({'close_on_focus_loss':False},edge='right');panel.show();dock.set_panel_anchor(panel)
    move=QMouseEvent(QEvent.Type.MouseMove,QPointF(5,20),QPointF(1910,1025),Qt.MouseButton.NoButton,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier)
    dock.mouseMoveEvent(move)
    release=QMouseEvent(QEvent.Type.MouseButtonRelease,QPointF(5,20),QPointF(1910,1025),Qt.MouseButton.LeftButton,Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier)
    dock.mouseReleaseEvent(release)
    assert (dock._dock_x,dock._dock_y,dock._edge)==original
    if panel:panel.close();dock.set_panel_anchor(None)
    dock.close()


def test_transient_work_area_clamp_does_not_overwrite_home(app,monkeypatch):
    screen=QRect(0,0,1920,1040)
    monkeypatch.setattr(DockWidget,'_screen_geo',lambda self:QRect(screen))
    config={'dock_edge':'right','dock_x':960,'dock_y':480}
    dock=DockWidget(object(),config)
    original=dock.geometry()
    screen.setHeight(400)
    dock._on_screen_geometry_changed()
    assert screen.contains(dock.geometry())
    assert dock._dock_y==480 and config['dock_y']==480
    screen.setHeight(1040)
    dock._on_screen_geometry_changed()
    assert dock.geometry()==original
    dock.close()


def test_completed_drop_is_not_cancelled_by_reentrant_mouse_ungrab(app,monkeypatch):
    monkeypatch.setattr(DockWidget,'_screen_geo',lambda self:QRect(0,0,1920,1040))
    config={'dock_edge':'right','dock_x':960,'dock_y':480}
    dock=DockWidget(object(),config)
    dock._drag_start_x,dock._drag_start_y=960,480
    dock._drag_pos=QPointF(1910,500).toPoint();dock._is_dragging=True
    original=dock._position_on_edge
    def reposition():
        QApplication.sendEvent(dock,QEvent(QEvent.Type.UngrabMouse))
        original()
    monkeypatch.setattr(dock,'_position_on_edge',reposition)
    release=QMouseEvent(QEvent.Type.MouseButtonRelease,QPointF(5,20),QPointF(1910,700),Qt.MouseButton.LeftButton,Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier)
    dock.mouseReleaseEvent(release)
    assert config['dock_y']==676 and dock._dock_y==676
    assert dock._drag_pos is None and not dock._is_dragging
    dock.close()
