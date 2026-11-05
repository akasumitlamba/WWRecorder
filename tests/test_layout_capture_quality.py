"""Screen-efficient panels, immutable selection and pixel-faithful annotations."""
import os,time
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from types import SimpleNamespace
import numpy as np
import pytest
from PIL import Image
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QRect,QPoint,QPointF,QEvent,Qt
from PyQt6.QtGui import QImage,QColor,QMouseEvent,QTextCursor,QPainter
from PyQt6.QtTest import QTest
from ui_elements import SelectionOverlay
from annotation_tool import AnnotationCanvas,_DrawingArea,AnnotationPill,draw_annotation_item
from dock_widget import SidebarPanel,SettingsSidebar,RecentFilesSidebar,_FileRow
from capture_frames import capture_bgra_frame
from display_geometry import ScreenTransform,build_capture_plan,compose_frozen_desktop

@pytest.fixture(scope='module')
def app():return QApplication.instance() or QApplication([])


def event(kind,pos,button=Qt.MouseButton.NoButton,buttons=Qt.MouseButton.NoButton):
    return QMouseEvent(kind,QPointF(*pos),QPointF(*pos),button,buttons,Qt.KeyboardModifier.NoModifier)


def test_selected_record_region_is_click_through_and_cannot_follow_hover(app):
    overlay=SelectionOverlay();overlay.setGeometry(-800,0,800,600)
    overlay.rect_obj=QRect(100,100,300,200);overlay.state='SELECTED';overlay._apply_selection_mask()
    original=QRect(overlay.rect_obj)
    assert not overlay.mask().contains(QPoint(200,150))
    assert not overlay.mask().contains(QPoint(20,20))
    assert overlay.mask().contains(QPoint(100,100))
    overlay.mousePressEvent(event(QEvent.Type.MouseButtonPress,(200,150),Qt.MouseButton.LeftButton,Qt.MouseButton.LeftButton))
    assert overlay.state=='SELECTED'
    for pos in ((300,200),(450,300),(40,50)):
        overlay.mouseMoveEvent(event(QEvent.Type.MouseMove,pos))
    assert overlay.rect_obj==original
    # Simulate a lost native release while an outline drag owns the pointer.
    overlay.state='MOVING';overlay._origin=QPoint(100,100)
    overlay.mouseMoveEvent(event(QEvent.Type.MouseMove,(500,400)))
    assert overlay.state=='SELECTED' and overlay.rect_obj==original
    overlay.close()


def test_selection_border_adjustment_requires_left_button_and_updates_input_mask(app):
    overlay=SelectionOverlay();overlay.setGeometry(0,0,800,600)
    overlay.rect_obj=QRect(100,100,300,200);overlay.state='SELECTED'
    overlay.mousePressEvent(event(QEvent.Type.MouseButtonPress,(100,100),Qt.MouseButton.LeftButton,Qt.MouseButton.LeftButton))
    assert overlay.state=='RESIZING'
    overlay.mouseMoveEvent(event(QEvent.Type.MouseMove,(80,90),buttons=Qt.MouseButton.LeftButton))
    assert overlay.rect_obj.topLeft()==QPoint(80,90) and overlay.mask().contains(QPoint(80,90))
    overlay.mouseReleaseEvent(event(QEvent.Type.MouseButtonRelease,(80,90),Qt.MouseButton.LeftButton))
    assert overlay.state=='SELECTED'
    overlay.close()


@pytest.mark.parametrize('edge',['top','bottom','right'])
def test_tip_is_exactly_one_line_with_four_pixels_and_horizontal_right_alignment(app,tmp_path,monkeypatch,edge):
    monkeypatch.setattr(RecentFilesSidebar,'_load_files',lambda self:None)
    panel=RecentFilesSidebar(str(tmp_path),edge=edge,close_on_focus_loss=False);panel.show();app.processEvents()
    panel._tips=['A very long tip '*40];panel._tip_index=0;panel._update_tip_text();app.processEvents()
    tip=panel._lbl_drag_info
    assert not tip.wordWrap() and tip.height()==tip.fontMetrics().height()+4
    assert tip.minimumHeight()==tip.maximumHeight()
    assert len(tip.text())<len(tip.toolTip())
    if edge in ('top','bottom'):
        assert tip.alignment() & Qt.AlignmentFlag.AlignRight
        assert tip.mapTo(panel,QPoint()).x()>=panel.width()-400
        screen=panel._panel_screen_geo()
        assert (panel.geometry().top()-screen.top() if edge=='top' else screen.bottom()-panel.geometry().bottom())==0
    panel.close()


