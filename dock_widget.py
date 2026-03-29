"""
dock_widget.py - Floating Assistive Dock & Sidebar Panels

• DockWidget       : Edge-snapping floating dock with 4 action buttons
• SidebarPanel     : Full-height resizable sidebar (base class)
• SettingsSidebar  : All app settings in a sidebar
• RecentFilesSidebar : Recent files gallery in a sidebar

All are invisible to screen capture via SetWindowDisplayAffinity.
Red + white theme to match the WWRECORDER brand.
"""

import ctypes
import os
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional

from PyQt6.QtWidgets import (
    QApplication, QWidget, QLabel, QPushButton, QToolButton,
    QHBoxLayout, QVBoxLayout, QScrollArea, QLineEdit,
    QMessageBox, QSizePolicy, QFileDialog, QCheckBox,
    QFrame, QComboBox,
)
from PyQt6.QtCore import (
    Qt, QRect, QPoint, QSize, QTimer, QMimeData, QUrl,
    pyqtSignal, QPropertyAnimation, QEasingCurve,
    QRunnable, QThreadPool, QObject,
)
from PyQt6.QtGui import (
    QPainter, QColor, QBrush, QPen, QFont,
    QPainterPath, QIcon, QDrag, QPixmap, QCursor, QImage,
)

import subprocess

# ── Windows API ────────────────────────────────────────────────────────────────
WDA_EXCLUDEFROMCAPTURE = 0x00000011
_user32 = ctypes.windll.user32 if sys.platform == "win32" else None


def _exclude_from_capture(hwnd: int) -> None:
    if _user32:
        try:
            _user32.SetWindowDisplayAffinity(ctypes.c_void_p(hwnd), WDA_EXCLUDEFROMCAPTURE)
        except Exception as exc:
            print(f"[Dock] SetWindowDisplayAffinity failed: {exc}")


def _asset(filename: str) -> str:
    base_dir = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_dir, 'icons', filename)


# ── Theme ─────────────────────────────────────────────────────────────────────
CLR_BG      = QColor(18, 18, 20, 250)
CLR_SURFACE = QColor(30, 30, 32)
CLR_CARD    = QColor(38, 38, 40)
CLR_BORDER  = QColor(55, 55, 58)
CLR_RED     = QColor(220, 38, 38)
CLR_RED_HVR = QColor(239, 68, 68)


# ─────────────────────────────────────────────────────────────────────────────
#  Red Toggle Switch
# ─────────────────────────────────────────────────────────────────────────────

