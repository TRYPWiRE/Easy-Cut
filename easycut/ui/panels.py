"""Left-hand library: Media, Text, Filters, Animations, Effects and Extensions."""
import os
import threading

import numpy as np
from PyQt6.QtCore import Qt, pyqtSignal, QSize, QObject, QUrl
from PyQt6.QtGui import QIcon, QPixmap, QImage, QColor, QPainter, QDesktopServices
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QListWidget, QListWidgetItem,
                             QStackedWidget, QFrame, QScrollArea, QAbstractItemView, QButtonGroup)

from .. import animations, filters, icons, media, theme, extensions
from ..config import REPO_URL
from .widgets import section, SliderRow, FlowLayout, fmt_time, Tile
from .timeline import media_mime


def _scroll(w):
    sa = QScrollArea()
    sa.setWidgetResizable(True)
    sa.setFrameShape(QFrame.Shape.NoFrame)
    sa.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    sa.setWidget(w)
    return sa


def _qimage(bgr):
    bgr = np.ascontiguousarray(bgr)
    h, w = bgr.shape[:2]
    if bgr.shape[2] == 4:
        return QImage(bgr.data, w, h, w * 4, QImage.Format.Format_ARGB32).copy()
    return QImage(bgr.data, w, h, w * 3, QImage.Format.Format_BGR888).copy()


def sample_image(w=112, h=70):
    """A little sunset landscape used for filter swatches."""
    y = np.linspace(0, 1, h)[:, None]
    x = np.linspace(0, 1, w)[None, :]
    img = np.zeros((h, w, 3), np.float32)
    sky_top = np.array([235, 120, 60])     # BGR
    sky_bot = np.array([120, 170, 255])
    img[:] = (sky_top * (1 - y[..., None]) + sky_bot * y[..., None])
    sun = ((x - 0.68) ** 2 + ((y - 0.55) * h / w) ** 2) < 0.012
    img[sun] = (120, 230, 255)
    hill = y > 0.62 + 0.08 * np.sin(x * 7)
    img[np.broadcast_to(hill, (h, w))] = (60, 130, 70)
    skin = (np.abs(x - 0.3) < 0.07) & (y > 0.4) & (y < 0.8)
    img[np.broadcast_to(skin, (h, w))] = (140, 170, 230)
    return img.clip(0, 255).astype(np.uint8)


class _ThumbSig(QObject):
    done = pyqtSignal(str, QImage)


# ======================================================================= Media
class MediaList(QListWidget):
    def __init__(self):
        super().__init__()
        self.setViewMode(QListWidget.ViewMode.IconMode)
        self.setIconSize(QSize(132, 74))
        self.setGridSize(QSize(150, 112))
        self.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.setMovement(QListWidget.Movement.Static)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setWordWrap(True)
        self.setSpacing(4)

    def mimeData(self, items):
        return media_mime([it.data(Qt.ItemDataRole.UserRole) for it in items])

    def mimeTypes(self):
        return ["application/x-easycut-media"]


