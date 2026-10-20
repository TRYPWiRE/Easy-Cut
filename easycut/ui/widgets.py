"""Small reusable widgets."""
from PyQt6.QtCore import Qt, pyqtSignal, QRect, QSize, QPoint, QTimer, QRectF
from PyQt6.QtGui import QColor, QPainter, QPen, QLinearGradient, QPainterPath
from PyQt6.QtWidgets import (QWidget, QHBoxLayout, QLabel, QSlider, QDoubleSpinBox, QPushButton, QColorDialog,
                             QLayout, QFrame, QCheckBox)

from .. import theme, icons


class SliderRow(QWidget):
    """Label + slider + numeric box. Emits valueChanged(float) live and editingFinished() on release."""
    valueChanged = pyqtSignal(float)
    editingFinished = pyqtSignal()

    def __init__(self, label, lo, hi, value=0.0, step=0.01, decimals=2, suffix="", default=None, parent=None):
        super().__init__(parent)
        self.lo, self.hi, self.step = lo, hi, step
        self.default = value if default is None else default
        self._mute = False
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 2)
        lay.setSpacing(8)
        self.label = QLabel(label)
        self.label.setMinimumWidth(84)
        self.label.setToolTip("Double-click the slider to reset")
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, int(round((hi - lo) / step)))
        self.spin = QDoubleSpinBox()
        self.spin.setRange(lo, hi)
        self.spin.setDecimals(decimals)
        self.spin.setSingleStep(step)
        self.spin.setSuffix(suffix)
        self.spin.setFixedWidth(74)
        self.spin.setAlignment(Qt.AlignmentFlag.AlignRight)
        lay.addWidget(self.label)
        lay.addWidget(self.slider, 1)
        lay.addWidget(self.spin)
        self.slider.valueChanged.connect(self._from_slider)
        self.spin.valueChanged.connect(self._from_spin)
        self.slider.sliderReleased.connect(self.editingFinished)
        self.spin.editingFinished.connect(self.editingFinished)
        self.slider.mouseDoubleClickEvent = self._reset
        self.setValue(value)

    def _reset(self, _ev):
        self.setValue(self.default)
        self.valueChanged.emit(self.default)
        self.editingFinished.emit()

    def _from_slider(self, v):
        if self._mute:
            return
        val = self.lo + v * self.step
        self._mute = True
        self.spin.setValue(val)
        self._mute = False
        self.valueChanged.emit(val)
        if not self.slider.isSliderDown():
            self.editingFinished.emit()

    def _from_spin(self, val):
        if self._mute:
            return
        self._mute = True
        self.slider.setValue(int(round((val - self.lo) / self.step)))
        self._mute = False
        self.valueChanged.emit(val)

    def setValue(self, val):
        self._mute = True
        self.spin.setValue(float(val))
        self.slider.setValue(int(round((float(val) - self.lo) / self.step)))
        self._mute = False

    def value(self):
        return self.spin.value()


class ColorButton(QPushButton):
    colorChanged = pyqtSignal(str)

    def __init__(self, color="#ffffff", parent=None, title="Choose colour"):
        super().__init__(parent)
        self.title = title
        self.setFixedSize(46, 26)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._color = color
        self.clicked.connect(self._pick)

    def color(self):
        return self._color

    def setColor(self, c):
        self._color = QColor(c).name()
        self.update()

    def _pick(self):
        c = QColorDialog.getColor(QColor(self._color), self, self.title)
        if c.isValid():
            self.setColor(c.name())
            self.colorChanged.emit(self._color)

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        p.setPen(QPen(QColor(theme.C.get("border", "#444")), 1.5))
        p.setBrush(QColor(self._color))
        rad = min(6, theme.C.get("radius", 6))
        p.drawRoundedRect(r, rad, rad)


def section(text):
    lbl = QLabel(text.upper())
    lbl.setObjectName("Section")
    return lbl


def hline():
    f = QFrame()
    f.setFixedHeight(1)
    f.setStyleSheet(f"background: {theme.C.get('border', '#333')};")
    return f


def icon_button(name, tip="", size=20, checkable=False, flat=True):
    b = QPushButton()
    b.setObjectName("Flat" if flat else "")
    icons.bind(b, name, size)
    b.setToolTip(tip)
    b.setCheckable(checkable)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setFixedSize(size + 14, size + 12)
    return b


