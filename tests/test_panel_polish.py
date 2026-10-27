"""Reference panel geometry, translucent repaint and precision wheel regressions."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from types import SimpleNamespace
import time
import pytest
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt, QRect, QPoint, QPointF
from PyQt6.QtGui import QColor, QImage, QPainter
from PyQt6.QtTest import QTest
from dock_widget import SidebarPanel, SettingsSidebar, RecentFilesSidebar, _FileRow
from annotation_tool import AnnotationCanvas, get_tool_cursor
from ui_elements import SelectionOverlay
import keycast


@pytest.fixture(scope="module", autouse=True)
def app():
    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize("edge", ["top", "bottom"])
def test_horizontal_panel_flush_with_screen_edge_and_no_internal_header_stripe(
    app, monkeypatch, tmp_path, edge
):
    monkeypatch.setattr(
        SidebarPanel, "_panel_screen_geo", lambda self: QRect(-1366, 0, 1366, 768)
    )
    monkeypatch.setattr(RecentFilesSidebar, "_load_files", lambda self: None)
    panel = RecentFilesSidebar(str(tmp_path), edge=edge, close_on_focus_loss=False)
    panel.show()
    app.processEvents()
    assert panel.y() == 0 if edge == "top" else panel.geometry().bottom() == 767
    image = panel.grab().toImage()
    dpr = image.devicePixelRatio()
    # The old rounded-rect + square-edge subpaths stroked an unwanted line at y=12.
    for y in (11, 12, 13):
        assert image.pixelColor(round(500 * dpr), round(y * dpr)).red() < 60
    panel.close()


@pytest.mark.parametrize("edge", ["left", "right", "top", "bottom"])
def test_header_controls_match_across_orientations_and_stay_inside(
    app, tmp_path, monkeypatch, edge
):
    monkeypatch.setattr(RecentFilesSidebar, "_load_files", lambda self: None)
    panel = RecentFilesSidebar(str(tmp_path), edge=edge, close_on_focus_loss=False)
    panel.show()
    app.processEvents()
    for button in (panel._btn_folder, panel._btn_search, panel._btn_settings):
        assert button.width() == button.height() == 32
        assert panel.rect().contains(
            QRect(button.mapTo(panel, QPoint()), button.size())
        )
        assert "border-radius: 5px" in button.styleSheet()
    panel.close()


def test_settings_independent_columns_avoid_empty_audio_row_and_default_gap(
    app, monkeypatch
):
    monkeypatch.setattr(
        SidebarPanel, "_panel_screen_geo", lambda self: QRect(0, 0, 1366, 768)
    )
    panel = SettingsSidebar({"close_on_focus_loss": False}, edge="bottom")
    panel.show()
    QTest.qWait(100)
    app.processEvents()
    capture, dock, audio, shortcuts, general = panel._settings_cards
    assert capture.height() < 150
    assert dock.y() == capture.geometry().bottom() + 13
    assert general.y() == audio.geometry().bottom() + 13
    assert shortcuts.y() == dock.geometry().bottom() + 13
    last = max(
        card.mapTo(panel, QPoint(0, card.height())).y()
        for card in panel._settings_cards
    )
    footer = panel._btn_save.mapTo(panel, QPoint()).y()
    assert 0 < footer - last < 45
    assert (
        panel._general_heading.isVisible()
        and not panel._advanced_section.btn_toggle.isVisible()
    )
    panel.close()


def test_name_and_size_share_menu_height_without_shrinking_hit_target(app, tmp_path):
    path = tmp_path / "a_long_capture_filename.png"
    path.write_bytes(b"x" * 3200)
    row = _FileRow(str(path), grid=True, defer_load=True)
    row.resize(250, 186)
    row.show()
    app.processEvents()
    assert row._lbl_size_text.text() == "3 KB" and row._lbl_size_text.isVisible()
    name = QRect(row._lbl_name.mapTo(row, QPoint()), row._lbl_name.size())
    size = QRect(row._lbl_size_text.mapTo(row, QPoint()), row._lbl_size_text.size())
    menu = QRect(row._btn_menu.mapTo(row, QPoint()), row._btn_menu.size())
    assert menu.height() == 26 and name.bottom() < size.top()
    assert name.top() >= menu.top() - 1 and size.bottom() <= menu.bottom() + 1
    assert row._thumb.width() == row.width() - 12
    row.close()


def test_transparent_annotation_repaint_erases_previous_shape(app):
    canvas = AnnotationCanvas()
    canvas.resize(420, 260)
    canvas.show()
    app.processEvents()
    shape = {
        "type": "rect",
        "start": (40, 40),
        "end": (100, 100),
        "width": 3,
        "color": "#FF0000",
    }
    canvas._items = [shape]
    before = canvas.grab().toImage()
    shape["start"] = (200, 40)
    shape["end"] = (260, 100)
    canvas.update()
    app.processEvents()
    after = canvas.grab().toImage()
    dpr = after.devicePixelRatio()
    assert before.pixelColor(round(40 * dpr), round(65 * dpr)).red() > 180
    assert after.pixelColor(round(40 * dpr), round(65 * dpr)).alpha() < 10
    assert after.pixelColor(round(200 * dpr), round(65 * dpr)).red() > 180
    canvas.close()


@pytest.mark.parametrize("mode", ["record", "screenshot"])
def test_selection_is_visible_red_with_consistently_centered_handles(app, mode):
    overlay = SelectionOverlay(mode=mode)
    overlay.resize(500, 320)
    overlay.rect_obj = QRect(80, 70, 240, 150)
    overlay.state = "SELECTED"
    assert overlay.selection_color.red() > 240 and overlay.selection_color.blue() < 100
    assert overlay.selection_color.alpha() == 255
    if mode == "record":
        expected = [
            (80, 70),
            (199, 70),
            (319, 70),
            (319, 144),
            (319, 219),
            (199, 219),
            (80, 219),
            (80, 144),
        ]
        actual = [
            (r.x() + r.width() / 2, r.y() + r.height() / 2)
            for r in overlay.get_handles().values()
        ]
        # Every hit target centre uses the same inclusive QRect edge coordinates.
        assert set(actual) == set(expected)
    overlay._cancel_emitted = True
    overlay.close()


def test_text_pointer_hotspot_matches_top_of_insertion_indicator(app):
    cursor = get_tool_cursor("text", QColor("red"))
    assert cursor.hotSpot() == QPoint(16, 16)
    image = cursor.pixmap().toImage()
    assert image.pixelColor(16, 4).alpha() > 200
    assert image.pixelColor(16, 0).alpha() == 0


@pytest.mark.parametrize("delta", [1, 2, 40, 119, 120, -1, -2, -40, -119, -120])
@pytest.mark.parametrize("message", [0x020A, 0x020E])
def test_precision_touchpad_sub_detent_deltas_keep_direction(delta, message):
    data = (delta & 0xFFFF) << 16
    expected = (
        ("scroll_up" if delta > 0 else "scroll_down")
        if message == 0x020A
        else ("scroll_right" if delta > 0 else "scroll_left")
    )
    assert keycast.raw_wheel_direction(message, data) == expected
    assert keycast.raw_wheel_direction(message, 0) is None


def test_hide_on_drag_is_inside_advanced_not_capture_card(app):
    panel = SettingsSidebar({"close_on_focus_loss": False}, edge="top")
    panel.show()
    QTest.qWait(40)
    capture = panel._settings_cards[0]
    assert not capture.isAncestorOf(panel._cmb_dock_position)
    assert panel._dock_settings_card.isAncestorOf(panel._cmb_dock_position)
    assert panel._dock_settings_card.isAncestorOf(panel._seg_font)
    assert not capture.isAncestorOf(panel._chk_hide_drag)
    assert panel._advanced_section.content_area.isAncestorOf(panel._chk_hide_drag)
    assert panel._general_heading.text() == "ADVANCED SETTINGS"
    panel.close()


def test_raw_wheel_filter_bypasses_rounding_without_suppressing_system(monkeypatch):
    monkeypatch.setattr(keycast.sys, "platform", "linux")
    callbacks = {}

    class Listener:
        alive = False

        def start(self):
            self.alive = True

        def stop(self):
            self.alive = False

        def is_alive(self):
            return self.alive

        def join(self, timeout):
            pass

    def factory(**kw):
        callbacks.update(kw)
        return [Listener(), Listener()]

    session = keycast.InputSession(factory)
    deadline = time.monotonic() + 1
    while not session.ready and time.monotonic() < deadline:
        time.sleep(0.005)
    data = SimpleNamespace(mouseData=(1 << 16), pt=SimpleNamespace(x=30, y=40))
    assert callbacks["wheel_filter"](0x020A, data) is False
    assert session.drain()[0][0][1] == "scroll_up"
    assert callbacks["wheel_filter"](0x0200, data) is True
    session.stop()


def test_hidden_settings_scrollbar_still_accepts_wheel(app):
    from PyQt6.QtGui import QWheelEvent

    panel = SettingsSidebar({"close_on_focus_loss": False}, edge="right")
    panel.show()
    panel._advanced_section.toggle()
    QTest.qWait(280)
    app.processEvents()
    bar = panel._settings_scroll.verticalScrollBar()
    assert not bar.isVisible() and bar.maximum() > 0
    wheel = QWheelEvent(
        QPointF(20, 20),
        QPointF(20, 20),
        QPoint(),
        QPoint(0, -120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.ScrollUpdate,
        False,
    )
    QApplication.sendEvent(panel._settings_scroll.viewport(), wheel)
    assert bar.value() > 0
    panel.close()


def test_generated_header_assets_are_transparent_and_shipped():
    from pathlib import Path
    from PIL import Image

    root = Path(__file__).resolve().parents[1] / "app/icons"
    for name in ("search", "settings", "close"):
        image = Image.open(root / f"panel-{name}.png").convert("RGBA")
        assert image.size == (64, 64)
        assert image.getpixel((0, 0))[3] == 0
        assert image.getchannel("A").getextrema()[1] > 240
        assert not image.info.get("exif")
    assert (root / "PANEL-ICONS.txt").is_file()


def test_dock_restore_waits_until_all_panels_are_closed():
    # Isolate the coordinator method without importing the Windows entrypoint.
    import ast
    from pathlib import Path

    tree = ast.parse(
        (Path(__file__).resolve().parents[1] / "app/main.py").read_text(
            encoding="utf-8"
        )
    )
    cls = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "WWRecorderApp"
    )
    method = next(
        node
        for node in cls.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_restore_dock_after_panel"
    )
    namespace = {}
    exec(
        compile(
            ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[])),
            "coordinator-test",
            "exec",
        ),
        namespace,
    )
    shown = []
    owner = SimpleNamespace(
        _recent_panel=SimpleNamespace(isVisible=lambda: False),
        _settings_sidebar=SimpleNamespace(isVisible=lambda: True),
        dock=SimpleNamespace(set_panel_anchor=lambda panel: shown.append(panel)),
    )
    namespace["_restore_dock_after_panel"](owner)
    assert shown == [owner._settings_sidebar]
    owner._settings_sidebar.isVisible = lambda: False
    namespace["_restore_dock_after_panel"](owner)
    assert shown == [owner._settings_sidebar, None]


def test_gallery_resize_cache_is_bounded_without_changing_saved_screenshot(
    app, tmp_path
):
    path = tmp_path / "original.png"
    original = QImage(2048, 1536, QImage.Format.Format_RGB32)
    original.fill(QColor("#27456A"))
    original.save(str(path))
    row = _FileRow(str(path), grid=True)
    assert row._image_preview.width() <= 640 and row._image_preview.height() <= 480
    row.resize(250, 186)
    row.show()
    app.processEvents()
    assert QImage(str(path)).size() == original.size()
    row.close()
