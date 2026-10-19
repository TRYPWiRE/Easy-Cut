"""Export dialog: canvas shape, quality, frame rate, format - then a light progress view while rendering."""
import os
import subprocess
import sys

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox, QButtonGroup,
                             QGridLayout, QLineEdit, QFileDialog, QStackedWidget, QWidget, QMessageBox)

from .. import formats, media, render, settings, icons, theme
from .widgets import RenderProgressBar, section, Toggle


class RenderThread(QThread):
    progress = pyqtSignal(str, float, object)
    finishedOk = pyqtSignal(str)
    failed = pyqtSignal(str)
    cancelled = pyqtSignal()

    def __init__(self, renderer):
        super().__init__()
        self.renderer = renderer

    def run(self):
        try:
            out = self.renderer.run(lambda ph, f, eta=None: self.progress.emit(ph, f, eta))
            self.finishedOk.emit(out)
        except render.RenderCancelled:
            self.cancelled.emit()
        except Exception as e:  # noqa: BLE001 - shown to the user
            self.failed.emit(str(e))
        finally:
            self.renderer.cleanup()


class AspectCard(QPushButton):
    def __init__(self, key):
        name, true, rw, rh, use = formats.ASPECTS[key]
        super().__init__()
        self.key = key
        self.setObjectName("Tile")
        self.setCheckable(True)
        self.setFixedSize(132, 104)
        self.setToolTip(f"{name} - {true}\n{use}")
        self.name, self.true, self.rw, self.rh = name, true, rw, rh

    def paintEvent(self, ev):
        super().paintEvent(ev)
        from PyQt6.QtGui import QPainter, QColor, QPen
        from PyQt6.QtCore import QRectF
        c = theme.C
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        box = 40
        s = box / max(self.rw, self.rh)
        w, h = self.rw * s, self.rh * s
        r = QRectF((self.width() - w) / 2, 10 + (box - h) / 2, w, h)
        p.setPen(QPen(QColor(c["accent"] if self.isChecked() else c["text_dim"]), 2))
        p.drawRoundedRect(r, 3, 3)
        p.setPen(QColor(c["text_strong"]))
        f = p.font()
        f.setBold(True)
        p.setFont(f)
        p.drawText(QRectF(0, 56, self.width(), 18), Qt.AlignmentFlag.AlignHCenter, self.name)
        f.setBold(False)
        if f.pointSizeF() > 0:
            f.setPointSizeF(f.pointSizeF() * 0.9)
        else:
            f.setPixelSize(max(8, int(f.pixelSize() * 0.9)))
        p.setFont(f)
        p.setPen(QColor(c["text_dim"]))
        p.drawText(QRectF(0, 76, self.width(), 18), Qt.AlignmentFlag.AlignHCenter, self.true)


