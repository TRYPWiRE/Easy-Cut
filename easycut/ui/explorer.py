"""Built-in File Explorer: every storage location in one window, with media thumbnails and details.

Layout (wide):    [ Locations ] | [ toolbar: ← → ↑ ⟳  breadcrumb … search  view  filter  full-view ]
                                 | [ grid of thumbnails  /  details list ]
                                 | [ selected file: preview · info · Add to timeline ]
In the narrow library panel the Locations sidebar folds into a "Locations" menu button.

Files can be double-clicked or dragged straight onto the timeline or the preview. Folders are watched, so new
recordings and downloads appear on their own.
"""
import os
import queue
import sys
import threading
import time

import numpy as np
from PyQt6.QtCore import (Qt, QAbstractTableModel, QModelIndex, QObject, pyqtSignal, QSize, QRectF, QTimer,
                          QSortFilterProxyModel, QMimeData, QUrl, QFileSystemWatcher, QStandardPaths, QStorageInfo)
from PyQt6.QtGui import QColor, QPainter, QImage, QPixmap, QFont, QFontMetrics, QPainterPath, QIcon
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit, QListView,
                             QTreeView, QStackedWidget, QSplitter, QFrame, QStyledItemDelegate, QStyle, QMenu,
                             QAbstractItemView, QComboBox, QToolButton, QTreeWidget, QTreeWidgetItem,
                             QHeaderView, QSizePolicy)

from .. import media, settings, theme, icons
from ..config import recordings_dir
from .timeline import MEDIA_MIME
from .widgets import icon_button, fmt_time

KIND_FILTERS = [("media", "All media"), ("video", "Videos"), ("audio", "Audio"), ("image", "Images"),
                ("all", "All files")]
COLS = ["Name", "Duration", "Details", "Size", "Modified"]
THUMB = QSize(176, 99)


