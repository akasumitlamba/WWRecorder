"""Floating annotation cursors must survive light, dark and saturated desktops."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import pytest
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QColor,QImage,QPainter
from tool_cursors import tool_cursor

@pytest.fixture(scope='module')
def app():return QApplication.instance() or QApplication([])

@pytest.mark.parametrize('background',['#FFFFFF','#000000','#808080','#FF0000','#00FFFF','#00FF00'])
@pytest.mark.parametrize('tool',['pencil','highlighter','eraser','text','crosshair','arrow','crop','move','resize_h','resize_v','resize_d1','resize_d2'])
def test_cursor_has_visible_contour_on_any_desktop(app,background,tool):
    pixmap=tool_cursor(tool,'#FFFFFF',20 if tool=='highlighter' else 4).pixmap()
    color=QColor(background)
    image=QImage(pixmap.size(),QImage.Format.Format_RGB32);image.fill(color)
    p=QPainter(image);p.drawPixmap(0,0,pixmap);p.end()
    visible=0
    for y in range(image.height()):
        for x in range(image.width()):
            c=image.pixelColor(x,y)
            if max(abs(c.red()-color.red()),abs(c.green()-color.green()),abs(c.blue()-color.blue()))>=80:
                visible+=1
    assert visible>=16,(tool,background,visible)