class MediaPage(QWidget):
    importRequested = pyqtSignal()
    addRequested = pyqtSignal(list)
    removeRequested = pyqtSignal(list)

    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        top = QHBoxLayout()
        t = QLabel("Media")
        t.setObjectName("H2")
        top.addWidget(t)
        top.addStretch(1)
        self.import_btn = QPushButton("  Import")
        self.import_btn.setObjectName("Primary")
        icons.bind(self.import_btn, "plus", 16, "accent_text")
        self.import_btn.clicked.connect(self.importRequested)
        top.addWidget(self.import_btn)
        lay.addLayout(top)
        self.list = MediaList()
        self.list.itemDoubleClicked.connect(lambda it: self.addRequested.emit([it.data(Qt.ItemDataRole.UserRole)]))
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._menu)
        lay.addWidget(self.list, 1)
        hint = QLabel("Double-click or drag onto the timeline.")
        hint.setObjectName("Dim")
        lay.addWidget(hint)
        self.sig = _ThumbSig()
        self.sig.done.connect(self._thumb_done)
        self.items = {}

    def _menu(self, pos):
        from PyQt6.QtWidgets import QMenu
        items = self.list.selectedItems()
        if not items:
            return
        paths = [it.data(Qt.ItemDataRole.UserRole) for it in items]
        m = QMenu(self)
        m.addAction("Add to timeline", lambda: self.addRequested.emit(paths))
        m.addAction("Remove from media", lambda: self.removeRequested.emit(paths))
        m.exec(self.list.mapToGlobal(pos))

    def set_media(self, paths):
        self.list.clear()
        self.items = {}
        for p in paths:
            self.add(p)

    def add(self, path):
        if path in self.items:
            return
        info = media.probe(path) if os.path.exists(path) else None
        name = os.path.basename(path)
        sub = ""
        if info:
            if info.kind == "image":
                sub = f"{info.width}×{info.height}"
            else:
                sub = fmt_time(info.duration).split(".")[0]
        it = QListWidgetItem(f"{name}\n{sub}")
        it.setData(Qt.ItemDataRole.UserRole, path)
        it.setToolTip(path)
        kind = media.media_kind(path)
        it.setIcon(self._placeholder(kind))
        self.list.addItem(it)
        self.items[path] = it
        if kind in ("video", "image"):
            threading.Thread(target=self._make_thumb, args=(path,), daemon=True).start()

    def _placeholder(self, kind):
        pm = QPixmap(264, 148)
        pm.fill(QColor(theme.C["panel2"]))
        p = QPainter(pm)
        name = {"audio": "music", "image": "image"}.get(kind, "media")
        p.drawPixmap(108, 50, icons.pixmap(name, 48, theme.C["text_dim"], dpr=1))
        p.end()
        return QIcon(pm)

    def _make_thumb(self, path):
        try:
            img = media.thumbnail(path, (264, 148))
            if img is not None:
                canvas = np.zeros((148, 264, 4), np.uint8)
                h, w = img.shape[:2]
                y, x = (148 - h) // 2, (264 - w) // 2
                canvas[y:y + h, x:x + w] = img
                self.sig.done.emit(path, _qimage(canvas))
        except Exception:
            pass

    def _thumb_done(self, path, img):
        it = self.items.get(path)
        if it is not None:
            it.setIcon(QIcon(QPixmap.fromImage(img)))

    def remove(self, path):
        it = self.items.pop(path, None)
        if it is not None:
            self.list.takeItem(self.list.row(it))


# ======================================================================= Text
TEXT_PRESETS = [
    ("Default text", {"text": "Default text", "font_size": 80, "bold": True, "text_outline": True}),
    ("Big title", {"text": "BIG TITLE", "font_size": 150, "bold": True, "text_outline": True}),
    ("Subtitle", {"text": "Your subtitle here", "font_size": 54, "bold": False, "text_bg": True,
                  "text_outline": False, "y": 0.38}),
    ("Neon", {"text": "Neon", "font_size": 120, "bold": True, "text_color": "#ff4f7b", "text_outline": True}),
    ("Lower third", {"text": "Name Surname\nTitle", "font_size": 46, "bold": True, "text_bg": True,
                     "text_bg_color": "#111111", "text_outline": False, "x": -0.28, "y": 0.32}),
    ("Caption", {"text": "caption", "font_size": 64, "bold": True, "text_color": "#ffe14d",
                 "text_outline": True, "y": 0.3}),
]