def human_size(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024.0
    return ""


def _qimage(bgra):
    bgra = np.ascontiguousarray(bgra)
    h, w = bgra.shape[:2]
    return QImage(bgra.data, w, h, w * 4, QImage.Format.Format_ARGB32).copy()


class Item:
    __slots__ = ("path", "name", "is_dir", "size", "mtime", "kind", "info", "thumb")

    def __init__(self, path, name, is_dir, size, mtime):
        self.path = path
        self.name = name
        self.is_dir = is_dir
        self.size = size
        self.mtime = mtime
        self.kind = "folder" if is_dir else (media.media_kind(path) or "other")
        self.info = None            # MediaInfo once probed
        self.thumb = None           # QImage once generated


# ====================================================================== background work
class _Signals(QObject):
    listed = pyqtSignal(int, str, list, str)     # generation, folder, items, error
    detail = pyqtSignal(int, str, object, object)  # generation, path, info, QImage


class Worker:
    """Lists folders and probes/thumbnails media in the background (one thread, newest request wins)."""

    def __init__(self):
        self.sig = _Signals()
        self.q = queue.Queue()
        self.gen = 0
        self.thumb_cache = {}
        threading.Thread(target=self._run, daemon=True).start()

    def list(self, folder):
        self.gen += 1
        self.q.put(("list", self.gen, folder))
        return self.gen

    def details(self, gen, items):
        for it in items:
            self.q.put(("detail", gen, it.path, it.kind, it.mtime))

    def _run(self):
        while True:
            job = self.q.get()
            try:
                if job[1] != self.gen:
                    continue                      # stale (the user moved on)
                if job[0] == "list":
                    self._list(job[1], job[2])
                else:
                    self._detail(*job[1:])
            except Exception:
                pass

    def _list(self, gen, folder):
        items, err = [], ""
        try:
            with os.scandir(folder) as it:
                for e in it:
                    if e.name.startswith(".") or e.name.lower() in ("desktop.ini", "thumbs.db", "$recycle.bin",
                                                                     "system volume information"):
                        continue
                    try:
                        st = e.stat()
                        is_dir = e.is_dir()
                    except OSError:
                        continue
                    if not is_dir and sys.platform == "win32":
                        try:
                            if st.st_file_attributes & 0x2:      # hidden
                                continue
                        except AttributeError:
                            pass
                    items.append(Item(e.path, e.name, is_dir, 0 if is_dir else st.st_size, st.st_mtime))
        except OSError as e:
            err = e.strerror or str(e)
        self.sig.listed.emit(gen, folder, items, err)

    def _detail(self, gen, path, kind, mtime):
        key = (path, mtime)
        if key in self.thumb_cache:
            info, img = self.thumb_cache[key]
            self.sig.detail.emit(gen, path, info, img)
            return
        info = media.probe(path) if kind in ("video", "audio", "image") else None
        img = None
        if kind in ("video", "image"):
            t = media.thumbnail(path, (THUMB.width() * 2, THUMB.height() * 2))
            if t is not None:
                img = _qimage(t)
        elif kind == "audio":
            img = waveform_image(path)
        if len(self.thumb_cache) > 2000:
            self.thumb_cache.clear()
        self.thumb_cache[key] = (info, img)
        if gen == self.gen:
            self.sig.detail.emit(gen, path, info, img)


def waveform_image(path, w=352, h=198):
    peaks = media.waveform(path, points=w // 3)
    if not peaks:
        return None
    img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    col = QColor(theme.C.get("clip_audio", "#1f9e74"))
    p.setBrush(col)
    n = len(peaks)
    bw = w / n
    for i, v in enumerate(peaks):
        bh = max(2.0, v * (h * 0.8))
        p.drawRoundedRect(QRectF(i * bw + 0.5, (h - bh) / 2, max(1.0, bw - 1), bh), 1, 1)
    p.end()
    return img


# ====================================================================== model
class FileModel(QAbstractTableModel):
    def __init__(self):
        super().__init__()
        self.items = []
        self.index_of = {}

    def set_items(self, items):
        self.beginResetModel()
        self.items = sorted(items, key=lambda i: (not i.is_dir, i.name.lower()))
        self.index_of = {it.path: n for n, it in enumerate(self.items)}
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.items)

    def columnCount(self, parent=QModelIndex()):
        return len(COLS)

    def headerData(self, section, orientation, role):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return COLS[section]
        return None

    def item(self, row):
        return self.items[row] if 0 <= row < len(self.items) else None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        it = self.item(index.row())
        if it is None:
            return None
        col = index.column()
        if role == Qt.ItemDataRole.UserRole:
            return it
        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0:
                return it.name
            if col == 1:
                return fmt_time(it.info.duration).split(".")[0] if it.info and it.kind in ("video", "audio") else ""
            if col == 2:
                return details_text(it, short=True)
            if col == 3:
                return "" if it.is_dir else human_size(it.size)
            if col == 4:
                return time.strftime("%d %b %Y  %H:%M", time.localtime(it.mtime))
        if role == Qt.ItemDataRole.DecorationRole and col == 0:
            name = {"folder": "folder", "video": "media", "audio": "music", "image": "image"}.get(it.kind, "doc")
            return QIcon(icons.pixmap(name, 16, theme.C["accent"] if it.is_dir else theme.C["text_dim"]))
        if role == Qt.ItemDataRole.ToolTipRole:
            return it.path
        if role == Qt.ItemDataRole.InitialSortOrderRole:
            return None
        if role == Qt.ItemDataRole.UserRole + 1:          # sort key
            if col == 0:
                return (not it.is_dir, it.name.lower())
            if col == 1:
                return (not it.is_dir, it.info.duration if it.info else 0)
            if col == 3:
                return (not it.is_dir, it.size)
            if col == 4:
                return (not it.is_dir, it.mtime)
            return (not it.is_dir, details_text(it, short=True))
        return None

    def flags(self, index):
        f = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        it = self.item(index.row())
        if it is not None and not it.is_dir and it.kind in ("video", "audio", "image"):
            f |= Qt.ItemFlag.ItemIsDragEnabled
        return f

    def mimeTypes(self):
        return [MEDIA_MIME, "text/uri-list"]

    def mimeData(self, indexes):
        paths = []
        for ix in indexes:
            it = self.item(ix.row())
            if it and not it.is_dir and it.path not in paths:
                paths.append(it.path)
        md = QMimeData()
        md.setData(MEDIA_MIME, "\n".join(paths).encode("utf-8"))
        md.setUrls([QUrl.fromLocalFile(p) for p in paths])
        return md

    def update_detail(self, path, info, img):
        row = self.index_of.get(path)
        if row is None:
            return
        it = self.items[row]
        it.info = info
        it.thumb = img
        self.dataChanged.emit(self.index(row, 0), self.index(row, len(COLS) - 1))


def details_text(it, short=False):
    if it.is_dir:
        return "Folder"
    i = it.info
    if it.kind == "video":
        if not i:
            return "Video"
        bits = [f"{i.width}×{i.height}" if i.width else "", f"{i.fps:.0f} fps" if i.fps else ""]
        if not short:
            bits.append("with sound" if i.has_audio else "no sound")
        return " · ".join(b for b in bits if b)
    if it.kind == "audio":
        if not i:
            return "Audio"
        return f"{i.sample_rate / 1000:g} kHz"
    if it.kind == "image":
        return f"{i.width}×{i.height}" if i and i.width else "Image"
    ext = os.path.splitext(it.name)[1].upper().lstrip(".")
    return f"{ext} file" if ext else "File"


class FilterProxy(QSortFilterProxyModel):
    def __init__(self):
        super().__init__()
        self.kind = "media"
        self.text = ""
        self.setSortRole(Qt.ItemDataRole.UserRole + 1)

    def set_filter(self, kind=None, text=None):
        if kind is not None:
            self.kind = kind
        if text is not None:
            self.text = text.lower().strip()
        self.invalidateFilter()

    def filterAcceptsRow(self, row, parent):
        it = self.sourceModel().item(row)
        if it is None:
            return False
        if self.text and self.text not in it.name.lower():
            return False
        if it.is_dir:
            return True
        if self.kind == "all":
            return True
        if self.kind == "media":
            return it.kind in ("video", "audio", "image")
        return it.kind == self.kind

    def lessThan(self, a, b):
        va = self.sourceModel().data(a, Qt.ItemDataRole.UserRole + 1)
        vb = self.sourceModel().data(b, Qt.ItemDataRole.UserRole + 1)
        try:
            return va < vb
        except TypeError:
            return str(va) < str(vb)


# ====================================================================== grid delegate
class GridDelegate(QStyledItemDelegate):
    CELL = QSize(THUMB.width() + 16, THUMB.height() + 50)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.thumb = QSize(THUMB)

    def set_compact(self, compact):
        self.thumb = QSize(132, 74) if compact else QSize(THUMB)

    def cell(self):
        return QSize(self.thumb.width() + 16, self.thumb.height() + 50)

    def sizeHint(self, option, index):
        return self.cell()

    def paint(self, p, option, index):
        it = index.data(Qt.ItemDataRole.UserRole)
        if it is None:
            return
        c = theme.C
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        r = QRectF(option.rect).adjusted(4, 4, -4, -4)
        sel = bool(option.state & QStyle.StateFlag.State_Selected)
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
        rad = min(10, max(4, c.get("radius", 8)))
        if sel or hover:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(c["accent_soft"] if sel else c["hover"]))
            p.drawRoundedRect(r, rad, rad)
        tr = QRectF(r.left() + 4, r.top() + 4, r.width() - 8, self.thumb.height())
        path = QPainterPath()
        path.addRoundedRect(tr, rad - 2, rad - 2)
        p.setClipPath(path)
        p.fillRect(tr, QColor(c["panel2"]))
        if it.thumb is not None and not it.thumb.isNull():
            img = it.thumb
            s = max(tr.width() / img.width(), tr.height() / img.height()) if it.kind == "video" else \
                min(tr.width() / img.width(), tr.height() / img.height())
            w, h = img.width() * s, img.height() * s
            p.drawImage(QRectF(tr.center().x() - w / 2, tr.center().y() - h / 2, w, h), img)
        else:
            name = {"folder": "folder", "video": "media", "audio": "music", "image": "image"}.get(it.kind, "doc")
            sz = 44 if it.is_dir else 34
            col = c["accent"] if it.is_dir else c["text_dim"]
            p.drawPixmap(int(tr.center().x() - sz / 2), int(tr.center().y() - sz / 2), icons.pixmap(name, sz, col))
        p.setClipping(False)
        # duration badge
        if it.info and it.kind in ("video", "audio") and it.info.duration:
            txt = fmt_time(it.info.duration).split(".")[0]
            f = QFont(option.font)
            f.setPointSizeF(max(6.5, f.pointSizeF() * 0.82) if f.pointSizeF() > 0 else 8)
            f.setBold(True)
            p.setFont(f)
            fm = QFontMetrics(f)
            bw = fm.horizontalAdvance(txt) + 10
            br = QRectF(tr.right() - bw - 5, tr.bottom() - 21, bw, 16)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, 170))
            p.drawRoundedRect(br, 5, 5)
            p.setPen(QColor("#ffffff"))
            p.drawText(br, Qt.AlignmentFlag.AlignCenter, txt)
        # name (two lines)
        p.setFont(option.font)
        p.setPen(QColor(c["text_strong"] if sel else c["text"]))
        nr = QRectF(r.left() + 4, tr.bottom() + 4, r.width() - 8, r.bottom() - tr.bottom() - 6)
        fm = QFontMetrics(option.font)
        name = it.name
        if fm.horizontalAdvance(name) > nr.width() * 2 - 10:
            name = fm.elidedText(name, Qt.TextElideMode.ElideMiddle, int(nr.width() * 2 - 10))
        p.drawText(nr, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWrapAnywhere, name)
        p.restore()


