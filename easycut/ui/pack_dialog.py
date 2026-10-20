"""'Get this pack' prompt: shows what's inside a pack, downloads it with a progress bar and installs it."""
import threading

from PyQt6.QtCore import Qt, QObject, pyqtSignal, QSize
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QWidget

from .. import catalog, extensions, updater, icons
from .widgets import RenderProgressBar, FlowLayout


class _Sig(QObject):
    progress = pyqtSignal(str, float)
    done = pyqtSignal(list, list)            # installed pack ids, pack ids that need a restart
    failed = pyqtSignal(str)


def install_packs(pack_ids, progress=None):
    """Download + install packs (blocking). Returns (installed ids, ids needing a restart)."""
    need_manifest = any(not (catalog.pack(pid) or {}).get("url") for pid in pack_ids)
    if need_manifest:
        if progress:
            progress("Checking for packs…", 0.0)
        m = updater.fetch_manifest()
        catalog.merge_manifest(m.get("extensions", []))
    done, restart = [], []
    for n, pid in enumerate(pack_ids):
        p = catalog.pack(pid) or {}
        if not p.get("url"):
            raise RuntimeError(f"{p.get('name', pid)} isn't available to download yet.")
        label = p.get("name", pid)

        def prog(f, n=n, label=label):
            if progress:
                progress(f"Downloading {label}…", (n + f) / len(pack_ids))

        data = updater.download(p["url"], p.get("sha256"), prog)
        if progress:
            progress(f"Installing {label}…", (n + 1) / len(pack_ids))
        ext, needs_restart = extensions.install_zip(data)
        if ext.error:
            raise RuntimeError(f"{label} was downloaded but couldn't start:\n{ext.error}")
        done.append(pid)
        if needs_restart:
            restart.append(pid)
    return done, restart


class PackDialog(QDialog):
    def __init__(self, pack_ids, item_name=None, parent=None, autostart=False):
        super().__init__(parent)
        from .panels import item_thumb
        self.pack_ids = list(pack_ids)
        self.installed_ids, self.restart_ids = [], []
        packs = [catalog.pack(pid) or {"id": pid, "name": pid, "items": []} for pid in self.pack_ids]
        single = len(packs) == 1
        self.setWindowTitle("Get pack" if single else "Get packs")
        self.setMinimumWidth(560)
        v = QVBoxLayout(self)
        v.setContentsMargins(22, 20, 22, 18)
        v.setSpacing(10)
        top = QHBoxLayout()
        ic = QLabel()
        ic.setPixmap(icons.pixmap("extensions", 34))
        top.addWidget(ic, 0, Qt.AlignmentFlag.AlignTop)
        tv = QVBoxLayout()
        title = QLabel(f"Get {packs[0].get('name')}" if single else f"Get {len(packs)} packs")
        title.setObjectName("H1")
        title.setWordWrap(True)
        tv.addWidget(title)
        if item_name:
            sub = QLabel(f"“{item_name}” is part of this free pack. Download it once and everything inside "
                         "is yours to use.")
        elif single:
            sub = QLabel(packs[0].get("description", ""))
        else:
            sub = QLabel(", ".join(p.get("name", p["id"]) for p in packs))
        sub.setObjectName("Dim")
        sub.setWordWrap(True)
        tv.addWidget(sub)
        top.addLayout(tv, 1)
        v.addLayout(top)
        if single:
            grid = QWidget()
            flow = FlowLayout(grid, 8)
            for it in packs[0].get("items", []):
                cell = QWidget()
                cv = QVBoxLayout(cell)
                cv.setContentsMargins(0, 0, 0, 0)
                cv.setSpacing(3)
                img = item_thumb(it["type"], it["id"])
                pic = QLabel()
                pic.setFixedSize(96, 60)
                if img is not None:
                    pic.setPixmap(QPixmap.fromImage(img).scaled(QSize(96, 60),
                                                                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                                                Qt.TransformationMode.SmoothTransformation))
                cv.addWidget(pic)
                name = it.get("name", it["id"])
                nl = QLabel(("★ " if name == item_name else "") + name)
                nl.setFixedWidth(96)
                nl.setAlignment(Qt.AlignmentFlag.AlignHCenter)
                if name == item_name:
                    nl.setStyleSheet("font-weight: 700;")
                cv.addWidget(nl)
                flow.addWidget(cell)
            v.addWidget(grid)
        size = sum(int(p.get("size") or 0) for p in packs)
        n_items = sum(len(p.get("items", [])) for p in packs)
        info = QLabel(f"{n_items} items" + (f"  ·  {catalog.size_label({'size': size})} download" if size else "")
                      + "  ·  free")
        info.setObjectName("Dim")
        v.addWidget(info)
        self.status = QLabel("")
        self.bar = RenderProgressBar()
        self.status.hide()
        self.bar.hide()
        v.addWidget(self.status)
        v.addWidget(self.bar)
        row = QHBoxLayout()
        row.addStretch(1)
        self.cancel_btn = QPushButton("Not now")
        self.cancel_btn.clicked.connect(self.reject)
        self.go_btn = QPushButton("  Download pack" if single else f"  Download {len(packs)} packs")
        self.go_btn.setObjectName("Primary")
        icons.bind(self.go_btn, "download", 16, "accent_text")
        self.go_btn.clicked.connect(self.start)
        row.addWidget(self.cancel_btn)
        row.addWidget(self.go_btn)
        v.addLayout(row)
        self.sig = _Sig()
        self.sig.progress.connect(self._progress)
        self.sig.done.connect(self._done)
        self.sig.failed.connect(self._failed)
        if autostart:
            self.start()

    def start(self):
        self.go_btn.setEnabled(False)
        self.cancel_btn.setEnabled(False)
        self.status.show()
        self.bar.show()
        self.status.setText("Starting…")
        self.bar.setValue(0)

        def work():
            try:
                done, restart = install_packs(self.pack_ids, lambda t, f: self.sig.progress.emit(t, f))
                self.sig.done.emit(done, restart)
            except Exception as e:  # noqa: BLE001 - shown to the user
                msg = str(e)
                if "urlopen" in msg or "Errno" in msg or "timed out" in msg or "getaddrinfo" in msg:
                    msg = "Couldn't reach the download server. Check your internet connection and try again."
                self.sig.failed.emit(msg)

        threading.Thread(target=work, daemon=True).start()

    def _progress(self, text, frac):
        self.status.setText(text)
        self.bar.setValue(frac)

    def _done(self, done, restart):
        self.installed_ids, self.restart_ids = done, restart
        self.bar.setValue(1.0)
        self.accept()

    def _failed(self, msg):
        self.bar.stop()
        self.bar.hide()
        self.status.setText(msg)
        self.status.setWordWrap(True)
        self.go_btn.setEnabled(True)
        self.go_btn.setText("  Try again")
        self.cancel_btn.setEnabled(True)
        self.cancel_btn.setText("Close")
