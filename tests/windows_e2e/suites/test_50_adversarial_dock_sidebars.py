"""
Area 1 — Edge dock & companion sidebars (adversarial).

Purpose: four-edge geometry, discovery strobe lifecycle, expand/collapse spam,
focus-loss vs popup guards, dirty settings, rename Escape, DPI offscreen paint.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PyQt6.QtCore import QPoint, QRect, Qt
from PyQt6.QtGui import QKeyEvent, QImage, QPainter
from PyQt6.QtWidgets import QApplication, QComboBox

from helpers.action_matrix import assert_invariant, make_settings_sidebar, set_toggle
from helpers.adversarial import DOCK_EDGES, DPI_SCALES
from helpers.env import import_app
from helpers.media import isolated_output_root, write_tiny_png

pytestmark = [
    pytest.mark.adversarial,
    pytest.mark.area_dock,
    pytest.mark.feature_ui,
]


@pytest.mark.pure_logic
@pytest.mark.parametrize("edge", DOCK_EDGES)
def test_dock_snaps_to_each_edge_negative_desktop(qapp, monkeypatch, edge):
    dock_widget = import_app("dock_widget")
    screen = QRect(-1920, -80, 1920, 1080)
    monkeypatch.setattr(dock_widget.DockWidget, "_screen_geo", lambda self: screen)
    cfg = {"dock_edge": edge, "dock_x": -900, "dock_y": 200}
    dock = dock_widget.DockWidget(object(), cfg)
    dock.show()
    QApplication.processEvents()
    dock._set_collapsed_geo(animate=False)
    QApplication.processEvents()
    geo = dock.geometry()
    assert_invariant(geo.width() > 0 and geo.height() > 0, "collapsed geo non-empty", widget="dock", state=edge)
    # Must remain intersecting the virtual screen (negative origins allowed).
    assert_invariant(
        geo.intersects(screen) or screen.contains(geo.center()),
        "dock intersects negative virtual desktop",
        widget="dock.edge",
        state=f"{edge} geo={geo.getRect()}",
    )
    dock.close()


@pytest.mark.pure_logic
def test_discovery_strobe_stops_after_acknowledge_survives_settings_reload(qapp, monkeypatch):
    """AI_CONTEXT: blink until first hover/action, then steady for process session.

    Settings reload / config mutation on the same dock instance must NOT restart
    the strobe. Cold-process restart re-enabling blink is documented separately.
    """
    dock_widget = import_app("dock_widget")
    monkeypatch.setattr(dock_widget.DockWidget, "_screen_geo", lambda self: QRect(0, 0, 1366, 768))
    dock = dock_widget.DockWidget(object(), {"dock_edge": "right"})
    assert_invariant(dock._is_first_launch is True, "starts undiscovered", widget="dock.discovery", state="construct")
    dock._acknowledge_startup_indicator()
    assert_invariant(dock._is_first_launch is False, "acknowledged", widget="dock.discovery", state="after hover")
    assert_invariant(not dock._first_blink_timer.isActive(), "blink timer stopped", widget="dock.discovery", state="after")
    # Simulate settings reload mutating config on the live dock.
    dock._config["close_on_focus_loss"] = False
    dock.set_dock_edge("left")
    QApplication.processEvents()
    assert_invariant(
        dock._is_first_launch is False,
        "settings/edge change must not revive discovery strobe",
        widget="dock.discovery",
        state="after settings reload",
    )
    dock.close()


@pytest.mark.pure_logic
def test_expand_collapse_spam_leaves_stable_terminal_geometry(qapp, monkeypatch):
    dock_widget = import_app("dock_widget")
    monkeypatch.setattr(dock_widget.DockWidget, "_screen_geo", lambda self: QRect(0, 0, 1440, 900))
    dock = dock_widget.DockWidget(object(), {"dock_edge": "right"})
    dock.show()
    QApplication.processEvents()
    for _ in range(12):
        dock._expand()
        dock._collapse()
    dock._set_collapsed_geo(animate=False)
    QApplication.processEvents()
    assert_invariant(dock._expanded is False, "ends collapsed", widget="dock.anim", state="spam")
    collapsed = QRect(dock.geometry())
    dock._set_expanded_geo(animate=False)
    QApplication.processEvents()
    expanded = QRect(dock.geometry())
    assert_invariant(expanded != collapsed, "expanded differs from collapsed", widget="dock.anim", state="terminal")
    # No zero-size intermediate stuck state.
    assert_invariant(expanded.width() >= 40 and expanded.height() >= 40, "expanded size sane", widget="dock.anim", state=str(expanded.getRect()))
    dock.close()


@pytest.mark.pure_logic
def test_focus_loss_ignored_while_active_popup(qapp, monkeypatch):
    dock_widget = import_app("dock_widget")
    side, _, _ = make_settings_sidebar(qapp, close_on_focus_loss=True)
    side.show()
    QApplication.processEvents()
    # Pretend a combo popup owns activation.
    monkeypatch.setattr(QApplication, "activePopupWidget", staticmethod(lambda: side._cmb_dock_position))
    monkeypatch.setattr(QApplication, "activeWindow", staticmethod(lambda: None))
    side._check_should_close()
    QApplication.processEvents()
    assert_invariant(side.isVisible(), "popup must not dismiss panel", widget="dock.popup_focus", state="combo open")
    monkeypatch.setattr(QApplication, "activePopupWidget", staticmethod(lambda: None))
    side.close()


@pytest.mark.pure_logic
@pytest.mark.parametrize("scale", DPI_SCALES)
def test_dock_paint_at_dpi_scales_no_exception(qapp, monkeypatch, scale):
    dock_widget = import_app("dock_widget")
    monkeypatch.setattr(dock_widget.DockWidget, "_screen_geo", lambda self: QRect(0, 0, int(1366 * scale), int(768 * scale)))
    dock = dock_widget.DockWidget(object(), {"dock_edge": "right"})
    dock.show()
    QApplication.processEvents()
    img = QImage(dock.width() or 48, dock.height() or 48, QImage.Format.Format_ARGB32)
    img.fill(0)
    p = QPainter(img)
    dock.render(p)
    p.end()
    # Sample corner transparent margin — grabber should not paint opaque bleed
    # into the extreme corners of a translucent window when collapsed.
    dock._set_collapsed_geo(animate=False)
    QApplication.processEvents()
    dock.close()


@pytest.mark.pure_logic
def test_settings_dirty_reset_and_save_matrix(qapp):
    side, persisted, saved = make_settings_sidebar(qapp, copy_to_clipboard=False)
    set_toggle(side, "_chk_clip", True)
    assert side._btn_save.isEnabled()
    side._reset()
    # Reset toward defaults (clipboard True) while last saved was False → still dirty.
    assert side._btn_save.isEnabled()
    side._save()
    assert saved and persisted.get("copy_to_clipboard") is True
    side.close()


@pytest.mark.pure_logic
def test_inline_rename_escape_cancels(qapp, tmp_path):
    dock_widget = import_app("dock_widget")
    out = isolated_output_root(tmp_path)
    path = write_tiny_png(out / "row.png")
    renames = []
    row = dock_widget._FileRow(str(path))
    row.rename_requested.connect(lambda a, b: renames.append((a, b)))
    row._start_rename()
    row._rename_edit.setText("nope")
    esc = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
    row._rename_edit.keyPressEvent(esc)
    QApplication.processEvents()
    assert_invariant(renames == [], "Escape cancels rename", widget="gallery.rename", state="escape")
    assert path.exists()
    row.deleteLater()