def test_vertical_advanced_preserves_comfortable_spacing_and_hidden_scroll(app, monkeypatch):
    monkeypatch.setattr(SidebarPanel, '_panel_screen_geo', lambda self: QRect(0,0,1366,720))
    panel = SettingsSidebar({'close_on_focus_loss':False})
    panel.show();QTest.qWait(30);app.processEvents()
    before = [(card._card_layout.contentsMargins().top(),card._card_layout.spacing()) for card in panel._settings_cards]
    assert not panel._advanced_section._expanded
    panel._advanced_section.toggle();QTest.qWait(260);app.processEvents()
    assert [(card._card_layout.contentsMargins().top(),card._card_layout.spacing()) for card in panel._settings_cards] == before
    assert panel._settings_scroll.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    assert panel._settings_scroll.verticalScrollBar().maximum() > 0
    panel._settings_scroll.verticalScrollBar().setValue(panel._settings_scroll.verticalScrollBar().maximum())
    assert panel._settings_scroll.verticalScrollBar().value() > 0
    panel.close()


def test_drag_setting_is_remembered_and_hides_only_when_enabled(app,tmp_path,monkeypatch):
    monkeypatch.setattr(RecentFilesSidebar,'_load_files',lambda self:None)
    settings=SettingsSidebar({'close_on_focus_loss':False,'hide_panel_on_drag':False})
    settings._chk_hide_drag.setChecked(True)
    import sys
    # Unit-isolate the entrypoint's already-tested hotkey validator from WinRT.
    monkeypatch.setitem(sys.modules, 'main', SimpleNamespace(validate_hotkey=lambda value:(True,'')))
    settings._save()
    assert settings.get_config()['hide_panel_on_drag'] is True
    for enabled in (False,True):
        panel=RecentFilesSidebar(str(tmp_path),hide_on_drag=enabled,close_on_focus_loss=False)
        panel.show();app.processEvents();panel._on_file_drag_started();app.processEvents()
        assert panel.isVisible() is not enabled
        panel.close()
    settings.close()


@pytest.mark.parametrize('font,height,thumb',[('Default',167,127),('Large',189,149)])
def test_grid_gives_space_to_thumbnail_and_one_menu_height_caption(app,tmp_path,font,height,thumb):
    (tmp_path/'recording.mp4').write_bytes(b'fixture')
    row=_FileRow(str(tmp_path/'recording.mp4'),font,defer_load=True,grid=True)
    row.resize(228 if font=='Default' else 252,height);row.show();app.processEvents()
    assert row._thumb.height()==thumb
    assert row._lbl_name.height()<=row._btn_menu.height()==26
    assert '10px' in row._lbl_name.styleSheet() if font=='Default' else '11px' in row._lbl_name.styleSheet()
    assert row._lbl_date.isHidden() and not row._lbl_size_text.isHidden()
    row.close()


@pytest.mark.parametrize('orientation',['vertical','horizontal'])
def test_annotation_toolbar_scales_both_dimensions_and_preserves_tools(app,orientation):
    pill=AnnotationPill();sizes=[]
    for length in (600,720,1040):
        rect=QRect(-length,0,length,length)
        pill._apply_orientation(orientation,rect);pill._dock_to_edge('left' if orientation=='vertical' else 'top',rect)
        assert rect.contains(pill.geometry())
        sizes.append((pill._btn_pin.width(),pill.width() if orientation=='vertical' else pill.height()))
    assert sizes[0][0]<sizes[-1][0] and sizes[0][1]<sizes[-1][1]
    assert 'laser' in pill._tool_btns and pill._active_tool=='pencil'
    pill.close()


def red_bounds(image):
    image=image.convertToFormat(QImage.Format.Format_RGBA8888)
    bits=image.bits();bits.setsize(image.sizeInBytes())
    rgba=np.frombuffer(bits,np.uint8).reshape(image.height(),image.bytesPerLine())[:,:image.width()*4].reshape(image.height(),image.width(),4)
    ys,xs=np.where((rgba[:,:,0]>170)&(rgba[:,:,1]<100)&(rgba[:,:,2]<100)&(rgba[:,:,3]>100))
    assert len(xs)
    return np.array([xs.min(),ys.min(),xs.max(),ys.max()])


