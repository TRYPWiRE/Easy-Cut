"""The timeline: tracks, clips, ruler and playhead - drag to move, drag edges to trim, snapping, drops."""
import threading
import queue

import numpy as np
from PyQt6.QtCore import Qt, pyqtSignal, QRectF, QPointF, QObject, QTimer, QMimeData
from PyQt6.QtGui import QPainter, QColor, QPen, QFont, QImage, QPainterPath, QPolygonF, QFontMetrics
from PyQt6.QtWidgets import QWidget, QMenu, QScrollBar

from .. import theme, media, icons
from .widgets import fmt_time

HEADER_W = 132
RULER_H = 28
H_VIDEO = 62
H_AUDIO = 46
EDGE = 7
MEDIA_MIME = "application/x-easycut-media"


# ---------------------------------------------------------------------- background thumbnails / waveforms
class _Signals(QObject):
    ready = pyqtSignal()


class ThumbCache:
    def __init__(self):
        self.thumbs = {}
        self.waves = {}
        self.pending = set()
        self.q = queue.Queue()
        self.sig = _Signals()
        self.readers = {}
        threading.Thread(target=self._work, daemon=True).start()

    def thumb(self, path, t, h):
        key = (path, round(t, 0), h)
        img = self.thumbs.get(key)
        if img is None and key not in self.pending:
            self.pending.add(key)
            self.q.put(("thumb", key))
        return img

    def image_thumb(self, path, h):
        key = (path, -1, h)
        img = self.thumbs.get(key)
        if img is None and key not in self.pending:
            self.pending.add(key)
            self.q.put(("image", key))
        return img

    def wave(self, path):
        w = self.waves.get(path)
        if w is None and ("wave", path) not in self.pending:
            self.pending.add(("wave", path))
            self.q.put(("wave", path))
        return w

    def _work(self):
        import cv2
        while True:
            kind, key = self.q.get()
            try:
                if kind == "wave":
                    self.waves[key] = np.array(media.waveform(key, points=2000) or [0.0], np.float32)
                    self.pending.discard(("wave", key))
                elif kind == "image":
                    path, _, h = key
                    img = media.read_image(path)
                    self.thumbs[key] = self._to_qimage(img, h, cv2) if img is not None else QImage()
                    self.pending.discard(key)
                else:
                    path, t, h = key
                    r = self.readers.get(path)
                    if r is None:
                        r = media.FrameReader(path, max_size=(320, 180))
                        self.readers[path] = r
                    f = r.frame_at(t)
                    self.thumbs[key] = self._to_qimage(cv2.cvtColor(f, cv2.COLOR_BGR2BGRA), h, cv2) \
                        if f is not None else QImage()
                    self.pending.discard(key)
                if len(self.thumbs) > 3000:
                    self.thumbs.clear()
                self.sig.ready.emit()
            except Exception:
                self.pending.discard(key)

    @staticmethod
    def _to_qimage(bgra, h, cv2):
        ih, iw = bgra.shape[:2]
        w = max(1, int(iw * h / ih))
        small = np.ascontiguousarray(cv2.resize(bgra, (w, h), interpolation=cv2.INTER_AREA))
        return QImage(small.data, w, h, w * 4, QImage.Format.Format_ARGB32).copy()


CACHE = None


def cache():
    global CACHE
    if CACHE is None:
        CACHE = ThumbCache()
    return CACHE


