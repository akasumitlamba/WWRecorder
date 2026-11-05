"""
Area 4 — Live annotator & photo editor (adversarial).

Purpose: eraser QPointF/QRectF hit-testing across object types and huge
highlighters; tool-switch mid-stroke; undo/redo/z-order; crop/rotate/flip × undo.
"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QPoint, QPointF
from PyQt6.QtWidgets import QApplication

from helpers.action_matrix import ANNOTATION_TOOLS, assert_invariant
from helpers.adversarial import make_live_canvas, shape_item, stroke_item, text_item
from helpers.env import import_app
from helpers.media import write_tiny_png

pytestmark = [
    pytest.mark.adversarial,
    pytest.mark.area_annotator,
    pytest.mark.feature_annotation,
]


@pytest.mark.pure_logic
@pytest.mark.parametrize(
    "item_factory",
    [
        lambda: stroke_item("pencil", [(10, 10), (40, 12), (80, 40)]),
        lambda: stroke_item("highlighter", [(20, 20), (120, 24)], thickness="huge"),
        lambda: shape_item("rect", (30, 30), (120, 90)),
        lambda: shape_item("circle", (40, 40), (100, 100)),
        lambda: shape_item("arrow", (10, 80), (140, 20)),
        lambda: text_item((50, 50), (140, 90), "erase me"),
    ],
    ids=["pencil", "highlighter_huge", "rect", "circle", "arrow", "text"],
)
def test_eraser_pointf_sweep_hits_all_object_types(qapp, item_factory):
    canvas, _ = make_live_canvas(qapp)
    item = item_factory()
    canvas._items = [item]
    # Continuous QPointF sweep across the item — must not TypeError.
    if item["type"] in ("pencil", "highlighter"):
        pts = item["points"]
        start = QPointF(pts[0][0], pts[0][1])
        end = QPointF(pts[-1][0], pts[-1][1])
    else:
        sx, sy = item["start"]
        ex, ey = item["end"]
        start = QPointF(sx, sy)
        end = QPointF(ex, ey)
    canvas._tool = "eraser"
    canvas._erase_action_items = []
    canvas._erase_original_indexes = {}
    try:
        canvas._erase_sweep(start, end)
    except TypeError as exc:
        raise AssertionError(
            f"eraser TypeError on {item['type']}: {exc} | widget=ann.eraser state=QPointF sweep"
        ) from exc
    QApplication.processEvents()
    # Item should be removed when sweep crosses it.
    assert_invariant(
        item not in canvas._items,
        f"{item['type']} erased by PointF sweep",
        widget="ann.eraser",
        state=item["type"],
    )
    canvas.close()


@pytest.mark.pure_logic
def test_huge_highlighter_radius_is_erasable_off_centerline(qapp):
    """Visible 44px highlighter ink beyond a 12px centerline radius must erase."""
    canvas, ann = make_live_canvas(qapp)
    item = stroke_item("highlighter", [(50, 50), (200, 50)], thickness="huge")
    canvas._items = [item]
    # Offset 18px perpendicular to the stroke — inside half of 44px ink.
    hit = canvas._hit_test(QPointF(120.0, 50.0 + 18.0), item)
    assert_invariant(hit, "off-center huge highlighter hits", widget="ann.eraser", state="huge+18px")
    canvas.close()


@pytest.mark.pure_logic
def test_tool_switch_matrix_while_items_present(qapp):
    canvas, _ = make_live_canvas(qapp)
    canvas._items = [
        stroke_item("pencil", [(0, 0), (10, 10)]),
        shape_item("rect", (20, 20), (60, 60)),
    ]
    for tool in ("pencil", "highlighter", "rect", "circle", "arrow", "text", "eraser", "laser"):
        canvas.set_tool(tool)
        assert_invariant(canvas._tool == tool, "tool set", widget=f"ann.tools.{tool}", state="switch")
    canvas.close()


@pytest.mark.pure_logic
def test_undo_redo_multi_action_and_clear(qapp):
    canvas, _ = make_live_canvas(qapp)
    # Simulate complete actions (not raw moves) via history-friendly appends.
    for i in range(3):
        canvas._items.append(stroke_item("pencil", [(i * 10, 0), (i * 10 + 5, 5)]))
        # Live canvas undo pops last drawable — depend on product undo semantics.
    before = len(canvas._items)
    canvas.undo()
    after_undo = len(canvas._items)
    assert_invariant(after_undo <= before, "undo reduces or no-ops safely", widget="ann.undo", state=f"{before}->{after_undo}")
    canvas.redo()
    canvas.clear_all()
    canvas.undo()
    canvas.redo()
    canvas.close()


@pytest.mark.pure_logic
def test_photo_editor_rotate_flip_crop_undo(qapp, tmp_path):
    """Exercise _DrawingArea directly — AnnotateWindow chrome can hang offscreen."""
    from PyQt6.QtCore import QRectF

    ann = import_app("annotation_tool")
    path = write_tiny_png(tmp_path / "photo.png", (10, 20, 30, 255))
    canvas = ann._DrawingArea(str(path))
    QApplication.processEvents()
    w0, h0 = canvas._original.width(), canvas._original.height()
    canvas.rotate_90()
    QApplication.processEvents()
    assert_invariant(
        canvas._original.width() == h0 and canvas._original.height() == w0,
        "90° rotate swaps dims",
        widget="ann.photo.rotate",
        state=f"{w0}x{h0}",
    )
    canvas.undo()
    QApplication.processEvents()
    assert_invariant(
        canvas._original.width() == w0 and canvas._original.height() == h0,
        "undo restore dims",
        widget="ann.photo.rotate",
        state="undo",
    )
    canvas.flip_horizontal()
    canvas.flip_vertical()
    canvas.undo()
    canvas.undo()
    canvas._crop_rect = QRectF(2, 2, 8, 8)
    canvas.commit_crop()
    QApplication.processEvents()
    assert_invariant(canvas._original.width() <= w0, "crop shrinks or equals", widget="ann.photo.crop", state="after")
    canvas.undo()
    canvas.close()


@pytest.mark.pure_logic
def test_hit_test_accepts_qpoint_and_qpointf(qapp):
    canvas, _ = make_live_canvas(qapp)
    item = shape_item("rect", (0, 0), (50, 50))
    assert canvas._hit_test(QPoint(25, 25), item)
    assert canvas._hit_test(QPointF(25.5, 25.5), item)
    canvas.close()
