"""Export window: one-click presets for beginners, every setting for pros, a live size estimate and a queue.

Left: preset cards (Video / Audio / My presets). Right: where to save, a summary of what you'll get, and a
"Customise" panel with the full settings (format, size, frame rate, quality / bitrate / target size, encoder,
audio codec settings, loudness, render range). Exports can be queued and rendered one after another.
"""
import os
import subprocess
import sys

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QUrl
from PyQt6.QtGui import QDesktopServices, QColor, QPainter
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox, QButtonGroup,
                             QLineEdit, QFileDialog, QStackedWidget, QWidget, QFrame, QMessageBox, QScrollArea,
                             QSpinBox, QDoubleSpinBox, QTabWidget, QListWidget, QListWidgetItem, QInputDialog,
                             QSizePolicy)

from .. import exportfmt, formats, media, render, settings, icons, theme
from .widgets import RenderProgressBar, section, Toggle, SliderRow, fmt_time


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


class PresetCard(QPushButton):
    """A preset in the left column: icon, name and a one-line description."""

    def __init__(self, key, name, sub, icon_name):
        super().__init__()
        self.key, self.name, self.sub, self.icon_name = key, name, sub, icon_name
        self.setCheckable(True)
        self.setObjectName("Tile")
        self.setFixedHeight(52)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def paintEvent(self, ev):
        super().paintEvent(ev)
        c = theme.C
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        on = self.isChecked()
        p.drawPixmap(12, 15, icons.pixmap(self.icon_name, 22, c["accent"]))
        f = p.font()
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(c["text_strong"]))
        p.drawText(46, 8, self.width() - 52, 18, Qt.AlignmentFlag.AlignVCenter, self.name)
        f.setBold(False)
        if f.pointSizeF() > 0:
            f.setPointSizeF(f.pointSizeF() * 0.88)
        p.setFont(f)
        p.setPen(QColor(c["text"] if on else c["text_dim"]))
        p.drawText(46, 27, self.width() - 52, 16, Qt.AlignmentFlag.AlignVCenter,
                   p.fontMetrics().elidedText(self.sub, Qt.TextElideMode.ElideRight, self.width() - 52))
        p.end()


def _combo(items, current=None):
    cb = QComboBox()
    for data, label in items:
        cb.addItem(label, data)
    if current is not None:
        cb.setCurrentIndex(max(0, cb.findData(current)))
    return cb


def _row(label, widget, tip=""):
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    lb = QLabel(label)
    lb.setMinimumWidth(118)
    if tip:
        lb.setToolTip(tip)
        widget.setToolTip(tip)
    h.addWidget(lb)
    h.addWidget(widget, 1)
    return w