class Toggle(QCheckBox):
    """iOS-style switch."""

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("QCheckBox::indicator { width: 0; height: 0; border: none; background: none; }")

    def sizeHint(self):
        s = super().sizeHint()
        return QSize(s.width() + 44, max(24, s.height()))

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = theme.C
        w, h = 38, 22
        y = (self.height() - h) / 2
        r = QRectF(self.width() - w - 2, y, w, h)
        on = self.isChecked()
        rad = h / 2 if c.get("radius", 8) > 0 else 2
        p.setPen(Qt.PenStyle.NoPen)
        on_col = c.get("switch_on", c["accent"]) if c.get("apple") else c["accent"]
        p.setBrush(QColor(on_col if on else (c["pressed"] if not c.get("apple") else
                                              ("#39393d" if c.get("dark") else "#e2e2e7"))))
        p.drawRoundedRect(r, rad, rad)
        k = h - 6
        kx = r.right() - k - 3 if on else r.left() + 3
        if c.get("apple"):
            p.setBrush(QColor(0, 0, 0, 40))
            p.drawEllipse(QRectF(kx, y + 3.8, k, k))
        p.setBrush(QColor("#ffffff" if not c.get("cyber") or not on else c["accent_text"]))
        p.drawRoundedRect(QRectF(kx, y + 3, k, k), rad - 3 if rad > 3 else 1, rad - 3 if rad > 3 else 1)
        p.setPen(QColor(c["text"]))
        p.drawText(QRect(0, 0, int(self.width() - w - 10), self.height()),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.text())

    def hitButton(self, pos):
        return self.rect().contains(pos)


