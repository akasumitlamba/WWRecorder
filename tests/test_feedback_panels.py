"""Visual/layout regressions from native desktop feedback."""
from pathlib import Path
import pytest
from PyQt6.QtCore import Qt,QEvent
from PyQt6.QtGui import QImage,QPainter,QColor,QIcon
from PyQt6.QtWidgets import QApplication,QLabel
from annotation_tool import AnnotateWindow,draw_annotation_item
from dock_widget import DockWidget,SettingsSidebar
from icon_theme import asset_path

@pytest.fixture
def app(): return QApplication.instance() or QApplication([])

@pytest.mark.parametrize('width',[700,1024,1440])
def test_image_editor_tool_and_action_groups_remain_single_row(app,tmp_path,width):
    path=tmp_path/'capture.png';image=QImage(400,250,QImage.Format.Format_RGB32);image.fill(QColor('white'));image.save(str(path))
    window=AnnotateWindow(str(path));window.resize(width,650);window.show();app.processEvents()
    try:
        for group in window._editor_top_groups:
            assert window._editor_top_layout.getItemPosition(window._editor_top_layout.indexOf(group))[0]==0
        for group in window._editor_bottom_widgets:
            assert window._editor_bottom_layout.getItemPosition(window._editor_bottom_layout.indexOf(group))[0]==0
        assert window._editor_toolbar.height()==56
        assert window._editor_bottom.height()==48
        for group in window._editor_top_groups:
            assert group.geometry().right()<=window._editor_toolbar.width()
    finally: window.close()

@pytest.mark.parametrize('edge',['top','bottom'])
def test_settings_footer_credit_next_to_save_and_uniform_selectors(app,edge):
    panel=SettingsSidebar({'dock_edge':edge},edge=edge)
    panel.resize(1366,600);panel.show();app.processEvents()
    try:
        actions=panel._settings_actions_layout
        assert actions.indexOf(panel._credit_link)+1==actions.indexOf(panel._btn_save)
        assert panel._seg_font.size()==panel._cmb_dock_position.size()
        assert panel._seg_font.size().width()==144
        assert 'border-radius: 6px' in panel._seg_font.container.styleSheet()
    finally:panel.close()


def test_dock_stop_icon_survives_hover_and_restores_camera(app):
    dock=DockWidget(object(),{})
    try:
        dock.set_recording_state(True)
        expected=QIcon(asset_path('stop.png')).pixmap(24,24).toImage()
        assert dock._btn_record.icon_normal.pixmap(24,24).toImage()==expected
        QApplication.sendEvent(dock._btn_record,QEvent(QEvent.Type.Enter))
        QApplication.sendEvent(dock._btn_record,QEvent(QEvent.Type.Leave))
        assert dock._btn_record.icon().pixmap(24,24).toImage()==expected
        dock.set_recording_state(False)
        assert dock._btn_record.icon_normal.pixmap(24,24).toImage()==QIcon(asset_path('record.png')).pixmap(24,24).toImage()
    finally:dock.close()


def test_laser_glow_is_centered_and_soft_not_offset(app):
    image=QImage(100,100,QImage.Format.Format_ARGB32_Premultiplied);image.fill(Qt.GlobalColor.transparent)
    painter=QPainter(image);painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    draw_annotation_item(painter,{'type':'laser','color':'#FF4055','width':5,'points':[(20,50),(80,50)],'opacity':1})
    painter.end()
    assert image.pixelColor(50,50).alpha()>200
    levels=[image.pixelColor(50,50+d).alpha() for d in range(10)]
    assert levels==sorted(levels,reverse=True)
    assert 0<levels[4]<levels[1] and levels[-1]==0
    assert all(abs(image.pixelColor(50,49-d).alpha()-image.pixelColor(50,50+d).alpha())<3 for d in range(8))


def test_quit_power_is_entirely_red_and_clear_uses_separate_brush(app):
    image=QImage(asset_path('power.png'))
    colors=[image.pixelColor(x,y) for x in range(image.width()) for y in range(image.height()) if image.pixelColor(x,y).alpha()>200]
    assert colors and all(c.red()>c.green()+100 and c.red()>c.blue()+100 for c in colors)
    assert asset_path('clear_brush.png')!=asset_path('delete.png')
    assert not QImage(asset_path('clear_brush.png')).isNull()


def test_generated_clear_brush_fills_toolbar_without_clipping(app):
    from annotation_tool import _AnnotationToolBtn
    button=_AnnotationToolBtn('clear_brush.png','Clear all',size=34,icon_size=22)
    assert button.iconSize().width()==28
    image=button.icon().pixmap(64,64).toImage()
    points=[(x,y) for x in range(64) for y in range(64) if image.pixelColor(x,y).alpha()>128]
    assert points
    width=max(x for x,y in points)-min(x for x,y in points)+1
    height=max(y for x,y in points)-min(y for x,y in points)+1
    assert 48<=max(width,height)<=58
    assert image.pixelColor(0,0).alpha()==0
    button.close()
