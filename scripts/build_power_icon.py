"""Render the Quit action as a red geometric power symbol."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
from PyQt6.QtCore import Qt,QRectF
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QImage,QPainter,QPen,QColor

def build():
    app=QApplication.instance() or QApplication([])
    folder=Path(__file__).resolve().parents[1]/'app/icons/modern'
    (folder/'power.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><g fill="none" stroke="#FF4055" stroke-width="5" stroke-linecap="round"><path d="M32 9 V31 M19 17 A21 21 0 1 0 45 17"/></g></svg>\n')
    image=QImage(64,64,QImage.Format.Format_ARGB32_Premultiplied);image.fill(Qt.GlobalColor.transparent)
    painter=QPainter(image);painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor('#FF4055'),5,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap))
    painter.drawArc(QRectF(11,11,42,42),130*16,280*16)
    painter.drawLine(32,9,32,31);painter.end()
    assert image.save(str(folder/'power.png'))
if __name__=='__main__':build()
