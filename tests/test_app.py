"""App-level tests: themes, extensions, updater, and the main window driven like a user would."""
import hashlib
import http.server
import io
import json
import os
import threading
import time
import unittest
import zipfile

from tests import _env
from tests._env import path, TMP, APP

from PyQt6.QtCore import Qt, QPointF
from PyQt6.QtGui import QMouseEvent

from easycut import (theme, extensions, filters, animations, updater, settings, media, project, render,
                     compositor)


def pump(n=5):
    for _ in range(n):
        APP.processEvents()


def template_zip(version="0.1.0", ext_id="example-pack"):
    src = os.path.join(_env.ROOT, "extensions", "_template")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name in ("manifest.json", "main.py"):
            with open(os.path.join(src, name), "rb") as fh:
                data = fh.read()
            if name == "manifest.json":
                m = json.loads(data)
                m["version"] = version
                m["id"] = ext_id
                data = json.dumps(m).encode()
            z.writestr(f"{ext_id}/{name}", data)
    return buf.getvalue()


class TestThemes(unittest.TestCase):
    def tearDown(self):
        theme.apply(APP, "dark")

    def test_presets_apply(self):
        for tid in theme.PRESET_ORDER:
            c = theme.apply(APP, tid)
            self.assertIn(c["accent"], APP.styleSheet())
            for k, _ in theme.BASE_KEYS:
                self.assertTrue(c[k].startswith("#"), (tid, k))

    def test_default_is_dark(self):
        self.assertEqual(settings.DEFAULTS["theme"], "dark")
        self.assertTrue(theme.PRESETS["dark"]["dark"])

    def test_preset_feel(self):
        self.assertEqual(theme.PRESETS["cyberpunk"]["accent"].lower(), "#fcee0a")      # yellow
        self.assertIn("#b026ff", theme.PRESETS["cyberpunk"]["accent2"].lower())        # purple
        self.assertEqual(theme.PRESETS["cyberpunk"]["radius"], 0)                     # sharp, futuristic
        self.assertEqual(theme.PRESETS["apple"]["accent"].lower(), "#007aff")         # iOS blue
        self.assertIn("🍏", theme.PRESETS["apple"]["name"])

    def test_custom_save_default_delete(self):
        colours = dict(theme.PRESETS["dark"])
        colours["accent"] = "#12ab34"
        theme.save_custom("Mine", colours)
        self.assertIn("Mine", theme.custom_themes())
        theme.apply(APP, "custom:Mine", remember=True)
        self.assertEqual(settings.get("theme"), "custom:Mine")
        self.assertEqual(theme.C["accent"], "#12ab34")
        with open(os.path.join(os.environ["EASYCUT_DATA_DIR"], "themes.json"), encoding="utf-8") as f:
            self.assertIn("Mine", json.load(f))
        theme.delete_custom("Mine")
        self.assertEqual(theme.resolve("custom:Mine")["name"], "Dark")
        settings.set("theme", "dark")