class TextPage(QWidget):
    addText = pyqtSignal(dict)

    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        t = QLabel("Text")
        t.setObjectName("H2")
        lay.addWidget(t)
        lay.addWidget(QLabel("Click a style to add it at the playhead."))
        lay.itemAt(1).widget().setObjectName("Dim")
        w = QWidget()
        flow = FlowLayout(w, 8)
        for name, preset in TEXT_PRESETS:
            b = QPushButton(name)
            b.setObjectName("Tile")
            b.setFixedSize(132, 62)
            col = preset.get("text_color", theme.C.get("text_strong"))
            b.setStyleSheet(f"font-size: {13 if preset.get('font_size', 80) < 100 else 16}px; font-weight: "
                            f"{'800' if preset.get('bold') else '400'}; color: {col};")
            b.clicked.connect(lambda _=False, pr=preset: self.addText.emit(dict(pr)))
            flow.addWidget(b)
        lay.addWidget(_scroll(w), 1)


# ======================================================================= Filters
class FiltersPage(QWidget):
    filterChosen = pyqtSignal(str)
    amountChanged = pyqtSignal(float)
    amountDone = pyqtSignal()
    applyAll = pyqtSignal()

    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        t = QLabel("Filters")
        t.setObjectName("H2")
        lay.addWidget(t)
        hint = QLabel("Select a clip, then pick a look.")
        hint.setObjectName("Dim")
        lay.addWidget(hint)
        self.holder = QWidget()
        self.flow = FlowLayout(self.holder, 8)
        lay.addWidget(_scroll(self.holder), 1)
        self.amount = SliderRow("Intensity", 0, 100, 100, step=1, decimals=0, suffix=" %", default=100)
        self.amount.valueChanged.connect(lambda v: self.amountChanged.emit(v / 100))
        self.amount.editingFinished.connect(self.amountDone)
        lay.addWidget(self.amount)
        allb = QPushButton("Apply to every clip")
        allb.clicked.connect(self.applyAll)
        lay.addWidget(allb)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons = {}
        self.rebuild()

    def rebuild(self):
        while self.flow.count():
            it = self.flow.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        self.buttons = {}
        sample = sample_image()
        for fid in filters.ORDER:
            f = filters.FILTERS[fid]
            img = filters.apply_preview(sample.copy(), {"filter": fid, "filter_amount": 1.0})
            b = Tile(f.name, image=_qimage(img), size=(128, 104))
            b.setCheckable(True)
            b.setToolTip(f.name + ("" if f.source == "built-in" else f"  (from {f.source})"))
            b.clicked.connect(lambda _=False, fid=fid: self.filterChosen.emit(fid))
            self.group.addButton(b)
            self.flow.addWidget(b)
            self.buttons[fid] = b
        self._more_tile()

    def _more_tile(self):
        b = Tile("More filters\ncoming soon", size=(128, 104))
        b.setToolTip("More filters arrive as Extensions")
        b.clicked.connect(lambda: self.window().show_extensions() if hasattr(self.window(), "show_extensions") else None)
        self.flow.addWidget(b)

    def sync(self, clip):
        fid = clip.get("filter", "none") if clip else "none"
        b = self.buttons.get(fid)
        if b:
            b.setChecked(True)
        self.amount.setValue(float(clip.get("filter_amount", 1.0)) * 100 if clip else 100)