class RenderDialog(QDialog):
    aspectChanged = pyqtSignal(str)

    def __init__(self, project, parent=None):
        super().__init__(parent)
        self.project = project
        self.setWindowTitle("Export video")
        self.setMinimumWidth(640)
        self.thread = None
        self.out_path = ""
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 18)
        self.stack = QStackedWidget()
        lay.addWidget(self.stack)
        self.stack.addWidget(self._settings_page())
        self.stack.addWidget(self._progress_page())

    # ------------------------------------------------------------------ settings
    def _settings_page(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        title = QLabel("Export")
        title.setObjectName("H1")
        lay.addWidget(title)
        lay.addWidget(section("Shape"))
        grid = QGridLayout()
        grid.setSpacing(8)
        self.aspect_group = QButtonGroup(self)
        for i, key in enumerate(formats.ASPECT_ORDER):
            card = AspectCard(key)
            card.setChecked(key == self.project.aspect)
            self.aspect_group.addButton(card)
            card.clicked.connect(self._update_summary)
            grid.addWidget(card, i // 4, i % 4)
        lay.addLayout(grid)
        row = QHBoxLayout()
        col = QVBoxLayout()
        col.addWidget(section("Quality"))
        self.quality = QComboBox()
        for k, label in formats.QUALITY_LABELS.items():
            self.quality.addItem(label, k)
        self.quality.setCurrentIndex(0)
        self.quality.currentIndexChanged.connect(self._update_summary)
        col.addWidget(self.quality)
        row.addLayout(col)
        col = QVBoxLayout()
        col.addWidget(section("Frame rate"))
        self.fps = QComboBox()
        for f in formats.FPS_OPTIONS:
            self.fps.addItem(formats.FPS_LABELS[f], f)
        self.fps.setCurrentIndex(1)
        self.fps.currentIndexChanged.connect(self._fps_changed)
        col.addWidget(self.fps)
        row.addLayout(col)
        col = QVBoxLayout()
        col.addWidget(section("Format"))
        self.fmt = QComboBox()
        for k, (label, ext) in formats.FORMATS.items():
            self.fmt.addItem(label, k)
        self.fmt.currentIndexChanged.connect(self._fmt_changed)
        col.addWidget(self.fmt)
        row.addLayout(col)
        lay.addLayout(row)
        row = QHBoxLayout()
        col = QVBoxLayout()
        col.addWidget(section("Encoder"))
        self.encoder = QComboBox()
        self.encoder.addItem("Automatic (graphics card when available)", "auto")
        self.encoder.addItem("CPU (x264)", "cpu")
        try:
            for enc, label in media.hardware_encoders():
                self.encoder.addItem(label, enc)
        except Exception:
            pass
        if not settings.get("hardware_encoding", True):
            self.encoder.setCurrentIndex(1)
        col.addWidget(self.encoder)
        row.addLayout(col, 2)
        col = QVBoxLayout()
        col.addWidget(section("While exporting"))
        self.low_impact = Toggle("Keep my PC responsive")
        self.low_impact.setChecked(True)
        self.low_impact.setToolTip("Runs the export at lower priority so the rest of your PC stays smooth")
        col.addWidget(self.low_impact)
        row.addLayout(col, 1)
        lay.addLayout(row)
        lay.addWidget(section("Save to"))
        row = QHBoxLayout()
        self.path = QLineEdit()
        base = settings.get("last_export_dir") or os.path.join(os.path.expanduser("~"), "Videos")
        if not os.path.isdir(base):
            base = os.path.expanduser("~")
        self.path.setText(os.path.join(base, f"{self.project.name or 'Easy-Cut video'}.mp4"))
        row.addWidget(self.path, 1)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        row.addWidget(browse)
        lay.addLayout(row)
        self.summary = QLabel("")
        self.summary.setObjectName("Dim")
        lay.addWidget(self.summary)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        self.go = QPushButton("  Export")
        self.go.setObjectName("Primary")
        icons.bind(self.go, "export", 16, "accent_text")
        self.go.clicked.connect(self.start)
        row.addWidget(cancel)
        row.addWidget(self.go)
        lay.addLayout(row)
        self._update_summary()
        return w

    def aspect(self):
        b = self.aspect_group.checkedButton()
        return b.key if b else self.project.aspect

    def _fps_changed(self):
        if self.fps.currentData() == 10 and self.fmt.currentData() != "gif":
            self.fmt.setCurrentIndex(self.fmt.findData("gif"))
        self._update_summary()

    def _fmt_changed(self):
        ext = formats.FORMATS[self.fmt.currentData()][1]
        root, _ = os.path.splitext(self.path.text())
        self.path.setText(root + ext)
        is_gif = self.fmt.currentData() == "gif"
        self.encoder.setEnabled(self.fmt.currentData() == "mp4")
        if is_gif and self.fps.currentData() != 10:
            self.fps.setCurrentIndex(0)
        self._update_summary()

    def _browse(self):
        ext = formats.FORMATS[self.fmt.currentData()][1]
        p, _ = QFileDialog.getSaveFileName(self, "Export video", self.path.text(), f"Video (*{ext})")
        if p:
            if not p.lower().endswith(ext):
                p += ext
            self.path.setText(p)

    def _update_summary(self):
        a = self.aspect()
        w, h = formats.canvas_size(a, self.quality.currentData())
        name, true, *_ = formats.ASPECTS[a]
        d = self.project.duration()
        txt = f"{name} ({true}) · {w}×{h} · {self.fps.currentData()} fps · {d:.1f}s"
        if self.fmt.currentData() == "gif" and h * w > 1920 * 1080:
            txt += "  ·  Tip: GIFs this large get very big - 1080p is usually plenty."
        if a != self.project.aspect:
            txt += "\nThis also changes your project's canvas to " + name + "."
        self.summary.setText(txt)

    # ------------------------------------------------------------------ progress
    def _progress_page(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 10, 0, 0)
        lay.setSpacing(12)
        self.p_title = QLabel("Rendering your video")
        self.p_title.setObjectName("H1")
        lay.addWidget(self.p_title)
        self.p_file = QLabel("")
        self.p_file.setObjectName("Dim")
        lay.addWidget(self.p_file)
        lay.addSpacing(10)
        row = QHBoxLayout()
        self.p_phase = QLabel("Preparing")
        row.addWidget(self.p_phase)
        row.addStretch(1)
        self.p_pct = QLabel("0%")
        self.p_pct.setObjectName("H2")
        row.addWidget(self.p_pct)
        lay.addLayout(row)
        self.bar = RenderProgressBar()
        lay.addWidget(self.bar)
        self.p_eta = QLabel("")
        self.p_eta.setObjectName("Dim")
        lay.addWidget(self.p_eta)
        lay.addStretch(1)
        row = QHBoxLayout()
        self.open_btn = QPushButton("Open video")
        self.folder_btn = QPushButton("Show in folder")
        self.open_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(self.out_path)))
        self.folder_btn.clicked.connect(self._show_folder)
        row.addWidget(self.open_btn)
        row.addWidget(self.folder_btn)
        row.addStretch(1)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.cancel)
        row.addWidget(self.cancel_btn)
        lay.addLayout(row)
        self.open_btn.hide()
        self.folder_btn.hide()
        return w

    def _show_folder(self):
        if sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", os.path.normpath(self.out_path)])
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(self.out_path)))

    def start(self):
        path = self.path.text().strip()
        if not path:
            return
        folder = os.path.dirname(path) or "."
        if not os.path.isdir(folder):
            try:
                os.makedirs(folder, exist_ok=True)
            except OSError:
                QMessageBox.warning(self, "Export", "That folder can't be created.")
                return
        if os.path.exists(path):
            r = QMessageBox.question(self, "Export", f"{os.path.basename(path)} already exists. Replace it?")
            if r != QMessageBox.StandardButton.Yes:
                return
        if self.aspect() != self.project.aspect:
            self.aspectChanged.emit(self.aspect())
        settings.set("last_export_dir", folder)
        settings.set("hardware_encoding", self.encoder.currentData() != "cpu")
        opts = render.RenderOptions(aspect=self.aspect(), quality=self.quality.currentData(),
                                    fps=self.fps.currentData(), fmt=self.fmt.currentData(), out_path=path,
                                    encoder=self.encoder.currentData(), low_impact=self.low_impact.isChecked())
        self.out_path = path
        from ..project import Project
        snapshot = Project.from_dict(self.project.to_dict())   # render a frozen copy
        self.renderer = render.Renderer(snapshot, opts)
        self.thread = RenderThread(self.renderer)
        self.thread.progress.connect(self._progress)
        self.thread.finishedOk.connect(self._done)
        self.thread.failed.connect(self._failed)
        self.thread.cancelled.connect(self._cancelled)
        w, h = opts.size
        self.p_file.setText(f"{os.path.basename(path)}  ·  {w}×{h}  ·  {opts.fps} fps")
        self.stack.setCurrentIndex(1)
        from PyQt6.QtWidgets import QSizePolicy
        self.stack.widget(0).setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.stack.adjustSize()
        self.setMinimumHeight(0)
        self.resize(self.width(), 300)
        self.bar.setValue(0)
        self.thread.start()

    def _progress(self, phase, frac, eta):
        self.p_phase.setText(phase)
        if frac > 0 and phase == "Rendering":
            self.p_title.setText("Rendering your video")
        self.bar.setValue(frac)
        self.p_pct.setText(f"{int(frac * 100)}%")
        if eta is not None and eta > 0:
            m, s = divmod(int(eta), 60)
            self.p_eta.setText(f"About {m}m {s:02d}s left" if m else f"About {s}s left")

    def _done(self, path):
        enc = getattr(self.renderer, "encoder", None)
        label = {"h264_nvenc": "NVIDIA GPU", "h264_qsv": "Intel GPU", "h264_amf": "AMD GPU"}.get(enc, "CPU")
        self.bar.setValue(1.0)
        self.p_pct.setText("100%")
        self.p_title.setText("Your video is ready 🎉")
        self.p_phase.setText("Done")
        size = os.path.getsize(path) / (1024 * 1024) if os.path.exists(path) else 0
        self.p_eta.setText(f"{size:.1f} MB · encoded on the {label}" if self.fmt.currentData() == "mp4"
                           else f"{size:.1f} MB")
        self.cancel_btn.setText("Close")
        self.cancel_btn.clicked.disconnect()
        self.cancel_btn.clicked.connect(self.accept)
        self.open_btn.show()
        self.folder_btn.show()

    def _failed(self, msg):
        self.bar.stop()
        self.p_title.setText("Export failed")
        self.p_phase.setText("Something went wrong")
        self.p_eta.setText(msg[-600:])
        self.p_eta.setWordWrap(True)
        self.p_eta.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.cancel_btn.setText("Close")
        self.cancel_btn.clicked.disconnect()
        self.cancel_btn.clicked.connect(self.reject)

    def _cancelled(self):
        self.reject()

    def cancel(self):
        if self.thread is not None and self.thread.isRunning():
            self.renderer.cancel()
            self.thread.wait(5000)
        self.reject()

    def closeEvent(self, ev):
        if self.thread is not None and self.thread.isRunning():
            self.renderer.cancel()
            self.thread.wait(5000)
        super().closeEvent(ev)
