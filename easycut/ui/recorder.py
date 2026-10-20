"""Record window: capture the screen (games included), the webcam and audio, then drop it all on the timeline.

- Live preview of the chosen display, with the webcam's picture-in-picture spot drawn on it
- Source cards: Screen, Webcam (+ corner and size), Microphone, System audio
- Quality: frame rate, resolution, quality, encoder (graphics card when available)
- Countdown, hide Easy-Cut while recording, global hotkey (Ctrl+Shift+R) to start/stop from inside a game
- A small floating REC bar while recording (hidden from the recording itself on Windows 10/11)
- When you stop, every part lands on its own timeline track, already lined up
"""
import os
import sys
import time

from PyQt6.QtCore import (Qt, QTimer, QThread, pyqtSignal, QRectF, QPoint, QAbstractNativeEventFilter, QUrl,
                          QObject)
from PyQt6.QtGui import QPainter, QColor, QPen, QFont, QGuiApplication, QDesktopServices, QPainterPath
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox, QWidget, QFrame,
                             QFileDialog, QButtonGroup, QApplication, QMessageBox, QGridLayout, QScrollArea,
                             QSizePolicy)

from .. import capture, config, icons, media, settings, theme
from .widgets import Toggle, SliderRow, section


def clock(t):
    t = int(max(0, t))
    h, r = divmod(t, 3600)
    m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"

IS_WIN = sys.platform == "win32"
HOTKEY_TEXT = "Ctrl+Shift+R"


# ====================================================================== global hotkey (Windows)
class GlobalHotkey(QAbstractNativeEventFilter):
    """Ctrl+Shift+R anywhere in Windows - even inside a full-screen game - calls `callback`."""
    WM_HOTKEY = 0x0312
    ID = 0xEC01

    def __init__(self, callback):
        super().__init__()
        self.callback = callback
        self.ok = False
        if not IS_WIN:
            return
        try:
            import ctypes
            MOD_CONTROL, MOD_SHIFT, MOD_NOREPEAT = 0x2, 0x4, 0x4000
            self.ok = bool(ctypes.windll.user32.RegisterHotKey(None, self.ID, MOD_CONTROL | MOD_SHIFT | MOD_NOREPEAT,
                                                               ord("R")))
            if self.ok:
                QApplication.instance().installNativeEventFilter(self)
        except Exception:
            self.ok = False

    def nativeEventFilter(self, etype, message):
        if etype == b"windows_generic_MSG" or etype == "windows_generic_MSG":
            try:
                import ctypes
                from ctypes import wintypes
                msg = wintypes.MSG.from_address(int(message))
                if msg.message == self.WM_HOTKEY and msg.wParam == self.ID:
                    QTimer.singleShot(0, self.callback)
                    return True, 0
            except Exception:
                pass
        return False, 0

    def release(self):
        if self.ok and IS_WIN:
            try:
                import ctypes
                ctypes.windll.user32.UnregisterHotKey(None, self.ID)
                QApplication.instance().removeNativeEventFilter(self)
            except Exception:
                pass
        self.ok = False


def exclude_from_capture(widget):
    """Windows 10 2004+: keep this window out of screen recordings (it stays visible to you)."""
    if not IS_WIN:
        return
    try:
        import ctypes
        ctypes.windll.user32.SetWindowDisplayAffinity(int(widget.winId()), 0x11)   # WDA_EXCLUDEFROMCAPTURE
    except Exception:
        pass


# ====================================================================== threads
class DeviceThread(QThread):
    found = pyqtSignal(dict)

    def run(self):
        self.found.emit(capture.list_devices())


class StartThread(QThread):
    failed = pyqtSignal(str)
    started_ok = pyqtSignal()

    def __init__(self, rec):
        super().__init__()
        self.rec = rec

    def run(self):
        try:
            self.rec.start()
            self.started_ok.emit()
        except Exception as e:  # noqa: BLE001 - shown to the user
            self.failed.emit(str(e))


class StopThread(QThread):
    done = pyqtSignal(object)
    status = pyqtSignal(str)

    def __init__(self, rec):
        super().__init__()
        self.rec = rec

    def run(self):
        self.done.emit(self.rec.stop(lambda s: self.status.emit(s)))


