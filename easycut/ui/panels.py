"""Left-hand library: Media, Text, Filters, Animations, Transitions, Effects and Extensions.

Every browser lists *all* items - built-in, installed and the ones inside packs that aren't downloaded yet.
Those last ones are drawn greyed out with a lock; clicking one offers to download its pack."""
import os
import threading

import numpy as np
from PyQt6.QtCore import Qt, pyqtSignal, QSize, QObject, QUrl
from PyQt6.QtGui import QIcon, QPixmap, QImage, QColor, QPainter, QDesktopServices
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QListWidget, QListWidgetItem,
                             QStackedWidget, QFrame, QScrollArea, QAbstractItemView, QButtonGroup, QSizePolicy)

from .. import animations, catalog, filters, icons, media, textrender, theme, extensions, thumbs
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


def sample_image(w=112, h=70):  # kept for older code
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


# ======================================================================= item grids
_thumb_cache = {}


def item_thumb(kind, item_id):
    """QImage preview for a library item: baked catalog thumbnail if there is one, else drawn live."""
    key = (kind, item_id)
    img = _thumb_cache.get(key)
    if img is not None:
        return img
    path = catalog.thumb_path(kind, item_id)
    if path:
        img = QImage(path)
    else:
        bgr = thumbs.make(kind, item_id)
        img = _qimage(bgr) if bgr is not None else None
    if img is not None and not img.isNull():
        _thumb_cache[key] = img
    return img


def clear_thumbs():
    _thumb_cache.clear()


def registry(kind):
    """(order, dict) of registered items of a kind."""
    if kind == "filter":
        return filters.ORDER, filters.FILTERS
    if kind == "effect":
        return filters.EFFECT_ORDER, filters.EFFECTS
    if kind == "transition":
        return animations.TRANSITION_ORDER, animations.TRANSITIONS
    if kind == "animation":
        return animations.ORDER, animations.ANIMATIONS
    if kind == "text_style":
        return textrender.STYLE_ORDER, textrender.STYLES
    if kind == "font":
        return textrender.FONT_ORDER, textrender.FONTS
    return [], {}


def library_items(kind, skip_none=False):
    """[(id, name, locked, pack)] - built-ins first, then every pack's items in catalog order."""
    order, reg = registry(kind)
    in_catalog = {iid for iid, _, _ in catalog.items(kind)}
    out = []
    for iid in order:
        if iid in in_catalog or (skip_none and iid == "none"):
            continue
        it = reg[iid]
        name = it["name"] if isinstance(it, dict) else it.name
        out.append((iid, name, False, None))
    for iid, name, pack in catalog.items(kind):
        out.append((iid, name, iid not in reg, pack))
    return out


class ItemGrid(QWidget):
    """A wrapping grid of thumbnail tiles for one kind of item, including locked ones."""
    chosen = pyqtSignal(str)
    lockedClicked = pyqtSignal(str, str)        # kind, item id

    def __init__(self, kind, tile_size=(128, 104), skip_none=False, checkable=True, extra=None):
        super().__init__()
        self.kind = kind
        self.tile_size = tile_size
        self.skip_none = skip_none
        self.checkable = checkable
        self.extra = extra or []                # [(key, label, icon)] tiles shown first
        self.flow = FlowLayout(self, 8)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.tiles = {}
        self.rebuild()

    def rebuild(self):
        while self.flow.count():
            it = self.flow.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        for b in list(self.group.buttons()):
            self.group.removeButton(b)
        self.tiles = {}
        for key, label, icon in self.extra:
            b = Tile(label, icon_name=icon, size=self.tile_size)
            b.clicked.connect(lambda _=False, k=key: self.chosen.emit(k))
            self.flow.addWidget(b)
        for iid, name, locked, pack in library_items(self.kind, self.skip_none):
            img = item_thumb(self.kind, iid)
            b = Tile(name, image=img, icon_name=None if img is not None else "effects", size=self.tile_size,
                     locked=locked)
            if locked:
                b.setToolTip(f"{name} - part of the {pack['name']} pack.\nClick to download it.")
                b.clicked.connect(lambda _=False, i=iid: self.lockedClicked.emit(self.kind, i))
            else:
                src = pack["name"] if pack else "Built in"
                b.setToolTip(f"{name}  ·  {src}")
                b.setCheckable(self.checkable)
                if self.checkable:
                    self.group.addButton(b)
                b.clicked.connect(lambda _=False, i=iid: self.chosen.emit(i))
            self.flow.addWidget(b)
            self.tiles[iid] = b

    def select(self, iid):
        b = self.tiles.get(iid)
        if b is not None and b.isCheckable():
            b.setChecked(True)
        elif self.group.checkedButton() is not None:
            self.group.setExclusive(False)
            self.group.checkedButton().setChecked(False)
            self.group.setExclusive(True)