@pytest.mark.parametrize('text',['Hello text','First line\nSecond line'])
@pytest.mark.parametrize('kind,scale',[('live',1),('image',.55),('image',1),('image',1.33)])
def test_typing_origin_size_and_rendered_glyphs_do_not_jump_on_commit(app,kind,scale,text):
    if kind=='live':canvas=AnnotationCanvas()
    else:
        original=QImage(800,600,QImage.Format.Format_RGB32);original.fill(QColor('white'));canvas=_DrawingArea(original)
    canvas.resize(900,700);canvas.show();app.processEvents();canvas._color=QColor('#FF0000')
    if kind=='image':canvas._scale=scale;canvas._offset_x=20;canvas._offset_y=30
    canvas._start_text_input((120,140) if kind=='live' else QPointF(120,140))
    canvas._text_edit.setPlainText(text)
    cursor=canvas._text_edit.textCursor();cursor.movePosition(QTextCursor.MoveOperation.Start);canvas._text_edit.setTextCursor(cursor)
    canvas._text_edit.setCursorWidth(0);app.processEvents()
    viewport=canvas._text_edit.viewport();origin=viewport.mapTo(canvas,QPoint())
    dpr=canvas.devicePixelRatioF()
    bounds_before=red_bounds(viewport.grab().toImage())+np.rint(np.array([origin.x(),origin.y(),origin.x(),origin.y()])*dpr).astype(int)
    caret=viewport.mapTo(canvas,canvas._text_edit.cursorRect().topLeft())
    expected=QPoint(120,140) if kind=='live' else QPoint(int(120*scale+20),int(140*scale+30))
    caret.setY(caret.y()+round(canvas._text_edit.cursorRect().height()/2))
    assert (caret-expected).manhattanLength()<=1
    pending_origin=canvas._text_pos
    assert abs(canvas._text_edit.font().pointSizeF()-16*scale)<.05
    canvas._commit_text();item=next(item for item in canvas._items if item.get('type')=='text')
    assert item['start']==pending_origin and item['font_size']==16
    composed=QImage(round(900*dpr),round(700*dpr),QImage.Format.Format_RGB32);composed.setDevicePixelRatio(dpr);composed.fill(QColor('white'));p=QPainter(composed)
    if kind=='image':p.translate(20,30);p.scale(scale,scale)
    draw_annotation_item(p,item);p.end()
    bounds_after=red_bounds(composed)
    assert np.max(np.abs(bounds_before-bounds_after))<=2,(bounds_before,bounds_after)
    canvas.close()


def test_native_png_retains_every_pixel_at_high_dpi(tmp_path):
    rng=np.random.default_rng(3);pixels=rng.integers(0,256,(240,360,3),np.uint8)
    source=Image.fromarray(pixels)
    transform=ScreenTransform('150%',0,0,240,160,0,0,360,240)
    plan=build_capture_plan({'left':0,'top':0,'width':240,'height':160},[transform])
    result=compose_frozen_desktop(source,(0,0),plan);path=tmp_path/'capture.png';result.save(path,'PNG')
    assert result.size==(360,240) and np.array_equal(np.asarray(Image.open(path)),pixels)


def test_native_capture_fast_path_is_writable_zero_copy_and_composition_reuses_buffer():
    raw=bytearray(range(64));capture=SimpleNamespace(grab=lambda region:SimpleNamespace(raw=raw))
    segment={'src_left':-20,'src_top':0,'src_width':4,'src_height':4,'dst_left':0,'dst_top':0,'dst_width':4,'dst_height':4}
    frame=capture_bgra_frame(capture,[segment],4,4)
    frame[0,0,0]=222;assert raw[0]==222
    shifted=dict(segment,dst_left=1,dst_width=4)
    scratch=np.empty((4,6,4),np.uint8)
    composed=capture_bgra_frame(capture,[shifted],6,4,scratch)
    assert composed is scratch and np.all(composed[:,0]==0) and np.all(composed[:,5]==0)


def test_mixed_dpi_resampling_keeps_color_when_mss_alpha_is_zero():
    pixels=np.zeros((4,4,4),np.uint8);pixels[:,:,:3]=[40,120,220]
    capture=SimpleNamespace(grab=lambda region:SimpleNamespace(raw=bytearray(pixels.tobytes())))
    segment={'src_left':0,'src_top':0,'src_width':4,'src_height':4,'dst_left':0,'dst_top':0,'dst_width':6,'dst_height':6}
    composed=capture_bgra_frame(capture,[segment],6,6)
    assert np.all(composed[:,:,:3]==[40,120,220])


def test_screenshot_actual_pixels_and_fit_preserve_saved_source(app,tmp_path):
    pixels=np.zeros((480,640,3),np.uint8);pixels[:,::2]=255
    path=tmp_path/'screen.png';Image.fromarray(pixels).save(path)
    canvas=_DrawingArea(str(path));canvas.resize(320,300);canvas.show();app.processEvents()
    before=canvas._original.copy()
    canvas.view_actual_pixels()
    assert abs(canvas._scale*canvas.devicePixelRatioF()-1)<1e-6
    canvas.view_fit();assert canvas._zoom_level==1
    assert canvas.save_image()
    assert np.array_equal(np.asarray(Image.open(path)),pixels)
    assert canvas._original==before
    canvas.close()


