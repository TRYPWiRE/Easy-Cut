"""Renders text clips to transparent images (used by both the preview and the export).

Also holds the registries for text styles (how the letters are painted) and fonts (bundled font files that
font packs add). Extensions add to both through the extension API.
"""
import os

import numpy as np

_cache = {}


# ====================================================================== text styles
class StyleContext:
    """What a style's paint function gets: sizes, colours and the clip."""

    def __init__(self, clip, px, w, h, path, color, scale):
        self.clip = clip
        self.px = px                  # font size in pixels
        self.w = w
        self.h = h
        self.path = path              # QPainterPath of the letters
        self.color = color            # QColor chosen by the user
        self.scale = scale            # canvas short side / 1080
        self.rect = path.boundingRect()


class TextStyle:
    def __init__(self, sid, name, paint=None, pad=0.0, source="built-in", swatch=None):
        self.id = sid
        self.name = name
        self.paint = paint            # fn(painter, ctx) -> None  (None = classic)
        self.pad = pad                # extra room around the text, as a fraction of the font size
        self.source = source
        self.swatch = swatch


def _paint_shadow(p, ctx):
    from PyQt6.QtGui import QColor
    off = max(1.0, ctx.px * 0.06)
    for i, a in ((3, 40), (2, 70), (1, 120)):
        p.save()
        p.translate(off * i * 0.6, off * i * 0.6)
        p.fillPath(ctx.path, QColor(0, 0, 0, a))
        p.restore()
    p.fillPath(ctx.path, ctx.color)


def _paint_hollow(p, ctx):
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QPen
    pen = QPen(ctx.color, max(1.5, ctx.px * 0.05))
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.strokePath(ctx.path, pen)


STYLES = {}
STYLE_ORDER = []


def register_style(s: TextStyle):
    if s.id not in STYLES:
        STYLE_ORDER.append(s.id)
    STYLES[s.id] = s
    _cache.clear()
    return s


register_style(TextStyle("none", "Classic"))
register_style(TextStyle("shadow", "Drop Shadow", _paint_shadow, pad=0.2))
register_style(TextStyle("hollow", "Hollow", _paint_hollow, pad=0.05))


def get_style(sid) -> TextStyle:
    return STYLES.get(sid) or STYLES["none"]


# ====================================================================== fonts
# id -> {"family", "name", "source"}; built-ins are common fonts every Windows PC has
FONTS = {}
FONT_ORDER = []
for _fam in ("Segoe UI", "Arial Black", "Impact", "Georgia", "Comic Sans MS", "Consolas", "Trebuchet MS",
             "Times New Roman"):
    _fid = "sys-" + _fam.lower().replace(" ", "-")
    FONTS[_fid] = {"family": _fam, "name": _fam, "source": "built-in"}
    FONT_ORDER.append(_fid)


def register_font(fid, name, path, source="extension"):
    """Load a font file for the whole app. Returns the family name (or None)."""
    from PyQt6.QtGui import QFontDatabase
    if not os.path.isfile(path):
        return None
    font_id = QFontDatabase.addApplicationFont(path)
    fams = QFontDatabase.applicationFontFamilies(font_id) if font_id >= 0 else []
    if not fams:
        return None
    if fid not in FONTS:
        FONT_ORDER.append(fid)
    FONTS[fid] = {"family": fams[0], "name": name, "source": source}
    _cache.clear()
    return fams[0]


def font_by_family(family):
    for fid, f in FONTS.items():
        if f["family"] == family:
            return fid
    return None


# ====================================================================== render
def render(clip, scale=1.0) -> np.ndarray:
    """BGRA uint8 image of the clip's text. `scale` = canvas short side / 1080."""
    from PyQt6.QtCore import Qt, QRectF
    from PyQt6.QtGui import QImage, QPainter, QFont, QColor, QFontMetricsF, QPainterPath, QPen

    text = clip.get("text") or " "
    style = get_style(clip.get("text_style", "none"))
    key = (text, clip.get("font"), clip.get("font_size"), clip.get("text_color"), clip.get("bold"),
           clip.get("text_bg"), clip.get("text_bg_color"), clip.get("text_outline"), style.id, round(scale, 4))
    if key in _cache:
        return _cache[key]
    px = max(4, int(round(float(clip.get("font_size", 80)) * scale)))
    font = QFont(clip.get("font") or "Segoe UI")
    font.setPixelSize(px)
    font.setBold(bool(clip.get("bold", True)))
    fm = QFontMetricsF(font)
    lines = text.split("\n")
    line_h = fm.height()
    width = max(fm.horizontalAdvance(ln) for ln in lines)
    pad = px * 0.35 if clip.get("text_bg") else px * 0.12
    pad += px * style.pad
    w = int(width + pad * 2) + 2
    h = int(line_h * len(lines) + pad * 2) + 2
    w, h = max(2, w + (w & 1)), max(2, h + (h & 1))
    img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    if clip.get("text_bg"):
        p.setPen(Qt.PenStyle.NoPen)
        bg = QColor(clip.get("text_bg_color", "#000000"))
        bg.setAlpha(200)
        p.setBrush(bg)
        inset = px * style.pad
        p.drawRoundedRect(QRectF(inset, inset, w - 2 * inset, h - 2 * inset), px * 0.25, px * 0.25)
    path = QPainterPath()
    for i, ln in enumerate(lines):
        x = pad + (width - fm.horizontalAdvance(ln)) / 2
        y = pad + i * line_h + fm.ascent()
        path.addText(x, y, font, ln)
    color = QColor(clip.get("text_color", "#ffffff"))
    if style.paint is not None:
        try:
            p.save()
            style.paint(p, StyleContext(clip, px, w, h, path, color, scale))
            p.restore()
        except Exception:
            p.restore()
            p.fillPath(path, color)
    else:
        if clip.get("text_outline", True) and not clip.get("text_bg"):
            pen = QPen(QColor(0, 0, 0, 220), max(1.0, px * 0.08))
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.strokePath(path, pen)
        p.fillPath(path, color)
    p.end()
    img = img.convertToFormat(QImage.Format.Format_ARGB32)
    ptr = img.constBits()
    ptr.setsize(img.sizeInBytes())
    arr = np.frombuffer(ptr, np.uint8).reshape(h, img.bytesPerLine() // 4, 4)[:, :w].copy()
    if len(_cache) > 64:
        _cache.clear()
    _cache[key] = arr
    return arr


def save_png(clip, scale, path):
    import cv2
    arr = render(clip, scale)
    ok, buf = cv2.imencode(".png", arr)
    if ok:
        buf.tofile(path)
    return arr.shape[1], arr.shape[0]