# ====================================================================== preview
class ScreenPreview(QWidget):
    """A live thumbnail of the chosen display with the webcam spot drawn where it'll go."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(320, 180)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.pix = None
        self.monitor = None
        self.screen_on = True
        self.cam = False
        self.corner = "br"
        self.cam_size = 0.28
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.grab)
        self.timer.start(700)

    def _qscreen(self):
        screens = QGuiApplication.screens()
        if not screens:
            return None
        if self.monitor:
            for s in screens:
                g = s.geometry()
                d = s.devicePixelRatio()
                if abs(g.x() * d - self.monitor["x"]) < 4 and abs(g.y() * d - self.monitor["y"]) < 4:
                    return s
        return QGuiApplication.primaryScreen()

    def grab(self):
        if not self.isVisible() or not self.screen_on:
            return
        s = self._qscreen()
        if s is None:
            return
        try:
            pm = s.grabWindow(0)
            if not pm.isNull():
                self.pix = pm.scaled(640, 360, Qt.AspectRatioMode.KeepAspectRatio,
                                     Qt.TransformationMode.SmoothTransformation)
        except Exception:
            self.pix = None
        self.update()

    def paintEvent(self, ev):
        c = theme.C
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        aw = (self.monitor or {}).get("w", 16) or 16
        ah = (self.monitor or {}).get("h", 9) or 9
        W, H = self.width() - 4, self.height() - 4
        if W / H > aw / ah:
            h = H
            w = h * aw / ah
        else:
            w = W
            h = w * ah / aw
        r = QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)
        rad = 10 if c.get("radius", 8) else 0
        path = QPainterPath()
        path.addRoundedRect(r, rad, rad)
        p.setClipPath(path)
        p.fillRect(r, QColor("#0b0b0e"))
        if self.screen_on and self.pix is not None:
            p.drawPixmap(r.toRect(), self.pix)
        elif not self.screen_on:
            p.setPen(QColor("#8a8a93"))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, "Screen off - webcam / audio only")
        if self.cam:
            cw = r.width() * self.cam_size
            ch = cw * 9 / 16
            m = r.width() * 0.025
            x = r.right() - cw - m if self.corner in ("br", "tr") else r.left() + m
            y = r.bottom() - ch - m if self.corner in ("br", "bl") else r.top() + m
            cr = QRectF(x, y, cw, ch)
            p.setPen(QPen(QColor(c["accent"]), 2))
            p.setBrush(QColor(20, 20, 26, 210))
            p.drawRoundedRect(cr, 6, 6)
            p.drawPixmap(int(cr.center().x() - 11), int(cr.center().y() - 11), icons.pixmap("webcam", 22, "#ffffff"))
        p.setClipping(False)
        p.setPen(QPen(QColor(c["border"]), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(r, rad, rad)


class SourceCard(QFrame):
    """A rounded card: icon + title + switch on top, settings underneath (dimmed while off)."""

    def __init__(self, icon_name, title, subtitle, on=True):
        super().__init__()
        self.setObjectName("Card")
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 10, 14, 12)
        v.setSpacing(8)
        top = QHBoxLayout()
        ic = QLabel()
        ic.setPixmap(icons.pixmap(icon_name, 22, theme.C["accent"]))
        top.addWidget(ic)
        tv = QVBoxLayout()
        tv.setSpacing(0)
        t = QLabel(title)
        t.setObjectName("H3")
        f = t.font()
        f.setBold(True)
        t.setFont(f)
        tv.addWidget(t)
        self.sub = QLabel(subtitle)
        self.sub.setObjectName("Dim")
        self.sub.setWordWrap(True)
        tv.addWidget(self.sub)
        top.addLayout(tv, 1)
        self.toggle = Toggle()
        self.toggle.setChecked(on)
        self.toggle.toggled.connect(self._sync)
        top.addWidget(self.toggle, 0, Qt.AlignmentFlag.AlignTop)
        v.addLayout(top)
        self.body = QWidget()
        self.body_l = QVBoxLayout(self.body)
        self.body_l.setContentsMargins(32, 0, 0, 0)
        self.body_l.setSpacing(6)
        v.addWidget(self.body)
        self._sync(on)

    def _sync(self, on):
        self.body.setEnabled(on)

    def on(self):
        return self.toggle.isChecked() and self.toggle.isEnabled()


def _combo(items, current=None):
    cb = QComboBox()
    for data, label in items:
        cb.addItem(label, data)
    if current is not None:
        cb.setCurrentIndex(max(0, cb.findData(current)))
    return cb


def _segmented(items, current, on_change=None):
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(4)
    g = QButtonGroup(w)
    g.setExclusive(True)
    for key, label in items:
        b = QPushButton(label)
        b.setCheckable(True)
        b.setObjectName("Seg")
        b.setProperty("key", key)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setChecked(key == current)
        g.addButton(b)
        h.addWidget(b)
    w.group = g

    def value():
        b = g.checkedButton()
        return b.property("key") if b else current
    w.value = value
    if on_change:
        g.buttonClicked.connect(lambda _b: on_change(value()))
    return w


# ====================================================================== countdown + REC bar
class Countdown(QWidget):
    finished = pyqtSignal()

    def __init__(self, seconds=3):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint |
                         Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.n = seconds
        self.setFixedSize(220, 220)
        self.t = QTimer(self)
        self.t.timeout.connect(self._tick)

    def start(self, monitor=None):
        scr = QGuiApplication.primaryScreen().geometry()
        self.move(scr.center() - QPoint(110, 110))
        self.show()
        exclude_from_capture(self)
        self.t.start(1000)

    def _tick(self):
        self.n -= 1
        if self.n <= 0:
            self.t.stop()
            self.hide()
            self.finished.emit()
            self.deleteLater()
        else:
            self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(12, 12, 16, 200))
        p.drawEllipse(QRectF(10, 10, 200, 200))
        p.setPen(QPen(QColor("#ff453a"), 6))
        p.drawEllipse(QRectF(16, 16, 188, 188))
        f = QFont(self.font())
        f.setPixelSize(96)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor("#ffffff"))
        p.drawText(QRectF(0, 0, 220, 220), Qt.AlignmentFlag.AlignCenter, str(self.n))


class RecBar(QWidget):
    """Floating, draggable bar shown while recording: ● REC 00:12  ·  60 fps  ·  42 MB  [Stop]."""
    stopRequested = pyqtSignal()

    def __init__(self):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint |
                         Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        h = QHBoxLayout(self)
        h.setContentsMargins(16, 8, 8, 8)
        h.setSpacing(10)
        self.dot = QLabel()
        self.dot.setFixedSize(12, 12)
        h.addWidget(self.dot)
        self.time = QLabel("00:00")
        f = self.time.font()
        f.setBold(True)
        f.setPointSizeF(max(10.5, f.pointSizeF() * 1.15))
        self.time.setFont(f)
        self.time.setStyleSheet("color: white;")
        h.addWidget(self.time)
        self.info = QLabel("")
        self.info.setStyleSheet("color: rgba(255,255,255,170);")
        h.addWidget(self.info)
        self.stop_btn = QPushButton("  Stop")
        icons.bind(self.stop_btn, "stop", 14, "#ffffff")
        self.stop_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.stop_btn.setStyleSheet("QPushButton { background: #ff453a; color: white; border: none; border-radius: 13px;"
                                    " padding: 5px 14px; font-weight: 600; } QPushButton:hover { background: #ff6259; }")
        self.stop_btn.clicked.connect(self.stopRequested)
        h.addWidget(self.stop_btn)
        self.blink = True
        self._drag = None
        self.setToolTip(f"Drag to move. {HOTKEY_TEXT} stops the recording from anywhere.")

    def place(self):
        scr = QGuiApplication.primaryScreen().availableGeometry()
        self.adjustSize()
        self.move(scr.center().x() - self.width() // 2, scr.top() + 18)

    def set_status(self, elapsed, fps, size, blink):
        self.time.setText(clock(elapsed))
        bits = []
        if fps:
            bits.append(f"{fps:.0f} fps")
        if size:
            bits.append(f"{size / 1e6:.0f} MB" if size < 1e9 else f"{size / 1e9:.2f} GB")
        self.info.setText("  ·  ".join(bits))
        self.dot.setStyleSheet(f"background: {'#ff453a' if blink else '#6b1f1b'}; border-radius: 6px;")

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor(255, 255, 255, 40), 1))
        p.setBrush(QColor(22, 22, 28, 235))
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self._drag = ev.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, ev):
        if self._drag is not None:
            self.move(ev.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, ev):
        self._drag = None


# ====================================================================== the dialog
class RecorderDialog(QDialog):
    """Emits `recorded(result, options)` once the files are finished."""
    recorded = pyqtSignal(object, dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Record - Easy-Cut")
        self.resize(1000, 660)
        self.setMinimumSize(760, 520)
        self.rec = None
        self.state = "idle"           # idle | countdown | starting | recording | stopping
        self.devices = {"video": [], "audio": []}
        self.mons = capture.monitors()
        self.hotkey = GlobalHotkey(self.toggle_recording)
        self.bar = None
        self.hidden_windows = []
        self._build()
        self._load_settings()
        self.dev_thread = DeviceThread()
        self.dev_thread.found.connect(self._devices_found)
        self.dev_thread.start()
        self.tick = QTimer(self)
        self.tick.timeout.connect(self._tick)
        self._blink = 0

    # ------------------------------------------------------------------ layout
    def _build(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(18)
        # left: preview + start
        left = QVBoxLayout()
        left.setSpacing(12)
        head = QHBoxLayout()
        ic = QLabel()
        ic.setPixmap(icons.pixmap("record", 26, "#ff453a"))
        head.addWidget(ic)
        tv = QVBoxLayout()
        tv.setSpacing(0)
        t = QLabel("Record")
        t.setObjectName("H1")
        tv.addWidget(t)
        s = QLabel("Your screen, gameplay, webcam and sound - straight into your timeline.")
        s.setObjectName("Dim")
        tv.addWidget(s)
        head.addLayout(tv, 1)
        left.addLayout(head)
        self.preview = ScreenPreview()
        left.addWidget(self.preview, 1)
        self.status = QLabel("")
        self.status.setObjectName("Dim")
        self.status.setWordWrap(True)
        left.addWidget(self.status)
        row = QHBoxLayout()
        self.folder_btn = QPushButton("  Recordings folder")
        icons.bind(self.folder_btn, "folder", 16)
        self.folder_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(self._out_dir())))
        row.addWidget(self.folder_btn)
        row.addStretch(1)
        self.start_btn = QPushButton("  Start recording")
        self.start_btn.setObjectName("Primary")
        self.start_btn.setMinimumHeight(40)
        self.start_btn.setMinimumWidth(220)
        icons.bind(self.start_btn, "record", 16, "accent_text")
        self.start_btn.clicked.connect(self.toggle_recording)
        row.addWidget(self.start_btn)
        left.addLayout(row)
        self.hint = QLabel((f"Tip: press {HOTKEY_TEXT} anywhere - even in a full-screen game - to start or stop."
                            if self.hotkey.ok or not IS_WIN else ""))
        self.hint.setObjectName("Dim")
        self.hint.setAlignment(Qt.AlignmentFlag.AlignRight)
        left.addWidget(self.hint)
        root.addLayout(left, 3)

        # right: sources and options (scrollable)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.Shape.NoFrame)
        sc.setMinimumWidth(360)
        holder = QWidget()
        rv = QVBoxLayout(holder)
        rv.setContentsMargins(0, 0, 12, 0)
        rv.setSpacing(10)
        rv.addWidget(section("Sources"))

        # screen
        self.screen_card = SourceCard("screen", "Screen", "A display - games, apps, anything you can see.")
        self.mon_combo = QComboBox()
        for m in self.mons:
            self.mon_combo.addItem(m["label"], m["index"])
        self.mon_combo.currentIndexChanged.connect(self._sync_preview)
        self.screen_card.body_l.addWidget(self.mon_combo)
        self.method_combo = _combo((("auto", "Automatic (best for games)"),
                                    ("dxgi", "Game capture - graphics card (DXGI)"),
                                    ("gdi", "Compatible capture (GDI)")))
        self.method_combo.setToolTip("Automatic uses the graphics card's desktop duplication - fast and smooth in "
                                     "games - and falls back to the compatible method if it isn't available.")
        self.screen_card.body_l.addWidget(self.method_combo)
        self.mouse_t = Toggle("Show mouse pointer")
        self.mouse_t.setChecked(True)
        self.screen_card.body_l.addWidget(self.mouse_t)
        self.screen_card.toggle.toggled.connect(self._sync_preview)
        rv.addWidget(self.screen_card)

        # webcam
        self.cam_card = SourceCard("webcam", "Webcam", "Picture-in-picture over your screen.", on=False)
        self.cam_combo = QComboBox()
        self.cam_combo.addItem("Looking for cameras…", None)
        self.cam_card.body_l.addWidget(self.cam_combo)
        self.corner_seg = _segmented((("tl", "↖"), ("tr", "↗"), ("bl", "↙"), ("br", "↘")), "br",
                                     lambda _v: self._sync_preview())
        crow = QHBoxLayout()
        cl = QLabel("Corner")
        cl.setObjectName("Dim")
        crow.addWidget(cl)
        crow.addWidget(self.corner_seg, 1)
        self.cam_card.body_l.addLayout(crow)
        self.cam_size = SliderRow("Size", 12, 50, 28, step=1, decimals=0, suffix="%")
        self.cam_size.valueChanged.connect(lambda _v: self._sync_preview())
        self.cam_card.body_l.addWidget(self.cam_size)
        self.cam_card.toggle.toggled.connect(self._sync_preview)
        rv.addWidget(self.cam_card)

        # microphone
        self.mic_card = SourceCard("mic", "Microphone", "Your voice, on its own track.", on=False)
        self.mic_combo = QComboBox()
        self.mic_combo.addItem("Looking for microphones…", None)
        self.mic_card.body_l.addWidget(self.mic_combo)
        rv.addWidget(self.mic_card)

        # system audio
        avail = capture.system_audio_available()
        self.sys_card = SourceCard("speaker", "System audio",
                                   "Game sound, music, voice chat - everything you hear." if avail else
                                   "Needs Windows (and the 'soundcard' add-on, included in the installer).",
                                   on=avail)
        self.sys_card.toggle.setEnabled(avail)
        rv.addWidget(self.sys_card)

        # quality
        rv.addWidget(section("Quality"))
        q = QFrame()
        q.setObjectName("Card")
        g = QGridLayout(q)
        g.setContentsMargins(14, 12, 14, 12)
        g.setHorizontalSpacing(10)
        g.setVerticalSpacing(8)

        def lab(text):
            lb = QLabel(text)
            lb.setObjectName("Dim")
            return lb
        g.addWidget(lab("Frame rate"), 0, 0)
        self.fps_seg = _segmented(((30, "30"), (60, "60"), (120, "120")), 60)
        g.addWidget(self.fps_seg, 0, 1)
        g.addWidget(lab("Resolution"), 1, 0)
        self.scale_combo = _combo((("native", "Same as the screen"), ("1440p", "1440p"), ("1080p", "1080p"),
                                   ("720p", "720p (smallest files)")))
        g.addWidget(self.scale_combo, 1, 1)
        g.addWidget(lab("Quality"), 2, 0)
        self.quality_seg = _segmented((("standard", "Standard"), ("high", "High"), ("ultra", "Ultra")), "high")
        g.addWidget(self.quality_seg, 2, 1)
        g.addWidget(lab("Encoder"), 3, 0)
        enc = [("auto", "Automatic (graphics card if possible)")]
        try:
            enc += [(e, n) for e, n in media.hardware_encoders()]
        except Exception:
            pass
        enc.append(("cpu", "Processor (x264)"))
        self.enc_combo = _combo(enc)
        g.addWidget(self.enc_combo, 3, 1)
        g.setColumnStretch(1, 1)
        rv.addWidget(q)

        # options
        rv.addWidget(section("When recording"))
        o = QFrame()
        o.setObjectName("Card")
        ov = QVBoxLayout(o)
        ov.setContentsMargins(14, 10, 14, 10)
        ov.setSpacing(6)
        self.countdown_t = Toggle("3-second countdown")
        self.hide_t = Toggle("Hide Easy-Cut while recording")
        self.timeline_t = Toggle("Add to the timeline when I stop")
        for w in (self.countdown_t, self.hide_t, self.timeline_t):
            w.setChecked(True)
            ov.addWidget(w)
        frow = QHBoxLayout()
        self.dir_label = QLabel("")
        self.dir_label.setObjectName("Dim")
        self.dir_label.setWordWrap(True)
        frow.addWidget(self.dir_label, 1)
        ch = QPushButton("Change…")
        ch.clicked.connect(self._choose_dir)
        frow.addWidget(ch)
        ov.addLayout(frow)
        rv.addWidget(o)
        rv.addStretch(1)
        for card in (self.mic_card, self.sys_card):
            card.toggle.toggled.connect(self._update_status)
        self.mic_combo.currentIndexChanged.connect(self._update_status)
        self.cam_combo.currentIndexChanged.connect(self._sync_preview)
        sc.setWidget(holder)
        root.addWidget(sc, 2)
        self.settings_area = sc

    # ------------------------------------------------------------------ settings
    def _out_dir(self):
        return config.recordings_dir()

    def _choose_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Save recordings to", self._out_dir())
        if d:
            settings.set("recordings_dir", d)
            self._refresh_dir()

    def _refresh_dir(self):
        d = self._out_dir()
        self.dir_label.setText("Saved to  " + d)
        self.dir_label.setToolTip(d)

    def _load_settings(self):
        s = settings.get("recorder", {}) or {}
        self.screen_card.toggle.setChecked(s.get("screen", True))
        idx = self.mon_combo.findData(s.get("monitor", -1))
        if idx >= 0:
            self.mon_combo.setCurrentIndex(idx)
        self.method_combo.setCurrentIndex(max(0, self.method_combo.findData(s.get("method", "auto"))))
        self.mouse_t.setChecked(s.get("mouse", True))
        self.cam_card.toggle.setChecked(bool(s.get("webcam_on", False)))
        self.mic_card.toggle.setChecked(bool(s.get("mic_on", False)))
        if self.sys_card.toggle.isEnabled():
            self.sys_card.toggle.setChecked(s.get("system", True))
        self.cam_size.setValue(int(s.get("cam_size", 28)))
        for b in self.corner_seg.group.buttons():
            b.setChecked(b.property("key") == s.get("corner", "br"))
        for b in self.fps_seg.group.buttons():
            b.setChecked(b.property("key") == s.get("fps", 60))
        for b in self.quality_seg.group.buttons():
            b.setChecked(b.property("key") == s.get("quality", "high"))
        self.scale_combo.setCurrentIndex(max(0, self.scale_combo.findData(s.get("scale", "native"))))
        self.enc_combo.setCurrentIndex(max(0, self.enc_combo.findData(s.get("encoder", "auto"))))
        self.countdown_t.setChecked(s.get("countdown", True))
        self.hide_t.setChecked(s.get("hide", True))
        self.timeline_t.setChecked(s.get("timeline", True))
        self._refresh_dir()
        self._sync_preview()

    def _save_settings(self):
        settings.set("recorder", {
            "screen": self.screen_card.toggle.isChecked(), "monitor": self.mon_combo.currentData(),
            "method": self.method_combo.currentData(), "mouse": self.mouse_t.isChecked(),
            "webcam_on": self.cam_card.toggle.isChecked(), "webcam": self.cam_combo.currentData(),
            "mic_on": self.mic_card.toggle.isChecked(), "mic": self.mic_combo.currentData(),
            "system": self.sys_card.toggle.isChecked(), "cam_size": self.cam_size.value(),
            "corner": self.corner_seg.value(), "fps": self.fps_seg.value(), "quality": self.quality_seg.value(),
            "scale": self.scale_combo.currentData(), "encoder": self.enc_combo.currentData(),
            "countdown": self.countdown_t.isChecked(), "hide": self.hide_t.isChecked(),
            "timeline": self.timeline_t.isChecked()})

    def _devices_found(self, devs):
        self.devices = devs
        s = settings.get("recorder", {}) or {}
        for combo, kind, card, key, none_text in (
                (self.cam_combo, "video", self.cam_card, "webcam", "No webcam found"),
                (self.mic_combo, "audio", self.mic_card, "mic", "No microphone found")):
            combo.clear()
            names = devs.get(kind, [])
            for n in names:
                combo.addItem(n, n)
            if not names:
                combo.addItem(none_text, None)
                card.toggle.setChecked(False)
                card.toggle.setEnabled(False)
            else:
                card.toggle.setEnabled(True)
                i = combo.findData(s.get(key))
                combo.setCurrentIndex(max(0, i))
                if kind == "audio" and "mic_on" not in s:
                    card.toggle.setChecked(True)          # first time: voice on by default
        self._sync_preview()

    def _monitor(self):
        idx = self.mon_combo.currentData()
        for m in self.mons:
            if m["index"] == idx:
                return m
        return self.mons[0]

    def _sync_preview(self, *_):
        self.preview.monitor = self._monitor()
        self.preview.screen_on = self.screen_card.toggle.isChecked()
        self.preview.cam = self.cam_card.on() and self.cam_combo.currentData() is not None
        self.preview.corner = self.corner_seg.value()
        self.preview.cam_size = self.cam_size.value() / 100
        self.preview.grab()
        self.preview.update()
        self._update_status()

    def _update_status(self, *_):
        if getattr(self, 'state', 'idle') != "idle":
            return
        parts = []
        if self.screen_card.toggle.isChecked():
            parts.append("screen")
        if self.cam_card.on() and self.cam_combo.currentData():
            parts.append("webcam")
        if self.mic_card.on() and self.mic_combo.currentData():
            parts.append("microphone")
        if self.sys_card.on():
            parts.append("system audio")
        if not parts:
            self.status.setText("Turn on at least one source to record.")
        else:
            self.status.setText("Ready to record " + ", ".join(parts[:-1]) + (" and " if len(parts) > 1 else "") +
                                parts[-1] + ". Each one gets its own track on the timeline.")
        self.start_btn.setEnabled(bool(parts))

    def config(self):
        cfg = capture.CaptureConfig()
        cfg.screen = self.screen_card.toggle.isChecked()
        cfg.monitor = self._monitor()
        cfg.method = self.method_combo.currentData()
        cfg.fps = self.fps_seg.value()
        cfg.scale = self.scale_combo.currentData()
        cfg.quality = self.quality_seg.value()
        cfg.encoder = self.enc_combo.currentData()
        cfg.show_mouse = self.mouse_t.isChecked()
        cfg.webcam = self.cam_combo.currentData() if self.cam_card.on() else None
        cfg.mic = self.mic_combo.currentData() if self.mic_card.on() else None
        cfg.system_audio = self.sys_card.on()
        cfg.out_dir = self._out_dir()
        cfg.test = bool(os.environ.get("EASYCUT_RECORD_TEST"))
        return cfg

    # ------------------------------------------------------------------ recording
    def toggle_recording(self):
        if self.state == "idle":
            self.begin()
        elif self.state == "recording":
            self.finish()
        elif self.state == "countdown":
            self._cancel_countdown()

    def begin(self):
        cfg = self.config()
        if not (cfg.screen or cfg.webcam or cfg.mic or cfg.system_audio):
            return
        if not (cfg.screen or cfg.webcam or cfg.mic):
            QMessageBox.information(self, "Record", "System audio is recorded alongside the screen, webcam or "
                                                    "microphone - turn one of those on too.")
            return
        self._save_settings()
        self.cfg = cfg
        self._set_inputs_enabled(False)
        if self.hide_t.isChecked():
            self._hide_windows()
        if self.countdown_t.isChecked():
            self.state = "countdown"
            self.start_btn.setText("  Cancel")
            self.cd = Countdown(3)
            self.cd.finished.connect(self._really_start)
            self.cd.start()
        else:
            self._really_start()

    def _cancel_countdown(self):
        try:
            self.cd.t.stop()
            self.cd.hide()
            self.cd.deleteLater()
        except Exception:
            pass
        self.state = "idle"
        self._restore_windows()
        self._set_inputs_enabled(True)
        self.start_btn.setText("  Start recording")

    def _really_start(self):
        if self.state not in ("idle", "countdown"):
            return
        self.state = "starting"
        self.status.setText("Starting…")
        self.start_btn.setEnabled(False)
        self.rec = capture.Recorder(self.cfg)
        self.st = StartThread(self.rec)
        self.st.started_ok.connect(self._started)
        self.st.failed.connect(self._start_failed)
        self.st.start()

    def _started(self):
        self.state = "recording"
        self.start_btn.setEnabled(True)
        self.start_btn.setText("  Stop recording")
        icons.bind(self.start_btn, "stop", 16, "accent_text")
        self.bar = RecBar()
        self.bar.stopRequested.connect(self.finish)
        self.bar.place()
        self.bar.show()
        exclude_from_capture(self.bar)
        self.tick.start(500)
        how = {"dxgi": "game capture", "gdi": "compatible capture"}.get(self.rec.method, "")
        enc = {"libx264": "processor"}.get(self.rec.encoder, "graphics card")
        self.status.setText(f"Recording ({how}, encoding on the {enc}). Press {HOTKEY_TEXT} or Stop to finish."
                            if self.cfg.screen else f"Recording. Press {HOTKEY_TEXT} or Stop to finish.")

    def _start_failed(self, err):
        self.state = "idle"
        self._restore_windows()
        self._set_inputs_enabled(True)
        self.start_btn.setEnabled(True)
        self.start_btn.setText("  Start recording")
        self.status.setText("")
        msg = "The recording couldn't start."
        low = err.lower()
        if "video=" in low or "could not find video device" in low or "webcam" in low:
            msg += "\n\nThe webcam may be in use by another app - close it, or turn the webcam off here."
        elif "audio=" in low:
            msg += "\n\nThe microphone may be in use or unplugged."
        QMessageBox.warning(self, "Record", msg + ("\n\nDetails:\n" + err[-900:] if err else ""))

    def _tick(self):
        if self.rec is None:
            return
        self._blink ^= 1
        if self.bar is not None:
            self.bar.set_status(self.rec.elapsed, self.rec.fps, self.rec.size, self._blink)
        if self.rec.proc is not None and self.rec.proc.poll() is not None and self.state == "recording":
            self.status.setText("The recording stopped unexpectedly - saving what was captured.")
            self.finish()

    def finish(self):
        if self.state != "recording":
            return
        self.state = "stopping"
        self.tick.stop()
        if self.bar is not None:
            self.bar.hide()
            self.bar.deleteLater()
            self.bar = None
        self._restore_windows()
        self.start_btn.setEnabled(False)
        self.start_btn.setText("  Finishing…")
        self.sp = StopThread(self.rec)
        self.sp.status.connect(self.status.setText)
        self.sp.done.connect(self._finished)
        self.sp.start()

    def _finished(self, res):
        self.state = "idle"
        self._set_inputs_enabled(True)
        self.start_btn.setEnabled(True)
        self.start_btn.setText("  Start recording")
        icons.bind(self.start_btn, "record", 16, "accent_text")
        self.rec = None
        if not res.files:
            QMessageBox.warning(self, "Record", "Nothing was recorded.\n\n" + "\n".join(res.warnings))
            self._update_status()
            return
        self.status.setText(f"Saved {clock(res.duration)} to {self._out_dir()}" +
                            ("\n" + " ".join(res.warnings) if res.warnings else ""))
        opts = {"timeline": self.timeline_t.isChecked(), "corner": self.corner_seg.value(),
                "cam_size": self.cam_size.value() / 100}
        self.recorded.emit(res, opts)
        if self.timeline_t.isChecked():
            self.accept()

    def _set_inputs_enabled(self, on):
        self.settings_area.setEnabled(on)

    def _hide_windows(self):
        self.hidden_windows = []
        for w in (self.parent(), self):
            if w is not None and w.isVisible():
                self.hidden_windows.append(w)
        # minimise rather than hide, so the taskbar keeps an icon to come back to
        for w in self.hidden_windows:
            w.setWindowOpacity(0.0)
        QTimer.singleShot(60, lambda: [w.showMinimized() for w in self.hidden_windows if w is self.parent()])

    def _restore_windows(self):
        for w in self.hidden_windows:
            w.setWindowOpacity(1.0)
            if w.isMinimized():
                w.showNormal()
        self.hidden_windows = []
        self.raise_()
        self.activateWindow()

    # ------------------------------------------------------------------ closing
    def reject(self):
        if self.state in ("recording", "starting"):
            if QMessageBox.question(self, "Record", "Stop and keep the recording?") == \
                    QMessageBox.StandardButton.Yes:
                self.finish()
            return
        if self.state == "stopping":
            return
        if self.state == "countdown":
            self._cancel_countdown()
        super().reject()

    def done(self, r):
        self.hotkey.release()
        self.preview.timer.stop()
        self._save_settings()
        super().done(r)
