"""
annotation_tool.py - WWRecorder Annotation System (Lazy-loaded)

• AnnotationCanvas  : Transparent overlay for drawing during recording
                      (NOT excluded from capture — visible in output)
• AnnotateWindow    : Screenshot editor window (WWR: Image Editor)

Loaded only when the user activates annotation to avoid impacting startup
or recording performance.
"""
import ctypes
import math
import os
import sys
import time
from typing import List, Optional

from PyQt6.QtWidgets import (
    QApplication, QWidget, QLabel, QPushButton, QToolButton,
    QHBoxLayout, QVBoxLayout, QBoxLayout, QSizePolicy, QMessageBox,
    QFrame, QToolTip, QGraphicsDropShadowEffect, QStackedWidget,
    QMenu, QComboBox, QFileDialog, QGridLayout, QPlainTextEdit, QScrollArea
)
from tool_cursors import shape_cursor

from PyQt6.QtCore import (
    Qt, QRect, QRectF, QPoint, QSize, QTimer, QPointF,
    pyqtSignal, QUrl, QMimeData, QEvent, QSaveFile, QIODevice,
)
from PyQt6.QtGui import (
    QPainter, QColor, QBrush, QPen, QFont, QFontMetrics,
    QPainterPath, QIcon, QPixmap, QImage, QCursor, QKeySequence, QShortcut,
    QTransform, QTextLayout, QTextOption
)
# ── Windows API ────────────────────────────────────────────────────────────────
MAX_ANNOTATION_TEXT = 500
MAX_UNDO_ITEMS = 300
LASER_TRAIL_HOLD_MS = 3000
LASER_TRAIL_FADE_MS = 1000


def _append_limited_text(current: str, addition: str) -> str:
    remaining = MAX_ANNOTATION_TEXT - len(current)
    if remaining <= 0:
        return current
    return current + addition[:remaining]


def _calc_text_box_height(text: str, font: QFont, box_width: float, min_height: float = 34.0) -> float:
    """Return the pixel height needed to show wrapped text without scrolling."""
    fm = QFontMetrics(font)
    line_height = max(fm.height(), 16)
    usable_w = max(float(box_width) - 16.0, 20.0)
    if not text:
        return max(min_height, line_height + 16.0)

    layout = QTextLayout(text, font)
    opt = QTextOption()
    opt.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
    layout.setTextOption(opt)
    layout.beginLayout()
    y_offset = 0.0
    while True:
        line = layout.createLine()
        if not line.isValid():
            break
        line.setLineWidth(usable_w)
        y_offset += line_height
    layout.endLayout()
    return max(min_height, y_offset + 16.0)


def _arrow_head_size(width: float, length: float) -> float:
    """Return a restrained arrow head that still distinguishes every width."""
    return min(max(6.0, 4.0 + float(width) * 1.8), 24.0, float(length) * 0.4)


def _fit_default_text_box(x, y, desired_width, desired_height, bounds_width, bounds_height):
    """Keep a click-created text editor visible at image/screen boundaries."""
    width = max(1.0, min(float(desired_width), float(bounds_width)))
    height = max(1.0, min(float(desired_height), float(bounds_height)))
    x = max(0.0, min(float(x), float(bounds_width) - width))
    y = max(0.0, min(float(y), float(bounds_height) - height))
    return x, y, width, height


def _text_editor_top_left(text_x, text_y):
    """Position the editor chrome so its first text glyph begins at the click."""
    return int(text_x) - 10, int(text_y) - 8


def _align_new_text_caret(owner, target, scale=1.0):
    """Place the first caret at the pointer's centre using Qt's real metrics."""
    editor = owner._text_edit
    editor.ensurePolished()
    caret = editor.cursorRect()
    origin = editor.viewport().mapTo(owner, caret.topLeft())
    dx = round(target[0] - origin.x())
    dy = round(target[1] - (origin.y() + caret.height() / 2))
    x, y = owner._text_pos
    owner._text_pos = (x + dx / scale, y + dy / scale)
    editor.move(editor.x() + dx, editor.y() + dy)
    owner._reposition_text_bar()


def _atomic_save_image(image: QImage, filepath: str, fmt: str | None = None) -> bool:
    save_file = QSaveFile(filepath)
    if not save_file.open(QIODevice.OpenModeFlag.WriteOnly):
        return False
    image_format = fmt or ('JPEG' if filepath.lower().endswith(('.jpg', '.jpeg')) else 'PNG')
    if not image.save(save_file, image_format):
        save_file.cancelWriting()
        return False
    return save_file.commit()


def _clamp_popup_position(anchor: QRect, popup: QSize, available: QRect, gap: int = 5) -> QPoint:
    below = anchor.bottom() + 1 + gap
    above = anchor.top() - popup.height() - gap
    y = below if below + popup.height() - 1 <= available.bottom() else above
    x = max(available.left(), min(anchor.left(), available.right() - popup.width() + 1))
    y = max(available.top(), min(y, available.bottom() - popup.height() + 1))
    return QPoint(x, y)


class _AnnotationPlainTextEdit(QPlainTextEdit):
    commit_requested = pyqtSignal()
    cancel_requested = pyqtSignal()
    content_resized = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.document().setDocumentMargin(0)
        self.setTabChangesFocus(False)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setStyleSheet("""
            QPlainTextEdit {
                background: rgba(20, 20, 24, 190);
                color: #FFFFFF;
                border: 2px dashed #EF4444;
                border-radius: 6px;
                padding: 6px 8px;
                selection-background-color: rgba(220, 38, 38, 160);
            }
        """)
        self.textChanged.connect(self._on_text_changed)

    def _on_text_changed(self):
        self._enforce_limit()
        self.content_resized.emit()

    def _enforce_limit(self):
        text = self.toPlainText()
        if len(text) <= MAX_ANNOTATION_TEXT:
            return
        cursor = self.textCursor()
        pos = min(cursor.position(), MAX_ANNOTATION_TEXT)
        self.blockSignals(True)
        self.setPlainText(text[:MAX_ANNOTATION_TEXT])
        cursor = self.textCursor()
        cursor.setPosition(pos)
        self.setTextCursor(cursor)
        self.blockSignals(False)

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.cancel_requested.emit()
            event.accept()
            return
        # Let QPlainTextEdit handle newlines, typing, cursor navigation natively
        super().keyPressEvent(event)
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.content_resized.emit()


def _trim_history(items: list, redo_stack: list) -> None:
    overflow = len(items) - MAX_UNDO_ITEMS
    if overflow > 0:
        del items[:overflow]
    overflow = len(redo_stack) - MAX_UNDO_ITEMS
    if overflow > 0:
        del redo_stack[:overflow]


try:
    _user32 = ctypes.windll.user32 if sys.platform == "win32" else None
except Exception:
    _user32 = None


def _asset(filename: str) -> str:
    from icon_theme import asset_path
    return asset_path(filename)


def _add_outline_to_pixmap(pixmap: QPixmap, outline_color: QColor = QColor(0, 0, 0, 180)) -> QPixmap:
    """Return a new QPixmap with a 1px outline added to the given pixmap's non-transparent pixels."""
    if pixmap.isNull():
        return pixmap
        
    # Scale up slightly to make room for the outline
    out = QPixmap(pixmap.width() + 2, pixmap.height() + 2)
    out.fill(Qt.GlobalColor.transparent)
    
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    
    # 1. Create a black version of the icon to use as the outline
    # We do this by drawing the icon with a specific composition mode
    mask = pixmap.toImage().createAlphaMask()
    outline_img = QImage(out.size(), QImage.Format.Format_ARGB32)
    outline_img.fill(Qt.GlobalColor.transparent)
    
    op = QPainter(outline_img)
    # Draw original pixmap 8 times at offsets to create a thick outline base
    for dx in [-1, 0, 1]:
        for dy in [-1, 0, 1]:
            if dx == 0 and dy == 0: continue
            op.drawPixmap(1 + dx, 1 + dy, pixmap)
    
    # Colorize the outline base to the requested outline color
    op.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    op.fillRect(outline_img.rect(), outline_color)
    op.end()
    
    # 2. Draw the outline first, then the original icon on top
    p.drawImage(0, 0, outline_img)
    p.drawPixmap(1, 1, pixmap)
    p.end()
    
    return out


# ── Shared Constants ──────────────────────────────────────────────────────────

ANNOTATION_COLORS = [
    ('#FF3B30', 'Red'),
    ('#FFD60A', 'Yellow'),
    ('#34C759', 'Green'),
    ('#0A84FF', 'Blue'),
    ('#FFFFFF', 'White'),
    ('#000000', 'Black'),
]

THICKNESS_LEVELS = {
    'pencil': {'thin': 2, 'normal': 4, 'big': 7, 'huge': 12},
    'highlighter': {'thin': 12, 'normal': 20, 'big': 30, 'huge': 44},
    'shapes': {'thin': 2, 'normal': 4, 'big': 7, 'huge': 12},
}

# PERF-010: Module-level constant to avoid per-call dict creation in mouseMoveEvent
_HANDLE_CURSORS = {
    'tl': Qt.CursorShape.SizeFDiagCursor,
    'br': Qt.CursorShape.SizeFDiagCursor,
    'tr': Qt.CursorShape.SizeBDiagCursor,
    'bl': Qt.CursorShape.SizeBDiagCursor,
    't':  Qt.CursorShape.SizeVerCursor,
    'b':  Qt.CursorShape.SizeVerCursor,
    'l':  Qt.CursorShape.SizeHorCursor,
    'r':  Qt.CursorShape.SizeHorCursor,
    'start': Qt.CursorShape.SizeAllCursor,
    'end': Qt.CursorShape.SizeAllCursor,
}


def _calc_cursor_pos(text: str, font: QFont, box_width: int, origin_x: float, origin_y: float):
    """Calculate accurate cursor position at end of word-wrapped text using QTextLayout.
    
    Returns (cursor_x, cursor_y_top, cursor_y_bottom) in absolute coordinates.
    QTextLayout performs the same word-boundary-first wrapping as committed text,
    so the cursor position matches exactly where the text visually ends.
    """
    fm = QFontMetrics(font)
    line_height = fm.height()
    
    if not text:
        # Empty text — cursor at the top-left of the box
        return (origin_x, origin_y, origin_y + line_height)
    
    layout = QTextLayout(text, font)
    opt = QTextOption()
    opt.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
    layout.setTextOption(opt)
    
    layout.beginLayout()
    y_offset = 0.0
    last_line_width = 0.0
    while True:
        line = layout.createLine()
        if not line.isValid():
            break
        line.setLineWidth(box_width)
        line.setPosition(QPointF(0, y_offset))
        last_line_width = line.naturalTextWidth()
        y_offset += line_height
    layout.endLayout()
    
    # Cursor is at the end of the last visual line
    cx = origin_x + last_line_width
    cy_top = origin_y + y_offset - line_height
    cy_bot = origin_y + y_offset
    return (cx, cy_top, cy_bot)


def _shape_bounding_rect(item: dict) -> QRectF:
    """Return the bounding rectangle for a shape item (circle, rect, arrow, text)."""
    sx, sy = item['start']
    ex, ey = item['end']
    x = min(sx, ex)
    y = min(sy, ey)
    w = abs(ex - sx)
    h = abs(ey - sy)
    if item.get('type') == 'text':
        pad_x = 8.0
        pad_y = 6.0
        return QRectF(x - pad_x, y - pad_y, w + pad_x * 2.0, h + pad_y * 2.0)
    return QRectF(x, y, w, h)


def _shape_handle_at(item: dict, px: float, py: float, threshold: float = 16.0) -> Optional[str]:
    """Return which resize handle of a shape is at (px, py), or None."""
    # Shapes and text boxes cannot be resized once drawn
    return None


def _resize_shape(item: dict, handle: str, px: float, py: float, initial_w: float = None, initial_fs: int = None):
    """Mutate a shape item's start/end based on dragging 'handle' to (px, py)."""
    # Shapes and text boxes cannot be resized once drawn
    return


def _draw_shape_handles(p: QPainter, item: dict, scale: float = 1.0):
    """Draw selection bounding box around selected text item."""
    if item.get('type') != 'text':
        return
    p.save()
    r = _shape_bounding_rect(item)
    pen_shadow = QPen(QColor(0, 0, 0, 160), 2.2 / scale, Qt.PenStyle.SolidLine)
    p.setPen(pen_shadow)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(r, 6.0 / scale, 6.0 / scale)

    pen_red = QPen(QColor("#EF4444"), 1.8 / scale, Qt.PenStyle.DashLine)
    p.setPen(pen_red)
    p.drawRoundedRect(r, 6.0 / scale, 6.0 / scale)
    p.restore()


class _SelectionActionBar(QWidget):
    """Floating action bar shown next to a selected item with [Edit] and [Delete] buttons."""
    edit_requested = pyqtSignal()
    delete_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(30)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("""
            _SelectionActionBar {
                background: rgba(26, 26, 30, 245);
                border: 1px solid #444448;
                border-radius: 6px;
            }
            QPushButton {
                background: #28282C;
                color: #FFFFFF;
                border: 1px solid #3E3E42;
                border-radius: 4px;
                padding: 3px 8px;
                font-family: 'Segoe UI';
                font-size: 11px;
                font-weight: 600;
            }
            QPushButton:hover { background: #38383E; }
            QPushButton#btn_delete:hover { background: #DC2626; border-color: #EF4444; }
        """)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 3, 4, 3)
        lay.setSpacing(4)

        edit_icon = QIcon(_asset('pencil.png')) if os.path.isfile(_asset('pencil.png')) else (QIcon(_asset('ve_edit.png')) if os.path.isfile(_asset('ve_edit.png')) else QIcon())
        delete_icon = QIcon(_asset('delete.png')) if os.path.isfile(_asset('delete.png')) else (QIcon(_asset('clear_all.png')) if os.path.isfile(_asset('clear_all.png')) else QIcon())

        self._btn_edit = QPushButton(" Edit")
        if not edit_icon.isNull():
            self._btn_edit.setIcon(edit_icon)
            self._btn_edit.setIconSize(QSize(13, 13))
        self._btn_edit.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_edit.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._btn_edit.clicked.connect(self.edit_requested.emit)
        lay.addWidget(self._btn_edit)

        self._btn_delete = QPushButton(" Delete")
        self._btn_delete.setObjectName("btn_delete")
        if not delete_icon.isNull():
            self._btn_delete.setIcon(delete_icon)
            self._btn_delete.setIconSize(QSize(13, 13))
        self._btn_delete.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_delete.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._btn_delete.clicked.connect(self.delete_requested.emit)
        lay.addWidget(self._btn_delete)

        self.adjustSize()

    def set_is_text(self, is_text: bool):
        self._btn_edit.setVisible(is_text)
        self.adjustSize()


