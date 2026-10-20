"""Neon & Glow Text - text styles. paint(p, ctx) draws ctx.path; ctx.color is the colour the user picked."""
from PyQt6.QtCore import Qt, QPointF
from PyQt6.QtGui import QColor, QPen, QLinearGradient, QBrush


def _pen(col, width):
    pen = QPen(col, max(0.5, width))
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    return pen


def _glow(p, ctx, col, reach, layers=8):
    for i in range(layers, 0, -1):
        c = QColor(col)
        c.setAlpha(int(18 + 10 * (layers - i) / layers))
        p.strokePath(ctx.path, _pen(c, ctx.px * reach * i / layers))


def neon(p, ctx):
    _glow(p, ctx, ctx.color, 0.55)
    p.strokePath(ctx.path, _pen(ctx.color, ctx.px * 0.07))
    core = QColor(ctx.color).lighter(170)
    p.strokePath(ctx.path, _pen(core, ctx.px * 0.025))


def electric(p, ctx):
    _glow(p, ctx, ctx.color, 0.3, 5)
    p.strokePath(ctx.path, _pen(ctx.color, ctx.px * 0.12))
    p.strokePath(ctx.path, _pen(QColor(255, 255, 255), ctx.px * 0.04))
    p.fillPath(ctx.path, QColor(10, 10, 20, 230))


def glitch(p, ctx):
    off = ctx.px * 0.05
    for dx, col in ((-off, QColor(0, 240, 255, 200)), (off, QColor(255, 0, 170, 200))):
        p.save()
        p.translate(dx, 0)
        p.fillPath(ctx.path, col)
        p.restore()
    p.fillPath(ctx.path, ctx.color)


def hologram(p, ctx):
    r = ctx.rect
    g = QLinearGradient(QPointF(r.left(), r.top()), QPointF(r.right(), r.bottom()))
    g.setColorAt(0, QColor(0, 255, 240))
    g.setColorAt(0.5, QColor(140, 120, 255))
    g.setColorAt(1, QColor(255, 120, 230))
    _glow(p, ctx, QColor(0, 220, 255), 0.3, 5)
    p.fillPath(ctx.path, QBrush(g))
    p.save()
    p.setClipPath(ctx.path)
    step = max(2.0, ctx.px * 0.08)
    y = r.top()
    while y < r.bottom():
        p.fillRect(int(r.left()), int(y), int(r.width()) + 1, max(1, int(step * 0.35)), QColor(255, 255, 255, 70))
        y += step
    p.restore()
    p.strokePath(ctx.path, _pen(QColor(220, 255, 255, 200), ctx.px * 0.015))


def fire(p, ctx):
    r = ctx.rect
    _glow(p, ctx, QColor(255, 110, 0), 0.45)
    g = QLinearGradient(QPointF(0, r.top()), QPointF(0, r.bottom()))
    g.setColorAt(0, QColor(255, 250, 160))
    g.setColorAt(0.45, QColor(255, 170, 0))
    g.setColorAt(1, QColor(220, 30, 0))
    p.fillPath(ctx.path, QBrush(g))


def register(api):
    api.register_text_style("txt-neon", "Neon Glow", neon, pad=0.35, swatch="#ff4fd8")
    api.register_text_style("txt-electric", "Electric", electric, pad=0.2, swatch="#4fd8ff")
    api.register_text_style("txt-glitch", "Glitch", glitch, pad=0.08, swatch="#ff00aa")
    api.register_text_style("txt-hologram", "Hologram", hologram, pad=0.2, swatch="#7cf7ff")
    api.register_text_style("txt-fire", "Fire", fire, pad=0.3, swatch="#ff8a00")