class RenderDialog(QDialog):
    aspectChanged = pyqtSignal(str)          # kept for older code (no longer changes the project)

    def __init__(self, project, parent=None, selection=None):
        super().__init__(parent)
        self.project = project
        self.selection = selection          # (start, end) of selected clips, or None
        self.setWindowTitle("Export")
        self.resize(1040, 720)
        self.setMinimumSize(900, 620)
        self.thread = None
        self.out_path = ""
        self.queue = []                     # [(name, settings, path, project snapshot)]
        self.results = []
        self._mute = False
        self.rate_mode = "quality"
        self.duration = project.duration()
        has_visual = any(c.is_visual for c in project.clips)
        last = settings.get("last_export") or {}
        start_key = last.get("preset") or ("yt1080" if has_visual else "mp3")
        if not has_visual and exportfmt.kind(last.get("settings", {}).get("fmt", "mp4_h264")) != "audio":
            start_key = "mp3"
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget()
        lay.addWidget(self.stack)
        self.stack.addWidget(self._settings_page())
        self.stack.addWidget(self._progress_page())
        if start_key.startswith("user:") and start_key[5:] in exportfmt.user_presets():
            self.choose_preset(start_key)
        elif exportfmt.preset(start_key):
            self.choose_preset(start_key)
        else:
            self.choose_preset("yt1080" if has_visual else "mp3")

    # ================================================================== settings page
    def _settings_page(self):
        page = QWidget()
        root = QHBoxLayout(page)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        # ---------------- left: presets
        left = QFrame()
        left.setObjectName("SideRail")
        left.setFixedWidth(272)
        lv = QVBoxLayout(left)
        lv.setContentsMargins(14, 16, 14, 14)
        t = QLabel("Export")
        t.setObjectName("H1")
        lv.addWidget(t)
        sub = QLabel(f"{self.project.name or 'Untitled'}  ·  {fmt_time(self.duration).split('.')[0]}")
        sub.setObjectName("Dim")
        lv.addWidget(sub)
        lv.addSpacing(6)
        holder = QWidget()
        self.preset_lay = QVBoxLayout(holder)
        self.preset_lay.setContentsMargins(0, 0, 4, 0)
        self.preset_lay.setSpacing(6)
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setFrameShape(QFrame.Shape.NoFrame)
        sa.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        sa.setWidget(holder)
        lv.addWidget(sa, 1)
        self.preset_group = QButtonGroup(self)
        self.cards = {}
        self._fill_presets()
        root.addWidget(left)
        # ---------------- right: details
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(22, 18, 22, 16)
        rv.setSpacing(10)
        # summary card
        card = QFrame()
        card.setObjectName("Hero")
        cv = QVBoxLayout(card)
        cv.setContentsMargins(18, 14, 18, 14)
        top = QHBoxLayout()
        self.sum_title = QLabel("")
        self.sum_title.setObjectName("H1")
        top.addWidget(self.sum_title, 1)
        self.sum_size = QLabel("")
        self.sum_size.setObjectName("H2")
        self.sum_size.setToolTip("Estimated file size")
        top.addWidget(self.sum_size)
        cv.addLayout(top)
        self.sum_line = QLabel("")
        cv.addWidget(self.sum_line)
        self.sum_desc = QLabel("")
        self.sum_desc.setObjectName("Dim")
        self.sum_desc.setWordWrap(True)
        cv.addWidget(self.sum_desc)
        self.sum_warn = QLabel("")
        self.sum_warn.setWordWrap(True)
        self.sum_warn.setStyleSheet(f"color: {theme.C['accent']};")
        cv.addWidget(self.sum_warn)
        rv.addWidget(card)
        # save to
        row = QHBoxLayout()
        row.addWidget(QLabel("Save to"))
        self.path = QLineEdit()
        row.addWidget(self.path, 1)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        row.addWidget(browse)
        rv.addLayout(row)
        base = settings.get("last_export_dir") or os.path.join(os.path.expanduser("~"), "Videos")
        if not os.path.isdir(base):
            base = os.path.expanduser("~")
        self.base_name = exportfmt.sanitize(self.project.name or "Easy-Cut video")
        self.path.setText(os.path.join(base, self.base_name + ".mp4"))
        # customise
        self.custom_btn = QPushButton("  Customise settings")
        self.custom_btn.setCheckable(True)
        icons.bind(self.custom_btn, "settings", 16)
        self.custom_btn.toggled.connect(lambda v: self.tabs.setVisible(v))
        rv.addWidget(self.custom_btn, 0, Qt.AlignmentFlag.AlignLeft)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.addTab(self._video_tab(), "Video")
        self.tabs.addTab(self._audio_tab(), "Audio")
        self.tabs.addTab(self._range_tab(), "Range && render")
        self.tabs.setVisible(False)
        rv.addWidget(self.tabs, 1)
        rv.addStretch(0)
        # queue
        self.queue_box = QFrame()
        self.queue_box.setObjectName("Card")
        qv = QVBoxLayout(self.queue_box)
        qv.setContentsMargins(12, 8, 12, 8)
        qh = QHBoxLayout()
        self.queue_title = QLabel("Queue")
        self.queue_title.setObjectName("H2")
        qh.addWidget(self.queue_title, 1)
        clear = QPushButton("Clear")
        clear.clicked.connect(self._clear_queue)
        qh.addWidget(clear)
        qv.addLayout(qh)
        self.queue_list = QListWidget()
        self.queue_list.setMaximumHeight(96)
        qv.addWidget(self.queue_list)
        self.queue_box.setVisible(False)
        rv.addWidget(self.queue_box)
        # buttons
        row = QHBoxLayout()
        save = QPushButton("Save as preset…")
        save.clicked.connect(self._save_preset)
        row.addWidget(save)
        self.del_preset = QPushButton("Delete preset")
        self.del_preset.clicked.connect(self._delete_preset)
        row.addWidget(self.del_preset)
        row.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        self.queue_btn = QPushButton("Add to queue")
        self.queue_btn.clicked.connect(self.add_to_queue)
        row.addWidget(self.queue_btn)
        self.go = QPushButton("  Export")
        self.go.setObjectName("Primary")
        icons.bind(self.go, "export", 16, "accent_text")
        self.go.clicked.connect(self.start)
        row.addWidget(self.go)
        rv.addLayout(row)
        root.addWidget(right, 1)
        return page

    def _fill_presets(self):
        while self.preset_lay.count():
            it = self.preset_lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        for b in list(self.preset_group.buttons()):
            self.preset_group.removeButton(b)
        self.cards = {}
        groups = [("Video", [p for p in exportfmt.PRESETS if p[1] == "Video"]),
                  ("Audio only", [p for p in exportfmt.PRESETS if p[1] == "Audio"])]
        for title, items in groups:
            self.preset_lay.addWidget(section(title))
            for pid, _, name, sub, icon, _s in items:
                self._card(pid, name, sub, icon)
        user = exportfmt.user_presets()
        if user:
            self.preset_lay.addWidget(section("My presets"))
            for name, s in user.items():
                self._card("user:" + name, name, exportfmt.describe(exportfmt.settings_for(**s)), "save")
        self.preset_lay.addStretch(1)

    def _card(self, key, name, sub, icon):
        c = PresetCard(key, name, sub, icon)
        c.clicked.connect(lambda _=False, k=key: self.choose_preset(k))
        self.preset_group.addButton(c)
        self.preset_lay.addWidget(c)
        self.cards[key] = c

    # ------------------------------------------------------------------ tabs
    def _video_tab(self):
        w = QWidget()
        g = QVBoxLayout(w)
        g.setContentsMargins(4, 10, 4, 4)
        g.setSpacing(6)
        items = [(k, exportfmt.FORMATS[k]["name"]) for k in exportfmt.VIDEO_ORDER] + \
                [(k, "Audio only · " + exportfmt.FORMATS[k]["name"]) for k in exportfmt.AUDIO_ORDER]
        self.fmt = _combo(items)
        g.addWidget(_row("Format", self.fmt))
        self.aspect = _combo([(k, formats.aspect_label(k)) for k in formats.ASPECT_ORDER])
        self.aspect_row = _row("Shape", self.aspect, "The frame shape. Your clips are fitted into it.")
        g.addWidget(self.aspect_row)
        rh = QWidget()
        rl = QHBoxLayout(rh)
        rl.setContentsMargins(0, 0, 0, 0)
        self.res = _combo([("480p", "480p (SD)"), ("720p", "720p (HD)"), ("1080p", "1080p (Full HD)"),
                           ("1440p", "1440p (2K)"), ("2160p", "2160p (4K)"), ("custom", "Custom size…")])
        rl.addWidget(self.res, 1)
        self.cw = QSpinBox()
        self.cw.setRange(16, 7680)
        self.cw.setSingleStep(2)
        self.ch = QSpinBox()
        self.ch.setRange(16, 4320)
        self.ch.setSingleStep(2)
        for sp in (self.cw, self.ch):
            sp.setFixedWidth(76)
        rl.addWidget(self.cw)
        self.times = QLabel("×")
        rl.addWidget(self.times)
        rl.addWidget(self.ch)
        self.res_row = _row("Resolution", rh)
        g.addWidget(self.res_row)
        self.fps = _combo([(f, f"{f} fps" + {10: "  (GIFs)", 24: "  (film)", 25: "  (PAL)", 30: "  (standard)",
                                               60: "  (smooth)"}.get(f, "")) for f in exportfmt.FPS_CHOICES])
        self.fps_row = _row("Frame rate", self.fps)
        g.addWidget(self.fps_row)
        mh = QWidget()
        ml = QHBoxLayout(mh)
        ml.setContentsMargins(0, 0, 0, 0)
        self.mode_group = QButtonGroup(self)
        self.mode_buttons = {}
        for key, label in (("quality", "Constant quality"), ("bitrate", "Bitrate"), ("size", "Target file size")):
            b = QPushButton(label)
            b.setCheckable(True)
            self.mode_group.addButton(b)
            self.mode_buttons[key] = b
            b.clicked.connect(lambda _=False, k=key: self._set_mode(k))
            ml.addWidget(b)
        ml.addStretch(1)
        self.mode_row = _row("Rate control", mh, "Quality keeps the look constant; bitrate keeps the data rate "
                                                 "constant; target size hits a file size exactly (2-pass).")
        g.addWidget(self.mode_row)
        self.quality = SliderRow("Quality", 0, 100, 80, step=1, decimals=0, default=80)
        self.quality.label.setMinimumWidth(118)
        self.q_hint = QLabel("")
        self.q_hint.setObjectName("Dim")
        g.addWidget(self.quality)
        g.addWidget(self.q_hint)
        self.kbps = QDoubleSpinBox()
        self.kbps.setRange(0.2, 200)
        self.kbps.setDecimals(1)
        self.kbps.setSuffix(" Mbps")
        self.kbps_row = _row("Video bitrate", self.kbps)
        g.addWidget(self.kbps_row)
        self.target = QDoubleSpinBox()
        self.target.setRange(0.5, 50000)
        self.target.setDecimals(1)
        self.target.setSuffix(" MB")
        self.target_row = _row("Target size", self.target)
        g.addWidget(self.target_row)
        self.speed = _combo([(k, exportfmt.SPEED_LABELS[k]) for k in exportfmt.SPEEDS])
        self.speed_row = _row("Encoding speed", self.speed, "Slower settings make smaller files at the same quality.")
        g.addWidget(self.speed_row)
        enc_items = [("auto", "Automatic (graphics card when available)"), ("cpu", "CPU (best compression)")]
        try:
            enc_items += [(e, n) for e, n in media.hardware_encoders()]
        except Exception:
            pass
        self.encoder = _combo(enc_items)
        self.encoder_row = _row("Encoder", self.encoder)
        g.addWidget(self.encoder_row)
        self.ten_bit = Toggle("10-bit colour (HDR-ready, smoother gradients)")
        g.addWidget(self.ten_bit)
        g.addStretch(1)
        for wdg in (self.fmt, self.aspect, self.res, self.fps, self.speed, self.encoder):
            wdg.currentIndexChanged.connect(self._changed)
        for wdg in (self.cw, self.ch, self.kbps, self.target):
            wdg.valueChanged.connect(self._changed)
        self.quality.valueChanged.connect(self._changed)
        self.ten_bit.toggled.connect(self._changed)
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setFrameShape(QFrame.Shape.NoFrame)
        sa.setWidget(w)
        return sa

    def _audio_tab(self):
        w = QWidget()
        g = QVBoxLayout(w)
        g.setContentsMargins(4, 10, 4, 4)
        g.setSpacing(6)
        self.include_audio = Toggle("Include sound")
        self.include_audio.setChecked(True)
        g.addWidget(self.include_audio)
        self.acodec_label = QLabel("")
        self.acodec_label.setObjectName("Dim")
        g.addWidget(self.acodec_label)
        self.abitrate = _combo([(k, f"{k} kbps") for k in (64, 96, 128, 160, 192, 256, 320)])
        self.abitrate_row = _row("Bitrate", self.abitrate)
        g.addWidget(self.abitrate_row)
        self.depth = _combo([(16, "16-bit (CD)"), (24, "24-bit (studio)")])
        self.depth_row = _row("Bit depth", self.depth)
        g.addWidget(self.depth_row)
        self.rate = _combo([(44100, "44.1 kHz (music / CD)"), (48000, "48 kHz (video)"), (96000, "96 kHz (hi-res)")])
        g.addWidget(_row("Sample rate", self.rate))
        self.channels = _combo([(2, "Stereo"), (1, "Mono")])
        g.addWidget(_row("Channels", self.channels))
        self.loud = _combo([(k, exportfmt.LOUDNESS_LABELS[k]) for k in exportfmt.LOUDNESS])
        g.addWidget(_row("Loudness", self.loud, "Matches the volume level platforms expect, so your export "
                                                 "isn't turned down or sounds quiet."))
        g.addStretch(1)
        for wdg in (self.abitrate, self.depth, self.rate, self.channels, self.loud):
            wdg.currentIndexChanged.connect(self._changed)
        self.include_audio.toggled.connect(self._changed)
        return w

    def _range_tab(self):
        w = QWidget()
        g = QVBoxLayout(w)
        g.setContentsMargins(4, 10, 4, 4)
        g.setSpacing(6)
        items = [("all", "Whole timeline")]
        if self.selection:
            items.append(("selection", f"Selected clips  ({fmt_time(self.selection[0]).split('.')[0]} - "
                                       f"{fmt_time(self.selection[1]).split('.')[0]})"))
        items.append(("custom", "Custom range…"))
        self.range = _combo(items)
        g.addWidget(_row("Export", self.range))
        rh = QWidget()
        rl = QHBoxLayout(rh)
        rl.setContentsMargins(0, 0, 0, 0)
        self.r_start = QDoubleSpinBox()
        self.r_end = QDoubleSpinBox()
        for sp in (self.r_start, self.r_end):
            sp.setRange(0, max(0.1, self.duration))
            sp.setDecimals(2)
            sp.setSuffix(" s")
        self.r_end.setValue(self.duration)
        rl.addWidget(QLabel("From"))
        rl.addWidget(self.r_start)
        rl.addWidget(QLabel("to"))
        rl.addWidget(self.r_end)
        rl.addStretch(1)
        self.range_row = _row("", rh)
        g.addWidget(self.range_row)
        self.low_impact = Toggle("Keep my PC responsive while exporting")
        self.low_impact.setChecked(True)
        g.addWidget(self.low_impact)
        g.addStretch(1)
        self.range.currentIndexChanged.connect(self._changed)
        self.r_start.valueChanged.connect(self._changed)
        self.r_end.valueChanged.connect(self._changed)
        return w

    # ------------------------------------------------------------------ settings <-> widgets
    def choose_preset(self, key):
        self.current_preset = key
        if key.startswith("user:"):
            s = exportfmt.settings_for(**exportfmt.user_presets().get(key[5:], {}))
        else:
            s = exportfmt.preset_settings(key, self.project.fps, self.project.aspect)
        b = self.cards.get(key)
        if b:
            b.setChecked(True)
        self.del_preset.setVisible(key.startswith("user:"))
        self.load(s)

    def load(self, s):
        self._mute = True
        try:
            self.fmt.setCurrentIndex(max(0, self.fmt.findData(s["fmt"])))
            self.aspect.setCurrentIndex(max(0, self.aspect.findData(s.get("aspect", self.project.aspect))))
            self.res.setCurrentIndex(max(0, self.res.findData(s.get("resolution", "1080p"))))
            w, h = exportfmt.frame_size(s)
            self.cw.setValue(w)
            self.ch.setValue(h)
            self.fps.setCurrentIndex(max(0, self.fps.findData(int(s.get("fps", 30)))))
            self.quality.setValue(float(s.get("quality", 80)))
            self.kbps.setValue(float(s.get("video_kbps", 8000)) / 1000)
            self.target.setValue(float(s.get("target_mb", 50)))
            self.speed.setCurrentIndex(max(0, self.speed.findData(s.get("speed", "balanced"))))
            enc = s.get("encoder", "auto")
            if not settings.get("hardware_encoding", True) and enc == "auto":
                enc = "cpu"
            self.encoder.setCurrentIndex(max(0, self.encoder.findData(enc)))
            self.ten_bit.setChecked(bool(s.get("ten_bit")))
            self.include_audio.setChecked(bool(s.get("include_audio", True)))
            self.abitrate.setCurrentIndex(max(0, self.abitrate.findData(int(s.get("audio_kbps", 192)))))
            self.depth.setCurrentIndex(max(0, self.depth.findData(int(s.get("bit_depth", 16)))))
            self.rate.setCurrentIndex(max(0, self.rate.findData(int(s.get("sample_rate", 48000)))))
            self.channels.setCurrentIndex(max(0, self.channels.findData(int(s.get("channels", 2)))))
            self.loud.setCurrentIndex(max(0, self.loud.findData(s.get("loudness", "off"))))
            self._set_mode(s.get("rate_mode", "quality"), refresh=False)
        finally:
            self._mute = False
        self._changed()

    def collect(self):
        s = exportfmt.settings_for(
            fmt=self.fmt.currentData(), aspect=self.aspect.currentData(), resolution=self.res.currentData(),
            width=self.cw.value(), height=self.ch.value(), fps=self.fps.currentData(),
            rate_mode=self.rate_mode, quality=self.quality.value(), video_kbps=int(self.kbps.value() * 1000),
            target_mb=self.target.value(), speed=self.speed.currentData(), encoder=self.encoder.currentData(),
            ten_bit=self.ten_bit.isChecked(), include_audio=self.include_audio.isChecked(),
            audio_kbps=self.abitrate.currentData(), bit_depth=self.depth.currentData(),
            sample_rate=self.rate.currentData(), channels=self.channels.currentData(),
            loudness=self.loud.currentData(), range=self.range.currentData())
        if s["range"] == "selection" and self.selection:
            s["range_start"], s["range_end"] = self.selection
        elif s["range"] == "custom":
            s["range_start"], s["range_end"] = self.r_start.value(), self.r_end.value()
        return s

    def _set_mode(self, key, refresh=True):
        self.rate_mode = key
        self.mode_buttons[key].setChecked(True)
        if refresh:
            self._changed()

    def export_duration(self, s):
        if s.get("range") in ("selection", "custom"):
            return max(0.05, float(s.get("range_end", 0)) - float(s.get("range_start", 0)))
        return self.duration

    def _changed(self, *_):
        if self._mute:
            return
        s = self.collect()
        f = exportfmt.fmt(s["fmt"])
        kind = f["kind"]
        is_av = kind != "audio"
        rc = exportfmt.supports_rate_control(s["fmt"])
        # show only what applies
        for wdg in (self.aspect_row, self.res_row, self.fps_row):
            wdg.setVisible(is_av)
        custom = s["resolution"] == "custom"
        self.cw.setVisible(custom)
        self.ch.setVisible(custom)
        self.times.setVisible(custom)
        self.mode_row.setVisible(rc)
        self.quality.setVisible(f.get("codec") in ("h264", "hevc", "vp9", "av1", "webp") and
                                (self.rate_mode == "quality" or not rc))
        self.q_hint.setVisible(self.quality.isVisible())
        self.q_hint.setText(f"{exportfmt.quality_label(s['quality'])}" +
                            (f"  ·  CRF {exportfmt.crf_for(f['codec'], s['quality'])}"
                             if f.get("codec") in ("h264", "hevc", "vp9", "av1") else ""))
        self.kbps_row.setVisible(rc and self.rate_mode == "bitrate")
        self.target_row.setVisible(rc and self.rate_mode == "size")
        self.speed_row.setVisible(rc)
        self.encoder_row.setVisible(exportfmt.supports_hw(s["fmt"]))
        self.ten_bit.setVisible(f.get("codec") in ("hevc", "vp9", "av1"))
        ac = f.get("acodec")
        self.include_audio.setVisible(is_av and bool(ac))
        lossless = ac in exportfmt.LOSSLESS_AUDIO or ac == "pcm24"
        self.abitrate_row.setVisible(bool(ac) and not lossless)
        self.depth_row.setVisible(ac in ("pcm", "pcm_be", "flac", "alac"))
        names = {"aac": "AAC", "mp3": "MP3", "opus": "Opus", "vorbis": "Vorbis", "flac": "FLAC (lossless)",
                 "alac": "Apple Lossless", "pcm": "PCM (uncompressed)", "pcm_be": "PCM (uncompressed)",
                 "pcm24": "PCM 24-bit (uncompressed)"}
        self.acodec_label.setText(f"Audio codec: {names.get(ac, '-')}" if ac else "This format has no sound.")
        self.range_row.setVisible(s["range"] == "custom")
        # summary
        dur = self.export_duration(s)
        self.sum_title.setText(f["name"])
        self.sum_line.setText(exportfmt.describe(s))
        self.sum_desc.setText(f["desc"])
        est = exportfmt.estimate_bytes(s, dur)
        self.sum_size.setText(("" if self.rate_mode == "size" and rc else "≈ ") + exportfmt.size_label(est))
        warn = []
        if is_av and s["aspect"] != self.project.aspect:
            warn.append(f"Your project is {formats.ASPECTS[self.project.aspect][0]}; this export is "
                        f"{formats.ASPECTS[s['aspect']][0]} - clips are fitted into the new shape.")
        if f.get("codec") == "gif" and dur > 20:
            warn.append("GIFs this long get very large - consider WebP or MP4.")
        if kind == "audio" and not any(c.has_sound for c in self.project.clips):
            warn.append("There's no sound on the timeline yet.")
        self.sum_warn.setText("\n".join(warn))
        self.sum_warn.setVisible(bool(warn))
        # file extension follows the format
        root, _ = os.path.splitext(self.path.text())
        self.path.setText(root + f["ext"])
        self.go.setText("  Export" if not self.queue else f"  Export {len(self.queue) + 1} files")

    # ------------------------------------------------------------------ presets
    def _save_preset(self):
        name, ok = QInputDialog.getText(self, "Save preset", "Name this preset:")
        if not ok or not name.strip():
            return
        exportfmt.save_user_preset(name.strip(), self.collect())
        self._fill_presets()
        self.choose_preset("user:" + name.strip())

    def _delete_preset(self):
        key = getattr(self, "current_preset", "")
        if key.startswith("user:"):
            exportfmt.delete_user_preset(key[5:])
            self._fill_presets()
            self.choose_preset("yt1080")

    def _browse(self):
        s = self.collect()
        f = exportfmt.fmt(s["fmt"])
        p, _ = QFileDialog.getSaveFileName(self, "Export", self.path.text(), f"{f['name']} (*{f['ext']})")
        if p:
            if not p.lower().endswith(f["ext"]):
                p += f["ext"]
            self.path.setText(p)

    # ------------------------------------------------------------------ queue
    def _job_name(self, s):
        return f"{os.path.basename(self.path.text())}  ·  {exportfmt.describe(s)}"

    def _validate_path(self):
        path = self.path.text().strip()
        if not path:
            return None
        folder = os.path.dirname(path) or "."
        if not os.path.isdir(folder):
            try:
                os.makedirs(folder, exist_ok=True)
            except OSError:
                QMessageBox.warning(self, "Export", "That folder can't be created.")
                return None
        if os.path.exists(path) and not any(j[2] == path for j in self.queue):
            r = QMessageBox.question(self, "Export", f"{os.path.basename(path)} already exists. Replace it?")
            if r != QMessageBox.StandardButton.Yes:
                return None
        return path

    def add_to_queue(self):
        path = self._validate_path()
        if not path:
            return
        if any(j[2] == path for j in self.queue):
            QMessageBox.information(self, "Export", "That file is already in the queue - pick another name.")
            return
        from ..project import Project
        s = self.collect()
        self.queue.append((self._job_name(s), s, path, Project.from_dict(self.project.to_dict())))
        self.queue_list.addItem(QListWidgetItem(self._job_name(s)))
        self.queue_box.setVisible(True)
        self.queue_title.setText(f"Queue ({len(self.queue)})")
        root, ext = os.path.splitext(path)
        self.path.setText(root + " (2)" + ext if not root.endswith(")") else root + ext)
        self._changed()

    def _clear_queue(self):
        self.queue = []
        self.queue_list.clear()
        self.queue_box.setVisible(False)
        self._changed()

    # ================================================================== progress page
    def _progress_page(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(28, 26, 28, 22)
        lay.setSpacing(12)
        self.p_title = QLabel("Rendering your video")
        self.p_title.setObjectName("H1")
        lay.addWidget(self.p_title)
        self.p_file = QLabel("")
        self.p_file.setObjectName("Dim")
        self.p_file.setWordWrap(True)
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
        self.p_eta.setWordWrap(True)
        lay.addWidget(self.p_eta)
        self.p_done = QListWidget()
        self.p_done.setVisible(False)
        lay.addWidget(self.p_done, 1)
        lay.addStretch(1)
        row = QHBoxLayout()
        self.open_btn = QPushButton("Open")
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
        target = self.out_path
        if os.path.isdir(os.path.splitext(target)[0]):
            target = os.path.splitext(target)[0]
        if sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", os.path.normpath(target)])
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(target)))

    def start(self):
        if not self.queue or self.path.text().strip() not in [j[2] for j in self.queue]:
            path = self._validate_path()
            if not path:
                return
            from ..project import Project
            s = self.collect()
            self.queue.append((self._job_name(s), s, path, Project.from_dict(self.project.to_dict())))
        last = self.queue[-1]
        settings.set("last_export_dir", os.path.dirname(last[2]))
        settings.set("last_export", {"preset": getattr(self, "current_preset", "yt1080"), "settings": last[1]})
        settings.set("hardware_encoding", last[1].get("encoder") != "cpu")
        self.jobs = list(self.queue)
        self.job_index = -1
        self.stack.setCurrentIndex(1)
        self._next_job()

    def _next_job(self):
        self.job_index += 1
        if self.job_index >= len(self.jobs):
            self._all_done()
            return
        name, s, path, snapshot = self.jobs[self.job_index]
        opts = render.RenderOptions(out_path=path, settings=s, low_impact=self.low_impact.isChecked())
        self.out_path = path
        self.renderer = render.Renderer(snapshot, opts)
        self.thread = RenderThread(self.renderer)
        self.thread.progress.connect(self._progress)
        self.thread.finishedOk.connect(self._job_done)
        self.thread.failed.connect(self._failed)
        self.thread.cancelled.connect(self._cancelled)
        n = len(self.jobs)
        kind = exportfmt.kind(s["fmt"])
        self.p_title.setText(("Rendering your audio" if kind == "audio" else "Rendering your video") +
                             (f"  ({self.job_index + 1} of {n})" if n > 1 else ""))
        self.p_file.setText(f"{os.path.basename(path)}  ·  {exportfmt.describe(s)}")
        self.bar.setValue(0)
        self.p_eta.setText("")
        self.thread.start()

    def _progress(self, phase, frac, eta):
        self.p_phase.setText(phase)
        self.bar.setValue(frac)
        self.p_pct.setText(f"{int(frac * 100)}%")
        if eta is not None and eta > 0:
            m, sec = divmod(int(eta), 60)
            self.p_eta.setText(f"About {m}m {sec:02d}s left" if m else f"About {sec}s left")

    def _job_done(self, path):
        size = 0
        if os.path.isfile(path):
            size = os.path.getsize(path)
        elif os.path.isdir(os.path.splitext(path)[0]):
            folder = os.path.splitext(path)[0]
            size = sum(os.path.getsize(os.path.join(folder, f)) for f in os.listdir(folder))
        enc = getattr(self.renderer, "encoder", None)
        where = {"h264_nvenc": "NVIDIA GPU", "hevc_nvenc": "NVIDIA GPU", "h264_qsv": "Intel GPU",
                 "hevc_qsv": "Intel GPU", "h264_amf": "AMD GPU", "hevc_amf": "AMD GPU"}.get(enc, "")
        self.results.append((path, size, where))
        self._next_job()

    def _all_done(self):
        self.bar.setValue(1.0)
        self.p_pct.setText("100%")
        n = len(self.results)
        self.p_title.setText("Your export is ready 🎉" if n == 1 else f"All {n} exports are ready 🎉")
        self.p_phase.setText("Done")
        path, size, where = self.results[-1]
        self.p_eta.setText(f"{exportfmt.size_label(size)}" + (f"  ·  encoded on the {where}" if where else ""))
        if n > 1:
            self.p_done.setVisible(True)
            for p, sz, _ in self.results:
                self.p_done.addItem(f"✓  {os.path.basename(p)}  ·  {exportfmt.size_label(sz)}")
        self.cancel_btn.setText("Close")
        self.cancel_btn.clicked.disconnect()
        self.cancel_btn.clicked.connect(self.accept)
        self.open_btn.setVisible(os.path.isfile(self.out_path))
        self.folder_btn.show()

    def _failed(self, msg):
        self.bar.stop()
        self.p_title.setText("Export failed")
        self.p_phase.setText("Something went wrong")
        self.p_eta.setText(msg[-600:])
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

    # older code / tests
    def aspect_key(self):
        return self.aspect.currentData()