# ======================================================================= Animations
class AnimationsPage(QWidget):
    animChosen = pyqtSignal(str, str)          # which ("in"/"out"), id
    durationChanged = pyqtSignal(str, float)
    durationDone = pyqtSignal()

    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        t = QLabel("Animations")
        t.setObjectName("H2")
        lay.addWidget(t)
        hint = QLabel("Select a clip, then choose how it enters and leaves.")
        hint.setObjectName("Dim")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        body = QWidget()
        self.body_lay = QVBoxLayout(body)
        self.body_lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(_scroll(body), 1)
        self.groups = {}
        self.buttons = {}
        self.durs = {}
        self.rebuild()

    def rebuild(self):
        while self.body_lay.count():
            it = self.body_lay.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()
        self.buttons = {"in": {}, "out": {}}
        for which, title in (("in", "In"), ("out", "Out")):
            self.body_lay.addWidget(section(f"Animation {title}"))
            holder = QWidget()
            flow = FlowLayout(holder, 6)
            grp = QButtonGroup(self)
            grp.setExclusive(True)
            self.groups[which] = grp
            for aid in animations.ORDER:
                a = animations.ANIMATIONS[aid]
                if which not in a.kinds:
                    continue
                b = QPushButton(a.name)
                b.setObjectName("Tile")
                b.setCheckable(True)
                b.setFixedSize(98, 40)
                b.clicked.connect(lambda _=False, w=which, aid=aid: self.animChosen.emit(w, aid))
                grp.addButton(b)
                flow.addWidget(b)
                self.buttons[which][aid] = b
            more = QPushButton("More soon…")
            more.setObjectName("Tile")
            more.setFixedSize(98, 40)
            more.setToolTip("More animations arrive as Extensions")
            more.clicked.connect(lambda: self.window().show_extensions())
            flow.addWidget(more)
            self.body_lay.addWidget(holder)
            d = SliderRow("Duration", 0.1, 3.0, 0.5, step=0.05, decimals=2, suffix=" s", default=0.5)
            d.valueChanged.connect(lambda v, w=which: self.durationChanged.emit(w, v))
            d.editingFinished.connect(self.durationDone)
            self.durs[which] = d
            self.body_lay.addWidget(d)
        self.body_lay.addStretch(1)

    def sync(self, clip):
        for which in ("in", "out"):
            aid = clip.get(f"anim_{which}", "none") if clip else "none"
            b = self.buttons[which].get(aid) or self.buttons[which].get("none")
            if b:
                b.setChecked(True)
            self.durs[which].setValue(float(clip.get(f"anim_{which}_dur", 0.5)) if clip else 0.5)


# ======================================================================= Effects
EFFECT_TILES = [
    ("chroma", "Chroma Key", "chroma", "Remove a green or blue screen"),
    ("crop", "Crop", "crop", "Trim the edges of the picture"),
    ("flip", "Flip", "flip", "Flip horizontally or vertically"),
    ("mirror", "Mirror", "mirror", "Reflect one half onto the other"),
    ("speed", "Speed & Pitch", "speed", "Slow-mo, fast-forward, pitch shift"),
    ("stabilize", "Stabilize", "stabilize", "Smooth out shaky footage"),
]


class EffectsPage(QWidget):
    effectChosen = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        t = QLabel("Video Effects")
        t.setObjectName("H2")
        lay.addWidget(t)
        hint = QLabel("Select a clip, then click an effect to open its settings.")
        hint.setObjectName("Dim")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        self.holder = QWidget()
        self.flow = FlowLayout(self.holder, 8)
        lay.addWidget(_scroll(self.holder), 1)
        self.rebuild()

    def rebuild(self):
        while self.flow.count():
            it = self.flow.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        for key, name, icon, tip in EFFECT_TILES:
            self._tile(key, name, icon, tip)
        for eid in filters.EFFECT_ORDER:
            e = filters.EFFECTS[eid]
            self._tile("fx:" + eid, e.name, "effects", f"From the {e.source} extension")
        b = Tile("More effects\ncoming soon", size=(128, 92))
        b.clicked.connect(lambda: self.window().show_extensions())
        self.flow.addWidget(b)

    def _tile(self, key, name, icon, tip):
        b = Tile(name, icon_name=icon, size=(128, 92))
        b.setToolTip(tip)
        b.clicked.connect(lambda _=False, k=key: self.effectChosen.emit(k))
        self.flow.addWidget(b)


