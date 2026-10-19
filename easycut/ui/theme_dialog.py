"""Appearance: pick Dark / Light / 🍏 Mode / Cyberpunk, or build and save a Custom theme."""
from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QPainter, QColor, QPainterPath, QPen, QFont
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QWidget, QGridLayout,
                             QLineEdit, QFontComboBox, QMessageBox, QScrollArea, QFrame, QStackedWidget, QComboBox)

from .. import theme, settings
from .widgets import ColorButton, SliderRow, section, Toggle


def paint_mini(p, rect, c):
    """Miniature Easy-Cut window in theme colours c."""
    r = QRectF(rect)
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    clip = QPainterPath()
    rad = 6 if c.get("radius", 8) else 0
    clip.addRoundedRect(r, rad, rad)
    p.setClipPath(clip)
    W, H, x0, y0 = r.width(), r.height(), r.left(), r.top()

    def box(x, y, w, h, col, rr=0.0):
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(col))
        q = QRectF(x0 + x * W, y0 + y * H, w * W, h * H)
        if rr:
            p.drawRoundedRect(q, rr * c.get("radius", 8) / 8, rr * c.get("radius", 8) / 8)
        else:
            p.drawRect(q)

    box(0, 0, 1, 1, c["window"])
    box(0, 0, 1, 0.11, c["header"])
    box(0.82, 0.025, 0.15, 0.06, c["accent"], 2)
    box(0.03, 0.035, 0.12, 0.04, c["text_strong"], 1)
    box(0, 0.11, 0.09, 0.89, c["header"])
    box(0.02, 0.15, 0.05, 0.07, c["accent_soft"] if "accent_soft" in c else c["panel2"], 1)
    box(0.02, 0.85, 0.05, 0.07, c["accent"], 1)
    box(0.1, 0.13, 0.25, 0.47, c["panel"], 2)
    for i in range(4):
        box(0.12 + (i % 2) * 0.115, 0.16 + (i // 2) * 0.14, 0.1, 0.11, c["panel2"], 1)
    box(0.37, 0.13, 0.36, 0.47, c["panel"], 2)
    box(0.40, 0.17, 0.30, 0.34, "#000000")
    box(0.75, 0.13, 0.23, 0.47, c["panel"], 2)
    for i in range(4):
        box(0.77, 0.18 + i * 0.09, 0.19, 0.02, c["text_dim"], 1)
        box(0.77, 0.21 + i * 0.09, 0.12, 0.015, c["accent"], 1)
    box(0.1, 0.63, 0.88, 0.35, c["timeline_bg"], 2)
    box(0.12, 0.68, 0.30, 0.08, c["clip_video"], 1)
    box(0.43, 0.68, 0.20, 0.08, c["clip_image"], 1)
    box(0.30, 0.78, 0.25, 0.07, c["clip_text"], 1)
    box(0.12, 0.87, 0.60, 0.07, c["clip_audio"], 1)
    box(0.5, 0.64, 0.004, 0.33, c["playhead"])
    p.restore()
    p.setPen(QPen(QColor(c["border"]), 1))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(r, rad, rad)


class ThemeCard(QPushButton):
    def __init__(self, theme_id):
        super().__init__()
        self.theme_id = theme_id
        self.setCheckable(True)
        self.setObjectName("Tile")
        self.setFixedSize(190, 150)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, ev):
        super().paintEvent(ev)
        c = theme.resolve(self.theme_id)
        p = QPainter(self)
        paint_mini(p, QRectF(10, 10, self.width() - 20, 100), c)
        p.setPen(QColor(theme.C["text_strong"]))
        f = QFont(self.font())
        f.setBold(True)
        p.setFont(f)
        name = theme.display_name(self.theme_id)
        if self.theme_id == settings.get("theme", "dark"):
            name += "  ✓ default"
        p.drawText(QRectF(0, 116, self.width(), 24), Qt.AlignmentFlag.AlignCenter, name)


class ThemeDialog(QDialog):
    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.setWindowTitle("Appearance")
        self.setMinimumSize(860, 620)
        self.original = theme.current_id
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 18)
        title = QLabel("Appearance")
        title.setObjectName("H1")
        lay.addWidget(title)
        sub = QLabel("Pick a look - it applies instantly and becomes your default. "
                     "Choose Custom to make your own.")
        sub.setObjectName("Dim")
        lay.addWidget(sub)
        self.stack = QStackedWidget()
        lay.addWidget(self.stack, 1)
        self.stack.addWidget(self._gallery())
        self.stack.addWidget(self._editor())

    # ------------------------------------------------------------------ gallery
    def _gallery(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 8, 0, 0)
        self.grid_holder = QWidget()
        self.grid = QGridLayout(self.grid_holder)
        self.grid.setSpacing(12)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setFrameShape(QFrame.Shape.NoFrame)
        sa.setWidget(self.grid_holder)
        v.addWidget(sa, 1)
        row = QHBoxLayout()
        new = QPushButton("  Custom…  ")
        new.setObjectName("Primary")
        new.clicked.connect(lambda: self.open_editor(None))
        row.addWidget(new)
        self.edit_btn = QPushButton("Edit selected custom theme")
        self.edit_btn.clicked.connect(lambda: self.open_editor(self._selected_custom()))
        self.del_btn = QPushButton("Delete")
        self.del_btn.clicked.connect(self._delete)
        row.addWidget(self.edit_btn)
        row.addWidget(self.del_btn)
        row.addStretch(1)
        close = QPushButton("Done")
        close.clicked.connect(self.accept)
        row.addWidget(close)
        v.addLayout(row)
        self._fill_gallery()
        return w

    def _fill_gallery(self):
        while self.grid.count():
            it = self.grid.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        ids = list(theme.PRESET_ORDER) + ["custom:" + n for n in theme.custom_themes()]
        self.cards = []
        for i, tid in enumerate(ids):
            card = ThemeCard(tid)
            card.setChecked(tid == theme.current_id)
            card.clicked.connect(lambda _=False, t=tid: self._choose(t))
            self.grid.addWidget(card, i // 4, i % 4)
            self.cards.append(card)
        self._sync_buttons()

    def _choose(self, tid):
        theme.apply(self.app, tid, remember=True)
        for c in self.cards:
            c.setChecked(c.theme_id == tid)
            c.update()
        self._sync_buttons()

    def _selected_custom(self):
        tid = theme.current_id
        return tid[7:] if tid.startswith("custom:") else None

    def _sync_buttons(self):
        has = self._selected_custom() is not None
        self.edit_btn.setEnabled(has)
        self.del_btn.setEnabled(has)

    def _delete(self):
        name = self._selected_custom()
        if not name:
            return
        if QMessageBox.question(self, "Delete theme", f"Delete the theme “{name}”?") != QMessageBox.StandardButton.Yes:
            return
        theme.delete_custom(name)
        theme.apply(self.app, "dark", remember=True)
        self._fill_gallery()

    # ------------------------------------------------------------------ editor
    def _editor(self):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 8, 0, 0)
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 8, 0)
        row = QHBoxLayout()
        row.addWidget(QLabel("Name"))
        self.name_edit = QLineEdit("My theme")
        row.addWidget(self.name_edit, 1)
        lv.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel("Start from"))
        self.base_combo = QComboBox()
        for tid in theme.PRESET_ORDER:
            self.base_combo.addItem(theme.display_name(tid), tid)
        self.base_combo.currentIndexChanged.connect(self._load_base)
        row.addWidget(self.base_combo, 1)
        lv.addLayout(row)
        lv.addWidget(section("Colours"))
        grid_w = QWidget()
        grid = QGridLayout(grid_w)
        grid.setContentsMargins(0, 0, 0, 0)
        self.color_buttons = {}
        for i, (key, label) in enumerate(theme.BASE_KEYS):
            b = ColorButton("#000000", title=label)
            b.colorChanged.connect(self._live)
            grid.addWidget(QLabel(label), i // 2, (i % 2) * 2)
            grid.addWidget(b, i // 2, (i % 2) * 2 + 1)
            self.color_buttons[key] = b
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setFrameShape(QFrame.Shape.NoFrame)
        sa.setWidget(grid_w)
        lv.addWidget(sa, 1)
        lv.addWidget(section("Shape & type"))
        self.radius = SliderRow("Corner radius", 0, 18, 8, step=1, decimals=0, suffix=" px", default=8)
        self.radius.editingFinished.connect(self._live)
        lv.addWidget(self.radius)
        row = QHBoxLayout()
        row.addWidget(QLabel("Font"))
        self.font_box = QFontComboBox()
        self.font_box.currentFontChanged.connect(lambda _f: self._live())
        row.addWidget(self.font_box, 1)
        lv.addLayout(row)
        self.set_default = Toggle("Set as my default theme")
        self.set_default.setChecked(True)
        lv.addWidget(self.set_default)
        row = QHBoxLayout()
        back = QPushButton("Cancel")
        back.clicked.connect(self._cancel_edit)
        save = QPushButton("Save theme")
        save.setObjectName("Primary")
        save.clicked.connect(self._save)
        row.addWidget(back)
        row.addStretch(1)
        row.addWidget(save)
        lv.addLayout(row)
        h.addWidget(left, 3)
        self.preview = _Preview()
        h.addWidget(self.preview, 2)
        return w

    def open_editor(self, name):
        self.editing = name
        self._before_edit = theme.current_id
        if name:
            data = theme.resolve("custom:" + name)
            self.name_edit.setText(name)
        else:
            data = theme.copy_current()
            self.name_edit.setText("My theme")
        self._set_editor(data)
        self.stack.setCurrentIndex(1)

    def _set_editor(self, data):
        self._mute = True
        for key, b in self.color_buttons.items():
            b.setColor(data.get(key, "#000000"))
        self.radius.setValue(data.get("radius", 8))
        self.font_box.setCurrentFont(QFont(data.get("font", "Segoe UI")))
        self._mute = False
        self._live()

    def _load_base(self):
        self._set_editor(theme.resolve(self.base_combo.currentData()))

    def _collect(self):
        d = {k: b.color() for k, b in self.color_buttons.items()}
        d["radius"] = int(self.radius.value())
        d["font"] = self.font_box.currentFont().family()
        return d

    def _live(self, *_):
        if getattr(self, "_mute", False):
            return
        c = theme.complete(self._collect())
        theme.C.clear()
        theme.C.update(c)
        self.app.setStyleSheet(theme.stylesheet(c))
        theme.notifier.changed.emit()
        self.preview.colors = c
        self.preview.update()

    def _cancel_edit(self):
        theme.apply(self.app, self._before_edit)
        self.stack.setCurrentIndex(0)

    def _save(self):
        name = self.name_edit.text().strip() or "My theme"
        if name in [theme.display_name(t) for t in theme.PRESET_ORDER]:
            name += " (custom)"
        theme.save_custom(name, self._collect())
        tid = "custom:" + name
        theme.apply(self.app, tid, remember=self.set_default.isChecked())
        if not self.set_default.isChecked():
            theme.apply(self.app, self._before_edit)
        self._fill_gallery()
        self.stack.setCurrentIndex(0)


class _Preview(QWidget):
    def __init__(self):
        super().__init__()
        self.colors = None
        self.setMinimumWidth(280)

    def paintEvent(self, ev):
        if not self.colors:
            return
        p = QPainter(self)
        w = self.width() - 10
        h = w * 0.68
        paint_mini(p, QRectF(5, 20, w, h), self.colors)
        p.setPen(QColor(theme.C["text_dim"]))
        p.drawText(QRectF(5, 30 + h, w, 40), Qt.AlignmentFlag.AlignHCenter,
                   "Live preview - the whole app updates as you edit")
