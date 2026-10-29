"""
ui_elements.py - WWRecorder UI Components

• SelectionOverlay  : Full-screen translucent region picker
• PillWidget        : Floating always-on-top recording controller
                      (invisible to capture via SetWindowDisplayAffinity)
• SettingsWindow    : Settings dialog
"""

import ctypes
import os
import sys
from typing import Optional

from PyQt6.QtWidgets import (
    QApplication, QDialog, QWidget, QLabel, QPushButton, QToolButton,
    QHBoxLayout, QVBoxLayout, QFileDialog, QLineEdit,
    QCheckBox, QGroupBox, QGraphicsDropShadowEffect,
    QSizePolicy, QToolTip, QMessageBox, QMenu, QWidgetAction,
)
from PyQt6.QtCore import (
    Qt, QRect, QRectF, QPoint, QPointF, QSize, QTimer, QThread,
    pyqtSignal, QPropertyAnimation, QEasingCurve,
)
from PyQt6.QtGui import (
    QPainter, QColor, QBrush, QPen, QFont, QFontMetrics,
    QPainterPath, QLinearGradient, QIcon, QCursor, QActionGroup,
    QPixmap, QImage, QRegion,
)


def _clamp_window_top_left(position: QPoint, size: QSize, available: QRect) -> QPoint:
    """Keep a resized floating window on its current screen without recentering it."""
    max_x = max(available.left(), available.right() - size.width() + 1)
    max_y = max(available.top(), available.bottom() - size.height() + 1)
    return QPoint(
        max(available.left(), min(position.x(), max_x)),
        max(available.top(), min(position.y(), max_y)),
    )

# ── Windows API constants ──────────────────────────────────────────────────────
WDA_EXCLUDEFROMCAPTURE = 0x00000011   # Invisible to all capture APIs
WDA_MONITOR = 0x00000001              # Fallback for older Windows 10 versions

_user32 = ctypes.windll.user32 if sys.platform == "win32" else None
if _user32:
    from ctypes import wintypes
    _user32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
    _user32.SetWindowDisplayAffinity.restype = wintypes.BOOL

def _exclude_from_capture(hwnd: int) -> None:
    """Mark this HWND so it is invisible to all screen-capture APIs."""
    if _user32:
        try:
            # Try WDA_EXCLUDEFROMCAPTURE first (Windows 10 2004+)
            res = _user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE)
            if not res:
                # Fallback to WDA_MONITOR
                _user32.SetWindowDisplayAffinity(hwnd, WDA_MONITOR)
        except Exception as exc:
            pass



# ─────────────────────────────────────────────────────────────────────────────
#  SelectionOverlay
# ─────────────────────────────────────────────────────────────────────────────

def _capture_outline_pen(color):
    """A visible thin cosmetic stroke with compact dashes at every DPI."""
    pen = QPen(color, 1.5, Qt.PenStyle.DashLine)
    pen.setCosmetic(True)
    pen.setDashPattern([3, 2])
    return pen