class LocationDelegate(QStyledItemDelegate):
    """Drive rows: name, a capacity bar, then 'x free of y' underneath."""

    def sizeHint(self, option, index):
        s = super().sizeHint(option, index)
        info = index.data(Qt.ItemDataRole.UserRole + 1)
        return QSize(s.width(), 52 if info else max(28, s.height()))

    def paint(self, p, option, index):
        info = index.data(Qt.ItemDataRole.UserRole + 1)
        if not info:
            super().paint(p, option, index)
            return
        used, total = info
        c = theme.C
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(option.rect)
        if option.state & (QStyle.StateFlag.State_Selected | QStyle.StateFlag.State_MouseOver):
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(c["accent_soft"] if option.state & QStyle.StateFlag.State_Selected else c["hover"]))
            p.drawRoundedRect(r.adjusted(1, 1, -1, -1), 6, 6)
        icon = index.data(Qt.ItemDataRole.DecorationRole)
        if icon is not None:
            icon.paint(p, int(r.left() + 4), int(r.top() + 6), 18, 18)
        x = r.left() + 30
        w = max(20.0, r.width() - 40)
        name = index.data(Qt.ItemDataRole.DisplayRole) or ""
        fm = QFontMetrics(option.font)
        p.setFont(option.font)
        p.setPen(QColor(c["text"]))
        p.drawText(QRectF(x, r.top() + 4, w, 18), Qt.AlignmentFlag.AlignVCenter,
                   fm.elidedText(name, Qt.TextElideMode.ElideRight, int(w)))
        y = r.top() + 26
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(c["pressed"]))
        p.drawRoundedRect(QRectF(x, y, w, 4), 2, 2)
        frac = used / total if total else 0
        p.setBrush(QColor(c["danger"] if frac > 0.9 else c["accent"]))
        p.drawRoundedRect(QRectF(x, y, max(3.0, w * frac), 4), 2, 2)
        f = QFont(option.font)
        if f.pointSizeF() > 0:
            f.setPointSizeF(f.pointSizeF() * 0.85)
        p.setFont(f)
        p.setPen(QColor(c["text_dim"]))
        p.drawText(QRectF(x, y + 6, w, 16), Qt.AlignmentFlag.AlignVCenter,
                   f"{human_size(total - used)} free of {human_size(total)}")
        p.restore()


