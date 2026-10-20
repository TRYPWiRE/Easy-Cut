"""Bold Text Styles."""
from PyQt6.QtCore import Qt, QPointF
from PyQt6.QtGui import QColor, QPen, QLinearGradient, QBrush


def _pen(col, width):
    pen = QPen(col, max(0.5, width))
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


def extrude(p, ctx):
    depth = max(2, int(ctx.px * 0.12))
    side = QColor(ctx.color).darker(260)
    for i in range(depth, 0, -1):
        p.save()
        p.translate(i * 0.7, i * 0.7)
        p.fillPath(ctx.path, side)
        p.restore()
    p.strokePath(ctx.path, _pen(QColor(0, 0, 0, 160), ctx.px * 0.02))
    p.fillPath(ctx.path, ctx.color)


def comic(p, ctx):
    off = ctx.px * 0.08
    p.save()
    p.translate(off, off)
    p.strokePath(ctx.path, _pen(QColor(0, 0, 0), ctx.px * 0.16))
    p.fillPath(ctx.path, QColor(0, 0, 0))
    p.restore()
    p.strokePath(ctx.path, _pen(QColor(0, 0, 0), ctx.px * 0.16))
    p.fillPath(ctx.path, ctx.color)


def chrome(p, ctx):
    r = ctx.rect
    g = QLinearGradient(QPointF(0, r.top()), QPointF(0, r.bottom()))
    for pos, c in ((0, "#ffffff"), (0.45, "#c9d2dc"), (0.5, "#4a5560"), (0.62, "#8d99a6"), (1, "#f2f6fa")):
        g.setColorAt(pos, QColor(c))
    p.strokePath(ctx.path, _pen(QColor(20, 24, 30), ctx.px * 0.08))
    p.fillPath(ctx.path, QBrush(g))


def rainbow(p, ctx):
    r = ctx.rect
    g = QLinearGradient(QPointF(r.left(), 0), QPointF(r.right(), 0))
    for i, c in enumerate(("#ff3b30", "#ff9500", "#ffcc00", "#34c759", "#0a84ff", "#af52de")):
        g.setColorAt(i / 5, QColor(c))
    p.strokePath(ctx.path, _pen(QColor(255, 255, 255), ctx.px * 0.07))
    p.fillPath(ctx.path, QBrush(g))


def retro(p, ctx):
    r = ctx.rect
    p.save()
    p.translate(ctx.px * 0.06, ctx.px * 0.06)
    p.fillPath(ctx.path, QColor(40, 10, 60))
    p.restore()
    g = QLinearGradient(QPointF(0, r.top()), QPointF(0, r.bottom()))
    bands = ("#ffe66d", "#ffb347", "#ff6f91", "#c25bff")
    for i, c in enumerate(bands):
        g.setColorAt(i / len(bands), QColor(c))
        g.setColorAt((i + 1) / len(bands) - 0.001, QColor(c))
    p.strokePath(ctx.path, _pen(QColor(40, 10, 60), ctx.px * 0.07))
    p.fillPath(ctx.path, QBrush(g))


def register(api):
    api.register_text_style("txt-3d", "3D Extrude", extrude, pad=0.2, swatch="#ffd166")
    api.register_text_style("txt-comic", "Comic Pop", comic, pad=0.2, swatch="#ffe14d")
    api.register_text_style("txt-chrome", "Chrome", chrome, pad=0.1, swatch="#c9d2dc")
    api.register_text_style("txt-rainbow", "Rainbow", rainbow, pad=0.1, swatch="#34c759")
    api.register_text_style("txt-retro", "Retro Stripes", retro, pad=0.15, swatch="#ff6f91")