class SelectionOverlay(QWidget):
    selectionChanged = pyqtSignal(dict)
    
    def __init__(self, mode="record"):
        flags = (
            Qt.WindowType.Window
            | Qt.WindowType.FramelessWindowHint 
            | Qt.WindowType.WindowStaysOnTopHint
        )
        super().__init__(None, flags)

        self._mode = mode
        self.state = 'IDLE'
        self._origin = None
        self._current = None
        self.rect_obj = QRect()
        self._bg_pixmap = None
        self._cancel_emitted = False
        
        if self._mode == "screenshot":
            self.hint_text = "  ⊞  Click and drag to select screenshot area  -  Esc to cancel  "
            self.selection_color = QColor(255, 60, 70, 255)  # Opaque red
        else:
            self.hint_text = "  ⊞  Click and drag to select recording area  -  Esc to cancel  "
            self.selection_color = QColor(255, 60, 70, 255)  # Opaque red

        self.handle_size = 5
        self.hovered_handle = None

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFocus()
        
        # Determine logical desktop bounds
        bounds = QRect()
        for screen in QApplication.screens():
            bounds = bounds.united(screen.geometry())
        self.setGeometry(bounds)

        self._hint = QLabel(self.hint_text, self)
        self._hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hint.setStyleSheet("""
            QLabel {
                color: #FFFFFF;
                background: rgba(0,0,0,175);
                border-radius: 10px;
                font-family: 'Segoe UI', sans-serif;
                font-size: 13px;
                font-weight: 500;
                padding: 8px 20px;
            }
        """)
        self._hint.adjustSize()
        self._hint.move(bounds.width() // 2 - self._hint.width() // 2, 28)

    def set_background(self, pixmap: QPixmap):
        """Set a static background image (frozen screenshot)."""
        self._bg_pixmap = pixmap
        self.update()

    def showEvent(self, event):
        super().showEvent(event)
        # We use a small delay to ensure the window is mapped and ready before 
        # we shout at Windows to give us the focus. This is more robust than 
        # doing it immediately.
        QTimer.singleShot(100, self._force_focus)

    def _force_focus(self):
        """Low-level Windows API call plus Qt activation to reliably steal focus."""
        if sys.platform == "win32":
            try:
                import ctypes
                user32 = ctypes.windll.user32
                kernel32 = ctypes.windll.kernel32

                hwnd = int(self.winId())
                target_hwnd = user32.GetForegroundWindow()
                target_thread = user32.GetWindowThreadProcessId(target_hwnd, None)
                my_thread = kernel32.GetCurrentThreadId()

                if target_thread != my_thread and target_thread != 0:
                    user32.AttachThreadInput(my_thread, target_thread, True)
                    user32.BringWindowToTop(hwnd)
                    user32.ShowWindow(hwnd, 5) # SW_SHOW
                    user32.SetForegroundWindow(hwnd)
                    user32.SetFocus(hwnd)
                    user32.AttachThreadInput(my_thread, target_thread, False)
                else:
                    user32.BringWindowToTop(hwnd)
                    user32.ShowWindow(hwnd, 5)
                    user32.SetForegroundWindow(hwnd)
                    user32.SetFocus(hwnd)
            except Exception as e:
                print(f"Focus error: {e}")
        
        self.activateWindow()
        self.raise_()
        self.setFocus()
        self.grabKeyboard()

    def hideEvent(self, event):
        super().hideEvent(event)
        self.releaseKeyboard()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            # BUG-020: Hide before emitting so handler doesn't reference a closing widget
            self._cancel_emitted = True
            self.hide()
            self.selectionChanged.emit({})
            self.close()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        if not self._cancel_emitted and self.state != 'SELECTED':
            self._cancel_emitted = True
            self.selectionChanged.emit({})
        super().closeEvent(event)

    def _apply_selection_mask(self):
        if self._mode != "record" or not self.rect_obj.isValid(): return
        # Only the outline/handles receive input after selection. The interior
        # and surrounding desktop belong to the user's applications.
        outer = self.rect_obj.adjusted(-4, -4, 4, 4)
        inner = self.rect_obj.adjusted(5, 5, -5, -5)
        region = QRegion(outer).subtracted(QRegion(inner))
        for handle in self.get_handles().values(): region = region.united(QRegion(handle))
        self.setMask(region.intersected(QRegion(self.rect())))

    def get_handles(self):
        if self._mode == "screenshot" or not self.rect_obj.isValid():
            return {}
        hs = self.handle_size
        r = self.rect_obj
        return {
            'tl': QRect(r.left() - hs, r.top() - hs, hs*2, hs*2),
            't': QRect(r.center().x() - hs, r.top() - hs, hs*2, hs*2),
            'tr': QRect(r.right() - hs, r.top() - hs, hs*2, hs*2),
            'r': QRect(r.right() - hs, r.center().y() - hs, hs*2, hs*2),
            'br': QRect(r.right() - hs, r.bottom() - hs, hs*2, hs*2),
            'b': QRect(r.center().x() - hs, r.bottom() - hs, hs*2, hs*2),
            'bl': QRect(r.left() - hs, r.bottom() - hs, hs*2, hs*2),
            'l': QRect(r.left() - hs, r.center().y() - hs, hs*2, hs*2)
        }

    def mousePressEvent(self, event):
        self.setFocus()
        pos = event.position().toPoint()
        if event.button() == Qt.MouseButton.LeftButton:
            if self.state == 'IDLE':
                self.state = 'DRAWING'
                self._origin = pos
                self._current = pos
                self._hint.hide()
            elif self.state == 'SELECTED':
                if self._mode == "record" and self.rect_obj.adjusted(6, 6, -6, -6).contains(pos):
                    event.ignore()
                    return
                handles = self.get_handles()
                for h, hr in handles.items():
                    if hr.contains(pos):
                        self.state = 'RESIZING'
                        self.hovered_handle = h
                        self._origin = pos
                        return
                if self.rect_obj.contains(pos):
                    self.state = 'MOVING'
                    self._origin = pos
                else:
                    self.state = 'DRAWING'
                    self._origin = pos
                    self._current = pos
                    self.rect_obj = QRect()
            self.update()

    def mouseMoveEvent(self, event):
        if self.state in ('DRAWING', 'MOVING', 'RESIZING') and not (event.buttons() & Qt.MouseButton.LeftButton):
            # A popup/focus transition can swallow the release. Never continue
            # moving a capture region on ordinary pointer motion.
            self.state = 'SELECTED' if self.rect_obj.width() >= 32 and self.rect_obj.height() >= 32 else 'IDLE'
            if self.state == 'SELECTED':
                self._apply_selection_mask()
                self._emit_change()
            else:
                self.clearMask()
            return
        pos = event.position().toPoint()
        pos.setX(max(self.rect().left(), min(self.rect().right(), pos.x())))
        pos.setY(max(self.rect().top(), min(self.rect().bottom(), pos.y())))
        if self.state == 'DRAWING':
            self._current = pos
            self.rect_obj = QRect(self._origin, self._current).normalized()
            self.update()
        elif self.state == 'MOVING':
            dp = pos - self._origin
            self.rect_obj.translate(dp)
            if self.rect_obj.left() < self.rect().left():
                self.rect_obj.moveLeft(self.rect().left())
            if self.rect_obj.right() > self.rect().right():
                self.rect_obj.moveRight(self.rect().right())
            if self.rect_obj.top() < self.rect().top():
                self.rect_obj.moveTop(self.rect().top())
            if self.rect_obj.bottom() > self.rect().bottom():
                self.rect_obj.moveBottom(self.rect().bottom())
            self._origin = pos
            self._apply_selection_mask()
            self.update()
        elif self.state == 'RESIZING':
            dp = pos - self._origin
            r = self.rect_obj
            h = self.hovered_handle
            if 't' in h: r.setTop(r.top() + dp.y())
            if 'b' in h: r.setBottom(r.bottom() + dp.y())
            if 'l' in h: r.setLeft(r.left() + dp.x())
            if 'r' in h: r.setRight(r.right() + dp.x())
            self.rect_obj = r.normalized()
            self.rect_obj = self.rect_obj.intersected(self.rect())
            self._origin = pos
            self._apply_selection_mask()
            self.update()
        elif self.state == 'SELECTED':
            handles = self.get_handles()
            h_found = None
            for h, hr in handles.items():
                if hr.contains(pos):
                    h_found = h
                    break
            if h_found in ['tl', 'br']: self.setCursor(Qt.CursorShape.SizeFDiagCursor)
            elif h_found in ['tr', 'bl']: self.setCursor(Qt.CursorShape.SizeBDiagCursor)
            elif h_found in ['t', 'b']: self.setCursor(Qt.CursorShape.SizeVerCursor)
            elif h_found in ['l', 'r']: self.setCursor(Qt.CursorShape.SizeHorCursor)
            elif self.rect_obj.contains(pos): self.setCursor(Qt.CursorShape.SizeAllCursor)
            else: self.setCursor(Qt.CursorShape.CrossCursor)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self.state == 'DRAWING':
                if self.rect_obj.width() >= 32 and self.rect_obj.height() >= 32:
                    self.state = 'SELECTED'
                    self._apply_selection_mask()
                    self._emit_change()
                else:
                    self.state = 'IDLE'
                    self.rect_obj = QRect()
                    self._hint.show()
                self.setCursor(Qt.CursorShape.CrossCursor)
            elif self.state in ['MOVING', 'RESIZING']:
                if self.rect_obj.width() >= 32 and self.rect_obj.height() >= 32:
                    self.state = 'SELECTED'
                    self._apply_selection_mask()
                    self._emit_change()
                else:
                    self.state = 'IDLE'
                    self.rect_obj = QRect()
                    self._hint.show()
            self.update()

    def _emit_change(self):
        # rect_obj is widget-local; consumers use virtual-desktop coordinates.
        desktop_origin = self.geometry().topLeft()
        region = {
            "top": self.rect_obj.top() + desktop_origin.y(),
            "left": self.rect_obj.left() + desktop_origin.x(),
            "width": self.rect_obj.width(),
            "height": self.rect_obj.height()
        }
        self.selectionChanged.emit(region)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        p.fillRect(self.rect(), Qt.GlobalColor.transparent)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 1. Draw the static frozen background if we have one
        if self._bg_pixmap:
            p.drawPixmap(self.rect(), self._bg_pixmap)
        else:
            # Fallback if no frozen background: just clear background
            p.fillRect(self.rect(), Qt.GlobalColor.transparent)

        # 2. Dim the area OUTSIDE the selection
        # We use QRegion to exclude the selection from the dimming fill
        dim_color = QColor(0, 0, 0, 0 if self._mode == "record" and self.state in ("SELECTED", "MOVING", "RESIZING") else 110)
        if self.rect_obj.isValid():
            full_region = QRegion(self.rect())
            sel_region = QRegion(self.rect_obj)
            dim_region = full_region.subtracted(sel_region)
            
            p.setClipRegion(dim_region)
            p.fillRect(self.rect(), dim_color)
            p.setClipping(False)
            
            # 3. Draw selection border (dashed lines)
            sel = self.rect_obj
            p.save()
            p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
            p.setPen(_capture_outline_pen(self.selection_color))
            p.drawRect(QRectF(sel).adjusted(0, 0, -1, -1))
            p.restore()

            if self._mode != "screenshot":
                handles = self.get_handles()
                for hr in handles.values():
                    center = QPointF(hr.x() + hr.width()/2, hr.y() + hr.height()/2)
                    p.setPen(QPen(QColor("#341015"), 1))
                    p.setBrush(self.selection_color)
                    p.drawEllipse(center, 2.5, 2.5)

            # 4. Draw dimensions label
            dim = f"{sel.width()} × {sel.height()}"
            p.setFont(QFont("Segoe UI", 10, QFont.Weight.Medium))
            fm = QFontMetrics(p.font())
            lw = fm.horizontalAdvance(dim) + 12
            lh = fm.height() + 6
            lx = sel.left() + 4
            ly = sel.top() - lh - 4 if sel.top() > lh + 8 else sel.top() + lh + 4

            bg_rect = QRect(lx - 2, ly - lh + 2, lw, lh)
            bg_color = QColor(self.selection_color)
            bg_color.setAlpha(200)
            p.fillRect(bg_rect, bg_color)
            p.setPen(QColor(255, 255, 255))
            p.drawText(bg_rect, Qt.AlignmentFlag.AlignCenter, dim)
        else:
            # If no selection, dim the whole thing
            p.fillRect(self.rect(), dim_color)

        p.end()


# ─────────────────────────────────────────────────────────────────────────────
#  CaptureBorderWidget
# ─────────────────────────────────────────────────────────────────────────────

class CaptureBorderWidget(QWidget):
    """
    A thin, transparent window that overlays the selected region to show
    a visible red outline during recording. It is excluded from capture
    and transparent to mouse clicks.
    """

    def __init__(self, region: dict):
        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowTransparentForInput
        )
        super().__init__(None, flags)

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        # Enforce exclusion initially
        _exclude_from_capture(int(self.winId()))

        # Use EXACT selection coordinates so border is visible at screen edges
        self.setGeometry(
            region["left"],
            region["top"],
            region["width"],
            region["height"],
        )

        # Enforce topmost to stay above Windows Taskbar
        self._top_timer = QTimer(self)
        self._top_timer.timeout.connect(self._enforce_topmost)
        self._top_timer.start(2000)  # PERF-007: Relaxed from 500ms

    def showEvent(self, event):
        super().showEvent(event)
        _exclude_from_capture(int(self.winId()))

    def _enforce_topmost(self):
        if self.isVisible() and _user32:
            HWND_TOPMOST = -1
            SWP_NOSIZE = 0x0001
            SWP_NOMOVE = 0x0002
            SWP_NOACTIVATE = 0x0010
            _user32.SetWindowPos(int(self.winId()), HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
            _exclude_from_capture(int(self.winId()))
        self.raise_()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        p.fillRect(self.rect(), Qt.GlobalColor.transparent)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        p.setPen(_capture_outline_pen(QColor(255, 60, 70, 255)))
        
        # Border sits precisely on the inner boundary
        # Since the widget is exactly the region size, drawing at adjusted(1,1,-1,-1)
        # keeps the line VISIBLE and centered.
        rect_border = self.rect().adjusted(1, 1, -1, -1)
        p.drawRect(rect_border)
        
        p.end()


# ─────────────────────────────────────────────────────────────────────────────
#  _PillToolButton  (internal)
# ─────────────────────────────────────────────────────────────────────────────

def _asset(filename: str) -> str:
    import os, sys
    from icon_theme import asset_path
    return asset_path(filename)

class _PillToolButton(QToolButton):
    """Icon only button used inside the Pill widget."""

    def __init__(self, icon_filename: str, text: str, checkable: bool = False, icon_off_filename: str = None):
        super().__init__()
        self.setCheckable(checkable)
        
        # NOTE: Tooltip only, no text label
        self.setToolTip(text)
        
        self.setIconSize(QSize(22, 22))
        self.setFixedSize(38, 38)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_AlwaysShowToolTips)
        
        self.icon_path_on = _asset(icon_filename)
        self.icon_path_off = _asset(icon_off_filename) if icon_off_filename else self.icon_path_on
        self.icon_name_on = icon_filename
        self.icon_name_off = icon_off_filename or icon_filename
        
        self._is_danger = False
        self._update_icon()
        self._update_style()
        self.toggled.connect(self._on_toggled)

        self._tip_timer = QTimer(self)
        self._tip_timer.setSingleShot(True)
        self._tip_timer.setInterval(400) 
        self._tip_timer.timeout.connect(self._show_tip)
        self.setMouseTracking(True)

    def set_danger(self, enabled: bool):
        """Toggle between standard and 'danger' red styling."""
        self._is_danger = enabled
        self._update_style()

    def _show_tip(self):
        if self.underMouse() and self.toolTip():
            pos = self.mapToGlobal(QPoint(self.width() // 2, self.height() + 4))
            QToolTip.showText(pos, self.toolTip(), self)

    def mousePressEvent(self, e):
        self._tip_timer.stop()
        QToolTip.hideText()
        super().mousePressEvent(e)

    def enterEvent(self, e):
        self._tip_timer.start()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._tip_timer.stop()
        QToolTip.hideText()
        super().leaveEvent(e)
        
    def _on_toggled(self):
        self._update_icon()
        self._update_style()

    def _update_icon(self):
        path = self.icon_path_on if (not self.isCheckable() or self.isChecked()) else self.icon_path_off
        if os.path.isfile(path):
            self.setIcon(QIcon(path))

    def _update_style(self):
        # Quiet neutral controls with red reserved for destructive/off states.
        if self._is_danger or (self.isCheckable() and not self.isChecked()):
            bg = "#351922"
            border = "#66303E"
            hover = "#4A202C"
        else:
            bg = "#181D27"
            border = "#353D4B"
            hover = "#252C39"

        base_style = f"""
            QToolButton {{
                background: {bg};
                border: 1px solid {border};
                border-radius: 9px;
                padding: 0px;
            }}
            QToolButton:hover {{ background: {hover}; border-color: #666670; }}
            QToolButton:pressed {{ background: #1C1C1E; }}
            QToolButton:focus {{ border: 1px solid #F87171; }}
            QToolButton:disabled {{ background: #1D1D20; border-color: #29292D; }}
        """
        checked_style = """
            QToolButton:checked {
                background: #172E28;
                color: #FFFFFF;
                border: 1px solid #3F8063;
            }
            QToolButton:checked:hover { background: #274033; border-color: #5B9A6D; }
        """
        self.setStyleSheet(base_style + (checked_style if self.isCheckable() else ""))

    def update_text(self, text: str):
        self.setToolTip(text)


# ─────────────────────────────────────────────────────────────────────────────
#  PillWidget
# ─────────────────────────────────────────────────────────────────────────────

class _StopWorker(QThread):
    save_finished = pyqtSignal(str)
    def __init__(self, engine):
        super().__init__()
        self._engine = engine
        self._session_generation = getattr(engine, '_session_generation', None)
        self._aborted = False
    def abort(self):
        """Ask the in-flight mux to stop treating its output as a successful save."""
        self._aborted = True
    def run(self):
        path = ''
        try:
            # Always release capture clients, even if Discard arrived before run.
            self._engine.stop_capture()
            if not self._aborted:
                path = self._engine.mux_and_save() or ''
        except Exception as exc:
            self._engine._last_error = str(exc)
            print(f'[PillWidget] Save failed: {exc}')
        if self._aborted:
            # One worker owns Stop -> mux -> discard. Never race input cleanup
            # against an encoder or WAV writer in another thread.
            if hasattr(self._engine, 'discard'):
                if self._session_generation is None:
                    self._engine.discard()
                else:
                    self._engine.discard(expected_generation=self._session_generation)
            if path:
                try:
                    os.remove(path)
                except OSError as exc:
                    print(f'[PillWidget] Discarded output preserved: {exc}')
            path = ''
        self.save_finished.emit(path)

_microphone_list_workers = set()


class _MicrophoneListWorker(QThread):
    loaded = pyqtSignal(list, str)

    def __init__(self, engine, parent):
        super().__init__()
        self.engine = engine
        _microphone_list_workers.add(self)
        self.finished.connect(lambda: _microphone_list_workers.discard(self))

    def run(self):
        initialized = False
        try:
            if sys.platform == 'win32':
                import pythoncom
                pythoncom.CoInitializeEx(pythoncom.COINIT_MULTITHREADED)
                initialized = True
            self.loaded.emit(self.engine.list_microphones(), "")
        except Exception as error:
            self.loaded.emit([], str(error))
        finally:
            if initialized:
                pythoncom.CoUninitialize()


class PillWidget(QWidget):
    stopped            = pyqtSignal(str)
    save_completed     = pyqtSignal(str)   # Emitted when background muxing finishes
    microphone_selected = pyqtSignal(str, str)
    keycast_consent_changed = pyqtSignal(bool)
    start_requested    = pyqtSignal()
    annotate_requested = pyqtSignal()      # Toggle annotation (same as dock)
    annotation_toggled = pyqtSignal(bool)  # True = annotation ON
    annotation_tool_changed = pyqtSignal(str)   # tool name
    annotation_color_changed = pyqtSignal(str)  # hex color
    annotation_undo = pyqtSignal()
    annotation_redo = pyqtSignal()
    annotation_clear = pyqtSignal()

    _BG_DARK    = QColor(28, 28, 30, 245)
    _BORDER_CLR = QColor(255, 255, 255, 20)

    def __init__(self, engine, config: dict, pre_record: bool = False):
        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        super().__init__(None, flags)
        self._engine  = engine
        self._config  = config
        self._pre_record = pre_record
        self._drag_pos: Optional[QPoint] = None
        self._elapsed = 0
        self._stop_worker: Optional[_StopWorker] = None
        self._stopping = False
        self._preparing = False
        self._user_positioned = False
        self._keycast_region = None
        self._keycast_warning = None
        self._keycast_confirmed = False
        from keycast import KeycastController
        self._keycast = KeycastController(self)
        self._keycast.failed.connect(self._on_keycast_failed)

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_AlwaysShowToolTips)
        self.setMouseTracking(True)

        self._build_ui()
        self._setup_timers()
        self._position_on_screen()

        self._topmost_timer = QTimer(self)
        self._topmost_timer.timeout.connect(self._enforce_topmost)
        self._topmost_timer.start(2000)

        QTimer.singleShot(150, self._apply_exclusion)

    def showEvent(self, event):
        super().showEvent(event)
        _exclude_from_capture(int(self.winId()))

    def _enforce_topmost(self):
        # Raising the owner above its active popup hides the microphone choices
        # on Windows. Let the popup own the topmost position until it closes.
        menu = getattr(self, '_mic_menu', None)
        if menu is not None and menu.isVisible():
            return
        if self._keycast_warning is not None and self._keycast_warning.isVisible():
            return
        if self.isVisible() and not self.underMouse():
            if _user32:
                HWND_TOPMOST = -1
                SWP_NOSIZE = 0x0001
                SWP_NOMOVE = 0x0002
                SWP_NOACTIVATE = 0x0010
                _user32.SetWindowPos(int(self.winId()), HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
                _exclude_from_capture(int(self.winId()))
            self.raise_()

    def _apply_exclusion(self):
        _exclude_from_capture(int(self.winId()))

    def _build_ui(self):
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSizeConstraint(QHBoxLayout.SizeConstraint.SetFixedSize)

        self._pill = QWidget(self)
        self._pill.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        pill_vbox = QVBoxLayout(self._pill)
        pill_vbox.setContentsMargins(0, 0, 0, 0)
        pill_vbox.setSpacing(0)
        pill_vbox.setSizeConstraint(QVBoxLayout.SizeConstraint.SetFixedSize)

        # ── ROW 1: Main Controls ──────────────────────────────────────────────
        row1_widget = QWidget()
        row1_widget.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        row = QHBoxLayout(row1_widget)
        row.setContentsMargins(10, 7, 10, 7)
        row.setSpacing(5)

        def control_group(object_name: str):
            group = QWidget()
            group.setObjectName(object_name)
            group.setStyleSheet(f"""
                QWidget#{object_name} {{
                    background: #11151D; border: 1px solid #343B48; border-radius: 12px;
                }}
            """)
            group_layout = QHBoxLayout(group)
            group_layout.setContentsMargins(3, 3, 3, 3)
            group_layout.setSpacing(2)
            return group, group_layout

        # ── Left Section: Recording Status ────────────────────────────────────
        self._btn_start = QPushButton("Start")
        self._btn_start.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_start.setStyleSheet(
            """
            QPushButton {
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #FF5264, stop:1 #E3223B);
                color: white; border: 1px solid rgba(255,255,255,0.18); border-radius: 9px;
                font-weight: 700; padding: 8px 16px; font-size: 12px;
            }
            QPushButton:hover { background: #FF4055; }
            QPushButton:pressed { background: #BE1230; }
            QPushButton:focus { border: 1px solid #FDA4AF; }
            QPushButton:disabled { background: #303034; color: rgba(255,255,255,0.45); }
            """
        )
        self._btn_start.clicked.connect(self.start_requested.emit)
        row.addWidget(self._btn_start)

        self._sep_start = self._make_sep(row, True)
        self._sep_start.setVisible(self._pre_record)

        self._status_badge = QWidget()
        self._status_badge.setObjectName("RecordingStatusBadge")
        self._status_badge.setFixedHeight(38)
        self._status_badge.setStyleSheet("""
            QWidget#RecordingStatusBadge {
                background: #11141A; border: 1px solid #343B48; border-radius: 9px;
            }
        """)
        status_layout = QHBoxLayout(self._status_badge)
        status_layout.setContentsMargins(9, 0, 9, 0)
        status_layout.setSpacing(6)

        self._dot = QLabel("●")
        self._dot.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._dot.setFixedWidth(10)
        self._dot.setStyleSheet("color:#FF4055; font-size:14px; padding:0; margin:0; border:none; background:transparent;")
        status_layout.addWidget(self._dot)
        
        self._lbl_time = QLabel("00:00:00")
        self._lbl_time.setFixedWidth(68)
        self._lbl_time.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_time.setStyleSheet(
            "color:#F8FAFC; font-family:'Cascadia Mono','Consolas',monospace; font-size:13px; font-weight:700; letter-spacing:0.2px; border:none; background:transparent;"
        )
        status_layout.addWidget(self._lbl_time)
        row.addWidget(self._status_badge)
        self._status_badge.setVisible(not self._pre_record)

        self._sep_timer = self._make_sep(row, False)

        # ── Buttons ───────────────────────────────────────────────────────────
        self._transport_group, transport_layout = control_group("TransportGroup")
        self._btn_pause = _PillToolButton("pause.png", "Pause recording")
        self._btn_pause.clicked.connect(self.toggle_pause)
        transport_layout.addWidget(self._btn_pause)
        self._btn_pause.setVisible(not self._pre_record)

        self._btn_stop = _PillToolButton("stop.png", "Stop and save recording")
        self._btn_stop.set_danger(True)
        self._btn_stop.clicked.connect(self._initiate_stop)
        transport_layout.addWidget(self._btn_stop)
        self._btn_stop.setVisible(not self._pre_record)
        self._transport_group.setVisible(not self._pre_record)
        row.addWidget(self._transport_group)

        self._sep_stop = QWidget()
        self._sep_stop.setVisible(False)

        self._audio_group, audio_layout = control_group("AudioGroup")
        self._btn_sys = _PillToolButton("desktop_audio.png", "Desktop Audio\nON", checkable=True, icon_off_filename="desktop_audiooff.png")
        sys_state = self._engine.get_system_audio() if hasattr(self._engine, 'get_system_audio') else bool(self._config.get('record_system_audio', True))
        self._btn_sys.setChecked(sys_state)
        self._btn_sys.update_text("Desktop Audio\nON" if sys_state else "Desktop Audio\nOFF")
        self._btn_sys.toggled.connect(self._on_sys_toggled)
        audio_layout.addWidget(self._btn_sys)

        self._btn_mic = _PillToolButton("mic.png", "Microphone\nON", checkable=True, icon_off_filename="micoff.png")
        mic_state = self._engine.get_mic() if hasattr(self._engine, 'get_mic') else bool(self._config.get('record_mic', True))
        self._btn_mic.setChecked(mic_state)
        self._btn_mic.update_text("Microphone\nON" if mic_state else "Microphone\nOFF")
        self._btn_mic.toggled.connect(self._on_mic_toggled)
        audio_layout.addWidget(self._btn_mic)
        self._btn_mic_menu = QToolButton()
        self._btn_mic_menu.setIcon(QIcon(_asset("spn_down.png")))
        self._btn_mic_menu.setIconSize(QSize(10, 10))
        self._btn_mic_menu.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_mic_menu.setAccessibleName("Choose microphone")
        self._btn_mic_menu.setFixedSize(16, 38)
        self._btn_mic_menu.setStyleSheet("""
            QToolButton { background: #181D27; border: none; border-left: 1px solid #353D4B;
                border-top-right-radius: 5px; border-bottom-right-radius: 5px; }
            QToolButton:hover { background: #353D4B; }
            QToolButton[menuOpen="true"] { background: #353D4B; border-left-color: #FF5264; }
            QToolButton:disabled { background: #181D27; }
        """)
        self._btn_mic_menu.setToolTip("Choose microphone")
        self._btn_mic_menu.clicked.connect(self._show_microphone_menu)
        audio_layout.addWidget(self._btn_mic_menu)
        self._mic_status_timer = QTimer(self)
        self._mic_status_timer.timeout.connect(self._update_microphone_tooltip)
        self._mic_status_timer.start(250)
        self._update_microphone_tooltip()
        row.addWidget(self._audio_group)

        # ── Annotate Toggle Button ─────────────────────────────
        self._btn_annotate = _PillToolButton("annotate.png", "Open live annotation toolbar")
        if not os.path.isfile(_asset("annotate.png")):
            self._btn_annotate.setText("✎")
            self._btn_annotate.setStyleSheet(self._btn_annotate.styleSheet() + "QToolButton { font-size: 16px; }")
        self._btn_annotate.setCheckable(True)
        self._btn_annotate.clicked.connect(self._on_annotate_clicked)
        row.addWidget(self._btn_annotate)

        # Keycast is a separate square recording control, beside Annotate.
        from keycast import keycast_icon
        self._btn_keycast = _PillToolButton("keycast.png", "Keycast off — show keys and mouse clicks in the recording", checkable=True)
        if not os.path.isfile(_asset("keycast.png")):
            self._btn_keycast.setIcon(keycast_icon())
        self._btn_keycast.setAccessibleName("Keycast")
        self._btn_keycast.toggled.connect(self._on_keycast_toggled)
        row.addWidget(self._btn_keycast)

        self._btn_discard = _PillToolButton("delete.png", "Discard recording")
        self._btn_discard.set_danger(True)
        self._btn_discard.clicked.connect(self._initiate_discard)
        if self._pre_record:
            self._btn_discard.setToolTip("Cancel / Discard")
        row.addWidget(self._btn_discard)

        pill_vbox.addWidget(row1_widget)

        # ── Group Visibility Initialization ───────────────────────────────────
        self._btn_start.setVisible(self._pre_record)
        self._sep_start.setVisible(self._pre_record)
        self._status_badge.setVisible(not self._pre_record)
        self._sep_timer.setVisible(not self._pre_record)
        self._btn_pause.setVisible(not self._pre_record)
        self._btn_stop.setVisible(not self._pre_record)
        self._transport_group.setVisible(not self._pre_record)

        # ── Size Pill to content ───────────────────────────────────────────────
        self._refresh_pill_size()
        outer.addWidget(self._pill)

    def set_keycast_region(self, region):
        self._keycast_region = dict(region)
        self._sync_keycast()

    def _on_keycast_toggled(self, checked):
        from enterprise_policy import disabled
        if checked and disabled('Keycast'):
            self._btn_keycast.setChecked(False)
            self._btn_keycast.setToolTip('Keycast is disabled by your administrator')
            return
        if checked and not self._config.get('keycast_warning_dismissed', False) and not self._keycast_confirmed:
            self._btn_keycast.blockSignals(True)
            self._btn_keycast.setChecked(False)
            self._btn_keycast.blockSignals(False)
            self._request_keycast_consent()
            return
        self._keycast_confirmed = False
        self._btn_keycast.setToolTip(
            "Keycast on — keys and clicks are visible in the recording" if checked else
            "Keycast off — show keys and mouse clicks in the recording")
        self._sync_keycast()

    def _request_keycast_consent(self):
        if self._keycast_warning is not None:
            self._keycast_warning.raise_()
            return
        box = QMessageBox(self)
        box.setWindowTitle('Before enabling Keycast')
        box.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        box.setText('Your keystrokes may be visible in the recording.')
        box.setInformativeText('This includes passwords, private text, and typing outside the selected '
                               'recording area. Anyone who watches or receives the recording may see '
                               'that input. Enable Keycast only when it is appropriate to show your typing.')
        remember = QCheckBox("Don't show this again", box)
        box.setCheckBox(remember)
        enable = box.addButton('Enable Keycast', QMessageBox.ButtonRole.AcceptRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(QMessageBox.StandardButton.Cancel)
        self._keycast_warning = box

        def completed(_result):
            self._keycast_warning = None
            if box.clickedButton() is enable and not self._stopping:
                if remember.isChecked():
                    self._config['keycast_warning_dismissed'] = True
                    self.keycast_consent_changed.emit(True)
                self._keycast_confirmed = True
                self._btn_keycast.setChecked(True)
            box.deleteLater()

        box.finished.connect(completed)
        box.open()
        _exclude_from_capture(int(box.winId()))

    def _sync_keycast(self):
        enabled = (self._btn_keycast.isChecked() and not self._pre_record and
                   not self._preparing and not self._stopping and self._keycast_region and
                   not self._engine.is_paused())
        from enterprise_policy import disabled
        enabled = enabled and not disabled('Keycast')
        if enabled and self._keycast.session is None:
            from display_geometry import qt_screen_transforms
            self._keycast.start(self._keycast_region, qt_screen_transforms(QApplication.screens()))
        elif not enabled:
            self._keycast.stop()

    def _on_keycast_failed(self, message):
        self._btn_keycast.setChecked(False)
        self._btn_keycast.setToolTip(message)
        self._btn_keycast.setAccessibleDescription(message)
        QToolTip.showText(self._btn_keycast.mapToGlobal(QPoint(0, self._btn_keycast.height())), message, self._btn_keycast)

    def _on_sys_toggled(self, checked):
        self._btn_sys.update_text("Desktop Audio\nON" if checked else "Desktop Audio\nOFF")
        self._engine.set_system_audio(checked)

    def _on_mic_toggled(self, checked):
        self._btn_mic.update_text("Microphone\nON" if checked else "Microphone\nOFF")
        self._engine.set_mic(checked)
        self._update_microphone_tooltip()

    def _update_microphone_tooltip(self):
        name = getattr(self._engine, '_microphone_name', 'Same as Windows')
        if getattr(self._engine, '_mic_fallback', False):
            name += ' (using Windows default)'
        failed = getattr(self._engine, '_microphone_failed', False)
        state = "failed" if failed else ("on" if self._engine.get_mic() else "off")
        self._btn_mic.setToolTip(f"Microphone {state} — {name}")
        self._btn_mic.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly if failed else Qt.ToolButtonStyle.ToolButtonIconOnly)
        self._btn_mic.setText("!" if failed else "")

    def _show_microphone_menu(self):
        if self._preparing or self._stopping:
            return
        if getattr(self, '_mic_menu_worker', None) and self._mic_menu_worker.isRunning():
            return
        self._btn_mic_menu.setEnabled(False)
        self._mic_menu_worker = _MicrophoneListWorker(self._engine, self)
        self._mic_menu_worker.loaded.connect(self._open_microphone_menu)
        self._mic_menu_worker.start()

    def _open_microphone_menu(self, devices, error):
        self._btn_mic_menu.setEnabled(not self._preparing and not self._stopping)
        if not self.isVisible() or self._stopping or self._preparing:
            return
        previous = getattr(self, '_mic_menu', None)
        if previous is not None:
            previous.close()
        menu = QMenu(self)
        menu.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        menu.aboutToHide.connect(lambda: self._release_microphone_menu(menu))
        menu.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        menu.setMinimumWidth(280)
        menu.setStyleSheet("""
            QMenu { background: #181D27; color: #F7F7FA; border: 1px solid #424B5D;
                border-radius: 8px; padding: 6px; font: 12px 'Segoe UI'; }
            QMenu::item { padding: 8px 14px 8px 10px; border-radius: 5px; }
            QMenu::item:selected { background: #343E50; color: white; }
            QMenu::indicator { width: 10px; height: 10px; margin-left: 7px; margin-right: 6px;
                border: 1px solid #657089; border-radius: 6px; background: transparent; }
            QMenu::indicator:checked { background: #FF5264; border: 2px solid #FFD2D8; }
            QMenu::separator { height: 1px; background: #353D4B; margin: 5px 7px; }
        """)
        group = QActionGroup(menu)
        group.setExclusive(True)
        selected = getattr(self._engine, '_microphone_id', '')
        for device_id, name in [("", "Same as Windows")] + devices:
            display_name = QFontMetrics(menu.font()).elidedText(name, Qt.TextElideMode.ElideRight, 280)
            action = menu.addAction(display_name)
            action.setToolTip(name)
            group.addAction(action)
            action.setCheckable(True)
            action.setChecked(device_id == selected)
            action.triggered.connect(lambda checked=False, i=device_id, n=name: self._select_microphone(i, n))
        if error:
            menu.addAction("Could not list microphones").setEnabled(False)
        menu.addSeparator()
        hint = QLabel("Using a Bluetooth mic may reduce headset playback quality.")
        hint.setWordWrap(True)
        hint.setFixedWidth(266)
        hint.setContentsMargins(10, 6, 10, 6)
        hint.setStyleSheet("color: #9BA6BA; background: transparent; font: 10px 'Segoe UI';")
        hint_action = QWidgetAction(menu)
        hint_action.setDefaultWidget(hint)
        hint_action.setEnabled(False)
        menu.addAction(hint_action)
        menu.ensurePolished()
        menu.winId()
        _exclude_from_capture(int(menu.winId()))
        size = menu.sizeHint()
        anchor = self._btn_mic_menu.mapToGlobal(QPoint(0, 0))
        screen = QApplication.screenAt(anchor) or QApplication.primaryScreen()
        position = _clamp_window_top_left(QPoint(anchor.x(), anchor.y() - size.height()), size, screen.availableGeometry())
        self._mic_menu = menu
        self._set_microphone_menu_open(True)
        menu.setWindowOpacity(0.0)
        menu.popup(position)
        menu._fade = QPropertyAnimation(menu, b"windowOpacity", menu)
        menu._fade.setDuration(120)
        menu._fade.setStartValue(0.0)
        menu._fade.setEndValue(1.0)
        menu._fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        menu._fade.start()
        # Apply to the final native popup handle, after Qt has shown it.
        _exclude_from_capture(int(menu.winId()))
        if _user32:
            _user32.SetWindowPos(int(menu.winId()), -1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010)
        menu.raise_()

    def _set_microphone_menu_open(self, opened):
        self._btn_mic_menu.setProperty("menuOpen", opened)
        self._btn_mic_menu.setIcon(QIcon(_asset("spn_up.png" if opened else "spn_down.png")))
        self._btn_mic_menu.style().unpolish(self._btn_mic_menu)
        self._btn_mic_menu.style().polish(self._btn_mic_menu)
        self._btn_mic_menu.update()

    def _release_microphone_menu(self, menu):
        if getattr(self, '_mic_menu', None) is menu:
            self._mic_menu = None
            self._set_microphone_menu_open(False)
        if hasattr(menu, "_fade"):
            menu._fade.stop()
        menu.deleteLater()

    def _select_microphone(self, device_id, name):
        if self._preparing or self._stopping:
            return
        self._engine.set_microphone(device_id, name)
        self.microphone_selected.emit(device_id, name)
        self._update_microphone_tooltip()

    # ── Annotation ────────────────────────────────────────────────────────────

    def _on_annotate_clicked(self):
        self.annotate_requested.emit()
        self.annotation_toggled.emit(self._btn_annotate.isChecked())

    def set_annotation_active(self, active: bool):
        if hasattr(self, '_btn_annotate'):
            self._btn_annotate.blockSignals(True)
            self._btn_annotate.setChecked(active)
            self._btn_annotate.blockSignals(False)
            if hasattr(self._btn_annotate, '_update_icon'):
                self._btn_annotate._update_icon()
            if hasattr(self._btn_annotate, '_update_style'):
                self._btn_annotate._update_style()

    def disable_annotation(self):
        """Called externally to turn off annotation mode (e.g. on stop)."""
        self.set_annotation_active(False)
        self.annotation_toggled.emit(False)

    # ── Timers ────────────────────────────────────────────────────────────────
    def _setup_timers(self):
        if self._pre_record:
            return
        self._tick = QTimer(self)
        self._tick.setInterval(1000)
        self._tick.timeout.connect(self._on_tick)
        self._tick.start()

        self._blink = QTimer(self)
        self._blink.setInterval(700)
        self._blink.timeout.connect(self._on_blink)
        self._blink.start()
        self._blink_on = True

    def set_recording_mode(self):
        """Transition from 'Pre-Record' (setup) to active recording UI."""
        if not self._pre_record:
            return
        self._pre_record = False
        self._preparing = False

        # Preparation temporarily locks all actions. Restore the controls that
        # are intentionally available during an active recording.
        for button in (self._btn_discard, self._btn_sys, self._btn_mic,
                       self._btn_mic_menu, self._btn_annotate, self._btn_keycast):
            button.setEnabled(True)
        
        # Hide start button, show recording status
        self._btn_start.hide()
        self._status_badge.show()
        self._sep_timer.show()
        self._sep_start.hide()
        
        # Show control buttons
        self._btn_pause.show()
        self._btn_stop.show()
        self._transport_group.show()
        self._btn_annotate.show()
        
        # Setup and start timers
        self._setup_timers()
        self._refresh_pill_size()
        self._sync_keycast()

    def set_preparing(self, preparing: bool):
        """Show preparation state and prevent duplicate or conflicting actions."""
        if not self._pre_record:
            return
        self._preparing = preparing
        self._btn_start.setEnabled(not preparing)
        self._btn_start.setText("Starting..." if preparing else "Start")
        for button in (self._btn_discard, self._btn_sys, self._btn_mic,
                       self._btn_mic_menu, self._btn_annotate, self._btn_keycast):
            button.setEnabled(not preparing)
        self._refresh_pill_size()

    def _update_size(self):
        """Recalculate layout and resize window to fit content."""
        self._pill.adjustSize()
        w = self._pill.sizeHint().width()
        h = self._pill.sizeHint().height()
        self.setFixedSize(w, h)
        self._pill.setGeometry(0, 0, w, h)

    def _on_tick(self):
        if not self._engine.is_paused():
            self._elapsed += 1
        h = self._elapsed // 3600
        m = (self._elapsed % 3600) // 60
        s = self._elapsed % 60
        if h > 0:
            self._lbl_time.setText(f"{h:02d}:{m:02d}:{s:02d}")
        else:
            self._lbl_time.setText(f"00:{m:02d}:{s:02d}")

    def _on_blink(self):
        if self._engine.is_paused():
            self._dot.setStyleSheet("color:#FF9F0A; font-size:12px; padding:0; margin:0;")
        else:
            self._blink_on = not self._blink_on
            clr = "#FF3B30" if self._blink_on else "rgba(255,59,48,0)"
            self._dot.setStyleSheet(f"color:{clr}; font-size:12px; padding:0; margin:0;")

    # ── Actions ─────────────────────────────────────────────────────────────
    def toggle_pause(self):
        if self._engine.is_paused():
            self._engine.resume()
            self._btn_pause.update_text("Pause recording")
            self._btn_pause.setIcon(QIcon(_asset("pause.png")))
        else:
            self._engine.pause()
            self._btn_pause.update_text("Resume recording")
            self._btn_pause.setIcon(QIcon(_asset("play.png")))
        self._sync_keycast()

    def _initiate_stop(self):
        if self._stopping or self._preparing:
            return
        self._stopping = True
        self._stop_worker = _StopWorker(self._engine)
        self._stop_worker.save_finished.connect(self._on_save_done)
        self._keycast.stop()
        if hasattr(self, '_tick'): self._tick.stop()
        if hasattr(self, '_blink'): self._blink.stop()
        if hasattr(self, '_topmost_timer'): self._topmost_timer.stop()

        # Disable annotation mode before stopping
        self.disable_annotation()

        # Hide pill IMMEDIATELY — user sees instant response
        self.hide()

        # Establish ownership before emitting a signal that can re-enter Discard.
        self.stopped.emit("<SAVING>")
        self._stop_worker.start()

    def _initiate_discard(self, *, confirm: bool = True):
        worker = getattr(self, "_stop_worker", None)
        # A second discard after the save was already aborted is a no-op.
        # A discard while mux is still running must abort that save instead of
        # returning early and letting save_finished resurrect a "saved" file.
        if getattr(self, "_save_aborted", False):
            return
        # Stop sets _stopping before the thread is actually running. Discard
        # during that window must still abort, or save_finished publishes the file.
        if self._stopping and worker is not None:
            self._abort_in_flight_save()
            return
        if self._stopping:
            return
        # Never call QMessageBox.exec() from closeEvent / teardown — nested
        # modal loops on the GUI thread deadlock or freeze Windows shutdown.
        if confirm and not self._pre_record:
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Warning)
            box.setWindowTitle("Discard Recording?")
            box.setText("Discard this recording permanently?")
            box.setInformativeText("Choose Stop instead if you want to keep it.")
            box.setStandardButtons(
                QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel
            )
            box.setDefaultButton(QMessageBox.StandardButton.Cancel)
            box.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
            box.show()
            _exclude_from_capture(int(box.winId()))
            if box.exec() != QMessageBox.StandardButton.Discard:
                return
        self._stopping = True
        self._keycast.stop()
        if hasattr(self, '_tick'): self._tick.stop()
        if hasattr(self, '_blink'): self._blink.stop()
        if hasattr(self, '_topmost_timer'): self._topmost_timer.stop()

        # Disable annotation mode before discarding
        self.disable_annotation()

        # Hide pill IMMEDIATELY
        self.hide()
        self.stopped.emit("<DISCARDED>")

        # Discard in background (fast — no muxing needed)
        import threading
        self._discard_generation = getattr(self._engine, '_session_generation', None)
        threading.Thread(target=self._do_discard, daemon=True).start()

    def _abort_in_flight_save(self):
        """Discard wins over an in-progress Stop/mux. Late save_finished must not publish a file."""
        self._save_aborted = True
        self._discard_generation = getattr(self._stop_worker, '_session_generation', None)
        self._stopping = True
        worker = getattr(self, "_stop_worker", None)
        if worker is not None:
            worker.abort()
        self._keycast.stop()
        if hasattr(self, "_tick"):
            self._tick.stop()
        if hasattr(self, "_blink"):
            self._blink.stop()
        if hasattr(self, "_topmost_timer"):
            self._topmost_timer.stop()
        self.disable_annotation()
        self.hide()
        self.stopped.emit("<DISCARDED>")

    def _do_discard(self):
        if hasattr(self._engine, "discard"):
            generation = getattr(self, '_discard_generation', None)
            if generation is None:
                self._engine.discard()
            else:
                self._engine.discard(expected_generation=generation)

    def _on_save_done(self, filepath: str):
        if getattr(self, "_save_aborted", False):
            # A discard can arrive after the worker emitted its queued result.
            # At this point mux no longer owns the output; cleanup is safe.
            if filepath:
                import threading
                def cleanup():
                    self._do_discard()
                    try:
                        os.remove(filepath)
                    except OSError as exc:
                        print(f'[PillWidget] Discarded output preserved: {exc}')
                threading.Thread(target=cleanup, daemon=True).start()
            self.close()
            return
        self.save_completed.emit(filepath)
        self.close()

    def closeEvent(self, event):
        if self._preparing and not self._stopping:
            event.ignore()
            return
        if (not self._stopping and not self._pre_record
                and getattr(self._engine, 'is_recording', lambda: False)()):
            # External window close must never silently discard a live take.
            # Stop/save asynchronously; successful completion closes the pill.
            event.ignore()
            self._initiate_stop()
            return
        if not self._stopping:
            self._initiate_discard(confirm=False)
        if hasattr(self, '_topmost_timer'):
            self._topmost_timer.stop()
        self._keycast.stop()
        super().closeEvent(event)

    def _make_sep(self, layout, visible=True):
        """Creates a separator container with internal margins that collapse when hidden."""
        container = QWidget()
        container.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        l = QHBoxLayout(container)
        l.setContentsMargins(4, 0, 4, 0)
        l.setSpacing(0)
        
        line = QWidget()
        line.setFixedSize(1, 20)
        line.setStyleSheet("background-color: #4A4A4C;")
        l.addWidget(line)
        
        container.setVisible(visible)
        layout.addWidget(container)
        return container

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        p.fillRect(self.rect(), Qt.GlobalColor.transparent)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = 12.0
        rect = self.rect().adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(float(rect.x()), float(rect.y()), float(rect.width()), float(rect.height()), r, r)

        gradient = QLinearGradient(0, 0, 0, self.height())
        gradient.setColorAt(0.0, QColor(29, 35, 48, 252))
        gradient.setColorAt(0.5, QColor(18, 22, 31, 252))
        gradient.setColorAt(1.0, QColor(10, 12, 17, 252))
        p.fillPath(path, QBrush(gradient))
        p.setPen(QPen(QColor(255, 255, 255, 38), 1.0))
        p.drawPath(path)
        p.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, event):
        if self._drag_pos and (event.buttons() & Qt.MouseButton.LeftButton):
            self._user_positioned = True
            self.move(event.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, _event):
        self._drag_pos = None

    def _refresh_pill_size(self):
        """Recalculate pill size to fit current content."""
        previous_position = QPoint(self.pos())
        preserve_user_position = self._user_positioned
        self._pill.adjustSize()
        self.adjustSize()
        if preserve_user_position:
            QTimer.singleShot(0, lambda pos=previous_position: self._restore_user_position(pos))
        else:
            QTimer.singleShot(0, self._position_on_screen)

    def _restore_user_position(self, position: QPoint):
        anchor = position + QPoint(max(1, self.width() // 2), max(1, self.height() // 2))
        screen = QApplication.screenAt(anchor) or QApplication.primaryScreen()
        available = screen.availableGeometry() if screen else QRect(0, 0, 1920, 1080)
        self.move(_clamp_window_top_left(position, self.size(), available))

    def _position_on_screen(self):
        sg = QApplication.primaryScreen().geometry()
        # Move up a bit to match control center styling commonly used
        self.move(sg.center().x() - self.width() // 2, sg.top() + 30)


# ─────────────────────────────────────────────────────────────────────────────
#  SettingsWindow
# ─────────────────────────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────────────────────────
#  Settings Custom Widgets
# ─────────────────────────────────────────────────────────────────────────────
class ToggleSwitch(QCheckBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(46, 26)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        bg = QColor("#32D74B") if self.isChecked() else QColor("#39393D")
        p.setBrush(bg)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(0, 0, self.width(), self.height(), 13, 13)
        p.setBrush(QColor("#FFFFFF"))
        if self.isChecked(): p.drawEllipse(self.width() - 24, 2, 22, 22)
        else: p.drawEllipse(2, 2, 22, 22)
        p.end()
    def hitButton(self, pos: QPoint) -> bool:
        return self.rect().contains(pos)

class HotkeyInput(QLineEdit):
    def __init__(self, default=""):
        super().__init__(default)
        self.setReadOnly(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._listening = False
    def mousePressEvent(self, e):
        super().mousePressEvent(e)
        self._listening = True
        self.setText("Listening...")
        self.setStyleSheet("background: #0A84FF; color: white;")
    def keyPressEvent(self, e):
        if not self._listening: return
        mods = []
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier: mods.append("<ctrl>")
        if e.modifiers() & Qt.KeyboardModifier.AltModifier: mods.append("<alt>")
        if e.modifiers() & Qt.KeyboardModifier.ShiftModifier: mods.append("<shift>")
        k = e.key()
        if k in (Qt.Key.Key_Control, Qt.Key.Key_Shift, Qt.Key.Key_Alt, Qt.Key.Key_Meta): return
        ks = ""
        if Qt.Key.Key_A <= k <= Qt.Key.Key_Z: ks = chr(k).lower()
        elif Qt.Key.Key_0 <= k <= Qt.Key.Key_9: ks = chr(k)
        else:
            map_k = {Qt.Key.Key_Return:"<enter>", Qt.Key.Key_Escape:"<esc>", Qt.Key.Key_Space:"<space>", Qt.Key.Key_Backspace:"<backspace>"}
            if k in map_k: ks = map_k[k]
            elif Qt.Key.Key_F1 <= k <= Qt.Key.Key_F12: ks = f"<f{k - Qt.Key.Key_F1 + 1}>"
        if ks:
            mods.append(ks)
            self.setText("+".join(mods))
            self._listening = False
            self.setStyleSheet("")

class SettingsWindow(QDialog):
    def __init__(self, config: dict):
        super().__init__(None, Qt.WindowType.WindowCloseButtonHint)
        self._config = config.copy()
        
        # OS window title & icon
        self.setWindowTitle("WWRecorder Settings")
        from distribution import application_icon_path
        icon_path = application_icon_path()
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
            
        self.setFixedWidth(500)
        self.setModal(True)
        self._build_ui()
        self._apply_style()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(30, 25, 30, 30)
        root.setSpacing(25)

        # Header
        hdr_lay = QHBoxLayout()
        icon_lbl = QLabel()
        from distribution import application_icon_path
        icon_path = application_icon_path()
        if os.path.exists(icon_path):
            from PyQt6.QtGui import QPixmap
            icon_lbl.setPixmap(QPixmap(icon_path).scaled(28, 28, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        hdr = QLabel("WWRecorder Settings")
        hdr.setObjectName("heading")
        hdr_lay.addWidget(icon_lbl)
        hdr_lay.addSpacing(8)
        hdr_lay.addWidget(hdr)
        hdr_lay.addStretch()
        root.addLayout(hdr_lay)

        # Layout Helper
        def create_group(title):
            grp = QGroupBox(title)
            lay = QVBoxLayout(grp)
            lay.setContentsMargins(20, 25, 20, 20)
            lay.setSpacing(14)
            return grp, lay

        # ── Output folder ─────────────────────────────────────────────────────
        grp_out, lay_out = create_group("Recording Output")
        
        row_out = QHBoxLayout()
        self._edt_folder = QLineEdit(self._config.get("output_folder", ""))
        self._edt_folder.setReadOnly(True)
        self._edt_folder.setMinimumHeight(38)
        row_out.addWidget(self._edt_folder)

        btn_browse = QPushButton("Browse")
        btn_browse.setObjectName("secondary")
        btn_browse.setMinimumHeight(38)
        btn_browse.setFixedWidth(80)
        btn_browse.clicked.connect(self._browse)
        row_out.addWidget(btn_browse)
        
        lay_out.addLayout(row_out)
        root.addWidget(grp_out)

        # ── Shortcuts & Share ─────────────────────────────────────────────────
        hk_share_lay = QHBoxLayout()
        hk_share_lay.setSpacing(15)

        grp_hk, lay_hk = create_group("Hotkey Settings")
        
        lbl_hk = QLabel("Shortcut Key:")
        lay_hk.addWidget(lbl_hk)
        
        self._edt_hotkey = HotkeyInput(self._config.get("hotkey", "<shift>+<backspace>"))
        self._edt_hotkey.setMinimumHeight(38)
        lay_hk.addWidget(self._edt_hotkey)
        
        hk_share_lay.addWidget(grp_hk)

        # ── Share App ─────────────────────────────────────────────────────────
        grp_share, lay_share = create_group("Share App")
        
        lbl_share = QLabel("Invite friends to use WWRecorder:")
        lay_share.addWidget(lbl_share)

        btn_copy_link = QPushButton("Copy App Link")
        btn_copy_link.setObjectName("secondary")
        btn_copy_link.setMinimumHeight(38)
        btn_copy_link.clicked.connect(self._copy_app_link)
        lay_share.addWidget(btn_copy_link)
        
        hk_share_lay.addWidget(grp_share)

        root.addLayout(hk_share_lay)

        # ── Toggles ───────────────────────────────────────────────────────────
        grp_def, lay_def = create_group("Default Behavior")

        def add_toggle_row(lay, label_text, is_checked):
            row = QHBoxLayout()
            chk = ToggleSwitch()
            chk.setChecked(is_checked)
            lbl = QLabel(label_text)
            lbl.setStyleSheet("font-size: 14px; color: #EBEBF5;")
            row.addWidget(chk)
            row.addSpacing(10)
            row.addWidget(lbl)
            row.addStretch()
            lay.addLayout(row)
            return chk

        self._chk_sys = add_toggle_row(lay_def, "Record system audio by default", self._config.get("default_system_audio", False))
        self._chk_mic = add_toggle_row(lay_def, "Record microphone by default", self._config.get("default_mic", False))
        self._chk_boot = add_toggle_row(lay_def, "Start WWRecorder with Windows", self._config.get("start_on_boot", False))
        
        root.addWidget(grp_def)

        # ── Buttons ───────────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        
        credit = QLabel("<a href='https://github.com/akasumitlamba' style='color:#0A84FF; text-decoration:underline; font-size:12px;'>Made by akasumitlamba</a>")
        credit.setOpenExternalLinks(True)
        btn_row.addWidget(credit)
        
        btn_row.addStretch()

        btn_cancel = QPushButton("Cancel")
        btn_cancel.setObjectName("secondary")
        btn_cancel.setMinimumHeight(38)
        btn_cancel.setFixedWidth(100)
        btn_cancel.clicked.connect(self.reject)
        
        btn_save = QPushButton("Save Settings")
        btn_save.setObjectName("primary")
        btn_save.setMinimumHeight(38)
        btn_save.setFixedWidth(130)
        btn_save.clicked.connect(self._save)

        btn_row.addWidget(btn_cancel)
        btn_row.addSpacing(6)
        btn_row.addWidget(btn_save)
        root.addLayout(btn_row)

    def _browse(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Output Folder", self._edt_folder.text())
        if folder:
            self._edt_folder.setText(folder)

    def _copy_app_link(self):
        QApplication.clipboard().setText("https://akasumitlamba.github.io/WWRecorder/")
        btn = self.sender()
        if btn:
            orig = btn.text()
            btn.setText("Copied!")
            QTimer.singleShot(1500, lambda: btn.setText(orig))

    def _save(self):
        self._config.update({
            "output_folder":        self._edt_folder.text(),
            "hotkey":               self._edt_hotkey.text().strip(),
            "default_system_audio": self._chk_sys.isChecked(),
            "default_mic":          self._chk_mic.isChecked(),
            "start_on_boot":        self._chk_boot.isChecked(),
        })
        self.accept()

    def get_config(self) -> dict: return self._config

    def _apply_style(self):
        self.setStyleSheet("""
            QDialog {
                background-color: #1C1C1E;
                color: #FFFFFF;
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            }
            #heading {
                font-size: 26px; font-weight: 700; color: #FFFFFF;
            }
            QGroupBox {
                background: #252528; border: 1px solid #333336; border-radius: 8px;
                font-size: 13px; font-weight: 600; color: #8E8E93;
                margin-top: 14px; padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin; subcontrol-position: top left; left: 16px; padding: 0 4px;
            }
            QLabel { font-size: 13px; color: #D1D1D6; }
            QLineEdit {
                background: #1C1C1E; border: 1px solid #333336; border-radius: 6px;
                padding: 0 12px; color: #FFFFFF; font-size: 14px;
            }
            QLineEdit:focus { border: 1px solid #0A84FF; }
            
            QCheckBox { font-size: 14px; color: #EBEBF5; spacing: 12px; height: 30px; }
            /* Default QCheckBox styles are ignored for the custom ToggleSwitch. */
            
            QPushButton {
                font-size: 14px; font-weight: 600; border-radius: 8px;
            }
            QPushButton#secondary {
                background: #3A3A3C; color: #FFFFFF; border: none;
            }
            QPushButton#secondary:hover { background: #48484A; }
            QPushButton#primary {
                background: #0A84FF; color: #FFFFFF; border: none;
            }
            QPushButton#primary:hover { background: #0070DF; }
        """)