# ====================================================================== locations
def quick_access():
    out = []
    home = os.path.expanduser("~")
    for label, loc, icon in (("Desktop", QStandardPaths.StandardLocation.DesktopLocation, "desktop"),
                             ("Videos", QStandardPaths.StandardLocation.MoviesLocation, "media"),
                             ("Music", QStandardPaths.StandardLocation.MusicLocation, "music"),
                             ("Pictures", QStandardPaths.StandardLocation.PicturesLocation, "image"),
                             ("Downloads", QStandardPaths.StandardLocation.DownloadLocation, "download"),
                             ("Documents", QStandardPaths.StandardLocation.DocumentsLocation, "doc")):
        p = QStandardPaths.writableLocation(loc)
        if p and os.path.isdir(p) and os.path.normcase(p) != os.path.normcase(home):
            out.append((label, p, icon))
    try:
        out.insert(0, ("Easy-Cut Recordings", recordings_dir(), "record"))
    except OSError:
        pass
    od = os.environ.get("OneDrive")
    if od and os.path.isdir(od):
        out.append(("OneDrive", od, "folder"))
    out.append(("Home", home, "folder"))
    return out


def _drive_type(root):
    if sys.platform != "win32":
        return 3
    try:
        import ctypes
        return ctypes.windll.kernel32.GetDriveTypeW(ctypes.c_wchar_p(root))
    except Exception:
        return 3


def drives():
    """[(label, root path, icon, (used, total) or None)] for every mounted storage location."""
    out = []
    seen = set()
    for v in QStorageInfo.mountedVolumes():
        if not v.isValid() or not v.isReady():
            continue
        root = v.rootPath()
        fs = bytes(v.fileSystemType()).decode("ascii", "ignore").lower()
        if sys.platform != "win32":
            if fs in ("tmpfs", "devtmpfs", "proc", "sysfs", "overlay", "squashfs", "cgroup", "cgroup2", "devpts",
                      "mqueue", "debugfs", "tracefs", "securityfs", "pstore", "bpf", "autofs", "fusectl",
                      "configfs", "hugetlbfs", "nsfs", "ramfs", "binfmt_misc", "efivarfs") or \
                    root.startswith(("/proc", "/sys", "/dev", "/run", "/snap", "/boot")):
                continue
        if root in seen:
            continue
        seen.add(root)
        total = v.bytesTotal()
        used = total - v.bytesAvailable()
        dtype = _drive_type(root)
        name = v.displayName() or root
        if sys.platform == "win32":
            letter = root.rstrip("\\/")
            kind = {2: "USB drive", 4: "Network drive", 5: "CD/DVD"}.get(dtype, "Local Disk")
            if name.rstrip("\\/") == letter or not name:
                name = kind
            label = f"{name} ({letter})"
        else:
            label = name if root != "/" else "File system"
        icon = "usb" if dtype == 2 else "drive"
        out.append((label, root, icon, (used, total) if total else None))
    return out