# ---------------------------------------------------------------------- timeline widget
class Timeline(QWidget):
    seekRequested = pyqtSignal(float)
    selectionChanged = pyqtSignal(list)
    edited = pyqtSignal(str)
    liveChanged = pyqtSignal()           # while dragging (for preview refresh)
    dropMedia = pyqtSignal(list, float, int)
    contextAction = pyqtSignal(str)
    zoomChanged = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.project = None
        self.playhead = 0.0
        self.selected = []
        self.pps = 80.0
        self.scroll_x = 0.0
        self.scroll_y = 0
        self.snap = True
        self.drag = None
        self.snap_line = None
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        self.setMinimumHeight(170)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        cache().sig.ready.connect(self._thumbs_ready)
        self._repaint_timer = QTimer(self, singleShot=True, interval=60, timeout=self.update)

    def _thumbs_ready(self):
        if not self._repaint_timer.isActive():
            self._repaint_timer.start()

    # ------------------------------------------------------------ geometry
    def set_project(self, p):
        self.project = p
        self.selected = [s for s in self.selected if p.clip(s)]
        self.update()

    def track_h(self, i):
        return H_VIDEO if self.project.tracks[i]["type"] == "video" else H_AUDIO

    def track_y(self, i):
        y = RULER_H + 4 - self.scroll_y
        for k in range(i):
            y += self.track_h(k) + 3
        return y

    def content_height(self):
        if not self.project:
            return 0
        return RULER_H + 4 + sum(self.track_h(i) + 3 for i in range(len(self.project.tracks))) + 20

    def track_at(self, y):
        for i in range(len(self.project.tracks)):
            ty = self.track_y(i)
            if ty - 2 <= y < ty + self.track_h(i) + 2:
                return i
        return -1

    def x_of(self, t):
        return HEADER_W + (t - self.scroll_x) * self.pps

    def t_of(self, x):
        return max(0.0, (x - HEADER_W) / self.pps + self.scroll_x)

    def clip_rect(self, c):
        y = self.track_y(c["track"])
        return QRectF(self.x_of(c["start"]), y, max(2.0, c["duration"] * self.pps), self.track_h(c["track"]))

    def clip_at(self, pos):
        for c in reversed(self.project.clips):
            if c["track"] < len(self.project.tracks) and self.clip_rect(c).adjusted(-2, 0, 2, 0).contains(pos):
                return c
        return None

    def visible_seconds(self):
        return max(1.0, (self.width() - HEADER_W) / self.pps)

    def set_zoom(self, pps, anchor_t=None):
        if anchor_t is None:
            anchor_t = self.playhead
        ax = self.x_of(anchor_t)
        self.pps = min(800.0, max(4.0, pps))
        self.scroll_x = max(0.0, anchor_t - (ax - HEADER_W) / self.pps)
        self.zoomChanged.emit()
        self.update()

    def zoom_to_fit(self):
        d = max(5.0, self.project.duration() * 1.08)
        self.pps = min(800.0, max(4.0, (self.width() - HEADER_W - 20) / d))
        self.scroll_x = 0
        self.zoomChanged.emit()
        self.update()

    def ensure_visible(self, t):
        vis = self.visible_seconds()
        if t < self.scroll_x or t > self.scroll_x + vis * 0.95:
            self.scroll_x = max(0.0, t - vis * 0.1)
            self.zoomChanged.emit()

    # ------------------------------------------------------------ snapping
    def snap_points(self, exclude=()):
        pts = [0.0, self.playhead]
        for c in self.project.clips:
            if c["id"] in exclude:
                continue
            pts += [c["start"], c.end]
        return pts

    def snap_t(self, t, exclude=(), extra_offsets=(0.0,)):
        """Snap t (or t+offset) to nearby points; returns (snapped_t, line_t or None)."""
        if not self.snap:
            return t, None
        thr = 9 / self.pps
        best, line = None, None
        for p in self.snap_points(exclude):
            for off in extra_offsets:
                d = abs((t + off) - p)
                if d < thr and (best is None or d < best[0]):
                    best = (d, p - off)
                    line = p
        return (best[1], line) if best else (t, None)

    # ------------------------------------------------------------ painting
    def paintEvent(self, ev):
        if not self.project:
            return
        c = theme.C
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()
        p.fillRect(self.rect(), QColor(c["timeline_bg"]))
        f = QFont(self.font())
        f.setPointSizeF(8.5)
        p.setFont(f)
        fm = QFontMetrics(f)
        rad = min(6, c["radius"])
        # tracks
        for i, tr in enumerate(self.project.tracks):
            y = self.track_y(i)
            h = self.track_h(i)
            if y > H or y + h < RULER_H:
                continue
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(c["track_bg"]))
            p.drawRect(QRectF(HEADER_W, y, W - HEADER_W, h))
        # clips
        p.save()
        p.setClipRect(QRectF(HEADER_W, RULER_H, W - HEADER_W, H - RULER_H))
        for clip in self.project.clips:
            if clip["track"] >= len(self.project.tracks):
                continue
            r = self.clip_rect(clip)
            if r.right() < HEADER_W or r.left() > W or r.bottom() < RULER_H or r.top() > H:
                continue
            self.paint_clip(p, clip, r, fm, rad)
        if self.snap_line is not None:
            x = self.x_of(self.snap_line)
            p.setPen(QPen(QColor(c["accent2"]), 1.4, Qt.PenStyle.DashLine))
            p.drawLine(QPointF(x, RULER_H), QPointF(x, H))
        p.restore()
        # headers
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(c["panel"]))
        p.drawRect(QRectF(0, RULER_H, HEADER_W, H))
        for i, tr in enumerate(self.project.tracks):
            y = self.track_y(i)
            h = self.track_h(i)
            if y > H or y + h < RULER_H:
                continue
            p.save()
            p.setClipRect(QRectF(0, RULER_H, HEADER_W, H))
            p.setPen(QColor(c["text"]))
            kind_icon = "media" if tr["type"] == "video" else "music"
            p.drawPixmap(int(10), int(y + h / 2 - 9), icons.pixmap(kind_icon, 18, c["text_dim"]))
            p.drawText(QRectF(34, y, HEADER_W - 80, h), Qt.AlignmentFlag.AlignVCenter, tr["name"])
            name = ("eye_off" if tr["hidden"] else "eye") if tr["type"] == "video" else ("mute" if tr["muted"] else "volume")
            active = tr["hidden"] or tr["muted"]
            p.drawPixmap(int(HEADER_W - 40), int(y + h / 2 - 9),
                         icons.pixmap(name, 18, c["accent"] if active else c["text_dim"]))
            p.restore()
        p.setPen(QPen(QColor(c["border"]), 1))
        p.drawLine(HEADER_W, RULER_H, HEADER_W, H)
        # ruler
        p.fillRect(QRectF(0, 0, W, RULER_H), QColor(c["panel"]))
        p.setPen(QPen(QColor(c["border"]), 1))
        p.drawLine(0, RULER_H, W, RULER_H)
        step = self._tick_step()
        t = (int(self.scroll_x / step)) * step
        end = self.scroll_x + self.visible_seconds() + step
        p.setPen(QColor(c["text_dim"]))
        while t <= end:
            x = self.x_of(t)
            if x >= HEADER_W:
                p.drawLine(QPointF(x, RULER_H - 9), QPointF(x, RULER_H))
                p.drawText(QPointF(x + 3, RULER_H - 11), fmt_time(t).replace(".00", ""))
                for k in range(1, 5):
                    sx = x + k * step * self.pps / 5
                    p.drawLine(QPointF(sx, RULER_H - 4), QPointF(sx, RULER_H))
            t += step
        p.setPen(QColor(c["text_strong"]))
        p.drawText(QRectF(10, 0, HEADER_W - 12, RULER_H), Qt.AlignmentFlag.AlignVCenter,
                   fmt_time(self.playhead, self.project.fps, frames=True))
        # playhead
        x = self.x_of(self.playhead)
        if x >= HEADER_W - 1:
            col = QColor(c["playhead"])
            p.setPen(QPen(col, 2))
            p.drawLine(QPointF(x, RULER_H - 6), QPointF(x, H))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            p.drawPolygon(QPolygonF([QPointF(x - 7, 2), QPointF(x + 7, 2), QPointF(x + 7, RULER_H - 12),
                                     QPointF(x, RULER_H - 4), QPointF(x - 7, RULER_H - 12)]))

    def _tick_step(self):
        for s in (0.1, 0.25, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600):
            if s * self.pps >= 70:
                return s
        return 1200

    def paint_clip(self, p, clip, r, fm, rad):
        c = theme.C
        kind = clip["kind"]
        col = QColor(c["clip_" + ("image" if kind == "image" else "text" if kind == "text" else
                                  "audio" if kind == "audio" else "video")])
        sel = clip["id"] in self.selected
        path = QPainterPath()
        path.addRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), rad, rad)
        p.save()
        p.setClipPath(path, Qt.ClipOperation.IntersectClip)
        dark = QColor(col).darker(260)
        p.fillRect(r, dark)
        # filmstrip
        h_thumb = int(r.height() - 18) if clip.has_sound and kind == "video" else int(r.height() - 16)
        if kind in ("video", "image") and h_thumb > 8:
            tw = max(16, int(h_thumb * 16 / 9))
            x = r.left()
            vis_l = max(r.left(), HEADER_W) - tw
            while x < r.right():
                if x + tw >= vis_l and x <= self.width():
                    if kind == "video":
                        t = clip.source_time(clip["start"] + (x - r.left()) / self.pps)
                        img = cache().thumb(clip["path"], max(0.0, t), h_thumb)
                    else:
                        img = cache().image_thumb(clip["path"], h_thumb)
                    if img is not None and not img.isNull():
                        p.drawImage(QPointF(x, r.top() + 16), img)
                        tw = max(16, img.width())
                x += tw
        # waveform
        if clip.has_sound:
            wave = cache().wave(clip["path"])
            wy = r.top() + (16 if kind == "audio" else r.height() - 16)
            wh = (r.height() - 20) if kind == "audio" else 14
            if wave is not None and len(wave) > 1 and clip["source_duration"] > 0:
                p.setPen(Qt.PenStyle.NoPen)
                wc = QColor(col).lighter(150) if kind == "audio" else QColor(c["clip_audio"]).lighter(130)
                wc.setAlpha(220)
                p.setBrush(wc)
                n = len(wave)
                left = max(r.left(), HEADER_W)
                right = min(r.right(), self.width())
                step = 2
                xx = left
                vol = min(2.0, float(clip.get("volume", 1.0))) if not clip.get("muted") else 0.0
                while xx < right:
                    st = clip.source_time(clip["start"] + (xx - r.left()) / self.pps)
                    idx = int(st / clip["source_duration"] * n)
                    if 0 <= idx < n:
                        a = float(wave[idx]) * min(1.0, vol)
                        hh = max(1.0, a * wh)
                        p.drawRect(QRectF(xx, wy + (wh - hh) / 2 if kind == "audio" else wy + wh - hh, 1.4, hh))
                    xx += step
        # title bar
        p.fillRect(QRectF(r.left(), r.top(), r.width(), 16), col)
        p.setPen(QColor("#ffffff") if theme.is_dark(col.name()) else QColor("#111111"))
        label = clip["text"].split("\n")[0] if kind == "text" else clip["name"]
        tags = []
        if abs(float(clip.get("speed", 1)) - 1) > 0.001:
            tags.append(f"{clip['speed']:.2g}x")
        if clip.get("filter", "none") != "none":
            tags.append("✦")
        if clip.get("chroma"):
            tags.append("Key")
        if clip.get("stabilize"):
            tags.append("Stab")
        if clip.get("anim_in", "none") != "none" or clip.get("anim_out", "none") != "none":
            tags.append("◆")
        text = (" · ".join(tags) + "  " if tags else "") + label
        tx = max(r.left() + 5, HEADER_W + 4) if r.left() < HEADER_W else r.left() + 5
        p.drawText(QRectF(tx, r.top(), max(0, r.right() - tx - 4), 16), Qt.AlignmentFlag.AlignVCenter,
                   fm.elidedText(text, Qt.TextElideMode.ElideRight, int(max(0, r.right() - tx - 4))))
        if kind == "text":
            p.setPen(QColor("#ffffff"))
            f2 = QFont(p.font())
            f2.setBold(True)
            f2.setPointSizeF(10)
            p.save()
            p.setFont(f2)
            p.drawText(QRectF(tx, r.top() + 16, max(0, r.right() - tx - 4), r.height() - 16),
                       Qt.AlignmentFlag.AlignVCenter, fm.elidedText(label, Qt.TextElideMode.ElideRight,
                                                                    int(max(0, r.right() - tx - 4))))
            p.restore()
        # animation ramps
        for which in ("in", "out"):
            if clip.get(f"anim_{which}", "none") != "none":
                w = min(r.width() / 2, float(clip.get(f"anim_{which}_dur", 0.5)) * self.pps)
                ac = QColor("#ffffff")
                ac.setAlpha(55)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(ac)
                if which == "in":
                    p.drawPolygon(QPolygonF([QPointF(r.left(), r.bottom()), QPointF(r.left() + w, r.top() + 16),
                                             QPointF(r.left(), r.top() + 16)]))
                else:
                    p.drawPolygon(QPolygonF([QPointF(r.right(), r.bottom()), QPointF(r.right() - w, r.top() + 16),
                                             QPointF(r.right(), r.top() + 16)]))
        p.restore()
        # border
        if sel:
            p.setPen(QPen(QColor(c["text_strong"] if not c.get("cyber") else c["accent"]), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r.adjusted(1, 1, -1, -1), rad, rad)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(c["text_strong"] if not c.get("cyber") else c["accent"]))
            hh = r.height() * 0.4
            p.drawRoundedRect(QRectF(r.left() + 1, r.center().y() - hh / 2, 4, hh), 2, 2)
            p.drawRoundedRect(QRectF(r.right() - 5, r.center().y() - hh / 2, 4, hh), 2, 2)
        else:
            p.setPen(QPen(QColor(col).darker(140), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), rad, rad)

    # ------------------------------------------------------------ mouse
    def mousePressEvent(self, ev):
        if not self.project:
            return
        pos = ev.position()
        self.setFocus()
        if ev.button() == Qt.MouseButton.RightButton:
            clip = self.clip_at(pos)
            if clip and clip["id"] not in self.selected:
                self.selected = [clip["id"]]
                self.selectionChanged.emit(self.selected)
                self.update()
            self._context(ev.globalPosition().toPoint(), clip)
            return
        if ev.button() != Qt.MouseButton.LeftButton:
            return
        ph_x = self.x_of(self.playhead)
        if pos.y() < RULER_H or (abs(pos.x() - ph_x) < 5 and pos.x() > HEADER_W and pos.y() < RULER_H + 10):
            if pos.x() > HEADER_W:
                self.drag = {"mode": "playhead"}
                self.seekRequested.emit(self.t_of(pos.x()))
            return
        if pos.x() < HEADER_W:
            ti = self.track_at(pos.y())
            if ti >= 0 and pos.x() > HEADER_W - 46:
                tr = self.project.tracks[ti]
                if tr["type"] == "video":
                    tr["hidden"] = not tr["hidden"]
                    self.edited.emit("Hide track" if tr["hidden"] else "Show track")
                else:
                    tr["muted"] = not tr["muted"]
                    self.edited.emit("Mute track" if tr["muted"] else "Unmute track")
                self.update()
            return
        clip = self.clip_at(pos)
        mods = ev.modifiers()
        if clip is None:
            if not (mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)):
                self.selected = []
                self.selectionChanged.emit(self.selected)
            self.drag = {"mode": "playhead"}
            self.seekRequested.emit(self.t_of(pos.x()))
            self.update()
            return
        if mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier):
            if clip["id"] in self.selected:
                self.selected.remove(clip["id"])
            else:
                self.selected.append(clip["id"])
        elif clip["id"] not in self.selected:
            self.selected = [clip["id"]]
        self.selectionChanged.emit(self.selected)
        r = self.clip_rect(clip)
        mode = "move"
        if pos.x() - r.left() < EDGE and r.width() > EDGE * 3:
            mode = "trim_l"
        elif r.right() - pos.x() < EDGE and r.width() > EDGE * 3:
            mode = "trim_r"
        orig = {cid: (self.project.clip(cid)["start"], self.project.clip(cid)["duration"],
                      self.project.clip(cid)["in_point"], self.project.clip(cid)["track"])
                for cid in self.selected if self.project.clip(cid)}
        self.drag = {"mode": mode, "clip": clip, "x0": pos.x(), "orig": orig, "changed": False}
        self.update()

    def mouseMoveEvent(self, ev):
        if not self.project:
            return
        pos = ev.position()
        if self.drag is None:
            clip = self.clip_at(pos)
            cur = Qt.CursorShape.ArrowCursor
            if clip:
                r = self.clip_rect(clip)
                if (pos.x() - r.left() < EDGE or r.right() - pos.x() < EDGE) and r.width() > EDGE * 3:
                    cur = Qt.CursorShape.SizeHorCursor
                else:
                    cur = Qt.CursorShape.OpenHandCursor
            elif pos.y() < RULER_H and pos.x() > HEADER_W:
                cur = Qt.CursorShape.PointingHandCursor
            self.setCursor(cur)
            return
        d = self.drag
        if d["mode"] == "playhead":
            t = self.t_of(pos.x())
            if self.snap and not (ev.modifiers() & Qt.KeyboardModifier.AltModifier):
                pts = [p for p in self.snap_points() if p != self.playhead]
                for sp in pts:
                    if abs(sp - t) * self.pps < 7:
                        t = sp
                        break
            self.seekRequested.emit(t)
            self._autoscroll(pos.x())
            return
        clip = d["clip"]
        dt = (pos.x() - d["x0"]) / self.pps
        s0, dur0, in0, tr0 = d["orig"][clip["id"]]
        no_snap = bool(ev.modifiers() & Qt.KeyboardModifier.AltModifier)
        self.snap_line = None
        if d["mode"] == "move":
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            new_start = max(0.0, s0 + dt)
            if not no_snap:
                new_start, self.snap_line = self.snap_t(new_start, exclude=set(d["orig"]), extra_offsets=(0.0, dur0))
                new_start = max(0.0, new_start)
            delta = new_start - s0
            # track change (single clip only, same track type)
            target = tr0
            if len(d["orig"]) == 1:
                ti = self.track_at(pos.y())
                if ti >= 0 and self.project.tracks[ti]["type"] == self.project.tracks[tr0]["type"]:
                    target = ti
            ok = True
            for cid, (cs, cd, ci, ct) in d["orig"].items():
                c2 = self.project.clip(cid)
                tt = target if cid == clip["id"] else ct
                ns = max(0.0, cs + delta)
                if not self._free(tt, ns, ns + cd, set(d["orig"])):
                    ok = False
                    break
            if ok:
                for cid, (cs, cd, ci, ct) in d["orig"].items():
                    c2 = self.project.clip(cid)
                    c2["start"] = max(0.0, cs + delta)
                    c2["track"] = target if cid == clip["id"] else ct
                d["changed"] = True
        elif d["mode"] == "trim_l":
            speed = clip["speed"] if clip["kind"] in ("video", "audio") else 1.0
            new_start = s0 + dt
            if not no_snap:
                new_start, self.snap_line = self.snap_t(new_start, exclude={clip["id"]})
            new_start = min(new_start, s0 + dur0 - 0.1)
            new_start = max(new_start, 0.0)
            if clip["kind"] in ("video", "audio"):
                new_start = max(new_start, s0 - in0 / speed)
            prev_end = max([c.end for c in self.project.clips_on(clip["track"])
                            if c["id"] != clip["id"] and c.end <= s0 + 1e-6], default=0.0)
            new_start = max(new_start, prev_end)
            delta = new_start - s0
            clip["start"] = new_start
            clip["duration"] = dur0 - delta
            if clip["kind"] in ("video", "audio"):
                clip["in_point"] = max(0.0, in0 + delta * speed)
            d["changed"] = True
        elif d["mode"] == "trim_r":
            new_end = s0 + dur0 + dt
            if not no_snap:
                new_end, self.snap_line = self.snap_t(new_end, exclude={clip["id"]})
            nxt = min([c["start"] for c in self.project.clips_on(clip["track"])
                       if c["id"] != clip["id"] and c["start"] >= s0 + dur0 - 1e-6], default=1e9)
            new_end = min(new_end, nxt)
            dur = max(0.1, min(new_end - s0, clip.max_duration()))
            clip["duration"] = dur
            d["changed"] = True
        self._autoscroll(pos.x())
        self.liveChanged.emit()
        self.update()

    def _free(self, track, start, end, ignore_ids):
        for c in self.project.clips_on(track):
            if c["id"] in ignore_ids:
                continue
            if c["start"] < end - 1e-6 and c.end > start + 1e-6:
                return False
        return True

    def _autoscroll(self, x):
        if x > self.width() - 30:
            self.scroll_x += 8 / self.pps
            self.zoomChanged.emit()
        elif x < HEADER_W + 10 and self.scroll_x > 0:
            self.scroll_x = max(0.0, self.scroll_x - 8 / self.pps)
            self.zoomChanged.emit()

    def mouseReleaseEvent(self, ev):
        d = self.drag
        self.drag = None
        self.snap_line = None
        if d and d.get("changed"):
            names = {"move": "Move clip", "trim_l": "Trim clip", "trim_r": "Trim clip"}
            self.edited.emit(names.get(d["mode"], "Edit"))
        self.update()

    def mouseDoubleClickEvent(self, ev):
        clip = self.clip_at(ev.position())
        if clip:
            self.contextAction.emit("focus_inspector")

    def wheelEvent(self, ev):
        dy = ev.angleDelta().y() or ev.angleDelta().x()
        mods = ev.modifiers()
        if mods & Qt.KeyboardModifier.ControlModifier:
            t = self.t_of(ev.position().x())
            self.set_zoom(self.pps * (1.18 if dy > 0 else 1 / 1.18), anchor_t=t)
        elif mods & Qt.KeyboardModifier.AltModifier:
            maxy = max(0, self.content_height() - self.height())
            self.scroll_y = int(min(maxy, max(0, self.scroll_y - dy / 2)))
            self.update()
        else:
            if abs(ev.angleDelta().y()) >= abs(ev.angleDelta().x()) and not (mods & Qt.KeyboardModifier.ShiftModifier):
                maxy = max(0, self.content_height() - self.height())
                if maxy > 0 and not (mods & Qt.KeyboardModifier.ShiftModifier) and ev.position().x() < HEADER_W:
                    self.scroll_y = int(min(maxy, max(0, self.scroll_y - dy / 2)))
                else:
                    self.scroll_x = max(0.0, self.scroll_x - dy / self.pps * 0.6)
            else:
                self.scroll_x = max(0.0, self.scroll_x - dy / self.pps * 0.6)
            self.zoomChanged.emit()
            self.update()

    def resizeEvent(self, ev):
        maxy = max(0, self.content_height() - self.height())
        self.scroll_y = min(self.scroll_y, maxy)
        super().resizeEvent(ev)

    def _context(self, gpos, clip):
        m = QMenu(self)
        if clip:
            m.addAction("Split at playhead\tS", lambda: self.contextAction.emit("split"))
            m.addAction("Duplicate\tCtrl+D", lambda: self.contextAction.emit("duplicate"))
            m.addAction("Delete\tDel", lambda: self.contextAction.emit("delete"))
            m.addSeparator()
            m.addAction("Reset effects", lambda: self.contextAction.emit("reset_effects"))
            if clip["kind"] in ("video", "image"):
                m.addAction("Fit to canvas", lambda: self.contextAction.emit("fit"))
                m.addAction("Fill canvas", lambda: self.contextAction.emit("fill"))
            m.addSeparator()
        m.addAction("Add video track", lambda: self.contextAction.emit("add_video_track"))
        m.addAction("Add audio track", lambda: self.contextAction.emit("add_audio_track"))
        ti = self.track_at(self.mapFromGlobal(gpos).y())
        if ti >= 0:
            self._ctx_track = ti
            m.addAction(f"Remove {self.project.tracks[ti]['name']}", lambda: self.contextAction.emit("remove_track"))
            m.addAction("Close gaps on this track", lambda: self.contextAction.emit("close_gaps"))
        m.exec(gpos)

    # ------------------------------------------------------------ drag & drop of media
    def dragEnterEvent(self, ev):
        md = ev.mimeData()
        if md.hasFormat(MEDIA_MIME) or md.hasUrls():
            ev.acceptProposedAction()

    def dragMoveEvent(self, ev):
        ev.acceptProposedAction()

    def dropEvent(self, ev):
        md = ev.mimeData()
        paths = []
        if md.hasFormat(MEDIA_MIME):
            paths = bytes(md.data(MEDIA_MIME)).decode("utf-8").split("\n")
        elif md.hasUrls():
            paths = [u.toLocalFile() for u in md.urls() if u.isLocalFile()]
        paths = [p for p in paths if p]
        if paths:
            pos = ev.position()
            t = self.t_of(pos.x())
            if self.snap:
                t, _ = self.snap_t(t)
            self.dropMedia.emit(paths, t, self.track_at(pos.y()))
            ev.acceptProposedAction()


def media_mime(paths):
    md = QMimeData()
    md.setData(MEDIA_MIME, "\n".join(paths).encode("utf-8"))
    return md


class TimelineScroll(QScrollBar):
    """Horizontal scrollbar bound to a Timeline."""

    def __init__(self, tl: Timeline):
        super().__init__(Qt.Orientation.Horizontal)
        self.tl = tl
        self._mute = False
        tl.zoomChanged.connect(self.sync)
        self.valueChanged.connect(self._moved)

    def sync(self):
        if not self.tl.project:
            return
        self._mute = True
        total = max(self.tl.project.duration() + self.tl.visible_seconds(), self.tl.scroll_x + self.tl.visible_seconds())
        self.setRange(0, int(max(0.0, total - self.tl.visible_seconds()) * 100))
        self.setPageStep(int(self.tl.visible_seconds() * 100))
        self.setValue(int(self.tl.scroll_x * 100))
        self._mute = False
        self.tl.update()

    def _moved(self, v):
        if self._mute:
            return
        self.tl.scroll_x = v / 100.0
        self.tl.update()
