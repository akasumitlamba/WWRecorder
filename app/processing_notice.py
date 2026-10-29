"""Non-modal recording finalization feedback; no capture/worker ownership."""
from PyQt6.QtCore import Qt, QTimer, QRect, QRectF, QPoint
from PyQt6.QtGui import QColor, QPainter, QPen, QIcon
from PyQt6.QtWidgets import QApplication, QWidget, QLabel, QPushButton, QHBoxLayout, QVBoxLayout


class ActivityRing(QWidget):
    """A time-based activity indicator, deliberately not a percentage."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(44, 44)
        self._angle = 0
        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._advance)
        self.setAccessibleName('Recording is being finalized')

    def _advance(self):
        self._angle = (self._angle + 12) % 360
        self.update()

    def showEvent(self, event):
        self._timer.start()
        super().showEvent(event)

    def hideEvent(self, event):
        self._timer.stop()
        super().hideEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        bounds = QRectF(3, 3, 38, 38)
        painter.setPen(QPen(QColor('#303949'), 3))
        painter.drawEllipse(bounds)
        painter.setPen(QPen(QColor('#FF5264'), 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawArc(bounds, -self._angle * 16, 105 * 16)
        painter.setPen(QPen(QColor('#F0F2F5'), 1.7))
        painter.drawRoundedRect(QRectF(14, 16, 13, 12), 2, 2)
        painter.drawLine(27, 20, 31, 18)
        painter.drawLine(31, 18, 31, 26)
        painter.drawLine(31, 26, 27, 24)
        painter.end()


class ProcessingNotice(QWidget):
    """Shown only during finalization; dismissal does not cancel media work."""
    def __init__(self):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAccessibleName('Recording processing notification')
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = QWidget(self)
        card.setObjectName('ProcessingCard')
        card.setStyleSheet('''
            QWidget#ProcessingCard {background:#151923;border:1px solid #424B5D;border-radius:12px;}
            QLabel {background:transparent;border:none;color:#B9C1CE;font:12px 'Segoe UI';}
            QPushButton {background:#242C3A;border:1px solid #424B5D;border-radius:6px;color:#F0F2F5;font:18px 'Segoe UI';}
            QPushButton:hover {background:#343E50;border-color:#FF5264;}
            QPushButton:focus {border-color:#FF5264;}
        ''')
        outer.addWidget(card)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(0)
        heading = QHBoxLayout()
        heading.setSpacing(12)
        self._activity = ActivityRing(card)
        heading.addWidget(self._activity)
        labels = QVBoxLayout()
        labels.setSpacing(3)
        self._status_lbl = QLabel('Processing recording')
        self._status_lbl.setWordWrap(True)
        self._status_lbl.setStyleSheet("color:#F7F7FA;font:600 14px 'Segoe UI';border:none;background:transparent;")
        labels.addWidget(self._status_lbl)
        self._sub_lbl = QLabel('Compressing video and audio')
        self._sub_lbl.setWordWrap(True)
        labels.addWidget(self._sub_lbl)
        heading.addLayout(labels, 1)
        self._btn_close = QPushButton()
        from icon_theme import asset_path
        from PyQt6.QtCore import QSize
        self._btn_close.setIcon(QIcon(asset_path('close.png')))
        self._btn_close.setIconSize(QSize(12, 12))
        self._btn_close.setFixedSize(20, 20)
        self._btn_close.setAccessibleName('Dismiss processing notification')
        self._btn_close.setStyleSheet('QPushButton {background:transparent;border:none;border-radius:4px;} '
                                     'QPushButton:hover {background:#343E50;}')
        self._btn_close.setToolTip('Dismiss notification — processing continues')
        self._btn_close.clicked.connect(self.hide_saving)
        heading.addWidget(self._btn_close, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(heading)
        self._stages = QLabel('Recorded   ›   Finalizing   ›   Ready')
        self._stages.setText('<span style="color:#53D3A0">Recorded</span> <span style="color:#657185">›</span> '
                             '<span style="color:#FF7382">Finalizing</span> <span style="color:#657185">› Ready</span>')
        self._stages.hide()
        self._message = QLabel('Your video will appear in Recent Files when ready.')
        self._message.setWordWrap(False)
        self._message.hide()
        self.setFixedWidth(370)
        self.adjustSize()

    def show_saving(self, anchor: QPoint | None = None):
        screen_obj = QApplication.screenAt(anchor) if anchor is not None else None
        screen_obj = screen_obj or QApplication.primaryScreen()
        bounds = screen_obj.availableGeometry() if screen_obj else QRect(0, 0, 1920, 1080)
        self.setFixedWidth(min(370, max(1, bounds.width() - 32)))
        self.adjustSize()
        self.move(max(bounds.left(), bounds.right()-self.width()-15),
                  max(bounds.top(), bounds.bottom()-self.height()-15))
        self.show()
        self.raise_()

    def hide_saving(self):
        self.hide()