def _smooth_points(points: list, window: int = 5, passes: int = 2) -> list:
    """Apply a multi-pass moving average to mathematically smooth wobbly mouse coordinate paths.
    Window size adapts to stroke length: short strokes get lighter smoothing to preserve detail."""
    n = len(points)
    if n < 3:
        return points

    # Adaptive window: scale with stroke length (min 3 for short strokes, max 7 for long ones)
    adaptive_window = max(3, min(7, int(math.log2(max(n, 4)))))
    w = adaptive_window if window == 5 else window  # Use adaptive unless explicitly overridden

    # Use at least 2 passes for long strokes to keep handwriting smooth
    adaptive_passes = 2 if n >= 10 else 1

    res = list(points)
    for _ in range(max(passes, adaptive_passes)):
        smoothed = [res[0]]
        for i in range(1, len(res) - 1):
            start = max(0, i - w // 2)
            end = min(len(res), i + w // 2 + 1)
            wx = sum(p[0] for p in res[start:end]) / (end - start)
            wy = sum(p[1] for p in res[start:end]) / (end - start)
            smoothed.append((wx, wy))
        smoothed.append(res[-1])
        res = smoothed
    return res


def _laser_dot_pixmap(size: int, color: QColor) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    center = QPointF(size / 2.0, size / 2.0)
    laser_color = QColor(color)
    glow = QColor(laser_color)
    glow.setAlpha(90)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(glow)
    p.drawEllipse(center, size * 0.25, size * 0.25)
    p.setBrush(laser_color)
    p.drawEllipse(center, size * 0.14, size * 0.14)
    p.setPen(QPen(QColor(255, 255, 255, 220), max(1.0, size / 32.0)))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(center, size * 0.14, size * 0.14)
    p.end()
    return pixmap


def get_tool_cursor(tool: str, color: QColor, thickness: str = 'normal') -> QCursor:
    """Return the context-aware cursor for the selected tool and color."""
    if not tool or tool == 'pointer':
        return QCursor(Qt.CursorShape.ArrowCursor)

    if tool == 'laser':
        pixmap = _laser_dot_pixmap(32, color)
        return QCursor(pixmap, 16, 16)

    from tool_cursors import tool_cursor
    if tool in ('pencil', 'highlighter'):
        width = THICKNESS_LEVELS.get(tool, {}).get(thickness, 4)
        return tool_cursor(tool, QColor(color).name(), width)
    if tool == 'eraser':
        return tool_cursor('crosshair')
    if tool in ('text', 'crop'):

        return tool_cursor(tool)
    return tool_cursor('crosshair')

# ── Shared paint helper ──────────────────────────────────────────────────────

def _paint_laser_path(p, path, color, width, opacity):
    p.setBrush(Qt.BrushStyle.NoBrush)
    for extra, alpha in ((6, 0.025), (4, 0.045), (2, 0.10), (0, 0.95)):
        tint = QColor(color)
        tint.setAlphaF(max(0.0, min(1.0, opacity * alpha)))
        p.setPen(QPen(tint, max(2.0, width * 0.8) + extra,
                      Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.drawPath(path)


def draw_annotation_item(p: QPainter, item: dict):
    """Draw a single annotation item using the given QPainter."""
    # History-action metadata is never paintable content.
    if item.get('_action'):
        return
    color = QColor(item['color'])
    t = item['type']

    if t in ('pencil', 'highlighter', 'laser'):
        c = QColor(color)
        if t == 'highlighter':
            c.setAlphaF(item.get('opacity', 0.4))
        elif t == 'laser':
            c.setAlphaF(item.get('opacity', 1.0))
            c = c.lighter(125)
        p.setBrush(Qt.BrushStyle.NoBrush)
        points = item['points']
        if len(points) == 1 and t == 'laser':
            path = QPainterPath()
            path.moveTo(float(points[0][0]), float(points[0][1]))
            path.lineTo(float(points[0][0])+0.01, float(points[0][1]))
            _paint_laser_path(p, path, color, item['width'], item.get('opacity', 1.0))
        elif len(points) > 1:
            path = QPainterPath()
            path.moveTo(float(points[0][0]), float(points[0][1]))
            if len(points) == 2:
                path.lineTo(float(points[1][0]), float(points[1][1]))
            else:
                for i in range(1, len(points) - 1):
                    p1 = points[i]
                    p2 = points[i + 1]
                    x1, y1 = float(p1[0]), float(p1[1])
                    
                    if len(p1) > 2 and p1[2]:
                        path.lineTo(x1, y1)
                    else:
                        x2, y2 = float(p2[0]), float(p2[1])
                        mid_x = (x1 + x2) / 2.0
                        mid_y = (y1 + y2) / 2.0
                        path.quadTo(x1, y1, mid_x, mid_y)
                path.lineTo(float(points[-1][0]), float(points[-1][1]))
            if t == 'laser':
                _paint_laser_path(p, path, color, item['width'], item.get('opacity', 1.0))
            else:
                p.setPen(QPen(c, item['width'], Qt.PenStyle.SolidLine,
                              Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
                p.drawPath(path)

    elif t == 'text':
        p.save()
        transform = p.worldTransform()
        display_scale = 1.0
        if (abs(transform.m12()) < 1e-8 and abs(transform.m21()) < 1e-8
                and transform.m11() > 0 and abs(transform.m11() - transform.m22()) < 1e-8):
            display_scale = transform.m11()
        font_size = item.get('font_size', 16)
        weight = QFont.Weight.Bold if item.get('bold', False) else QFont.Weight.Normal
        font = QFont("Segoe UI", font_size, weight)
        font.setPointSizeF(float(font_size) * display_scale)
        font.setItalic(item.get('italic', False))
        font.setUnderline(item.get('underline', False))
        p.setFont(font)
        fm = QFontMetrics(font)
        line_height = max(fm.lineSpacing(), 16 * display_scale)
        
        text = item.get('text', '')
        lines = text.split('\n')
        
        if 'start' in item and 'end' in item:
            sx, sy = item['start']
            ex, ey = item['end']
            x = min(sx, ex)
            y = min(sy, ey)
        else:
            x, y = item.get('pos', (0, 0))

        # Hint the committed glyphs at the same screen font size as the editor,
        # instead of scaling already-hinted native-size glyphs after commit.
        if display_scale != 1.0:
            origin = transform.map(QPointF(x, y))
            x, y = origin.x(), origin.y()
            p.setWorldTransform(QTransform())

        # Calculate exact tight width and height for all lines
        max_w = max((fm.horizontalAdvance(ln) for ln in lines), default=20)
        tight_w = max(float(max_w), 20.0)
        total_h = max(float(len(lines) * line_height), float(line_height))
        
        pad_x = 8.0 * display_scale
        pad_y = 6.0 * display_scale
        draw_rect = QRectF(x - pad_x, y - pad_y, tight_w + pad_x * 2.0, total_h + pad_y * 2.0)

        # High quality antialiased rounded background wrapping tightly horizontally and vertically
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(20, 20, 24, 190))
        p.drawRoundedRect(draw_rect, 6.0, 6.0)
        p.restore()

        # Draw each line cleanly at exact baseline
        p.setPen(QPen(color))
        ascent = fm.ascent()
        for i, line_text in enumerate(lines):
            line_y = y + i * line_height + ascent
            p.drawText(QPointF(x, line_y), line_text)

        p.restore()

    elif t == 'circle':
        pen = QPen(color, item['width'], Qt.PenStyle.SolidLine,
                   Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        sx, sy = item['start']
        ex, ey = item['end']
        rect = QRectF(float(min(sx, ex)), float(min(sy, ey)),
                      float(abs(ex - sx)), float(abs(ey - sy)))
        p.drawEllipse(rect)

    elif t == 'rect':
        pen = QPen(color, item['width'], Qt.PenStyle.SolidLine,
                   Qt.PenCapStyle.SquareCap, Qt.PenJoinStyle.MiterJoin)
        pen.setMiterLimit(10.0)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        sx, sy = item['start']
        ex, ey = item['end']
        rect = QRectF(float(min(sx, ex)), float(min(sy, ey)),
                      float(abs(ex - sx)), float(abs(ey - sy)))
        p.drawRect(rect)

    elif t == 'arrow':
        pen = QPen(color, item['width'], Qt.PenStyle.SolidLine,
                   Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        sx, sy = item['start']
        ex, ey = item['end']

        # Arrowhead scaled by stroke width
        dx = ex - sx
        dy = ey - sy
        length = math.hypot(dx, dy)
        if length > 0:
            angle = math.atan2(dy, dx)
            # Keep the head visibly proportional across every thickness.  The
            # old 10px floor made Thin and Normal look almost identical, while
            # the unbounded multiplier made Huge unnecessarily dominant.
            arrow_size = _arrow_head_size(item['width'], length)

            # ARROW FIX: Shorten the line so it ends at the arrowhead base,
            # preventing the round cap from poking past the arrowhead tip.
            # Using QPointF prevents integer rounding errors that make the line look off-center.
            base_distance = arrow_size * math.cos(math.pi / 6) - (item['width'] / 2.0)
            line_end_x = ex - base_distance * math.cos(angle)
            line_end_y = ey - base_distance * math.sin(angle)
            p.drawLine(QPointF(sx, sy), QPointF(line_end_x, line_end_y))

            p1x = ex - arrow_size * math.cos(angle - math.pi / 6)
            p1y = ey - arrow_size * math.sin(angle - math.pi / 6)
            p2x = ex - arrow_size * math.cos(angle + math.pi / 6)
            p2y = ey - arrow_size * math.sin(angle + math.pi / 6)

            tri = QPainterPath()
            tri.moveTo(float(ex), float(ey))
            tri.lineTo(float(p1x), float(p1y))
            tri.lineTo(float(p2x), float(p2y))
            tri.closeSubpath()
            p.fillPath(tri, QBrush(color))
        else:
            p.drawLine(int(sx), int(sy), int(ex), int(ey))


# ─────────────────────────────────────────────────────────────────────────────
#  _ToastWidget — Animated Tool Switch Feedback
# ─────────────────────────────────────────────────────────────────────────────

class _ToastWidget(QWidget):
    """Small pill-shaped widget with an icon + text that flashes when switching tools."""
    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setObjectName("ToastWidget")
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 16, 8)
        layout.setSpacing(10)
        
        self.icon_label = QLabel()
        self.icon_label.setFixedSize(20, 20)
        self.icon_label.setScaledContents(True)
        layout.addWidget(self.icon_label)
        
        self.text_label = QLabel()
        self.text_label.setStyleSheet("color: white; font-size: 14px; font-weight: bold; font-family: 'Segoe UI'; border: none; background: transparent;")
        layout.addWidget(self.text_label)
        
        self.hide()

    def paintEvent(self, event):
        # A QWidget subclass on a translucent canvas does not reliably paint
        # its QSS background. Paint an opaque backing before the child labels.
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#424B5D"), 1.0))
        painter.setBrush(QColor("#151923"))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 12.0, 12.0)

    def show_message(self, text: str, icon_path: str):
        self.text_label.setText(text)
        if os.path.exists(icon_path):
            self.icon_label.setPixmap(QPixmap(icon_path))
            self.icon_label.show()
        else:
            self.icon_label.hide()
            
        self.adjustSize()
        self.show()
        self.raise_()

# ─────────────────────────────────────────────────────────────────────────────
#  AnnotationCanvas — Live Recording Overlay

class AnnotationCanvas(QWidget):
    """
    Transparent overlay positioned exactly over the recording region.
    NOT excluded from screen capture — drawn annotations appear in the video.
    """
    undo_redo_state_changed = pyqtSignal(bool, bool)
    pause_requested = pyqtSignal()
    close_requested = pyqtSignal()

    def __init__(self):
        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        super().__init__(None, flags)

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setMouseTracking(True)
        self.setCursor(shape_cursor(Qt.CursorShape.CrossCursor))
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        # Position exactly over the entire virtual desktop (all monitors)
        desktop_rect = QApplication.primaryScreen().virtualGeometry()
        
        # Prevent Windows Taskbar from auto-hiding by making the canvas 1px shorter than the virtual desktop
        desktop_rect.adjust(0, 0, 0, -1)
        
        self.setGeometry(desktop_rect)

        self._items: List[dict] = []
        self._redo_stack: List[dict] = []
        self._current_item: Optional[dict] = None

        self._tool = 'pencil'
        self._color = QColor('#FF3B30')
        self._active_thickness = 'normal'
        self._drawing = False
        self._interactive = True
        self._erase_action_items = []
        self._erase_last_pos: Optional[QPointF] = None
        self._erase_original_indexes = {}

        # Transient laser trails never enter permanent annotation history.
        self._laser_trails: List[dict] = []
        self._laser_fade_at: Optional[float] = None
        self._laser_expires_at: Optional[float] = None
        self._laser_fade_timer = QTimer(self)
        self._laser_fade_timer.setInterval(33)
        self._laser_fade_timer.timeout.connect(self._advance_laser_trails)

        # Shape resize / move state
        self._selected_shape_idx: Optional[int] = None
        self._resize_handle: Optional[str] = None
        self._resizing = False
        self._moving_shape = False
        self._move_offset = (0.0, 0.0)
        self._initial_width = 0.0
        self._initial_font_size = 16

        # Text input state
        self._text_input_active = False
        self._text_pos = None
        self._text_buffer = ""
        self._text_box_w = 200.0   # Default text box width
        self._text_box_h = 40.0    # Default text box height (auto-expands)
        self._text_box_creating = False  # True while dragging to create box
        self._text_box_drag_start = None
        self._editing_text_backup = None
        self._editing_text_index = None
        self._cursor_visible = True
        self._cursor_timer = QTimer(self)
        self._cursor_timer.setInterval(530)
        self._cursor_timer.timeout.connect(self._blink_cursor)

        # Text formatting toolbar (child widget, hidden until text input starts)
        self._text_bar = _TextEditBar(self)
        self._text_bar.hide()
        self._text_bar.formatting_changed.connect(self._apply_text_editor_style)
        self._text_edit = _AnnotationPlainTextEdit(self)
        self._text_edit.hide()
        self._text_edit.commit_requested.connect(self._commit_text)
        self._text_edit.cancel_requested.connect(self._cancel_text)
        self._text_edit.content_resized.connect(self._auto_resize_text_editor)

        # Selection action bar (Edit / Delete floating mini-bar)
        self._action_bar = _SelectionActionBar(self)
        self._action_bar.hide()
        self._action_bar.edit_requested.connect(self._on_action_bar_edit)
        self._action_bar.delete_requested.connect(self._on_action_bar_delete)

        self._text_box_initial_h = 40.0
        self._did_move_shape = False
        self._press_pos = None

        # PERF-004/008: Repaint throttling to prevent 100+ full repaints/sec on high-DPI
        self._repaint_dirty = False
        self._repaint_timer = QTimer(self)
        self._repaint_timer.setInterval(16)  # ~60fps cap
        self._repaint_timer.timeout.connect(self._flush_repaint)

        # Shortcuts
        QShortcut(QKeySequence("Ctrl+Z"), self, self.undo)
        QShortcut(QKeySequence("Ctrl+Y"), self, self.redo)
        QShortcut(QKeySequence("Ctrl+Shift+Z"), self, self.redo)
        QShortcut(QKeySequence(Qt.Key.Key_Space), self, self._on_space_pressed)
        QShortcut(QKeySequence("Delete"), self, self._on_delete_pressed)
        QShortcut(QKeySequence("Backspace"), self, self._on_delete_pressed)
        QShortcut(QKeySequence("Esc"), self, self._on_esc_pressed)
        
        # Tool switch toast
        self._toast_widget = _ToastWidget(self)
        self._toast_timer = QTimer(self)
        self._toast_timer.timeout.connect(self._toast_widget.hide)

    def _show_selection_action_bar(self, idx: int):
        if idx is None or idx < 0 or idx >= len(self._items):
            if hasattr(self, '_action_bar'):
                self._action_bar.hide()
            return
        item = self._items[idx]
        is_text = (item.get('type') == 'text')
        self._action_bar.set_is_text(is_text)
        r = _shape_bounding_rect(item)
        bx = int(r.left())
        by = int(r.top()) - self._action_bar.height() - 6
        if by < 5:
            by = int(r.bottom()) + 6
        self._action_bar.move(bx, by)
        self._action_bar.show()
        self._action_bar.raise_()

    def _on_action_bar_edit(self):
        if self._selected_shape_idx is not None and 0 <= self._selected_shape_idx < len(self._items):
            idx = self._selected_shape_idx
            self._action_bar.hide()
            self._begin_edit_text(idx)

    def _on_action_bar_delete(self):
        if self._selected_shape_idx is not None and 0 <= self._selected_shape_idx < len(self._items):
            idx = self._selected_shape_idx
            item = self._items[idx]
            erase_action = {'_action': 'erase', '_erased_items': [(idx, item)]}
            self._items.pop(idx)
            self._items.append(erase_action)
            self._redo_stack.clear()
            self._deselect_shape()
            self.modified()
            self.update()

    def _on_delete_pressed(self):
        if self._text_input_active:
            return
        if self._selected_shape_idx is not None and 0 <= self._selected_shape_idx < len(self._items):
            self._on_action_bar_delete()
        # No selection: do nothing. Clear All is a separate explicit action.

    def _on_space_pressed(self):
        if not self._text_input_active:
            self.pause_requested.emit()

    def _on_esc_pressed(self):
        if self._text_input_active:
            self._cancel_text()
        elif self._selected_shape_idx is not None:
            self._deselect_shape()
        else:
            self.close_requested.emit()

    def keyPressEvent(self, event):
        if self._text_input_active:
            super().keyPressEvent(event)
            return

        key = event.key()
        mods = event.modifiers()
        ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
        shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)

        if ctrl and not shift and key == Qt.Key.Key_Z:
            self.undo()
            event.accept()
            return
        elif (ctrl and key == Qt.Key.Key_Y) or (ctrl and shift and key == Qt.Key.Key_Z):
            self.redo()
            event.accept()
            return
        elif key == Qt.Key.Key_Space:
            self._on_space_pressed()
            event.accept()
            return
        elif key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self._on_delete_pressed()
            event.accept()
            return
        elif key == Qt.Key.Key_Escape:
            self._on_esc_pressed()
            event.accept()
            return

        super().keyPressEvent(event)

    # ── Public API ────────────────────────────────────────────────────────────

    def set_interactive(self, interactive: bool):
        """Toggle between drawing mode and pass-through mode."""
        self._interactive = interactive
        if interactive:
            self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
            self._update_cursor()
            self.show()
            
            # Use native Windows API to enforce topmost if possible, to avoid Qt layer issues
            if getattr(sys, 'platform', '') == 'win32' and _user32:
                HWND_TOPMOST = -1
                SWP_NOSIZE = 0x0001
                SWP_NOMOVE = 0x0002
                SWP_NOACTIVATE = 0x0010
                try:
                    _user32.SetWindowPos(int(self.winId()), HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
                except Exception:
                    pass
                    
            self.activateWindow()
            self.setFocus()
        else:
            self._commit_text()
            self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            self.unsetCursor()

    @property
    def has_annotations(self) -> bool:
        return len(self._items) > 0

    def _update_cursor(self):
        if self._interactive:
            self.setCursor(get_tool_cursor(self._tool, self._color, self._active_thickness))

    def _show_toast(self, message: str, icon_name: str, duration_ms: int = 1500,
                    center_screen: bool = False):
        """Show lightweight tool feedback without taking input focus."""
        cx = self.width() // 2 - self._toast_widget.width() // 2
        cy = self.height() // 2 - self._toast_widget.height() // 2 if center_screen else self.height() - 220
        self._toast_widget.move(cx, cy)
        self._toast_widget.show_message(message, _asset(icon_name))
        
        # Re-center after content change
        self._toast_widget.adjustSize()
        cx = self.width() // 2 - self._toast_widget.width() // 2
        cy = self.height() // 2 - self._toast_widget.height() // 2 if center_screen else self.height() - 220
        self._toast_widget.move(cx, cy)

        self._toast_timer.start(duration_ms)

    def set_annotation_paused(self, paused: bool):
        """Switch canvas interaction and clearly confirm the new mode."""
        self.set_interactive(not paused)
        if paused:
            self._show_toast(
                "Annotation paused — click Play or press Space to continue",
                "play.png", duration_ms=3200, center_screen=True,
            )
        else:
            self._show_toast(
                "Annotation is active — draw on the screen",
                "pause.png", duration_ms=2600, center_screen=True,
            )

    def set_tool(self, tool: str):
        self._commit_text()
        self._deselect_shape()
        self._tool = tool
        self._update_cursor()
        
        tool_info = {
            'pencil': ('Pencil', 'pencil.png'),
            'highlighter': ('Highlighter', 'highlighter.png'),
            'eraser': ('Eraser', 'eraser.png'),
            'text': ('Text', 'text_tool.png'),
            'circle': ('Circle', 'shape_circle.png'),
            'rect': ('Rectangle', 'shape_rect.png'),
            'arrow': ('Arrow', 'shape_arrow.png'),
            'laser': ('Laser pointer', ''),
        }
        if tool in tool_info:
            name, icon = tool_info[tool]
            self._show_toast(name, icon)

    def set_color(self, color: QColor):
        self._color = color
        self._apply_text_editor_style()
        self._update_cursor()
        
    def set_thickness(self, thickness_key: str):
        self._active_thickness = thickness_key
        self._update_cursor()

    def modified(self):
        _trim_history(self._items, self._redo_stack)
        self.undo_redo_state_changed.emit(bool(self._items), bool(self._redo_stack))

    def undo(self):
        if self._items:
            item = self._items.pop()
            if item.get('_action') == 'erase':
                # BUG-008 Fix: Restore items at their exact original z-index
                for idx, erased in sorted(item['_erased_items'], key=lambda entry: entry[0]):
                    self._items.insert(min(idx, len(self._items)), erased)
            elif item.get('_action') == 'clear':
                self._items = list(item['_cleared_items'])
            elif item.get('_action') == 'update':
                item['_target'].clear()
                item['_target'].update(item['_before'])
            self._redo_stack.append(item)
            self.modified()
            self.update()

    def redo(self):
        if self._redo_stack:
            item = self._redo_stack.pop()
            if item.get('_action') == 'erase':
                # BUG-008 Fix: Redo an erase → remove the items again
                erased_set = set(id(e) for _, e in item['_erased_items'])
                self._items = [i for i in self._items if id(i) not in erased_set]
            elif item.get('_action') == 'clear':
                self._items.clear()
            elif item.get('_action') == 'update':
                item['_target'].clear()
                item['_target'].update(item['_after'])
            self._items.append(item)
            self.modified()
            self.update()

    def clear_all(self):
        had_laser = bool(self._laser_trails) or (
            self._current_item is not None and self._current_item.get('type') == 'laser'
        )
        self._laser_trails.clear()
        self._laser_fade_at = None
        self._laser_expires_at = None
        self._laser_fade_timer.stop()
        if had_laser:
            self._current_item = None
            self._drawing = False
        if not self._items:
            if had_laser:
                self.update()
            return
        clear_action = {'_action': 'clear', '_cleared_items': list(self._items)}
        self._items = [clear_action]
        self._redo_stack.clear()
        self._current_item = None
        self.modified()
        self.update()

    def _finish_laser_trail(self, trail: dict) -> None:
        now = time.monotonic()
        trail['opacity'] = 1.0
        self._laser_trails.append(trail)
        self._laser_fade_at = now + LASER_TRAIL_HOLD_MS / 1000.0
        self._laser_expires_at = self._laser_fade_at + LASER_TRAIL_FADE_MS / 1000.0
        for existing in self._laser_trails:
            existing['opacity'] = 1.0
        if not self._laser_fade_timer.isActive():
            self._laser_fade_timer.start()

    def _pause_laser_expiry(self) -> None:
        """Keep every trail visible while another laser gesture is active."""
        self._laser_fade_at = None
        self._laser_expires_at = None
        self._laser_fade_timer.stop()
        for trail in self._laser_trails:
            trail['opacity'] = 1.0

    def _advance_laser_trails(self) -> None:
        if self._drawing and self._current_item is not None and self._current_item.get('type') == 'laser':
            return
        if self._laser_fade_at is None or self._laser_expires_at is None:
            self._laser_fade_timer.stop()
            return
        now = time.monotonic()
        if now >= self._laser_expires_at:
            self._laser_trails.clear()
            self._laser_fade_at = None
            self._laser_expires_at = None
            self._laser_fade_timer.stop()
        elif now > self._laser_fade_at:
            opacity = max(
                0.0,
                (self._laser_expires_at - now) / (LASER_TRAIL_FADE_MS / 1000.0),
            )
            for trail in self._laser_trails:
                trail['opacity'] = opacity
        self.update()

    def _dist_to_segment(self, px, py, x1, y1, x2, y2):
        dx = x2 - x1
        dy = y2 - y1
        if dx == 0 and dy == 0:
            return math.hypot(px - x1, py - y1)
        t = ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)
        t = max(0, min(1, t))
        nearest_x = x1 + t * dx
        nearest_y = y1 + t * dy
        return math.hypot(px - nearest_x, py - nearest_y)

    def _hit_test(self, pos, item: dict) -> bool:
        t = item['type']
        px, py = float(pos.x()), float(pos.y())
        base_threshold = 12.0 # pixels
        widths = THICKNESS_LEVELS.get(t, {})
        stroke_width = float(item.get('width', widths.get(item.get('thickness', 'normal'), 4)))
        th = max(base_threshold, stroke_width / 2.0 + 4.0)

        if t in ('pencil', 'highlighter'):
            points = item['points']
            if points:
                xs = [p[0] for p in points]
                ys = [p[1] for p in points]
                if px < min(xs) - th or px > max(xs) + th:
                    return False
                if py < min(ys) - th or py > max(ys) + th:
                    return False
            if len(points) == 1:
                return math.hypot(px - points[0][0], py - points[0][1]) < th
            for i in range(len(points) - 1):
                x1, y1 = points[i][:2]
                x2, y2 = points[i+1][:2]
                if self._dist_to_segment(px, py, x1, y1, x2, y2) < th:
                    return True
            return False

        elif t == 'rect':
            sx, sy = item['start']
            ex, ey = item['end']
            rect = QRectF(float(min(sx, ex)), float(min(sy, ey)), float(abs(ex - sx)), float(abs(ey - sy)))
            return rect.adjusted(-th, -th, th, th).contains(QPointF(pos))

        elif t == 'circle':
            sx, sy = item['start']
            ex, ey = item['end']
            rx, ry = abs(ex - sx) / 2.0, abs(ey - sy) / 2.0
            cx, cy = (sx + ex) / 2.0, (sy + ey) / 2.0
            if rx == 0 or ry == 0: return False
            val = ((px - cx)**2) / ((rx + th)**2) + ((py - cy)**2) / ((ry + th)**2)
            return val <= 1.0

        elif t == 'arrow':
            sx, sy = item['start']
            ex, ey = item['end']
            return self._dist_to_segment(px, py, sx, sy, ex, ey) < th

        elif t == 'text':
            if 'start' in item and 'end' in item:
                sx, sy = item['start']
                ex, ey = item['end']
                rect = QRectF(float(min(sx, ex)), float(min(sy, ey)), float(abs(ex - sx)), float(abs(ey - sy)))
                return rect.adjusted(-th, -th, th, th).contains(QPointF(pos))
            
            tx, ty = item.get('pos', (0,0))
            fs = item.get('font_size', 16)
            weight = QFont.Weight.Bold if item.get('bold', True) else QFont.Weight.Normal
            font = QFont("Segoe UI", fs, weight)
            font.setItalic(item.get('italic', False))
            font.setUnderline(item.get('underline', False))
            fm = QFontMetrics(font)
            lines = item['text'].split('\n')
            max_w = max((fm.horizontalAdvance(ln) for ln in lines), default=0)
            total_h = fm.height() * len(lines)
            rect = QRectF(float(tx), float(ty) - float(fm.ascent()), float(max_w), float(total_h))
            return rect.adjusted(-th, -th, th, th).contains(QPointF(pos))

        return False

    # ── Mouse Events ──────────────────────────────────────────────────────────

    def _deselect_shape(self):
        """Deselect any currently-selected shape or text."""
        if self._selected_shape_idx is not None:
            self._selected_shape_idx = None
            self._resize_handle = None
            self._resizing = False
            self._moving_shape = False
            if hasattr(self, '_action_bar'):
                self._action_bar.hide()
            self.update()

    def mouseDoubleClickEvent(self, event):
        if not self._interactive or event.button() != Qt.MouseButton.LeftButton:
            return
        pos = event.position().toPoint()
        for i in range(len(self._items) - 1, -1, -1):
            item = self._items[i]
            if item.get('type') == 'text' and 'start' in item and self._hit_test(pos, item):
                self._begin_edit_text(i)
                event.accept()
                return
        super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event):
        if not self._interactive or event.button() != Qt.MouseButton.LeftButton:
            return
        pos = event.position().toPoint()
        px, py = float(pos.x()), float(pos.y())

        # 0. Eraser handles its own hit testing
        if self._tool == 'eraser':
            self._deselect_shape()
            self._drawing = True
            self._erase_action_items = []
            self._erase_original_indexes = {
                id(item): index for index, item in enumerate(self._items)
            }
            self._erase_last_pos = QPointF(pos)
            self._erase_at(pos)
            return

        # Laser gestures ignore permanent-item selection and pause the shared
        # expiry countdown. Every prior laser trail remains fully visible until
        # this new gesture ends and starts one fresh countdown for the group.
        if self._tool == 'laser':
            if self._text_input_active:
                self._commit_text()
            self._deselect_shape()
            self._pause_laser_expiry()
            self._drawing = True
            self._current_item = {
                'type': 'laser',
                'points': [(pos.x(), pos.y(), False)],
                'color': self._color.name(),
                'width': 5.0,
                'opacity': 1.0,
            }
            self.update()
            return

        # 1. Check if we're clicking inside an active text box (to keep typing)
        if self._text_input_active and self._is_inside_text_box(pos):
            return

        # 2. Commit active text if clicking outside
        if self._text_input_active:
            self._commit_text()

        # 3. Check for move hit on already selected text item
        if self._selected_shape_idx is not None and 0 <= self._selected_shape_idx < len(self._items):
            sel_item = self._items[self._selected_shape_idx]
            if sel_item.get('type') == 'text' and 'start' in sel_item:
                r = _shape_bounding_rect(sel_item)
                if r.adjusted(-12, -12, 12, 12).contains(QPointF(px, py)):
                    self._moving_shape = True
                    self._move_before = dict(self._items[self._selected_shape_idx])
                    self._did_move_shape = False
                    self._press_pos = pos
                    self._move_offset = (px - r.left(), py - r.top())
                    return
                else:
                    self._deselect_shape()

        # 4. Check for selecting an existing TEXT item (only text can be selected/moved)
        for i in range(len(self._items) - 1, -1, -1):
            item = self._items[i]
            if item.get('type') == 'text' and 'start' in item and self._hit_test(pos, item):
                self._selected_shape_idx = i
                r = _shape_bounding_rect(item)
                self._moving_shape = True
                self._move_before = dict(self._items[self._selected_shape_idx])
                self._did_move_shape = False
                self._press_pos = pos
                self._move_offset = (px - r.left(), py - r.top())
                self._show_selection_action_bar(i)
                self.update()
                return

        # 5. No text item hit -> Start new drawing
        self._deselect_shape()
        self._did_move_shape = False
        self._press_pos = None
        
        if self._tool == 'text':
            self._text_box_creating = True
            self._text_box_drag_start = (px, py)
            self._text_pos = (px, py)
            self._text_box_w = 0.0
            self._text_box_h = 0.0
            self._drawing = True
            return

        self._drawing = True
        self._redo_stack.clear()

        if self._tool in ('pencil', 'highlighter'):
            group = self._tool
            width = THICKNESS_LEVELS.get(group, {}).get(self._active_thickness, 4 if group == 'pencil' else 20)
            opacity = 1.0 if self._tool == 'pencil' else 0.4
            self._current_item = {
                'type': self._tool,
                'points': [(pos.x(), pos.y(), False)],
                'color': self._color.name(),
                'width': width,
                'opacity': opacity,
            }
        elif self._tool in ('circle', 'rect', 'arrow'):
            width = THICKNESS_LEVELS.get('shapes', {}).get(self._active_thickness, 4)
            self._current_item = {
                'type': self._tool,
                'start': (pos.x(), pos.y()),
                'end': (pos.x(), pos.y()),
                'color': self._color.name(),
                'width': width,
            }

    def mouseMoveEvent(self, event):
        if not self._interactive:
            return
        pos = event.position().toPoint()
        px, py = float(pos.x()), float(pos.y())

        # ── Text box creation drag ──
        if self._text_box_creating and self._text_box_drag_start:
            sx, sy = self._text_box_drag_start
            self._text_pos = (min(sx, px), min(sy, py))
            self._text_box_w = abs(px - sx)
            self._text_box_h = abs(py - sy)
            self.update()
            return

        # ── Shape/text move drag ──
        if self._moving_shape and self._selected_shape_idx is not None:
            if self._press_pos and (pos - self._press_pos).manhattanLength() > 4:
                self._did_move_shape = True
            sel_item = self._items[self._selected_shape_idx]
            r = _shape_bounding_rect(sel_item)
            new_x = px - self._move_offset[0]
            new_y = py - self._move_offset[1]
            dx = new_x - r.left()
            dy = new_y - r.top()
            sx, sy = sel_item['start']
            ex, ey = sel_item['end']
            sel_item['start'] = (sx + dx, sy + dy)
            sel_item['end'] = (ex + dx, ey + dy)
            self._show_selection_action_bar(self._selected_shape_idx)
            self._schedule_repaint()  # PERF-009: Throttle to 60fps
            return

        # ── Shape resize drag ──
        if self._resizing and self._selected_shape_idx is not None and self._resize_handle:
            sel_item = self._items[self._selected_shape_idx]
            if sel_item.get('type') == 'text':
                _resize_shape(sel_item, self._resize_handle, px, py, 
                              initial_w=self._initial_width, initial_fs=self._initial_font_size)
            else:
                _resize_shape(sel_item, self._resize_handle, px, py)
            self._show_selection_action_bar(self._selected_shape_idx)
            self._schedule_repaint()  # PERF-009: Throttle to 60fps
            return

        # ── Hover cursor for resize/move handles ──
        if self._selected_shape_idx is not None and 0 <= self._selected_shape_idx < len(self._items):
            sel_item = self._items[self._selected_shape_idx]
            if 'start' in sel_item:
                handle = _shape_handle_at(sel_item, px, py, threshold=16.0)
                if handle:
                    self.setCursor(shape_cursor(_HANDLE_CURSORS.get(handle, Qt.CursorShape.SizeAllCursor)))
                    return
                r = _shape_bounding_rect(sel_item)
                if r.adjusted(-8, -8, 8, 8).contains(QPointF(px, py)):
                    self.setCursor(shape_cursor(Qt.CursorShape.SizeAllCursor))
                    return
            self._update_cursor()

        if self._tool == 'eraser' and self._drawing:
            self._erase_sweep(self._erase_last_pos, QPointF(pos))
            self._erase_last_pos = QPointF(pos)
            return

        if not self._drawing or not self._current_item:
            return

        if self._current_item['type'] in ('pencil', 'highlighter', 'laser'):
            pts = self._current_item['points']
            nx, ny = float(pos.x()), float(pos.y())
            is_ctrl = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
            is_alt = bool(event.modifiers() & Qt.KeyboardModifier.AltModifier)

            if 'anchor' not in self._current_item:
                self._current_item['anchor'] = None

            if is_ctrl or is_alt:
                if self._current_item['anchor'] is None:
                    # Anchor straight line at starting position
                    self._current_item['anchor'] = pts[0] if pts else (nx, ny)
                    pts.append((nx, ny, True))
                else:
                    sx, sy = self._current_item['anchor'][0], self._current_item['anchor'][1]
                    dx, dy = nx - sx, ny - sy
                    if is_alt and (abs(dx) > 0.1 or abs(dy) > 0.1):
                        # Holding Alt -> Snap to 45 or 90 degrees
                        angle = math.atan2(dy, dx)
                        snap_angle = round(angle / (math.pi / 4)) * (math.pi / 4)
                        dist = math.hypot(dx, dy)
                        nx = sx + dist * math.cos(snap_angle)
                        ny = sy + dist * math.sin(snap_angle)
                    # Ctrl (without Alt) -> straight line at ANY angle (nx, ny unaltered)
                    pts[-1] = (nx, ny, True)
            else:
                self._current_item['anchor'] = None
                # Normal freehand drawing with interpolation
                if pts:
                    lx, ly = pts[-1][0], pts[-1][1]
                    dist = math.hypot(nx - lx, ny - ly)
                    steps = int(dist / 3.0)
                    if steps > 1:
                        for i in range(1, steps + 1):
                            ix = lx + (nx - lx) * (i / steps)
                            iy = ly + (ny - ly) * (i / steps)
                            pts.append((ix, iy, False))
                    else:
                        pts.append((nx, ny, False))
                else:
                    pts.append((nx, ny, False))
        elif self._current_item['type'] in ('circle', 'rect', 'arrow'):
            self._current_item['end'] = (pos.x(), pos.y())

        self._schedule_repaint()

    def _schedule_repaint(self):
        """PERF-008: Throttle repaints to ~60fps instead of calling update() on every mouse event."""
        if not self._repaint_dirty:
            self._repaint_dirty = True
            if not self._repaint_timer.isActive():
                self._repaint_timer.start()

    def _flush_repaint(self):
        """Actually trigger the repaint if dirty."""
        if self._repaint_dirty:
            self._repaint_dirty = False
            self.update()
        else:
            self._repaint_timer.stop()

    def _erase_sweep(self, start: Optional[QPointF], end: QPointF):
        if start is None:
            self._erase_at(end)
            return
        distance = math.hypot(end.x() - start.x(), end.y() - start.y())
        steps = max(1, int(math.ceil(distance / 4.0)))
        for step in range(1, steps + 1):
            amount = step / steps
            self._erase_at(QPointF(
                start.x() + (end.x() - start.x()) * amount,
                start.y() + (end.y() - start.y()) * amount,
            ))

    def _erase_at(self, pos):
        new_items = []
        changed = False
        for current_index, item in enumerate(self._items):
            if item.get('_action') or 'type' not in item:
                new_items.append(item)  # History records are not drawable/erasable.
                continue
            if self._hit_test(pos, item):
                if not any(existing is item for _, existing in self._erase_action_items):
                    original_index = self._erase_original_indexes.get(id(item), current_index)
                    self._erase_action_items.append((original_index, item))
                changed = True
            else:
                new_items.append(item)
        if changed:
            self._items = new_items
            self._redo_stack.clear()  # New action clears redo
            self._schedule_repaint()

    def mouseReleaseEvent(self, event):
        if not self._interactive:
            return

        # End text box creation
        if self._text_box_creating:
            self._text_box_creating = False
            if self._text_box_w > 10 and self._text_box_h > 10:
                self._text_box_initial_h = max(34.0, self._text_box_h)
                self._start_text_input(self._text_pos)
            else:
                # Click to place default box
                x, y, self._text_box_w, self._text_box_h = _fit_default_text_box(
                    self._text_pos[0], self._text_pos[1], 200.0, 40.0,
                    self.width(), self.height(),
                )
                self._text_pos = (x, y)
                self._text_box_initial_h = self._text_box_h
                self._start_text_input(self._text_pos)
            self._drawing = False
            return

        # End shape/text move
        if self._moving_shape:
            if self._selected_shape_idx is not None:
                target = self._items[self._selected_shape_idx]
                before = getattr(self, '_move_before', dict(target))
                if before != target:
                    self._items.append({'_action': 'update', '_target': target,
                                        '_before': before, '_after': dict(target)})
                    self._redo_stack.clear()
                    if hasattr(self, '_has_unsaved'):
                        self._has_unsaved = True
            self._moving_shape = False
            self._did_move_shape = False
            self._press_pos = None
            self.modified()
            if self._selected_shape_idx is not None:
                self._show_selection_action_bar(self._selected_shape_idx)
            self.update()
            return

        # End shape resize
        if self._resizing:
            self._resizing = False
            self._resize_handle = None
            self.modified()
            if self._selected_shape_idx is not None:
                self._show_selection_action_bar(self._selected_shape_idx)
            self.update()
            return

        if not self._drawing:
            return

        self._drawing = False
        if self._tool == 'eraser':
            if self._erase_action_items:
                self._items.append({
                    '_action': 'erase',
                    '_erased_items': sorted(self._erase_action_items, key=lambda entry: entry[0]),
                })
                self.modified()
            self._erase_action_items = []
            self._erase_original_indexes = {}
            self._erase_last_pos = None
            self.update()
            return
        if self._current_item:
            t = self._current_item['type']
            valid = False
            if t in ('pencil', 'highlighter', 'laser'):
                pts = self._current_item['points']
                if len(pts) > 1 or t == 'laser':
                    has_straight = any(len(p) > 2 and p[2] for p in pts)
                    if not has_straight and len(pts) > 1:
                        self._current_item['points'] = _smooth_points(pts)
                    valid = True
            elif t in ('circle', 'rect', 'arrow'):
                sx, sy = self._current_item['start']
                ex, ey = self._current_item['end']
                valid = abs(ex - sx) > 3 or abs(ey - sy) > 3
            if valid:
                if t == 'laser':
                    self._finish_laser_trail(self._current_item)
                else:
                    self._items.append(self._current_item)
                    self.modified()
            self._current_item = None
        self.update()

    # ── Keyboard (for text tool) ──────────────────────────────────────────────

    def _make_text_font(self) -> QFont:
        """Build a QFont from the current text toolbar settings."""
        size = self._text_bar.get_font_size() if self._text_bar else 16
        weight = QFont.Weight.Bold if (self._text_bar and self._text_bar.is_bold()) else QFont.Weight.Normal
        font = QFont("Segoe UI", size, weight)
        if self._text_bar:
            font.setItalic(self._text_bar.is_italic())
            font.setUnderline(self._text_bar.is_underline())
        return font

    def _apply_text_editor_style(self):
        if not getattr(self, '_text_edit', None):
            return
        font = self._make_text_font()
        font_size = font.pointSize()
        font_weight = "bold" if font.bold() else "normal"
        font_style = "italic" if font.italic() else "normal"
        text_decoration = "underline" if font.underline() else "none"
        self._text_edit.setFont(font)
        self._text_edit.document().setDefaultFont(font)
        self._text_edit.setStyleSheet(f"""
            QPlainTextEdit {{
                background: rgba(20, 20, 24, 190);
                color: {self._color.name()};
                border: 2px dashed #EF4444;
                border-radius: 6px;
                padding: 6px 8px;
                font-family: 'Segoe UI';
                font-size: {font_size}pt;
                font-weight: {font_weight};
                font-style: {font_style};
                text-decoration: {text_decoration};
                selection-background-color: rgba(220, 38, 38, 160);
            }}
        """)
        self._auto_resize_text_editor()

    def _reposition_text_bar(self):
        if not self._text_input_active or not self._text_pos or not self._text_bar.isVisible():
            return
        x, y = self._text_pos
        pad = 6
        bar_x = int(x - pad)
        bar_y = int(y - pad) - self._text_bar.height() - 4
        if bar_y < 5:
            bar_y = int(y + self._text_box_h + pad) + 4
        self._text_bar.move(bar_x, bar_y)

    def _auto_resize_text_editor(self):
        if not self._text_input_active or not self._text_pos or not getattr(self, '_text_edit', None):
            return
        font = self._make_text_font()
        fm = QFontMetrics(font)
        text = self._text_edit.toPlainText()
        lines = text.split('\n') if text else [""]
        line_count = max(len(lines), 1)
        line_height = max(fm.height(), 18)

        # Horizontal sizing: expand if typed text exceeds initial box width
        max_line_w = max((fm.horizontalAdvance(ln) for ln in lines), default=20)
        needed_w = max_line_w + 36
        box_w = max(int(getattr(self, '_text_box_w', 120.0)), needed_w, 80)
        self._text_box_w = float(box_w)

        # Vertical sizing: expand if lines exceed initial box height
        doc = self._text_edit.document()
        doc.setTextWidth(box_w - 16)
        doc_h = int(doc.size().height()) + 16
        needed_h = max(line_count * line_height + 20, doc_h)

        display_h = max(int(getattr(self, '_text_box_initial_h', 34.0)), needed_h)
        self._text_box_h = float(display_h)
        editor_x, editor_y = _text_editor_top_left(*self._text_pos)
        self._text_edit.setGeometry(editor_x, editor_y, box_w + 10, display_h + 8)
        self._reposition_text_bar()
        self.update()

    def _begin_edit_text(self, idx: int):
        if idx < 0 or idx >= len(self._items):
            return
        item = self._items[idx]
        if item.get('type') != 'text':
            return
        self._editing_text_index = idx
        self._editing_text_backup = self._items.pop(idx)
        self._selected_shape_idx = None
        if hasattr(self, '_action_bar'):
            self._action_bar.hide()
        sx, sy = item['start']
        ex, ey = item['end']
        self._text_box_w = max(abs(ex - sx), 60.0)
        self._text_box_h = max(abs(ey - sy), 34.0)
        self._text_box_initial_h = self._text_box_h
        self._text_pos = (min(sx, ex), min(sy, ey))
        self._color = QColor(item['color'])
        self._text_bar.set_defaults(
            font_size=item.get('font_size', 16),
            bold=item.get('bold', False),
            italic=item.get('italic', False),
            underline=item.get('underline', False),
        )
        self._start_text_input(self._text_pos)
        self._text_edit.blockSignals(True)
        self._text_edit.setPlainText(item.get('text', ''))
        cursor = self._text_edit.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self._text_edit.setTextCursor(cursor)
        self._text_edit.blockSignals(False)
        self._auto_resize_text_editor()

    def _is_inside_text_box(self, pos: QPoint) -> bool:
        """Check if the given widget-coord point is inside the current text input area."""
        if not self._text_input_active or not self._text_pos:
            return False
        return self._text_edit.geometry().adjusted(-6, -6, 6, 6).contains(pos)

    def _start_text_input(self, pos):
        self._cursor_timer.stop()
        self._text_input_active = True
        self._text_pos = pos
        self._text_buffer = ""
        self._cursor_visible = True
        self._cursor_timer.start()
        if hasattr(self, '_action_bar'):
            self._action_bar.hide()
        
        box_w = max(60, int(self._text_box_w))
        box_h = max(int(getattr(self, '_text_box_initial_h', 34.0)), int(self._text_box_h))
        self._text_box_h = float(box_h)
        editor_x, editor_y = _text_editor_top_left(pos[0], pos[1])
        self._text_edit.setGeometry(editor_x, editor_y, box_w + 10, box_h + 8)
        
        bar_x = int(pos[0]) - 6
        bar_y = int(pos[1]) - self._text_bar.height() - 8
        if bar_y < 5:
            bar_y = int(pos[1]) + box_h + 8
        self._text_bar.move(bar_x, bar_y)
        self._text_bar.show()
        self._text_bar.raise_()
        
        self._text_edit.blockSignals(True)
        self._text_edit.clear()
        self._text_edit.blockSignals(False)
        self._apply_text_editor_style()
        self._text_edit.show()
        _align_new_text_caret(self, pos)
        self._text_edit.raise_()
        self._text_edit.setFocus(Qt.FocusReason.OtherFocusReason)
        self.update()

    def _finish_text_history(self):
        self._text_result_index = len(self._items) - 1
        if self._editing_text_backup is not None:
            replacement = self._items.pop()
            target = self._editing_text_backup
            before = dict(target)
            target.clear()
            target.update(replacement)
            index = min(self._editing_text_index, len(self._items))
            self._items.insert(index, target)
            self._items.append({'_action': 'update', '_target': target,
                                '_before': before, '_after': dict(target)})
            self._text_result_index = index

    def _commit_text(self):
        if not self._text_input_active:
            return
        text = self._text_edit.toPlainText() if getattr(self, '_text_edit', None) else self._text_buffer
        if text.strip():
            font = self._make_text_font()
            fm = QFontMetrics(font)
            lines = text.split('\n')

            # Tight horizontal & vertical wrap around actual text content
            max_line_w = max((fm.horizontalAdvance(ln) for ln in lines), default=20)
            tight_w = max(float(max_line_w), 20.0)

            line_height = max(fm.height(), 16)
            tight_h = max(float(len(lines) * line_height), float(line_height))

            self._items.append({
                'type': 'text',
                'start': self._text_pos,
                'end': (self._text_pos[0] + tight_w, self._text_pos[1] + tight_h),
                'text': text,
                'color': self._color.name(),
                'font_size': self._text_bar.get_font_size() if self._text_bar else 16,
                'bold': self._text_bar.is_bold() if self._text_bar else False,
                'italic': self._text_bar.is_italic() if self._text_bar else False,
                'underline': self._text_bar.is_underline() if self._text_bar else False,
            })
            self._finish_text_history()
            self._redo_stack.clear()
            self.modified()
            self._selected_shape_idx = self._text_result_index
            self._show_selection_action_bar(self._selected_shape_idx)
        if self._editing_text_backup is not None and not text.strip():
            self._items.insert(min(self._editing_text_index, len(self._items)), self._editing_text_backup)
        self._text_input_active = False
        self._text_buffer = ""
        self._editing_text_backup = None
        self._cursor_timer.stop()
        self._text_bar.hide()
        if getattr(self, '_text_edit', None):
            self._text_edit.blockSignals(True)
            self._text_edit.hide()
            self._text_edit.clear()
            self._text_edit.blockSignals(False)
        self.update()

    def _cancel_text(self):
        if not self._text_input_active:
            return
        if self._editing_text_backup is not None:
            self._items.insert(min(self._editing_text_index, len(self._items)), self._editing_text_backup)
            self._editing_text_backup = None
        self._text_input_active = False
        self._text_buffer = ""
        self._cursor_timer.stop()
        self._text_bar.hide()
        if getattr(self, '_text_edit', None):
            self._text_edit.blockSignals(True)
            self._text_edit.hide()
            self._text_edit.clear()
            self._text_edit.blockSignals(False)
        self.update()

    def _blink_cursor(self):
        self._cursor_visible = not self._cursor_visible
        if self._text_input_active:  # PERF-009: Only repaint when text cursor is visible
            self.update()

    # ── Paint ─────────────────────────────────────────────────────────────────

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        p.fillRect(self.rect(), Qt.GlobalColor.transparent)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        if self._interactive:
            # Draw a nearly invisible background so Windows registers clicks on "empty" space 
            # instead of letting them fall through to the desktop (due to WS_EX_LAYERED behavior)
            p.fillRect(self.rect(), QColor(255, 255, 255, 1))

        for item in self._items:
            draw_annotation_item(p, item)

        for trail in self._laser_trails:
            draw_annotation_item(p, trail)

        if self._current_item:
            draw_annotation_item(p, self._current_item)

        # Draw selection box on selected text item
        if self._selected_shape_idx is not None and 0 <= self._selected_shape_idx < len(self._items):
            sel = self._items[self._selected_shape_idx]
            if sel.get('type') == 'text':
                _draw_shape_handles(p, sel)

        # Text input box preview (during creation)
        if self._text_box_creating:
            p.setPen(QPen(QColor("#EF4444"), 2, Qt.PenStyle.DashLine))
            p.setBrush(QColor(239, 68, 68, 25))
            p.drawRoundedRect(QRectF(self._text_pos[0], self._text_pos[1], self._text_box_w, self._text_box_h), 4, 4)

        # Text input preview with cursor and border
        if self._text_input_active and self._text_pos and not (getattr(self, '_text_edit', None) and self._text_edit.isVisible()):
            color = QColor(self._color.name())
            font = self._make_text_font()
            fm = QFontMetrics(font)
            p.setFont(font)
            p.setPen(QPen(color))

            x, y = self._text_pos
            line_height = fm.height()

            # Keep words together when possible, then break an oversized word only as needed.
            layout = QTextLayout(self._text_buffer, font)
            opt = QTextOption()
            opt.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
            layout.setTextOption(opt)

            layout.beginLayout()
            y_offset = 0.0
            while True:
                line = layout.createLine()
                if not line.isValid():
                    break
                line.setLineWidth(self._text_box_w)
                line.setPosition(QPointF(0, y_offset))
                y_offset += line_height
            layout.endLayout()

            # Draw the text using the layout
            layout.draw(p, QPointF(x, y))

            # Update box height to fit all wrapped lines
            self._text_box_h = max(y_offset, line_height + 4)

            # Draw border
            pad = 6
            border_rect = QRectF(x - pad, y - pad, self._text_box_w + pad * 2, self._text_box_h + pad * 2)
            
            # Red dash
            p.setPen(QPen(QColor("#EF4444"), 1.8, Qt.PenStyle.DashLine))
            p.drawRoundedRect(border_rect, 4, 4)

            # Blinking cursor uses the same QTextLayout wrapping logic.
            if self._cursor_visible:
                p.setPen(QPen(color, 2))
                cx, cy_top, cy_bot = _calc_cursor_pos(
                    self._text_buffer, font, int(self._text_box_w), x, y)
                p.drawLine(int(cx), int(cy_top), int(cx), int(cy_bot))

            # Keep toolbar firmly anchored above the text box
            if self._text_bar and self._text_bar.isVisible():
                border_top = int(y - pad)
                border_left = int(x - pad)
                bar_y = border_top - self._text_bar.height() - 4
                if bar_y < 5:
                    bar_y = int(y + self._text_box_h + pad) + 4
                self._text_bar.move(border_left, bar_y)

        p.end()

    def closeEvent(self, event):
        """Clean up resources to prevent memory leaks."""
        self._cursor_timer.stop()
        self._items.clear()
        self._redo_stack.clear()
        self._text_bar.hide()
        if getattr(self, '_text_edit', None):
            self._text_edit.hide()
        super().closeEvent(event)


# ─────────────────────────────────────────────────────────────────────────────
#  _DrawingArea — Image editor canvas for AnnotateWindow
# ─────────────────────────────────────────────────────────────────────────────

class _DrawingArea(QWidget):
    """
    Displays an image scaled to fit and allows annotation drawing.
    Stores all coordinates in image space for pixel-perfect saving.
    """
    modified = pyqtSignal()
    tool_changed = pyqtSignal(str)

    def __init__(self, image_path, parent=None):
        super().__init__(parent)
        if isinstance(image_path, QPixmap):
            self._original = image_path.toImage()
            self._filepath = ""
        elif isinstance(image_path, QImage):
            self._original = image_path
            self._filepath = ""
        elif isinstance(image_path, str) and image_path:
            self._filepath = image_path
            self._original = QImage(image_path)
        else:
            self._filepath = ""
            self._original = QImage(1, 1, QImage.Format.Format_ARGB32)
        self._items: List[dict] = []
        self._redo_stack: List[dict] = []
        self._current_item: Optional[dict] = None
        self._has_unsaved = False

        self._tool = 'pencil'
        self._color = QColor('#FF3B30')
        self._active_thickness = 'normal'
        self._drawing = False
        
        # Shape resize / move state
        self._selected_shape_idx: Optional[int] = None
        self._resize_handle: Optional[str] = None
        self._resizing = False
        self._moving_shape = False
        self._move_offset = (0.0, 0.0)
        self._initial_width = 0.0
        self._initial_font_size = 16
        # Crop tool state
        self._crop_rect: Optional[QRectF] = None
        self._crop_drag: Optional[str] = None
        self._crop_start_pos: Optional[QPointF] = None
        self._crop_orig_rect: Optional[QRectF] = None
        self._erase_action_items = []
        self._erase_last_pos: Optional[QPointF] = None
        self._erase_original_indexes = {}

        # Scale / offset for image display
        self._scale = 1.0
        self._offset_x = 0.0
        self._offset_y = 0.0
        self._zoom_level = 1.0  # User-controlled zoom multiplier
        self._panning = False
        self._pan_start = None
        self._pan_offset_start = None

        # Text input
        self._text_input_active = False
        self._space_pressed = False

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._text_pos = None
        self._text_buffer = ""
        self._text_box_w = 200.0   # Default text box width
        self._text_box_h = 40.0    # Default text box height (auto-expands)
        self._text_box_creating = False  # True while dragging to create box
        self._text_box_drag_start = None
        self._editing_text_backup = None
        self._editing_text_index = None
        self._cursor_visible = True
        self._cursor_timer = QTimer(self)
        self._cursor_timer.setInterval(530)
        self._cursor_timer.timeout.connect(self._blink_cursor)

        # Text formatting toolbar (child widget, hidden until text input starts)
        self._text_bar = _TextEditBar(self)
        self._text_bar.hide()
        self._text_bar.formatting_changed.connect(self._apply_text_editor_style)
        self._text_edit = _AnnotationPlainTextEdit(self)
        self._text_edit.hide()
        self._text_edit.commit_requested.connect(self._commit_text)
        self._text_edit.cancel_requested.connect(self._cancel_text)
        self._text_edit.content_resized.connect(self._auto_resize_text_editor)

        # Selection action bar (Edit / Delete floating mini-bar)
        self._action_bar = _SelectionActionBar(self)
        self._action_bar.hide()
        self._action_bar.edit_requested.connect(self._on_action_bar_edit)
        self._action_bar.delete_requested.connect(self._on_action_bar_delete)

        self._text_box_initial_h = 40.0
        self._did_move_shape = False
        self._press_pos = None

        self.setMouseTracking(True)
        self.setCursor(shape_cursor(Qt.CursorShape.CrossCursor))
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumSize(200, 200)

        # Shortcuts
        QShortcut(QKeySequence("Ctrl+Z"), self, self._safe_undo)
        QShortcut(QKeySequence("Ctrl+Y"), self, self._safe_redo)
        QShortcut(QKeySequence("Ctrl+S"), self, self.save_image)
        QShortcut(QKeySequence("Delete"), self, self._safe_delete)
        QShortcut(QKeySequence("Backspace"), self, self._safe_delete)
        QShortcut(QKeySequence("Esc"), self, self._on_esc_pressed)
        QShortcut(QKeySequence("Return"), self, self._on_enter_pressed)
        QShortcut(QKeySequence("Enter"), self, self._on_enter_pressed)
        
        # Tool switch toast
        self._toast_widget = _ToastWidget(self)
        self._toast_timer = QTimer(self)
        self._toast_timer.timeout.connect(self._toast_widget.hide)

        # PERF-009: Repaint throttle for 60fps max during drawing
        self._repaint_dirty = False
        self._repaint_timer = QTimer(self)
        self._repaint_timer.setInterval(16)  # ~60fps
        self._repaint_timer.timeout.connect(self._flush_repaint)

    def _show_selection_action_bar(self, idx: int):
        if idx is None or idx < 0 or idx >= len(self._items):
            if hasattr(self, '_action_bar'):
                self._action_bar.hide()
            return
        item = self._items[idx]
        is_text = (item.get('type') == 'text')
        self._action_bar.set_is_text(is_text)
        r = _shape_bounding_rect(item)
        wx = int(r.left() * self._scale + self._offset_x)
        wy = int(r.top() * self._scale + self._offset_y)
        wh = int(r.height() * self._scale)
        by = wy - self._action_bar.height() - 6
        if by < 5:
            by = wy + wh + 6
        self._action_bar.move(wx, by)
        self._action_bar.show()
        self._action_bar.raise_()

    def _on_action_bar_edit(self):
        if self._selected_shape_idx is not None and 0 <= self._selected_shape_idx < len(self._items):
            idx = self._selected_shape_idx
            self._action_bar.hide()
            self._begin_edit_text(idx)

    def _on_action_bar_delete(self):
        if self._selected_shape_idx is not None and 0 <= self._selected_shape_idx < len(self._items):
            idx = self._selected_shape_idx
            item = self._items.pop(idx)
            self._items.append({'_action': 'erase', '_erased_items': [(idx, item)]})
            self._redo_stack.clear()
            self._deselect_shape()
            self._has_unsaved = True
            self.modified.emit()
            self.update()

    def _safe_undo(self): self.undo()
    def _safe_redo(self): self.redo()
    def _safe_delete(self):
        if self._text_input_active:
            return
        if self._selected_shape_idx is not None and 0 <= self._selected_shape_idx < len(self._items):
            self._on_action_bar_delete()
        # No selection: do nothing. Clear All is a separate explicit action.

    def _on_esc_pressed(self):
        try:
            if self._text_input_active:
                self._cancel_text()
            elif self._tool == 'crop':
                self._crop_rect = None
                self._crop_drag = None
                self.set_tool('pencil')
                self.update()
            elif self._selected_shape_idx is not None:
                self._deselect_shape()
            else:
                w = self.window()
                if w and hasattr(w, 'close'):
                    w.close()
        except RuntimeError:
            pass

    def _on_enter_pressed(self):
        if self._text_input_active:
            return  # Enter handled by keyPressEvent for multi-line text
        if self._tool == 'crop':
            self.commit_crop()

    def has_unsaved(self) -> bool:
        return self._has_unsaved

    def _widget_to_image(self, pos: QPoint) -> QPointF:
        """Convert widget coordinates to image coordinates."""
        return QPointF(
            (pos.x() - self._offset_x) / self._scale,
            (pos.y() - self._offset_y) / self._scale,
        )

    def view_actual_pixels(self):
        self._commit_text()
        self._scale = 1.0 / max(1.0, self.devicePixelRatioF())
        self._zoom_level = self._scale / max(.001, self._get_base_scale())
        self._offset_x = (self.width() - self._original.width() * self._scale) / 2
        self._offset_y = (self.height() - self._original.height() * self._scale) / 2
        self.update()

    def view_fit(self):
        self._commit_text()
        self._zoom_level = 1.0
        self._recalc_transform()
        self.update()

    def _get_base_scale(self):
        if self._original.isNull():
            return 1.0
        ww = self.width()
        wh = self.height() - 20 # 10px pad top/bottom
        if ww <= 0 or wh <= 0:
            return 1.0
        return min(1.0 / max(1.0, self.devicePixelRatioF()), ww / self._original.width(), wh / self._original.height())

    def _recalc_transform(self):
        """Recalculate scale. Offset is only centered if zoom is 1.0."""
        if self._original.isNull():
            return
        base_scale = self._get_base_scale()
        self._scale = base_scale * self._zoom_level
        
        # Only force center if we are fully zoomed out, otherwise let the user keep their pan
        if self._zoom_level <= 1.01:
            iw, ih = self._original.width(), self._original.height()
            self._offset_x = (self.width() - iw * self._scale) / 2
            self._offset_y = 10 + (self.height() - 20 - ih * self._scale) / 2

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._recalc_transform()

    # ── Public API ────────────────────────────────────────────────────────────

    def _update_cursor(self):
        if self._tool == 'crop' and getattr(self, '_crop_rect', None):
            self.setCursor(shape_cursor(Qt.CursorShape.CrossCursor))
        else:
            self.setCursor(get_tool_cursor(self._tool, self._color, getattr(self, '_active_thickness', 'normal')))

    def _show_toast(self, message: str, icon_name: str):
        self._toast_widget.show_message(message, _asset(icon_name))
        self._toast_widget.adjustSize()
        # Position near bottom center, slightly above bottom bar
        cx = self.width() // 2 - self._toast_widget.width() // 2
        cy = self.height() - 150
        self._toast_widget.move(cx, cy)
        self._toast_timer.start(1500)

    def set_tool(self, tool: str):
        self._commit_text()
        self._deselect_shape()
        
        if self._tool == 'crop' and tool != 'crop':
            self._crop_rect = None
            self._crop_drag = None
            self.update()
            
        self._tool = tool
        
        # When crop is activated, immediately show boundary around full image
        if tool == 'crop':
            iw = float(self._original.width())
            ih = float(self._original.height())
            self._crop_rect = QRectF(0.0, 0.0, iw, ih)
            self._crop_drag = None
            self._crop_orig_rect = QRectF(0.0, 0.0, iw, ih)
            
        self._update_cursor()
        self.tool_changed.emit(tool)
        self.update()

        # Improvement 1: Visual feedback
        tool_info = {
            'pencil': ('Pencil', 'pencil.png'),
            'highlighter': ('Highlighter', 'highlighter.png'),
            'eraser': ('Eraser', 'eraser.png'),
            'text': ('Text', 'text_tool.png'),
            'circle': ('Circle', 'shape_circle.png'),
            'rect': ('Rectangle', 'shape_rect.png'),
            'arrow': ('Arrow', 'shape_arrow.png'),
            'crop': ('Crop', 'crop.png')
        }
        if tool in tool_info:
            name, icon = tool_info[tool]
            self._show_toast(name, icon)

    def set_color(self, color: QColor):
        self._color = color
        self._apply_text_editor_style()
        self._update_cursor()
        
    def set_thickness(self, thickness_key: str):
        self._active_thickness = thickness_key
        self._update_cursor()

    def undo(self):
        self._deselect_shape()
        if self._items:
            item = self._items.pop()
            if item.get('_action') == 'erase':
                # BUG-008: Undo an erase → restore the erased items
                entries = sorted(
                    item['_erased_items'],
                    key=lambda entry: entry[0] if isinstance(entry, tuple) else len(self._items),
                )
                for erased in entries:
                    if isinstance(erased, tuple):
                        index, restored_item = erased
                        self._items.insert(min(index, len(self._items)), restored_item)
                    else:
                        self._items.append(erased)
            elif item.get('_action') == 'clear':
                self._items = list(item['_cleared_items'])
            elif item.get('_action') == 'update':
                item['_target'].clear()
                item['_target'].update(item['_before'])
            self._redo_stack.append(item)
            if item.get('type') == 'transform':
                self._original = item['old_image']
                self._items = list(item['old_items'])
                self._recalc_transform()
                self._clear_crop_state()
            self._has_unsaved = True
            self.modified.emit()
            self.update()

    def redo(self):
        self._deselect_shape()
        if self._redo_stack:
            item = self._redo_stack.pop()
            if item.get('_action') == 'erase':
                # BUG-008: Redo an erase → remove the items again
                erased_set = {
                    id(entry[1] if isinstance(entry, tuple) else entry)
                    for entry in item['_erased_items']
                }
                self._items = [i for i in self._items if id(i) not in erased_set]
            elif item.get('_action') == 'clear':
                self._items.clear()
            elif item.get('_action') == 'update':
                item['_target'].clear()
                item['_target'].update(item['_after'])
            if item.get('type') == 'transform':
                item['old_items'] = list(self._items)
                self._items.clear()
                self._items.append(item)
                self._original = item['new_image']
                self._recalc_transform()
                self._clear_crop_state()
            else:
                self._items.append(item)
            self._has_unsaved = True
            self.modified.emit()
            self.update()

    def clear_all(self):
        self._deselect_shape()
        if not self._items:
            return
        clear_action = {'_action': 'clear', '_cleared_items': list(self._items)}
        self._items = [clear_action]
        self._redo_stack.clear()
        self._current_item = None
        self._has_unsaved = True  # Clearing IS an unsaved change vs on-disk file
        self.modified.emit()
        self.update()

    def _deselect_shape(self):
        """Deselect any currently-selected shape or text."""
        if self._selected_shape_idx is not None:
            self._selected_shape_idx = None
            self._resize_handle = None
            self._resizing = False
            self._moving_shape = False
            self.update()

    def _apply_structural_transform(self, action: str):
        self._commit_text()
        
        old_original = self._original.copy()
        old_items = list(self._items)
        
        base = old_original.copy()
        if old_items:
            p = QPainter(base)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            for item in old_items:
                if item.get('type') != 'transform':
                    draw_annotation_item(p, item)
            p.end()
            
        if action == 'rotate_90':
            new_image = base.transformed(QTransform().rotate(90), Qt.TransformationMode.SmoothTransformation)
        elif action == 'flip_h':
            # Horizontal flip mirrors left-to-right.
            new_image = base.mirrored(True, False)
        elif action == 'flip_v':
            # Vertical flip mirrors top-to-bottom.
            new_image = base.mirrored(False, True)
        elif action == 'crop':
            if not self._crop_rect:
                return
            cr = self._crop_rect.normalized().toRect()
            cr = cr.intersected(base.rect())
            if not cr.isValid() or cr.width() < 4 or cr.height() < 4:
                return
            new_image = base.copy(cr)
        else:
            return
            
        record = {
            'type': 'transform',
            'old_image': old_original,
            'old_items': old_items,
            'new_image': new_image
        }
        
        self._items.clear()
        self._items.append(record)
        self._redo_stack.clear()
        
        self._original = new_image
        self._clear_crop_state()
        if action == 'crop':
            self.set_tool('pencil')
            
        self._recalc_transform()
        self._has_unsaved = True
        self.modified.emit()
        self.update()

    def rotate_90(self): self._apply_structural_transform('rotate_90')
    def flip_horizontal(self): self._apply_structural_transform('flip_h')
    def flip_vertical(self): self._apply_structural_transform('flip_v')
    def commit_crop(self): self._apply_structural_transform('crop')

    def _clear_crop_state(self):
        """Discard crop geometry tied to the previous image orientation/size."""
        self._crop_rect = None
        self._crop_drag = None
        self._crop_start_pos = None
        self._crop_orig_rect = None

    def _crop_handle_at(self, cr: QRectF, ix: float, iy: float) -> Optional[str]:
        """Return which resize handle is nearest to (ix,iy), or None."""
        dist = max(20.0 / self._scale, 12.0)
        checks = [
            ('tl', cr.left(),          cr.top()),
            ('tr', cr.right(),         cr.top()),
            ('bl', cr.left(),          cr.bottom()),
            ('br', cr.right(),         cr.bottom()),
            ('t',  cr.center().x(),    cr.top()),
            ('b',  cr.center().x(),    cr.bottom()),
            ('l',  cr.left(),          cr.center().y()),
            ('r',  cr.right(),         cr.center().y()),
        ]
        for handle, hx, hy in checks:
            if math.hypot(ix - hx, iy - hy) < dist:
                return handle
        return None

    def _dist_to_segment(self, px, py, x1, y1, x2, y2):
        dx = x2 - x1
        dy = y2 - y1
        if dx == 0 and dy == 0:
            return math.hypot(px - x1, py - y1)
        t = ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)
        t = max(0, min(1, t))
        nearest_x = x1 + t * dx
        nearest_y = y1 + t * dy
        return math.hypot(px - nearest_x, py - nearest_y)

    def _hit_test(self, pos, item: dict) -> bool:
        t = item['type']
        px, py = float(pos.x()), float(pos.y())
        # Item coordinates are image-local; retain a roughly 12-screen-pixel
        # interaction radius at every fit and zoom scale, scaled with stroke thickness.
        base_threshold = 12.0 / max(self._scale, 0.001)
        widths = THICKNESS_LEVELS.get(t, {})
        stroke_width = float(item.get('width', widths.get(item.get('thickness', 'normal'), 4)))
        th = max(base_threshold, stroke_width / 2.0 + 4.0 / max(self._scale, 0.001))

        if t in ('pencil', 'highlighter'):
            points = item['points']
            if points:
                xs = [p[0] for p in points]
                ys = [p[1] for p in points]
                if px < min(xs) - th or px > max(xs) + th:
                    return False
                if py < min(ys) - th or py > max(ys) + th:
                    return False
            if len(points) == 1:
                return math.hypot(px - points[0][0], py - points[0][1]) < th
            for i in range(len(points) - 1):
                x1, y1 = points[i][0], points[i][1]
                x2, y2 = points[i+1][0], points[i+1][1]
                if self._dist_to_segment(px, py, x1, y1, x2, y2) < th:
                    return True
            return False

        elif t == 'rect':
            sx, sy = item['start']
            ex, ey = item['end']
            rect = QRectF(float(min(sx, ex)), float(min(sy, ey)), float(abs(ex - sx)), float(abs(ey - sy)))
            return rect.adjusted(-th, -th, th, th).contains(QPointF(pos))

        elif t == 'circle':
            sx, sy = item['start']
            ex, ey = item['end']
            rx, ry = abs(ex - sx) / 2.0, abs(ey - sy) / 2.0
            cx, cy = (sx + ex) / 2.0, (sy + ey) / 2.0
            if rx == 0 or ry == 0: return False
            val = ((px - cx)**2) / ((rx + th)**2) + ((py - cy)**2) / ((ry + th)**2)
            return val <= 1.0

        elif t == 'arrow':
            sx, sy = item['start']
            ex, ey = item['end']
            return self._dist_to_segment(px, py, sx, sy, ex, ey) < th

        elif t == 'text':
            if 'start' in item and 'end' in item:
                sx, sy = item['start']
                ex, ey = item['end']
                rect = QRectF(float(min(sx, ex)), float(min(sy, ey)), float(abs(ex - sx)), float(abs(ey - sy)))
                return rect.adjusted(-th, -th, th, th).contains(QPointF(pos))

            tx, ty = item.get('pos', (0,0))
            fs = item.get('font_size', 16)
            weight = QFont.Weight.Bold if item.get('bold', True) else QFont.Weight.Normal
            font = QFont("Segoe UI", fs, weight)
            font.setItalic(item.get('italic', False))
            font.setUnderline(item.get('underline', False))
            fm = QFontMetrics(font)
            lines = item['text'].split('\n')
            max_w = max((fm.horizontalAdvance(ln) for ln in lines), default=0)
            total_h = fm.height() * len(lines)
            rect = QRectF(float(tx), float(ty) - float(fm.ascent()), float(max_w), float(total_h))
            return rect.adjusted(-th, -th, th, th).contains(QPointF(pos))

        return False

    def save_image(self) -> bool:
        """Compose annotations onto the original image and overwrite the file."""
        self._commit_text()
        result = QImage(self._original)
        p = QPainter(result)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        for item in self._items:
            if item.get('type') != 'transform':
                draw_annotation_item(p, item)
        p.end()

        ok = _atomic_save_image(result, self._filepath)
        if ok:
            self._original = result
            self._has_unsaved = False
            self._items.clear()
            self._redo_stack.clear()
            self.modified.emit()
            self.update()
        return ok

    def get_composed_image(self) -> QImage:
        """Return image with all annotations composed on top."""
        result = QImage(self._original)
        p = QPainter(result)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        for item in self._items:
            if item.get('type') != 'transform':
                draw_annotation_item(p, item)
        p.end()
        return result

    # ── Mouse ─────────────────────────────────────────────────────────────────

    def _deselect_shape(self):
        """Deselect any currently-selected shape or text."""
        if self._selected_shape_idx is not None:
            self._selected_shape_idx = None
            self._resize_handle = None
            self._resizing = False
            self._moving_shape = False
            if hasattr(self, '_action_bar'):
                self._action_bar.hide()
            self.update()

    def mouseDoubleClickEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        widget_pos = event.position().toPoint()
        img_pos = self._widget_to_image(widget_pos)
        for i in range(len(self._items) - 1, -1, -1):
            item = self._items[i]
            if item.get('type') == 'text' and 'start' in item and self._hit_test(img_pos, item):
                self._begin_edit_text(i)
                event.accept()
                return
        super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event):
        # Middle-click pan or Space+Left-click pan
        if event.button() == Qt.MouseButton.MiddleButton or (event.button() == Qt.MouseButton.LeftButton and self._space_pressed):
            self._panning = True
            self._pan_start = event.position().toPoint()
            self._pan_offset_start = (self._offset_x, self._offset_y)
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        widget_pos = event.position().toPoint()
        img_pos = self._widget_to_image(widget_pos)
        ix, iy = img_pos.x(), img_pos.y()

        # ── Check if clicking on the already selected text item to move it ──
        if self._selected_shape_idx is not None and 0 <= self._selected_shape_idx < len(self._items):
            sel_item = self._items[self._selected_shape_idx]
            if sel_item.get('type') == 'text' and 'start' in sel_item:
                r = _shape_bounding_rect(sel_item)
                if r.adjusted(-12/self._scale, -12/self._scale, 12/self._scale, 12/self._scale).contains(img_pos):
                    self._moving_shape = True
                    self._move_before = dict(self._items[self._selected_shape_idx])
                    self._did_move_shape = False
                    self._press_pos = widget_pos
                    self._move_offset = (ix - r.left(), iy - r.top())
                    return
                else:
                    self._deselect_shape()

        # Clip to image bounds
        iw, ih = self._original.width(), self._original.height()
        # Allows starting crop slightly outside, but restrict drawing
        if (img_pos.x() < 0 or img_pos.y() < 0 or img_pos.x() > iw or img_pos.y() > ih) and self._tool != 'crop':
            return

        if self._tool == 'crop':
            self._commit_text()
            iw, ih = float(self._original.width()), float(self._original.height())
            ix = max(0.0, min(iw, img_pos.x()))
            iy = max(0.0, min(ih, img_pos.y()))

            if self._crop_rect:
                cr = self._crop_rect.normalized()
                handle = self._crop_handle_at(cr, ix, iy)
                if handle:
                    self._crop_drag = handle
                    self._crop_orig_rect = QRectF(cr)
                    self._crop_start_pos = QPointF(ix, iy)
                elif cr.contains(QPointF(ix, iy)):
                    self._crop_drag = 'move'
                    self._crop_orig_rect = QRectF(cr)
                    self._crop_start_pos = QPointF(ix, iy)
                # Outside crop box: do nothing (crop started at image boundary)
            self._drawing = True
            self.update()
            return

        if self._tool == 'eraser':
            self._deselect_shape()
            self._drawing = True
            self._erase_action_items = []
            self._erase_original_indexes = {
                id(item): index for index, item in enumerate(self._items)
            }
            self._erase_last_pos = QPointF(img_pos)
            self._erase_at(img_pos)
            return

        if self._tool == 'text':
            if self._text_input_active:
                # Check if click is inside the text box area → keep editing
                if self._is_inside_text_box(img_pos):
                    return
                # Click outside → commit
                self._commit_text()
            
            # Check if clicking on an existing committed text item to select it
            if not self._text_input_active:
                for i in range(len(self._items) - 1, -1, -1):
                    item = self._items[i]
                    if item.get('type') == 'text' and 'start' in item and self._hit_test(img_pos, item):
                        self._selected_shape_idx = i
                        r = _shape_bounding_rect(item)
                        self._moving_shape = True
                        self._move_before = dict(self._items[self._selected_shape_idx])
                        self._did_move_shape = False
                        self._press_pos = widget_pos
                        self._move_offset = (ix - r.left(), iy - r.top())
                        self._show_selection_action_bar(i)
                        self.update()
                        return
                # No existing text hit → start creating new text box
                self._text_box_creating = True
                self._text_box_drag_start = (ix, iy)
                self._text_pos = (ix, iy)
                self._text_box_w = 0.0
                self._text_box_h = 0.0
                self._drawing = True
            return

        self._drawing = True
        self._redo_stack.clear()

        if self._tool in ('pencil', 'highlighter'):
            group = self._tool
            base_width = THICKNESS_LEVELS.get(group, {}).get(self._active_thickness, 4 if group == 'pencil' else 20)
            width = base_width / self._scale
            opacity = 1.0 if self._tool == 'pencil' else 0.4
            self._current_item = {
                'type': self._tool,
                'points': [(img_pos.x(), img_pos.y())],
                'color': self._color.name(),
                'width': width,
                'opacity': opacity,
            }
        elif self._tool in ('circle', 'rect', 'arrow'):
            base_width = THICKNESS_LEVELS.get('shapes', {}).get(self._active_thickness, 4)
            width = base_width / self._scale
            self._current_item = {
                'type': self._tool,
                'start': (img_pos.x(), img_pos.y()),
                'end': (img_pos.x(), img_pos.y()),
                'color': self._color.name(),
                'width': width,
            }

    def mouseMoveEvent(self, event):
        # Middle-click pan
        if self._panning and self._pan_start and self._pan_offset_start:
            delta = event.position().toPoint() - self._pan_start
            self._offset_x = self._pan_offset_start[0] + delta.x()
            self._offset_y = self._pan_offset_start[1] + delta.y()
            self._clamp_offsets()
            self.update()
            return

        widget_pos = event.position().toPoint()
        img_pos = self._widget_to_image(widget_pos)
        ix, iy = img_pos.x(), img_pos.y()

        # ── Text box creation drag ──
        if self._text_box_creating and self._text_box_drag_start:
            sx, sy = self._text_box_drag_start
            self._text_pos = (min(sx, ix), min(sy, iy))
            self._text_box_w = abs(ix - sx)
            self._text_box_h = abs(iy - sy)
            self.update()
            return

        # ── Shape/text move drag ──
        if self._moving_shape and self._selected_shape_idx is not None:
            if self._press_pos and (widget_pos - self._press_pos).manhattanLength() > 4:
                self._did_move_shape = True
            sel_item = self._items[self._selected_shape_idx]
            r = _shape_bounding_rect(sel_item)
            new_x = ix - self._move_offset[0]
            new_y = iy - self._move_offset[1]
            dx = new_x - r.left()
            dy = new_y - r.top()
            sx, sy = sel_item['start']
            ex, ey = sel_item['end']
            sel_item['start'] = (sx + dx, sy + dy)
            sel_item['end'] = (ex + dx, ey + dy)
            self._show_selection_action_bar(self._selected_shape_idx)
            self._schedule_repaint()  # PERF-009: Throttle to 60fps
            return

        # ── Shape resize drag ──
        if self._resizing and self._selected_shape_idx is not None and self._resize_handle:
            sel_item = self._items[self._selected_shape_idx]
            if sel_item.get('type') == 'text':
                _resize_shape(sel_item, self._resize_handle, ix, iy,
                              initial_w=self._initial_width, initial_fs=self._initial_font_size)
            else:
                _resize_shape(sel_item, self._resize_handle, ix, iy)
            self._show_selection_action_bar(self._selected_shape_idx)
            self._schedule_repaint()  # PERF-009: Throttle to 60fps
            return

        # ── Hover cursor for resize/move handles ──
        if self._selected_shape_idx is not None and 0 <= self._selected_shape_idx < len(self._items):
            sel_item = self._items[self._selected_shape_idx]
            if 'start' in sel_item:
                handle = _shape_handle_at(sel_item, ix, iy, threshold=16.0/self._scale)
                if handle:
                    self.setCursor(shape_cursor(_HANDLE_CURSORS.get(handle, Qt.CursorShape.SizeAllCursor)))
                    return
                r = _shape_bounding_rect(sel_item)
                if r.adjusted(-8/self._scale, -8/self._scale, 8/self._scale, 8/self._scale).contains(img_pos):
                    self.setCursor(shape_cursor(Qt.CursorShape.SizeAllCursor))
                    return
            self._update_cursor()

        # ── Crop hover cursors (when not actively dragging) ────────────────
        if self._tool == 'crop' and not self._drawing and self._crop_rect:
            cr = self._crop_rect.normalized()
            ix_val, iy_val = img_pos.x(), img_pos.y()
            handle = self._crop_handle_at(cr, ix_val, iy_val)
            _CROP_CURSORS = {
                'tl': Qt.CursorShape.SizeFDiagCursor,
                'br': Qt.CursorShape.SizeFDiagCursor,
                'tr': Qt.CursorShape.SizeBDiagCursor,
                'bl': Qt.CursorShape.SizeBDiagCursor,
                't':  Qt.CursorShape.SizeVerCursor,
                'b':  Qt.CursorShape.SizeVerCursor,
                'l':  Qt.CursorShape.SizeHorCursor,
                'r':  Qt.CursorShape.SizeHorCursor,
            }
            if handle:
                self.setCursor(shape_cursor(_CROP_CURSORS.get(handle, Qt.CursorShape.CrossCursor)))
            elif cr.contains(QPointF(ix_val, iy_val)):
                self.setCursor(shape_cursor(Qt.CursorShape.SizeAllCursor))
            else:
                self.setCursor(shape_cursor(Qt.CursorShape.CrossCursor))

        if not self._drawing:
            return

        if self._tool == 'crop' and self._drawing and self._crop_rect:
            ix = max(0.0, min(float(self._original.width()), ix))
            iy = max(0.0, min(float(self._original.height()), iy))
            orig = self._crop_orig_rect
            start = self._crop_start_pos
            handle = self._crop_drag

            new_r = QRectF(orig)
            if handle == 'move':
                dx = ix - start.x()
                dy = iy - start.y()
                new_r.translate(dx, dy)
            elif handle == 'draw':
                new_r = QRectF(start, QPointF(ix, iy)).normalized()
            else:
                # Free crop is the default. Each edge follows the pointer
                # independently; holding Ctrl temporarily locks the ratio that
                # existed when this drag began (including after an earlier crop).
                left, top, right, bottom = orig.left(), orig.top(), orig.right(), orig.bottom()
                if handle and 'l' in handle:
                    left = ix
                if handle and 'r' in handle:
                    right = ix
                if handle and 't' in handle:
                    top = iy
                if handle and 'b' in handle:
                    bottom = iy
                new_r = QRectF(QPointF(left, top), QPointF(right, bottom)).normalized()

                if (event.modifiers() & Qt.KeyboardModifier.ControlModifier) and handle:
                    ratio = orig.width() / max(orig.height(), 0.001)
                    anchors = {
                        'tl': orig.bottomRight(), 'tr': orig.bottomLeft(),
                        'bl': orig.topRight(), 'br': orig.topLeft(),
                    }
                    anchor = anchors.get(handle)
                    if anchor:
                        dw, dh = ix - anchor.x(), iy - anchor.y()
                        if abs(dw) / max(abs(dh), 0.001) > ratio:
                            dh = math.copysign(abs(dw) / ratio, dh or 1.0)
                        else:
                            dw = math.copysign(abs(dh) * ratio, dw or 1.0)
                        new_r = QRectF(anchor, QPointF(anchor.x() + dw, anchor.y() + dh)).normalized()
                    elif handle in ('l', 'r'):
                        width = abs((ix - orig.right()) if handle == 'l' else (ix - orig.left()))
                        height = width / ratio
                        cy = orig.center().y()
                        new_r.setTop(cy - height / 2.0)
                        new_r.setBottom(cy + height / 2.0)
                    elif handle in ('t', 'b'):
                        height = abs((iy - orig.bottom()) if handle == 't' else (iy - orig.top()))
                        width = height * ratio
                        cx = orig.center().x()
                        new_r.setLeft(cx - width / 2.0)
                        new_r.setRight(cx + width / 2.0)

            new_r = new_r.normalized()
            new_r.setLeft(max(0.0, new_r.left()))
            new_r.setTop(max(0.0, new_r.top()))
            new_r.setRight(min(float(self._original.width()), new_r.right()))
            new_r.setBottom(min(float(self._original.height()), new_r.bottom()))
            self._crop_rect = new_r
            self.update()
            return

        if self._tool == 'eraser':
            self._erase_sweep(self._erase_last_pos, QPointF(img_pos))
            self._erase_last_pos = QPointF(img_pos)
            return

        if not self._current_item:
            return

        if self._current_item['type'] in ('pencil', 'highlighter'):
            pts = self._current_item['points']
            nx, ny = float(img_pos.x()), float(img_pos.y())
            is_ctrl = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
            is_alt = bool(event.modifiers() & Qt.KeyboardModifier.AltModifier)

            if 'anchor' not in self._current_item:
                self._current_item['anchor'] = None

            if is_ctrl or is_alt:
                if self._current_item['anchor'] is None:
                    # Anchor straight line at starting point
                    self._current_item['anchor'] = pts[0] if pts else (nx, ny)
                    pts.append((nx, ny, True))
                else:
                    sx, sy = self._current_item['anchor'][0], self._current_item['anchor'][1]
                    dx, dy = nx - sx, ny - sy
                    if is_alt and (abs(dx) > 0.1 or abs(dy) > 0.1):
                        # Holding Alt -> snap straight line to 45 or 90 degrees
                        angle = math.atan2(dy, dx)
                        snap_angle = round(angle / (math.pi / 4)) * (math.pi / 4)
                        dist = math.hypot(dx, dy)
                        nx = sx + dist * math.cos(snap_angle)
                        ny = sy + dist * math.sin(snap_angle)
                    # Ctrl (without Alt) -> straight line at ANY angle
                    pts[-1] = (nx, ny, True)
            else:
                self._current_item['anchor'] = None
                # Normal freehand drawing with interpolation
                if pts:
                    lx, ly = pts[-1][0], pts[-1][1]
                    dist = math.hypot(nx - lx, ny - ly)
                    steps = int(dist / 3.0)
                    if steps > 1:
                        for i in range(1, steps + 1):
                            ix_pt = lx + (nx - lx) * (i / steps)
                            iy_pt = ly + (ny - ly) * (i / steps)
                            pts.append((ix_pt, iy_pt, False))
                    else:
                        pts.append((nx, ny, False))
                else:
                    pts.append((nx, ny, False))
        elif self._current_item['type'] in ('circle', 'rect', 'arrow'):
            self._current_item['end'] = (img_pos.x(), img_pos.y())

        self._schedule_repaint()  # PERF-009: Throttle to 60fps

    def _erase_sweep(self, start: Optional[QPointF], end: QPointF):
        if start is None:
            self._erase_at(end)
            return
        distance = math.hypot(end.x() - start.x(), end.y() - start.y())
        # Four screen pixels is dense enough that a fast drag cannot jump over
        # a normal stroke. Convert that spacing into image coordinates.
        spacing = 4.0 / max(self._scale, 0.001)
        steps = max(1, int(math.ceil(distance / spacing)))
        for step in range(1, steps + 1):
            amount = step / steps
            self._erase_at(QPointF(
                start.x() + (end.x() - start.x()) * amount,
                start.y() + (end.y() - start.y()) * amount,
            ))

    def _erase_at(self, pos: QPoint):
        new_items = []
        for current_index, item in enumerate(self._items):
            if item.get('_action') or 'type' not in item:
                new_items.append(item)  # History records are not drawable/erasable.
                continue
            if self._hit_test(pos, item):
                if not any(existing is item for _, existing in self._erase_action_items):
                    original_index = self._erase_original_indexes.get(id(item), current_index)
                    self._erase_action_items.append((original_index, item))
            else:
                new_items.append(item)
        if len(new_items) != len(self._items):
            self._items = new_items
            self._redo_stack.clear()  # New action clears redo
            self._has_unsaved = True
            self.modified.emit()
            self._schedule_repaint()  # PERF-009: Throttle to 60fps

    def mouseReleaseEvent(self, event):
        # End middle-click or Space-click pan
        if self._panning and (event.button() == Qt.MouseButton.MiddleButton or event.button() == Qt.MouseButton.LeftButton):
            self._panning = False
            self._update_cursor()
            return

        # End text box creation
        if self._text_box_creating:
            self._text_box_creating = False
            if self._text_box_w > 10 / self._scale and self._text_box_h > 10 / self._scale:
                self._text_box_initial_h = max(34.0, self._text_box_h)
                self._start_text_input(QPointF(self._text_pos[0], self._text_pos[1]))
            else:
                # Just a click? Create a default-sized box
                x, y, self._text_box_w, self._text_box_h = _fit_default_text_box(
                    self._text_pos[0], self._text_pos[1],
                    200.0 / self._scale, 40.0 / self._scale,
                    self._original.width(), self._original.height(),
                )
                self._text_pos = (x, y)
                self._text_box_initial_h = self._text_box_h
                self._start_text_input(QPointF(self._text_pos[0], self._text_pos[1]))
            self._drawing = False
            return

        # End shape/text move
        if self._moving_shape:
            if self._selected_shape_idx is not None:
                target = self._items[self._selected_shape_idx]
                before = getattr(self, '_move_before', dict(target))
                if before != target:
                    self._items.append({'_action': 'update', '_target': target,
                                        '_before': before, '_after': dict(target)})
                    self._redo_stack.clear()
                    if hasattr(self, '_has_unsaved'):
                        self._has_unsaved = True
            self._moving_shape = False
            self._did_move_shape = False
            self._press_pos = None
            self.modified.emit()
            if self._selected_shape_idx is not None:
                self._show_selection_action_bar(self._selected_shape_idx)
            self.update()
            return

        # End shape resize
        if self._resizing:
            self._resizing = False
            self._resize_handle = None
            self.modified.emit()
            if self._selected_shape_idx is not None:
                self._show_selection_action_bar(self._selected_shape_idx)
            self.update()
            return

        if not self._drawing:
            return
        self._drawing = False

        if self._tool == 'eraser':
            if self._erase_action_items:
                self._items.append({
                    '_action': 'erase',
                    '_erased_items': sorted(self._erase_action_items, key=lambda entry: entry[0]),
                })
            self._erase_action_items = []
            self._erase_original_indexes = {}
            self._erase_last_pos = None
            self.update()
            return
        
        if self._tool == 'crop':
            self._crop_drag = None
            if self._crop_rect:
                self._crop_rect = self._crop_rect.normalized()
                self._crop_orig_rect = QRectF(self._crop_rect)
            self.update()
            return
            
        if self._current_item:
            t = self._current_item['type']
            valid = False
            if t in ('pencil', 'highlighter'):
                pts = self._current_item['points']
                if len(pts) > 1:
                    has_straight = any(len(p) > 2 and p[2] for p in pts)
                    if not has_straight:
                        self._current_item['points'] = _smooth_points(pts)
                    valid = True
            elif t in ('circle', 'rect', 'arrow'):
                sx, sy = self._current_item['start']
                ex, ey = self._current_item['end']
                valid = abs(ex - sx) > 3 or abs(ey - sy) > 3
            if valid:
                self._items.append(self._current_item)
                self._has_unsaved = True
                self.modified.emit()
            self._current_item = None
        self.update()

    def wheelEvent(self, event):
        """Improvement 7: Zoom via Ctrl+Scroll and trackpad Pan via Scroll"""
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            old_zoom = self._zoom_level
            
            if delta > 0:
                self._zoom_level = min(5.0, self._zoom_level * 1.15)
            elif delta < 0:
                self._zoom_level = max(0.25, self._zoom_level / 1.15)
            
            if self._zoom_level != old_zoom:
                pos = event.position().toPoint()
                img_x = (pos.x() - self._offset_x) / self._scale
                img_y = (pos.y() - self._offset_y) / self._scale
                
                self._scale = self._get_base_scale() * self._zoom_level
                
                self._offset_x = pos.x() - img_x * self._scale
                self._offset_y = pos.y() - img_y * self._scale
                self._clamp_offsets()
                
            self.update()
            event.accept()
        else:
            delta = event.angleDelta()
            if not delta.isNull():
                self._offset_x += delta.x()
                self._offset_y += delta.y()
                self._clamp_offsets()
                self.update()
                event.accept()
            else:
                super().wheelEvent(event)

    # ── Keyboard (text tool) ──────────────────────────────────────────────────

    def keyPressEvent(self, event):
        if self._text_input_active:
            # Let _text_edit handle its own key events directly; do NOT call sendEvent (prevents recursion crash)
            return

        # Non-text shortcuts
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if event.key() == Qt.Key.Key_Z:
                self.undo()
            elif event.key() == Qt.Key.Key_Y:
                self.redo()
            elif event.key() == Qt.Key.Key_S:
                self.save_image()
                
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self._space_pressed = True
            if not self._text_input_active:
                self.setCursor(Qt.CursorShape.OpenHandCursor)

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self._space_pressed = False
            self._update_cursor()

    def _make_text_font(self) -> QFont:
        """Build a QFont from the current text toolbar settings."""
        size = self._text_bar.get_font_size() if self._text_bar else 16
        weight = QFont.Weight.Bold if (self._text_bar and self._text_bar.is_bold()) else QFont.Weight.Normal
        font = QFont("Segoe UI", size, weight)
        if self._text_bar:
            font.setItalic(self._text_bar.is_italic())
            font.setUnderline(self._text_bar.is_underline())
        return font

    def _apply_text_editor_style(self):
        if not getattr(self, '_text_edit', None):
            return
        font = self._make_text_font()
        scaled_size = max(0.1, font.pointSizeF() * self._scale)
        font.setPointSizeF(scaled_size)
        font_weight = "bold" if font.bold() else "normal"
        font_style = "italic" if font.italic() else "normal"
        text_decoration = "underline" if font.underline() else "none"
        self._text_edit.setFont(font)
        self._text_edit.document().setDefaultFont(font)
        self._text_edit.setStyleSheet(f"""
            QPlainTextEdit {{
                background: rgba(20, 20, 24, 190);
                color: {self._color.name()};
                border: 2px dashed #EF4444;
                border-radius: 6px;
                padding: 6px 8px;
                font-family: 'Segoe UI';
                font-size: {scaled_size}pt;
                font-weight: {font_weight};
                font-style: {font_style};
                text-decoration: {text_decoration};
                selection-background-color: rgba(220, 38, 38, 160);
            }}
        """)
        self._auto_resize_text_editor()

    def _is_inside_text_box(self, img_pos) -> bool:
        """Check if the given image-coord point is inside the current text input area."""
        if not self._text_input_active or not self._text_pos:
            return False
        px = img_pos.x() if hasattr(img_pos, 'x') else img_pos[0]
        py = img_pos.y() if hasattr(img_pos, 'y') else img_pos[1]
        x, y = self._text_pos
        rect = QRectF(x, y, self._text_box_w, self._text_box_h)
        return rect.adjusted(-6 / self._scale, -6 / self._scale, 6 / self._scale, 6 / self._scale).contains(QPointF(px, py))

    def _auto_resize_text_editor(self):
        if not self._text_input_active or not self._text_pos or not getattr(self, '_text_edit', None):
            return
        font = self._make_text_font()
        fm = QFontMetrics(font)
        text = self._text_edit.toPlainText()
        lines = text.split('\n') if text else [""]
        line_count = max(len(lines), 1)
        line_height = max(fm.height(), 18)

        # Horizontal sizing: expand if typed text exceeds initial box width
        max_line_w = max((fm.horizontalAdvance(ln) for ln in lines), default=20)
        needed_w = max_line_w + 36
        box_w = max(float(getattr(self, '_text_box_w', 120.0)), float(needed_w), 80.0)
        self._text_box_w = float(box_w)

        # Vertical sizing: expand if lines exceed initial box height
        doc = self._text_edit.document()
        doc.setTextWidth((box_w - 16.0) * self._scale)
        doc_h = (doc.size().height() / max(self._scale, 0.001)) + 16.0
        needed_h = max(float(line_count * line_height + 20), doc_h)

        display_h = max(float(getattr(self, '_text_box_initial_h', 34.0)), needed_h)
        self._text_box_h = float(display_h)
        
        wx = int(self._text_pos[0] * self._scale + self._offset_x)
        wy = int(self._text_pos[1] * self._scale + self._offset_y)
        ww = max(60, int(box_w * self._scale))
        wh = max(34, int(display_h * self._scale))
        editor_x, editor_y = _text_editor_top_left(wx, wy)
        self._text_edit.setGeometry(editor_x, editor_y, ww + 10, wh + 8)
        self._reposition_text_bar()
        self.update()

    def _begin_edit_text(self, idx: int):
        if idx < 0 or idx >= len(self._items):
            return
        item = self._items[idx]
        if item.get('type') != 'text':
            return
        self._editing_text_index = idx
        self._editing_text_backup = self._items.pop(idx)
        self._selected_shape_idx = None
        if hasattr(self, '_action_bar'):
            self._action_bar.hide()
        sx, sy = item['start']
        ex, ey = item['end']
        self._text_box_w = max(abs(ex - sx), 40.0)
        self._text_box_h = max(abs(ey - sy), 34.0)
        self._text_box_initial_h = self._text_box_h
        self._text_pos = (min(sx, ex), min(sy, ey))
        self._color = QColor(item['color'])
        self._text_bar.set_defaults(
            font_size=item.get('font_size', 16),
            bold=item.get('bold', False),
            italic=item.get('italic', False),
            underline=item.get('underline', False),
        )
        self._start_text_input(QPointF(self._text_pos[0], self._text_pos[1]))
        self._text_edit.blockSignals(True)
        self._text_edit.setPlainText(item.get('text', ''))
        cursor = self._text_edit.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self._text_edit.setTextCursor(cursor)
        self._text_edit.blockSignals(False)
        self._auto_resize_text_editor()

    def _reposition_text_bar(self):
        if not self._text_input_active or not self._text_pos or not self._text_bar.isVisible():
            return
        wx = int(self._text_pos[0] * self._scale + self._offset_x)
        wy = int(self._text_pos[1] * self._scale + self._offset_y)
        wh = max(34, int(self._text_box_h * self._scale))
        bar_x = wx - 6
        bar_y = wy - self._text_bar.height() - 8
        if bar_y < 5:
            bar_y = wy + wh + 8
        self._text_bar.move(bar_x, bar_y)

    def _start_text_input(self, img_pos: QPointF):
        self._text_input_active = True
        self._text_pos = (img_pos.x(), img_pos.y())
        self._text_buffer = ""
        self._cursor_visible = True
        self._cursor_timer.start()
        self.setFocus()
        if hasattr(self, '_action_bar'):
            self._action_bar.hide()
        
        display_h = max(float(getattr(self, '_text_box_initial_h', 34.0)), float(self._text_box_h))
        self._text_box_h = display_h
        wx = int(img_pos.x() * self._scale + self._offset_x)
        wy = int(img_pos.y() * self._scale + self._offset_y)
        ww = max(60, int(self._text_box_w * self._scale))
        wh = max(34, int(display_h * self._scale))
        
        bar_x = wx - 6
        bar_y = wy - self._text_bar.height() - 8
        if bar_y < 5:
            bar_y = wy + wh + 8
        self._text_bar.move(bar_x, bar_y)
        self._text_bar.show()
        self._text_bar.raise_()
        
        self._text_edit.blockSignals(True)
        self._text_edit.clear()
        self._text_edit.blockSignals(False)
        self._apply_text_editor_style()
        self._auto_resize_text_editor()
        self._text_edit.show()
        _align_new_text_caret(self, (wx, wy), self._scale)
        self._text_edit.raise_()
        self._text_edit.setFocus(Qt.FocusReason.OtherFocusReason)
        self.update()

    def _clamp_offsets(self):
        iw = self._original.width() * self._scale
        ih = self._original.height() * self._scale
        # Require at least 150px of overlap, or the whole image if it's tiny
        margin_x = min(150.0, iw, float(self.width()))
        margin_y = min(150.0, ih, float(self.height()))
        
        min_x = margin_x - iw
        max_x = self.width() - margin_x
        if min_x > max_x:
            min_x = (self.width() - iw) / 2
            max_x = min_x
            
        min_y = margin_y - ih
        max_y = self.height() - margin_y
        if min_y > max_y:
            min_y = (self.height() - ih) / 2
            max_y = min_y
            
        self._offset_x = max(min_x, min(max_x, self._offset_x))
        self._offset_y = max(min_y, min(max_y, self._offset_y))

    def _finish_text_history(self):
        self._text_result_index = len(self._items) - 1
        if self._editing_text_backup is not None:
            replacement = self._items.pop()
            target = self._editing_text_backup
            before = dict(target)
            target.clear()
            target.update(replacement)
            index = min(self._editing_text_index, len(self._items))
            self._items.insert(index, target)
            self._items.append({'_action': 'update', '_target': target,
                                '_before': before, '_after': dict(target)})
            self._text_result_index = index

    def _commit_text(self):
        text = self._text_edit.toPlainText() if getattr(self, '_text_edit', None) else self._text_buffer
        if self._text_input_active and text.strip():
            font = self._make_text_font()
            fm = QFontMetrics(font)
            lines = text.split('\n')

            # Tight horizontal & vertical wrap around actual text content
            max_line_w = max((fm.horizontalAdvance(ln) for ln in lines), default=20)
            tight_w = max(float(max_line_w), 20.0)

            line_height = max(fm.height(), 16)
            tight_h = max(float(len(lines) * line_height), float(line_height))

            self._items.append({
                'type': 'text',
                'start': self._text_pos,
                'end': (self._text_pos[0] + tight_w, self._text_pos[1] + tight_h),
                'text': text,
                'color': self._color.name(),
                'font_size': self._text_bar.get_font_size() if self._text_bar else 16,
                'bold': self._text_bar.is_bold() if self._text_bar else False,
                'italic': self._text_bar.is_italic() if self._text_bar else False,
                'underline': self._text_bar.is_underline() if self._text_bar else False,
            })
            self._finish_text_history()
            self._redo_stack.clear()
            self._has_unsaved = True
            self.modified.emit()
            self._selected_shape_idx = self._text_result_index
            self._show_selection_action_bar(self._selected_shape_idx)
        if self._editing_text_backup is not None and not text.strip():
            self._items.insert(min(self._editing_text_index, len(self._items)), self._editing_text_backup)
        self._text_input_active = False
        self._text_buffer = ""
        self._editing_text_backup = None
        self._cursor_timer.stop()
        self._text_bar.hide()
        if getattr(self, '_text_edit', None):
            self._text_edit.blockSignals(True)
            self._text_edit.hide()
            self._text_edit.clear()
            self._text_edit.blockSignals(False)
        self.update()

    def _cancel_text(self):
        if not self._text_input_active:
            return
        if self._editing_text_backup is not None:
            self._items.insert(min(self._editing_text_index, len(self._items)), self._editing_text_backup)
            self._editing_text_backup = None
        self._text_input_active = False
        self._text_buffer = ""
        self._cursor_timer.stop()
        self._text_bar.hide()
        if getattr(self, '_text_edit', None):
            self._text_edit.blockSignals(True)
            self._text_edit.hide()
            self._text_edit.clear()
            self._text_edit.blockSignals(False)
        self.update()

    def _blink_cursor(self):
        self._cursor_visible = not self._cursor_visible
        if self._text_input_active:  # PERF-009: Only repaint when text cursor is visible
            self.update()

    def _schedule_repaint(self):
        """PERF-009: Throttle repaints to ~60fps instead of calling update() on every mouse event."""
        if not self._repaint_dirty:
            self._repaint_dirty = True
            if not self._repaint_timer.isActive():
                self._repaint_timer.start()

    def _flush_repaint(self):
        """Actually trigger the repaint if dirty."""
        if self._repaint_dirty:
            self._repaint_dirty = False
            self.update()
        else:
            self._repaint_timer.stop()

    # ── Paint ─────────────────────────────────────────────────────────────────

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        # Dark background
        p.fillRect(self.rect(), QColor(18, 18, 20))

        # Checkerboard under image for transparency visibility
        p.save()
        p.translate(self._offset_x, self._offset_y)
        p.scale(self._scale, self._scale)

        # Draw the image
        p.drawImage(0, 0, self._original)

        # Draw committed items (in image coords)
        for item in self._items:
            if item.get('type') != 'transform':
                draw_annotation_item(p, item)

        # Draw in-progress item
        if self._current_item:
            draw_annotation_item(p, self._current_item)

        # Draw selection box on selected text item
        if self._selected_shape_idx is not None and 0 <= self._selected_shape_idx < len(self._items):
            sel = self._items[self._selected_shape_idx]
            if sel.get('type') == 'text':
                _draw_shape_handles(p, sel, scale=self._scale)

        # Text input box preview (during creation)
        if self._text_box_creating:
            p.setPen(QPen(QColor("#EF4444"), 2.0 / self._scale, Qt.PenStyle.DashLine))
            p.setBrush(QColor(239, 68, 68, 25))
            p.drawRoundedRect(QRectF(self._text_pos[0], self._text_pos[1], self._text_box_w, self._text_box_h), 4.0 / self._scale, 4.0 / self._scale)

        # Text input preview
        if self._text_input_active and self._text_pos and not (getattr(self, '_text_edit', None) and self._text_edit.isVisible()):
            color = QColor(self._color.name())
            font = self._make_text_font()
            fm = QFontMetrics(font)
            p.setFont(font)
            p.setPen(QPen(color))

            x, y = self._text_pos
            line_height = fm.height()

            # Keep words together when possible, then break an oversized word only as needed.
            layout = QTextLayout(self._text_buffer, font)
            opt = QTextOption()
            opt.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
            layout.setTextOption(opt)

            layout.beginLayout()
            y_offset = 0.0
            while True:
                line = layout.createLine()
                if not line.isValid():
                    break
                line.setLineWidth(self._text_box_w)
                line.setPosition(QPointF(0, y_offset))
                y_offset += line_height
            layout.endLayout()

            # Draw the text using the layout
            layout.draw(p, QPointF(x, y))

            # Update box height to fit all wrapped lines
            self._text_box_h = max(y_offset, line_height + 4)

            # Draw border
            pad = 6 / self._scale
            border_rect = QRectF(x - pad, y - pad, self._text_box_w + pad * 2, self._text_box_h + pad * 2)
            
            p.drawRoundedRect(border_rect, 4, 4)
            # 2. White dash
            p.setPen(QPen(QColor(255, 255, 255, 200), 1.0 / self._scale, Qt.PenStyle.DashLine))
            p.drawRoundedRect(border_rect, 4, 4)

            # Blinking cursor uses the same QTextLayout wrapping logic.
            if self._cursor_visible:
                p.setPen(QPen(color, 2 / self._scale))
                cx, cy_top, cy_bot = _calc_cursor_pos(
                    self._text_buffer, font, int(self._text_box_w), x, y)
                p.drawLine(int(cx), int(cy_top), int(cx), int(cy_bot))

            # Keep toolbar firmly anchored above the text box
            if self._text_bar and self._text_bar.isVisible():
                border_top_widget = int((y - pad) * self._scale + self._offset_y)
                border_left_widget = int((x - pad) * self._scale + self._offset_x)
                bar_y = border_top_widget - self._text_bar.height() - 4
                if bar_y < 5:
                    bar_y = int((y + self._text_box_h + pad) * self._scale + self._offset_y) + 4
                self._text_bar.move(border_left_widget, bar_y)

        # Draw crop rect
        if self._tool == 'crop' and self._crop_rect:
            cr = self._crop_rect.normalized()
            iw = float(self._original.width())
            ih = float(self._original.height())

            # Outer dark overlay
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, 140))
            p.drawRect(QRectF(0, 0, iw, cr.top()))
            p.drawRect(QRectF(0, cr.bottom(), iw, ih - cr.bottom()))
            p.drawRect(QRectF(0, cr.top(), cr.left(), cr.height()))
            p.drawRect(QRectF(cr.right(), cr.top(), iw - cr.right(), cr.height()))

            # Dashed white border
            pen = QPen(QColor(255, 255, 255, 220), 1.5 / self._scale, Qt.PenStyle.SolidLine)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(cr)

            # Rule-of-thirds grid
            thin = QPen(QColor(255, 255, 255, 70), 0.5 / self._scale)
            p.setPen(thin)
            for i in (1, 2):
                x = cr.left() + cr.width() * i / 3
                y = cr.top() + cr.height() * i / 3
                p.drawLine(QPointF(x, cr.top()), QPointF(x, cr.bottom()))
                p.drawLine(QPointF(cr.left(), y), QPointF(cr.right(), y))

            # Corner handles (L-shaped brackets, like real crop tools)
            hlen = min(12.0 / self._scale, cr.width() / 4, cr.height() / 4)
            hw = 2.5 / self._scale
            hp = QPen(QColor(255, 255, 255), hw)
            hp.setCapStyle(Qt.PenCapStyle.SquareCap)
            p.setPen(hp)
            corners = [
                (cr.left(),  cr.top(),    1,  1),
                (cr.right(), cr.top(),   -1,  1),
                (cr.left(),  cr.bottom(), 1, -1),
                (cr.right(), cr.bottom(),-1, -1),
            ]
            for cx, cy, sx, sy in corners:
                p.drawLine(QPointF(cx, cy), QPointF(cx + sx * hlen, cy))
                p.drawLine(QPointF(cx, cy), QPointF(cx, cy + sy * hlen))

            # Edge midpoint handles (small squares)
            sq = 4.0 / self._scale
            p.setBrush(QColor(255, 255, 255))
            p.setPen(QPen(QColor(0,0,0,180), 0.8 / self._scale))
            mids = [
                (cr.center().x(), cr.top()),
                (cr.center().x(), cr.bottom()),
                (cr.left(),  cr.center().y()),
                (cr.right(), cr.center().y()),
            ]
            for mx, my in mids:
                p.drawRect(QRectF(mx - sq, my - sq, sq * 2, sq * 2))

            # Instruction text (drawn in widget coords after p.restore)
        p.restore()
        p.end()

        # Draw instruction text in widget coords (outside scaling transform)
        if self._tool == 'crop' and self._crop_rect:
            cr = self._crop_rect.normalized()
            wp = QPainter(self)
            wp.setRenderHint(QPainter.RenderHint.Antialiasing)
            # Convert image coords → widget coords for the text position
            text_y_img = cr.top()
            text_y_widget = text_y_img * self._scale + self._offset_y
            text_x_widget = cr.left() * self._scale + self._offset_x
            text_w_widget = cr.width() * self._scale
            HINT = "Hold Ctrl to lock aspect ratio while cropping."
            font = QFont("Segoe UI", 10, QFont.Weight.Bold)
            wp.setFont(font)
            fm2 = QFontMetrics(font)
            th = fm2.height() + 6
            ty = max(2, text_y_widget - th - 4)
            # Background pill
            pill_rect = QRectF(text_x_widget, ty, text_w_widget, th)
            wp.setBrush(QColor(0, 0, 0, 160))
            wp.setPen(Qt.PenStyle.NoPen)
            wp.drawRoundedRect(pill_rect, 4, 4)
            wp.setPen(QColor(255, 255, 255, 220))
            wp.drawText(pill_rect, Qt.AlignmentFlag.AlignCenter, HINT)
            wp.end()


