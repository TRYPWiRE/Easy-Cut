"""Renders text clips to transparent images (used by both the preview and the export)."""
import numpy as np

_cache = {}


def render(clip, scale=1.0) -> np.ndarray:
    """BGRA uint8 image of the clip's text. `scale` = canvas short side / 1080."""
    from PyQt6.QtCore import Qt, QRectF
    from PyQt6.QtGui import QImage, QPainter, QFont, QColor, QFontMetricsF, QPainterPath, QPen

    text = clip.get("text") or " "
    key = (text, clip.get("font"), clip.get("font_size"), clip.get("text_color"), clip.get("bold"),
           clip.get("text_bg"), clip.get("text_bg_color"), clip.get("text_outline"), round(scale, 4))
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
        p.drawRoundedRect(QRectF(0, 0, w, h), px * 0.25, px * 0.25)
    path = QPainterPath()
    for i, ln in enumerate(lines):
        x = pad + (width - fm.horizontalAdvance(ln)) / 2
        y = pad + i * line_h + fm.ascent()
        path.addText(x, y, font, ln)
    if clip.get("text_outline", True) and not clip.get("text_bg"):
        pen = QPen(QColor(0, 0, 0, 220), max(1.0, px * 0.08))
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.strokePath(path, pen)
    p.fillPath(path, QColor(clip.get("text_color", "#ffffff")))
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