# ====================================================================== the panel
class ExplorerPanel(QWidget):
    addToTimeline = pyqtSignal(list)
    addToMedia = pyqtSignal(list)
    fullViewToggled = pyqtSignal(bool)
    minimiseRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.worker = Worker()
        self.worker.sig.listed.connect(self._listed)
        self.worker.sig.detail.connect(self._detail)
        self.history = []
        self.hpos = -1
        self.folder = ""
        self.gen = 0
        self.full = False
        self.watcher = QFileSystemWatcher(self)
        self.watcher.directoryChanged.connect(lambda _p: self.refresh_timer.start())
        self.refresh_timer = QTimer(self, singleShot=True, interval=700, timeout=self.refresh)
        self.player = None
        self._build()
        start = settings.get("explorer_folder") or ""
        if not os.path.isdir(start):
            start = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.MoviesLocation) or \
                os.path.expanduser("~")
        self.navigate(start)
        theme.notifier.changed.connect(self._theme_changed)

    # ------------------------------------------------------------------ layout
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 8)
        root.setSpacing(8)
        # title row
        top = QHBoxLayout()
        title = QLabel("Explorer")
        title.setObjectName("H2")
        self.title = title
        top.addWidget(title)
        top.addStretch(1)
        self.loc_btn = QToolButton()
        self.loc_btn.setText("Locations")
        self.loc_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        icons.bind(self.loc_btn, "drive", 16)
        self.loc_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.loc_menu = QMenu(self)
        self.loc_menu.aboutToShow.connect(self._fill_loc_menu)
        self.loc_btn.setMenu(self.loc_menu)
        top.addWidget(self.loc_btn)
        self.view_grid = icon_button("grid", "Thumbnails", 16, checkable=True)
        self.view_list = icon_button("list", "Details", 16, checkable=True)
        self.view_grid.clicked.connect(lambda: self.set_view("grid"))
        self.view_list.clicked.connect(lambda: self.set_view("list"))
        top.addWidget(self.view_grid)
        top.addWidget(self.view_list)
        self.full_btn = icon_button("fullscreen", "Full view", 16, checkable=True)
        self.full_btn.toggled.connect(self.set_full)
        top.addWidget(self.full_btn)
        self.min_btn = icon_button("minimise", "Minimise the panel", 16)
        self.min_btn.clicked.connect(self.minimiseRequested)
        top.addWidget(self.min_btn)
        root.addLayout(top)
        # nav row
        nav = QHBoxLayout()
        nav.setSpacing(2)
        self.back_btn = icon_button("back", "Back (Alt+←)", 16)
        self.fwd_btn = icon_button("forward", "Forward (Alt+→)", 16)
        self.up_btn = icon_button("up", "Up one folder (Backspace)", 16)
        self.refresh_btn = icon_button("update", "Refresh", 16)
        self.back_btn.clicked.connect(self.back)
        self.fwd_btn.clicked.connect(self.forward)
        self.up_btn.clicked.connect(self.up)
        self.refresh_btn.clicked.connect(self.refresh)
        for b in (self.back_btn, self.fwd_btn, self.up_btn, self.refresh_btn):
            nav.addWidget(b)
        self.crumbs = Breadcrumbs()
        self.crumbs.navigate.connect(self.navigate)
        nav.addWidget(self.crumbs, 1)
        root.addLayout(nav)
        # search + filter row
        frow = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search this folder")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda t: self.proxy.set_filter(text=t))
        frow.addWidget(self.search, 1)
        self.kind_box = QComboBox()
        for k, label in KIND_FILTERS:
            self.kind_box.addItem(label, k)
        self.kind_box.currentIndexChanged.connect(lambda _i: self.proxy.set_filter(kind=self.kind_box.currentData()))
        frow.addWidget(self.kind_box)
        root.addLayout(frow)
        # body: sidebar | views
        self.split = QSplitter(Qt.Orientation.Horizontal)
        self.split.setChildrenCollapsible(False)
        self.sidebar = QTreeWidget()
        self.sidebar.setHeaderHidden(True)
        self.sidebar.setIndentation(10)
        self.sidebar.setRootIsDecorated(False)
        self.sidebar.setItemDelegate(LocationDelegate(self.sidebar))
        self.sidebar.setMinimumWidth(190)
        self.sidebar.itemClicked.connect(self._loc_clicked)
        self.sidebar.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.sidebar.customContextMenuRequested.connect(self._loc_menu_at)
        self.split.addWidget(self.sidebar)
        self.model = FileModel()
        self.proxy = FilterProxy()
        self.proxy.setSourceModel(self.model)
        self.views = QStackedWidget()
        self.grid = QListView()
        self.grid.setViewMode(QListView.ViewMode.IconMode)
        self.grid.setResizeMode(QListView.ResizeMode.Adjust)
        self.grid.setMovement(QListView.Movement.Static)
        self.grid.setUniformItemSizes(True)
        self.grid_delegate = GridDelegate(self.grid)
        self.grid.setItemDelegate(self.grid_delegate)
        self.grid.setGridSize(self.grid_delegate.cell() + QSize(4, 4))
        self.grid.setMouseTracking(True)
        self.list = QTreeView()
        self.list.setRootIsDecorated(False)
        self.list.setUniformRowHeights(True)
        self.list.setSortingEnabled(True)
        self.list.setAlternatingRowColors(False)
        for v in (self.grid, self.list):
            v.setModel(self.proxy)
            v.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
            v.setDragEnabled(True)
            v.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
            v.doubleClicked.connect(self._activated)
            v.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            v.customContextMenuRequested.connect(lambda pos, v=v: self._file_menu(v, pos))
            v.selectionModel().selectionChanged.connect(self._selection_changed)
            v.setFrameShape(QFrame.Shape.NoFrame)
        hh = self.list.header()
        hh.setStretchLastSection(False)
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in range(1, len(COLS)):
            hh.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        self.list.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self.views.addWidget(self.grid)
        self.views.addWidget(self.list)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        self.status = QLabel("")
        self.status.setObjectName("Dim")
        self.status.hide()
        rl.addWidget(self.status)
        rl.addWidget(self.views, 1)
        self.split.addWidget(right)
        self.split.setStretchFactor(1, 1)
        root.addWidget(self.split, 1)
        # details strip
        self.details = DetailsStrip()
        self.details.addTimeline.connect(lambda: self.addToTimeline.emit(self.selected_files()))
        self.details.addMedia.connect(lambda: self.addToMedia.emit(self.selected_files()))
        self.details.playRequested.connect(self._toggle_play)
        root.addWidget(self.details)
        self.count = QLabel("")
        self.count.setObjectName("Dim")
        root.addWidget(self.count)
        self.set_view(settings.get("explorer_view", "grid"))
        self._fill_sidebar()

    def _theme_changed(self):
        self._fill_sidebar()
        self.grid.viewport().update()

    # ------------------------------------------------------------------ responsive
    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        wide = self.width() >= 640
        self.title.setVisible(self.width() >= 380)
        self.sidebar.setVisible(wide)
        self.loc_btn.setVisible(not wide)
        self.details.set_compact(self.width() < 520)
        compact = self.width() < 560
        if compact != getattr(self, "_compact", None):
            self._compact = compact
            self.grid_delegate.set_compact(compact)
            self.grid.setGridSize(self.grid_delegate.cell() + QSize(4, 4))
            self.crumbs.max_parts = 2 if compact else 4
            self.crumbs.set_path(self.crumbs.path)
            self.grid.doItemsLayout()

    def set_full(self, on):
        self.full = on
        self.full_btn.setChecked(on)
        icons.bind(self.full_btn, "fit" if on else "fullscreen", 16)
        self.full_btn.setToolTip("Back to normal size" if on else "Full view")
        self.min_btn.setVisible(not on)
        self.fullViewToggled.emit(on)
        if on and self.views.currentWidget() is self.grid:
            pass

    # ------------------------------------------------------------------ locations
    def _fill_sidebar(self):
        self.sidebar.clear()
        bold = QFont(self.font())
        bold.setBold(True)

        def section_item(text):
            it = QTreeWidgetItem([text.upper()])
            it.setFlags(Qt.ItemFlag.ItemIsEnabled)
            it.setFont(0, bold)
            it.setForeground(0, QColor(theme.C["text_dim"]))
            self.sidebar.addTopLevelItem(it)
            it.setExpanded(True)
            return it

        def child(parent, label, path, icon, cap=None):
            it = QTreeWidgetItem([label])
            it.setIcon(0, QIcon(icons.pixmap(icon, 18, theme.C["accent"])))
            it.setData(0, Qt.ItemDataRole.UserRole, path)
            it.setData(0, Qt.ItemDataRole.UserRole + 1, cap)
            it.setToolTip(0, path)
            parent.addChild(it)
            return it

        qa = section_item("Quick access")
        for label, path, icon in quick_access():
            child(qa, label, path, icon)
        favs = [p for p in settings.get("explorer_favourites", []) if os.path.isdir(p)]
        if favs:
            fv = section_item("Favourites")
            for p in favs:
                child(fv, os.path.basename(p.rstrip("\\/")) or p, p, "star")
        dv = section_item("This PC")
        for label, root, icon, cap in drives():
            child(dv, label, root, icon, cap)
        rec = [p for p in settings.get("explorer_recent", []) if os.path.isdir(p)][:6]
        if rec:
            rc = section_item("Recent folders")
            for p in rec:
                child(rc, os.path.basename(p.rstrip("\\/")) or p, p, "clock")
        self.sidebar.expandAll()

    def _loc_clicked(self, item, _col):
        path = item.data(0, Qt.ItemDataRole.UserRole)
        if path:
            self.navigate(path)

    def _fill_loc_menu(self):
        m = self.loc_menu
        m.clear()
        m.addSection("Quick access")
        for label, path, icon in quick_access():
            m.addAction(QIcon(icons.pixmap(icon, 16, theme.C["accent"])), label, lambda p=path: self.navigate(p))
        favs = [p for p in settings.get("explorer_favourites", []) if os.path.isdir(p)]
        if favs:
            m.addSection("Favourites")
            for p in favs:
                m.addAction(QIcon(icons.pixmap("star", 16, theme.C["accent"])), os.path.basename(p.rstrip("\\/")),
                            lambda p=p: self.navigate(p))
        m.addSection("This PC")
        for label, root, icon, cap in drives():
            free = f"  ·  {human_size(cap[1] - cap[0])} free" if cap else ""
            m.addAction(QIcon(icons.pixmap(icon, 16, theme.C["accent"])), label + free,
                        lambda p=root: self.navigate(p))

    def _loc_menu_at(self, pos):
        item = self.sidebar.itemAt(pos)
        path = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        if not path:
            return
        m = QMenu(self)
        favs = settings.get("explorer_favourites", [])
        if path in favs:
            m.addAction("Remove from favourites", lambda: self.set_favourite(path, False))
        else:
            m.addAction("Add to favourites", lambda: self.set_favourite(path, True))
        m.exec(self.sidebar.mapToGlobal(pos))

    def set_favourite(self, path, on):
        favs = [p for p in settings.get("explorer_favourites", []) if p != path]
        if on:
            favs.append(path)
        settings.set("explorer_favourites", favs)
        self._fill_sidebar()

    # ------------------------------------------------------------------ navigation
    def navigate(self, folder, record=True):
        folder = os.path.abspath(folder)
        if not os.path.isdir(folder):
            return
        if record:
            del self.history[self.hpos + 1:]
            if not self.history or self.history[-1] != folder:
                self.history.append(folder)
            self.hpos = len(self.history) - 1
        self.folder = folder
        self.crumbs.set_path(folder)
        self.search.clear()
        self.status.hide()
        self._stop_preview()
        for d in self.watcher.directories():
            self.watcher.removePath(d)
        self.watcher.addPath(folder)
        self.gen = self.worker.list(folder)
        settings.set("explorer_folder", folder)
        rec = [p for p in settings.get("explorer_recent", []) if p != folder]
        settings.set("explorer_recent", [folder] + rec[:9])
        self._update_nav()

    def refresh(self):
        if self.folder:
            sel = self.selected_files()
            self.gen = self.worker.list(self.folder)
            self._reselect = sel

    def back(self):
        if self.hpos > 0:
            self.hpos -= 1
            self.navigate(self.history[self.hpos], record=False)

    def forward(self):
        if self.hpos < len(self.history) - 1:
            self.hpos += 1
            self.navigate(self.history[self.hpos], record=False)

    def up(self):
        parent = os.path.dirname(self.folder.rstrip("\\/"))
        if parent and parent != self.folder and os.path.isdir(parent):
            self.navigate(parent if not (sys.platform == "win32" and len(parent) == 2) else parent + "\\")

    def _update_nav(self):
        self.back_btn.setEnabled(self.hpos > 0)
        self.fwd_btn.setEnabled(self.hpos < len(self.history) - 1)
        parent = os.path.dirname(self.folder.rstrip("\\/"))
        self.up_btn.setEnabled(bool(parent) and parent != self.folder)

    def _listed(self, gen, folder, items, err):
        if gen != self.gen:
            return
        self.model.set_items(items)
        if err:
            self.status.setText(f"Can't open this folder: {err}")
            self.status.show()
        n_media = sum(1 for i in items if i.kind in ("video", "audio", "image"))
        n_dirs = sum(1 for i in items if i.is_dir)
        self.count.setText(f"{n_dirs} folder{'s' if n_dirs != 1 else ''} · {n_media} media file"
                           f"{'s' if n_media != 1 else ''}")
        self.worker.details(gen, [i for i in self.model.items if i.kind in ("video", "audio", "image")][:800])
        reselect = getattr(self, "_reselect", None)
        if reselect:
            self.select_paths(reselect)
            self._reselect = None
        else:
            self.details.show_item(None)

    def _detail(self, gen, path, info, img):
        if gen != self.gen:
            return
        self.model.update_detail(path, info, img)
        cur = self.current_item()
        if cur is not None and cur.path == path:
            self.details.show_item(cur)

    # ------------------------------------------------------------------ views & selection
    def set_view(self, which):
        self.views.setCurrentWidget(self.grid if which == "grid" else self.list)
        self.view_grid.setChecked(which == "grid")
        self.view_list.setChecked(which != "grid")
        settings.set("explorer_view", which)

    def current_view(self):
        return self.views.currentWidget()

    def selected_items(self):
        v = self.current_view()
        rows = sorted({self.proxy.mapToSource(ix).row() for ix in v.selectionModel().selectedIndexes()})
        return [self.model.item(r) for r in rows if self.model.item(r) is not None]

    def selected_files(self):
        return [i.path for i in self.selected_items() if not i.is_dir and i.kind in ("video", "audio", "image")]

    def current_item(self):
        items = self.selected_items()
        return items[0] if items else None

    def select_paths(self, paths):
        v = self.current_view()
        sm = v.selectionModel()
        sm.clear()
        for p in paths:
            row = self.model.index_of.get(p)
            if row is not None:
                ix = self.proxy.mapFromSource(self.model.index(row, 0))
                sm.select(ix, sm.SelectionFlag.Select | sm.SelectionFlag.Rows)

    def _selection_changed(self, *_):
        self._stop_preview()
        items = self.selected_items()
        self.details.show_item(items[0] if len(items) == 1 else None, len(items))
        if len(items) == 1 and settings.get("explorer_autoplay", False) and items[0].kind in ("audio", "video"):
            self._toggle_play()

    def _activated(self, ix):
        it = self.model.item(self.proxy.mapToSource(ix).row())
        if it is None:
            return
        if it.is_dir:
            self.navigate(it.path)
        elif it.kind in ("video", "audio", "image"):
            self.addToTimeline.emit([it.path])

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key.Key_Backspace:
            self.up()
        elif ev.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            items = self.selected_items()
            if len(items) == 1 and items[0].is_dir:
                self.navigate(items[0].path)
            elif self.selected_files():
                self.addToTimeline.emit(self.selected_files())
        elif ev.modifiers() & Qt.KeyboardModifier.AltModifier and ev.key() == Qt.Key.Key_Left:
            self.back()
        elif ev.modifiers() & Qt.KeyboardModifier.AltModifier and ev.key() == Qt.Key.Key_Right:
            self.forward()
        else:
            super().keyPressEvent(ev)

    def _file_menu(self, view, pos):
        ix = view.indexAt(pos)
        it = self.model.item(self.proxy.mapToSource(ix).row()) if ix.isValid() else None
        m = QMenu(self)
        files = self.selected_files()
        if it is not None and it.is_dir:
            m.addAction("Open", lambda: self.navigate(it.path))
            favs = settings.get("explorer_favourites", [])
            if it.path in favs:
                m.addAction("Remove from favourites", lambda: self.set_favourite(it.path, False))
            else:
                m.addAction("Add to favourites", lambda: self.set_favourite(it.path, True))
        if files:
            m.addAction("Add to timeline", lambda: self.addToTimeline.emit(files))
            m.addAction("Add to media", lambda: self.addToMedia.emit(files))
        if it is not None:
            m.addSeparator()
            m.addAction("Show in system Explorer", lambda: self._reveal(it.path))
        m.addSeparator()
        m.addAction("Add this folder to favourites", lambda: self.set_favourite(self.folder, True))
        m.addAction("Refresh", self.refresh)
        m.exec(view.viewport().mapToGlobal(pos))

    @staticmethod
    def _reveal(path):
        import subprocess
        if sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        else:
            from PyQt6.QtGui import QDesktopServices
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(path)))

    # ------------------------------------------------------------------ preview playback
    def _toggle_play(self):
        it = self.current_item()
        if it is None or it.kind not in ("audio", "video"):
            return
        if self.player is not None and self.details.playing:
            self._stop_preview()
            return
        try:
            from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
        except Exception:
            return
        if self.player is None:
            self.player = QMediaPlayer(self)
            self.audio_out = QAudioOutput(self)
            self.player.setAudioOutput(self.audio_out)
            self.player.playbackStateChanged.connect(
                lambda st: self.details.set_playing(st == QMediaPlayer.PlaybackState.PlayingState))
        self.details.attach_video(self.player if it.kind == "video" else None)
        self.player.setSource(QUrl.fromLocalFile(it.path))
        self.player.play()

    def _stop_preview(self):
        if self.player is not None:
            self.player.stop()
            self.details.attach_video(None)
        self.details.set_playing(False)

    def hideEvent(self, ev):
        self._stop_preview()
        super().hideEvent(ev)


