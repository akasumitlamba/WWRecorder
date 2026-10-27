import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import pytest
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QImage, QColor
from annotation_tool import AnnotationCanvas, _DrawingArea

@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])

@pytest.fixture
def photo(app, tmp_path):
    path = tmp_path / 'image.png'
    img = QImage(300, 200, QImage.Format.Format_RGB32)
    img.fill(QColor('white')); img.save(str(path))
    canvas = _DrawingArea(str(path))
    yield canvas
    canvas.close()


def test_photo_delete_undo_restores_order_and_redo_deletes(photo):
    first = {'type': 'rect', 'start': (0, 0), 'end': (10, 10), 'color': '#ff0000'}
    second = {'type': 'rect', 'start': (20, 20), 'end': (30, 30), 'color': '#ff0000'}
    photo._items = [first, second]
    photo._selected_shape_idx = 0
    photo._on_action_bar_delete()
    photo.undo()
    assert photo._items == [first, second]
    photo.redo()
    assert first not in photo._items and second in photo._items


def test_photo_clear_is_one_undo_step(photo):
    original = [{'type': 'rect'}, {'type': 'text'}]
    photo._items = original.copy()
    photo.clear_all(); photo.undo()
    assert photo._items == original
    photo.redo()
    assert all(item.get('_action') for item in photo._items)


def test_edit_text_history_restores_original_object_and_z_order(photo):
    target = {'type': 'text', 'text': 'before'}
    photo._items = [target, {'type': 'rect'}]
    photo._editing_text_index = 0
    photo._editing_text_backup = photo._items.pop(0)
    photo._items.append({'type': 'text', 'text': 'after'})
    photo._finish_text_history()
    photo.undo()
    assert photo._items[0] is target and target['text'] == 'before'
    photo.redo()
    assert photo._items[0] is target and target['text'] == 'after'


def test_live_update_undo_keeps_caption(app):
    canvas = AnnotationCanvas()
    item = {'type': 'text', 'text': 'new', 'start': (20, 20)}
    canvas._items = [item, {'_action': 'update', '_target': item,
                         '_before': {'type': 'text', 'text': 'old', 'start': (0, 0)},
                         '_after': dict(item)}]
    canvas.undo()
    assert item['text'] == 'old' and item['start'] == (0, 0)
    canvas.redo()
    assert item['text'] == 'new' and item['start'] == (20, 20)
    canvas.close()


def test_caption_image_retains_background_and_underline(app, tmp_path):
    from video_editor import _TextOverlayItem, DraggableTextItem, _render_caption_image
    from PyQt6.QtMultimediaWidgets import QGraphicsVideoItem
    from PyQt6.QtCore import QSizeF
    video = QGraphicsVideoItem(); video.setSize(QSizeF(640, 360))
    item = _TextOverlayItem(); item.text = 'Caption'; item.underline = True
    gfx = DraggableTextItem(item, video); gfx.update_style()
    path = tmp_path / 'caption.png'
    _render_caption_image(gfx, str(path))
    image = QImage(str(path))
    assert not image.isNull() and gfx.font().underline()
    assert 0 < image.pixelColor(image.width() // 2, 3).alpha() < 255


def test_pill_selection_is_independent_of_mute_and_keeps_compact_controls(app):
    from ui_elements import PillWidget
    class Engine:
        _microphone_name = 'Same as Windows'
        _microphone_failed = False
        def get_mic(self): return False
        def get_system_audio(self): return False
        def set_microphone(self, device_id, name):
            self.selected = (device_id, name)
            self._microphone_name = name
        def is_paused(self): return False
    engine = Engine()
    pill = PillWidget(engine, {}, pre_record=True)
    chosen = []
    pill.microphone_selected.connect(lambda *args: chosen.append(args))
    pill._select_microphone('usb', 'USB microphone')
    assert chosen == [('usb', 'USB microphone')]
    assert not pill._btn_mic.isChecked()
    assert 'USB microphone' in pill._btn_mic.toolTip()
    assert pill._btn_mic.width() == pill._btn_mic.height() == 38
    assert pill._btn_mic_menu.width() == 16
    assert not hasattr(pill, '_btn_settings')
    assert pill._btn_annotate.size() == pill._btn_discard.size()
    engine._microphone_failed = True
    pill._update_microphone_tooltip()
    assert pill._btn_mic.text() == '!' and 'failed' in pill._btn_mic.toolTip()
    pill._stopping = True
    pill.close()


def test_desktop_startup_reflects_windows_disabled_state(monkeypatch):
    import sys
    from types import SimpleNamespace
    from startup_integration import desktop_startup_state
    class Key:
        def __init__(self, path): self.path = path
        def __enter__(self): return self
        def __exit__(self, *args): pass
    registry = SimpleNamespace(HKEY_CURRENT_USER=object(),
        OpenKey=lambda root, path: Key(path),
        QueryValueEx=lambda key, name: (bytes([3, 0, 0, 0]) + bytes(8), 3)
            if 'StartupApproved' in key.path else ('recorder.exe', 1))
    monkeypatch.setitem(sys.modules, 'winreg', registry)
    enabled, message = desktop_startup_state()
    assert not enabled and 'disabled in Windows' in message


def test_late_mic_menu_result_cannot_unlock_preparation(app):
    from ui_elements import PillWidget
    class Engine:
        def get_mic(self): return False
        def get_system_audio(self): return False
        def is_paused(self): return False
        def set_microphone(self, *args): raise AssertionError('Must remain locked')
    pill = PillWidget(Engine(), {}, pre_record=True)
    pill.show(); pill.set_preparing(True)
    pill._open_microphone_menu([('usb', 'USB microphone')], '')
    pill._select_microphone('usb', 'USB microphone')
    pill._initiate_stop()
    assert not pill._btn_mic_menu.isEnabled()
    assert not pill._stopping
    pill.set_preparing(False); pill._stopping = True; pill.close()
