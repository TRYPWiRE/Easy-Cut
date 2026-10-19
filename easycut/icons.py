"""Line icons drawn with QPainter (crisp at any DPI, recoloured live when the theme changes) + the app icon."""
import math
import weakref

from PyQt6.QtCore import Qt, QRectF, QPointF, QSize
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QPen, QColor, QPainterPath, QFont, QPolygonF

from . import theme

APP_BG = "#2a0812"
APP_FG = "#ff4f7b"


def _pen(p, col, w=1.8):
    pen = QPen(QColor(col), w)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)


def _draw(p, name, col):
    """Draw icon `name` on a 24x24 grid."""
    fill = QColor(col)
    P = QPointF
    if name == "play":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(fill)
        p.drawPolygon(QPolygonF([P(7, 4.5), P(19.5, 12), P(7, 19.5)]))
    elif name == "pause":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(fill)
        p.drawRoundedRect(QRectF(6, 4.5, 4, 15), 1, 1)
        p.drawRoundedRect(QRectF(14, 4.5, 4, 15), 1, 1)
    elif name in ("start", "end"):
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(fill)
        if name == "start":
            p.drawRect(QRectF(5, 5, 2.4, 14))
            p.drawPolygon(QPolygonF([P(19, 5), P(9, 12), P(19, 19)]))
        else:
            p.drawRect(QRectF(16.6, 5, 2.4, 14))
            p.drawPolygon(QPolygonF([P(5, 5), P(15, 12), P(5, 19)]))
    elif name in ("frame_back", "frame_fwd"):
        _pen(p, col)
        if name == "frame_back":
            p.drawPolyline(QPolygonF([P(14, 6), P(8, 12), P(14, 18)]))
        else:
            p.drawPolyline(QPolygonF([P(10, 6), P(16, 12), P(10, 18)]))
    elif name == "split":
        _pen(p, col)
        p.drawEllipse(QRectF(3.5, 14, 5, 5))
        p.drawEllipse(QRectF(15.5, 14, 5, 5))
        p.drawLine(P(7.5, 14.5), P(17, 4))
        p.drawLine(P(16.5, 14.5), P(7, 4))
    elif name == "trash":
        _pen(p, col)
        p.drawLine(P(4, 7), P(20, 7))
        p.drawPolyline(QPolygonF([P(6, 7), P(7, 20), P(17, 20), P(18, 7)]))
        p.drawPolyline(QPolygonF([P(9, 7), P(9.5, 4), P(14.5, 4), P(15, 7)]))
        p.drawLine(P(10, 11), P(10, 16))
        p.drawLine(P(14, 11), P(14, 16))
    elif name in ("undo", "redo"):
        _pen(p, col)
        path = QPainterPath()
        if name == "undo":
            path.moveTo(5, 10)
            path.lineTo(15, 10)
            path.cubicTo(21, 10, 21, 19, 15, 19)
            path.lineTo(9, 19)
            p.drawPath(path)
            p.drawPolyline(QPolygonF([P(9, 6), P(5, 10), P(9, 14)]))
        else:
            path.moveTo(19, 10)
            path.lineTo(9, 10)
            path.cubicTo(3, 10, 3, 19, 9, 19)
            path.lineTo(15, 19)
            p.drawPath(path)
            p.drawPolyline(QPolygonF([P(15, 6), P(19, 10), P(15, 14)]))
    elif name == "plus":
        _pen(p, col, 2)
        p.drawLine(P(12, 5), P(12, 19))
        p.drawLine(P(5, 12), P(19, 12))
    elif name == "media":
        _pen(p, col)
        p.drawRoundedRect(QRectF(3.5, 5, 17, 14), 2.5, 2.5)
        p.setBrush(fill)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawPolygon(QPolygonF([P(10, 9), P(15.5, 12), P(10, 15)]))
    elif name == "text":
        _pen(p, col, 2.1)
        p.drawLine(P(5, 6), P(19, 6))
        p.drawLine(P(12, 6), P(12, 19))
        p.drawLine(P(9, 19), P(15, 19))
    elif name == "filters":
        _pen(p, col)
        p.drawEllipse(QRectF(4, 4, 10, 10))
        p.drawEllipse(QRectF(10, 4, 10, 10))
        p.drawEllipse(QRectF(7, 10, 10, 10))
    elif name == "anim":
        _pen(p, col)
        p.drawEllipse(QRectF(11, 7, 10, 10))
        p.drawLine(P(3, 9), P(8, 9))
        p.drawLine(P(2, 12), P(9, 12))
        p.drawLine(P(3, 15), P(8, 15))
    elif name == "effects":
        _pen(p, col)
        p.drawLine(P(4, 20), P(14, 10))
        star = [P(17, 3), P(18.2, 5.8), P(21, 7), P(18.2, 8.2), P(17, 11), P(15.8, 8.2), P(13, 7), P(15.8, 5.8)]
        p.drawPolygon(QPolygonF(star))
        p.drawPoint(P(8, 6))
        p.drawPoint(P(20, 15))
    elif name == "extensions":
        _pen(p, col)
        path = QPainterPath()
        path.moveTo(5, 8)
        path.lineTo(9, 8)
        path.arcTo(QRectF(9, 4.5, 4, 4), 180, -180)
        path.lineTo(17, 8)
        path.lineTo(17, 11)
        path.arcTo(QRectF(17, 11, 4, 4), 90, -180)
        path.lineTo(17, 19)
        path.lineTo(5, 19)
        path.closeSubpath()
        p.drawPath(path)
    elif name == "export":
        _pen(p, col)
        p.drawLine(P(12, 4), P(12, 15))
        p.drawPolyline(QPolygonF([P(7.5, 8.5), P(12, 4), P(16.5, 8.5)]))
        p.drawPolyline(QPolygonF([P(4, 14), P(4, 20), P(20, 20), P(20, 14)]))
    elif name == "magnet":
        _pen(p, col)
        path = QPainterPath()
        path.moveTo(6, 4)
        path.lineTo(6, 12)
        path.arcTo(QRectF(6, 6, 12, 12), 180, 180)
        path.lineTo(18, 4)
        p.drawPath(path)
        p.drawLine(P(4, 8), P(8, 8))
        p.drawLine(P(16, 8), P(20, 8))
    elif name in ("zoom_in", "zoom_out"):
        _pen(p, col)
        p.drawEllipse(QRectF(4, 4, 12, 12))
        p.drawLine(P(14.5, 14.5), P(20, 20))
        p.drawLine(P(7, 10), P(13, 10))
        if name == "zoom_in":
            p.drawLine(P(10, 7), P(10, 13))
    elif name == "theme":
        _pen(p, col)
        path = QPainterPath()
        path.addEllipse(QRectF(3.5, 3.5, 17, 17))
        p.drawPath(path)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(fill)
        for x, y in ((9, 8.5), (14.5, 8), (17, 12.5), (8, 13.5)):
            p.drawEllipse(QPointF(x, y), 1.6, 1.6)
    elif name == "settings":
        _pen(p, col)
        p.drawEllipse(QRectF(9, 9, 6, 6))
        for i in range(8):
            a = i * math.pi / 4
            p.drawLine(P(12 + math.cos(a) * 6, 12 + math.sin(a) * 6), P(12 + math.cos(a) * 8.5, 12 + math.sin(a) * 8.5))
        p.drawEllipse(QRectF(6, 6, 12, 12))
    elif name == "folder":
        _pen(p, col)
        p.drawPolyline(QPolygonF([P(3.5, 18.5), P(3.5, 5.5), P(9.5, 5.5), P(11.5, 8), P(20.5, 8), P(20.5, 18.5),
                                  P(3.5, 18.5)]))
    elif name == "save":
        _pen(p, col)
        p.drawPolyline(QPolygonF([P(4, 4), P(16.5, 4), P(20, 7.5), P(20, 20), P(4, 20), P(4, 4)]))
        p.drawRect(QRectF(8, 4, 7, 5))
        p.drawRect(QRectF(7, 13, 10, 7))
    elif name in ("eye", "eye_off"):
        _pen(p, col)
        path = QPainterPath()
        path.moveTo(2.5, 12)
        path.quadTo(12, 3, 21.5, 12)
        path.quadTo(12, 21, 2.5, 12)
        p.drawPath(path)
        p.drawEllipse(QPointF(12, 12), 3, 3)
        if name == "eye_off":
            p.drawLine(P(4, 20), P(20, 4))
    elif name in ("volume", "mute"):
        _pen(p, col)
        p.drawPolygon(QPolygonF([P(4, 9), P(8, 9), P(13, 5), P(13, 19), P(8, 15), P(4, 15)]))
        if name == "volume":
            path = QPainterPath()
            path.moveTo(16, 8.5)
            path.quadTo(18.5, 12, 16, 15.5)
            path.moveTo(18.5, 6)
            path.quadTo(22.5, 12, 18.5, 18)
            p.drawPath(path)
        else:
            p.drawLine(P(16, 9), P(21, 15))
            p.drawLine(P(21, 9), P(16, 15))
    elif name == "fullscreen":
        _pen(p, col)
        for a, b, c in (((4, 9), (4, 4), (9, 4)), ((15, 4), (20, 4), (20, 9)), ((20, 15), (20, 20), (15, 20)),
                        ((9, 20), (4, 20), (4, 15))):
            p.drawPolyline(QPolygonF([P(*a), P(*b), P(*c)]))
    elif name == "music":
        _pen(p, col)
        p.drawLine(P(9, 17), P(9, 5))
        p.drawLine(P(9, 5), P(19, 3.5))
        p.drawLine(P(19, 3.5), P(19, 15))
        p.setBrush(fill)
        p.drawEllipse(QPointF(6.5, 17.5), 2.6, 2.1)
        p.drawEllipse(QPointF(16.5, 15.5), 2.6, 2.1)
    elif name == "image":
        _pen(p, col)
        p.drawRoundedRect(QRectF(3.5, 4.5, 17, 15), 2, 2)
        p.drawPolyline(QPolygonF([P(4, 17), P(9.5, 11.5), P(13, 15), P(15.5, 12.5), P(20, 17)]))
        p.drawEllipse(QPointF(15.5, 8.5), 1.4, 1.4)
    elif name == "crop":
        _pen(p, col)
        p.drawPolyline(QPolygonF([P(7, 3), P(7, 17), P(21, 17)]))
        p.drawPolyline(QPolygonF([P(3, 7), P(17, 7), P(17, 21)]))
    elif name == "flip":
        _pen(p, col)
        p.drawLine(P(12, 3), P(12, 21))
        p.drawPolygon(QPolygonF([P(9, 6), P(3, 18), P(9, 18)]))
        p.setBrush(fill)
        p.drawPolygon(QPolygonF([P(15, 6), P(21, 18), P(15, 18)]))
    elif name == "mirror":
        _pen(p, col)
        p.drawRect(QRectF(3.5, 5, 17, 14))
        pen = QPen(QColor(col), 1.4, Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.drawLine(P(12, 5), P(12, 19))
        _pen(p, col)
        p.drawPolyline(QPolygonF([P(6, 15), P(9, 9), P(10, 12)]))
        p.drawPolyline(QPolygonF([P(18, 15), P(15, 9), P(14, 12)]))
    elif name == "chroma":
        _pen(p, col)
        p.drawRoundedRect(QRectF(3.5, 4.5, 17, 15), 2, 2)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(col))
        p.drawEllipse(QPointF(12, 10), 2.6, 2.6)
        p.drawRoundedRect(QRectF(8, 13.5, 8, 6), 2.5, 2.5)
    elif name == "speed":
        _pen(p, col)
        path = QPainterPath()
        path.arcMoveTo(QRectF(3.5, 5, 17, 17), 200)
        path.arcTo(QRectF(3.5, 5, 17, 17), 200, -220)
        p.drawPath(path)
        p.drawLine(P(12, 13.5), P(16.5, 9))
    elif name == "stabilize":
        _pen(p, col)
        p.drawRoundedRect(QRectF(6, 6, 12, 12), 2, 2)
        for a, b in (((2.5, 9), (2.5, 15)), ((21.5, 9), (21.5, 15)), ((9, 2.5), (15, 2.5)), ((9, 21.5), (15, 21.5))):
            p.drawLine(P(*a), P(*b))
    elif name == "transform":
        _pen(p, col)
        p.drawRect(QRectF(5, 5, 14, 14))
        p.setBrush(fill)
        for x, y in ((5, 5), (19, 5), (19, 19), (5, 19)):
            p.drawRect(QRectF(x - 1.8, y - 1.8, 3.6, 3.6))
    elif name == "adjust":
        _pen(p, col)
        for y, x in ((7, 15), (12, 8), (17, 13)):
            p.drawLine(P(4, y), P(20, y))
            p.setBrush(QColor(theme.C.get("panel", "#222")) if theme.C else Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(x, y), 2.2, 2.2)
            p.setBrush(Qt.BrushStyle.NoBrush)
    elif name == "audio":
        _pen(p, col)
        for i, h in enumerate((4, 9, 14, 7, 11, 5)):
            x = 4.5 + i * 3
            p.drawLine(P(x, 12 - h / 2), P(x, 12 + h / 2))
    elif name == "close":
        _pen(p, col, 2)
        p.drawLine(P(6, 6), P(18, 18))
        p.drawLine(P(18, 6), P(6, 18))
    elif name == "check":
        _pen(p, col, 2.2)
        p.drawPolyline(QPolygonF([P(5, 12.5), P(10, 17.5), P(19, 7)]))
    elif name == "info":
        _pen(p, col)
        p.drawEllipse(QRectF(3.5, 3.5, 17, 17))
        p.drawLine(P(12, 11), P(12, 16.5))
        p.drawPoint(P(12, 7.8))
    elif name == "update":
        _pen(p, col)
        path = QPainterPath()
        path.arcMoveTo(QRectF(4.5, 4.5, 15, 15), 40)
        path.arcTo(QRectF(4.5, 4.5, 15, 15), 40, 280)
        p.drawPath(path)
        p.drawPolyline(QPolygonF([P(18.5, 3.5), P(18.5, 8), P(14, 8)]))
    elif name == "fit":
        _pen(p, col)
        p.drawRect(QRectF(3.5, 6, 17, 12))
        p.drawRect(QRectF(8, 8, 8, 8))
    else:  # unknown: a dot
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(fill)
        p.drawEllipse(QPointF(12, 12), 3, 3)


