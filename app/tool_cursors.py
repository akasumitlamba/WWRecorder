"""Compact themed cursors with exact interaction hotspots and contrast halos."""
from functools import lru_cache
from PyQt6.QtCore import Qt, QPointF, QRectF
from PyQt6.QtGui import QCursor, QPixmap, QPainter, QPen, QColor, QPainterPath, QPolygonF
from icon_theme import asset_path


def _pen(color, width):
    return QPen(QColor(color), width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)


def _nib(pixmap):
    image = pixmap.toImage()
    pixels = [(x, y) for y in range(image.height()) for x in range(image.width())
              if (c := image.pixelColor(x, y)).alpha() > 160 and c.red() > 150 and c.green() < 135 and c.blue() < 160]
    if not pixels: return 3, pixmap.height()-4
    score = max(y-x for x,y in pixels)
    tip = [(x,y) for x,y in pixels if y-x >= score-1]
    return round(sum(x for x,y in tip)/len(tip)), round(sum(y for x,y in tip)/len(tip))


def _glyph(painter, pixmap, x, y):
    # A one-pixel dark halo keeps white symbols readable on a light desktop.
    shadow = QPixmap(pixmap.size()); shadow.fill(Qt.GlobalColor.transparent)
    p = QPainter(shadow);p.drawPixmap(0,0,pixmap)
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    p.fillRect(shadow.rect(), QColor('#11151D'));p.end()
    for dx,dy in ((-1,0),(1,0),(0,-1),(0,1)):painter.drawPixmap(x+dx,y+dy,shadow)
    painter.drawPixmap(x,y,pixmap)


@lru_cache(maxsize=96)
def tool_cursor(tool, color='#FF5264', width=4):
    if tool in ('pencil','highlighter'):
        size = 80 if width > 24 else 48
        x,y = size//2-4,size//2+8
        canvas = QPixmap(size,size);canvas.fill(Qt.GlobalColor.transparent)
        p = QPainter(canvas);p.setRenderHint(QPainter.RenderHint.Antialiasing)
        tint = QColor(color);tint.setAlpha(100 if tool=='highlighter' else 255)
        p.setPen(_pen('#11151D',1));p.setBrush(tint)
        radius=max(1.5,float(width)/2)
        p.drawEllipse(QPointF(x,y),radius,radius)
        glyph=QPixmap(asset_path('cursor_'+tool+'.png')).scaled(24,24,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation)
        if not glyph.isNull():
            tx,ty=_nib(glyph);_glyph(p,glyph,x-tx,y-ty)
        p.end();return QCursor(canvas,x,y)
    canvas=QPixmap(32,32);canvas.fill(Qt.GlobalColor.transparent)
    p=QPainter(canvas);p.setRenderHint(QPainter.RenderHint.Antialiasing)
    path=QPainterPath()
    if tool=='text':
        path.moveTo(16,4);path.lineTo(16,27)
        path.moveTo(11,4);path.lineTo(21,4)
        path.moveTo(11,27);path.lineTo(21,27)
    elif tool=='crop':
        for x,y,dx,dy in ((7,7,1,1),(25,7,-1,1),(7,25,1,-1),(25,25,-1,-1)):
            path.moveTo(x+dx*6,y);path.lineTo(x,y);path.lineTo(x,y+dy*6)
    else:
        if tool in ('move','resize_h','crosshair','arrow'):
            path.moveTo(4,16);path.lineTo(12,16);path.moveTo(20,16);path.lineTo(28,16)
        if tool in ('move','resize_v','crosshair','arrow'):
            path.moveTo(16,4);path.lineTo(16,12);path.moveTo(16,20);path.lineTo(16,28)
        if tool in ('resize_d1','resize_d2'):
            a,b = ((6,6),(26,26)) if tool=='resize_d1' else ((6,26),(26,6))
            path.moveTo(*a);path.lineTo(*b)
            for x,y in (a,b):
                sx=1 if x==6 else -1;sy=1 if y==6 else -1
                path.moveTo(x+sx*7,y);path.lineTo(x,y);path.lineTo(x,y+sy*7)
        if tool in ('move','resize_h'):
            for x,dx in ((4,1),(28,-1)):
                path.moveTo(x+dx*5,11);path.lineTo(x,16);path.lineTo(x+dx*5,21)
        if tool in ('move','resize_v'):
            for y,dy in ((4,1),(28,-1)):
                path.moveTo(11,y+dy*5);path.lineTo(16,y);path.lineTo(21,y+dy*5)
        if tool=='arrow':
            path.moveTo(18,14);path.lineTo(27,5);path.lineTo(27,12)
            path.moveTo(27,5);path.lineTo(20,5)
        if tool=='eraser':
            path.addRect(QRectF(9,18,14,10))
            glyph=QPixmap(asset_path('cursor_eraser.png')).scaled(20,20,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation)
            if not glyph.isNull(): _glyph(p,glyph,12,1)
    p.setPen(_pen('#11151D',4.5));p.drawPath(path)
    p.setPen(_pen('#F0F2F5',1.5));p.drawPath(path);p.end()
    return QCursor(canvas,16,23 if tool=='eraser' else 16)


def shape_cursor(shape):
    names={Qt.CursorShape.SizeAllCursor:'move',Qt.CursorShape.SizeHorCursor:'resize_h',
           Qt.CursorShape.SizeVerCursor:'resize_v',Qt.CursorShape.SizeFDiagCursor:'resize_d1',
           Qt.CursorShape.SizeBDiagCursor:'resize_d2',Qt.CursorShape.CrossCursor:'crosshair'}
    return tool_cursor(names[shape]) if shape in names else QCursor(shape)