def _page(title, hint):
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(10, 10, 10, 10)
    t = QLabel(title)
    t.setObjectName("H2")
    lay.addWidget(t)
    if hint:
        h = QLabel(hint)
        h.setObjectName("Dim")
        h.setWordWrap(True)
        lay.addWidget(h)
    return w, lay


def _get_more(lay, text, category):
    b = QPushButton(f"  {text}")
    icons.bind(b, "extensions", 16, "accent")
    b.clicked.connect(lambda: b.window().show_extensions(category))
    lay.addWidget(b)
    return b


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
    styleChosen = pyqtSignal(str)
    fontChosen = pyqtSignal(str)
    lockedClicked = pyqtSignal(str, str)

    def __init__(self):
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        body, lay = _page("Text", "Click a preset to add text at the playhead. Styles and fonts apply to the "
                                  "selected text clip.")
        outer.addWidget(_scroll(body))
        lay.addWidget(section("Add text"))
        w = QWidget()
        flow = FlowLayout(w, 8)
        for name, preset in TEXT_PRESETS:
            b = QPushButton(name)
            b.setObjectName("Tile")
            b.setFixedSize(128, 52)
            col = preset.get("text_color", theme.C.get("text_strong"))
            b.setStyleSheet(f"font-size: {13 if preset.get('font_size', 80) < 100 else 16}px; font-weight: "
                            f"{'800' if preset.get('bold') else '400'}; color: {col};")
            b.clicked.connect(lambda _=False, pr=preset: self.addText.emit(dict(pr)))
            flow.addWidget(b)
        lay.addWidget(w)
        lay.addWidget(section("Text styles"))
        self.styles = ItemGrid("text_style", (128, 96))
        self.styles.chosen.connect(self.styleChosen)
        self.styles.lockedClicked.connect(self.lockedClicked)
        lay.addWidget(self.styles)
        lay.addWidget(section("Fonts"))
        self.fonts = ItemGrid("font", (128, 96))
        self.fonts.chosen.connect(self.fontChosen)
        self.fonts.lockedClicked.connect(self.lockedClicked)
        lay.addWidget(self.fonts)
        _get_more(lay, "Get more text packs", "Text")
        lay.addStretch(1)

    def rebuild(self):
        self.styles.rebuild()
        self.fonts.rebuild()

    def sync(self, clip):
        if clip is None or clip.get("kind") != "text":
            self.styles.select(None)
            self.fonts.select(None)
            return
        self.styles.select(clip.get("text_style", "none"))
        self.fonts.select(textrender.font_by_family(clip.get("font")))