def pixmap(name, size=20, color=None, dpr=2.0) -> QPixmap:
    theme.ensure_loaded()
    col = color or theme.C.get("text", "#d9d9e0")
    px = int(size * dpr)
    pm = QPixmap(px, px)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(px / 24.0, px / 24.0)
    _draw(p, name, col)
    p.end()
    pm.setDevicePixelRatio(dpr)
    return pm


def icon(name, size=20, color=None) -> QIcon:
    theme.ensure_loaded()
    ic = QIcon()
    ic.addPixmap(pixmap(name, size, color or theme.C.get("text")), QIcon.Mode.Normal, QIcon.State.Off)
    ic.addPixmap(pixmap(name, size, theme.C.get("text_strong")), QIcon.Mode.Normal, QIcon.State.On)
    ic.addPixmap(pixmap(name, size, theme.C.get("text_dim")), QIcon.Mode.Disabled, QIcon.State.Off)
    return ic


_bound = []


def bind(button, name, size=20, color_key=None):
    """Give a button a themed icon that recolours itself when the theme changes."""
    _bound[:] = [b for b in _bound if b[0]() is not None and b[0]() is not button]
    _bound.append((weakref.ref(button), name, size, color_key))
    _apply_one(button, name, size, color_key)


def _apply_one(button, name, size, color_key):
    col = theme.C.get(color_key) if color_key else None
    button.setIcon(icon(name, size, col))
    button.setIconSize(QSize(size, size))


