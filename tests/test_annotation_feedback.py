"""Render the shared annotation feedback without Windows capture dependencies."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QApplication, QWidget
from annotation_tool import _ThicknessButton, _ToastWidget


@pytest.fixture(scope='module')
def qt_app():
    return QApplication.instance() or QApplication([])


def test_toast_paints_dark_backing_on_white_canvas(qt_app):
    parent = QWidget()
    parent.resize(700, 100)
    parent.setStyleSheet('background: white;')
    toast = _ToastWidget(parent)
    parent.show()
    for message in ('Annotation paused', 'Annotation is active'):
        toast.show_message(message, '')
        qt_app.processEvents()
        image = toast.grab().toImage()
        backing = image.pixelColor(image.width() // 2, 3)
        assert backing.alpha() == 255
        assert max(backing.red(), backing.green(), backing.blue()) < 80
        assert toast.text_label.text() == message
    parent.close()


@pytest.mark.parametrize('size,compact', [(25, True), (28, True), (34, True), (34, False)])
@pytest.mark.parametrize('tool', ['pencil', 'highlighter', 'rect'])
def test_gauge_shows_diagonal_stroke_with_increasing_width(qt_app, size, compact, tool):
    button = _ThicknessButton('Thickness', size=size, compact=compact)
    button.set_preview(tool, QColor('#FF3B30'))
    button.show()
    areas = []
    for level in ('thin', 'normal', 'big', 'huge'):
        button.set_thickness_label(level)
        qt_app.processEvents()
        image = button.grab().toImage()
        pixels = [(x, y) for x in range(min(image.width(), 34)) for y in range(image.height())
                  if image.pixelColor(x, y).red() > image.pixelColor(x, y).green() + 25
                  and image.pixelColor(x, y).red() > image.pixelColor(x, y).blue() + 25]
        assert pixels
        cx, cy = button._gauge_center_x() * image.devicePixelRatio(), button.height() * image.devicePixelRatio() / 2
        # A bottom-left to top-right stroke has negative coordinate covariance.
        assert sum((x - cx) * (y - cy) for x, y in pixels) < 0
        areas.append(len(pixels))
    assert all(left < right for left, right in zip(areas, areas[1:])), areas
    button.close()