# ======================================================================= Extensions
class ExtensionsPage(QWidget):
    installRequested = pyqtSignal(dict)
    installFile = pyqtSignal()
    removeRequested = pyqtSignal(str)
    refreshRequested = pyqtSignal()

    def __init__(self):
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(10)
        outer.addWidget(_scroll(body))
        t = QLabel("Extensions")
        t.setObjectName("H2")
        lay.addWidget(t)
        hero = QFrame()
        hero.setObjectName("Hero")
        hl = QVBoxLayout(hero)
        hl.setContentsMargins(16, 16, 16, 16)
        hl.setSpacing(10)
        top = QHBoxLayout()
        ic = QLabel()
        ic.setPixmap(icons.pixmap("extensions", 36, theme.C["accent"]))
        theme.notifier.changed.connect(lambda: ic.setPixmap(icons.pixmap("extensions", 36, theme.C["accent"])))
        top.addWidget(ic)
        top.addStretch(1)
        badge = QLabel("COMING SOON")
        badge.setObjectName("Badge")
        top.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)
        hl.addLayout(top)
        h = QLabel("More is on the way!")
        h.setObjectName("H1")
        h.setWordWrap(True)
        hl.addWidget(h)
        body_txt = QLabel("Keep an eye out for more extensions as we update Easy-Cut. They install in one "
                          "click right here, update themselves, and slot straight into the app.")
        body_txt.setWordWrap(True)
        hl.addWidget(body_txt)
        inc = QLabel("Extensions will include:")
        inc.setObjectName("Dim")
        hl.addWidget(inc)
        for text in ("✦  More filters", "◆  More animations", "✷  More video effects"):
            ch = QLabel(text)
            ch.setObjectName("Chip")
            hl.addWidget(ch)
        lay.addWidget(hero)
        lay.addWidget(section("Your extensions"))
        self.list = QListWidget()
        self.list.setMinimumHeight(120)
        lay.addWidget(self.list)
        self.empty = QLabel("No extensions have been released yet - check back soon.")
        self.empty.setObjectName("Dim")
        self.empty.setWordWrap(True)
        lay.addWidget(self.empty)
        self.refresh_btn = QPushButton("Check for extensions")
        self.refresh_btn.clicked.connect(self.refreshRequested)
        self.file_btn = QPushButton("Install from file…")
        self.file_btn.clicked.connect(self.installFile)
        gh = QPushButton("Easy-Cut on GitHub")
        gh.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(REPO_URL)))
        for b in (self.refresh_btn, self.file_btn, gh):
            lay.addWidget(b)
        lay.addStretch(1)
        self.available = []

    def populate(self, available=None, updates=None):
        if available is not None:
            self.available = available
        updates = {e["id"]: e for e in (updates or [])}
        self.list.clear()
        inst = extensions.installed()
        for ext in inst.values():
            state = "Disabled" if extensions.is_disabled(ext.id) else ("Error" if ext.error else "Installed")
            if ext.id in updates:
                state = f"Update to {updates[ext.id]['version']}"
            self._row(ext.name, ext.version, ext.description, state, ext.id, updates.get(ext.id))
        for e in self.available:
            if e["id"] not in inst:
                self._row(e.get("name", e["id"]), e.get("version", ""), e.get("description", ""), "Install",
                          e["id"], e)
        self.empty.setVisible(self.list.count() == 0)
        self.list.setVisible(self.list.count() > 0)

    def _row(self, name, version, desc, state, ext_id, entry):
        it = QListWidgetItem()
        w = QWidget()
        hl = QHBoxLayout(w)
        hl.setContentsMargins(8, 6, 8, 6)
        v = QVBoxLayout()
        title = QLabel(f"<b>{name}</b>  <span style='color:{theme.C['text_dim']}'>v{version}</span>")
        v.addWidget(title)
        d = QLabel(desc)
        d.setObjectName("Dim")
        d.setWordWrap(True)
        v.addWidget(d)
        hl.addLayout(v, 1)
        if entry is not None and (state == "Install" or state.startswith("Update")):
            b = QPushButton(state)
            b.setObjectName("Primary")
            b.clicked.connect(lambda _=False, e=entry: self.installRequested.emit(e))
            hl.addWidget(b)
        if state != "Install":
            rm = QPushButton("Remove")
            rm.clicked.connect(lambda _=False, i=ext_id: self.removeRequested.emit(i))
            hl.addWidget(rm)
        it.setSizeHint(w.sizeHint())
        self.list.addItem(it)
        self.list.setItemWidget(it, w)


