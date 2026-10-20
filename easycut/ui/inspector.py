"""Right-hand inspector: every setting of the selected clip(s)."""
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTabWidget, QScrollArea, QPushButton,
                             QComboBox, QPlainTextEdit, QFontComboBox, QStackedWidget, QFrame)

from .. import effects, filters, textrender
from .widgets import SliderRow, ColorButton, section, Toggle, icon_button


def scroll(widget):
    sa = QScrollArea()
    sa.setWidgetResizable(True)
    sa.setFrameShape(QFrame.Shape.NoFrame)
    sa.setWidget(widget)
    sa.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    return sa


class Inspector(QWidget):
    changed = pyqtSignal(dict)          # live: field -> value (applied to selected clips)
    committed = pyqtSignal(str)         # an edit finished (add to undo history)
    speedChanged = pyqtSignal(float)
    pickColor = pyqtSignal()
    normalizeRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Panel")
        self.setMinimumWidth(300)
        self.clips = []
        self._loading = False
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        self.title = QLabel("Inspector")
        self.title.setObjectName("H2")
        outer.addWidget(self.title)
        self.stack = QStackedWidget()
        outer.addWidget(self.stack, 1)
        empty = QWidget()
        el = QVBoxLayout(empty)
        el.addStretch(1)
        hint = QLabel("Select a clip on the timeline\nto edit it here.")
        hint.setObjectName("Dim")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        el.addWidget(hint)
        el.addStretch(2)
        self.stack.addWidget(empty)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setUsesScrollButtons(True)
        self.stack.addWidget(self.tabs)
        self._build_basic()
        self._build_effects()
        self._build_adjust()
        self._build_speed()
        self._build_audio()
        self._build_text()
        self.commit_timer = QTimer(self, singleShot=True, interval=400)
        self.commit_timer.timeout.connect(lambda: self.committed.emit(self._pending_label))
        self._pending_label = "Edit"

    # ------------------------------------------------------------------ helpers
    def _emit(self, field, value, label=None, commit_now=False):
        if self._loading:
            return
        self.changed.emit({field: value})
        self._pending_label = label or "Edit clip"
        if commit_now:
            self.commit_timer.stop()
            self.committed.emit(self._pending_label)
        else:
            self.commit_timer.start()

    def _slider(self, lay, label, field, lo, hi, step, decimals=2, suffix="", factor=1.0, default=None):
        s = SliderRow(label, lo, hi, step=step, decimals=decimals, suffix=suffix,
                      default=default if default is not None else lo)
        s.valueChanged.connect(lambda v, f=field, k=factor: self._emit(f, v / k, label))
        s.factor = factor
        s.field = field
        lay.addWidget(s)
        self._sliders.append(s)
        return s

    def _page(self, name):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(4, 8, 8, 8)
        lay.setSpacing(6)
        self.tabs.addTab(scroll(w), name)
        return w, lay

    # ------------------------------------------------------------------ pages
    def _build_basic(self):
        self._sliders = []
        self.basic, lay = self._page("Basic")
        lay.addWidget(section("Frame"))
        row = QHBoxLayout()
        self.fit_btn = QPushButton("Fit")
        self.fill_btn = QPushButton("Fill")
        for b, v in ((self.fit_btn, "fit"), (self.fill_btn, "fill")):
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, v=v: (self._emit("fit", v, "Fit mode", True), self._sync_fit(v)))
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addWidget(section("Transform"))
        self.s_scale = self._slider(lay, "Scale", "scale", 5, 500, 1, 0, " %", factor=100, default=100)
        self.s_x = self._slider(lay, "Position X", "x", -150, 150, 0.5, 1, " %", factor=100, default=0)
        self.s_y = self._slider(lay, "Position Y", "y", -150, 150, 0.5, 1, " %", factor=100, default=0)
        self.s_rot = self._slider(lay, "Rotation", "rotation", -180, 180, 1, 0, "°", default=0)
        self.s_op = self._slider(lay, "Opacity", "opacity", 0, 100, 1, 0, " %", factor=100, default=100)
        reset = QPushButton("Reset transform")
        reset.clicked.connect(self._reset_transform)
        lay.addWidget(reset, 0, Qt.AlignmentFlag.AlignLeft)
        lay.addWidget(QLabel("Tip: drag the clip in the preview to move it,\nor drag a corner to resize it."))
        lay.itemAt(lay.count() - 1).widget().setObjectName("Dim")
        lay.addStretch(1)

    def _sync_fit(self, v):
        self.fit_btn.setChecked(v == "fit")
        self.fill_btn.setChecked(v == "fill")

    def _reset_transform(self):
        for f, v in (("scale", 1.0), ("x", 0.0), ("y", 0.0), ("rotation", 0.0), ("opacity", 1.0)):
            self.changed.emit({f: v})
        self.committed.emit("Reset transform")
        self.load(self.clips)

    def _build_effects(self):
        w, lay = self._page("Effects")
        self.effects_page = w
        # chroma key
        lay.addWidget(section("Chroma key (green screen)"))
        self.chroma_on = Toggle("Remove a background colour")
        self.chroma_on.toggled.connect(lambda v: self._emit("chroma", v, "Chroma key", True))
        lay.addWidget(self.chroma_on)
        row = QHBoxLayout()
        row.addWidget(QLabel("Key colour"))
        self.chroma_col = ColorButton("#00ff00", title="Key colour")
        self.chroma_col.colorChanged.connect(lambda c: self._emit("chroma_color", c, "Key colour", True))
        row.addWidget(self.chroma_col)
        self.pick_btn = icon_button("chroma", "Pick the colour from the preview", 18, flat=False)
        self.pick_btn.clicked.connect(self.pickColor)
        row.addWidget(self.pick_btn)
        for name, col in (("Green", "#00ff00"), ("Blue", "#0047bb")):
            b = QPushButton(name)
            b.clicked.connect(lambda _=False, c=col: (self.chroma_col.setColor(c),
                                                      self._emit("chroma_color", c, "Key colour", True)))
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        self.s_sim = self._slider(lay, "Strength", "chroma_similarity", 1, 60, 0.5, 1, " %", factor=100, default=15)
        self.s_blend = self._slider(lay, "Smoothness", "chroma_blend", 0, 50, 0.5, 1, " %", factor=100, default=8)
        # crop
        lay.addWidget(section("Crop"))
        self.crop_sliders = []
        for i, name in enumerate(("Left", "Top", "Right", "Bottom")):
            s = SliderRow(name, 0, 45, step=0.5, decimals=1, suffix=" %", default=0)
            s.valueChanged.connect(lambda v, i=i: self._crop_changed(i, v))
            lay.addWidget(s)
            self.crop_sliders.append(s)
        # flip & mirror
        lay.addWidget(section("Flip & mirror"))
        row = QHBoxLayout()
        self.flip_h = QPushButton("Flip horizontal")
        self.flip_v = QPushButton("Flip vertical")
        for b, f in ((self.flip_h, "flip_h"), (self.flip_v, "flip_v")):
            b.setCheckable(True)
            b.toggled.connect(lambda v, f=f: self._emit(f, v, "Flip", True))
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel("Mirror"))
        self.mirror = QComboBox()
        for k, label in effects.MIRROR_MODES:
            self.mirror.addItem(label, k)
        self.mirror.currentIndexChanged.connect(
            lambda _i: self._emit("mirror", self.mirror.currentData(), "Mirror", True))
        row.addWidget(self.mirror, 1)
        lay.addLayout(row)
        # stabilize
        lay.addWidget(section("Image stabilization"))
        self.stab_on = Toggle("Smooth out camera shake")
        self.stab_on.toggled.connect(lambda v: self._emit("stabilize", v, "Stabilization", True))
        lay.addWidget(self.stab_on)
        self.s_stab = self._slider(lay, "Strength", "stabilize_strength", 0, 100, 1, 0, " %", factor=100, default=50)
        note = QLabel("Stabilization is worked out when you export,\nso the preview shows the original footage.")
        note.setObjectName("Dim")
        lay.addWidget(note)
        # extension effects
        self.ext_box = QWidget()
        self.ext_lay = QVBoxLayout(self.ext_box)
        self.ext_lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.ext_box)
        lay.addStretch(1)

    def rebuild_extension_effects(self):
        while self.ext_lay.count():
            it = self.ext_lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        self.ext_checks = {}
        self.ext_amounts = {}
        if not filters.EFFECTS:
            hint = QLabel("Add effects like VHS, Glow or Pixelate from the Effects tab on the left.")
            hint.setObjectName("Dim")
            hint.setWordWrap(True)
            self.ext_lay.addWidget(section("Pack effects"))
            self.ext_lay.addWidget(hint)
            return
        self.ext_lay.addWidget(section("Pack effects"))
        for eid in filters.EFFECT_ORDER:
            e = filters.EFFECTS[eid]
            cb = Toggle(e.name)
            cb.toggled.connect(lambda v, eid=eid: self._fx_toggled(eid, v))
            self.ext_lay.addWidget(cb)
            amt = SliderRow("Amount", 0, 100, 100, step=1, decimals=0, suffix=" %", default=100)
            amt.valueChanged.connect(lambda v, eid=eid: self._fx_amount(eid, v / 100))
            amt.setVisible(False)
            self.ext_lay.addWidget(amt)
            self.ext_checks[eid] = cb
            self.ext_amounts[eid] = amt

    def _fx_toggled(self, eid, on):
        if eid in getattr(self, "ext_amounts", {}):
            self.ext_amounts[eid].setVisible(on)
        if self._loading or not self.clips:
            return
        fx = [dict(f) for f in self.clips[0].get("fx", []) if f.get("id") != eid]
        if on:
            fx.append({"id": eid, "amount": self.ext_amounts[eid].value() / 100 if eid in self.ext_amounts else 1.0})
        self._emit("fx", fx, "Effect", True)

    def _fx_amount(self, eid, v):
        if self._loading or not self.clips:
            return
        fx = [dict(f) for f in self.clips[0].get("fx", [])]
        for f in fx:
            if f.get("id") == eid:
                f["amount"] = v
        self._emit("fx", fx, "Effect amount")

    def rebuild_styles(self):
        self._loading = True
        cur = self.style_box.currentData()
        self.style_box.clear()
        for sid in textrender.STYLE_ORDER:
            self.style_box.addItem(textrender.STYLES[sid].name, sid)
        idx = self.style_box.findData(cur)
        self.style_box.setCurrentIndex(max(0, idx))
        self._loading = False

    def _crop_changed(self, i, v):
        if self._loading or not self.clips:
            return
        crop = list(self.clips[0].get("crop", [0, 0, 0, 0]))
        crop[i] = v / 100.0
        self._emit("crop", crop, "Crop")

    def _build_adjust(self):
        w, lay = self._page("Adjust")
        lay.addWidget(section("Colour"))
        self.s_bri = self._slider(lay, "Brightness", "brightness", -100, 100, 1, 0, factor=100, default=0)
        self.s_con = self._slider(lay, "Contrast", "contrast", 0, 200, 1, 0, " %", factor=100, default=100)
        self.s_sat = self._slider(lay, "Saturation", "saturation", 0, 200, 1, 0, " %", factor=100, default=100)
        lay.addWidget(section("Filter"))
        self.filter_label = QLabel("None")
        lay.addWidget(self.filter_label)
        self.s_famt = self._slider(lay, "Intensity", "filter_amount", 0, 100, 1, 0, " %", factor=100, default=100)
        hint = QLabel("Pick filters from the Filters tab on the left.")
        hint.setObjectName("Dim")
        lay.addWidget(hint)
        lay.addStretch(1)

    def _build_speed(self):
        w, lay = self._page("Speed")
        self.speed_page = w
        lay.addWidget(section("Speed"))
        self.s_speed = SliderRow("Speed", 0.1, 10, step=0.05, decimals=2, suffix=" x", default=1)
        self.s_speed.valueChanged.connect(self._speed_live)
        self.s_speed.editingFinished.connect(lambda: self.committed.emit("Speed"))
        lay.addWidget(self.s_speed)
        from PyQt6.QtWidgets import QGridLayout
        row = QGridLayout()
        row.setSpacing(6)
        for i, v in enumerate((0.25, 0.5, 1.0, 1.5, 2.0, 4.0)):
            b = QPushButton(f"{v:g}×")
            b.setMinimumWidth(40)
            b.clicked.connect(lambda _=False, v=v: (self.s_speed.setValue(v), self._speed_live(v),
                                                    self.committed.emit("Speed")))
            row.addWidget(b, i // 3, i % 3)
        lay.addLayout(row)
        lay.addWidget(section("Pitch"))
        self.keep_pitch = Toggle("Keep the original pitch")
        self.keep_pitch.toggled.connect(lambda v: self._emit("keep_pitch", v, "Keep pitch", True))
        lay.addWidget(self.keep_pitch)
        self.s_pitch = self._slider(lay, "Pitch", "pitch", -12, 12, 0.5, 1, " st", default=0)
        hint = QLabel("Pitch is in semitones: +12 is one octave up.")
        hint.setObjectName("Dim")
        lay.addWidget(hint)
        lay.addStretch(1)

    def _speed_live(self, v):
        if not self._loading:
            self.speedChanged.emit(v)

    def _build_audio(self):
        w, lay = self._page("Audio")
        self.audio_page = w
        self.no_audio = QLabel("This clip has no sound.")
        self.no_audio.setObjectName("Dim")
        lay.addWidget(self.no_audio)
        self.audio_box = QWidget()
        al = QVBoxLayout(self.audio_box)
        al.setContentsMargins(0, 0, 0, 0)
        al.setSpacing(6)
        al.addWidget(section("Level"))
        self.s_vol = self._slider(al, "Volume", "volume", 0, 200, 1, 0, " %", factor=100, default=100)
        self.s_pan = self._slider(al, "Pan  L ↔ R", "pan", -100, 100, 1, 0, factor=100, default=0)
        row = QHBoxLayout()
        self.mute = Toggle("Mute this clip")
        self.mute.toggled.connect(lambda v: self._emit("muted", v, "Mute", True))
        row.addWidget(self.mute, 1)
        self.norm_btn = QPushButton("Normalize")
        self.norm_btn.setToolTip("Set the volume so the loudest moment peaks just below 0 dB")
        self.norm_btn.clicked.connect(self.normalizeRequested)
        row.addWidget(self.norm_btn)
        al.addLayout(row)
        al.addWidget(section("Fades"))
        self.s_afi = self._slider(al, "Fade in", "afade_in", 0, 10, 0.05, 2, " s", default=0)
        self.s_afo = self._slider(al, "Fade out", "afade_out", 0, 10, 0.05, 2, " s", default=0)
        tip = QLabel("Tip: drag the small handles at the top corners of the clip on the timeline.")
        tip.setObjectName("Dim")
        tip.setWordWrap(True)
        al.addWidget(tip)
        al.addWidget(section("Equalizer"))
        self.s_eql = self._slider(al, "Bass", "eq_low", -12, 12, 0.5, 1, " dB", default=0)
        self.s_eqm = self._slider(al, "Mids", "eq_mid", -12, 12, 0.5, 1, " dB", default=0)
        self.s_eqh = self._slider(al, "Treble", "eq_high", -12, 12, 0.5, 1, " dB", default=0)
        from PyQt6.QtWidgets import QGridLayout
        presets = QGridLayout()
        presets.setSpacing(6)
        for i, (name, vals) in enumerate((("Flat", (0, 0, 0)), ("Bass boost", (6, 0, 1)), ("Voice", (-3, 3, 2)),
                                          ("Bright", (0, 1, 5)), ("Warm", (3, 1, -3)), ("Telephone", (-10, 6, -8)))):
            b = QPushButton(name)
            b.setMinimumWidth(40)
            b.clicked.connect(lambda _=False, v=vals: self._eq_preset(v))
            presets.addWidget(b, i // 3, i % 3)
        al.addLayout(presets)
        al.addWidget(section("Clean up & space"))
        self.s_dn = self._slider(al, "Noise removal", "denoise", 0, 100, 1, 0, " %", factor=100, default=0)
        self.comp = Toggle("Even out loud and quiet parts (compressor)")
        self.comp.toggled.connect(lambda v: self._emit("compress", v, "Compressor", True))
        al.addWidget(self.comp)
        self.s_rev = self._slider(al, "Reverb", "reverb", 0, 100, 1, 0, " %", factor=100, default=0)
        reset = QPushButton("Reset audio effects")
        reset.clicked.connect(self._reset_audio)
        al.addWidget(reset, 0, Qt.AlignmentFlag.AlignLeft)
        lay.addWidget(self.audio_box)
        lay.addStretch(1)

    def _eq_preset(self, vals):
        for field, v, slider in zip(("eq_low", "eq_mid", "eq_high"), vals, (self.s_eql, self.s_eqm, self.s_eqh)):
            slider.setValue(v)
            self.changed.emit({field: float(v)})
        self.committed.emit("EQ preset")

    def _reset_audio(self):
        for f, v in (("pan", 0.0), ("afade_in", 0.0), ("afade_out", 0.0), ("eq_low", 0.0), ("eq_mid", 0.0),
                     ("eq_high", 0.0), ("compress", False), ("denoise", 0.0), ("reverb", 0.0), ("volume", 1.0)):
            self.changed.emit({f: v})
        self.committed.emit("Reset audio")
        self.load(self.clips)

    def _build_text(self):
        w, lay = self._page("Text")
        self.text_page_index = self.tabs.count() - 1
        lay.addWidget(section("Text"))
        self.text_edit = QPlainTextEdit()
        self.text_edit.setFixedHeight(80)
        self.text_edit.textChanged.connect(lambda: self._emit("text", self.text_edit.toPlainText(), "Edit text"))
        lay.addWidget(self.text_edit)
        row = QHBoxLayout()
        row.addWidget(QLabel("Style"))
        self.style_box = QComboBox()
        self.style_box.currentIndexChanged.connect(
            lambda _i: self._emit("text_style", self.style_box.currentData() or "none", "Text style", True))
        row.addWidget(self.style_box, 1)
        lay.addLayout(row)
        self.rebuild_styles()
        row = QHBoxLayout()
        row.addWidget(QLabel("Font"))
        self.font_box = QFontComboBox()
        self.font_box.currentFontChanged.connect(lambda f: self._emit("font", f.family(), "Font", True))
        row.addWidget(self.font_box, 1)
        lay.addLayout(row)
        self.s_fsize = self._slider(lay, "Size", "font_size", 10, 400, 1, 0, " px", default=80)
        row = QHBoxLayout()
        row.addWidget(QLabel("Colour"))
        self.text_col = ColorButton("#ffffff")
        self.text_col.colorChanged.connect(lambda c: self._emit("text_color", c, "Text colour", True))
        row.addWidget(self.text_col)
        self.bold = QPushButton("Bold")
        self.bold.setCheckable(True)
        self.bold.toggled.connect(lambda v: self._emit("bold", v, "Bold", True))
        row.addWidget(self.bold)
        self.outline = QPushButton("Outline")
        self.outline.setCheckable(True)
        self.outline.toggled.connect(lambda v: self._emit("text_outline", v, "Outline", True))
        row.addWidget(self.outline)
        row.addStretch(1)
        lay.addLayout(row)
        row = QHBoxLayout()
        self.text_bg = Toggle("Background box")
        self.text_bg.toggled.connect(lambda v: self._emit("text_bg", v, "Text background", True))
        row.addWidget(self.text_bg, 1)
        self.text_bg_col = ColorButton("#000000")
        self.text_bg_col.colorChanged.connect(lambda c: self._emit("text_bg_color", c, "Box colour", True))
        row.addWidget(self.text_bg_col)
        lay.addLayout(row)
        lay.addStretch(1)

    # ------------------------------------------------------------------ load
    def load(self, clips):
        self.clips = clips
        if not clips:
            self.stack.setCurrentIndex(0)
            self.title.setText("Inspector")
            return
        c = clips[0]
        self._loading = True
        try:
            self.stack.setCurrentIndex(1)
            self.title.setText(c["text"].split("\n")[0][:28] if c["kind"] == "text" else c["name"][:32]
                               if len(clips) == 1 else f"{len(clips)} clips selected")
            for s in self._sliders:
                s.setValue(float(c.get(s.field, s.default)) * s.factor)
            self._sync_fit(c.get("fit", "fit"))
            self.chroma_on.setChecked(bool(c.get("chroma")))
            self.chroma_col.setColor(c.get("chroma_color", "#00ff00"))
            for i, s in enumerate(self.crop_sliders):
                s.setValue(float(c.get("crop", [0, 0, 0, 0])[i]) * 100)
            self.flip_h.setChecked(bool(c.get("flip_h")))
            self.flip_v.setChecked(bool(c.get("flip_v")))
            idx = self.mirror.findData(c.get("mirror", "none"))
            self.mirror.setCurrentIndex(max(0, idx))
            self.stab_on.setChecked(bool(c.get("stabilize")))
            self.s_speed.setValue(float(c.get("speed", 1.0)))
            self.keep_pitch.setChecked(bool(c.get("keep_pitch", True)))
            self.mute.setChecked(bool(c.get("muted")))
            self.filter_label.setText("Filter: " + filters.get(c.get("filter", "none")).name)
            for eid, cb in getattr(self, "ext_checks", {}).items():
                on = next((f for f in c.get("fx", []) if f.get("id") == eid), None)
                cb.setChecked(on is not None)
                self.ext_amounts[eid].setVisible(on is not None)
                self.ext_amounts[eid].setValue(float(on.get("amount", 1.0)) * 100 if on else 100)
            kind = c["kind"]
            visual = kind in ("video", "image", "text")
            self.tabs.setTabVisible(0, visual)
            self.tabs.setTabVisible(1, visual)
            self.tabs.setTabVisible(2, visual)
            self.tabs.setTabVisible(3, kind in ("video", "audio"))
            self.tabs.setTabVisible(4, kind in ("video", "audio"))
            self.tabs.setTabVisible(self.text_page_index, kind == "text")
            self.stab_on.setEnabled(kind == "video")
            self.s_stab.setEnabled(kind == "video")
            has_sound = c.has_sound
            self.audio_box.setVisible(has_sound)
            self.no_audio.setVisible(not has_sound)
            self.comp.setChecked(bool(c.get("compress")))
            self.fit_btn.setEnabled(kind != "text")
            self.fill_btn.setEnabled(kind != "text")
            if kind == "text":
                if self.text_edit.toPlainText() != c.get("text", ""):
                    self.text_edit.setPlainText(c.get("text", ""))
                self.font_box.setCurrentFont(QFont(c.get("font", "Segoe UI")))
                self.style_box.setCurrentIndex(max(0, self.style_box.findData(c.get("text_style", "none"))))
                self.text_col.setColor(c.get("text_color", "#ffffff"))
                self.bold.setChecked(bool(c.get("bold", True)))
                self.outline.setChecked(bool(c.get("text_outline", True)))
                self.text_bg.setChecked(bool(c.get("text_bg")))
                self.text_bg_col.setColor(c.get("text_bg_color", "#000000"))
            if not self.tabs.isTabVisible(self.tabs.currentIndex()):
                for i in range(self.tabs.count()):
                    if self.tabs.isTabVisible(i):
                        self.tabs.setCurrentIndex(i)
                        break
        finally:
            self._loading = False

    def show_tab(self, name):
        for i in range(self.tabs.count()):
            if self.tabs.tabText(i) == name and self.tabs.isTabVisible(i):
                self.tabs.setCurrentIndex(i)
                return
