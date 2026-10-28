import os
from pathlib import Path
import sys
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication, QWidget
import pytest
import distribution


@pytest.fixture(scope='session')
def app():
    return QApplication.instance() or QApplication([])


def test_canonical_icon_loads_in_source_layout(app):
    path = Path(distribution.application_icon_path())
    assert path == Path(distribution.__file__).parent / 'icon.ico'
    icon = QIcon(str(path))
    assert not icon.isNull()
    assert len(icon.availableSizes()) == 9
    previous = app.windowIcon()
    try:
        app.setWindowIcon(icon)
        window = QWidget()
        assert window.windowIcon().cacheKey() == icon.cacheKey()
        window.close()
    finally:
        app.setWindowIcon(previous)


def test_canonical_icon_uses_frozen_payload_root(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, '_MEIPASS', str(tmp_path), raising=False)
    assert distribution.application_icon_path() == str(tmp_path / 'icon.ico')


@pytest.mark.parametrize('size', [16, 24, 32, 48, 64, 72, 96, 128, 256])
def test_every_windows_icon_frame_has_clean_transparent_corners(size):
    from PIL import Image
    image = Image.open(distribution.application_icon_path()).ico.getimage((size,size)).convert('RGBA')
    assert image.getbbox() is not None
    for x,y in [(0,0),(size-1,0),(0,size-1),(size-1,size-1)]:
        assert image.getpixel((x,y)) == (0,0,0,0)
    assert image.getpixel((size//2,size//2))[3] == 255


def test_taskbar_artwork_occupies_more_canvas_without_corner_bleed():
    from PIL import Image
    for size in (24,32,48,64,96,256):
        image=Image.open(distribution.application_icon_path()).ico.getimage((size,size)).convert('RGBA')
        bounds=image.getchannel('A').point(lambda a:255 if a>=100 else 0).getbbox()
        assert bounds[2]-bounds[0] >= size*.94
        assert image.getpixel((0,0)) == (0,0,0,0)
        assert image.getpixel((size-1,size-1)) == (0,0,0,0)
