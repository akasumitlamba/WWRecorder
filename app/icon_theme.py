"""Shared approved icon routing and contrast for both Windows editions."""
import os
import sys
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap, QBitmap, QRegion

ALIASES = {
    've_play': 'play', 've_pause': 'pause', 've_close': 'close',
    've_delete': 'clear_all', 'delete': 'clear_all', 'copy': 'copyicon',
    've_save': 'save', 'panel-reset': 'reset', 'panel-share': 'share',
    'panel-power': 'power', 'panel-search': 'search',
    'panel-settings': 'settings', 'panel-close': 'close',
}

CONTROL_STYLE = '''
    QToolButton, QPushButton {
        background: #202633; border: 1px solid #424B5D;
        border-radius: 6px; color: #F0F2F5; padding: 0px;
    }
    QToolButton:hover, QPushButton:hover { background: #303B4E; border-color: #6A7890; }
    QToolButton:pressed, QPushButton:pressed { background: #151C28; border-color: #FF7382; }
    QToolButton:checked, QPushButton:checked { background: #492333; border-color: #FF7382; }
    QToolButton:focus, QPushButton:focus { border-color: #FF7382; }
    QToolButton:disabled, QPushButton:disabled { background: #191E28; border-color: #303744; }
    QToolButton::menu-indicator { image: none; }
'''


def asset_path(filename):
    base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    # Recording keeps the original recognizable camera, not a record dot.
    if filename == 'record.png':
        return os.path.join(base, 'icons', filename)
    stem, extension = os.path.splitext(filename)
    name = ALIASES.get(stem, stem)
    modern = os.path.join(base, 'icons', 'modern', name + extension)
    if extension.lower() == '.png' and os.path.isfile(modern):
        return modern
    return os.path.join(base, 'icons', filename)


def wordmark_pixmap(height):
    """Discard only transparent margins; retain every established logo pixel."""
    image = QPixmap(asset_path('wwrecorder.png')).toImage()
    if image.isNull(): return QPixmap()
    mask = QBitmap.fromImage(image.createAlphaMask())
    bounds = QRegion(mask).boundingRect()
    if not bounds.isEmpty(): image = image.copy(bounds)
    return QPixmap.fromImage(image).scaledToHeight(height, Qt.TransformationMode.SmoothTransformation)
