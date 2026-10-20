"""Easy-Cut main window."""
import copy
import json
import os
import threading
import time

from PyQt6.QtCore import Qt, QTimer, QElapsedTimer, QObject, pyqtSignal, QUrl, QEvent
from PyQt6.QtGui import QKeySequence, QShortcut, QDesktopServices, QColor
from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSplitter,
                             QFrame, QComboBox, QFileDialog, QMessageBox, QMenu, QApplication, QSlider,
                             QLineEdit, QPlainTextEdit, QAbstractSpinBox, QDialog)

from .. import __version__, APP_NAME, formats, media, project as proj, settings, theme, icons, extensions, updater
from .. import animations, render, catalog, textrender
from ..compositor import Compositor
from ..config import data_path, cache_dir, PROJECT_EXT, RELEASES_URL, GITHUB_URL, TKO_URL, TOPTRACKING_URL
from .inspector import Inspector
from .panels import Library
from .preview import PreviewPanel
from .render_dialog import RenderDialog
from .pack_dialog import PackDialog
from .theme_dialog import ThemeDialog
from .timeline import Timeline, TimelineScroll
from .widgets import icon_button, fmt_time

PREVIEW_SIZES = {"performance": (640, 360), "balanced": (960, 540), "quality": (1280, 720)}


class _Bridge(QObject):
    """Thread -> UI signals."""
    audioReady = pyqtSignal(str, str)
    updatesChecked = pyqtSignal(object, str)
    extInstalled = pyqtSignal(object, bool, str)
    appDownloaded = pyqtSignal(bytes, str, str)