class Breadcrumbs(QWidget):
    """Clickable path segments; click the empty area (or type) to edit the path."""
    navigate = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setObjectName("Crumbs")
        self.lay = QHBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(0)
        self.stack = QStackedWidget()
        self.bar = QWidget()
        self.bar_lay = QHBoxLayout(self.bar)
        self.bar_lay.setContentsMargins(4, 0, 4, 0)
        self.bar_lay.setSpacing(0)
        self.edit = QLineEdit()
        self.edit.returnPressed.connect(self._typed)
        self.edit.editingFinished.connect(lambda: self.stack.setCurrentWidget(self.bar))
        self.stack.addWidget(self.bar)
        self.stack.addWidget(self.edit)
        self.lay.addWidget(self.stack)
        self.path = ""
        self.max_parts = 4
        self.setMinimumWidth(80)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_path(self, path):
        self.path = path
        while self.bar_lay.count():
            it = self.bar_lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        parts = []
        p = path
        while True:
            head, tail = os.path.split(p.rstrip("\\/")) if p.rstrip("\\/") else (p, "")
            if not tail:
                parts.append((p, p.rstrip("\\/") or p))
                break
            parts.append((p, tail))
            if head == p:
                break
            p = head
        parts.reverse()
        if len(parts) > self.max_parts:
            parts = [(None, "…")] + parts[-(self.max_parts - 1 if self.max_parts > 2 else 2):]
        for i, (full, label) in enumerate(parts):
            if i:
                sep = QLabel("›")
                sep.setObjectName("Dim")
                self.bar_lay.addWidget(sep)
            b = QPushButton(label)
            b.setObjectName("Flat")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            if full is None:
                b.setEnabled(False)
            else:
                b.clicked.connect(lambda _=False, f=full: self.navigate.emit(f))
            if i == len(parts) - 1:
                f = b.font()
                f.setBold(True)
                b.setFont(f)
            self.bar_lay.addWidget(b)
        self.bar_lay.addStretch(1)
        self.stack.setCurrentWidget(self.bar)

    def mousePressEvent(self, ev):
        self.edit.setText(self.path)
        self.stack.setCurrentWidget(self.edit)
        self.edit.setFocus()
        self.edit.selectAll()

    def _typed(self):
        p = os.path.expandvars(os.path.expanduser(self.edit.text().strip().strip('"')))
        self.stack.setCurrentWidget(self.bar)
        if os.path.isdir(p):
            self.navigate.emit(p)