# ─────────────────────────────────────────────────────────────────────────────
#  Text Edit Toolbar (shown during text input)
# ─────────────────────────────────────────────────────────────────────────────

class _TextEditBar(QWidget):
    """Small floating toolbar for text formatting: font size, bold, italic, underline."""
    formatting_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(32)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("""
            _TextEditBar {
                background: rgba(28, 28, 30, 240);
                border: 1px solid #3C3C3E;
                border-radius: 6px;
            }
        """)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 2, 6, 2)
        lay.setSpacing(3)

        # Font size combo
        self._combo_size = QComboBox()
        self._combo_size.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._combo_size.addItems(['10', '12', '14', '16', '20', '24', '32', '48'])
        self._combo_size.setCurrentText('16')
        self._combo_size.setFixedWidth(58)
        self._combo_size.setFixedHeight(24)
        self._combo_size.currentTextChanged.connect(self.formatting_changed.emit)
        down_arrow = _asset("spn_down.png").replace("\\", "/")
        self._combo_size.setStyleSheet("""
            QComboBox {
                background: #252528; color: white; border: 1px solid #3C3C3E;
                border-radius: 4px; padding: 0 14px 0 6px; font-size: 11px; font-family: 'Segoe UI';
            }
            QComboBox:hover { background: #2E2E32; }
            QComboBox::drop-down {
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 14px;
                border-left: none;
            }
            QComboBox::down-arrow {
                image: url("__DOWN_ARROW__");
                width: 10px;
                height: 10px;
                margin-right: 3px;
            }
            QComboBox QAbstractItemView {
                background: #1C1C1E; color: white; border: 1px solid #3C3C3E;
                selection-background-color: #DC2626;
            }
        """.replace("__DOWN_ARROW__", down_arrow))
        lay.addWidget(self._combo_size)

        # Separator
        sep = QFrame()
        sep.setFixedSize(1, 18)
        sep.setStyleSheet("background: #3C3C3E;")
        lay.addWidget(sep)

        # Bold / Italic / Underline
        self._btn_bold = self._make_fmt_btn("B", "font-weight: 900;")
        self._btn_italic = self._make_fmt_btn("I", "font-style: italic;")
        self._btn_underline = self._make_fmt_btn("U", "text-decoration: underline;")
        self._btn_bold.toggled.connect(self.formatting_changed.emit)
        self._btn_italic.toggled.connect(self.formatting_changed.emit)
        self._btn_underline.toggled.connect(self.formatting_changed.emit)
        lay.addWidget(self._btn_bold)
        lay.addWidget(self._btn_italic)
        lay.addWidget(self._btn_underline)

        self.adjustSize()

    def _make_fmt_btn(self, label: str, font_css: str) -> QPushButton:
        btn = QPushButton(label)
        from icon_theme import CONTROL_STYLE
        name = {"B": "bold", "I": "italic", "U": "underline"}[label]
        btn.setText("")
        btn.setIcon(QIcon(_asset(name + ".png")))
        btn.setIconSize(QSize(20, 20))
        btn.setToolTip(name.title())
        btn.setAccessibleName(name.title())
        btn.setCheckable(True)
        btn.setFixedSize(26, 24)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn.setStyleSheet(f"""
            QPushButton {{
                background: #252528; color: white; border: 1px solid #3C3C3E;
                border-radius: 4px; font-size: 12px; font-family: 'Segoe UI';
                {font_css}
            }}
            QPushButton:hover {{ background: #333336; }}
            QPushButton:checked {{
                background: rgba(220, 38, 38, 0.3); border: 1px solid #DC2626;
            }}
        """)
        return btn

    def get_font_size(self) -> int:
        try:
            return int(self._combo_size.currentText())
        except ValueError:
            return 16

    def is_bold(self) -> bool:
        return self._btn_bold.isChecked()

    def is_italic(self) -> bool:
        return self._btn_italic.isChecked()

    def is_underline(self) -> bool:
        return self._btn_underline.isChecked()

    def set_defaults(self, font_size=16, bold=True, italic=False, underline=False):
        self._combo_size.setCurrentText(str(font_size))
        self._btn_bold.setChecked(bold)
        self._btn_italic.setChecked(italic)
        self._btn_underline.setChecked(underline)