# ======================================================================= Filters
class FiltersPage(QWidget):
    filterChosen = pyqtSignal(str)
    amountChanged = pyqtSignal(float)
    amountDone = pyqtSignal()
    applyAll = pyqtSignal()
    lockedClicked = pyqtSignal(str, str)

    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 10)
        body, blay = _page("Filters", "Select a clip, then pick a look. Locked looks come in free packs.")
        self.grid = ItemGrid("filter")
        self.grid.chosen.connect(self.filterChosen)
        self.grid.lockedClicked.connect(self.lockedClicked)
        blay.addWidget(self.grid)
        _get_more(blay, "Get more filter packs", "Filters")
        blay.addStretch(1)
        lay.addWidget(_scroll(body), 1)
        bottom = QVBoxLayout()
        bottom.setContentsMargins(10, 0, 10, 0)
        self.amount = SliderRow("Intensity", 0, 100, 100, step=1, decimals=0, suffix=" %", default=100)
        self.amount.valueChanged.connect(lambda v: self.amountChanged.emit(v / 100))
        self.amount.editingFinished.connect(self.amountDone)
        bottom.addWidget(self.amount)
        allb = QPushButton("Apply to every clip")
        allb.clicked.connect(self.applyAll)
        bottom.addWidget(allb)
        lay.addLayout(bottom)

    @property
    def buttons(self):
        return self.grid.tiles

    def rebuild(self):
        self.grid.rebuild()

    def sync(self, clip):
        self.grid.select(clip.get("filter", "none") if clip else "none")
        self.amount.setValue(float(clip.get("filter_amount", 1.0)) * 100 if clip else 100)


# ======================================================================= Animations
class AnimationsPage(QWidget):
    animChosen = pyqtSignal(str, str)          # which ("in"/"out"), id
    durationChanged = pyqtSignal(str, float)
    durationDone = pyqtSignal()
    lockedClicked = pyqtSignal(str, str)

    def __init__(self):
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        body, lay = _page("Animations", "Select a clip, then choose how it enters and leaves.")
        outer.addWidget(_scroll(body))
        self.grids = {}
        self.durs = {}
        for which, title in (("in", "In"), ("out", "Out")):
            lay.addWidget(section(f"Animation {title}"))
            g = ItemGrid("animation", (128, 96))
            g.chosen.connect(lambda aid, w=which: self.animChosen.emit(w, aid))
            g.lockedClicked.connect(lambda k, i, w=which: self.lockedClicked.emit(f"{k}:{w}", i))
            self.grids[which] = g
            lay.addWidget(g)
            d = SliderRow("Duration", 0.1, 3.0, 0.5, step=0.05, decimals=2, suffix=" s", default=0.5)
            d.valueChanged.connect(lambda v, w=which: self.durationChanged.emit(w, v))
            d.editingFinished.connect(self.durationDone)
            self.durs[which] = d
            lay.addWidget(d)
        _get_more(lay, "Get more animation packs", "Animations")
        lay.addStretch(1)

    @property
    def buttons(self):
        return {w: g.tiles for w, g in self.grids.items()}

    def rebuild(self):
        for g in self.grids.values():
            g.rebuild()

    def sync(self, clip):
        for which in ("in", "out"):
            self.grids[which].select(clip.get(f"anim_{which}", "none") if clip else "none")
            self.durs[which].setValue(float(clip.get(f"anim_{which}_dur", 0.5)) if clip else 0.5)


# ======================================================================= Transitions
class TransitionsPage(QWidget):
    transitionChosen = pyqtSignal(str)
    durationChanged = pyqtSignal(float)
    durationDone = pyqtSignal()
    lockedClicked = pyqtSignal(str, str)

    def __init__(self):
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        body, lay = _page("Transitions", "Select the clip a transition should lead INTO, then pick one. It plays "
                                         "over the end of the clip before it.")
        outer.addWidget(_scroll(body))
        self.grid = ItemGrid("transition")
        self.grid.chosen.connect(self.transitionChosen)
        self.grid.lockedClicked.connect(self.lockedClicked)
        lay.addWidget(self.grid)
        self.dur = SliderRow("Duration", 0.1, 3.0, 0.5, step=0.05, decimals=2, suffix=" s", default=0.5)
        self.dur.valueChanged.connect(self.durationChanged)
        self.dur.editingFinished.connect(self.durationDone)
        lay.addWidget(self.dur)
        _get_more(lay, "Get more transition packs", "Transitions")
        lay.addStretch(1)

    def rebuild(self):
        self.grid.rebuild()

    def sync(self, clip):
        self.grid.select(clip.get("trans_in", "none") if clip else "none")
        self.dur.setValue(float(clip.get("trans_dur", 0.5)) if clip else 0.5)