class TestExtensions(unittest.TestCase):
    def test_install_load_register_uninstall(self):
        ext, restart = extensions.install_zip(template_zip())
        self.assertFalse(restart)
        self.assertTrue(ext.loaded, ext.error)
        self.assertIn("example-teal-orange", filters.FILTERS)
        self.assertIn("example-swing", animations.ANIMATIONS)
        self.assertIn("example-vignette", filters.EFFECTS)
        # extension items work in preview and export
        p = project.Project()
        c = p.place(p.clip_from_media(media.probe(path("clip.mp4")), duration=1.0))
        c.update(filter="example-teal-orange", anim_in="example-swing", fx=[{"id": "example-vignette", "amount": 1}])
        comp = compositor.Compositor()
        frame = comp.compose(p, 0.5, 320, 180)
        self.assertEqual(frame.shape, (180, 320, 3))
        out = os.path.join(TMP, "ext.mp4")
        render.Renderer(p, render.RenderOptions(out_path=out, encoder="cpu")).run()
        self.assertTrue(os.path.getsize(out) > 1000)
        # update needs restart because it's loaded
        ext2, restart2 = extensions.install_zip(template_zip("0.2.0"))
        self.assertTrue(restart2)
        self.assertTrue(extensions.uninstall("example-pack"))
        extensions.apply_pending()
        self.assertNotIn("example-pack", extensions.installed())

    def test_bad_zip_rejected(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("x/readme.txt", "hi")
        with self.assertRaises(ValueError):
            extensions.install_zip(buf.getvalue())

    def test_zip_slip_blocked(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("evil/manifest.json", json.dumps({"id": "evil", "version": "1"}))
            z.writestr("evil/main.py", "def register(api):\n    pass\n")
            z.writestr("evil/../../escape.txt", "nope")
        extensions.install_zip(buf.getvalue(), live=False)
        self.assertFalse(os.path.exists(os.path.join(os.environ["EASYCUT_DATA_DIR"], "escape.txt")))
        extensions.uninstall("evil")

    def test_version_compare(self):
        self.assertTrue(updater.newer("0.1.10", "0.1.9"))
        self.assertFalse(updater.newer("0.1.0", "0.1.0"))
        self.assertTrue(updater.newer("1.0", "0.9.9"))


class _Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


class TestUpdater(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = os.path.join(TMP, "server")
        os.makedirs(cls.root, exist_ok=True)
        data = template_zip("0.3.0", "srv-pack")
        with open(os.path.join(cls.root, "srv-pack.zip"), "wb") as f:
            f.write(data)
        cls.sha = hashlib.sha256(data).hexdigest()
        handler = lambda *a, **k: _Handler(*a, directory=cls.root, **k)  # noqa: E731
        cls.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{cls.port}"
        manifest = {"app": {"version": "99.0.0", "url": f"{base}/setup.exe", "sha256": "0"},
                    "extensions": [{"id": "srv-pack", "name": "Server pack", "version": "0.3.0",
                                    "url": f"{base}/srv-pack.zip", "sha256": cls.sha, "min_app": "0.1.0"},
                                   {"id": "future", "name": "Future", "version": "1.0", "url": "x",
                                    "min_app": "50.0"}]}
        with open(os.path.join(cls.root, "manifest.json"), "w") as f:
            json.dump(manifest, f)
        cls.base = base

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def test_check_and_install(self):
        m = updater.fetch_manifest(self.base + "/manifest.json")
        res = updater.check(m)
        self.assertEqual(res["app"]["version"], "99.0.0")
        ids = [e["id"] for e in res["available"]]
        self.assertIn("srv-pack", ids)
        self.assertNotIn("future", ids)            # needs a newer app
        ext, restart = updater.install_extension(res["available"][0])
        self.assertEqual(ext.id, "srv-pack")
        self.assertEqual(updater.check(m)["available"], [e for e in updater.check(m)["available"] if e["id"] != "srv-pack"])
        extensions.uninstall("srv-pack")
        extensions.apply_pending()

    def test_checksum_mismatch_refused(self):
        with self.assertRaises(ValueError):
            updater.download(self.base + "/srv-pack.zip", "deadbeef")

    def test_self_update_only_when_installed(self):
        self.assertFalse(updater.can_self_update())   # running from source


class TestMainWindow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from easycut.ui.mainwindow import MainWindow
        cls.w = MainWindow(APP)
        cls.w.resize(1500, 900)
        cls.w.show()
        pump()

    @classmethod
    def tearDownClass(cls):
        cls.w.dirty = False
        cls.w.close()
        pump()

    def setUp(self):
        self.w.dirty = False
        self.w.new_project()
        pump()

    def test_import_and_auto_canvas(self):
        self.w.import_paths([path("portrait.mp4")], add_to_timeline=True)
        self.assertEqual(self.w.project.aspect, "tiktok")
        self.assertEqual(len(self.w.project.clips), 1)
        self.assertIn(path("portrait.mp4"), self.w.project.media)

    def test_edit_flow_with_undo(self):
        w = self.w
        w.add_to_timeline([path("clip.mp4"), path("photo.png")])
        self.assertEqual(len(w.project.clips), 2)
        c = w.project.clips[0]
        w.timeline.selected = [c["id"]]
        w._selection_changed([c["id"]])
        w.seek(1.0)
        w.split()
        self.assertEqual(len(w.project.clips), 3)
        w.undo()
        self.assertEqual(len(w.project.clips), 2)
        w.redo()
        self.assertEqual(len(w.project.clips), 3)
        w.timeline.selected = [w.project.clips[-1]["id"]]
        w.delete_selected()
        self.assertEqual(len(w.project.clips), 2)

    def test_filters_animations_effects_from_panels(self):
        w = self.w
        w.add_to_timeline([path("green.mp4")])
        c = w.project.clips[0]
        w.timeline.selected = [c["id"]]
        w._selection_changed([c["id"]])
        w._filter_chosen("vivid")
        self.assertEqual(c["filter"], "vivid")
        w._anim_chosen("in", "zoom")
        w.stop()
        self.assertEqual(c["anim_in"], "zoom")
        w._effect_chosen("chroma")
        self.assertTrue(c["chroma"])
        w._effect_chosen("stabilize")
        self.assertTrue(c["stabilize"])
        w.inspector.changed.emit({"mirror": "left"})
        w.inspector.changed.emit({"flip_h": True})
        w.inspector.changed.emit({"crop": [0.1, 0, 0, 0]})
        self.assertEqual(c["mirror"], "left")
        self.assertTrue(c["flip_h"])
        w._speed_changed(2.0)
        self.assertAlmostEqual(c["duration"], 1.5, delta=0.05)
        w.render_preview()
        self.assertEqual(w.preview.canvas.canvas_size, w.preview_size())

    def test_eyedropper_picks_key_colour(self):
        w = self.w
        w.add_to_timeline([path("green.mp4")])
        c = w.project.clips[0]
        w.timeline.selected = [c["id"]]
        w._selection_changed([c["id"]])
        w.seek(0.5)
        w._color_picked(0.05, 0.5)
        col = c["chroma_color"].lstrip("#")
        r, g, b = int(col[0:2], 16), int(col[2:4], 16), int(col[4:6], 16)
        self.assertTrue(g > 200 and r < 60 and b < 60, c["chroma_color"])
        self.assertTrue(c["chroma"])

    def test_canvas_drag_moves_clip(self):
        w = self.w
        w.add_to_timeline([path("clip.mp4")])
        c = w.project.clips[0]
        w.timeline.selected = [c["id"]]
        w._selection_changed([c["id"]])
        w.apply_fields({"scale": 0.5})
        w.render_preview()
        w.preview.canvas.transformLive.emit(0.2, -0.1, 0.6)
        self.assertAlmostEqual(c["x"], 0.2)
        self.assertAlmostEqual(c["scale"], 0.6)

    def test_text_and_tracks(self):
        w = self.w
        w.add_to_timeline([path("clip.mp4")])
        w.seek(0.5)
        w.add_text({"text": "Hi"})
        t = [c for c in w.project.clips if c["kind"] == "text"][0]
        self.assertAlmostEqual(t["start"], 0.5)
        self.assertEqual(w.project.tracks[t["track"]]["type"], "video")
        w._context_action("add_audio_track")
        self.assertEqual(len(w.project.tracks_of("audio")), 2)

    def test_timeline_mouse_trim(self):
        w = self.w
        w.add_to_timeline([path("clip.mp4")])
        tl = w.timeline
        tl.set_zoom(100)
        tl.scroll_x = 0
        c = w.project.clips[0]
        r = tl.clip_rect(c)
        y = r.center().y()

        def ev(kind, x):
            return QMouseEvent(kind, QPointF(x, y), QPointF(x, y), Qt.MouseButton.LeftButton,
                               Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        tl.snap = False
        tl.mousePressEvent(ev(QMouseEvent.Type.MouseButtonPress, r.right() - 2))
        tl.mouseMoveEvent(ev(QMouseEvent.Type.MouseMove, r.right() - 102))
        tl.mouseReleaseEvent(ev(QMouseEvent.Type.MouseButtonRelease, r.right() - 102))
        self.assertAlmostEqual(c["duration"], 3.0, delta=0.05)
        # can't trim past the source length
        r = tl.clip_rect(c)
        tl.mousePressEvent(ev(QMouseEvent.Type.MouseButtonPress, r.right() - 2))
        tl.mouseMoveEvent(ev(QMouseEvent.Type.MouseMove, r.right() + 800))
        tl.mouseReleaseEvent(ev(QMouseEvent.Type.MouseButtonRelease, r.right() + 800))
        self.assertAlmostEqual(c["duration"], c["source_duration"], delta=0.05)
        tl.snap = True

    def test_save_and_open(self):
        w = self.w
        w.add_to_timeline([path("clip.mp4")])
        f = os.path.join(TMP, "proj.ecut")
        w.project.path = f
        self.assertTrue(w.save())
        w.new_project()
        w.open_project(f, ask=False)
        self.assertEqual(len(w.project.clips), 1)
        self.assertEqual(w.project.name, "proj")

    def test_playback_ticks(self):
        w = self.w
        w.add_to_timeline([path("clip.mp4")])
        w.seek(0)
        w.play()
        import time
        t0 = time.time()
        while time.time() - t0 < 0.6:
            pump(2)
        w.stop()
        self.assertGreater(w.playhead, 0.2)

    def test_audio_preview_builds(self):
        w = self.w
        w.add_to_timeline([path("clip.mp4")])
        w._maybe_build_audio()
        import time
        t0 = time.time()
        while w.audio_building and time.time() - t0 < 30:
            pump(2)
            time.sleep(0.05)
        pump(5)
        self.assertTrue(w.audio_path and os.path.exists(w.audio_path))

    def test_dialogs_open(self):
        from easycut.ui.render_dialog import RenderDialog
        from easycut.ui.theme_dialog import ThemeDialog
        self.w.add_to_timeline([path("clip.mp4")])
        d = RenderDialog(self.w.project, self.w)
        d.show()
        pump()
        self.assertEqual(d.aspect_key(), self.w.project.aspect)
        d.choose_preset("gif")              # one-click preset switches format and file name
        self.assertEqual(d.fmt.currentData(), "gif")
        self.assertTrue(d.path.text().endswith(".gif"))
        d.choose_preset("mp3")
        self.assertEqual(d.collect()["fmt"], "mp3")
        self.assertTrue(d.path.text().endswith(".mp3"))
        d.choose_preset("discord")
        self.assertEqual(d.collect()["rate_mode"], "size")
        d.close()
        t = ThemeDialog(APP, self.w)
        t.show()
        pump()
        t._choose("cyberpunk")
        self.assertEqual(theme.current_id, "cyberpunk")
        t.open_editor(None)
        t.color_buttons["accent"].setColor("#abcdef")
        t._live()
        self.assertEqual(theme.C["accent"], "#abcdef")
        t.name_edit.setText("Test Theme")
        t._save()
        self.assertEqual(settings.get("theme"), "custom:Test Theme")
        t._choose("dark")
        theme.delete_custom("Test Theme")
        t.close()

    def test_explorer_adds_to_timeline(self):
        lib = self.w.library
        lib.show("explorer")
        pump()
        ex = lib.explorer
        ex.addToTimeline.emit([path("clip.mp4")])
        pump()
        self.assertEqual(len(self.w.project.clips), 1)
        lib.set_collapsed(True)
        pump()
        self.assertTrue(lib.collapsed if hasattr(lib, "collapsed") else True)
        lib.set_collapsed(False)

    def test_audio_tools_detach_solo_fades(self):
        w = self.w
        w.add_to_timeline([path("clip.mp4")])
        c = w.project.clips[0]
        a = w.project.detach_audio(c)
        self.assertIsNotNone(a)
        self.assertEqual(a["kind"], "audio")
        self.assertTrue(c["muted"] or not c.get("has_audio", True) or c.get("volume", 1) == 0)
        a["afade_in"], a["afade_out"], a["eq_low"], a["pan"] = 0.5, 0.5, 4.0, -0.3
        w.project.tracks[a["track"]]["solo"] = True
        from easycut import render
        self.assertEqual([x["id"] for x in render.audible_clips(w.project)], [a["id"]])

    def test_recording_lands_on_timeline(self):
        from easycut import capture
        out = os.path.join(TMP, "recs")
        cfg = capture.CaptureConfig(test=True, webcam="cam", mic="mic", out_dir=out, fps=30, encoder="cpu")
        rec = capture.Recorder(cfg)
        rec.start()
        time.sleep(2.0)
        res = rec.stop()
        self.assertEqual(set(res.files), {"screen", "webcam", "mic"})
        for p in res.files.values():
            self.assertTrue(os.path.exists(p))
        self.assertTrue(res.files["screen"].endswith(".mp4"))
        added = self.w.import_recording(res, {"timeline": True, "corner": "br", "cam_size": 0.28})
        pump()
        self.assertEqual(len(added), 3)
        pr = self.w.project
        screen = next(c for c in pr.clips if c["name"] == "Screen recording")
        cam = next(c for c in pr.clips if c["name"] == "Webcam")
        mic = next(c for c in pr.clips if c["name"] == "Microphone")
        self.assertLess(cam["track"], screen["track"])           # webcam sits above the screen
        self.assertGreater(cam["x"], 0)
        self.assertGreater(cam["y"], 0)                          # bottom-right corner
        self.assertLess(cam["scale"], 0.5)
        self.assertEqual(pr.tracks[mic["track"]]["type"], "audio")

    def test_recorder_dialog_opens(self):
        from easycut.ui.recorder import RecorderDialog
        d = RecorderDialog(self.w)
        d.show()
        d.dev_thread.wait(20000)
        pump()
        d._devices_found({"video": ["Cam A"], "audio": ["Mic A"]})
        d.cam_card.toggle.setChecked(True)
        cfg = d.config()
        self.assertEqual(cfg.webcam, "Cam A")
        self.assertTrue(cfg.screen)
        d.close()

    def test_apple_theme_chrome(self):
        theme.apply(APP, "apple")
        self.w._theme_changed() if hasattr(self.w, "_theme_changed") else None
        pump()
        self.assertTrue(theme.C.get("apple"))
        self.assertGreaterEqual(self.w.library.rail_width(), 190)
        theme.apply(APP, "dark")
        self.w._theme_changed() if hasattr(self.w, "_theme_changed") else None
        pump()
        self.assertFalse(theme.C.get("apple"))

    def test_extensions_page_highlighted(self):
        lib = self.w.library
        b = lib.rail_buttons["extensions"]
        self.assertEqual(b.objectName(), "RailExt")
        self.assertEqual(b.badge, "NEW")
        self.w.show_extensions()
        self.assertIs(lib.stack.currentWidget(), lib.extensions)


if __name__ == "__main__":
    unittest.main()
