"""Bounded frozen startup probe. Never starts capture, hooks, or update checks."""
import json
from pathlib import Path

def run(receipt):
    from PyQt6.QtCore import QTimer, QT_VERSION_STR
    from PyQt6.QtGui import QIcon
    from PyQt6.QtWidgets import QApplication, QWidget
    from PyQt6.QtMultimedia import QMediaPlayer
    from PyQt6.QtMultimediaWidgets import QVideoWidget
    from icon_theme import asset_path
    app=QApplication.instance() or QApplication([])
    window=QWidget();player=QMediaPlayer();video=QVideoWidget();player.setVideoOutput(video)
    for name in ('undo.png','redo.png','record.png','playback-speed.png'):
        if QIcon(asset_path(name)).isNull():raise RuntimeError('Missing runtime icon: '+name)
    QTimer.singleShot(250,app.quit)
    result=app.exec()
    Path(receipt).write_text(json.dumps({'ok':result==0,'qt':QT_VERSION_STR,'capture_started':False}))
    return result