# ======================================================================= Library (rail + pages)
class RailButton(QPushButton):
    """Side-rail button with the icon centred above its label."""

    def __init__(self, label, icon_name, badge=""):
        super().__init__("")
        self.badge = badge
        self.label = label
        self.icon_name = icon_name
        self.setToolTip(label)

    def paintEvent(self, ev):
        from PyQt6.QtWidgets import QStyleOptionButton, QStyle
        opt = QStyleOptionButton()
        self.initStyleOption(opt)
        p = QPainter(self)
        self.style().drawControl(QStyle.ControlElement.CE_PushButton, opt, p, self)
        c = theme.C
        on = self.isChecked()
        ext = self.objectName() == "RailExt"
        if ext:
            col = c["accent_text"] if on else c["accent"]
        else:
            col = c["text_strong"] if on else c["text_dim"]
        p.drawPixmap(int((self.width() - 22) / 2), 10, icons.pixmap(self.icon_name, 22, col))
        p.setPen(QColor(c["accent_text"] if (on and ext) else c["text_strong"] if (on or ext) else c["text_dim"]))
        f = p.font()
        f.setPointSizeF(8.2)
        f.setBold(ext)
        p.setFont(f)
        p.drawText(self.rect().adjusted(0, 36, 0, -2), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                   self.label)
        if self.badge:
            from PyQt6.QtCore import QRectF
            f.setPointSizeF(6.8)
            f.setBold(True)
            p.setFont(f)
            bw = p.fontMetrics().horizontalAdvance(self.badge) + 8
            br = QRectF(self.width() - bw - 3, 3, bw, 13)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(c["accent2"] if on else c["accent"]))
            rr = 6 if c.get("radius", 8) else 0
            p.drawRoundedRect(br, rr, rr)
            p.setPen(QColor("#ffffff" if on else c["accent_text"]))
            p.drawText(br, Qt.AlignmentFlag.AlignCenter, self.badge)
        p.end()


class Library(QWidget):
    def __init__(self):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        rail = QFrame()
        rail.setObjectName("SideRail")
        rail.setFixedWidth(80)
        rl = QVBoxLayout(rail)
        rl.setContentsMargins(6, 8, 6, 8)
        rl.setSpacing(4)
        self.stack = QStackedWidget()
        panel = QFrame()
        panel.setObjectName("Panel")
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.addWidget(self.stack)
        self.media = MediaPage()
        self.text = TextPage()
        self.filters = FiltersPage()
        self.anims = AnimationsPage()
        self.effects = EffectsPage()
        self.extensions = ExtensionsPage()
        self.group = QButtonGroup(self)
        self.rail_buttons = {}
        for key, label, icon, page in (("media", "Media", "media", self.media), ("text", "Text", "text", self.text),
                                       ("filters", "Filters", "filters", self.filters),
                                       ("anims", "Animations", "anim", self.anims),
                                       ("effects", "Effects", "effects", self.effects),
                                       ("extensions", "Extensions", "extensions", self.extensions)):
            b = RailButton(label, icon, "NEW" if key == "extensions" else "")
            b.setObjectName("RailExt" if key == "extensions" else "Rail")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setFixedHeight(62)
            idx = self.stack.addWidget(page)
            b.clicked.connect(lambda _=False, i=idx: self.stack.setCurrentIndex(i))
            self.group.addButton(b)
            self.rail_buttons[key] = b
            if key == "extensions":
                rl.addStretch(1)
            rl.addWidget(b)
        self.rail_buttons["media"].setChecked(True)
        lay.addWidget(rail)
        lay.addWidget(panel, 1)

    def show(self, key):
        b = self.rail_buttons[key]
        b.setChecked(True)
        b.click()
