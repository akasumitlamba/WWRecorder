"""Helpers for adversarial / interaction-matrix E2E suites.

Purpose
-------
Drive real DockWidget / SelectionOverlay / PillWidget / AnnotationCanvas /
merge helpers with rapid input, float/int coordinate coercion, and busy-state
guards — without faking away the behavior under test.
"""

from __future__ import annotations

from types import SimpleNamespace

from helpers.action_matrix import FakeRecordingEngine, assert_invariant, base_settings_config
from helpers.env import import_app


RESIZE_HANDLES = ("tl", "t", "tr", "r", "br", "b", "bl", "l")
DOCK_EDGES = ("left", "right", "top", "bottom")
DPI_SCALES = (1.0, 1.25, 1.5, 2.0)


def make_dock(qapp, *, edge: str = "right", screen=None, **config_overrides):
    from PyQt6.QtCore import QRect

    dock_widget = import_app("dock_widget")
    cfg = base_settings_config(dock_edge=edge, **config_overrides)
    engine = FakeRecordingEngine()
    dock = dock_widget.DockWidget(engine, cfg)
    if screen is not None:
        dock._screen_geo = lambda _self=None, s=screen: s if isinstance(s, QRect) else s  # type: ignore
        # Prefer monkeypatched method on instance:
        dock._screen_geo = lambda s=screen: s  # noqa: E731
    qapp.processEvents()
    return dock, engine, cfg


def make_selection_overlay(qapp, mode: str = "record"):
    ui = import_app("ui_elements")
    overlay = ui.SelectionOverlay(mode=mode)
    qapp.processEvents()
    return overlay


def make_live_canvas(qapp):
    ann = import_app("annotation_tool")
    canvas = ann.AnnotationCanvas()
    qapp.processEvents()
    return canvas, ann


def stroke_item(tool: str, points, *, thickness: str = "normal", color: str = "#FF3B30"):
    return {
        "type": tool,
        "points": [(float(x), float(y)) for x, y in points],
        "color": color,
        "thickness": thickness,
        "opacity": 0.4 if tool == "highlighter" else 1.0,
    }


def shape_item(kind: str, start, end, *, thickness: str = "normal"):
    return {
        "type": kind,
        "start": (float(start[0]), float(start[1])),
        "end": (float(end[0]), float(end[1])),
        "color": "#FF3B30",
        "thickness": thickness,
    }


def text_item(start, end, text: str = "hi"):
    return {
        "type": "text",
        "start": (float(start[0]), float(start[1])),
        "end": (float(end[0]), float(end[1])),
        "text": text,
        "color": "#FFFFFF",
        "font_size": 16,
        "bold": True,
    }


def delete_region(start_ms: int, end_ms: int):
    return SimpleNamespace(start_ms=start_ms, end_ms=end_ms)


def simulate_pointer_drag(widget, start, end, *, steps: int = 8):
    """Fire press/move/release using QPointF-capable positions when possible."""
    from PyQt6.QtCore import QPoint, QPointF, Qt
    from PyQt6.QtGui import QMouseEvent
    from PyQt6.QtCore import QEvent
    from PyQt6.QtWidgets import QApplication

    def _pt(p):
        if isinstance(p, QPointF):
            return p
        if isinstance(p, QPoint):
            return QPointF(p)
        return QPointF(float(p[0]), float(p[1]))

    s = _pt(start)
    e = _pt(end)
    press = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        s,
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    widget.mousePressEvent(press)
    for i in range(1, steps + 1):
        t = i / steps
        mid = QPointF(s.x() + (e.x() - s.x()) * t, s.y() + (e.y() - s.y()) * t)
        move = QMouseEvent(
            QEvent.Type.MouseMove,
            mid,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        widget.mouseMoveEvent(move)
    release = QMouseEvent(
        QEvent.Type.MouseButtonRelease,
        e,
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    widget.mouseReleaseEvent(release)
    QApplication.processEvents()