# ─────────────────────────────────────────────────────────────────────────────
#  Smart Tooltip & Color Picker Button
# ─────────────────────────────────────────────────────────────────────────────

def _show_smart_tooltip(widget: QWidget):
    """Show tooltip placed cleanly beside the toolbar so it never overlaps or gets hidden."""
    tip = widget.toolTip()
    if not tip:
        return

    tl = widget.mapToGlobal(QPoint(0, 0))
    w = widget.width()
    h = widget.height()

    window = widget.window()
    dock_edge = getattr(window, '_dock_edge', 'left')
    orientation = getattr(window, '_orientation', 'vertical')

    screen = QApplication.screenAt(tl) or QApplication.primaryScreen()
    sg = screen.availableGeometry() if screen else QRect(0, 0, 1920, 1080)

    fm = QFontMetrics(QApplication.font())
    tip_w = max(90, fm.horizontalAdvance(tip) + 20)
    tip_h = 26

    if orientation == 'horizontal':
        if dock_edge == 'bottom':
            pos_x = min(max(sg.left() + 4, tl.x() + (w - tip_w) // 2), sg.right() - tip_w - 4)
            pos_y = tl.y() - tip_h - 6
        else:
            pos_x = min(max(sg.left() + 4, tl.x() + (w - tip_w) // 2), sg.right() - tip_w - 4)
            pos_y = tl.y() + h + 6
    else:
        if dock_edge == 'right':
            pos_x = tl.x() - tip_w - 8
            pos_y = tl.y() + (h - tip_h) // 2
        else:
            pos_x = tl.x() + w + 8
            pos_y = tl.y() + (h - tip_h) // 2

    pos_x = max(sg.left() + 4, min(pos_x, sg.right() - tip_w - 4))
    pos_y = max(sg.top() + 4, min(pos_y, sg.bottom() - tip_h - 4))

    QToolTip.showText(QPoint(int(pos_x), int(pos_y)), tip, widget)


class _ColorDot(QPushButton):
    """Small circular color swatch button."""
    color_picked = pyqtSignal(QColor)

    def __init__(self, hex_color: str, size: int = 30, parent=None):
        super().__init__(parent)
        self._hex = hex_color
        self._qcolor = QColor(hex_color)
        self._selected = False
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_AlwaysShowToolTips, True)
        self.setStyleSheet("QPushButton { background: transparent; border: none; }")
        self.clicked.connect(lambda: self.color_picked.emit(self._qcolor))

    def set_selected(self, selected: bool):
        self._selected = selected
        self.update()

    def enterEvent(self, event):
        _show_smart_tooltip(self)
        super().enterEvent(event)

    def leaveEvent(self, event):
        QToolTip.hideText()
        super().leaveEvent(event)

    def event(self, e):
        if e.type() == QEvent.Type.ToolTip:
            _show_smart_tooltip(self)
            e.accept()
            return True
        return super().event(e)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Precise geometric center
        w = float(self.width())
        h = float(self.height())
        cx = w / 2.0
        cy = h / 2.0
        
        # Max radius that comfortably fits within the button square
        base_radius = (min(w, h) / 2.0) - 2.5
        
        if self._selected:
            # Outer white selection ring (centered)
            p.setPen(QPen(QColor(255, 255, 255, 240), 1.8))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(cx, cy), base_radius, base_radius)

            # Inner color circle (centered with a clean gap from the ring)
            if self._qcolor.lightness() < 40:
                p.setPen(QPen(QColor(255, 255, 255, 120), 1.0))
            else:
                p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(self._qcolor))
            p.drawEllipse(QPointF(cx, cy), base_radius - 3.5, base_radius - 3.5)
        else:
            # Clean color circle (for dark/black colors, draw a subtle contrast ring so it is clearly visible)
            r = base_radius - 1.5
            if self._qcolor.lightness() < 40:
                p.setPen(QPen(QColor(255, 255, 255, 140), 1.2))
            else:
                p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(self._qcolor))
            p.drawEllipse(QPointF(cx, cy), r, r)

        p.end()


