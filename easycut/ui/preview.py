"""Preview monitor: shows the composited frame and lets you move/scale the selected clip directly."""
import numpy as np
from PyQt6.QtCore import Qt, pyqtSignal, QRectF
from PyQt6.QtGui import QPainter, QColor, QPen, QImage, QFont
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QLabel

from .. import theme, icons
from .widgets import icon_button, fmt_time


class PreviewCanvas(QWidget):
    transformLive = pyqtSignal(float, float, float)    # x, y, scale
    transformDone = pyqtSignal()
    colorPicked = pyqtSignal(float, float)             # canvas fractions
    filesDropped = pyqtSignal(list)
    importRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.img = None
        self.canvas_size = (960, 540)
        self.sel_rect = None          # (cx, cy, w, h) in canvas pixels
        self.sel_clip = None
        self.drag = None
        self.picking = False
        self.empty = True
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        self.setMinimumSize(320, 200)

    def set_frame(self, bgr: np.ndarray):
        h, w = bgr.shape[:2]
        self._buf = np.ascontiguousarray(bgr)
        self.img = QImage(self._buf.data, w, h, w * 3, QImage.Format.Format_BGR888)
        self.canvas_size = (w, h)
        self.update()

    def target_rect(self):
        W, H = self.canvas_size
        m = 14
        aw, ah = self.width() - 2 * m, self.height() - 2 * m
        s = min(aw / W, ah / H)
        dw, dh = W * s, H * s
        return QRectF((self.width() - dw) / 2, (self.height() - dh) / 2, dw, dh), s

    def _sel_screen(self):
        if not self.sel_rect:
            return None
        tr, s = self.target_rect()
        cx, cy, w, h = self.sel_rect
        return QRectF(tr.left() + (cx - w / 2) * s, tr.top() + (cy - h / 2) * s, w * s, h * s)

    def paintEvent(self, ev):
        c = theme.C
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(c["panel"]))
        tr, s = self.target_rect()
        if self.img is not None:
            p.drawImage(tr, self.img)
        p.setPen(QPen(QColor(c["border"]), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(tr.adjusted(-0.5, -0.5, 0.5, 0.5))
        if self.empty:
            p.setPen(QColor(c["text_dim"]))
            f = QFont(self.font())
            f.setPointSizeF(12)
            p.setFont(f)
            p.drawPixmap(int(tr.center().x() - 24), int(tr.center().y() - 50), icons.pixmap("media", 48, c["accent"]))
            p.drawText(tr.adjusted(0, 20, 0, 0), Qt.AlignmentFlag.AlignCenter,
                       "Drop videos, photos or music here\nor click to import")
        sr = self._sel_screen()
        if sr is not None and not self.picking:
            col = QColor(c["accent"])
            p.setPen(QPen(col, 1.5, Qt.PenStyle.DashLine))
            p.drawRect(sr)
            p.setPen(QPen(col, 1.5))
            p.setBrush(QColor(c["text_strong"] if not c.get("cyber") else c["accent"]))
            for pt in (sr.topLeft(), sr.topRight(), sr.bottomLeft(), sr.bottomRight()):
                p.drawEllipse(pt, 5, 5)
        if self.picking:
            p.setPen(QColor(c["text_strong"]))
            p.drawText(tr.adjusted(8, 8, -8, -8), Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter,
                       "Click the colour to remove (Esc to cancel)")

    def _corner_hit(self, pos):
        sr = self._sel_screen()
        if sr is None:
            return None
        for name, pt in (("tl", sr.topLeft()), ("tr", sr.topRight()), ("bl", sr.bottomLeft()),
                         ("br", sr.bottomRight())):
            if (pt - pos).manhattanLength() < 14:
                return name
        return None

    def mousePressEvent(self, ev):
        pos = ev.position()
        tr, s = self.target_rect()
        if self.picking:
            if tr.contains(pos):
                self.colorPicked.emit((pos.x() - tr.left()) / tr.width(), (pos.y() - tr.top()) / tr.height())
            self.picking = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self.update()
            return
        if self.empty:
            self.importRequested.emit()
            return
        if self.sel_clip is None or ev.button() != Qt.MouseButton.LeftButton:
            return
        corner = self._corner_hit(pos)
        sr = self._sel_screen()
        if corner or (sr is not None and sr.contains(pos)):
            c = self.sel_clip
            self.drag = {"mode": "scale" if corner else "move", "p0": pos, "x0": float(c.get("x", 0)),
                         "y0": float(c.get("y", 0)), "s0": float(c.get("scale", 1)),
                         "center": sr.center(), "d0": max(4.0, (pos - sr.center()).manhattanLength())}

    def mouseMoveEvent(self, ev):
        pos = ev.position()
        if self.drag is None:
            if self.picking:
                self.setCursor(Qt.CursorShape.CrossCursor)
            elif self._corner_hit(pos):
                self.setCursor(Qt.CursorShape.SizeFDiagCursor)
            elif self._sel_screen() is not None and self._sel_screen().contains(pos):
                self.setCursor(Qt.CursorShape.SizeAllCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)
            return
        tr, s = self.target_rect()
        d = self.drag
        if d["mode"] == "move":
            dx = (pos.x() - d["p0"].x()) / tr.width()
            dy = (pos.y() - d["p0"].y()) / tr.height()
            nx, ny = d["x0"] + dx, d["y0"] + dy
            # gentle snap to centre lines
            if abs(nx) < 0.012:
                nx = 0.0
            if abs(ny) < 0.012:
                ny = 0.0
            self.transformLive.emit(nx, ny, d["s0"])
        else:
            dist = max(4.0, (pos - d["center"]).manhattanLength())
            ns = max(0.05, min(8.0, d["s0"] * dist / d["d0"]))
            self.transformLive.emit(d["x0"], d["y0"], ns)

    def mouseReleaseEvent(self, ev):
        if self.drag is not None:
            self.drag = None
            self.transformDone.emit()

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key.Key_Escape and self.picking:
            self.picking = False
            self.update()
        else:
            super().keyPressEvent(ev)

    def dragEnterEvent(self, ev):
        if ev.mimeData().hasUrls() or ev.mimeData().hasFormat("application/x-easycut-media"):
            ev.acceptProposedAction()

    def dropEvent(self, ev):
        md = ev.mimeData()
        if md.hasFormat("application/x-easycut-media"):
            paths = bytes(md.data("application/x-easycut-media")).decode("utf-8").split("\n")
        else:
            paths = [u.toLocalFile() for u in md.urls() if u.isLocalFile()]
        if paths:
            self.filesDropped.emit([p for p in paths if p])


class PreviewPanel(QWidget):
    """Canvas + transport controls."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Panel")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 6)
        lay.setSpacing(4)
        self.canvas = PreviewCanvas()
        lay.addWidget(self.canvas, 1)
        bar = QHBoxLayout()
        bar.setContentsMargins(12, 0, 12, 0)
        self.time_label = QLabel("00:00.00")
        self.time_label.setObjectName("Timecode")
        self.dur_label = QLabel("/ 00:00.00")
        self.dur_label.setObjectName("Dim")
        bar.addWidget(self.time_label)
        bar.addWidget(self.dur_label)
        bar.addStretch(1)
        self.btn_start = icon_button("start", "Go to start (Home)", 18)
        self.btn_back = icon_button("frame_back", "Previous frame (←)", 18)
        self.btn_play = icon_button("play", "Play / Pause (Space)", 22)
        self.btn_fwd = icon_button("frame_fwd", "Next frame (→)", 18)
        self.btn_end = icon_button("end", "Go to end (End)", 18)
        for b in (self.btn_start, self.btn_back, self.btn_play, self.btn_fwd, self.btn_end):
            bar.addWidget(b)
        bar.addStretch(1)
        self.info = QLabel("")
        self.info.setObjectName("Dim")
        self.info.setMinimumWidth(150)
        self.info.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        bar.addWidget(self.info)
        lay.addLayout(bar)

    def set_playing(self, playing):
        icons.bind(self.btn_play, "pause" if playing else "play", 22)

    def set_time(self, t, dur, fps):
        self.time_label.setText(fmt_time(t, fps, frames=True))
        self.dur_label.setText("/ " + fmt_time(dur, fps, frames=True))