def test_grid_columns_include_gaps_and_do_not_clip_last_card(app,tmp_path,monkeypatch):
    monkeypatch.setattr(RecentFilesSidebar,'_load_files',lambda self:None)
    monkeypatch.setattr(SidebarPanel,'_panel_screen_geo',lambda self:QRect(0,0,1366,768))
    paths=[]
    for index in range(14):
        path=tmp_path/f'shot{index}.png';Image.new('RGB',(320,180),'blue').save(path);paths.append((path,time.time()))
    panel=RecentFilesSidebar(str(tmp_path),edge='bottom',close_on_focus_loss=False)
    panel._on_files_scanned(paths);panel.show();QTest.qWait(30);panel._reflow_grids();app.processEvents()
    viewport=panel._scroll.viewport()
    for group,grid in panel._grid_groups:
        for row in group.file_rows:
            assert row.mapTo(viewport,QPoint()).x()+row.width()<=viewport.width()
    panel.close()


def test_typing_caret_near_image_edge_does_not_shift_when_editor_chrome_is_clipped(app):
    canvas=AnnotationCanvas();canvas.resize(600,400)
    canvas._start_text_input((3,2));canvas._text_edit.setPlainText('Edge')
    cursor=canvas._text_edit.textCursor();cursor.movePosition(QTextCursor.MoveOperation.Start);canvas._text_edit.setTextCursor(cursor)
    origin=canvas._text_edit.viewport().mapTo(canvas,canvas._text_edit.cursorRect().topLeft())
    origin.setY(origin.y()+round(canvas._text_edit.cursorRect().height()/2))
    assert origin==QPoint(3,2)
    pending_origin=canvas._text_pos
    canvas._commit_text();assert canvas._items[-1]['start']==pending_origin
    canvas.close()


@pytest.mark.parametrize('dpr',[1,1.5,2])
def test_capture_outline_is_thin_but_visible_at_scaled_dpi(dpr):
    from ui_elements import _capture_outline_pen
    image=QImage(round(140*dpr),round(100*dpr),QImage.Format.Format_RGBA8888)
    image.setDevicePixelRatio(dpr);image.fill(Qt.GlobalColor.transparent)
    painter=QPainter(image);painter.setRenderHint(QPainter.RenderHint.Antialiasing,False)
    painter.setPen(_capture_outline_pen(QColor(224,76,76,200)));painter.drawRect(QRect(10,10,100,70));painter.end()
    bits=image.bits();bits.setsize(image.sizeInBytes());pixels=np.frombuffer(bits,np.uint8).reshape(image.height(),image.bytesPerLine())[:,:image.width()*4].reshape(image.height(),image.width(),4)
    stripe=pixels[round(20*dpr):round(60*dpr),round(10*dpr)-3:round(10*dpr)+4,3]
    assert 1 <= np.count_nonzero(np.any(stripe>0,axis=0)) <= 2


def test_annotation_screen_watch_is_released_on_close(app):
    pill=AnnotationPill();pill.show();app.processEvents()
    assert pill._watched_screen is not None and pill._screen_watch_connected
    pill.close();app.processEvents()
    assert pill._watched_screen is None and not pill._screen_watch_connected
    app.primaryScreen().availableGeometryChanged.emit(app.primaryScreen().availableGeometry())
    assert not pill._screen_resize_pending


def test_explorer_uses_installed_application_icon_with_arrow_outside_its_edge(app,tmp_path,monkeypatch):
    import dock_widget
    from PyQt6.QtGui import QPixmap,QIcon
    executable=tmp_path/'explorer.exe';executable.write_bytes(b'fixture')
    monkeypatch.setenv('WINDIR',str(tmp_path));lookups=[]
    base=QPixmap(24,24);base.fill(QColor('green'))
    class Provider:
        def icon(self,info):lookups.append(info.filePath());return QIcon(base)
    monkeypatch.setattr(dock_widget,'QFileIconProvider',Provider)
    image=RecentFilesSidebar._explorer_icon().pixmap(32,32).toImage()
    assert [os.path.normcase(os.path.normpath(path)) for path in lookups] == [os.path.normcase(os.path.normpath(str(executable)))]
    assert image.pixelColor(6,10).green()>70
    assert image.pixelColor(29,15).alpha()>0  # Arrow extends beyond the 24px app artwork.


def test_screenshot_view_controls_fit_minimum_editor_width(app, tmp_path):
    from annotation_tool import AnnotateWindow
    path = tmp_path / "native.png"
    image = QImage(300, 200, QImage.Format.Format_RGB32)
    image.fill(QColor("#334455"))
    image.save(str(path))
    window = AnnotateWindow(str(path))
    window.resize(700, 500)
    window.show()
    app.processEvents()
    assert window.minimumSizeHint().width() <= 700
    assert window._btn_actual_pixels.height() == 32
    assert window._btn_fit.height() == 32
    window.close()