def refresh_bound():
    alive = []
    for ref, name, size, key in _bound:
        b = ref()
        if b is None:
            continue
        try:
            _apply_one(b, name, size, key)
            alive.append((ref, name, size, key))
        except RuntimeError:
            pass
    _bound[:] = alive


theme.notifier.changed.connect(refresh_bound)


# ---------------------------------------------------------------------- app icon (Lumen-style, "Ec")
def app_pixmap(s=256) -> QPixmap:
    pm = QPixmap(s, s)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    r = QRectF(0, 0, s, s).adjusted(s * 0.03, s * 0.03, -s * 0.03, -s * 0.03)
    p.setPen(QPen(QColor(APP_FG), max(1.0, s * 0.035)))
    p.setBrush(QColor(APP_BG))
    p.drawRoundedRect(r, s * 0.2, s * 0.2)
    f = QFont("Segoe UI")
    f.setPixelSize(int(s * 0.46))
    f.setBold(True)
    p.setFont(f)
    p.setPen(QColor(APP_FG))
    p.drawText(r, Qt.AlignmentFlag.AlignCenter, "Ec")
    p.end()
    return pm


def app_icon() -> QIcon:
    import os
    from .config import asset
    ico = asset("easycut.ico")
    if os.path.exists(ico):
        return QIcon(ico)
    ic = QIcon()
    for s in (16, 24, 32, 48, 64, 128, 256):
        ic.addPixmap(app_pixmap(s))
    return ic