class DetailsStrip(QFrame):
    addTimeline = pyqtSignal()
    addMedia = pyqtSignal()
    playRequested = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setObjectName("Card")
        self.playing = False
        h = QHBoxLayout(self)
        h.setContentsMargins(8, 8, 10, 8)
        h.setSpacing(10)
        self.pic_stack = QStackedWidget()
        self.pic_stack.setFixedSize(128, 72)
        self.pic = QLabel()
        self.pic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.pic_stack.addWidget(self.pic)
        self.video = None
        h.addWidget(self.pic_stack)
        v = QVBoxLayout()
        v.setSpacing(2)
        self.name = QLabel("Select a file to see its details")
        self.name.setObjectName("H2")
        self.info = QLabel("Double-click or drag media onto the timeline.")
        self.info.setObjectName("Dim")
        self.info.setWordWrap(True)
        v.addWidget(self.name)
        v.addWidget(self.info)
        btns = QHBoxLayout()
        self.play_btn = QPushButton("  Play")
        icons.bind(self.play_btn, "play", 14)
        self.play_btn.clicked.connect(self.playRequested)
        self.add_btn = QPushButton("  Add to timeline")
        self.add_btn.setObjectName("Primary")
        icons.bind(self.add_btn, "plus", 14, "accent_text")
        self.add_btn.clicked.connect(self.addTimeline)
        self.media_btn = QPushButton("Add to media")
        self.media_btn.clicked.connect(self.addMedia)
        for b in (self.play_btn, self.add_btn, self.media_btn):
            btns.addWidget(b)
        btns.addStretch(1)
        v.addLayout(btns)
        h.addLayout(v, 1)
        self.show_item(None)

    def set_compact(self, compact):
        self.pic_stack.setVisible(not compact)
        self.media_btn.setVisible(not compact)

    def show_item(self, it, count=0):
        has = it is not None and not it.is_dir and it.kind in ("video", "audio", "image")
        multi = count > 1
        self.add_btn.setEnabled(has or multi)
        self.media_btn.setEnabled(has or multi)
        self.play_btn.setVisible(has and it.kind in ("audio", "video"))
        if multi:
            self.name.setText(f"{count} items selected")
            self.info.setText("Add them to the timeline in one go.")
            self.pic.setPixmap(icons.pixmap("media", 34, theme.C["text_dim"]))
            return
        if it is None:
            self.name.setText("Select a file to see its details")
            self.info.setText("Double-click or drag media onto the timeline.")
            self.pic.setPixmap(icons.pixmap("folder", 34, theme.C["text_dim"]))
            return
        fm = QFontMetrics(self.name.font())
        self.name.setText(fm.elidedText(it.name, Qt.TextElideMode.ElideMiddle, max(120, self.width() - 200)))
        self.name.setToolTip(it.path)
        bits = []
        if it.kind in ("video", "audio") and it.info:
            bits.append(fmt_time(it.info.duration).split(".")[0])
        d = details_text(it)
        if d:
            bits.append(d)
        if not it.is_dir:
            bits.append(human_size(it.size))
        bits.append(time.strftime("%d %b %Y", time.localtime(it.mtime)))
        self.info.setText("  ·  ".join(bits))
        if it.thumb is not None and not it.thumb.isNull():
            pm = QPixmap.fromImage(it.thumb).scaled(QSize(128, 72), Qt.AspectRatioMode.KeepAspectRatio,
                                                    Qt.TransformationMode.SmoothTransformation)
            self.pic.setPixmap(pm)
        else:
            name = {"folder": "folder", "video": "media", "audio": "music", "image": "image"}.get(it.kind, "doc")
            self.pic.setPixmap(icons.pixmap(name, 34, theme.C["text_dim"]))

    def set_playing(self, on):
        self.playing = on
        icons.bind(self.play_btn, "stop" if on else "play", 14)
        self.play_btn.setText("  Stop" if on else "  Play")

    def attach_video(self, player):
        if player is None:
            self.pic_stack.setCurrentWidget(self.pic)
            return
        try:
            from PyQt6.QtMultimediaWidgets import QVideoWidget
        except Exception:
            return
        if self.video is None:
            self.video = QVideoWidget()
            self.pic_stack.addWidget(self.video)
        player.setVideoOutput(self.video)
        self.pic_stack.setCurrentWidget(self.video)