# ─────────────────────────────────────────────────────────────────────────────
#  Annotation Tool Button (used in both pill and AnnotateWindow)
# ─────────────────────────────────────────────────────────────────────────────

class _AnnotationToolBtn(QToolButton):
    """Small tool button for annotation tools in the pill and editor."""

    def __init__(self, icon_name: str, tooltip: str, fallback_text: str = "",
                 size: int = 30, icon_size: int = 16, checkable: bool = False):
        super().__init__()
        self.setToolTip(tooltip)
        self.setAccessibleName(tooltip.split(" (")[0])
        self.setAttribute(Qt.WidgetAttribute.WA_AlwaysShowToolTips, True)
        self.setCheckable(checkable)
        self.setFixedSize(size, size)
        visible_size = min(size - 6, max(22, icon_size))
        self.setIconSize(QSize(visible_size, visible_size))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._available = True

        icon_path = _asset(icon_name)
        if os.path.isfile(icon_path):
            if icon_name == 'clear_brush.png':
                self.setIconSize(QSize(min(size - 4, 28), min(size - 4, 28)))
                # Fit generated artwork by its alpha bounds, not its export canvas.
                # The source artwork remains intact; only toolbar display is fitted.
                from PyQt6.QtGui import QBitmap, QRegion
                image = QImage(icon_path)
                bounds = QRegion(QBitmap.fromImage(image.createAlphaMask())).boundingRect()
                if not bounds.isEmpty():
                    image = image.copy(bounds)
                glyph = QPixmap.fromImage(image).scaled(56, 56, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                fitted = QPixmap(64, 64)
                fitted.fill(Qt.GlobalColor.transparent)
                painter = QPainter(fitted)
                painter.drawPixmap((64-glyph.width())//2, (64-glyph.height())//2, glyph)
                painter.end()
                self.setIcon(QIcon(fitted))
            else:
                self.setIcon(QIcon(icon_path))
        elif fallback_text:
            self.setText(fallback_text)
            self.setStyleSheet(self.styleSheet() + f"font-size: {icon_size - 2}px;")

        self._active_icon = self.icon()
        self._apply_style()

    def _apply_style(self):
        from icon_theme import CONTROL_STYLE
        self.setStyleSheet(CONTROL_STYLE + "QToolButton[available=\"false\"] {background:#191E28;border-color:#303744;}")

    def set_available(self, available: bool) -> None:
        """Keep tooltips hoverable while preventing unavailable actions."""
        self._available = available
        self.setProperty("available", available)
        if hasattr(self, "_active_icon"):
            self.setIcon(self._active_icon if available else QIcon(self._active_icon.pixmap(self.iconSize(), QIcon.Mode.Disabled)))
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def enterEvent(self, event):
        _show_smart_tooltip(self)
        super().enterEvent(event)

    def leaveEvent(self, event):
        QToolTip.hideText()
        super().leaveEvent(event)

    def event(self, e):
        if e.type() == QEvent.Type.ToolTip:
            _show_smart_tooltip(self)
            e.accept()
            return True
        return super().event(e)

    def mousePressEvent(self, event):
        if not self._available:
            event.accept()
            return
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if not self._available and event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            event.accept()
            return
        super().keyPressEvent(event)


class _PinToolButton(QToolButton):
    """Drag handle with six dots — always draggable, no pin toggle."""
    toolbar_drag = pyqtSignal(object)

    def __init__(self, parent=None, size: int = 30):
        super().__init__(parent)
        self.setCheckable(False)
        self.setFixedSize(size, size)
        self.setCursor(shape_cursor(Qt.CursorShape.SizeAllCursor))
        self.setToolTip("Drag to reposition toolbar")
        self.setAccessibleName("Move annotation toolbar")
        self.setAttribute(Qt.WidgetAttribute.WA_AlwaysShowToolTips, True)
        self._press_global = None
        self._dragging = False
        self.setStyleSheet("""
            QToolButton {
                background: transparent;
                border: none;
                border-radius: 6px;
                padding: 0;
            }
            QToolButton:hover { background: rgba(255,255,255,0.08); }
        """)

    def enterEvent(self, event):
        _show_smart_tooltip(self)
        super().enterEvent(event)

    def leaveEvent(self, event):
        QToolTip.hideText()
        super().leaveEvent(event)

    def event(self, e):
        if e.type() == QEvent.Type.ToolTip:
            _show_smart_tooltip(self)
            e.accept()
            return True
        return super().event(e)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_global = event.globalPosition().toPoint()
            self._dragging = False
        event.accept()

    def mouseMoveEvent(self, event):
        if (
            self._press_global is not None
            and event.buttons() & Qt.MouseButton.LeftButton
        ):
            if (event.globalPosition().toPoint() - self._press_global).manhattanLength() > 4:
                self._dragging = True
                self.toolbar_drag.emit(event)
        event.accept()

    def mouseReleaseEvent(self, event):
        if self._dragging:
            self._dragging = False
            self._press_global = None
            self.toolbar_drag.emit(event)
            event.accept()
            return
        self._press_global = None
        event.accept()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()
        cx = w / 2.0
        cy = h / 2.0
        dot_r = 1.6
        gap_x = 5.0
        gap_y = 4.0

        color = QColor(100, 116, 139)
        if self.underMouse():
            color = QColor(203, 213, 225)

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(color))

        # 2 columns × 3 rows = 6 dots
        for col in (-1, 1):
            for row in (-1, 0, 1):
                x = cx + col * gap_x / 2.0
                y = cy + row * gap_y
                p.drawEllipse(QPointF(x, y), dot_r, dot_r)

        p.end()

# ─────────────────────────────────────────────────────────────────────────────
#  Thickness Button & Picker
# ─────────────────────────────────────────────────────────────────────────────

class _ThicknessButton(_AnnotationToolBtn):
    """Button showing a refined stroke-gauge and active color preview."""
    def __init__(self, tooltip: str, size: int = 34, icon_size: int = 18, compact: bool = False):
        super().__init__('', tooltip, '', size=size, icon_size=icon_size)
        self._current_label = "Normal"
        self._compact = compact
        self._preview_color = QColor("#FF3B30")
        self._preview_tool = "pencil"
        self._preview_thickness = "normal"
        if compact:
            self.setFixedSize(size, size)
        else:
            self.setFixedWidth(86)

    def set_compact(self, compact: bool):
        self._compact = compact
        if compact:
            self.setFixedSize(self.height(), self.height())
        else:
            self.setFixedWidth(86)
        self.update()

    def set_thickness_label(self, label: str):
        self._current_label = label.capitalize()
        self._preview_thickness = label.lower()
        self.update()

    def set_preview(self, tool_id: str, color: QColor):
        """Update the tool and color for the stroke preview."""
        self._preview_tool = tool_id
        self._preview_color = QColor(color)
        self.update()

    def _gauge_center_x(self) -> float:
        """Keep the full editor's preview clear of its label and arrow."""
        return self.width() / 2.0 if self._compact else 17.0

    def paintEvent(self, event):
        # Draw base button background (from parent stylesheet)
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = float(self.width())
        h = float(self.height())
        cx = self._gauge_center_x()
        cy = h / 2.0

        # Outer gauge ring (gives it a polished tool appearance rather than a raw blob)
        gauge_r = (min(w, h) / 2.0) - 3.5
        ring_color = QColor("#3B475B") if self.underMouse() else QColor("#262E3D")
        p.setPen(QPen(ring_color, 1.2))
        p.setBrush(QBrush(QColor("#151922")))
        p.drawEllipse(QPointF(cx, cy), gauge_r, gauge_r)

        # A diagonal stroke inside the ring distinguishes thickness from
        # the laser dot. Normalize each tool's real widths to the same gauge.
        group = self._preview_tool
        if group in ('circle', 'rect', 'arrow'):
            group = 'shapes'
        if group not in THICKNESS_LEVELS:
            group = 'pencil'
        levels = THICKNESS_LEVELS[group]
        stroke_px = levels.get(self._preview_thickness, levels['normal'])
        ratio = (stroke_px - min(levels.values())) / (max(levels.values()) - min(levels.values()))
        inner_r = max(1.0, gauge_r - 3.0)
        preview_width = 1.0 + ratio * (inner_r * 0.65 - 1.0)
        # Round caps must stay clear of the ring even at the largest width.
        half_length = max(0.0, inner_r - preview_width / 2.0) / math.sqrt(2.0)
        color = QColor(self._preview_color)
        if self._preview_tool == 'highlighter':
            color.setAlphaF(0.6)
        # Preserve visibility for a black stroke against the dark gauge.
        p.setPen(QPen(QColor("#D0D4DC"), preview_width + 1.5,
                      Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        start = QPointF(cx - half_length, cy + half_length)
        end = QPointF(cx + half_length, cy - half_length)
        p.drawLine(start, end)
        p.setPen(QPen(color, preview_width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(start, end)

        if not self._compact and self.width() >= 70:
            p.setPen(QColor(255, 255, 255))
            p.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
            # Three fixed visual slots: gauge (0–34), label (36–66), arrow.
            # The previous label began at x=24 while the gauge was centered at
            # x=43, so the red preview painted directly over “Normal”.
            r = self.rect().adjusted(36, 0, -16, 0)
            p.drawText(r, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self._current_label)

            p.setPen(QPen(QColor(255, 255, 255, 180), 1.2))
            arrow_x = self.width() - 10
            arrow_y = self.height() / 2
            p.drawLine(QPointF(arrow_x - 3, arrow_y - 1), QPointF(arrow_x, arrow_y + 2))
            p.drawLine(QPointF(arrow_x, arrow_y + 2), QPointF(arrow_x + 3, arrow_y - 1))

        p.end()

from PyQt6.QtWidgets import QWidgetAction, QHBoxLayout, QLabel, QRadioButton

class _RadioDot(QWidget):
    """Smooth antialiased circular selector dot."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(18, 18)
        self._checked = False
        self._hovered = False
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def setChecked(self, checked: bool):
        self._checked = bool(checked)
        self.update()

    def isChecked(self) -> bool:
        return self._checked

    def setHovered(self, hovered: bool):
        self._hovered = bool(hovered)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = QRectF(1.5, 1.5, 15.0, 15.0)

        if self._checked:
            # Outer circular accent ring & fill (#FF4055)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(QColor('#FF4055')))
            p.drawEllipse(rect)

            # Inner concentric solid white circular dot
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(QColor('#FFFFFF')))
            p.drawEllipse(QRectF(5.5, 5.5, 7.0, 7.0))
        else:
            # Unchecked: smooth circular ring with subtle dark fill
            border_color = QColor('#9CA3AF') if self._hovered else QColor('#4B5563')
            p.setPen(QPen(border_color, 1.8))
            p.setBrush(QBrush(QColor('#171B24')))
            p.drawEllipse(rect)

        p.end()


class _ThicknessRowWidget(QWidget):
    row_clicked = pyqtSignal(str)

    def __init__(self, key: str, tool_id: str, current_color: QColor, parent=None):
        super().__init__(parent)
        self.key = key
        self.tool_id = tool_id
        self.current_color = QColor(current_color)

        self.setStyleSheet("""
            QWidget {
                background: transparent;
                border-radius: 8px;
            }
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(12)

        # Custom antialiased circular radio indicator
        self.radio = _RadioDot(self)
        layout.addWidget(self.radio, 0, Qt.AlignmentFlag.AlignVCenter)

        # Map programmatic keys back to readable labels
        label_map = {'thin': 'Thin', 'normal': 'Normal', 'big': 'Big', 'huge': 'Huge'}
        lbl_text = label_map.get(key, key.capitalize())

        self.label = QLabel(lbl_text, self)
        self.label.setStyleSheet("""
            QLabel {
                color: #E2E8F0;
                font-size: 13px;
                font-weight: 500;
                font-family: 'Segoe UI Variable Display', 'Segoe UI', sans-serif;
                background: transparent;
            }
        """)
        self.label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(self.label, 0, Qt.AlignmentFlag.AlignVCenter)

        layout.addStretch()

        # Preview area sized for harmonious stroke presentation
        preview = QWidget(self)
        preview.setFixedSize(76, 32)

        def paintPreview(event):
            p = QPainter(preview)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)

            # Elegant proportional heights for the dropdown capsule preview
            display_heights = {'thin': 3.0, 'normal': 6.0, 'big': 12.0, 'huge': 20.0}
            pill_h = display_heights.get(key, 6.0)

            c = QColor(self.current_color)
            if tool_id == 'highlighter':
                c.setAlphaF(0.55)

            pill_w = float(preview.width()) - 16.0
            pill_x = 8.0
            pill_y = (float(preview.height()) - pill_h) / 2.0
            radius = pill_h / 2.0

            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(c))
            p.drawRoundedRect(QRectF(pill_x, pill_y, pill_w, pill_h), radius, radius)

            if tool_id == 'highlighter':
                p.setPen(QPen(QColor(255, 255, 255, 110), 1.0))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRoundedRect(QRectF(pill_x, pill_y, pill_w, pill_h), radius, radius)

            p.end()

        preview.paintEvent = paintPreview
        layout.addWidget(preview, 0, Qt.AlignmentFlag.AlignVCenter)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def enterEvent(self, event):
        self.setStyleSheet("""
            _ThicknessRowWidget {
                background: rgba(255, 255, 255, 0.08);
                border-radius: 8px;
            }
        """)
        self.radio.setHovered(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.setStyleSheet("""
            _ThicknessRowWidget {
                background: transparent;
                border-radius: 8px;
            }
        """)
        self.radio.setHovered(False)
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.radio.setChecked(True)
            self.row_clicked.emit(self.key)
        super().mouseReleaseEvent(event)

class _ThicknessPickerMenu(QMenu):
    thickness_selected = pyqtSignal(str)

    def __init__(self, tool_id: str, color: QColor, current_thickness: str, parent=None):
        super().__init__(parent)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setStyleSheet("""
            QMenu {
                background-color: #131722;
                border: 1px solid #2B3545;
                border-radius: 12px;
                padding: 6px;
            }
            QMenu::item { background: transparent; padding: 0px; }
        """)
        self._rows = []
        keys = ['thin', 'normal', 'big', 'huge']
        for key in keys:
            row = _ThicknessRowWidget(key, tool_id, color)
            if key == current_thickness:
                row.radio.setChecked(True)
            row.row_clicked.connect(self._on_row_clicked)
            action = QWidgetAction(self)
            action.setDefaultWidget(row)
            action.setData(key)
            self.addAction(action)
            self._rows.append(row)

    def _on_row_clicked(self, key):
        for row in self._rows:
            row.radio.setChecked(row.key == key)
        self.thickness_selected.emit(key)
        self.close()


# ─────────────────────────────────────────────────────────────────────────────
#  AnnotateWindow — Screenshot Editor (WWR: Image Editor)
# ─────────────────────────────────────────────────────────────────────────────

class AnnotateWindow(QWidget):
    """
    Full screenshot editor window. Opens when user clicks a screenshot
    notification or uses the sidebar annotate button.
    """

    closed = pyqtSignal()

    def __init__(self, image_path):
        super().__init__(None, Qt.WindowType.WindowCloseButtonHint
                         | Qt.WindowType.WindowMinMaxButtonsHint)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self._filepath = image_path if isinstance(image_path, str) else ""
        if isinstance(image_path, str) and image_path:
            title_name = os.path.basename(image_path)
        else:
            title_name = "Clipboard Image"
        self.setWindowTitle(f"WWR: Image Editor – {title_name}")
        self.setMinimumSize(700, 500)

        from distribution import application_icon_path
        icon_path = application_icon_path()
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        self._active_tool = 'pencil'
        self._active_color = QColor('#FF3B30')
        self._active_thickness = 'normal'
        self._tool_buttons: dict = {}
        self._color_dots: list = []
        self._is_dragging = False  # BUG-007/023: Initialize drag state
        self._drag_pos = None

        # Force valid point size to stop terminal spam
        self.setFont(QFont("Segoe UI", 10))

        self._build_ui()
        self._apply_theme()
        self._select_tool(None)
        self._select_color(QColor('#FF3B30'))

        # Size to 80% of screen
        sg = QApplication.primaryScreen().availableGeometry()
        w = int(sg.width() * 0.8)
        h = int(sg.height() * 0.8)
        self.resize(w, h)
        self.move(sg.center().x() - w // 2, sg.center().y() - h // 2)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Top Toolbar ──────────────────────────────────────────────────────
        toolbar = QWidget()
        toolbar.setObjectName("TopToolbar")
        toolbar.setFixedHeight(56)
        toolbar.setStyleSheet("#TopToolbar { background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #1D2330, stop:1 #10131A); border-bottom: 1px solid #343B48; }")
        
        tbar = QGridLayout(toolbar)
        tbar.setContentsMargins(16, 8, 16, 8)
        tbar.setColumnStretch(0, 1)
        tbar.setColumnStretch(1, 0)
        tbar.setColumnStretch(2, 1)

        # LEFT: Tools container
        left_w = QWidget()
        l_layout = QHBoxLayout(left_w)
        l_layout.setContentsMargins(0, 0, 0, 0)
        l_layout.setSpacing(4)
        l_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        tbar.addWidget(left_w, 0, 0)

        tools = [
            ('pencil', 'pencil.png', 'Pencil', '✏'),
            ('highlighter', 'highlighter.png', 'Highlighter', '🖍'),
            ('eraser', 'eraser.png', 'Eraser', '🧹'),
            ('text', 'text_tool.png', 'Text', 'T'),
            ('circle', 'shape_circle.png', 'Circle', '○'),
            ('rect', 'shape_rect.png', 'Rectangle', '□'),
            ('arrow', 'shape_arrow.png', 'Arrow', '↗'),
        ]
        for tool_id, icon, tip, fallback in tools:
            btn = _AnnotationToolBtn(icon, tip, fallback, size=34, icon_size=18, checkable=True)
            btn.clicked.connect(lambda checked, t=tool_id: self._select_tool(t))
            l_layout.addWidget(btn)
            self._tool_buttons[tool_id] = btn

        l_layout.addSpacing(4)
        sep_tools = QFrame()
        sep_tools.setFixedSize(1, 28)
        sep_tools.setStyleSheet("background: #4A4A4C;")
        l_layout.addWidget(sep_tools)
        l_layout.addSpacing(4)
        
        # The editor toolbar already has a tooltip and a four-choice picker.
        # Keep this control compact so its label cannot collide with adjacent
        # tools when the editor is at its minimum supported width.
        self.btn_thickness = _ThicknessButton(
            'Stroke Thickness', size=34, icon_size=18, compact=True
        )
        self.btn_thickness.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        l_layout.addWidget(self.btn_thickness)

        # CENTER: Colors container
        cent_w = QWidget()
        c_layout = QHBoxLayout(cent_w)
        c_layout.setContentsMargins(0, 0, 0, 0)
        c_layout.setSpacing(8)
        tbar.addWidget(cent_w, 0, 1, Qt.AlignmentFlag.AlignCenter)

        sep1 = QFrame()
        sep1.setFixedSize(1, 28)
        sep1.setStyleSheet("background: #4A4A4C;")
        c_layout.addWidget(sep1)

        for hex_color, name in ANNOTATION_COLORS:
            dot = _ColorDot(hex_color, 24)
            dot.color_picked.connect(self._select_color)
            dot.setToolTip(name)
            c_layout.addWidget(dot, 0, Qt.AlignmentFlag.AlignCenter)
            self._color_dots.append(dot)

        sep2 = QFrame()
        sep2.setFixedSize(1, 28)
        sep2.setStyleSheet("background: #4A4A4C;")
        c_layout.addWidget(sep2)

        # RIGHT: Undo / Redo / Clear
        right_w = QWidget()
        r_layout = QHBoxLayout(right_w)
        r_layout.setContentsMargins(0, 0, 0, 0)
        r_layout.setSpacing(4)
        r_layout.setAlignment(Qt.AlignmentFlag.AlignRight)
        tbar.addWidget(right_w, 0, 2)
        self._editor_toolbar = toolbar
        self._editor_top_layout = tbar
        self._editor_top_groups = (left_w, cent_w, right_w)

        self._btn_undo = _AnnotationToolBtn('undo.png', 'Undo (Ctrl+Z)', '↩', size=34, icon_size=18)
        self._btn_undo.clicked.connect(self._undo)
        r_layout.addWidget(self._btn_undo)

        self._btn_redo = _AnnotationToolBtn('redo.png', 'Redo (Ctrl+Y)', '↪', size=34, icon_size=18)
        self._btn_redo.clicked.connect(self._redo)
        r_layout.addWidget(self._btn_redo)

        btn_clear = _AnnotationToolBtn('clear_brush.png', 'Clear All', '🧹', size=34, icon_size=18)
        btn_clear.clicked.connect(self._clear)
        r_layout.addWidget(btn_clear)

        toolbar.setMinimumWidth(toolbar.sizeHint().width())
        top_scroll = QScrollArea()
        top_scroll.setWidget(toolbar)
        top_scroll.setWidgetResizable(True)
        top_scroll.setFrameShape(QFrame.Shape.NoFrame)
        top_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        top_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        top_scroll.setFixedHeight(72)
        self._editor_top_scroll = top_scroll
        root.addWidget(top_scroll)

        # ── Drawing Area ─────────────────────────────────────────────────────
        self._canvas = _DrawingArea(self._filepath)
        self._canvas.modified.connect(self._on_modified)
        self._canvas.tool_changed.connect(self._sync_active_tool)
        root.addWidget(self._canvas, 1)

        # ── Bottom Bar ───────────────────────────────────────────────────────
        bottom = QWidget()
        bottom.setObjectName("BottomBar")
        bottom.setFixedHeight(48)
        bottom.setStyleSheet("#BottomBar { background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #10131A, stop:1 #1D2330); border-top: 1px solid #343B48; }")
        bbar = QGridLayout(bottom)
        bbar.setContentsMargins(10, 6, 10, 6)
        bbar.setSpacing(4)

        # LEFT: Open in Default App
        btn_open = QPushButton("Open Default App")
        btn_open.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_open.setFixedHeight(32)
        btn_open.setStyleSheet("""
            QPushButton {
                background: #262628; color: rgba(255,255,255,0.8); border: 1px solid #3C3C3E;
                border-radius: 6px; font-size: 11px; padding: 0 12px; font-family: 'Segoe UI';
            }
            QPushButton:hover { background: #3A3A3C; }
        """)
        btn_open.setIcon(QIcon(_asset("open.png")))
        btn_open.setIconSize(QSize(20,20))
        btn_open.clicked.connect(self._open_default)
        bbar.addWidget(btn_open, 0, 0)
        self._btn_actual_pixels = QPushButton()
        self._btn_actual_pixels.setIcon(QIcon(_asset("actual_size.png")))
        self._btn_actual_pixels.setIconSize(QSize(24,24))
        self._btn_actual_pixels.setFixedSize(44, 32)
        self._btn_actual_pixels.setToolTip("View original screenshot pixels without fitting/resizing")
        self._btn_actual_pixels.setStyleSheet(btn_open.styleSheet() + " QPushButton { padding: 0; }")
        self._btn_actual_pixels.clicked.connect(self._canvas.view_actual_pixels)
        bbar.addWidget(self._btn_actual_pixels, 0, 1)
        self._btn_fit = QPushButton()
        self._btn_fit.setIcon(QIcon(_asset("fit_image.png")))
        self._btn_fit.setIconSize(QSize(22,22))
        self._btn_fit.setFixedSize(34, 32)
        self._btn_fit.setToolTip("Fit screenshot in the editor; the saved image stays full resolution")
        self._btn_fit.setStyleSheet(btn_open.styleSheet() + " QPushButton { padding: 0; }")
        self._btn_fit.clicked.connect(self._canvas.view_fit)
        bbar.addWidget(self._btn_fit, 0, 2)


        # CENTRE: Stacked (transform buttons | crop confirm bar)
        self._bottom_stack = QStackedWidget()
        self._bottom_stack.setFixedHeight(36)
        self._bottom_stack.setStyleSheet("background: transparent; border: none;")

        # PAGE 0 — normal transform buttons
        page_transforms = QWidget()
        page_transforms.setStyleSheet("background: transparent;")
        pt_layout = QHBoxLayout(page_transforms)
        pt_layout.setContentsMargins(0, 0, 0, 0)
        pt_layout.setSpacing(4)
        pt_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        btn_crop = _AnnotationToolBtn('crop.png', 'Crop Image', '◩', size=32, icon_size=16)
        btn_crop.clicked.connect(lambda: self._select_tool('crop'))
        pt_layout.addWidget(btn_crop)
        self._btn_crop_activate = btn_crop

        btn_rot = _AnnotationToolBtn('rotate.png', 'Rotate 90°', '↻', size=32, icon_size=16)
        btn_rot.clicked.connect(self._canvas.rotate_90)
        pt_layout.addWidget(btn_rot)

        btn_fh = _AnnotationToolBtn('flip_h.png', 'Flip Horizontal', '↔', size=32, icon_size=16)
        btn_fh.clicked.connect(self._canvas.flip_horizontal)
        pt_layout.addWidget(btn_fh)

        btn_fv = _AnnotationToolBtn('flip_v.png', 'Flip Vertical', '↕', size=32, icon_size=16)
        btn_fv.clicked.connect(self._canvas.flip_vertical)
        pt_layout.addWidget(btn_fv)

        self._bottom_stack.addWidget(page_transforms)  # index 0

        # PAGE 1 — crop confirmation bar
        page_crop = QWidget()
        page_crop.setStyleSheet("background: transparent;")
        pc_layout = QHBoxLayout(page_crop)
        pc_layout.setContentsMargins(0, 0, 0, 0)
        pc_layout.setSpacing(8)
        pc_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        lbl_crop = QLabel("✂ Crop Mode")
        lbl_crop.setStyleSheet("color: rgba(255,255,255,0.5); font-size: 11px; font-family: 'Segoe UI';")
        pc_layout.addWidget(lbl_crop)

        btn_crop_ok = QPushButton("Apply (Enter)")
        btn_crop_ok.setIcon(QIcon(_asset("apply.png")))
        btn_crop_ok.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_crop_ok.setFixedHeight(30)
        btn_crop_ok.setStyleSheet("""
            QPushButton {
                background: #16A34A; color: #FFFFFF; border: none;
                border-radius: 5px; font-size: 11px; font-weight: 600;
                padding: 0 14px; font-family: 'Segoe UI';
            }
            QPushButton:hover { background: #22C55E; }
        """)
        btn_crop_ok.clicked.connect(self._canvas.commit_crop)
        pc_layout.addWidget(btn_crop_ok)

        btn_crop_cancel = QPushButton("Cancel (Esc)")
        btn_crop_cancel.setIcon(QIcon(_asset("close.png")))
        btn_crop_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_crop_cancel.setFixedHeight(30)
        btn_crop_cancel.setStyleSheet("""
            QPushButton {
                background: #3A3A3C; color: rgba(255,255,255,0.85); border: 1px solid #555;
                border-radius: 5px; font-size: 11px; padding: 0 12px; font-family: 'Segoe UI';
            }
            QPushButton:hover { background: #4A4A4C; }
        """)
        btn_crop_cancel.clicked.connect(self._cancel_crop)
        pc_layout.addWidget(btn_crop_cancel)

        self._bottom_stack.addWidget(page_crop)  # index 1

        bbar.addWidget(self._bottom_stack, 0, 3)


        # RIGHT: Copy + Save
        btn_copy = _AnnotationToolBtn('copyicon.png', 'Copy to Clipboard', '⎘', size=32, icon_size=18)
        btn_copy.setStyleSheet(btn_copy.styleSheet() + " QToolButton { color: white; }")
        btn_copy.clicked.connect(self._copy_clipboard)
        self._btn_copy = btn_copy
        bbar.addWidget(btn_copy, 0, 4)

        # No separate feedback label; we use the buttons themselves

        self._btn_save = QPushButton("Save")
        self._btn_save.setIcon(QIcon(_asset("save.png")))
        self._btn_save.setIconSize(QSize(20,20))
        self._btn_save.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_save.setFixedHeight(32)
        self._save_default_style = """
            QPushButton {
                background: #16A34A; color: #FFFFFF; border: none;
                border-radius: 6px; font-size: 11px; font-weight: 600;
                padding: 0 18px; font-family: 'Segoe UI';
            }
            QPushButton:hover { background: #15803D; }
        """
        self._btn_save.setStyleSheet(self._save_default_style)
        self._btn_save.clicked.connect(self._save)
        bbar.addWidget(self._btn_save, 0, 5)

        # Save As button
        self._btn_save_as = QPushButton("Save As")
        self._btn_save_as.setIcon(QIcon(_asset("save_as.png")))
        self._btn_save_as.setIconSize(QSize(20,20))
        self._btn_save_as.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_save_as.setFixedHeight(32)
        self._btn_save_as.setStyleSheet("""
            QPushButton {
                background: #3A3A3C; color: rgba(255,255,255,0.85); border: 1px solid #555;
                border-radius: 6px; font-size: 11px; font-weight: 600;
                padding: 0 14px; font-family: 'Segoe UI';
            }
            QPushButton:hover { background: #4A4A4C; }
        """)
        self._btn_save_as.clicked.connect(self._save_as)
        bbar.addWidget(self._btn_save_as, 0, 6)

        bottom.setMinimumWidth(bottom.sizeHint().width())
        bottom_scroll = QScrollArea()
        bottom_scroll.setWidget(bottom)
        bottom_scroll.setWidgetResizable(True)
        bottom_scroll.setFrameShape(QFrame.Shape.NoFrame)
        bottom_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        bottom_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        bottom_scroll.setFixedHeight(64)
        root.addWidget(bottom_scroll)
        self._editor_bottom_scroll = bottom_scroll
        self._editor_bottom = bottom
        self._editor_bottom_layout = bbar
        self._editor_bottom_widgets = (btn_open, self._btn_actual_pixels, self._btn_fit,
                                       self._bottom_stack, btn_copy, self._btn_save, self._btn_save_as)
        self._resize_editor_controls()

    def _resize_editor_controls(self):
        if not hasattr(self, '_editor_bottom_widgets'):
            return
        compact = False  # Keep tool/action groups on a single row at every window size.
        if hasattr(self, '_editor_top_scroll'):
            need_scroll = self._editor_toolbar.minimumWidth() > self.width()
            self._editor_top_scroll.setFixedHeight(72 if need_scroll else 56)
        if hasattr(self, '_editor_bottom_scroll'):
            need_scroll = self._editor_bottom.minimumWidth() > self.width()
            self._editor_bottom_scroll.setFixedHeight(64 if need_scroll else 48)
        top = self._editor_top_layout
        left, colors, right = self._editor_top_groups
        for widget in (left, colors, right):
            top.removeWidget(widget)
        for column in range(3):
            top.setColumnStretch(column, 0)
        if compact:
            top.addWidget(left, 0, 0, 1, 3)
            top.addWidget(colors, 1, 0, 1, 2, Qt.AlignmentFlag.AlignLeft)
            top.addWidget(right, 1, 2, Qt.AlignmentFlag.AlignRight)
            self._editor_toolbar.setFixedHeight(96)
        else:
            top.addWidget(left, 0, 0)
            top.addWidget(colors, 0, 1, Qt.AlignmentFlag.AlignCenter)
            top.addWidget(right, 0, 2)
            top.setColumnStretch(0, 1)
            top.setColumnStretch(2, 1)
            self._editor_toolbar.setFixedHeight(56)
        bottom = self._editor_bottom_layout
        for widget in self._editor_bottom_widgets:
            bottom.removeWidget(widget)
        for column in range(7):
            bottom.setColumnStretch(column, 0)
        for index, widget in enumerate(self._editor_bottom_widgets):
            if compact and index == 3:
                bottom.addWidget(widget, 1, 0, 1, 7)
            else:
                bottom.addWidget(widget, 0, index)
        bottom.setColumnStretch(3, 1)
        self._editor_bottom.setFixedHeight(88 if compact else 48)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._resize_editor_controls()

    def _select_tool(self, tool_id: str):
        self._active_tool = tool_id
        if hasattr(self, 'btn_thickness'):
            # Only recreate menu if tool or color actually changed (Improvement 12)
            cache_key = (tool_id, self._active_color.name() if isinstance(self._active_color, QColor) else str(self._active_color), self._active_thickness)
            if getattr(self, '_thickness_cache_key', None) != cache_key:
                menu = _ThicknessPickerMenu(tool_id, self._active_color, self._active_thickness, self)
                menu.thickness_selected.connect(self._select_thickness)
                self.btn_thickness.setMenu(menu)
                self._thickness_cache_key = cache_key
            
            # Update button preview label and stroke preview
            self.btn_thickness.set_thickness_label(self._active_thickness)
            self.btn_thickness.set_preview(self._active_tool, self._active_color)
            
        self._canvas.set_tool(tool_id)
        self._sync_active_tool(tool_id)
        self._update_undo_redo_state()

    def _select_thickness(self, thickness_key: str):
        self._active_thickness = thickness_key
        # Refresh the menu to show the selected radio button
        self._select_tool(self._active_tool)
        self._canvas.set_thickness(thickness_key)

    def _cancel_crop(self):
        """Cancel crop mode and return to pencil."""
        self._canvas._crop_rect = None
        self._canvas._crop_drag = None
        self._canvas.update()
        self._select_tool('pencil')

    def _sync_active_tool(self, tool_id: str):
        self._active_tool = tool_id
        is_crop = (tool_id == 'crop')

        # Swap bottom bar page
        self._bottom_stack.setCurrentIndex(1 if is_crop else 0)

        # Grey out / enable top toolbar tools and action buttons
        for tid, btn in self._tool_buttons.items():
            if is_crop:
                btn.setChecked(False)
                btn.setEnabled(False)
                btn.setStyleSheet(btn.styleSheet() + "QToolButton { opacity: 0.3; }")
            else:
                btn.setEnabled(True)
                btn.setChecked(tid == tool_id)
                # Re-apply normal style
                btn._apply_style()
                if tid == tool_id:
                    btn.setChecked(True)

        # Dim color dots while cropping
        for dot in self._color_dots:
            dot.setEnabled(not is_crop)
            dot.setStyleSheet("" if not is_crop else "QPushButton { opacity: 0.3; }")

        # Disable thickness button while cropping
        if hasattr(self, 'btn_thickness'):
            self.btn_thickness.setEnabled(not is_crop)

    def _select_color(self, color: QColor):
        self._active_color = color
        self._canvas.set_color(color)
        for dot in self._color_dots:
            dot.set_selected(dot._qcolor == color)
        # Update thickness menu color
        if hasattr(self, 'btn_thickness'):
            self._select_tool(self._active_tool)

    def _undo(self):
        self._canvas.undo()
        self._update_undo_redo_state()

    def _redo(self):
        self._canvas.redo()
        self._update_undo_redo_state()

    def _update_undo_redo_state(self):
        """Grey out Undo/Redo buttons when their stacks are empty."""
        has_undo = bool(self._canvas._items)
        has_redo = bool(self._canvas._redo_stack)
        if hasattr(self, '_btn_undo'):
            self._btn_undo.setEnabled(has_undo)
            self._btn_undo.setStyleSheet(
                self._btn_undo.styleSheet() + ('' if has_undo else ' QToolButton { opacity: 0.3; }')
            )
        if hasattr(self, '_btn_redo'):
            self._btn_redo.setEnabled(has_redo)
            self._btn_redo.setStyleSheet(
                self._btn_redo.styleSheet() + ('' if has_redo else ' QToolButton { opacity: 0.3; }')
            )

    def _clear(self):
        self._canvas.clear_all()

    def _on_modified(self):
        has = self._canvas.has_unsaved()
        title_base = f"WWRecorder: Annotate – {os.path.basename(self._filepath)}"
        self.setWindowTitle(f"{'● ' if has else ''}{title_base}")
        self._update_undo_redo_state()

    def _open_default(self):
        if isinstance(self._filepath, str) and self._filepath and os.path.isfile(self._filepath):
            os.startfile(self._filepath)

    def _copy_clipboard(self):
        img = self._canvas.get_composed_image()
        mime = QMimeData()
        mime.setImageData(img)
        # Only set file URL if no unsaved changes, otherwise pasting into some apps
        # will use the original unannotated file from disk instead of the image data.
        if isinstance(self._filepath, str) and self._filepath and os.path.isfile(self._filepath) and not self._canvas.has_unsaved():
            from PyQt6.QtCore import QUrl
            mime.setUrls([QUrl.fromLocalFile(self._filepath)])
        QApplication.clipboard().setMimeData(mime)
        self._btn_copy.setIcon(QIcon(_asset('apply.png')))
        self._btn_copy.setText("")
        QTimer.singleShot(1500, self._restore_copy_btn)
    def _restore_copy_btn(self):
        try:
            self._btn_copy.setText("")
            icon_path = _asset('copyicon.png')
            if os.path.isfile(icon_path):
                self._btn_copy.setIcon(QIcon(icon_path))
            else:
                self._btn_copy.setText("⎘")
        except RuntimeError:
            pass

    def _save(self):
        ok = self._canvas.save_image()
        if ok:
            self._on_modified()
            # Brief green flash on save button for confirmation
            self._btn_save.setText("Saved!")
            self._btn_save.setStyleSheet("""
                QPushButton {
                    background: #16A34A; color: #FFFFFF; border: none;
                    border-radius: 6px; font-size: 11px; font-weight: 600;
                    padding: 0 18px; font-family: 'Segoe UI';
                }
            """)
            QTimer.singleShot(1500, self._restore_save_btn)

    def _restore_save_btn(self):
        try:
            self._btn_save.setText("Save")
            self._btn_save.setStyleSheet(self._save_default_style)
        except RuntimeError:
            pass

    def _save_as(self):
        """Save annotated image to a new file chosen by the user."""
        fp = self._filepath if isinstance(self._filepath, str) and self._filepath else "screenshot.png"
        ext = os.path.splitext(fp)[1] or '.png'
        default_name = os.path.splitext(os.path.basename(fp))[0] + '_annotated' + ext
        default_dir = os.path.dirname(fp) if os.path.dirname(fp) else os.path.expanduser("~")
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Annotated Image As",
            os.path.join(default_dir, default_name),
            "PNG Image (*.png);;JPEG Image (*.jpg *.jpeg);;All Files (*)",
        )
        if path:
            img = self._canvas.get_composed_image()
            fmt = 'JPEG' if path.lower().endswith(('.jpg', '.jpeg')) else 'PNG'
            if os.path.normcase(os.path.abspath(path)) == os.path.normcase(os.path.abspath(fp)):
                ok = self._canvas.save_image()
            else:
                ok = _atomic_save_image(img, path, fmt)
            if ok:
                # We could provide dynamic feedback on the Save As button if desired
                # For now, just silently succeed, or flash the button green similarly:
                self._btn_save_as.setStyleSheet("""
                    QPushButton {
                        background: #16A34A; color: #FFFFFF; border: none;
                        border-radius: 6px; font-size: 11px; font-weight: 600;
                        padding: 0 14px; font-family: 'Segoe UI';
                    }
                """)
                self._btn_save_as.setText("Saved!")
                QTimer.singleShot(1500, self._restore_save_as_btn)
            else:
                QMessageBox.warning(self, "Could not save image",
                    "The image could not be saved. Your existing file is unchanged; the edits are still open here. Try another folder.")

    def _restore_save_as_btn(self):
        try:
            self._btn_save_as.setText("Save As")
            self._btn_save_as.setStyleSheet("""
                QPushButton {
                    background: #3A3A3C; color: rgba(255,255,255,0.85); border: 1px solid #555;
                    border-radius: 6px; font-size: 11px; font-weight: 600;
                    padding: 0 14px; font-family: 'Segoe UI';
                }
                QPushButton:hover { background: #4A4A4C; }
            """)
        except RuntimeError:
            pass

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            if hasattr(self, '_canvas'):
                try:
                    self._canvas._on_esc_pressed()
                except RuntimeError:
                    pass
                event.accept()
                return
        super().keyPressEvent(event)

    def closeEvent(self, event):
        if self._canvas.has_unsaved():
            msg = QMessageBox(self)
            msg.setWindowTitle("Unsaved Changes")
            msg.setText("You have unsaved annotations.")
            msg.setInformativeText("Do you want to save before closing?")
            msg.setStandardButtons(
                QMessageBox.StandardButton.Save
                | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel
            )
            msg.setDefaultButton(QMessageBox.StandardButton.Save)
            reply = msg.exec()
            if reply == QMessageBox.StandardButton.Save:
                if not self._canvas.save_image():
                    QMessageBox.critical(
                        self, "Save Failed",
                        "The annotated image could not be saved. The editor will remain open."
                    )
                    event.ignore()
                    return
            elif reply == QMessageBox.StandardButton.Cancel:
                event.ignore()
                return
        self.closed.emit()
        event.accept()

    def _apply_theme(self):
        self.setStyleSheet("""
            AnnotateWindow {
                background: #090B10;
                color: #FFFFFF;
                font-family: 'Segoe UI';
            }
            QToolTip {
                color: #FFFFFF; background: #202024; border: 1px solid #4A4A52;
                border-radius: 4px; padding: 5px 8px;
            }
        """)

# ─────────────────────────────────────────────────────────────────────────────
#  AnnotationPill
# ─────────────────────────────────────────────────────────────────────────────

class AnnotationPill(QWidget):
    """Floating global toolbar for live annotation outside of the recording pill."""
    tool_changed = pyqtSignal(str)
    color_changed = pyqtSignal(str)
    thickness_changed = pyqtSignal(str)
    undo_requested = pyqtSignal()
    redo_requested = pyqtSignal()
    clear_requested = pyqtSignal()
    pause_toggled = pyqtSignal(bool)
    close_requested = pyqtSignal()

    def __init__(self, parent=None):
        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        super().__init__(parent, flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_AlwaysShowToolTips, True)

        # Force valid point size to stop terminal spam
        self.setFont(QFont("Segoe UI", 10))
        
        self._active_tool = 'pencil'
        self._active_color = '#FF3B30'
        self._active_thickness = 'normal'
        
        self._drag_pos = None
        self._is_dragging = False
        self._pinned = True
        self._orientation = 'vertical'
        self._dock_edge = 'left'
        self._separators = []
        self._group_specs = []
        self._drag_surfaces = set()
        self._pill = None
        self._pill_layout = None
        
        self._build_ui()
        
        self._topmost_timer = QTimer(self)
        self._topmost_timer.timeout.connect(self._enforce_topmost)
        self._topmost_timer.start(2000)  # PERF-007: Relaxed from 1000ms

    def _has_active_popup(self) -> bool:
        return (
            QApplication.activePopupWidget() is not None
            or QToolTip.isVisible()
        )

    def _enforce_topmost(self):
        try:
            # Do not raise the bar over its own thickness menu, active popups,
            # or when a tooltip is visible or when the cursor is hovering the toolbar.
            if self._has_active_popup():
                return
            if self.isVisible() and not self.underMouse() and not (self._pill and self._pill.underMouse()):
                if getattr(sys, 'platform', '') == 'win32' and _user32:
                    HWND_TOPMOST = -1
                    SWP_NOSIZE = 0x0001
                    SWP_NOMOVE = 0x0002
                    SWP_NOACTIVATE = 0x0010
                    try:
                        _user32.SetWindowPos(int(self.winId()), HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
                    except Exception:
                        pass
                self.raise_()
        except RuntimeError:
            pass  # Widget was already deleted by Qt

    def closeEvent(self, event):
        self._topmost_timer.stop()
        previous = getattr(self, '_watched_screen', None)
        if previous is not None:
            try: previous.availableGeometryChanged.disconnect(self._resize_for_screen)
            except (TypeError, RuntimeError): pass
        handle = self.windowHandle()
        if handle is not None and getattr(self, '_screen_watch_connected', False):
            try: handle.screenChanged.disconnect(self._watch_toolbar_screen)
            except (TypeError, RuntimeError): pass
        self._watched_screen = None
        self._screen_watch_connected = False
        super().closeEvent(event)
        
    def _make_separator(self) -> QFrame:
        sep = QFrame()
        sep.setStyleSheet("background: rgba(255, 255, 255, 0.10); border-radius: 1px;")
        self._separators.append(sep)
        self._update_separator_size(sep)
        return sep

    def _update_separator_size(self, sep: QFrame):
        if self._orientation == 'horizontal':
            sep.setFixedSize(1, self._separator_length)
        else:
            sep.setFixedSize(self._separator_length, 1)

    def _apply_orientation(self, orientation: str, available_geometry=None):
        if orientation not in ('vertical', 'horizontal') or self._pill_layout is None:
            return
        self._orientation = orientation
        sg = available_geometry or self._screen_geometry()
        available_length = sg.width() if orientation == 'horizontal' else sg.height()
        self._apply_control_density(available_length)
        direction = (
            QBoxLayout.Direction.LeftToRight
            if orientation == 'horizontal'
            else QBoxLayout.Direction.TopToBottom
        )
        self._pill_layout.setDirection(direction)
        for sep in self._separators:
            self._update_separator_size(sep)
        self.btn_thickness.set_compact(True)
        self._pill_layout.invalidate()
        self._pill_layout.activate()
        if self._pill:
            self._pill.adjustSize()
        self.layout().activate()
        hint = self.sizeHint()
        self.setFixedSize(hint)

    def _apply_control_density(self, available_length: int) -> None:
        """Use comfortable controls normally and a laptop-safe density only when needed."""
        # A single strip occupies at most roughly 90% of its screen edge. Scale both
        # dimensions continuously, with comfortable bounds for logical pixels.
        control_size = max(22, min(40, round(available_length * 0.04)))
        icon_size = max(16, round(control_size * 0.72))
        color_size = max(18, round(control_size * 0.86))
        self._separator_length = max(18, control_size - 5)

        if hasattr(self, '_btn_pin'):
            self._btn_pin.setFixedSize(control_size, control_size)
        if hasattr(self, 'btn_thickness'):
            self.btn_thickness.setFixedSize(control_size, control_size)
            self.btn_thickness.setIconSize(QSize(icon_size, icon_size))
        for btn in getattr(self, '_sized_buttons', []):
            btn.setFixedSize(control_size, control_size)
            btn.setIconSize(QSize(icon_size, icon_size))
        for dot in getattr(self, '_color_dots', []):
            dot.setFixedSize(color_size, color_size)
        for sep in self._separators:
            self._update_separator_size(sep)

    def _screen_geometry(self, global_pos: Optional[QPoint] = None):
        screen = QApplication.screenAt(global_pos or self.frameGeometry().center())
        if screen is None:
            screen = QApplication.primaryScreen()
        return screen.availableGeometry()

    def _nearest_edge(self, global_pos: QPoint, sg: Optional[QRect] = None) -> str:
        sg = sg or self._screen_geometry(global_pos)
        # True pixel distance makes snapping predictable. Stable ordering
        # deliberately gives side edges priority on an exact tie, producing a
        # vertical toolbar as requested.
        edges = [
            (abs(global_pos.x() - sg.left()), 0, 'left'),
            (abs(sg.right() - global_pos.x()), 1, 'right'),
            (abs(global_pos.y() - sg.top()), 2, 'top'),
            (abs(sg.bottom() - global_pos.y()), 3, 'bottom'),
        ]
        return min(edges, key=lambda item: (item[0], item[1]))[2]

    def _dock_to_edge(self, edge: str, sg: Optional[QRect] = None):
        hint = self.sizeHint()
        self.setFixedSize(hint)
        sg = sg or self._screen_geometry()
        margin = 4  # Minimal margin so toolbar docks tightly against screen edges without floating gaps
        w, h = hint.width(), hint.height()
        x, y = self.x(), self.y()

        if edge == 'top':
            x = max(sg.left() + margin, min(x, sg.right() - w + 1 - margin))
            y = sg.top() + margin
        elif edge == 'bottom':
            x = max(sg.left() + margin, min(x, sg.right() - w + 1 - margin))
            y = sg.bottom() - h + 1 - margin
        elif edge == 'left':
            x = sg.left() + margin
            y = max(sg.top() + margin, min(y, sg.bottom() - h + 1 - margin))
        else: # right
            x = sg.right() - w + 1 - margin
            y = max(sg.top() + margin, min(y, sg.bottom() - h + 1 - margin))

        self._dock_edge = edge
        self.setGeometry(int(x), int(y), int(w), int(h))

    def _snap_after_drag(self, cursor_tip: Optional[QPoint] = None):
        snap_point = cursor_tip or QCursor.pos()
        sg = self._screen_geometry(snap_point)
        edge = self._nearest_edge(snap_point, sg)
        new_orientation = 'horizontal' if edge in ('top', 'bottom') else 'vertical'
        self._apply_orientation(new_orientation, sg)
        self._dock_to_edge(edge, sg)

    def _build_ui(self):
        # Adaptive density: 32px/23px on normal screens, 28px/21px on compact
        # (<680px available edge). Keeps the original single-strip layout.
        control_size = 32
        icon_size = 23
        color_size = 28
        gap = 1
        self._separator_length = 27
        self._sized_buttons = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        self._pill = QWidget(self)
        self._pill.setObjectName('PillContainer')
        self._pill.setAttribute(Qt.WidgetAttribute.WA_AlwaysShowToolTips, True)
        self._pill.setStyleSheet("""
            * { font-family: 'Segoe UI'; font-size: 10pt; }
            QWidget#PillContainer {
                background: #11141D;
                border: 1px solid #283142;
                border-radius: 12px;
            }
            QToolTip {
                color: #FFFFFF; background: #181D26;
                border: 1px solid #3B475B; padding: 4px 8px;
                border-radius: 4px;
            }
        """)
        self._pill_layout = QBoxLayout(QBoxLayout.Direction.TopToBottom, self._pill)
        layout = self._pill_layout
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(gap)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        def add_separator():
            layout.addSpacing(gap)
            layout.addWidget(self._make_separator(), 0, Qt.AlignmentFlag.AlignCenter)
            layout.addSpacing(gap)

        self._btn_pin = _PinToolButton(self._pill, size=control_size)
        self._btn_pin.setToolTip("Drag to move toolbar")
        self._btn_pin.toolbar_drag.connect(self._on_toolbar_drag)
        layout.addWidget(self._btn_pin, 0, Qt.AlignmentFlag.AlignCenter)

        self.btn_thickness = _ThicknessButton(
            'Stroke Thickness', size=control_size, icon_size=icon_size, compact=True
        )
        self.btn_thickness.setToolTip("Stroke Thickness")
        self.btn_thickness.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.btn_thickness.pressed.connect(self._on_thickness_pressed)
        self.btn_thickness.set_preview(self._active_tool, QColor(self._active_color))
        layout.addWidget(self.btn_thickness, 0, Qt.AlignmentFlag.AlignCenter)
        add_separator()

        tools = [
            ('pencil', 'pencil.png', 'Pencil — draw freehand', '✏'),
            ('highlighter', 'highlighter.png', 'Highlighter — semi-transparent mark', '🖍'),
            ('eraser', 'eraser.png', 'Eraser — remove annotations', '🧹'),
            ('text', 'text_tool.png', 'Text — type notes on screen', 'T'),
            ('circle', 'shape_circle.png', 'Circle — draw ellipse / circle', '○'),
            ('rect', 'shape_rect.png', 'Rectangle — draw box', '□'),
            ('arrow', 'shape_arrow.png', 'Arrow — point & indicate', '↗'),
            ('laser', '', 'Laser pointer — transient highlight trail', ''),
        ]
        self._tool_btns = {}
        for tool_id, icon, tip, fallback in tools:
            btn = _AnnotationToolBtn(icon, tip, fallback, size=control_size,
                                     icon_size=icon_size, checkable=True)
            if tool_id == 'laser':
                btn.setIcon(QIcon(_laser_dot_pixmap(icon_size, QColor(self._active_color))))
            btn.clicked.connect(lambda checked, t=tool_id: self._select_tool(t))
            layout.addWidget(btn, 0, Qt.AlignmentFlag.AlignCenter)
            self._tool_btns[tool_id] = btn
            self._sized_buttons.append(btn)
        add_separator()

        self._color_dots = []
        for hex_color, name in ANNOTATION_COLORS:
            dot = _ColorDot(hex_color, color_size)
            dot.color_picked.connect(self._select_color)
            dot.setToolTip(f"{name} color")
            dot.setAccessibleName(f'{name} annotation color')
            layout.addWidget(dot, 0, Qt.AlignmentFlag.AlignCenter)
            self._color_dots.append(dot)
        add_separator()

        self._btn_undo = _AnnotationToolBtn(
            'undo.png', 'Undo (Ctrl+Z)', '↩', size=control_size, icon_size=icon_size)
        self._btn_undo.clicked.connect(self.undo_requested.emit)
        self._btn_undo.set_available(False)
        self._sized_buttons.append(self._btn_undo)
        layout.addWidget(self._btn_undo, 0, Qt.AlignmentFlag.AlignCenter)

        self._btn_redo = _AnnotationToolBtn(
            'redo.png', 'Redo (Ctrl+Y)', '↻', size=control_size, icon_size=icon_size)
        self._btn_redo.clicked.connect(self.redo_requested.emit)
        self._btn_redo.set_available(False)
        self._sized_buttons.append(self._btn_redo)
        layout.addWidget(self._btn_redo, 0, Qt.AlignmentFlag.AlignCenter)

        self._btn_clear = _AnnotationToolBtn(
            'clear_brush.png', 'Clear all annotations', '🧹', size=control_size, icon_size=icon_size)
        self._btn_clear.clicked.connect(self.clear_requested.emit)
        self._sized_buttons.append(self._btn_clear)
        layout.addWidget(self._btn_clear, 0, Qt.AlignmentFlag.AlignCenter)

        self._btn_pause = _AnnotationToolBtn(
            'pause.png', 'Pause annotation — interact with the screen (Space)', 'Ⅱ',
            size=control_size, icon_size=icon_size, checkable=True)
        self._btn_pause.toggled.connect(self._on_pause_toggled)
        self._sized_buttons.append(self._btn_pause)
        layout.addWidget(self._btn_pause, 0, Qt.AlignmentFlag.AlignCenter)
        add_separator()

        self._btn_close = _AnnotationToolBtn(
            'close.png', 'Exit Annotator (Esc)', '✕', size=control_size, icon_size=icon_size)
        self._btn_close.setStyleSheet("""
            QToolButton { background: transparent; border: none; border-radius: 7px; color: rgba(255,255,255,0.75); }
            QToolButton:hover { background: #DC2626; color: white; }
        """)
        self._btn_close.clicked.connect(self.close_requested.emit)
        layout.addWidget(self._btn_close, 0, Qt.AlignmentFlag.AlignCenter)

        root.addWidget(self._pill)

        self._tool_btns[self._active_tool].setChecked(True)
        self._color_dots[0].set_selected(True)

        self._shortcut_undo = QShortcut(QKeySequence("Ctrl+Z"), self, self.undo_requested.emit)
        self._shortcut_redo = QShortcut(QKeySequence("Ctrl+Y"), self, self.redo_requested.emit)
        self._shortcut_redo_shift = QShortcut(QKeySequence("Ctrl+Shift+Z"), self, self.redo_requested.emit)
        self._shortcut_pause = QShortcut(QKeySequence(Qt.Key.Key_Space), self, lambda: self._btn_pause.toggle())
        self._shortcut_close = QShortcut(QKeySequence("Esc"), self, self.close_requested.emit)

        self._pill.installEventFilter(self)
        self._drag_surfaces.add(self._pill)
        self._apply_orientation('vertical')

    def keyPressEvent(self, event):
        key = event.key()
        mods = event.modifiers()
        ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
        shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)

        if ctrl and not shift and key == Qt.Key.Key_Z:
            self.undo_requested.emit()
            event.accept()
            return
        elif (ctrl and key == Qt.Key.Key_Y) or (ctrl and shift and key == Qt.Key.Key_Z):
            self.redo_requested.emit()
            event.accept()
            return
        elif key == Qt.Key.Key_Space:
            self._btn_pause.toggle()
            event.accept()
            return
        elif key == Qt.Key.Key_Escape:
            self.close_requested.emit()
            event.accept()
            return

        super().keyPressEvent(event)

    def _on_pin_toggled(self, pinned: bool = False):
        pass

    def eventFilter(self, obj, event):
        if obj in self._drag_surfaces:
            et = event.type()
            if et == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                self._is_dragging = True
                return True
            if et == QEvent.Type.MouseMove and self._is_dragging and self._drag_pos is not None:
                self.move(event.globalPosition().toPoint() - self._drag_pos)
                return True
            if et == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
                if self._is_dragging:
                    self._is_dragging = False
                    self._drag_pos = None
                    self._snap_after_drag(event.globalPosition().toPoint())
                    return True
        return super().eventFilter(obj, event)

    def _on_toolbar_drag(self, event):
        if event.type() == QEvent.Type.MouseMove:
            if self._drag_pos is None:
                self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._is_dragging = True
            self.move(event.globalPosition().toPoint() - self._drag_pos)
        elif event.type() == QEvent.Type.MouseButtonRelease:
            self._is_dragging = False
            self._drag_pos = None
            self._snap_after_drag(event.globalPosition().toPoint())
        
    def _on_pause_toggled(self, checked: bool):
        if checked:
            self._btn_pause.setToolTip("Resume annotation (Space)")
            icon_path = _asset('play.png')
            if os.path.isfile(icon_path):
                self._btn_pause.setIcon(QIcon(icon_path))
            else:
                self._btn_pause.setText('▶')
        else:
            self._btn_pause.setToolTip("Pause annotation — interact with the screen (Space)")
            icon_path = _asset('pause.png')
            if os.path.isfile(icon_path):
                self._btn_pause.setIcon(QIcon(icon_path))
            else:
                self._btn_pause.setText('Ⅱ')
        self.pause_toggled.emit(checked)

    def update_undo_redo_state(self, has_undo: bool, has_redo: bool):
        if hasattr(self, '_btn_undo'):
            self._btn_undo.set_available(has_undo)
        if hasattr(self, '_btn_redo'):
            self._btn_redo.set_available(has_redo)

    def _select_tool(self, tool_id: str):
        self._active_tool = tool_id
        if hasattr(self, 'btn_thickness'):
            # Update button preview label and stroke preview
            self.btn_thickness.set_thickness_label(self._active_thickness)
            self.btn_thickness.set_preview(self._active_tool, QColor(self._active_color))

        for tid, btn in self._tool_btns.items():
            btn.setChecked(tid == tool_id)
        self.tool_changed.emit(tool_id)

    def _on_thickness_pressed(self):
        """Open thickness menu on the side with the most available space."""
        menu = _ThicknessPickerMenu(self._active_tool, QColor(self._active_color), self._active_thickness, self)
        menu.thickness_selected.connect(self._select_thickness)

        btn_global = self.btn_thickness.mapToGlobal(QPoint(0, 0))
        anchor = QRect(btn_global, self.btn_thickness.size())
        hint = menu.sizeHint().expandedTo(QSize(1, 160))
        menu.exec(_clamp_popup_position(anchor, hint, self._screen_geometry()))

    def _select_thickness(self, thickness_key: str):
        self._active_thickness = thickness_key
        # Update the visual preview on the button
        if hasattr(self, 'btn_thickness'):
            self.btn_thickness.set_thickness_label(self._active_thickness)
            self.btn_thickness.set_preview(self._active_tool, QColor(self._active_color))
        self.thickness_changed.emit(thickness_key)
        
    def _select_color(self, qcolor: QColor):
        hx = qcolor.name().upper()
        self._active_color = hx
        for dot in self._color_dots:
            dot.set_selected(dot._hex.upper() == hx)
        if hasattr(self, 'btn_thickness'):
            self.btn_thickness.set_preview(self._active_tool, QColor(self._active_color))
        laser_button = getattr(self, '_tool_btns', {}).get('laser')
        if laser_button is not None:
            laser_button.setIcon(QIcon(_laser_dot_pixmap(
                laser_button.iconSize().width(), QColor(self._active_color)
            )))
        self.color_changed.emit(hx)
        
    def _watch_toolbar_screen(self, screen):
        previous = getattr(self, '_watched_screen', None)
        if previous is screen: return
        if previous is not None:
            try: previous.availableGeometryChanged.disconnect(self._resize_for_screen)
            except (TypeError, RuntimeError): pass
        self._watched_screen = screen
        if screen is not None: screen.availableGeometryChanged.connect(self._resize_for_screen)
        self._resize_for_screen()

    def _resize_for_screen(self, *_):
        if getattr(self, '_screen_resize_pending', False): return
        self._screen_resize_pending = True
        QTimer.singleShot(0, self._apply_screen_resize)

    def _apply_screen_resize(self):
        self._screen_resize_pending = False
        if not self.isVisible(): return
        sg = self._screen_geometry()
        self._apply_orientation(self._orientation, sg)
        self._dock_to_edge(self._dock_edge, sg)

    def showEvent(self, event):
        super().showEvent(event)
        handle = self.windowHandle()
        if handle is not None and not getattr(self, '_screen_watch_connected', False):
            self._screen_watch_connected = True
            handle.screenChanged.connect(self._watch_toolbar_screen)
            self._watch_toolbar_screen(handle.screen())
        if not getattr(self, '_positioned', False):
            self._apply_orientation('vertical')
            sg = self._screen_geometry()
            hint = self.sizeHint()
            w = hint.width()
            h = hint.height()
            x = sg.left() + 18
            y = sg.center().y() - h // 2
            self.setFixedSize(w, h)
            self.move(int(x), int(y))
            self._dock_edge = 'left'
            self._positioned = True