# ======================================================================= Effects
EFFECT_TILES = [
    ("chroma", "Chroma Key", "chroma"),
    ("crop", "Crop", "crop"),
    ("flip", "Flip", "flip"),
    ("mirror", "Mirror", "mirror"),
    ("speed", "Speed & Pitch", "speed"),
    ("stabilize", "Stabilize", "stabilize"),
]


class EffectsPage(QWidget):
    effectChosen = pyqtSignal(str)
    lockedClicked = pyqtSignal(str, str)

    def __init__(self):
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        body, lay = _page("Video Effects", "Select a clip, then click an effect to add it or open its settings.")
        outer.addWidget(_scroll(body))
        lay.addWidget(section("Built-in tools"))
        self.tools = ItemGrid("none", (128, 92), checkable=False, extra=EFFECT_TILES)
        self.tools.chosen.connect(self.effectChosen)
        lay.addWidget(self.tools)
        lay.addWidget(section("Effects"))
        self.grid = ItemGrid("effect", checkable=False)
        self.grid.chosen.connect(lambda eid: self.effectChosen.emit("fx:" + eid))
        self.grid.lockedClicked.connect(self.lockedClicked)
        lay.addWidget(self.grid)
        _get_more(lay, "Get more effect packs", "Effects")
        lay.addStretch(1)

    def rebuild(self):
        self.grid.rebuild()


# ======================================================================= Extensions
class PackCard(QFrame):
    getRequested = pyqtSignal(str)
    removeRequested = pyqtSignal(str)

    def __init__(self, pack, state):
        super().__init__()
        self.setObjectName("Card")
        self.pack_id = pack["id"]
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 10, 12, 10)
        v.setSpacing(6)
        top = QHBoxLayout()
        name = QLabel(pack.get("name", pack["id"]))
        name.setObjectName("H2")
        name.setWordWrap(True)
        top.addWidget(name, 1)
        cat = QLabel(pack.get("category", "").upper())
        cat.setObjectName("Badge")
        top.addWidget(cat, 0, Qt.AlignmentFlag.AlignTop)
        v.addLayout(top)
        if pack.get("description"):
            d = QLabel(pack["description"])
            d.setObjectName("Dim")
            d.setWordWrap(True)
            v.addWidget(d)
        strip = QHBoxLayout()
        strip.setSpacing(4)
        for it in pack.get("items", [])[:5]:
            img = item_thumb(it["type"], it["id"])
            lbl = QLabel()
            lbl.setToolTip(it.get("name", it["id"]))
            if img is not None:
                pm = QPixmap.fromImage(img).scaled(QSize(56, 35), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                                   Qt.TransformationMode.SmoothTransformation)
                lbl.setPixmap(pm)
            lbl.setFixedSize(56, 35)
            strip.addWidget(lbl)
        strip.addStretch(1)
        v.addLayout(strip)
        names = QLabel(" · ".join(it.get("name", it["id"]) for it in pack.get("items", [])))
        names.setWordWrap(True)
        v.addWidget(names)
        row = QHBoxLayout()
        n = len(pack.get("items", []))
        info = QLabel(f"{n} item{'s' if n != 1 else ''}" + (f"  ·  {catalog.size_label(pack)}" if pack.get("size") else ""))
        info.setObjectName("Dim")
        row.addWidget(info)
        row.addStretch(1)
        if state == "installed":
            ok = QLabel("✓ Installed")
            ok.setStyleSheet(f"color: {theme.C['success']}; font-weight: 700;")
            row.addWidget(ok)
            rm = QPushButton("Remove")
            rm.clicked.connect(lambda: self.removeRequested.emit(self.pack_id))
            row.addWidget(rm)
        elif state == "update":
            b = QPushButton("Update")
            b.setObjectName("Primary")
            b.clicked.connect(lambda: self.getRequested.emit(self.pack_id))
            row.addWidget(b)
        elif state == "restart":
            lbl = QLabel("Finishes when you restart")
            lbl.setObjectName("Dim")
            row.addWidget(lbl)
        else:
            b = QPushButton("  Get")
            b.setObjectName("Primary")
            icons.bind(b, "download", 15, "accent_text")
            b.clicked.connect(lambda: self.getRequested.emit(self.pack_id))
            row.addWidget(b)
        v.addLayout(row)