class FlowLayout(QLayout):
    """Wrapping grid layout for tiles."""

    def __init__(self, parent=None, spacing=8):
        super().__init__(parent)
        self.items = []
        self.setSpacing(spacing)
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self.items.append(item)

    def count(self):
        return len(self.items)

    def itemAt(self, i):
        return self.items[i] if 0 <= i < len(self.items) else None

    def takeAt(self, i):
        return self.items.pop(i) if 0 <= i < len(self.items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        return self._do(QRect(0, 0, w, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        s = QSize()
        for it in self.items:
            s = s.expandedTo(it.minimumSize())
        return s + QSize(2, 2)

    def _do(self, rect, test):
        x, y, line_h = rect.x(), rect.y(), 0
        sp = self.spacing()
        for it in self.items:
            hint = it.sizeHint()
            nx = x + hint.width() + sp
            if nx - sp > rect.right() and line_h > 0:
                x = rect.x()
                y += line_h + sp
                nx = x + hint.width() + sp
                line_h = 0
            if not test:
                it.setGeometry(QRect(QPoint(x, y), hint))
            x = nx
            line_h = max(line_h, hint.height())
        return y + line_h - rect.y()


class RenderProgressBar(QWidget):
    """A slim, smooth progress bar with a soft moving sheen (repaints only itself, ~30 fps while active)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.value = 0.0
        self.shown = 0.0
        self.phase = 0.0
        self.setFixedHeight(14)
        self.timer = QTimer(self)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self._tick)

    def setValue(self, v):
        self.value = max(0.0, min(1.0, float(v)))
        if not self.timer.isActive():
            self.timer.start()

    def stop(self):
        self.timer.stop()
        self.update()

    def _tick(self):
        self.shown += (self.value - self.shown) * 0.18
        self.phase = (self.phase + 0.02) % 1.0
        self.update()
        if abs(self.value - self.shown) < 0.0005 and self.value >= 1.0:
            self.timer.stop()

    def paintEvent(self, ev):
        c = theme.C
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0, 3, 0, -3)
        rad = r.height() / 2 if c.get("radius", 8) > 0 else 0
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(c["pressed"]))
        p.drawRoundedRect(r, rad, rad)
        w = r.width() * self.shown
        if w > 1:
            fr = QRectF(r.left(), r.top(), max(r.height(), w), r.height())
            g = QLinearGradient(fr.topLeft(), fr.topRight())
            g.setColorAt(0, QColor(c["accent2"]))
            g.setColorAt(1, QColor(c["accent"]))
            p.setBrush(g)
            p.drawRoundedRect(fr, rad, rad)
            # sheen
            sx = fr.left() + (fr.width() + 80) * self.phase - 40
            sg = QLinearGradient(sx - 40, 0, sx + 40, 0)
            sg.setColorAt(0, QColor(255, 255, 255, 0))
            sg.setColorAt(0.5, QColor(255, 255, 255, 70))
            sg.setColorAt(1, QColor(255, 255, 255, 0))
            path = QPainterPath()
            path.addRoundedRect(fr, rad, rad)
            p.setClipPath(path)
            p.fillRect(fr, sg)


def fmt_time(t, fps=30, frames=False):
    t = max(0.0, t)
    m, s = divmod(t, 60)
    h, m = divmod(int(m), 60)
    if frames:
        f = int(round((t - int(t)) * fps)) % fps
        return f"{h:02d}:{m:02d}:{int(s):02d}:{f:02d}" if h else f"{m:02d}:{int(s):02d}:{f:02d}"
    return f"{h}:{m:02d}:{int(s):02d}" if h else f"{m:02d}:{s:05.2f}"


class Tile(QPushButton):
    """Library tile: picture (or themed icon) on top, label underneath."""

    def __init__(self, label, image=None, icon_name=None, size=(128, 104), icon_size=30, parent=None,
                 locked=False, font=None):
        super().__init__(parent)
        self.locked = locked            # part of a pack that isn't downloaded yet: drawn greyed with a lock
        self.font_family = font         # draw the label in this font (font tiles)
        self.label = label
        self.image = image              # QImage / QPixmap or None
        self.icon_name = icon_name
        self.icon_size = icon_size
        self.setObjectName("Tile")
        self.setFixedSize(*size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, ev):
        from PyQt6.QtWidgets import QStyleOptionButton, QStyle
        from PyQt6.QtGui import QPixmap
        opt = QStyleOptionButton()
        self.initStyleOption(opt)
        opt.text = ""
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.style().drawControl(QStyle.ControlElement.CE_PushButton, opt, p, self)
        c = theme.C
        label_h = 22
        area = QRectF(6, 6, self.width() - 12, self.height() - 12 - label_h)
        if self.image is not None:
            pm = self.image if isinstance(self.image, QPixmap) else QPixmap.fromImage(self.image)
            s = min(area.width() / pm.width(), area.height() / pm.height())
            w, h = pm.width() * s, pm.height() * s
            r = QRectF(area.center().x() - w / 2, area.center().y() - h / 2, w, h)
            path = QPainterPath()
            rad = min(6, c.get("radius", 6))
            path.addRoundedRect(r, rad, rad)
            p.save()
            p.setClipPath(path)
            if self.locked:
                p.setOpacity(0.38)
            p.drawPixmap(r.toRect(), pm)
            p.restore()
        elif self.icon_name:
            sz = self.icon_size
            col = c["accent_text"] if (self.isChecked() and c.get("cyber")) else c["accent"]
            p.drawPixmap(int(area.center().x() - sz / 2), int(area.center().y() - sz / 2),
                         icons.pixmap(self.icon_name, sz, col))
        if self.locked:
            # lock badge in the top-right corner of the picture
            br = QRectF(self.width() - 30, 9, 21, 21)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, 150))
            p.drawEllipse(br)
            p.drawPixmap(int(br.left() + 3), int(br.top() + 3), icons.pixmap("lock", 15, "#ffffff"))
        p.setPen(QColor(c["text_dim"] if self.locked else c["text_strong"] if self.isChecked() else c["text"]))
        f = p.font()
        f.setBold(self.isChecked())
        p.setFont(f)
        from PyQt6.QtGui import QFontMetrics
        fm = QFontMetrics(f)
        text = fm.elidedText(self.label, Qt.TextElideMode.ElideRight, self.width() - 10)
        if self.image is None and self.icon_name is None:
            p.drawText(QRectF(4, 4, self.width() - 8, self.height() - 8), Qt.AlignmentFlag.AlignCenter |
                       Qt.TextFlag.TextWordWrap, self.label)
        else:
            p.drawText(QRectF(5, self.height() - label_h - 6, self.width() - 10, label_h),
                       Qt.AlignmentFlag.AlignCenter, text)
        p.end()
