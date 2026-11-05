"""Render the shared geometric check from native vector geometry, not a font."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QImage,QPainter,QPainterPath,QPen,QColor
from PyQt6.QtCore import Qt
POINTS=((14,33),(26,45),(50,21))

def build():
    app=QApplication.instance() or QApplication([])
    root=Path(__file__).resolve().parents[1]/'app/icons/modern'
    d='M14 33 L26 45 L50 21'
    (root/'apply.svg').write_text(f'<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64"><path d="{d}" fill="none" stroke="#F0F2F5" stroke-width="5.5" stroke-linecap="round" stroke-linejoin="round"/></svg>\n')
    image=QImage(64,64,QImage.Format.Format_ARGB32_Premultiplied);image.fill(Qt.GlobalColor.transparent)
    painter=QPainter(image);painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor('#F0F2F5'),5.5,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap,Qt.PenJoinStyle.RoundJoin))
    path=QPainterPath();path.moveTo(*POINTS[0])
    for point in POINTS[1:]:path.lineTo(*point)
    painter.drawPath(path);painter.end()
    if not image.save(str(root/'apply.png')):raise RuntimeError('Could not write confirmation icon')

if __name__=='__main__':build()