class ExtensionsPage(QWidget):
    getRequested = pyqtSignal(str)           # pack id
    getAllRequested = pyqtSignal(list)       # pack ids
    installFile = pyqtSignal()
    removeRequested = pyqtSignal(str)
    refreshRequested = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.category = "All"
        self.updates = {}
        self.restart_ids = set()
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
        hl.setContentsMargins(14, 12, 14, 12)
        hl.setSpacing(6)
        top = QHBoxLayout()
        ic = QLabel()
        ic.setPixmap(icons.pixmap("extensions", 28, theme.C["accent"]))
        theme.notifier.changed.connect(lambda: ic.setPixmap(icons.pixmap("extensions", 28, theme.C["accent"])))
        top.addWidget(ic)
        h = QLabel("Free packs - grab only what you need")
        h.setObjectName("H2")
        h.setWordWrap(True)
        top.addWidget(h, 1)
        hl.addLayout(top)
        txt = QLabel("Every pack holds about 5 filters, transitions, animations, effects, text styles or fonts. "
                     "Keep an eye out - more packs arrive as we update Easy-Cut.")
        txt.setWordWrap(True)
        hl.addWidget(txt)
        lay.addWidget(hero)
        chips = QWidget()
        cf = FlowLayout(chips, 6)
        self.cat_group = QButtonGroup(self)
        self.cat_buttons = {}
        for cat in ["All"] + catalog.CATEGORIES:
            b = QPushButton(cat)
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, c=cat: self.set_category(c))
            self.cat_group.addButton(b)
            cf.addWidget(b)
            self.cat_buttons[cat] = b
        self.cat_buttons["All"].setChecked(True)
        lay.addWidget(chips)
        row = QHBoxLayout()
        self.summary = QLabel("")
        self.summary.setObjectName("Dim")
        row.addWidget(self.summary, 1)
        self.get_all = QPushButton("Get all")
        self.get_all.setObjectName("Primary")
        self.get_all.clicked.connect(self._get_all)
        row.addWidget(self.get_all)
        lay.addLayout(row)
        self.cards_box = QWidget()
        self.cards = QVBoxLayout(self.cards_box)
        self.cards.setContentsMargins(0, 0, 0, 0)
        self.cards.setSpacing(8)
        lay.addWidget(self.cards_box)
        lay.addWidget(section("More"))
        self.refresh_btn = QPushButton("Check for new packs & updates")
        self.refresh_btn.clicked.connect(self.refreshRequested)
        self.file_btn = QPushButton("Install from file…")
        self.file_btn.clicked.connect(self.installFile)
        gh = QPushButton("Easy-Cut on GitHub")
        gh.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(REPO_URL)))
        for b in (self.refresh_btn, self.file_btn, gh):
            lay.addWidget(b)
        lay.addStretch(1)
        self.populate()

    def set_category(self, cat):
        self.category = cat if cat in self.cat_buttons else "All"
        self.cat_buttons[self.category].setChecked(True)
        self.populate()

    def state(self, pack_id):
        if pack_id in self.restart_ids:
            return "restart"
        inst = extensions.installed()
        if pack_id in inst:
            return "update" if pack_id in self.updates else "installed"
        return "get"

    def populate(self, updates=None, restart_ids=None):
        if updates is not None:
            self.updates = {e["id"]: e for e in updates}
        if restart_ids is not None:
            self.restart_ids = set(restart_ids)
        while self.cards.count():
            it = self.cards.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        packs = catalog.packs(self.category)
        inst = extensions.installed()
        known = {p["id"] for p in catalog.packs()}
        # sideloaded extensions that aren't in the catalog
        extra = [{"id": e.id, "name": e.name, "category": e.category or "Other", "description": e.description,
                  "items": e.items} for e in inst.values() if e.id not in known]
        if self.category == "All":
            packs = packs + extra
        missing = []
        for p in packs:
            st = self.state(p["id"])
            card = PackCard(p, st)
            card.getRequested.connect(self.getRequested)
            card.removeRequested.connect(self.removeRequested)
            self.cards.addWidget(card)
            if st == "get":
                missing.append(p["id"])
        total = len(packs)
        have = sum(1 for p in packs if p["id"] in inst)
        where = "" if self.category == "All" else f" {self.category.lower()}"
        self.summary.setText(f"{have} of {total}{where} pack{'s' if total != 1 else ''} installed")
        self._missing = missing
        self.get_all.setVisible(bool(missing))
        self.get_all.setText(f"Get all {len(missing)}" if self.category == "All" else
                             f"Get all {self.category.lower()}")
        if not packs:
            e = QLabel("No packs here yet - check back soon.")
            e.setObjectName("Dim")
            self.cards.addWidget(e)

    def _get_all(self):
        if self._missing:
            self.getAllRequested.emit(list(self._missing))


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
        if c.get("apple"):
            # sidebar row: tinted icon + label, like a desktop file-manager sidebar
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.drawPixmap(10, int((self.height() - 18) / 2), icons.pixmap(self.icon_name, 18, c["accent"]))
            p.setPen(QColor(c["text_strong"] if on else c["text"]))
            f = p.font()
            f.setPointSizeF(9.6)
            f.setBold(on)
            p.setFont(f)
            p.drawText(self.rect().adjusted(36, 0, -6, 0), Qt.AlignmentFlag.AlignVCenter, self.label)
            if self.badge:
                f.setPointSizeF(7)
                f.setBold(True)
                p.setFont(f)
                bw = p.fontMetrics().horizontalAdvance(self.badge) + 12
                from PyQt6.QtCore import QRectF
                br = QRectF(self.width() - bw - 8, (self.height() - 16) / 2, bw, 16)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(c["accent"]))
                p.drawRoundedRect(br, 8, 8)
                p.setPen(QColor("#ffffff"))
                p.drawText(br, Qt.AlignmentFlag.AlignCenter, self.badge)
            p.end()
            return
        if ext:
            col = c["accent_text"] if on else c["accent"]
        else:
            col = c["text_strong"] if on else c["text_dim"]
        top = max(4, int((self.height() - 40) / 2))
        p.drawPixmap(int((self.width() - 22) / 2), top, icons.pixmap(self.icon_name, 22, col))
        p.setPen(QColor(c["accent_text"] if (on and ext) else c["text_strong"] if (on or ext) else c["text_dim"]))
        f = p.font()
        f.setPointSizeF(8.2)
        f.setBold(ext)
        p.setFont(f)
        p.drawText(self.rect().adjusted(0, top + 25, 0, -1), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
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
    collapsedChanged = pyqtSignal(bool)

    def __init__(self):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        rail = QFrame()
        rail.setObjectName("SideRail")
        rail.setFixedWidth(80)
        self.rail = rail
        rl = QVBoxLayout(rail)
        self.rail_lay = rl
        rl.setContentsMargins(6, 8, 6, 8)
        rl.setSpacing(2)
        self.rail_title = QLabel("Library")
        self.rail_title.setObjectName("Section")
        self.rail_title.setContentsMargins(8, 2, 0, 4)
        rl.addWidget(self.rail_title)
        self.stack = QStackedWidget()
        panel = QFrame()
        panel.setObjectName("Panel")
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.addWidget(self.stack)
        self.media = MediaPage()
        from .explorer import ExplorerPanel
        self.explorer = ExplorerPanel()
        self.text = TextPage()
        self.filters = FiltersPage()
        self.anims = AnimationsPage()
        self.transitions = TransitionsPage()
        self.effects = EffectsPage()
        self.extensions = ExtensionsPage()
        self.group = QButtonGroup(self)
        self.rail_buttons = {}
        for key, label, icon, page in (("media", "Media", "media", self.media),
                                       ("explorer", "Explorer", "folder", self.explorer),
                                       ("text", "Text", "text", self.text),
                                       ("filters", "Filters", "filters", self.filters),
                                       ("anims", "Animations", "anim", self.anims),
                                       ("transitions", "Transitions", "transition", self.transitions),
                                       ("effects", "Effects", "effects", self.effects),
                                       ("extensions", "Extensions", "extensions", self.extensions)):
            b = RailButton(label, icon, "NEW" if key == "extensions" else "")
            b.setObjectName("RailExt" if key == "extensions" else "Rail")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setMinimumHeight(44)
            b.setMaximumHeight(58)
            b.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
            idx = self.stack.addWidget(page)
            b.pressed.connect(lambda i=idx: self._rail_pressed(i))
            b.clicked.connect(lambda _=False, i=idx: self._rail_clicked(i))
            self.group.addButton(b)
            self.rail_buttons[key] = b
            if key == "extensions":
                rl.addStretch(1)
            rl.addWidget(b)
        self.rail_buttons["media"].setChecked(True)
        self.panel = panel
        self.collapsed = False
        lay.addWidget(rail)
        lay.addWidget(panel, 1)
        self.apply_style()
        theme.notifier.changed.connect(self.apply_style)

    def rail_width(self):
        return 196 if theme.C.get("apple") else 80

    def apply_style(self):
        """🍏 Mode uses a wide list-style sidebar; the other themes an icon rail."""
        apple = bool(theme.C.get("apple"))
        self.rail.setFixedWidth(self.rail_width())
        self.rail_title.setVisible(apple)
        self.rail_lay.setContentsMargins(10 if apple else 6, 10 if apple else 8, 10 if apple else 6, 10 if apple else 8)
        for b in self.rail_buttons.values():
            if apple:
                b.setMinimumHeight(30)
                b.setMaximumHeight(30)
            else:
                b.setMinimumHeight(44)
                b.setMaximumHeight(58)
            b.update()

    def _rail_pressed(self, idx):
        self._was_current = (self.stack.currentIndex() == idx) and not self.collapsed

    def _rail_clicked(self, idx):
        # clicking the open tab again minimises the panel; any tab re-opens it
        if getattr(self, "_was_current", False):
            self.set_collapsed(True)
            return
        self.stack.setCurrentIndex(idx)
        self.set_collapsed(False)

    def set_collapsed(self, on):
        if on == self.collapsed:
            return
        self.collapsed = on
        self.panel.setVisible(not on)
        self.collapsedChanged.emit(on)

    def show(self, key):
        b = self.rail_buttons[key]
        b.setChecked(True)
        self.stack.setCurrentWidget({"media": self.media, "explorer": self.explorer, "text": self.text,
                                     "filters": self.filters, "anims": self.anims, "transitions": self.transitions,
                                     "effects": self.effects, "extensions": self.extensions}[key])
        self.set_collapsed(False)

    def rebuild(self):
        """Refresh every browser (after packs are installed or removed)."""
        for page in (self.text, self.filters, self.anims, self.transitions, self.effects):
            page.rebuild()
        self.extensions.populate()

    def locked_signals(self):
        return [self.text.lockedClicked, self.filters.lockedClicked, self.anims.lockedClicked,
                self.transitions.lockedClicked, self.effects.lockedClicked]