class _RedToggle(QCheckBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(40, 22)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        bg = QColor("#DC2626") if self.isChecked() else QColor("#39393D")
        p.setBrush(bg)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(0, 0, self.width(), self.height(), 11, 11)
        p.setBrush(QColor("#FFFFFF"))
        if self.isChecked():
            p.drawEllipse(self.width() - 20, 2, 18, 18)
        else:
            p.drawEllipse(2, 2, 18, 18)
        p.end()

    def hitButton(self, pos):
        return self.rect().contains(pos)


# ─────────────────────────────────────────────────────────────────────────────
#  Hotkey Input (reused from ui_elements style, red themed)
# ─────────────────────────────────────────────────────────────────────────────

class _HotkeyInput(QFrame):
    textChanged = pyqtSignal(str)

    def __init__(self, default=""):
        super().__init__()
        self._text = default
        self._listening = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(36)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(10, 0, 10, 0)
        self.layout.setSpacing(6)
        
        self._prompt = QLabel("Listening... (Press Esc to cancel)")
        self._prompt.setStyleSheet("color: rgba(255,255,255,0.7); font-size: 13px; font-family: 'Segoe UI';")
        self._prompt.hide()
        self.layout.addWidget(self._prompt)
        
        self._keys_container = QWidget()
        self._keys_layout = QHBoxLayout(self._keys_container)
        self._keys_layout.setContentsMargins(0, 0, 0, 0)
        self._keys_layout.setSpacing(4)
        self._keys_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self.layout.addWidget(self._keys_container)
        self.layout.addStretch()

        self._update_style()
        self.setText(default)

    def _update_style(self):
        if self._listening:
            self.setStyleSheet("""
                _HotkeyInput { background: #DC2626; border: 1px solid #EF4444; border-radius: 6px; }
            """)
        else:
            self.setStyleSheet("""
                _HotkeyInput { background: #1C1C1E; border: 1px solid #3C3C3E; border-radius: 6px; }
                _HotkeyInput:hover { border: 1px solid #5C5C5E; }
            """)

    def text(self):
        return self._text

    def setText(self, txt):
        if self._text != txt:
            self._text = txt
            self.textChanged.emit(txt)
        
        while self._keys_layout.count():
            item = self._keys_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
                
        if not txt:
            self._prompt.setText("Click to set shortcut")
            self._prompt.show()
            self._keys_container.hide()
            return
            
        self._prompt.hide()
        self._keys_container.show()
        
        keys = txt.replace('<', '').replace('>', '').split('+')
        for k in keys:
            if not k:
                continue
            lbl = QLabel(k.title())
            lbl.setFixedHeight(22)
            lbl.setStyleSheet("""
                background: #2D2D30; color: #FFFFFF; border: 1px solid #4D4D50;
                border-radius: 4px; padding: 0 6px; font-size: 11px; font-weight: 600; font-family: 'Segoe UI';
            """)
            self._keys_layout.addWidget(lbl)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._listening = True
            self._keys_container.hide()
            self._prompt.setText("Listening... (Press Esc to cancel)")
            self._prompt.show()
            self._update_style()
            self.setFocus()

    def keyPressEvent(self, e):
        if not self._listening:
            return
        
        k = e.key()
        if k == Qt.Key.Key_Escape:
            self._listening = False
            self.setText(self._text)
            self._update_style()
            return

        mods = []
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            mods.append("<ctrl>")
        if e.modifiers() & Qt.KeyboardModifier.AltModifier:
            mods.append("<alt>")
        if e.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            mods.append("<shift>")
            
        if k in (Qt.Key.Key_Control, Qt.Key.Key_Shift, Qt.Key.Key_Alt, Qt.Key.Key_Meta):
            return
            
        ks = ""
        if Qt.Key.Key_A <= k <= Qt.Key.Key_Z:
            ks = chr(k).lower()
        elif Qt.Key.Key_0 <= k <= Qt.Key.Key_9:
            ks = chr(k)
        else:
            map_k = {
                Qt.Key.Key_Return: "<enter>", Qt.Key.Key_Space: "<space>", Qt.Key.Key_Backspace: "<backspace>",
                Qt.Key.Key_Home: "<home>", Qt.Key.Key_End: "<end>", Qt.Key.Key_Insert: "<insert>",
                Qt.Key.Key_Delete: "<delete>", Qt.Key.Key_PageUp: "<page_up>", Qt.Key.Key_PageDown: "<page_down>",
                Qt.Key.Key_Up: "<up>", Qt.Key.Key_Down: "<down>", Qt.Key.Key_Left: "<left>", Qt.Key.Key_Right: "<right>",
                Qt.Key.Key_Print: "<print_screen>", Qt.Key.Key_SysReq: "<print_screen>",
                Qt.Key.Key_Escape: "<esc>", Qt.Key.Key_Tab: "<tab>",
            }
            if k in map_k:
                ks = map_k[k]
            elif Qt.Key.Key_F1 <= k <= Qt.Key.Key_F12:
                ks = f"<f{k - Qt.Key.Key_F1 + 1}>"
                
        if ks:
            mods.append(ks)
            self._listening = False
            self.setText("+".join(mods))
            self._update_style()
            
    def focusOutEvent(self, e):
        if self._listening:
            self._listening = False
            self.setText(self._text)
            self._update_style()
        super().focusOutEvent(e)


# ─────────────────────────────────────────────────────────────────────────────
#  _ShareWidget
# ─────────────────────────────────────────────────────────────────────────────

class _ShareWidget(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(36)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._url = "https://akasumitlamba.github.io/WWRecorder/"
        self._setup_normal_style()
        
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 0, 10, 0)
        lay.setSpacing(4)
        
        self._lbl = QLabel(self._url)
        self._lbl.setStyleSheet("color: #DC2626; font-size: 11px; font-family: 'Segoe UI'; border: none; background: transparent;")
        lay.addWidget(self._lbl, 1)
        
        self._ico = QLabel()
        pm = QPixmap(_asset("copy.png"))
        if not pm.isNull():
            self._ico.setPixmap(pm.scaled(14, 14, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        else:
            self._ico.setText("📋")
            self._ico.setStyleSheet("color: rgba(255,255,255,0.4); font-size: 14px; border: none; background: transparent;")
        lay.addWidget(self._ico)

    def _setup_normal_style(self):
        self.setStyleSheet("""
            _ShareWidget {
                background: #1C1C1E; border: 1px solid #3C3C3E; border-radius: 6px;
            }
            _ShareWidget:hover { background: #262628; border: 1px solid #5C5C5E; }
        """)
        
    def mousePressEvent(self, e):
        QApplication.clipboard().setText(self._url)
        self._lbl.setText("Copied to clipboard!")
        self._lbl.setStyleSheet("color: #22C55E; font-size: 11px; font-weight: 600; font-family: 'Segoe UI'; border: none; background: transparent;")
        self.setStyleSheet("""
            _ShareWidget {
                background: rgba(34, 197, 94, 0.1); border: 1px solid rgba(34, 197, 94, 0.3); border-radius: 6px;
            }
        """)
        QTimer.singleShot(1500, self._restore)
        super().mousePressEvent(e)
        
    def _restore(self):
        self._lbl.setText(self._url)
        self._lbl.setStyleSheet("color: #DC2626; font-size: 11px; font-family: 'Segoe UI'; border: none; background: transparent;")
        self._setup_normal_style()


# ─────────────────────────────────────────────────────────────────────────────
#  DockWidget — Clean 4-button dock
# ─────────────────────────────────────────────────────────────────────────────

class DockWidget(QWidget):
    """
    Small grabber on screen edge → hovers to reveal 4 action buttons.
    """

    screenshot_requested = pyqtSignal()
    record_requested     = pyqtSignal()
    files_requested      = pyqtSignal()
    settings_requested   = pyqtSignal()

    GRABBER_W = 12
    GRABBER_H = 48

    EXPANDED_W = 44
    EXPANDED_H = 160

    def __init__(self, engine, config: dict, parent=None):
        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        super().__init__(None, flags)

        self._engine = engine
        self._config = config.copy()
        self._expanded = False
        self._is_recording = False
        self._drag_pos: Optional[QPoint] = None
        self._is_dragging = False
        self._edge = config.get("dock_edge", "right")
        self._dock_y = config.get("dock_y", -1)

        self._collapse_timer = QTimer(self)
        self._collapse_timer.setSingleShot(True)
        self._collapse_timer.setInterval(400)
        self._collapse_timer.timeout.connect(self._collapse)

        self._pulse_visible = True
        self._pulse_timer = QTimer(self)
        self._pulse_timer.setInterval(600)
        self._pulse_timer.timeout.connect(self._pulse_tick)

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setMouseTracking(True)

        self._build_panel()
        self._position_on_edge()

        self._topmost_timer = QTimer(self)
        self._topmost_timer.timeout.connect(self._enforce_topmost)
        self._topmost_timer.start(2000)

        QTimer.singleShot(150, self._apply_exclusion)

    def _enforce_topmost(self):
        if self.isVisible():
            if _user32:
                HWND_TOPMOST = -1
                SWP_NOSIZE = 0x0001
                SWP_NOMOVE = 0x0002
                SWP_NOACTIVATE = 0x0010
                _user32.SetWindowPos(int(self.winId()), HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
            self.raise_()

    def _apply_exclusion(self):
        _exclude_from_capture(int(self.winId()))

    def _build_panel(self):
        self._panel = QWidget(self)
        self._panel.setVisible(False)
        self._panel.setMouseTracking(True)

        layout = QVBoxLayout(self._panel)
        layout.setContentsMargins(4, 8, 4, 8)
        layout.setSpacing(4)

        hk_ss = self._config.get("hotkey_screenshot", "<ctrl>+<alt>+c").replace("<", "").replace(">", "").title()
        self._btn_screenshot = self._make_btn("screenshot.png", f"Screenshot ({hk_ss})")
        self._btn_screenshot.clicked.connect(self.screenshot_requested.emit)
        layout.addWidget(self._btn_screenshot)

        hk_rec = self._config.get("hotkey", "<shift>+<backspace>").replace("<", "").replace(">", "").title()
        self._btn_record = self._make_btn("record.png", f"Start / Stop Recording ({hk_rec})")
        self._btn_record.clicked.connect(self.record_requested.emit)
        layout.addWidget(self._btn_record)

        self._btn_files = self._make_btn("folder.png", "Recent Files")
        self._btn_files.clicked.connect(self.files_requested.emit)
        layout.addWidget(self._btn_files)

        self._btn_settings = self._make_btn("settings.png", "Settings")
        self._btn_settings.clicked.connect(self.settings_requested.emit)
        layout.addWidget(self._btn_settings)

        self._panel.adjustSize()

    def _make_btn(self, icon_file: str, tooltip: str) -> QToolButton:
        icon_path = _asset(icon_file)

        class TintingToolButton(QToolButton):
            def __init__(self, tooltip):
                super().__init__()
                self.setToolTip(tooltip)
                self.setIconSize(QSize(16, 16))
                self.setFixedSize(30, 30)
                self.setCursor(Qt.CursorShape.PointingHandCursor)
                self.setMouseTracking(True)
                
                self.icon_normal = QIcon()
                self.icon_hover = QIcon()
                
                if os.path.isfile(icon_path):
                    pm = QPixmap(icon_path)
                    self.icon_normal = QIcon(pm)
                    
                    pm_white = QPixmap(pm.size())
                    pm_white.fill(Qt.GlobalColor.transparent)
                    p = QPainter(pm_white)
                    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
                    p.drawPixmap(0, 0, pm)
                    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
                    p.fillRect(pm_white.rect(), QColor(255, 255, 255))
                    p.end()
                    self.icon_hover = QIcon(pm_white)
                    
                    self.setIcon(self.icon_normal)
                    
            def enterEvent(self, e):
                if not self.icon_hover.isNull():
                    self.setIcon(self.icon_hover)
                super().enterEvent(e)
                
            def leaveEvent(self, e):
                if not self.icon_normal.isNull():
                    self.setIcon(self.icon_normal)
                super().leaveEvent(e)

        btn = TintingToolButton(tooltip)

        btn.setStyleSheet("""
            QToolButton {
                background: #262628;
                border: 1px solid #3A3A3C;
                border-radius: 7px;
            }
            QToolButton:hover {
                background: #DC2626;
                border: 1px solid #EF4444;
            }
            QToolButton:pressed {
                background: #B91C1C;
            }
        """)
        return btn

    def update_config(self, config: dict):
        self._config = config.copy()
        self._edge = self._config.get("dock_edge", "right")
        hk_ss = self._config.get("hotkey_screenshot", "<ctrl>+<alt>+c").replace("<", "").replace(">", "").title()
        hk_rec = self._config.get("hotkey", "<shift>+<backspace>").replace("<", "").replace(">", "").title()
        if hasattr(self, '_btn_screenshot'):
            self._btn_screenshot.setToolTip(f"Screenshot ({hk_ss})")
        if hasattr(self, '_btn_record'):
            self._btn_record.setToolTip(f"Start / Stop Recording ({hk_rec})")

    # ── Geometry ─────────────────────────────────────────────────────────────

    def _screen_geo(self) -> QRect:
        s = self.screen()
        if not s:
            s = QApplication.primaryScreen()
        return s.availableGeometry() if s else QRect(0, 0, 1920, 1080)

    def _position_on_edge(self):
        sg = self._screen_geo()
        if self._dock_y < 0:
            self._dock_y = sg.center().y() - self.GRABBER_H // 2
        self._dock_y = max(sg.top(), min(self._dock_y, sg.bottom() - self.GRABBER_H))
        self._set_collapsed_geo()

    def _stop_animations(self):
        if hasattr(self, '_collapse_anim') and self._collapse_anim.state() == QPropertyAnimation.State.Running:
            self._collapse_anim.stop()
        if hasattr(self, '_expand_anim') and self._expand_anim.state() == QPropertyAnimation.State.Running:
            self._expand_anim.stop()

    def _set_collapsed_geo(self, animate=True):
        self._stop_animations()
        sg = self._screen_geo()
        x = sg.left() if self._edge == "left" else sg.right() - self.GRABBER_W
        end_rect = QRect(x, self._dock_y, self.GRABBER_W, self.GRABBER_H)
        
        self._expanded = False
        
        if animate and self.isVisible():
            self._collapse_anim = QPropertyAnimation(self, b"geometry")
            self._collapse_anim.setDuration(250)
            self._collapse_anim.setStartValue(self.geometry())
            self._collapse_anim.setEndValue(end_rect)
            self._collapse_anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
            self._collapse_anim.finished.connect(self._on_collapse_finished)
            self._collapse_anim.start()
        else:
            self.setGeometry(end_rect)
            self._panel.setVisible(False)

    def _on_collapse_finished(self):
        if not self._expanded:
            self._panel.setVisible(False)

    def _set_expanded_geo(self, animate=True):
        self._stop_animations()
        sg = self._screen_geo()
        w = self.EXPANDED_W
        h = self.EXPANDED_H

        if self._edge == "left":
            x = sg.left()
        else:
            x = sg.right() - w

        center_y = self._dock_y + self.GRABBER_H // 2
        y = center_y - h // 2
        y = max(sg.top(), min(y, sg.bottom() - h))

        end_rect = QRect(x, y, w, h)
        self._expanded = True
        self._panel.setGeometry(0, 0, w, h)
        self._panel.setVisible(True)

        if animate and self.isVisible():
            self._expand_anim = QPropertyAnimation(self, b"geometry")
            self._expand_anim.setDuration(300)
            self._expand_anim.setStartValue(self.geometry())
            self._expand_anim.setEndValue(end_rect)
            self._expand_anim.setEasingCurve(QEasingCurve.Type.OutBack)
            self._expand_anim.start()
        else:
            self.setGeometry(end_rect)

    # ── Expand / Collapse ────────────────────────────────────────────────────

    def _expand(self):
        if self._expanded or self._is_dragging:
            return
        self._collapse_timer.stop()
        self._set_expanded_geo()

    def _collapse(self):
        if not self._expanded:
            return
        self._set_collapsed_geo()

    # ── Mouse events ─────────────────────────────────────────────────────────

    def enterEvent(self, event):
        self._collapse_timer.stop()
        if not self._expanded and not self._is_dragging:
            self._expand()
        super().enterEvent(event)

    def leaveEvent(self, event):
        if self._expanded:
            self._collapse_timer.start()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint()
            self._drag_start_y = self._dock_y
            self._is_dragging = False

    def mouseMoveEvent(self, event):
        if self._drag_pos and (event.buttons() & Qt.MouseButton.LeftButton):
            delta = event.globalPosition().toPoint() - self._drag_pos
            if abs(delta.y()) > 8 or abs(delta.x()) > 8 or self._is_dragging:
                if not self._is_dragging:
                    self._is_dragging = True
                    self._expanded = False
                    self._panel.setVisible(False)
                    self._stop_animations()
                
                sg = self._screen_geo()
                new_y = self._drag_start_y + delta.y()
                self._dock_y = max(sg.top(), min(new_y, sg.bottom() - self.GRABBER_H))
                
                # Instantly move without animating during drag
                self._set_collapsed_geo(animate=False)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self._is_dragging:
                sg = self._screen_geo()
                gpos = event.globalPosition().toPoint()
                self._edge = "left" if gpos.x() < sg.left() + sg.width() // 2 else "right"
                self._set_collapsed_geo()
                self._save_dock_position()
            self._drag_pos = None
            self._is_dragging = False

    def _save_dock_position(self):
        self._config["dock_edge"] = self._edge
        self._config["dock_y"] = self._dock_y

    # ── Paint ────────────────────────────────────────────────────────────────

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        if self._expanded:
            path = QPainterPath()
            r = self.rect().adjusted(1, 1, -1, -1)
            path.addRoundedRect(float(r.x()), float(r.y()), float(r.width()), float(r.height()), 10.0, 10.0)
            p.fillPath(path, QBrush(QColor(18, 18, 20)))

            # Red accent on docked edge
            aw = 2
            if self._edge == "left":
                p.fillRect(0, 12, aw, self.height() - 24, QBrush(CLR_RED))
            else:
                p.fillRect(self.width() - aw, 12, aw, self.height() - 24, QBrush(CLR_RED))

            p.setPen(QPen(CLR_BORDER, 1.0))
            p.drawPath(path)
        else:
            # Collapsed grabber — round outer corners only
            gp = QPainterPath()
            if self._edge == "left":
                gp.moveTo(0, 0)
                gp.lineTo(float(self.GRABBER_W - 5), 0)
                gp.arcTo(float(self.GRABBER_W - 10), 0, 10, 10, 90, -90)
                gp.lineTo(float(self.GRABBER_W), float(self.GRABBER_H - 5))
                gp.arcTo(float(self.GRABBER_W - 10), float(self.GRABBER_H - 10), 10, 10, 0, -90)
                gp.lineTo(0, float(self.GRABBER_H))
                gp.closeSubpath()
            else:
                gp.moveTo(float(self.GRABBER_W), 0)
                gp.lineTo(5.0, 0)
                gp.arcTo(0, 0, 10, 10, 90, 90)
                gp.lineTo(0, float(self.GRABBER_H - 5))
                gp.arcTo(0, float(self.GRABBER_H - 10), 10, 10, 180, 90)
                gp.lineTo(float(self.GRABBER_W), float(self.GRABBER_H))
                gp.closeSubpath()

            p.fillPath(gp, QBrush(QColor(30, 30, 32, 220)))

            # 3 grab lines
            p.setPen(QPen(QColor(200, 200, 200, 160), 1.5))
            cx = self.GRABBER_W // 2
            cy = self.GRABBER_H // 2
            for dy in [-7, 0, 7]:
                p.drawLine(cx - 3, cy + dy, cx + 3, cy + dy)

            # Red dots (top and bottom)
            if self._is_recording:
                if self._pulse_visible:
                    p.setBrush(QColor(255, 59, 48))
                    p.setPen(Qt.PenStyle.NoPen)
                    p.drawEllipse(cx - 3, 5, 6, 6)
                    p.drawEllipse(cx - 3, self.GRABBER_H - 11, 6, 6)
            else:
                p.setBrush(CLR_RED)
                p.setPen(Qt.PenStyle.NoPen)
                p.drawEllipse(cx - 2, 6, 4, 4)
                p.drawEllipse(cx - 2, self.GRABBER_H - 10, 4, 4)

        p.end()

    # ── Recording state ──────────────────────────────────────────────────────

    def set_recording_state(self, is_recording: bool):
        self._is_recording = is_recording
        if is_recording:
            self._btn_record.setToolTip("Stop Recording")
            stop_ico = _asset("stop.png")
            if os.path.isfile(stop_ico):
                self._btn_record.setIcon(QIcon(stop_ico))
            self._btn_record.setStyleSheet("""
                QToolButton { background: #DC2626; border: 1px solid #EF4444; border-radius: 7px; }
                QToolButton:hover { background: #B91C1C; }
            """)
            self._pulse_timer.start()
        else:
            self._btn_record.setToolTip("Record")
            rec_ico = _asset("record.png")
            if os.path.isfile(rec_ico):
                self._btn_record.setIcon(QIcon(rec_ico))
            self._btn_record.setStyleSheet("""
                QToolButton { background: #262628; border: 1px solid #3A3A3C; border-radius: 7px; }
                QToolButton:hover { background: #DC2626; border: 1px solid #EF4444; }
                QToolButton:pressed { background: #B91C1C; }
            """)
            self._pulse_timer.stop()
            self._pulse_visible = True
        self.update()

    def _pulse_tick(self):
        self._pulse_visible = not self._pulse_visible
        self.update()


# ─────────────────────────────────────────────────────────────────────────────
#  SidebarPanel (base)
# ─────────────────────────────────────────────────────────────────────────────

class SidebarPanel(QWidget):
    """
    Full-screen-height sidebar with WWRECORDER heading PNG,
    resizable width, capture-invisible.
    """

    closed = pyqtSignal()
    width_changed = pyqtSignal(int)

    MIN_WIDTH = 340
    DEFAULT_WIDTH = 380
    MAX_WIDTH = 600

    def __init__(self, edge: str = "right", parent=None):
        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        super().__init__(None, flags)

        self._edge = edge
        self._resizing = False
        self._resize_start_x = 0
        self._resize_start_w = 0

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setMouseTracking(True)
        self.setMinimumWidth(self.MIN_WIDTH)
        self.setMaximumWidth(self.MAX_WIDTH)

        QTimer.singleShot(150, self._apply_exclusion)

    def _apply_exclusion(self):
        _exclude_from_capture(int(self.winId()))

    def _position_sidebar(self, width: int = 0):
        sg = QApplication.primaryScreen().availableGeometry()
        w = width or self.DEFAULT_WIDTH
        h = sg.height()

        # Flush to the screen edge
        if self._edge == "left":
            x = sg.left()
        else:
            x = sg.right() - w

        y = sg.top()
        self.setFixedHeight(h)
        self.resize(w, h)
        self.move(x, y)

    def _build_heading(self, parent_layout: QVBoxLayout, extra_buttons: list = None):
        """Add the WWRECORDER heading image from icons folder."""
        heading_container = QWidget()
        heading_layout = QHBoxLayout(heading_container)
        heading_layout.setContentsMargins(0, 4, 0, 4)
        heading_layout.setSpacing(10)

        # Try to load the WWRECORDER PNG
        heading_path = _asset("wwrecorder.png")
        if os.path.isfile(heading_path):
            img_label = QLabel()
            px = QPixmap(heading_path)
            scaled = px.scaledToHeight(26, Qt.TransformationMode.SmoothTransformation)
            img_label.setPixmap(scaled)
            heading_layout.addWidget(img_label)
        else:
            lbl_ww = QLabel("WW")
            lbl_ww.setStyleSheet("color: #FFFFFF; font-size: 18px; font-weight: 900; font-family: 'Segoe UI Black', 'Impact';")
            heading_layout.addWidget(lbl_ww)
            lbl_r = QLabel("R")
            lbl_r.setStyleSheet("color: #DC2626; font-size: 18px; font-weight: 900; font-family: 'Segoe UI Black', 'Impact';")
            heading_layout.addWidget(lbl_r)
            lbl_rest = QLabel("ECORDER")
            lbl_rest.setStyleSheet("color: #FFFFFF; font-size: 18px; font-weight: 900; font-family: 'Segoe UI Black', 'Impact';")
            heading_layout.addWidget(lbl_rest)

        heading_layout.addStretch()

        # Optional extra buttons (e.g. settings gear in recent files)
        if extra_buttons:
            for btn in extra_buttons:
                heading_layout.addWidget(btn)

        # Close button
        btn_close = QPushButton("✕")
        btn_close.setFixedSize(26, 26)
        btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_close.setStyleSheet("""
            QPushButton {
                background: #262628; color: rgba(255,255,255,0.6); border: 1px solid #3C3C3E;
                border-radius: 13px; font-size: 11px; font-weight: 600;
            }
            QPushButton:hover { background: #DC2626; color: #FFFFFF; border-color: #EF4444; }
        """)
        btn_close.clicked.connect(self.close_panel)
        heading_layout.addWidget(btn_close)

        parent_layout.addWidget(heading_container)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background-color: #3C3C3E; max-height: 1px; border: none;")
        parent_layout.addWidget(sep)
        parent_layout.addSpacing(8)

    def open_panel(self):
        sg = QApplication.primaryScreen().availableGeometry()
        w = self.width() if self.width() >= self.MIN_WIDTH else self.DEFAULT_WIDTH
        h = sg.height()
        y = sg.top()

        if self._edge == "left":
            start_x = sg.left() - w
            end_x = sg.left()
        else:
            start_x = sg.right()
            end_x = sg.right() - w

        self.setGeometry(start_x, y, w, h)
        self.show()

        self._anim = QPropertyAnimation(self, b"geometry")
        self._anim.setDuration(350)
        self._anim.setStartValue(QRect(start_x, y, w, h))
        self._anim.setEndValue(QRect(end_x, y, w, h))
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.start()

    def close_panel(self):
        if not self.isVisible():
            return
        
        sg = QApplication.primaryScreen().availableGeometry()
        w = self.width()
        h = sg.height()
        y = sg.top()
        
        if self._edge == "left":
            start_x = sg.left()
            end_x = sg.left() - w
        else:
            start_x = sg.right() - w
            end_x = sg.right()

        self._anim = QPropertyAnimation(self, b"geometry")
        self._anim.setDuration(300)
        self._anim.setStartValue(QRect(start_x, y, w, h))
        self._anim.setEndValue(QRect(end_x, y, w, h))
        self._anim.setEasingCurve(QEasingCurve.Type.InCubic)
        self._anim.finished.connect(self._finish_close)
        self._anim.start()

    def _finish_close(self):
        self.hide()
        self.closed.emit()

    # ── Resize by dragging inner edge ────────────────────────────────────────

    def _is_on_resize_edge(self, pos: QPoint) -> bool:
        margin = 6
        if self._edge == "right":
            return pos.x() <= margin
        else:
            return pos.x() >= self.width() - margin

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._is_on_resize_edge(event.pos()):
            self._resizing = True
            self._resize_start_x = event.globalPosition().toPoint().x()
            self._resize_start_w = self.width()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._resizing:
            dx = event.globalPosition().toPoint().x() - self._resize_start_x
            if self._edge == "right":
                new_w = self._resize_start_w - dx
            else:
                new_w = self._resize_start_w + dx
            new_w = max(self.MIN_WIDTH, min(new_w, self.MAX_WIDTH))
            self._position_sidebar(new_w)
            event.accept()
        elif self._is_on_resize_edge(event.pos()):
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._resizing:
            self._resizing = False
            self.width_changed.emit(self.width())
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    # ── Paint ────────────────────────────────────────────────────────────────

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        r = self.rect().adjusted(0, 0, 0, 0)

        # Only round corners on the inner edge (away from screen edge)
        if self._edge == "right":
            # Round left corners only
            path.moveTo(float(r.right()), float(r.top()))
            path.lineTo(float(r.left() + 12), float(r.top()))
            path.arcTo(float(r.left()), float(r.top()), 24, 24, 90, 90)
            path.lineTo(float(r.left()), float(r.bottom() - 12))
            path.arcTo(float(r.left()), float(r.bottom() - 24), 24, 24, 180, 90)
            path.lineTo(float(r.right()), float(r.bottom()))
            path.closeSubpath()
        else:
            # Round right corners only
            path.moveTo(float(r.left()), float(r.top()))
            path.lineTo(float(r.right() - 12), float(r.top()))
            path.arcTo(float(r.right() - 24), float(r.top()), 24, 24, 90, -90)
            path.lineTo(float(r.right()), float(r.bottom() - 12))
            path.arcTo(float(r.right() - 24), float(r.bottom() - 24), 24, 24, 0, -90)
            path.lineTo(float(r.left()), float(r.bottom()))
            path.closeSubpath()

        p.fillPath(path, QBrush(QColor(18, 18, 20, 220)))
        p.setPen(QPen(CLR_BORDER, 1.0))
        p.drawPath(path)
        p.end()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close_panel()


# ─────────────────────────────────────────────────────────────────────────────
#  Settings UI Helpers
# ─────────────────────────────────────────────────────────────────────────────

class _SegmentedToggle(QWidget):
    valueChanged = pyqtSignal(str)
    
    def __init__(self, options: list[str], current: str):
        super().__init__()
        self._options = options
        self._current = current
        self._buttons = {}
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        for i, opt in enumerate(options):
            b = QPushButton(opt)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setFixedHeight(24)
            b.setFixedWidth(60)
            b.clicked.connect(lambda checked, o=opt: self._set_value(o))
            self._buttons[opt] = b
            layout.addWidget(b)
            
        self._update_styles()
        
    def _set_value(self, val):
        if val != self._current:
            self._current = val
            self._update_styles()
            self.valueChanged.emit(val)
            
    def value(self) -> str:
        return self._current
        
    def setValue(self, val: str):
        if val in self._options:
            self._current = val
            self._update_styles()
            
    def _update_styles(self):
        opts = list(self._options)
        for i, opt in enumerate(opts):
            b = self._buttons[opt]
            rad = "4px 0 0 4px" if i == 0 else "0 4px 4px 0"
            if opt == self._current:
                b.setStyleSheet(f"""
                    QPushButton {{
                        background: #DC2626; color: #FFFFFF; font-weight: bold; font-family: 'Segoe UI'; font-size: 11px;
                        border: 1px solid #DC2626; border-radius: {rad};
                    }}
                """)
            else:
                b.setStyleSheet(f"""
                    QPushButton {{
                        background: #1C1C1E; color: rgba(255,255,255,0.6); font-family: 'Segoe UI'; font-size: 11px;
                        border: 1px solid #3C3C3E; border-radius: {rad};
                    }}
                    QPushButton:hover {{ background: #2D2D30; color: #FFFFFF; }}
                """)

# ─────────────────────────────────────────────────────────────────────────────
#  SettingsSidebar
# ─────────────────────────────────────────────────────────────────────────────

class SettingsSidebar(SidebarPanel):
    """Full settings panel in a sidebar, matching the old SettingsWindow features."""

    settings_saved = pyqtSignal(dict)
    files_requested = pyqtSignal()
    quit_requested = pyqtSignal()

    def __init__(self, config: dict, default_config: dict = None, edge: str = "right"):
        super().__init__(edge)
        self._config = config.copy()
        self._default_config = default_config or {}
        self._build_ui()
        self._position_sidebar()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(0)

        # Recent files folder button for heading bar
        btn_files = QPushButton()
        btn_files.setToolTip("Recent Files")
        btn_files.setFixedSize(26, 26)
        btn_files.setCursor(Qt.CursorShape.PointingHandCursor)
        files_ico = _asset("folder.png")
        if os.path.isfile(files_ico):
            btn_files.setIcon(QIcon(files_ico))
            btn_files.setIconSize(QSize(14, 14))
        btn_files.setStyleSheet("""
            QPushButton {
                background: #262628; border: 1px solid #3C3C3E;
                border-radius: 13px;
            }
            QPushButton:hover { background: #DC2626; border-color: #EF4444; }
        """)
        btn_files.clicked.connect(self.files_requested.emit)

        self._build_heading(root, extra_buttons=[btn_files])

        # Scrollable content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("""
            QScrollArea { background: transparent; border: none; }
            QScrollBar:vertical { background: transparent; width: 5px; }
            QScrollBar::handle:vertical { background: rgba(220,38,38,0.4); border-radius: 2px; min-height: 20px; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
        """)

        content = QWidget()
        content.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(content)
        lay.setContentsMargins(0, 0, 6, 0)
        lay.setSpacing(16)

        # ── Recording Output ─────────────────────────────────────────────────
        self._add_section_title(lay, "RECORDING OUTPUT")
        folder_row = QHBoxLayout()
        folder_row.setSpacing(8)
        self._edt_folder = QLineEdit(self._config.get("output_folder", ""))
        self._edt_folder.setReadOnly(True)
        self._edt_folder.setMinimumHeight(36)
        self._edt_folder.setStyleSheet("""
            QLineEdit {
                background: #1C1C1E; border: 1px solid #3C3C3E; border-radius: 6px;
                padding: 0 10px; color: #FFFFFF; font-size: 12px; font-family: 'Segoe UI';
            }
        """)
        folder_row.addWidget(self._edt_folder)

        btn_browse = QPushButton("Browse")
        btn_browse.setFixedSize(70, 36)
        btn_browse.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_browse.setStyleSheet("""
            QPushButton {
                background: #262628; color: #FFFFFF; border: 1px solid #3C3C3E;
                border-radius: 6px; font-size: 12px; font-weight: 600;
            }
            QPushButton:hover { background: #DC2626; border-color: #EF4444; }
        """)
        btn_browse.clicked.connect(self._browse)
        folder_row.addWidget(btn_browse)
        lay.addLayout(folder_row)

        # ── Hotkeys ─────────────────────────────────────────────────────────
        self._add_section_title(lay, "HOTKEYS")
        lbl_hk = QLabel("Click below, then press your desired shortcut:")
        lbl_hk.setStyleSheet("color: rgba(255,255,255,0.6); font-size: 11px; font-family: 'Segoe UI';")
        lay.addWidget(lbl_hk)

        hk_row2 = QHBoxLayout()
        lbl_s = QLabel("Screenshot:")
        lbl_s.setFixedWidth(70)
        lbl_s.setStyleSheet("color: #FFFFFF; font-size: 12px; font-family: 'Segoe UI';")
        hk_row2.addWidget(lbl_s)
        self._edt_screenshot = _HotkeyInput(self._config.get("hotkey_screenshot", "<ctrl>+<alt>+c"))
        hk_row2.addWidget(self._edt_screenshot, 1)
        lay.addLayout(hk_row2)

        hk_row = QHBoxLayout()
        lbl_r = QLabel("Recording:")
        lbl_r.setFixedWidth(70)
        lbl_r.setStyleSheet("color: #FFFFFF; font-size: 12px; font-family: 'Segoe UI';")
        hk_row.addWidget(lbl_r)
        self._edt_hotkey = _HotkeyInput(self._config.get("hotkey", "<shift>+<backspace>"))
        hk_row.addWidget(self._edt_hotkey, 1)
        lay.addLayout(hk_row)

        # ── Default Behavior ─────────────────────────────────────────────────
        self._add_section_title(lay, "DEFAULT BEHAVIOR")
        self._chk_sys = self._add_toggle(lay, "Record system audio by default", self._config.get("default_system_audio", True))
        self._chk_mic = self._add_toggle(lay, "Record microphone by default", self._config.get("default_mic", False))
        self._chk_boot = self._add_toggle(lay, "Start WWRecorder with Windows", self._config.get("start_on_boot", False))
        self._chk_clip = self._add_toggle(lay, "Auto-copy captures to clipboard", self._config.get("copy_to_clipboard", True))

        # ── Appearance ───────────────────────────────────────────────────────
        self._add_section_title(lay, "APPEARANCE")
        row_app = QHBoxLayout()
        row_app.setContentsMargins(0, 0, 0, 0)
        lbl_app = QLabel("UI Font Size")
        lbl_app.setStyleSheet("color: rgba(255,255,255,0.85); font-size: 12px; font-family: 'Segoe UI';")
        row_app.addWidget(lbl_app, 1)

        self._seg_font = _SegmentedToggle(["Default", "Large"], self._config.get("font_size", "Default"))
        self._seg_font.valueChanged.connect(self._check_dirty)
        row_app.addWidget(self._seg_font)
        lay.addLayout(row_app)

        # ── Share ────────────────────────────────────────────────────────────
        self._add_section_title(lay, "SHARE APP")
        self._share_widget = _ShareWidget()
        lay.addWidget(self._share_widget)

        lay.addStretch()

        # ── Quit & Save ──────────────────────────────────────────────────────
        bot_lay = QVBoxLayout()
        bot_lay.setContentsMargins(0, 0, 0, 0)
        bot_lay.setSpacing(10)

        self._btn_save = QPushButton("Save Settings")
        self._btn_save.setFixedHeight(34)
        self._btn_save.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_save.clicked.connect(self._save)
        bot_lay.addWidget(self._btn_save)

        row2 = QHBoxLayout()
        row2.setContentsMargins(0, 0, 0, 0)
        row2.setSpacing(10)

        self._btn_quit = QPushButton("⏻  Quit App")
        self._btn_quit.setFixedHeight(34)
        self._btn_quit.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_quit.setStyleSheet("""
            QPushButton {
                background: #1C1C1E; border: 1px solid #3C3C3E; border-radius: 6px;
                color: #EF4444; font-size: 12px; font-weight: 600; font-family: 'Segoe UI';
            }
            QPushButton:hover { background: #DC2626; color: #FFFFFF; border-color: #EF4444; }
        """)
        self._btn_quit.clicked.connect(self.quit_requested.emit)
        row2.addWidget(self._btn_quit, 1)

        self._btn_reset = QPushButton("↺  Reset")
        self._btn_reset.setFixedHeight(34)
        self._btn_reset.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_reset.setStyleSheet("""
            QPushButton {
                background: #1C1C1E; border: 1px solid #3C3C3E; border-radius: 6px;
                color: #A0A0A5; font-size: 12px; font-weight: 600; font-family: 'Segoe UI';
                padding-bottom: 2px;
            }
            QPushButton:hover { background: #5C5C5E; color: #FFFFFF; }
        """)
        self._btn_reset.clicked.connect(self._reset)
        row2.addWidget(self._btn_reset, 1)

        bot_lay.addLayout(row2)
        lay.addLayout(bot_lay)

        # Connect signals for dirty checking
        self._edt_folder.textChanged.connect(self._check_dirty)
        self._edt_hotkey.textChanged.connect(self._check_dirty)
        self._edt_screenshot.textChanged.connect(self._check_dirty)
        self._chk_sys.toggled.connect(self._check_dirty)
        self._chk_mic.toggled.connect(self._check_dirty)
        self._chk_boot.toggled.connect(self._check_dirty)
        self._chk_clip.toggled.connect(self._check_dirty)
        self._seg_font.valueChanged.connect(self._check_dirty)
        self._check_dirty()

        # Credit
        credit = QLabel("<a href='https://github.com/akasumitlamba' style='color: #DC2626; text-decoration: none; font-size: 10px; font-weight: 600;'>Made by akasumitlamba</a>")
        credit.setOpenExternalLinks(True)
        credit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addSpacing(6)
        lay.addWidget(credit)

        scroll.setWidget(content)
        root.addWidget(scroll, 1)

    def _check_dirty(self, *_):
        dirty = (
            self._edt_folder.text() != self._config.get("output_folder", "") or
            self._edt_hotkey.text() != self._config.get("hotkey", "") or
            self._edt_screenshot.text() != self._config.get("hotkey_screenshot", "") or
            self._chk_sys.isChecked() != self._config.get("default_system_audio", True) or
            self._chk_mic.isChecked() != self._config.get("default_mic", False) or
            self._chk_boot.isChecked() != self._config.get("start_on_boot", False) or
            self._chk_clip.isChecked() != self._config.get("copy_to_clipboard", True) or
            self._seg_font.value() != self._config.get("font_size", "Default")
        )
        self._btn_save.setEnabled(dirty)
        if dirty:
            self._btn_save.setStyleSheet("""
                QPushButton {
                    background: #DC2626; border: 1px solid #EF4444; border-radius: 6px;
                    color: #FFFFFF; font-size: 13px; font-weight: 600; font-family: 'Segoe UI';
                }
                QPushButton:hover { background: #B91C1C; }
            """)
        else:
            self._btn_save.setStyleSheet("""
                QPushButton {
                    background: #2D2D30; border: 1px solid #3C3C3E; border-radius: 6px;
                    color: rgba(255,255,255,0.4); font-size: 13px; font-weight: 500; font-family: 'Segoe UI';
                }
            """)

    def _add_section_title(self, parent_layout, text: str):
        lbl = QLabel(text)
        lbl.setStyleSheet("color: rgba(255,255,255,0.4); font-size: 10px; font-weight: 700; letter-spacing: 1.5px; font-family: 'Segoe UI';")
        parent_layout.addWidget(lbl)

    def _add_toggle(self, parent_layout, label: str, checked: bool) -> _RedToggle:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        lbl = QLabel(label)
        lbl.setStyleSheet("color: rgba(255,255,255,0.85); font-size: 12px; font-family: 'Segoe UI';")
        row.addWidget(lbl, 1)
        toggle = _RedToggle()
        toggle.setChecked(checked)
        row.addWidget(toggle)
        parent_layout.addLayout(row)
        return toggle

    def _browse(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Output Folder", self._edt_folder.text())
        if folder:
            self._edt_folder.setText(folder)

    def _save(self):
        self._config.update({
            "output_folder":        self._edt_folder.text(),
            "hotkey":               self._edt_hotkey.text(),
            "hotkey_screenshot":    self._edt_screenshot.text(),
            "default_system_audio": self._chk_sys.isChecked(),
            "default_mic":          self._chk_mic.isChecked(),
            "start_on_boot":        self._chk_boot.isChecked(),
            "copy_to_clipboard":    self._chk_clip.isChecked(),
            "font_size":            self._seg_font.value(),
        })
        self.settings_saved.emit(self._config)
        # Update dirty state to reflect saved values (sidebar stays open)
        self._check_dirty()

    def _reset(self):
        if not self._default_config: return
        self._edt_folder.setText(self._default_config.get("output_folder", ""))
        self._edt_hotkey.setText(self._default_config.get("hotkey", ""))
        self._edt_screenshot.setText(self._default_config.get("hotkey_screenshot", ""))
        self._chk_sys.setChecked(self._default_config.get("default_system_audio", True))
        self._chk_mic.setChecked(self._default_config.get("default_mic", False))
        self._chk_boot.setChecked(self._default_config.get("start_on_boot", False))
        self._chk_clip.setChecked(self._default_config.get("copy_to_clipboard", True))
        self._seg_font.setValue(self._default_config.get("font_size", "Default"))

    def get_config(self) -> dict:
        return self._config


# ─────────────────────────────────────────────────────────────────────────────
#  _FileRow + Thumbnail Extraction
# ─────────────────────────────────────────────────────────────────────────────

class _ThumbSignals(QObject):
    loaded = pyqtSignal(bytes)

class _VideoThumbnailTask(QRunnable):
    def __init__(self, filepath: str, signal: pyqtSignal):
        super().__init__()
        self.filepath = filepath
        self.signal = signal

    def run(self):
        try:
            from recorder import get_ffmpeg_path
            ffmpeg = get_ffmpeg_path()
            # Grab a tiny jpeg of the very first frame quickly
            cmd = [
                ffmpeg, "-y", "-v", "quiet", "-ss", "00:00:00.000", "-i", self.filepath,
                "-vframes", "1", "-f", "image2pipe", "-vcodec", "mjpeg",
                "-vf", "scale=-1:80", "-"
            ]
            flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            res = subprocess.run(cmd, capture_output=True, check=True, creationflags=flags)
            if res.stdout:
                self.signal.emit(res.stdout)
        except Exception:
            pass

class _FileRow(QWidget):
    """A single row in the recent files list."""

    open_requested   = pyqtSignal(str)
    rename_requested = pyqtSignal(str, str)
    delete_requested = pyqtSignal(str)

    def __init__(self, filepath: str, font_size_mode: str = "Default", parent=None):
        super().__init__(parent)
        self._filepath = filepath
        self._font_size_mode = font_size_mode
        self._is_renaming = False
        self._drag_start_pos = None
        self.setFixedHeight(50)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._build_ui()

    @property
    def filename(self) -> str:
        return Path(self._filepath).name

    def _build_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(10)

        # Thumbnail
        self._thumb = QLabel()
        self._thumb.setFixedSize(54, 40)
        self._thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)

        ext = Path(self._filepath).suffix.lower()
        if ext in (".png", ".jpg", ".jpeg"):
            px = QPixmap(self._filepath)
            if not px.isNull():
                self._thumb.setPixmap(px.scaled(self._thumb.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
                self._thumb.setStyleSheet("background: #000000; border-radius: 4px; border: 1px solid #333;")
            else:
                self._thumb.setText("IMG")
                self._thumb.setStyleSheet("background: rgba(34, 197, 94, 0.1); color: #22C55E; border-radius: 4px; font-size: 10px; font-weight: 800;")
        elif ext in (".mkv", ".mp4", ".webm", ".avi"):
            play_ico = _asset("play.png")
            if os.path.isfile(play_ico):
                px = QPixmap(play_ico)
                self._thumb.setPixmap(px.scaled(24, 24, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
                self._thumb.setStyleSheet("background: rgba(220, 38, 38, 0.15); border-radius: 4px; border: 1px solid rgba(220, 38, 38, 0.3);")
            else:
                self._thumb.setText("▶")
                self._thumb.setStyleSheet("background: rgba(220, 38, 38, 0.15); color: #DC2626; border-radius: 4px; font-size: 14px; border: 1px solid rgba(220, 38, 38, 0.3);")
                
            # Async thumbnail load
            self._thumb_signals = _ThumbSignals()
            self._thumb_signals.loaded.connect(self._on_video_thumb_loaded)
            task = _VideoThumbnailTask(self._filepath, self._thumb_signals.loaded)
            QThreadPool.globalInstance().start(task)
        else:
            self._thumb.setText("FILE")
            self._thumb.setStyleSheet("background: rgba(255, 255, 255, 0.1); color: #FFFFFF; border-radius: 4px; font-size: 10px; font-weight: 800;")

        layout.addWidget(self._thumb)

        info = QVBoxLayout()
        info.setSpacing(2)
        info.setContentsMargins(4, 0, 0, 0)

        fs_name = "14px" if self._font_size_mode == "Large" else "12px"
        fs_meta = "11px" if self._font_size_mode == "Large" else "9px"
        self._rename_h = 24 if self._font_size_mode == "Large" else 20
        
        fname = Path(self._filepath).name
        self._lbl_name = QLabel(fname)
        self._lbl_name.setStyleSheet(f"color: #FFFFFF; font-size: {fs_name}; font-weight: 500; font-family: 'Segoe UI';")
        self._lbl_name.setToolTip(fname)
        self._lbl_name.setMinimumWidth(10)
        self._lbl_name.setSizePolicy(QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.Preferred)
        info.addWidget(self._lbl_name)

        # Inline rename
        self._rename_edit = QLineEdit()
        self._rename_edit.setVisible(False)
        self._rename_edit.setStyleSheet("""
            QLineEdit {
                background: #1C1C1E; border: 1px solid #DC2626; border-radius: 4px;
                color: #FFFFFF; font-size: 11px; padding: 2px 6px;
            }
        """)
        self._rename_edit.returnPressed.connect(self._finish_rename)
        self._rename_edit.editingFinished.connect(self._finish_rename)
        info.addWidget(self._rename_edit)

        try:
            st = os.stat(self._filepath)
            mt = datetime.fromtimestamp(st.st_mtime)
            
            # Formulate file size suffix
            size_mb = st.st_size / (1024 * 1024)
            if size_mb >= 1.0:
                size_str = f"{size_mb:.1f} MB"
            else:
                size_kb = st.st_size / 1024
                size_str = f"{size_kb:.0f} KB"
                
            meta = mt.strftime(f'%b %d, %Y  •  %I:%M %p  •  {size_str}')
        except Exception:
            meta = ""
            
        lbl_meta = QLabel(meta)
        lbl_meta.setStyleSheet(f"color: rgba(255,255,255,0.45); font-size: {fs_meta}; font-family: 'Segoe UI';")
        lbl_meta.setMinimumWidth(10)
        lbl_meta.setSizePolicy(QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.Preferred)
        info.addWidget(lbl_meta)
        info.addStretch()
        layout.addLayout(info, 1)

        self._btn_rename = self._icon_btn("rename.png", "Rename")
        self._btn_rename.clicked.connect(self._start_rename)
        layout.addWidget(self._btn_rename)

        self._btn_delete = self._icon_btn("delete.png", "Delete")
        self._btn_delete.clicked.connect(lambda: self.delete_requested.emit(self._filepath))
        layout.addWidget(self._btn_delete)

        self.setStyleSheet("""
            _FileRow { background: transparent; border-radius: 6px; }
            _FileRow:hover { background: rgba(220,38,38,0.1); }
        """)

    def _on_video_thumb_loaded(self, pm_data: bytes):
        pm = QPixmap()
        pm.loadFromData(pm_data, "JPEG")
        if not pm.isNull():
            # Add a slight play button overlay on top of the thumbnail
            painter = QPainter(pm)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setBrush(QColor(0, 0, 0, 100))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRect(pm.rect())
            
            play_ico = _asset("play.png")
            if os.path.isfile(play_ico):
                ico = QPixmap(play_ico).scaled(32, 32, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                x = (pm.width() - ico.width()) // 2
                y = (pm.height() - ico.height()) // 2
                painter.drawPixmap(x, y, ico)
            painter.end()

            self._thumb.setText("")
            self._thumb.setPixmap(pm.scaled(self._thumb.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation))
            self._thumb.setStyleSheet("background: #000000; border-radius: 4px; border: 1px solid #333;")

    def _icon_btn(self, icon_name, tip):
        b = QPushButton()
        b.setToolTip(tip)
        b.setFixedSize(26, 26)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        ico = _asset(icon_name)
        if os.path.isfile(ico):
            b.setIcon(QIcon(ico))
            b.setIconSize(QSize(14, 14))
        else:
            b.setText(tip[0])
        b.setStyleSheet("""
            QPushButton { background: transparent; border: none; border-radius: 4px; color: rgba(255,255,255,0.45); font-size: 11px; }
            QPushButton:hover { background: rgba(220,38,38,0.2); }
        """)
        return b

    def _start_rename(self):
        self._is_renaming = True
        self._rename_edit.setText(Path(self._filepath).stem)
        self._rename_edit.setVisible(True)
        self._rename_edit.setFocus()
        self._rename_edit.selectAll()
        self._lbl_name.setVisible(False)

    def _finish_rename(self):
        new = self._rename_edit.text().strip()
        if new and new != Path(self._filepath).stem:
            self.rename_requested.emit(self._filepath, new + Path(self._filepath).suffix)
        self._rename_edit.setVisible(False)
        self._lbl_name.setVisible(True)
        self._is_renaming = False

    def mouseDoubleClickEvent(self, event):
        if not self._is_renaming:
            self.open_requested.emit(self._filepath)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and not self._is_renaming:
            self._drag_start_pos = event.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not (event.buttons() & Qt.MouseButton.LeftButton) or self._is_renaming or not self._drag_start_pos:
            return
        if (event.pos() - self._drag_start_pos).manhattanLength() < QApplication.startDragDistance():
            return

        drag = QDrag(self)
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(self._filepath)])
        drag.setMimeData(mime)

        px = QPixmap(140, 26)
        px.fill(QColor(30, 30, 32, 220))
        pt = QPainter(px)
        pt.setPen(QColor(255, 255, 255))
        pt.setFont(QFont("Segoe UI", 8))
        pt.drawText(px.rect().adjusted(6, 0, 0, 0), Qt.AlignmentFlag.AlignVCenter, Path(self._filepath).name)
        pt.end()
        drag.setPixmap(px)

        # COPY only — never move files
        drag.exec(Qt.DropAction.CopyAction)


# ─────────────────────────────────────────────────────────────────────────────
#  RecentFilesSidebar
# ─────────────────────────────────────────────────────────────────────────────

class RecentFilesSidebar(SidebarPanel):
    """Recent files gallery in a full-height sidebar."""

    settings_requested = pyqtSignal()

    def __init__(self, output_folder: str, font_size_mode: str = "Default", edge: str = "right"):
        super().__init__(edge)
        self._output_folder = output_folder
        self._font_size_mode = font_size_mode
        self._build_ui()
        self._position_sidebar()
        self._load_files()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(0)

        # Settings gear button for heading bar
        btn_settings = QPushButton()
        btn_settings.setToolTip("Settings")
        btn_settings.setFixedSize(26, 26)
        btn_settings.setCursor(Qt.CursorShape.PointingHandCursor)
        settings_ico = _asset("settings.png")
        if os.path.isfile(settings_ico):
            btn_settings.setIcon(QIcon(settings_ico))
            btn_settings.setIconSize(QSize(14, 14))
        btn_settings.setStyleSheet("""
            QPushButton {
                background: #262628; border: 1px solid #3C3C3E;
                border-radius: 13px;
            }
            QPushButton:hover { background: #DC2626; border-color: #EF4444; }
        """)
        btn_settings.clicked.connect(self.settings_requested.emit)

        self._build_heading(root, extra_buttons=[btn_settings])

        # Header Actions Row
        actions_row = QHBoxLayout()
        actions_row.setContentsMargins(0, 0, 0, 0)
        actions_row.setSpacing(6)

        # Open folder button
        btn_folder = QPushButton("  Open Folder in Explorer")
        btn_folder.setFixedHeight(34)
        btn_folder.setCursor(Qt.CursorShape.PointingHandCursor)
        ico = _asset("folder.png")
        if os.path.isfile(ico):
            btn_folder.setIcon(QIcon(ico))
            btn_folder.setIconSize(QSize(14, 14))
        btn_folder.setStyleSheet("""
            QPushButton {
                background: #262628; color: rgba(255,255,255,0.8); border: 1px solid #3C3C3E;
                border-radius: 6px; font-size: 11px; text-align: left; padding-left: 10px;
            }
            QPushButton:hover { background: #DC2626; color: #FFFFFF; border-color: #EF4444; }
        """)
        btn_folder.clicked.connect(self._open_folder)
        actions_row.addWidget(btn_folder, 1)

        # Toggle Search Button
        btn_toggle_search = QPushButton()
        btn_toggle_search.setFixedSize(34, 34)
        btn_toggle_search.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_toggle_search.setToolTip("Search Recordings")
        s_ico = _asset("search.png")
        if os.path.isfile(s_ico):
            btn_toggle_search.setIcon(QIcon(s_ico))
            btn_toggle_search.setIconSize(QSize(14, 14))
        else:
            btn_toggle_search.setText("🔍")
            btn_toggle_search.setStyleSheet("color: rgba(255,255,255,0.6); font-size: 14px;")
        btn_toggle_search.setStyleSheet("""
            QPushButton {
                background: #262628; border: 1px solid #3C3C3E; border-radius: 6px;
            }
            QPushButton:hover { background: #DC2626; border-color: #EF4444; }
        """)
        btn_toggle_search.clicked.connect(self._toggle_search)
        actions_row.addWidget(btn_toggle_search)

        root.addLayout(actions_row)

        # Search box (hidden by default)
        self._edt_search = QLineEdit()
        self._edt_search.setVisible(False)
        self._edt_search.setPlaceholderText("Search recordings...")
        self._edt_search.setFixedHeight(34)
        self._edt_search.setStyleSheet("""
            QLineEdit {
                background: #1C1C1E; border: 1px solid #3C3C3E; border-radius: 6px;
                padding: 0 10px; color: #FFFFFF; font-size: 11px; font-family: 'Segoe UI';
                margin-top: 6px;
            }
            QLineEdit:focus { border: 1px solid #DC2626; }
        """)
        self._edt_search.textChanged.connect(self._filter_files)
        root.addWidget(self._edt_search)

        root.addSpacing(8)

        # Scroll area
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet("""
            QScrollArea { background: transparent; border: none; }
            QScrollBar:vertical { background: transparent; width: 5px; }
            QScrollBar::handle:vertical { background: rgba(220,38,38,0.4); border-radius: 2px; min-height: 20px; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
        """)

        self._file_container = QWidget()
        self._file_container.setStyleSheet("background: transparent;")
        self._file_layout = QVBoxLayout(self._file_container)
        self._file_layout.setContentsMargins(0, 0, 0, 0)
        self._file_layout.setSpacing(2)
        self._file_layout.addStretch()

        self._scroll.setWidget(self._file_container)
        root.addWidget(self._scroll, 1)

        # Drag and drop hint
        self._lbl_drag_info = QLabel("💡Tip: You can drag and drop these files anywhere!")
        self._lbl_drag_info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_drag_info.setStyleSheet("color: rgba(255,255,255,0.35); font-size: 10px; padding-top: 6px; font-style: italic; font-family: 'Segoe UI';")
        root.addWidget(self._lbl_drag_info)

        self._lbl_empty = QLabel("No files yet.\nCapture something to get started.")
        self._lbl_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_empty.setStyleSheet("color: rgba(255,255,255,0.25); font-size: 11px; padding: 30px;")
        self._lbl_empty.setWordWrap(True)
        self._lbl_empty.setVisible(False)
        root.addWidget(self._lbl_empty, 1)

    def _load_files(self):
        while self._file_layout.count() > 1:
            item = self._file_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        folder = Path(self._output_folder)
        if not folder.exists():
            self._lbl_empty.setVisible(True)
            self._scroll.setVisible(False)
            self._lbl_drag_info.setVisible(False)
            return

        exts = {".mkv", ".mp4", ".png", ".jpg", ".webm", ".avi"}
        files = []
        for f in folder.iterdir():
            if f.is_file() and f.suffix.lower() in exts:
                try:
                    files.append((f, f.stat().st_mtime))
                except Exception:
                    pass

        files.sort(key=lambda x: x[1], reverse=True)

        if not files:
            self._lbl_empty.setVisible(True)
            self._scroll.setVisible(False)
            self._lbl_drag_info.setVisible(False)
            return

        self._lbl_empty.setVisible(False)
        self._scroll.setVisible(True)
        self._lbl_drag_info.setVisible(True)

        font_size_mode = getattr(self, "_font_size_mode", "Default")
        for fpath, _ in files[:50]:
            row = _FileRow(str(fpath), font_size_mode)
            row.open_requested.connect(self._open_file)
            row.rename_requested.connect(self._rename_file)
            row.delete_requested.connect(self._delete_file)
            self._file_layout.insertWidget(self._file_layout.count() - 1, row)
            
        # apply any existing search filter
        if getattr(self, '_edt_search', None) and self._edt_search.text():
            self._filter_files(self._edt_search.text())

    def _filter_files(self, text: str):
        query = text.lower()
        for i in range(self._file_layout.count() - 1): # skip stretch at end
            item = self._file_layout.itemAt(i)
            widget = item.widget()
            if widget and hasattr(widget, 'filename'):
                widget.setVisible(query in widget.filename.lower())

    def _toggle_search(self):
        is_visible = self._edt_search.isVisible()
        if is_visible:
            self._edt_search.setVisible(False)
            self._edt_search.clear()  # Clear search when closed
        else:
            self._edt_search.setVisible(True)
            self._edt_search.setFocus()

    def refresh(self):
        self._load_files()

    def _open_file(self, fp):
        if os.path.isfile(fp):
            os.startfile(fp)

    def _rename_file(self, old, new_name):
        try:
            new = os.path.join(os.path.dirname(old), new_name)
            if not os.path.exists(new):
                os.rename(old, new)
                self._load_files()
        except Exception as e:
            print(f"[RecentFiles] Rename: {e}")

    def _delete_file(self, fp):
        reply = QMessageBox.question(
            self, "Delete File", f"Permanently delete\n{os.path.basename(fp)}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            try:
                os.remove(fp)
                self._load_files()
            except Exception as e:
                print(f"[RecentFiles] Delete: {e}")

    def _open_folder(self):
        if os.path.isdir(self._output_folder):
            os.startfile(self._output_folder)