class MainWindow(QMainWindow):
    def __init__(self, app, open_path=None):
        super().__init__()
        self.app = app
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(icons.app_icon())
        self.resize(1480, 920)
        self.setMinimumSize(1100, 700)
        self.project = proj.Project()
        self.history = proj.History(self.project)
        self.dirty = False
        self.playhead = 0.0
        self.playing = False
        self.play_until = None
        self.play_start_t = 0.0
        self.compositor = Compositor()
        self.bridge = _Bridge()
        self.bridge.audioReady.connect(self._audio_ready)
        self.bridge.updatesChecked.connect(self._updates_checked)
        self.bridge.extInstalled.connect(self._ext_installed)
        self.bridge.appDownloaded.connect(self._app_downloaded)
        self.audio_sig = None
        self.audio_path = None
        self.audio_building = False
        self.manifest_updates = None
        self._build_ui()
        self._init_audio()
        self._shortcuts()
        self.play_timer = QTimer(self)
        self.play_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.play_timer.timeout.connect(self._tick)
        self.clock = QElapsedTimer()
        self.preview_timer = QTimer(self, singleShot=True, interval=15, timeout=self.render_preview)
        self.audio_timer = QTimer(self, singleShot=True, interval=700, timeout=self._maybe_build_audio)
        self.autosave_timer = QTimer(self, interval=120000, timeout=self._autosave)
        self.autosave_timer.start()
        theme.notifier.changed.connect(self._theme_changed)
        app.installEventFilter(self)
        self.set_project(self.project)
        if open_path and os.path.isfile(open_path):
            if open_path.lower().endswith(PROJECT_EXT):
                QTimer.singleShot(50, lambda: self.open_project(open_path))
            else:
                QTimer.singleShot(50, lambda: self.import_paths([open_path], add_to_timeline=True))
        else:
            QTimer.singleShot(400, self._offer_recovery)
        if settings.get("check_updates", True):
            QTimer.singleShot(1500, self.check_updates)
        self._mark_session(open_=True)
        self.apply_chrome()

    # ================================================================== UI
    def _build_ui(self):
        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        v = QVBoxLayout(root)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        v.addWidget(self._top_bar())
        self.banner = self._update_banner()
        v.addWidget(self.banner)
        body = QWidget()
        bl = QVBoxLayout(body)
        bl.setContentsMargins(8, 8, 8, 8)
        bl.setSpacing(8)
        self.vsplit = QSplitter(Qt.Orientation.Vertical)
        self.vsplit.setChildrenCollapsible(False)
        self.hsplit = QSplitter(Qt.Orientation.Horizontal)
        self.hsplit.setChildrenCollapsible(False)
        self.library = Library()
        self.library.setMinimumWidth(self.library.rail_width() + 310)
        self.preview = PreviewPanel()
        self.inspector = Inspector()
        self.hsplit.addWidget(self.library)
        self.hsplit.addWidget(self.preview)
        self.hsplit.addWidget(self.inspector)
        self.hsplit.setStretchFactor(0, 0)
        self.hsplit.setStretchFactor(1, 1)
        self.hsplit.setStretchFactor(2, 0)
        self.hsplit.setSizes([450, 700, 340])
        self.vsplit.addWidget(self.hsplit)
        self.vsplit.addWidget(self._timeline_panel())
        self.vsplit.setSizes([560, 330])
        bl.addWidget(self.vsplit)
        v.addWidget(body, 1)
        self._wire()

    def _top_bar(self):
        from .chrome import DragBar, WindowDots
        bar = DragBar()
        bar.setObjectName("TopBar")
        bar.setFixedHeight(52)
        self.top_bar = bar
        h = QHBoxLayout(bar)
        h.setContentsMargins(12, 6, 12, 6)
        h.setSpacing(6)
        self.dots = WindowDots()
        self.dots.hide()
        h.addWidget(self.dots)
        logo = QLabel()
        self.logo = logo
        logo.setPixmap(icons.app_pixmap(64).scaled(30, 30, Qt.AspectRatioMode.KeepAspectRatio,
                                                    Qt.TransformationMode.SmoothTransformation))
        h.addWidget(logo)
        brand = QLabel("Easy-Cut")
        brand.setObjectName("Brand")
        self.brand = brand
        h.addWidget(brand)
        h.addSpacing(10)
        self.menu_btn = QPushButton("File")
        self.menu_btn.setObjectName("Flat")
        self.menu_btn.setMenu(self._file_menu())
        h.addWidget(self.menu_btn)
        self.view_btn = QPushButton("View")
        self.view_btn.setObjectName("Flat")
        self.view_btn.setMenu(self._view_menu())
        h.addWidget(self.view_btn)
        self.help_btn = QPushButton("Help")
        self.help_btn.setObjectName("Flat")
        self.help_btn.setMenu(self._help_menu())
        h.addWidget(self.help_btn)
        h.addSpacing(12)
        self.undo_btn = icon_button("undo", "Undo (Ctrl+Z)", 18)
        self.redo_btn = icon_button("redo", "Redo (Ctrl+Y)", 18)
        self.undo_btn.clicked.connect(self.undo)
        self.redo_btn.clicked.connect(self.redo)
        h.addWidget(self.undo_btn)
        h.addWidget(self.redo_btn)
        h.addStretch(1)
        title = QWidget()
        tv = QVBoxLayout(title)
        tv.setContentsMargins(0, 0, 0, 0)
        tv.setSpacing(0)
        self.name_label = QLabel("Untitled")
        self.name_label.setObjectName("H2")
        self.name_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.name_sub = QLabel("")
        self.name_sub.setObjectName("Dim")
        self.name_sub.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.name_sub.hide()
        tv.addWidget(self.name_label)
        tv.addWidget(self.name_sub)
        h.addWidget(title)
        h.addStretch(1)
        h.addWidget(QLabel("Canvas"))
        self.aspect_combo = QComboBox()
        for k in formats.ASPECT_ORDER:
            self.aspect_combo.addItem(formats.aspect_label(k), k)
        self.aspect_combo.setMinimumWidth(230)
        self.aspect_combo.currentIndexChanged.connect(self._aspect_from_combo)
        h.addWidget(self.aspect_combo)
        self.record_btn = QPushButton("  Record")
        icons.bind(self.record_btn, "record", 16, "#ff453a")
        self.record_btn.setToolTip("Record your screen, gameplay, webcam and audio (Ctrl+R)")
        self.record_btn.clicked.connect(self.show_recorder)
        h.addWidget(self.record_btn)
        self.theme_btn = icon_button("theme", "Appearance & themes", 20)
        self.theme_btn.clicked.connect(self.show_themes)
        h.addWidget(self.theme_btn)
        self.export_btn = QPushButton("  Export")
        self.export_btn.setObjectName("Primary")
        icons.bind(self.export_btn, "export", 16, "accent_text")
        self.export_btn.setToolTip("Export your video (Ctrl+E)")
        self.export_btn.clicked.connect(self.export)
        h.addWidget(self.export_btn)
        return bar

    def _update_banner(self):
        f = QFrame()
        f.setObjectName("Card")
        h = QHBoxLayout(f)
        h.setContentsMargins(14, 6, 10, 6)
        self.banner_label = QLabel("")
        h.addWidget(self.banner_label, 1)
        self.banner_btn = QPushButton("Update")
        self.banner_btn.setObjectName("Primary")
        self.banner_btn.clicked.connect(self._banner_action)
        h.addWidget(self.banner_btn)
        x = icon_button("close", "Hide", 14)
        x.clicked.connect(f.hide)
        h.addWidget(x)
        f.hide()
        return f

    def _file_menu(self):
        m = QMenu(self)
        m.addAction("New project", QKeySequence("Ctrl+N"), self.new_project)
        m.addAction("Open project…", QKeySequence("Ctrl+O"), self.open_dialog)
        self.recent_menu = m.addMenu("Open recent")
        self.recent_menu.aboutToShow.connect(self._fill_recent)
        m.addSeparator()
        m.addAction("Save", QKeySequence("Ctrl+S"), self.save)
        m.addAction("Save as…", QKeySequence("Ctrl+Shift+S"), self.save_as)
        m.addSeparator()
        m.addAction("Import media…", QKeySequence("Ctrl+I"), self.import_dialog)
        m.addAction("Record screen, webcam && audio…", QKeySequence("Ctrl+R"), self.show_recorder)
        m.addAction("Export video…", QKeySequence("Ctrl+E"), self.export)
        m.addSeparator()
        m.addAction("Exit", self.close)
        return m

    def _view_menu(self):
        m = QMenu(self)
        m.addAction("Appearance & themes…", self.show_themes)
        pq = m.addMenu("Preview quality")
        for key, label in (("performance", "Performance (lightest)"), ("balanced", "Balanced"),
                           ("quality", "High quality")):
            a = pq.addAction(label, lambda k=key: self._set_preview_quality(k))
            a.setCheckable(True)
            a.setChecked(settings.get("preview_quality") == key)
            a.setData(key)
        self.pq_menu = pq
        m.addSeparator()
        a = m.addAction("🍏 Mode: use the built-in title bar")
        a.setCheckable(True)
        a.setChecked(settings.get("mac_titlebar", True))
        a.toggled.connect(lambda v: (settings.set("mac_titlebar", v), self.apply_chrome()))
        m.addSeparator()
        m.addAction("Zoom timeline to fit", lambda: self.timeline.zoom_to_fit())
        m.addAction("Extensions", self.show_extensions)
        return m

    def _help_menu(self):
        m = QMenu(self)
        m.addAction("Check for updates…", lambda: self.check_updates(manual=True))
        a = m.addAction("Check for updates on startup")
        a.setCheckable(True)
        a.setChecked(settings.get("check_updates", True))
        a.toggled.connect(lambda v: settings.set("check_updates", v))
        a = m.addAction("Update extensions automatically")
        a.setCheckable(True)
        a.setChecked(settings.get("auto_update_extensions", False))
        a.toggled.connect(lambda v: settings.set("auto_update_extensions", v))
        m.addSeparator()
        m.addAction("Keyboard shortcuts", self.show_shortcuts)
        m.addAction("Open app data folder", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(data_path("x")[:-2])))
        m.addSeparator()
        m.addAction(f"About {APP_NAME}", self.show_about)
        return m

    def _timeline_panel(self):
        panel = QFrame()
        panel.setObjectName("Panel")
        v = QVBoxLayout(panel)
        v.setContentsMargins(6, 4, 6, 4)
        v.setSpacing(2)
        tb = QHBoxLayout()
        tb.setSpacing(2)
        self.split_btn = icon_button("split", "Split at playhead (S / Ctrl+B)", 18)
        self.split_btn.clicked.connect(self.split)
        self.del_btn = icon_button("trash", "Delete (Del)", 18)
        self.del_btn.clicked.connect(self.delete_selected)
        self.dup_btn = icon_button("plus", "Duplicate (Ctrl+D)", 18)
        self.dup_btn.clicked.connect(self.duplicate)
        self.text_btn = icon_button("text", "Add text at playhead", 18)
        self.text_btn.clicked.connect(lambda: self.add_text({}))
        for b in (self.split_btn, self.del_btn, self.dup_btn, self.text_btn):
            tb.addWidget(b)
        tb.addSpacing(10)
        self.snap_btn = icon_button("magnet", "Snapping (N)", 18, checkable=True)
        self.snap_btn.setChecked(settings.get("snap", True))
        self.snap_btn.toggled.connect(self._snap_toggled)
        tb.addWidget(self.snap_btn)
        tb.addStretch(1)
        self.tl_info = QLabel("")
        self.tl_info.setObjectName("Dim")
        tb.addWidget(self.tl_info)
        tb.addSpacing(10)
        zo = icon_button("zoom_out", "Zoom out (-)", 16)
        zi = icon_button("zoom_in", "Zoom in (+)", 16)
        fit = icon_button("fit", "Zoom to fit", 16)
        self.zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self.zoom_slider.setRange(0, 1000)
        self.zoom_slider.setFixedWidth(130)
        tb.addWidget(zo)
        tb.addWidget(self.zoom_slider)
        tb.addWidget(zi)
        tb.addWidget(fit)
        v.addLayout(tb)
        self.timeline = Timeline()
        self.timeline.snap = self.snap_btn.isChecked()
        v.addWidget(self.timeline, 1)
        self.tl_scroll = TimelineScroll(self.timeline)
        v.addWidget(self.tl_scroll)
        zo.clicked.connect(lambda: self.timeline.set_zoom(self.timeline.pps / 1.4))
        zi.clicked.connect(lambda: self.timeline.set_zoom(self.timeline.pps * 1.4))
        fit.clicked.connect(lambda: self.timeline.zoom_to_fit())
        self.zoom_slider.valueChanged.connect(self._zoom_slider_moved)
        self.timeline.zoomChanged.connect(self._sync_zoom_slider)
        return panel

    def _wire(self):
        tl = self.timeline
        tl.seekRequested.connect(self.seek)
        tl.selectionChanged.connect(self._selection_changed)
        tl.edited.connect(self.commit)
        tl.liveChanged.connect(self._live_changed)
        tl.dropMedia.connect(self._drop_media)
        tl.contextAction.connect(self._context_action)
        ins = self.inspector
        ins.changed.connect(self.apply_fields)
        ins.committed.connect(self.commit)
        ins.speedChanged.connect(self._speed_changed)
        ins.pickColor.connect(self._start_pick)
        ins.normalizeRequested.connect(self.normalize_selected)
        ins.rebuild_extension_effects()
        lib = self.library
        lib.media.importRequested.connect(self.import_dialog)
        lib.explorer.addToTimeline.connect(lambda paths: self.import_paths(paths, add_to_timeline=True))
        lib.explorer.addToMedia.connect(self._explorer_add_media)
        lib.explorer.fullViewToggled.connect(self.set_explorer_full)
        lib.explorer.minimiseRequested.connect(lambda: lib.set_collapsed(True))
        lib.collapsedChanged.connect(self._library_collapsed)
        lib.media.addRequested.connect(lambda paths: self.add_to_timeline(paths))
        lib.media.removeRequested.connect(self._remove_media)
        lib.text.addText.connect(self.add_text)
        lib.filters.filterChosen.connect(self._filter_chosen)
        lib.filters.amountChanged.connect(lambda v: self.apply_fields({"filter_amount": v}, visual_only=True))
        lib.filters.amountDone.connect(lambda: self.commit("Filter intensity"))
        lib.filters.applyAll.connect(self._filter_all)
        lib.anims.animChosen.connect(self._anim_chosen)
        lib.anims.durationChanged.connect(lambda w, v: self.apply_fields({f"anim_{w}_dur": v}, visual_only=True))
        lib.anims.durationDone.connect(lambda: self.commit("Animation length"))
        lib.effects.effectChosen.connect(self._effect_chosen)
        lib.transitions.transitionChosen.connect(self._transition_chosen)
        lib.transitions.durationChanged.connect(self._transition_duration)
        lib.transitions.durationDone.connect(lambda: self.commit("Transition length"))
        lib.text.styleChosen.connect(self._style_chosen)
        lib.text.fontChosen.connect(self._font_chosen)
        for sig in lib.locked_signals():
            sig.connect(self.request_item)
        ext = lib.extensions
        ext.getRequested.connect(lambda pid: self.get_packs([pid]))
        ext.getAllRequested.connect(self.get_packs)
        ext.installFile.connect(self.install_extension_file)
        ext.removeRequested.connect(self.remove_extension)
        ext.refreshRequested.connect(lambda: self.check_updates(manual=True))
        pv = self.preview
        pv.btn_play.clicked.connect(self.toggle_play)
        pv.btn_start.clicked.connect(lambda: self.seek(0))
        pv.btn_end.clicked.connect(lambda: self.seek(self.project.duration()))
        pv.btn_back.clicked.connect(lambda: self.step(-1))
        pv.btn_fwd.clicked.connect(lambda: self.step(1))
        pv.canvas.transformLive.connect(self._canvas_transform)
        pv.canvas.transformDone.connect(lambda: self.commit("Move clip"))
        pv.canvas.colorPicked.connect(self._color_picked)
        pv.canvas.filesDropped.connect(lambda paths: self.import_paths(paths, add_to_timeline=True))
        pv.canvas.importRequested.connect(self.import_dialog)

    def _shortcuts(self):
        for seq, fn in (("Ctrl+Z", self.undo), ("Ctrl+Y", self.redo), ("Ctrl+Shift+Z", self.redo),
                        ("Ctrl+N", self.new_project), ("Ctrl+O", self.open_dialog), ("Ctrl+S", self.save),
                        ("Ctrl+Shift+S", self.save_as), ("Ctrl+I", self.import_dialog), ("Ctrl+E", self.export),
                        ("Ctrl+R", self.show_recorder),
                        ("Ctrl+D", self.duplicate), ("Ctrl+B", self.split), ("Ctrl+A", self.select_all),
                        ("Ctrl+=", lambda: self.timeline.set_zoom(self.timeline.pps * 1.4)),
                        ("Ctrl+-", lambda: self.timeline.set_zoom(self.timeline.pps / 1.4))):
            sc = QShortcut(QKeySequence(seq), self)
            sc.activated.connect(fn)

    def eventFilter(self, obj, ev):
        """Single-key shortcuts that must not fire while typing in a text box."""
        if ev.type() == QEvent.Type.KeyPress and self.isActiveWindow() and QApplication.activeModalWidget() is None:
            fw = QApplication.focusWidget()
            typing = isinstance(fw, (QLineEdit, QPlainTextEdit, QAbstractSpinBox)) or \
                (isinstance(fw, QComboBox) and fw.isEditable())
            if not typing and not (ev.modifiers() & (Qt.KeyboardModifier.ControlModifier |
                                                     Qt.KeyboardModifier.AltModifier)):
                k = ev.key()
                handled = True
                if k == Qt.Key.Key_Space:
                    self.toggle_play()
                elif k == Qt.Key.Key_S:
                    self.split()
                elif k in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
                    self.delete_selected()
                elif k == Qt.Key.Key_Left:
                    self.step(-10 if ev.modifiers() & Qt.KeyboardModifier.ShiftModifier else -1)
                elif k == Qt.Key.Key_Right:
                    self.step(10 if ev.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1)
                elif k == Qt.Key.Key_Home:
                    self.seek(0)
                elif k == Qt.Key.Key_End:
                    self.seek(self.project.duration())
                elif k == Qt.Key.Key_N:
                    self.snap_btn.toggle()
                elif k in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
                    self.timeline.set_zoom(self.timeline.pps * 1.4)
                elif k == Qt.Key.Key_Minus:
                    self.timeline.set_zoom(self.timeline.pps / 1.4)
                elif k == Qt.Key.Key_Escape:
                    self.timeline.selected = []
                    self._selection_changed([])
                    self.timeline.update()
                else:
                    handled = False
                if handled:
                    return True
        return super().eventFilter(obj, ev)

    # ================================================================== project state
    def set_project(self, p, keep_history=False):
        self.stop()
        self.project = p
        if not keep_history:
            self.history = proj.History(p)
        self.compositor.prune(p)
        self.timeline.set_project(p)
        self.library.media.set_media([m for m in p.media])
        self._sync_aspect_combo()
        self._selection_changed(self.timeline.selected)
        self.refresh()
        self.tl_scroll.sync()
        self._sync_zoom_slider()

    def refresh(self, preview=True):
        self.timeline.update()
        if theme.C.get("apple"):
            self.name_label.setText(self.project.name or "Untitled")
            self.name_sub.setText("Edited" if self.dirty else ("Saved" if self.project.path else "Not saved"))
        else:
            self.name_label.setText(("● " if self.dirty else "") + (self.project.name or "Untitled"))
        self.setWindowTitle(f"{self.project.name or 'Untitled'}{' *' if self.dirty else ''} - {APP_NAME}")
        self.undo_btn.setEnabled(self.history.can_undo())
        self.redo_btn.setEnabled(self.history.can_redo())
        d = self.project.duration()
        if self.playhead > d:
            self.playhead = d
        self.preview.set_time(self.playhead, d, self.project.fps)
        n = len(self.project.clips)
        self.tl_info.setText(f"{n} clip{'s' if n != 1 else ''} · {fmt_time(d).split('.')[0]}")
        self.preview.canvas.empty = not self.project.clips
        w, h = formats.canvas_size(self.project.aspect)
        self.preview.info.setText(f"{formats.ASPECTS[self.project.aspect][1]} · {self.project.fps} fps")
        self.export_btn.setEnabled(bool(self.project.clips))
        if preview:
            self.schedule_preview()

    def commit(self, label="Edit"):
        if self.history.commit(self.project):
            self.dirty = True
            self.audio_timer.start()
        self.compositor.prune(self.project)
        self.refresh()
        self.tl_scroll.sync()

    def undo(self):
        p = self.history.undo()
        if p is not None:
            self._restore(p)

    def redo(self):
        p = self.history.redo()
        if p is not None:
            self._restore(p)

    def _restore(self, p):
        p.path = self.project.path
        p.name = self.project.name
        sel = list(self.timeline.selected)
        self.project = p
        self.timeline.set_project(p)
        self.timeline.selected = [s for s in sel if p.clip(s)]
        self.library.media.set_media(p.media)
        self._sync_aspect_combo()
        self._selection_changed(self.timeline.selected)
        self.dirty = True
        self.audio_timer.start()
        self.refresh()

    # ================================================================== selection & editing
    def selected_clips(self):
        return [c for c in (self.project.clip(i) for i in self.timeline.selected) if c]

    def _selection_changed(self, ids):
        clips = self.selected_clips()
        self.inspector.load(clips)
        first = clips[0] if clips else None
        vis = first if first and first.is_visual else None
        self.library.filters.sync(vis)
        self.library.anims.sync(vis)
        self.library.transitions.sync(vis)
        self.library.text.sync(first)
        self.schedule_preview()

    def apply_fields(self, fields: dict, visual_only=False):
        clips = self.selected_clips()
        if visual_only:
            clips = [c for c in clips if c.is_visual]
        for c in clips:
            for k, v in fields.items():
                if k in ("volume", "muted") and not c.has_sound:
                    continue
                if k == "stabilize" and c["kind"] != "video":
                    continue
                c[k] = copy.deepcopy(v)
        self.timeline.update()
        self.schedule_preview()

    def _speed_changed(self, v):
        for c in self.selected_clips():
            if c["kind"] in ("video", "audio"):
                self.project.set_speed(c, v)
                # don't run into the next clip on the track
                nxt = min([o["start"] for o in self.project.clips_on(c["track"])
                           if o["id"] != c["id"] and o["start"] > c["start"] + 1e-6], default=1e9)
                if c.end > nxt:
                    c["duration"] = max(0.05, nxt - c["start"])
        self.refresh()

    def _canvas_transform(self, x, y, s):
        c = self._selected_visual()
        if c is None:
            return
        c["x"], c["y"], c["scale"] = x, y, s
        self.inspector.load(self.selected_clips())
        self.schedule_preview()

    def _selected_visual(self):
        for c in self.selected_clips():
            if c.is_visual:
                return c
        return None

    def _filter_chosen(self, fid):
        clips = [c for c in self.selected_clips() if c.is_visual]
        if not clips:
            self.toast("Select a clip on the timeline first, then choose a filter.")
            return
        self.apply_fields({"filter": fid}, visual_only=True)
        self.commit("Filter")
        self.inspector.load(self.selected_clips())

    def _filter_all(self):
        cur = self._selected_visual()
        fid = cur["filter"] if cur else "none"
        amt = cur["filter_amount"] if cur else 1.0
        for c in self.project.clips:
            if c.is_visual and c["kind"] != "text":
                c["filter"], c["filter_amount"] = fid, amt
        self.commit("Filter all clips")

    def _anim_chosen(self, which, aid):
        if not [c for c in self.selected_clips() if c.is_visual]:
            self.toast("Select a clip on the timeline first, then choose an animation.")
            self.library.anims.sync(None)
            return
        if which == "in" and aid != "none" and any(c.get("trans_in", "none") != "none"
                                                    for c in self.selected_clips()):
            self.apply_fields({"trans_in": "none"}, visual_only=True)
            self.toast("The clip's transition was removed - a clip can have a transition or an in-animation.")
        self.apply_fields({f"anim_{which}": aid}, visual_only=True)
        self.commit("Animation")
        self.library.transitions.sync(self._selected_visual())
        c = self._selected_visual()
        if c:
            self.seek(c["start"] if which == "in" else max(c["start"], c.end - c[f"anim_{which}_dur"] - 0.05))
            self.play_range(c["start"], min(c.end, c["start"] + c["anim_in_dur"] + 0.4)) if which == "in" else \
                self.play_range(max(c["start"], c.end - c["anim_out_dur"] - 0.4), c.end)

    def _transition_chosen(self, tid):
        clips = [c for c in self.selected_clips() if c.is_visual]
        if not clips:
            self.toast("Select the clip the transition should lead into, then choose a transition.")
            self.library.transitions.sync(None)
            return
        c = clips[0]
        if tid != "none" and c["start"] < 0.05:
            self.toast("This clip is at the very start - transitions play over the clip before it, so move it "
                       "later or pick a clip further along.")
        if tid != "none" and c.get("anim_in", "none") != "none":
            self.apply_fields({"anim_in": "none"}, visual_only=True)
            self.toast("The clip's in-animation was replaced by the transition.")
        self.apply_fields({"trans_in": tid}, visual_only=True)
        self.commit("Transition")
        self.library.anims.sync(c)
        if tid != "none":
            pre = animations.pre_roll(c)
            self.play_range(max(0.0, c["start"] - pre - 0.3), min(c.end, c["start"] + 0.4))

    def _transition_duration(self, v):
        self.apply_fields({"trans_dur": v}, visual_only=True)
        self.timeline.update()

    def _text_clips(self):
        return [c for c in self.selected_clips() if c["kind"] == "text"]

    def _style_chosen(self, sid):
        if not self._text_clips():
            self.add_text({"text_style": sid, "text": textrender.get_style(sid).name, "font_size": 110})
            return
        for c in self._text_clips():
            c["text_style"] = sid
        self.commit("Text style")
        self.inspector.load(self.selected_clips())
        self.schedule_preview()

    def _font_chosen(self, fid):
        f = textrender.FONTS.get(fid)
        if f is None:
            return
        if not self._text_clips():
            self.add_text({"font": f["family"], "text": f["name"], "font_size": 110, "bold": False})
            return
        for c in self._text_clips():
            c["font"] = f["family"]
        self.commit("Font")
        self.inspector.load(self.selected_clips())
        self.schedule_preview()

    # ------------------------------------------------------------------ packs
    def request_item(self, kind, item_id):
        """A locked item was clicked: offer its pack, then use the item straight away."""
        which = None
        if ":" in kind:
            kind, which = kind.split(":", 1)
        pack = catalog.pack_for(kind, item_id)
        if pack is None:
            return
        name = next((it.get("name") for it in pack.get("items", []) if it["id"] == item_id), item_id)
        dlg = PackDialog([pack["id"]], item_name=name, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self._packs_installed(dlg.installed_ids, dlg.restart_ids)
        if pack["id"] in dlg.restart_ids:
            return
        self.use_item(kind, item_id, which)

    def use_item(self, kind, item_id, which=None):
        if kind == "filter":
            if self._selected_visual():
                self._filter_chosen(item_id)
        elif kind == "transition":
            if self._selected_visual():
                self._transition_chosen(item_id)
        elif kind == "animation":
            if self._selected_visual():
                self._anim_chosen(which or "in", item_id)
        elif kind == "effect":
            if self.selected_clips():
                self._effect_chosen("fx:" + item_id)
        elif kind == "text_style":
            self._style_chosen(item_id)
        elif kind == "font":
            self._font_chosen(item_id)

    def get_packs(self, pack_ids):
        pack_ids = [p for p in pack_ids if p]
        if not pack_ids:
            return
        dlg = PackDialog(pack_ids, parent=self, autostart=True)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._packs_installed(dlg.installed_ids, dlg.restart_ids)

    def _packs_installed(self, done, restart):
        self._restart_packs = set(getattr(self, "_restart_packs", set())) | set(restart)
        updates = [e for e in (self.manifest_updates or {}).get("extensions", []) if e["id"] not in done]
        if self.manifest_updates:
            self.manifest_updates["extensions"] = updates
        self._rebuild_libraries()
        self.library.extensions.populate(updates, self._restart_packs)
        names = [(catalog.pack(p) or {}).get("name", p) for p in done]
        if restart:
            self.toast("Updated packs finish installing the next time you open Easy-Cut.", 8000)
        elif names:
            self.toast(f"{', '.join(names)} installed - enjoy!", 6000)

    def _effect_chosen(self, key):
        clips = self.selected_clips()
        if not clips:
            self.toast("Select a clip on the timeline first, then choose an effect.")
            return
        c = clips[0]
        if key == "speed":
            if c["kind"] not in ("video", "audio"):
                self.toast("Speed works on video and audio clips.")
                return
            self.inspector.show_tab("Speed")
            return
        if not c.is_visual:
            self.toast("That effect works on video, photo and text clips.")
            return
        if key == "chroma" and not c.get("chroma"):
            self.apply_fields({"chroma": True}, visual_only=True)
            self.commit("Chroma key")
        if key == "stabilize":
            if c["kind"] != "video":
                self.toast("Stabilization works on video clips.")
                return
            if not c.get("stabilize"):
                self.apply_fields({"stabilize": True})
                self.commit("Stabilization")
        if key.startswith("fx:"):
            eid = key[3:]
            fx = [f for f in c.get("fx", []) if f.get("id") != eid] + [{"id": eid, "amount": 1.0}]
            self.apply_fields({"fx": fx}, visual_only=True)
            self.commit("Effect")
        self.inspector.load(self.selected_clips())
        self.inspector.show_tab("Effects")

    def normalize_selected(self):
        """Set each selected clip's volume so its loudest peak sits at -1 dB."""
        clips = [c for c in self.selected_clips() if c.has_sound]
        if not clips:
            return
        self.toast("Measuring loudness…")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            for c in clips:
                peak = media.peak_db(c["path"], c["in_point"], c.source_span())
                if peak is None:
                    continue
                c["volume"] = max(0.0, min(2.0, 10 ** ((-1.0 - peak) / 20)))
        finally:
            QApplication.restoreOverrideCursor()
        self.commit("Normalize")
        self.inspector.load(self.selected_clips())
        self.toast("Normalized - the loudest moment now peaks at -1 dB.")

    def _start_pick(self):
        if self._selected_visual() is None:
            return
        self.stop()
        self.preview.canvas.picking = True
        self.preview.canvas.setCursor(Qt.CursorShape.CrossCursor)
        self.preview.canvas.setFocus()
        self.preview.canvas.update()

    def _color_picked(self, fx, fy):
        c = self._selected_visual()
        if c is None:
            return
        W, H = self.preview_size()
        tmp = proj.Project.from_dict(self.project.to_dict())
        tc = tmp.clip(c["id"])
        tc["chroma"] = False
        frame = self.compositor.compose(tmp, self.playhead, W, H)
        x = min(W - 1, max(0, int(fx * W)))
        y = min(H - 1, max(0, int(fy * H)))
        b, g, r = [int(v) for v in frame[y, x]]
        col = QColor(r, g, b).name()
        self.apply_fields({"chroma_color": col, "chroma": True}, visual_only=True)
        self.commit("Pick key colour")
        self.inspector.load(self.selected_clips())

    def _live_changed(self):
        self.schedule_preview()
        self.inspector.load(self.selected_clips()) if self.timeline.drag and \
            self.timeline.drag.get("mode") != "playhead" else None

    def select_all(self):
        self.timeline.selected = [c["id"] for c in self.project.clips]
        self._selection_changed(self.timeline.selected)
        self.timeline.update()

    def split(self):
        t = self.playhead
        targets = self.selected_clips() or [c for c in self.project.clips if c["start"] < t < c.end]
        made = []
        for c in targets:
            r = self.project.split(c, t)
            if r is not None:
                made.append(r)
        if made:
            self.timeline.selected = [made[0]["id"]]
            self._selection_changed(self.timeline.selected)
            self.commit("Split")

    def delete_selected(self):
        clips = self.selected_clips()
        if not clips:
            return
        for c in clips:
            self.project.remove(c)
        self.timeline.selected = []
        self._selection_changed([])
        self.commit("Delete")

    def duplicate(self):
        clips = self.selected_clips()
        new = []
        for c in clips:
            d = proj.Clip(copy.deepcopy(dict(c)))
            d["id"] = proj.new_id()
            d = self.project.place(d, preferred_track=c["track"], at=c.end)
            new.append(d["id"])
        if new:
            self.timeline.selected = new
            self._selection_changed(new)
            self.commit("Duplicate")

    def _context_action(self, action):
        clips = self.selected_clips()
        if action == "split":
            self.split()
        elif action == "delete":
            self.delete_selected()
        elif action == "duplicate":
            self.duplicate()
        elif action == "reset_effects":
            keep = ("id", "kind", "path", "name", "track", "start", "duration", "in_point", "source_duration",
                    "has_audio", "has_video", "src_w", "src_h", "sample_rate", "text", "font", "font_size",
                    "text_color", "bold", "text_bg", "text_bg_color", "text_outline", "text_style", "speed")
            for c in clips:
                fresh = proj.DEFAULT_CLIP
                for k, v in fresh.items():
                    if k not in keep:
                        c[k] = copy.deepcopy(v)
            self.commit("Reset effects")
            self._selection_changed(self.timeline.selected)
        elif action in ("fit", "fill"):
            self.apply_fields({"fit": action, "scale": 1.0, "x": 0.0, "y": 0.0}, visual_only=True)
            self.commit("Fit")
            self._selection_changed(self.timeline.selected)
        elif action == "add_video_track":
            self.project.add_track("video")
            self.commit("Add track")
        elif action == "add_audio_track":
            self.project.add_track("audio")
            self.commit("Add track")
        elif action == "remove_track":
            ti = getattr(self.timeline, "_ctx_track", -1)
            if ti >= 0:
                kind = self.project.tracks[ti]["type"]
                if len(self.project.tracks_of(kind)) <= 1:
                    self.toast("You need at least one track of each type.")
                    return
                self.project.remove_track(ti)
                self.commit("Remove track")
        elif action == "close_gaps":
            ti = getattr(self.timeline, "_ctx_track", -1)
            if ti >= 0:
                self.project.ripple_close(ti)
                self.commit("Close gaps")
        elif action == "detach_audio":
            made = [self.project.detach_audio(c) for c in clips]
            made = [m for m in made if m]
            if made:
                self.timeline.selected = [made[0]["id"]]
                self._selection_changed(self.timeline.selected)
                self.commit("Detach audio")
                self.toast("Audio moved to its own track - edit it separately from the picture.")
        elif action == "edit_transition":
            self.library.show("transitions")
        elif action == "remove_transition":
            self.apply_fields({"trans_in": "none"}, visual_only=True)
            self.commit("Remove transition")
            self._selection_changed(self.timeline.selected)
        elif action == "focus_inspector":
            self.inspector.setFocus()

    # ------------------------------------------------------------------ library panel size / explorer full view
    def _library_collapsed(self, on):
        if on:
            if getattr(self, "_explorer_full", False):
                self.library.explorer.set_full(False)
            self._lib_sizes = self.hsplit.sizes()
            rw = self.library.rail_width()
            self.library.setMinimumWidth(rw)
            self.library.setMaximumWidth(rw)
            sizes = self.hsplit.sizes()
            spare = sizes[0] - rw
            self.hsplit.setSizes([rw, sizes[1] + spare, sizes[2]])
        else:
            self.library.setMaximumWidth(16777215)
            self.library.setMinimumWidth(self.library.rail_width() + 310)
            if getattr(self, "_lib_sizes", None):
                self.hsplit.setSizes(self._lib_sizes)

    def set_explorer_full(self, on):
        """Give the Explorer the whole workspace above the timeline (the timeline stays, for dragging)."""
        if on == getattr(self, "_explorer_full", False):
            return
        self._explorer_full = on
        if on:
            self._full_sizes = self.hsplit.sizes()
            self.library.show("explorer")
            self.preview.hide()
            self.inspector.hide()
        else:
            self.preview.show()
            self.inspector.show()
            if getattr(self, "_full_sizes", None):
                self.hsplit.setSizes(self._full_sizes)

    def _explorer_add_media(self, paths):
        self.import_paths(paths)
        self.toast(f"Added {len(paths)} file{'s' if len(paths) != 1 else ''} to Media.")

    def _snap_toggled(self, v):
        self.timeline.snap = v
        settings.set("snap", v)

    # ================================================================== media
    def import_dialog(self):
        exts = " ".join("*" + e for e in sorted(media.VIDEO_EXTS | media.AUDIO_EXTS | media.IMAGE_EXTS))
        paths, _ = QFileDialog.getOpenFileNames(self, "Import media", settings.get("last_import_dir") or
                                                os.path.expanduser("~"), f"Media ({exts});;All files (*)")
        if paths:
            settings.set("last_import_dir", os.path.dirname(paths[0]))
            self.import_paths(paths)

    def import_paths(self, paths, add_to_timeline=False, at=None, track=None):
        good = []
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            for p in paths:
                if p.lower().endswith(PROJECT_EXT):
                    QApplication.restoreOverrideCursor()
                    self.open_project(p)
                    return
                if not media.media_kind(p) or not os.path.isfile(p):
                    continue
                if p not in self.project.media:
                    self.project.media.append(p)
                self.library.media.add(p)
                good.append(p)
        finally:
            QApplication.restoreOverrideCursor()
        skipped = len(paths) - len(good)
        if skipped:
            self.toast(f"{skipped} file{'s were' if skipped > 1 else ' was'} not a supported video, photo or audio file.")
        if good and add_to_timeline:
            self.add_to_timeline(good, at=at, track=track)
        elif good:
            self.dirty = True
            self.refresh(preview=False)

    def add_to_timeline(self, paths, at=None, track=None):
        added = []
        was_empty = not self.project.clips
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            for p in paths:
                if not os.path.exists(p):
                    continue
                if p not in self.project.media:
                    self.project.media.append(p)
                    self.library.media.add(p)
                info = media.probe(p)
                if not info.kind or (info.kind == "video" and not info.has_video and not info.has_audio):
                    continue
                if was_empty and not added and info.kind in ("video", "image") and info.width and info.height:
                    self._auto_aspect(info.width, info.height)
                clip = self.project.clip_from_media(info)
                pref = track if track is not None and track >= 0 and \
                    self.project.tracks[track]["type"] == ("audio" if info.kind == "audio" else "video") else None
                if at is None and pref is None:
                    self.project.place(clip)
                else:
                    self.project.place(clip, preferred_track=pref, at=at if at is not None else None)
                    if at is not None:
                        at = clip.end
                added.append(clip["id"])
        finally:
            QApplication.restoreOverrideCursor()
        if added:
            self.timeline.selected = [added[-1]]
            self._selection_changed(self.timeline.selected)
            self.commit("Add media")
            if was_empty:
                QTimer.singleShot(0, self.timeline.zoom_to_fit)

    # ================================================================== recording
    def show_recorder(self):
        from .recorder import RecorderDialog
        if getattr(self, "_recorder", None) is not None and self._recorder.isVisible():
            self._recorder.raise_()
            self._recorder.activateWindow()
            return
        self._recorder = RecorderDialog(self)
        self._recorder.recorded.connect(self.import_recording)
        self._recorder.finished.connect(lambda _r: setattr(self, "_recorder", None))
        self._recorder.show()

    def import_recording(self, res, opts=None):
        """Put a finished recording on the timeline: screen on a video track, webcam as picture-in-picture
        above it, microphone and system audio on their own audio tracks - all lined up."""
        from .. import capture
        opts = opts or {}
        paths = [res.files[k] for k in ("screen", "webcam", "mic", "system") if k in res.files]
        for p in paths:
            if p not in self.project.media:
                self.project.media.append(p)
                self.library.media.add(p)
        if not opts.get("timeline", True):
            self.dirty = True
            self.refresh(preview=False)
            self.toast("Recording saved to your media.")
            return []
        pr = self.project
        was_empty = not pr.clips
        at = 0.0 if was_empty else pr.duration()
        added = []
        names = {"screen": "Screen recording", "webcam": "Webcam", "mic": "Microphone", "system": "System audio"}
        infos = {k: media.probe(p) for k, p in res.files.items()}
        main = infos.get("screen") or infos.get("webcam")
        if was_empty and main is not None and main.width and main.height:
            self._auto_aspect(main.width, main.height)

        def free_track(kind, start, dur, above=None):
            for t in (reversed(pr.tracks_of(kind)) if kind == "audio" or above is None else
                      sorted([t for t in pr.tracks_of(kind) if t < above], reverse=True)):
                if pr.track_free(t, start, start + dur):
                    return t
            return pr.add_track(kind)

        screen_clip = None
        if "screen" in infos:
            c = pr.clip_from_media(infos["screen"])
            c["name"] = names["screen"]
            t = free_track("video", at, c["duration"])
            pr.place(c, preferred_track=t, at=at)
            screen_clip = c
            added.append(c)
        if "webcam" in infos:
            info = infos["webcam"]
            c = pr.clip_from_media(info)
            c["name"] = names["webcam"]
            if screen_clip is not None:
                t = free_track("video", at, c["duration"], above=screen_clip["track"])
                W, H = formats.canvas_size(pr.aspect)
                x, y, sc = capture.pip_transform(W, H, info.width or 640, info.height or 360,
                                                 opts.get("cam_size", 0.28), opts.get("corner", "br"))
                c.update({"x": round(x, 4), "y": round(y, 4), "scale": round(sc, 4)})
            else:
                t = free_track("video", at, c["duration"])
            pr.place(c, preferred_track=t, at=at + res.offsets.get("webcam", 0.0))
            added.append(c)
        for kind in ("mic", "system"):
            if kind not in infos:
                continue
            c = pr.clip_from_media(infos[kind])
            c["name"] = names[kind]
            off = res.offsets.get(kind, 0.0)
            start = at + max(0.0, off)
            if off < 0:                       # started before the screen: trim the lead-in
                c["in_point"] = c["in_point"] + (-off)
                c["duration"] = max(0.1, c["duration"] + off)
            t = free_track("audio", start, c["duration"])
            pr.place(c, preferred_track=t, at=start)
            added.append(c)
        if not added:
            return []
        self.timeline.selected = [c["id"] for c in added]
        self._selection_changed(self.timeline.selected)
        self.commit("Add recording")
        self.seek(at)
        QTimer.singleShot(0, self.timeline.zoom_to_fit)
        bits = [names[k].lower() if k != "screen" else "screen" for k in ("screen", "webcam", "mic", "system")
                if k in infos]
        self.toast("Recording added - " + ", ".join(bits) + " on their own tracks.")
        return added

    def _auto_aspect(self, w, h):
        r = w / h
        key = "tiktok" if r < 0.7 else "portrait45" if r < 0.9 else "square" if r < 1.1 else \
            "classic" if r < 1.45 else "movie" if r < 2.0 else "cinema"
        if key != self.project.aspect:
            self.project.aspect = key
            self._sync_aspect_combo()
            self.toast(f"Canvas set to {formats.ASPECTS[key][0]} ({formats.ASPECTS[key][1]}) to match your video. "
                       "Change it any time at the top.")

    def _drop_media(self, paths, t, track):
        self.import_paths(paths, add_to_timeline=True, at=t, track=track)

    def _remove_media(self, paths):
        for p in paths:
            if p in self.project.media:
                self.project.media.remove(p)
            self.library.media.remove(p)
        self.dirty = True
        self.refresh(preview=False)

    def add_text(self, preset):
        c = proj.Clip(kind="text", name="Text", duration=3.0, has_video=True)
        c.update(preset)
        c["kind"] = "text"
        tracks = self.project.tracks_of("video")
        top = tracks[0]
        at = self.playhead
        if not self.project.track_free(top, at, at + c["duration"]):
            self.project.add_track("video")
            top = 0
        self.project.place(c, preferred_track=top, at=at)
        self.timeline.selected = [c["id"]]
        self._selection_changed(self.timeline.selected)
        self.commit("Add text")
        self.inspector.show_tab("Text")
        self.inspector.text_edit.setFocus()
        self.inspector.text_edit.selectAll()

    # ================================================================== canvas
    def _sync_aspect_combo(self):
        self.aspect_combo.blockSignals(True)
        self.aspect_combo.setCurrentIndex(max(0, self.aspect_combo.findData(self.project.aspect)))
        self.aspect_combo.blockSignals(False)

    def _aspect_from_combo(self):
        key = self.aspect_combo.currentData()
        if key and key != self.project.aspect:
            self.project.aspect = key
            self.commit("Canvas shape")

    def set_aspect(self, key):
        if key != self.project.aspect:
            self.project.aspect = key
            self._sync_aspect_combo()
            self.commit("Canvas shape")

    def preview_size(self):
        mw, mh = PREVIEW_SIZES.get(settings.get("preview_quality", "balanced"), (960, 540))
        return formats.preview_size(self.project.aspect, mw, mh)

    def _set_preview_quality(self, key):
        settings.set("preview_quality", key)
        for a in self.pq_menu.actions():
            a.setChecked(a.data() == key)
        self.compositor.close()
        self.schedule_preview()

    # ================================================================== preview & playback
    def schedule_preview(self):
        if not self.playing and not self.preview_timer.isActive():
            self.preview_timer.start()

    def render_preview(self):
        W, H = self.preview_size()
        try:
            frame = self.compositor.compose(self.project, self.playhead, W, H)
        except Exception as e:  # keep the UI alive whatever a file does
            import numpy as np
            frame = np.zeros((H, W, 3), np.uint8)
            self.statusBar().showMessage(f"Preview error: {e}", 4000)
        self.preview.canvas.set_frame(frame)
        sel = self._selected_visual()
        canvas = self.preview.canvas
        if sel is not None and sel["start"] <= self.playhead < sel.end and not self.playing:
            canvas.sel_clip = sel
            canvas.sel_rect = self.compositor.clip_rect(self.project, sel, self.playhead, W, H)
        else:
            canvas.sel_clip = None
            canvas.sel_rect = None
        self.preview.set_time(self.playhead, self.project.duration(), self.project.fps)

    def seek(self, t):
        t = max(0.0, min(float(t), max(0.0, self.project.duration())))
        self.playhead = t
        self.timeline.playhead = t
        if self.playing:
            self.play_start_t = t
            self.clock.restart()
            self._sync_audio(force=True)
        else:
            self.timeline.ensure_visible(t)
        self.timeline.update()
        self.render_preview() if not self.playing else None

    def step(self, frames):
        self.stop()
        fps = self.project.fps
        f = round(self.playhead * fps) + frames
        self.seek(f / fps)

    def toggle_play(self):
        if self.playing:
            self.stop()
        else:
            self.play()

    def play(self, until=None):
        if not self.project.clips:
            return
        d = self.project.duration()
        if self.playhead >= d - 0.02:
            self.playhead = 0.0
        self.play_until = until
        self.playing = True
        self.play_start_t = self.playhead
        self.clock.start()
        self.preview.set_playing(True)
        self.preview.canvas.sel_rect = None
        fps = min(30, self.project.fps)
        self.play_timer.start(int(1000 / fps))
        self._maybe_build_audio()
        self._sync_audio(force=True)

    def play_range(self, a, b):
        self.seek(a)
        self.play(until=b)

    def stop(self):
        if not self.playing:
            return
        self.playing = False
        self.play_timer.stop()
        self.preview.set_playing(False)
        if self.player is not None:
            self.player.pause()
        self.preview.meter.set_levels(None)
        self.render_preview()

    def _tick(self):
        t = self.play_start_t + self.clock.elapsed() / 1000.0
        end = self.play_until if self.play_until is not None else self.project.duration()
        if t >= end:
            self.playhead = min(end, self.project.duration())
            self.timeline.playhead = self.playhead
            self.stop()
            self.timeline.update()
            return
        self.playhead = t
        self.timeline.playhead = t
        vis = self.timeline.visible_seconds()
        if t > self.timeline.scroll_x + vis * 0.92:
            self.timeline.scroll_x = t - vis * 0.08
            self.tl_scroll.sync()
        self.render_preview()
        self.timeline.update()
        self._sync_audio()
        self._update_meters()

    # ------------------------------------------------------------------ audio preview
    def _init_audio(self):
        self.player = None
        try:
            from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
            self.player = QMediaPlayer(self)
            self.audio_out = QAudioOutput(self)
            self.audio_out.setVolume(1.0)
            self.player.setAudioOutput(self.audio_out)
        except Exception:
            self.player = None

    def _audio_signature(self):
        parts = []
        for c in self.project.clips:
            if c.has_sound:
                tr = self.project.tracks[c["track"]] if c["track"] < len(self.project.tracks) else {}
                parts.append((c["path"], round(c["start"], 3), round(c["duration"], 3), round(c["in_point"], 3),
                              c["speed"], c["keep_pitch"], c["pitch"], c["volume"], c["muted"], tr.get("muted"),
                              tr.get("hidden"), tr.get("solo"), c["track"], c["anim_in"], c["anim_out"],
                              c["anim_in_dur"], c["anim_out_dur"], c.get("pan"), c.get("afade_in"),
                              c.get("afade_out"), c.get("eq_low"), c.get("eq_mid"), c.get("eq_high"),
                              c.get("compress"), c.get("denoise"), c.get("reverb")))
        return json.dumps(parts)

    def _maybe_build_audio(self):
        if self.player is None or self.audio_building:
            return
        sig = self._audio_signature()
        if sig == self.audio_sig:
            return
        if sig == "[]":
            self.audio_sig = sig
            self.audio_path = None
            self.player.stop()
            return
        self.audio_building = True
        snap = proj.Project.from_dict(self.project.to_dict())
        out = os.path.join(cache_dir("preview"), f"audio_{int(time.time() * 1000)}.wav")

        def work():
            ok = False
            try:
                ok = render.render_audio_preview(snap, out)
            except Exception:
                ok = False
            self.bridge.audioReady.emit(out if ok else "", sig)

        threading.Thread(target=work, daemon=True).start()

    def _audio_ready(self, path, sig):
        self.audio_building = False
        old = self.audio_path
        if path:
            self.audio_path = path
            self.audio_sig = sig
            self.audio_pcm = self._load_pcm(path)
            self.player.setSource(QUrl.fromLocalFile(path))
            if self.playing:
                self._sync_audio(force=True)
        if old and old != path:
            QTimer.singleShot(3000, lambda: self._rm(old))
        if self._audio_signature() != self.audio_sig:
            self.audio_timer.start()

    @staticmethod
    def _load_pcm(path):
        """The preview mix as an int16 (frames, 2) array, for the level meters."""
        import wave
        import numpy as np
        try:
            with wave.open(path, "rb") as w:
                data = np.frombuffer(w.readframes(w.getnframes()), np.int16)
                ch = w.getnchannels()
                rate = w.getframerate()
            return data.reshape(-1, ch), rate
        except Exception:
            return None

    def _update_meters(self):
        pcm = getattr(self, "audio_pcm", None)
        if not self.playing or pcm is None:
            self.preview.meter.set_levels(None)
            return
        import numpy as np
        data, rate = pcm
        i1 = int(self.playhead * rate)
        i0 = max(0, i1 - int(0.05 * rate))
        block = data[i0:i1]
        if len(block) == 0:
            self.preview.meter.set_levels(None)
            return
        peak = np.abs(block.astype(np.int32)).max(axis=0) / 32768.0
        rms = np.sqrt((block.astype(np.float64) ** 2).mean(axis=0)) / 32768.0
        if peak.shape[0] == 1:
            peak = np.repeat(peak, 2)
            rms = np.repeat(rms, 2)
        self.preview.meter.set_levels((float(peak[0]), float(peak[1])), (float(rms[0]), float(rms[1])))

    @staticmethod
    def _rm(p):
        try:
            os.remove(p)
        except OSError:
            pass

    def _sync_audio(self, force=False):
        if self.player is None or not self.audio_path:
            return
        from PyQt6.QtMultimedia import QMediaPlayer
        want = int(self.playhead * 1000)
        if force or abs(self.player.position() - want) > 180:
            self.player.setPosition(want)
        if self.playing and self.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
            self.player.play()

    # ================================================================== zoom slider
    def _sync_zoom_slider(self):
        import math
        self.zoom_slider.blockSignals(True)
        v = (math.log(self.timeline.pps) - math.log(4)) / (math.log(800) - math.log(4)) * 1000
        self.zoom_slider.setValue(int(v))
        self.zoom_slider.blockSignals(False)
        self.tl_scroll.sync()

    def _zoom_slider_moved(self, v):
        import math
        pps = math.exp(math.log(4) + v / 1000 * (math.log(800) - math.log(4)))
        self.timeline.set_zoom(pps)

    # ================================================================== files
    def maybe_save(self):
        if not self.dirty or not self.project.clips:
            return True
        r = QMessageBox.question(self, APP_NAME, f"Save changes to “{self.project.name}”?",
                                 QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard |
                                 QMessageBox.StandardButton.Cancel)
        if r == QMessageBox.StandardButton.Save:
            return self.save()
        return r == QMessageBox.StandardButton.Discard

    def new_project(self):
        if not self.maybe_save():
            return
        self.dirty = False
        self.timeline.selected = []
        self.playhead = 0.0
        self.timeline.playhead = 0.0
        self.set_project(proj.Project())

    def open_dialog(self):
        if not self.maybe_save():
            return
        p, _ = QFileDialog.getOpenFileName(self, "Open project", os.path.expanduser("~"),
                                           f"Easy-Cut project (*{PROJECT_EXT})")
        if p:
            self.open_project(p, ask=False)

    def open_project(self, path, ask=True):
        if ask and not self.maybe_save():
            return
        try:
            p = proj.Project.load(path)
        except Exception as e:
            QMessageBox.warning(self, APP_NAME, f"That project couldn't be opened.\n\n{e}")
            return
        self.dirty = False
        self.timeline.selected = []
        self.playhead = 0.0
        self.timeline.playhead = 0.0
        self.set_project(p)
        settings.add_recent(path)
        missing = sorted({c["path"] for c in p.clips if c["kind"] != "text" and not os.path.exists(c["path"])})
        if missing:
            self._relink(missing)
        QTimer.singleShot(0, self.timeline.zoom_to_fit)

    def _relink(self, missing):
        r = QMessageBox.question(self, APP_NAME, f"{len(missing)} media file(s) used by this project can't be found "
                                 "(moved or renamed?).\n\nFind them now?")
        if r != QMessageBox.StandardButton.Yes:
            return
        for old in missing:
            new, _ = QFileDialog.getOpenFileName(self, f"Where is {os.path.basename(old)}?", os.path.dirname(old))
            if not new:
                continue
            for c in self.project.clips:
                if c["path"] == old:
                    c["path"] = new
                    c["name"] = os.path.basename(new)
            self.project.media = [new if m == old else m for m in self.project.media]
        self.library.media.set_media(self.project.media)
        self.compositor.close()
        self.commit("Relink media")

    def save(self):
        if not self.project.path:
            return self.save_as()
        try:
            self.project.save(self.project.path)
        except OSError as e:
            QMessageBox.warning(self, APP_NAME, f"Couldn't save the project.\n\n{e}")
            return False
        self.dirty = False
        settings.add_recent(self.project.path)
        self.refresh(preview=False)
        self.toast("Project saved")
        return True

    def save_as(self):
        base = self.project.path or os.path.join(os.path.expanduser("~"), "Documents",
                                                 (self.project.name or "My video") + PROJECT_EXT)
        p, _ = QFileDialog.getSaveFileName(self, "Save project", base, f"Easy-Cut project (*{PROJECT_EXT})")
        if not p:
            return False
        if not p.lower().endswith(PROJECT_EXT):
            p += PROJECT_EXT
        self.project.path = p
        return self.save()

    def _fill_recent(self):
        self.recent_menu.clear()
        rec = [p for p in settings.get("recent_projects", []) if os.path.exists(p)]
        if not rec:
            a = self.recent_menu.addAction("No recent projects")
            a.setEnabled(False)
        for p in rec:
            self.recent_menu.addAction(os.path.basename(p), lambda p=p: self.open_project(p))

    def _autosave(self):
        if not self.dirty or not self.project.clips:
            return
        try:
            d = self.project.to_dict()
            d["autosave_of"] = self.project.path
            with open(data_path("autosave", "autosave.ecut"), "w", encoding="utf-8") as f:
                json.dump(d, f)
        except OSError:
            pass

    def _mark_session(self, open_):
        try:
            flag = data_path("autosave", "session.lock")
            if open_:
                self._recover_available = os.path.exists(flag) and os.path.exists(data_path("autosave", "autosave.ecut"))
                with open(flag, "w") as f:
                    f.write(str(os.getpid()))
            else:
                os.remove(flag)
                try:
                    os.remove(data_path("autosave", "autosave.ecut"))
                except OSError:
                    pass
        except OSError:
            pass

    def _offer_recovery(self):
        if not getattr(self, "_recover_available", False):
            return
        r = QMessageBox.question(self, APP_NAME, "Easy-Cut didn't close properly last time.\n"
                                 "Would you like to recover your unsaved project?")
        if r == QMessageBox.StandardButton.Yes:
            try:
                with open(data_path("autosave", "autosave.ecut"), "r", encoding="utf-8") as f:
                    d = json.load(f)
                p = proj.Project.from_dict(d)
                p.path = d.get("autosave_of") or ""
                self.set_project(p)
                self.dirty = True
                self.refresh()
            except Exception:
                pass

    # ================================================================== export & dialogs
    def export(self):
        if not self.project.clips:
            self.toast("Add some media to the timeline first.")
            return
        self.stop()
        sel = self.selected_clips()
        selection = (min(c.vis_start for c in sel), max(c.end for c in sel)) if sel else None
        dlg = RenderDialog(self.project, self, selection=selection)
        dlg.exec()

    def show_themes(self):
        ThemeDialog(self.app, self).exec()

    def apply_chrome(self):
        """🍏 Mode: frameless window + our own title bar. Other themes: the normal Windows title bar."""
        from .chrome import EdgeResizer, win_round_corners
        apple = bool(theme.C.get("apple"))
        frameless = apple and settings.get("mac_titlebar", True)
        if not hasattr(self, "resizer"):
            self.resizer = EdgeResizer(self)
            self.app.installEventFilter(self.resizer)
        self.resizer.active = frameless
        self.dots.setVisible(frameless)
        self.logo.setVisible(not apple)
        self.brand.setVisible(not apple)
        self.name_sub.setVisible(apple)
        self.top_bar.setFixedHeight(54 if apple else 52)
        was = bool(self.windowFlags() & Qt.WindowType.FramelessWindowHint)
        if was != frameless:
            visible = self.isVisible()
            geo = self.geometry()
            self.setWindowFlag(Qt.WindowType.FramelessWindowHint, frameless)
            if visible:
                self.setGeometry(geo)
                self.show()
        if frameless:
            win_round_corners(self)
        self.refresh(preview=False)

    def _theme_changed(self):
        self.apply_chrome()
        if not self.library.collapsed:
            want = self.library.rail_width() + 310
            self.library.setMinimumWidth(want)
            sizes = self.hsplit.sizes()
            if sizes and sizes[0] < want + 60:
                grow = want + 60 - sizes[0]
                self.hsplit.setSizes([sizes[0] + grow, max(300, sizes[1] - grow), sizes[2]])
        self.timeline.update()
        self.preview.canvas.update()
        self.library.filters.rebuild()
        self.library.filters.sync(self._selected_visual())

    def show_extensions(self, category=None):
        if category:
            self.library.extensions.set_category(category)
        self.library.show("extensions")

    def show_shortcuts(self):
        rows = [("Space", "Play / pause"), ("S  or  Ctrl+B", "Split at playhead"), ("Delete", "Delete selection"),
                ("Ctrl+D", "Duplicate"), ("Ctrl+Z / Ctrl+Y", "Undo / redo"), ("← / →", "Previous / next frame"),
                ("Shift+← / →", "Jump 10 frames"), ("Home / End", "Start / end"), ("+ / -", "Zoom timeline"),
                ("Ctrl+scroll", "Zoom timeline at the mouse"), ("N", "Snapping on/off"),
                ("Alt while dragging", "Temporarily turn off snapping"), ("Ctrl+I", "Import media"),
                ("Ctrl+E", "Export"), ("Ctrl+S", "Save project")]
        QMessageBox.information(self, "Keyboard shortcuts",
                                "\n".join(f"{k:<22}  {v}" for k, v in rows))

    def show_about(self):
        dlg = QDialog(self)
        dlg.setWindowTitle(f"About {APP_NAME}")
        v = QVBoxLayout(dlg)
        v.setContentsMargins(24, 22, 24, 20)
        top = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(icons.app_pixmap(128).scaled(72, 72, Qt.AspectRatioMode.KeepAspectRatio,
                                                     Qt.TransformationMode.SmoothTransformation))
        top.addWidget(logo)
        t = QVBoxLayout()
        h = QLabel(f"{APP_NAME}")
        h.setObjectName("H1")
        t.addWidget(h)
        s = QLabel(f"Version {__version__} · free, no ads, no account")
        s.setObjectName("Dim")
        t.addWidget(s)
        top.addLayout(t, 1)
        v.addLayout(top)
        body = QLabel("Easy-going editing with serious power underneath. If Easy-Cut has earned a place in your "
                      "toolkit, the best way to support it is to join the community - share what you've made and "
                      "tell us what to build next.")
        body.setWordWrap(True)
        v.addWidget(body)
        row = QHBoxLayout()
        for label, url in (("TopTracking.App Discord", TOPTRACKING_URL), ("TKO Gaming & Services", TKO_URL),
                           ("GitHub", GITHUB_URL)):
            b = QPushButton(label)
            b.clicked.connect(lambda _=False, u=url: QDesktopServices.openUrl(QUrl(u)))
            row.addWidget(b)
        v.addLayout(row)
        ok = QPushButton("Close")
        ok.setObjectName("Primary")
        ok.clicked.connect(dlg.accept)
        v.addWidget(ok, 0, Qt.AlignmentFlag.AlignRight)
        dlg.exec()

    def toast(self, text, ms=4500):
        self.statusBar().showMessage(text, ms)

    # ================================================================== updates & extensions
    def check_updates(self, manual=False, quiet_ok=False):
        self._manual_check = manual

        def work():
            try:
                m = updater.fetch_manifest()
                res = updater.check(m)
                res["manifest_extensions"] = m.get("extensions", [])
                self.bridge.updatesChecked.emit(res, "")
            except Exception as e:  # noqa: BLE001
                self.bridge.updatesChecked.emit(None, str(e))

        threading.Thread(target=work, daemon=True).start()

    def _updates_checked(self, result, err):
        manual = getattr(self, "_manual_check", False)
        if result is None:
            if manual:
                QMessageBox.information(self, "Updates", "Couldn't reach the update server right now.\n"
                                        "Check your internet connection and try again.")
            return
        self.manifest_updates = result
        known = {p["id"] for p in catalog.packs()}
        catalog.merge_manifest(result.get("manifest_extensions", []))
        if {p["id"] for p in catalog.packs()} != known:
            self._rebuild_libraries()          # new packs were released since this version shipped
        self.library.extensions.populate(result["extensions"], getattr(self, "_restart_packs", set()))
        if result["extensions"] and settings.get("auto_update_extensions", False):
            for e in result["extensions"]:
                self.install_extension(e, quiet=True)
        if result["app"]:
            v = result["app"]["version"]
            self.banner_label.setText(f"Easy-Cut {v} is available. " + (result["app"].get("notes") or ""))
            self.banner_btn.setText("Update now" if updater.can_self_update() else "Download")
            self._banner_mode = "app"
            self.banner.show()
        elif result["extensions"] and not settings.get("auto_update_extensions", False):
            n = len(result["extensions"])
            self.banner_label.setText(f"{n} pack update{'s are' if n > 1 else ' is'} available.")
            self.banner_btn.setText("Update")
            self._banner_mode = "ext"
            self.banner.show()
        elif manual:
            QMessageBox.information(self, "Updates", f"You're on the latest version ({__version__}).")

    def _banner_action(self):
        r = self.manifest_updates or {}
        if getattr(self, "_banner_mode", "") == "ext":
            for e in r.get("extensions", []):
                self.install_extension(e, quiet=True)
            self.banner.hide()
            return
        app = r.get("app")
        if not app:
            return
        if not updater.can_self_update():
            QDesktopServices.openUrl(QUrl(RELEASES_URL))
            return
        if not self.maybe_save():
            return
        self.banner_label.setText("Downloading the update…")
        self.banner_btn.setEnabled(False)

        def work():
            try:
                data = updater.download(app["url"], app.get("sha256"))
                self.bridge.appDownloaded.emit(data, app["version"], "")
            except Exception as e:  # noqa: BLE001
                self.bridge.appDownloaded.emit(b"", app["version"], str(e))

        threading.Thread(target=work, daemon=True).start()

    def _app_downloaded(self, data, version, err):
        self.banner_btn.setEnabled(True)
        if err:
            self.banner_label.setText(f"The update couldn't be downloaded: {err}")
            return
        updater.run_installer(data, version)
        self.dirty = False
        self.close()

    def install_extension(self, entry, quiet=False):
        self.toast(f"Installing {entry.get('name', entry['id'])}…")

        def work():
            try:
                ext, restart = updater.install_extension(entry)
                self.bridge.extInstalled.emit(ext, restart, "")
            except Exception as e:  # noqa: BLE001
                self.bridge.extInstalled.emit(None, False, str(e))

        threading.Thread(target=work, daemon=True).start()

    def install_extension_file(self):
        p, _ = QFileDialog.getOpenFileName(self, "Install extension", os.path.expanduser("~"),
                                           "Easy-Cut extension (*.zip)")
        if not p:
            return
        try:
            with open(p, "rb") as f:
                ext, restart = extensions.install_zip(f.read())
            self._ext_installed(ext, restart, "")
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Extensions", f"That extension couldn't be installed.\n\n{e}")

    def _ext_installed(self, ext, restart, err):
        if err:
            QMessageBox.warning(self, "Extensions", f"The extension couldn't be installed.\n\n{err}")
            return
        if ext is not None and ext.error:
            QMessageBox.warning(self, "Extensions", f"{ext.name} was installed but couldn't start:\n\n{ext.error}")
        if restart:
            self.toast(f"{ext.name} will be updated the next time you open Easy-Cut.", 8000)
        else:
            self.toast(f"{ext.name} is installed and ready.")
        if ext is not None:
            self._packs_installed([ext.id], [ext.id] if restart else [])

    def remove_extension(self, ext_id):
        name = (catalog.pack(ext_id) or {}).get("name", ext_id)
        if QMessageBox.question(self, "Extensions", f"Remove {name}? You can download it again any time.") \
                != QMessageBox.StandardButton.Yes:
            return
        restart = extensions.uninstall(ext_id)
        if restart:
            self._restart_packs = set(getattr(self, "_restart_packs", set())) | {ext_id}
        self.toast(f"{name} will be removed the next time you open Easy-Cut." if restart else f"{name} removed.")
        self.library.extensions.populate(None, getattr(self, "_restart_packs", set()))

    def _rebuild_libraries(self):
        self.library.rebuild()
        self.inspector.rebuild_extension_effects()
        self.inspector.rebuild_styles()
        self._selection_changed(self.timeline.selected)

    # ================================================================== close
    def closeEvent(self, ev):
        if not self.maybe_save():
            ev.ignore()
            return
        self.stop()
        self.compositor.close()
        self._mark_session(open_=False)
        if self.audio_path:
            self._rm(self.audio_path)
        ev.accept()
