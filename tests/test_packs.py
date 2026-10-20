"""Pack tests: catalog consistency, every pack item rendering the same in preview and export, and the
download -> install -> use flow (against a local test server)."""
import hashlib
import http.server
import json
import os
import shutil
import threading
import time
import unittest

from tests import _env
from tests._env import path, TMP, APP

import numpy as np

from easycut import (animations, catalog, compositor, extensions, filters, media, project, render, textrender)

EXT_SRC = os.path.join(_env.ROOT, "extensions")
PACKS = sorted(n for n in os.listdir(EXT_SRC) if not n.startswith(("_", ".")) and
               os.path.isfile(os.path.join(EXT_SRC, n, "manifest.json")))


def manifest(name):
    with open(os.path.join(EXT_SRC, name, "manifest.json"), encoding="utf-8") as f:
        return json.load(f)


def pump(n=5):
    for _ in range(n):
        APP.processEvents()


def zip_pack(name, version=None):
    """Pack zip bytes exactly as tools/build_extensions.py makes them."""
    import sys
    sys.path.insert(0, os.path.join(_env.ROOT, "tools"))
    from build_extensions import build_zip
    src = os.path.join(EXT_SRC, name)
    if version:
        src = os.path.join(TMP, "verpack", name)
        shutil.rmtree(src, ignore_errors=True)
        shutil.copytree(os.path.join(EXT_SRC, name), src)
        m = manifest(name)
        m["version"] = version
        with open(os.path.join(src, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(m, f)
    out = os.path.join(TMP, f"{name}.zip")
    build_zip(src, manifest(name)["id"], out)
    with open(out, "rb") as f:
        return f.read()


REGISTRIES = {
    "filter": lambda: filters.FILTERS, "effect": lambda: filters.EFFECTS,
    "transition": lambda: animations.TRANSITIONS, "animation": lambda: animations.ANIMATIONS,
    "text_style": lambda: textrender.STYLES, "font": lambda: textrender.FONTS,
}


class TestCatalog(unittest.TestCase):
    def setUp(self):
        catalog.reset()

    def test_bundled_catalog_matches_pack_folders(self):
        cat = {p["id"]: p for p in catalog.packs()}
        self.assertEqual(sorted(cat), sorted(manifest(n)["id"] for n in PACKS),
                         "assets/catalog is out of date - run tools/build_catalog.py")
        for name in PACKS:
            m = manifest(name)
            self.assertEqual(cat[m["id"]]["items"], m["items"], f"{name}: catalog items out of date")
            self.assertIn(m["category"], catalog.CATEGORIES)
            for it in m["items"]:
                self.assertIsNotNone(catalog.thumb_path(it["type"], it["id"]), f"no thumbnail for {it['id']}")

    def test_every_category_has_packs_of_about_five(self):
        for cat in catalog.CATEGORIES:
            packs = catalog.packs(cat)
            self.assertGreaterEqual(len(packs), 2, cat)
            for p in packs:
                self.assertEqual(len(p["items"]), 5, p["id"])

    def test_item_lookup(self):
        self.assertEqual(catalog.pack_for("transition", "dyn-spin")["id"], "dynamic-transitions")
        self.assertEqual(catalog.pack_for("font", "fnt-bungee")["category"], "Fonts")
        self.assertIsNone(catalog.pack_for("filter", "vivid"))       # built-in
        ids = [i for i, _, _ in catalog.items("text_style")]
        self.assertIn("txt-neon", ids)

    def test_manifest_merge_adds_new_packs_and_urls(self):
        catalog.merge_manifest([
            {"id": "cinematic-filters", "url": "http://x/c.zip", "sha256": "ab", "version": "1.0.1"},
            {"id": "brand-new", "name": "Brand New", "category": "Effects", "version": "1.0.0", "url": "u",
             "items": [{"type": "effect", "id": "bn-1", "name": "One"}]},
        ])
        self.assertEqual(catalog.pack("cinematic-filters")["url"], "http://x/c.zip")
        self.assertEqual(catalog.pack("cinematic-filters")["name"], "Cinematic Filters")   # kept
        self.assertEqual(catalog.pack_for("effect", "bn-1")["id"], "brand-new")
        self.assertIn("brand-new", [p["id"] for p in catalog.packs("Effects")])
        catalog.reset()


class TestPackItems(unittest.TestCase):
    """Load every pack from its zip and check each item works in both the preview and the export."""

    @classmethod
    def setUpClass(cls):
        for name in PACKS:
            ext, restart = extensions.install_zip(zip_pack(name))
            assert not ext.error, ext.error

    def test_packs_register_exactly_their_items(self):
        for name in PACKS:
            for it in manifest(name)["items"]:
                reg = REGISTRIES[it["type"]]()
                self.assertIn(it["id"], reg, f"{name} didn't register {it['id']}")

    def test_fonts_load(self):
        for fid in ("fnt-bungee", "fnt-press-start", "fnt-orbitron"):
            self.assertIn(fid, textrender.FONTS)
            from PyQt6.QtGui import QFontDatabase
            self.assertIn(textrender.FONTS[fid]["family"], QFontDatabase.families())

    def _compare(self, p, frames, tol, label):
        out = os.path.join(TMP, "pack_item.mp4")
        render.Renderer(p, render.RenderOptions(out_path=out, encoder="cpu")).run()
        comp = compositor.Compositor()
        W, H = 480, 270
        r = media.FrameReader(out, (W, H))
        try:
            for f in frames:
                t = f / 30
                d = np.abs(comp.compose(p, t, W, H).astype(int) - r.frame_at(t).astype(int)).mean()
                self.assertLess(d, tol, f"{label}: preview and export differ at t={t:.2f} ({d:.2f})")
        finally:
            r.close()
            comp.close()

    def test_every_transition(self):
        for tid, name, pack in catalog.items("transition"):
            p = project.Project()
            a = p.place(p.clip_from_media(media.probe(path("photo.png")), duration=1.5))
            a["filter"] = "bw"
            b = p.place(p.clip_from_media(media.probe(path("clip.mp4")), duration=1.5))
            b.update(trans_in=tid, trans_dur=0.8)
            self._compare(p, range(19, 47, 4), 5, name)

    def test_every_animation(self):
        for aid, name, pack in catalog.items("animation"):
            p = project.Project()
            p.place(p.clip_from_media(media.probe(path("photo.png")), duration=2.0))
            c = p.place(p.clip_from_media(media.probe(path("green.mp4")), duration=2.0), preferred_track=0, at=0)
            c.update(scale=0.5, anim_in=aid, anim_in_dur=1.0, anim_out=aid, anim_out_dur=0.6)
            self._compare(p, range(1, 60, 5), 5, name)

    def test_every_effect(self):
        for eid, name, pack in catalog.items("effect"):
            p = project.Project()
            c = p.place(p.clip_from_media(media.probe(path("clip.mp4")), duration=0.5))
            c["fx"] = [{"id": eid, "amount": 0.8}]
            # noise is random, and block/kernel effects land on a slightly different pixel grid in the small preview
            tol = 14 if eid in ("rfx-vhs", "rfx-grain") else 10 if eid in ("rfx-pixelate", "sfx-emboss") else 5
            self._compare(p, (3, 9), tol, name)

    def test_effect_keeps_green_screen_transparency(self):
        for eid in ("rfx-vignette", "sfx-glow", "sfx-blur"):
            p = project.Project()
            p.place(p.clip_from_media(media.probe(path("photo.png")), duration=0.5))
            c = p.place(p.clip_from_media(media.probe(path("green.mp4")), duration=0.5), preferred_track=0, at=0)
            c.update(chroma=True, fx=[{"id": eid, "amount": 0.6}])
            self._compare(p, (6,), 6, eid)

    def test_every_filter(self):
        for fid, name, pack in catalog.items("filter"):
            p = project.Project()
            c = p.place(p.clip_from_media(media.probe(path("photo.png")), duration=0.4))
            c["filter"] = fid
            self._compare(p, (5,), 3, name)

    def test_every_text_style_and_font(self):
        for sid, name, pack in catalog.items("text_style"):
            img = textrender.render(project.Clip(kind="text", text="Style", font_size=120, text_style=sid))
            self.assertGreater(int(img[:, :, 3].max()), 200, name)
        for fid, name, pack in catalog.items("font"):
            fam = textrender.FONTS[fid]["family"]
            img = textrender.render(project.Clip(kind="text", text="Font", font_size=120, font=fam))
            self.assertGreater(int(img[:, :, 3].max()), 200, name)
        p = project.Project()
        p.place(project.Clip(kind="text", text="Neon 123", font_size=140, text_style="txt-neon",
                             font=textrender.FONTS["fnt-bungee"]["family"], duration=0.4))
        # glowing text on black is the harshest case for comparing a small preview with a full-size export:
        # font smoothing differs slightly between the two sizes (more so with Windows' font rendering)
        self._compare(p, (5,), 6, "styled text")

    def test_typewriter_reveals_letters_over_time(self):
        c = project.Clip(kind="text", text="ABCD", duration=2, anim_in="tan-typewriter", anim_in_dur=1.0)
        amounts = [animations.state(c, t)["reveals"][0][1] for t in (0.1, 0.3, 0.6, 0.9, 1.5)]
        self.assertEqual(amounts[:4], [0.0, 0.25, 0.5, 0.75])
        self.assertEqual(amounts[4], 1.0)


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


class TestDownloadFlow(unittest.TestCase):
    """Locked item -> pack prompt -> download from the 'GitHub' manifest -> item applied."""

    @classmethod
    def setUpClass(cls):
        cls.root = os.path.join(TMP, "packserver")
        os.makedirs(cls.root, exist_ok=True)
        cls.entries = []
        for name in ("vibe-filters", "essential-transitions"):
            data = zip_pack(name)
            with open(os.path.join(cls.root, name + ".zip"), "wb") as f:
                f.write(data)
            m = manifest(name)
            cls.entries.append(dict(m, url="", sha256=hashlib.sha256(data).hexdigest(), size=len(data)))
        handler = lambda *a, **k: _Quiet(*a, directory=cls.root, **k)  # noqa: E731
        cls.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        for e, name in zip(cls.entries, ("vibe-filters", "essential-transitions")):
            e["url"] = f"{base}/{name}.zip"
        with open(os.path.join(cls.root, "manifest.json"), "w") as f:
            json.dump({"app": {"version": "1.0.0"}, "extensions": cls.entries}, f)
        cls.old_url = os.environ.get("EASYCUT_MANIFEST_URL")
        from easycut import updater
        cls.updater = updater
        cls.manifest_url = f"{base}/manifest.json"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def setUp(self):
        catalog.reset()
        for pid in ("vibe-filters", "essential-transitions"):
            extensions.uninstall(pid)
            extensions.loaded.pop(pid, None)
        extensions.apply_pending()
        for fid in [i for i, _, _ in catalog.items("filter")]:
            filters.FILTERS.pop(fid, None)
            if fid in filters.ORDER:
                filters.ORDER.remove(fid)

    def _patch_manifest(self):
        orig = self.updater.fetch_manifest
        self.updater.fetch_manifest = lambda url=None: orig(self.manifest_url)
        self.addCleanup(setattr, self.updater, "fetch_manifest", orig)

    def test_install_packs_fetches_manifest_when_needed(self):
        from easycut.ui.pack_dialog import install_packs
        self._patch_manifest()
        seen = []
        done, restart = install_packs(["vibe-filters"], lambda t, f: seen.append((t, f)))
        self.assertEqual(done, ["vibe-filters"])
        self.assertIn("vibe-neon", filters.FILTERS)
        self.assertTrue(any("Downloading" in t for t, _ in seen))
        self.assertAlmostEqual(seen[-1][1], 1.0)

    def test_tampered_download_is_refused(self):
        from easycut.ui.pack_dialog import install_packs
        catalog.merge_manifest([dict(self.entries[0], sha256="0" * 64)])
        with self.assertRaises(ValueError):
            install_packs(["vibe-filters"])
        self.assertNotIn("vibe-filters", extensions.installed())

    def test_locked_item_click_installs_and_applies(self):
        from easycut.ui.mainwindow import MainWindow
        from easycut.ui import pack_dialog
        self._patch_manifest()
        w = MainWindow(APP)
        w.show()
        pump()
        try:
            # the transition tile is locked before the pack is downloaded
            grid = w.library.transitions.grid
            self.assertTrue(grid.tiles["ess-zoom-in"].locked)
            w.add_to_timeline([path("photo.png"), path("clip.mp4")])
            clip = w.project.clips[-1]
            w.timeline.selected = [clip["id"]]
            w._selection_changed([clip["id"]])

            def run_dialog(dlg):
                dlg.start()
                t0 = time.time()
                while dlg.result() == 0 and time.time() - t0 < 30:
                    pump(2)
                    time.sleep(0.02)
                return dlg.result()
            orig = pack_dialog.PackDialog.exec
            pack_dialog.PackDialog.exec = run_dialog
            self.addCleanup(setattr, pack_dialog.PackDialog, "exec", orig)
            grid.tiles["ess-zoom-in"].click()
            pump()
            self.assertEqual(clip["trans_in"], "ess-zoom-in")
            self.assertIn("essential-transitions", extensions.installed())
            self.assertFalse(w.library.transitions.grid.tiles["ess-zoom-in"].locked)
            self.assertEqual(w.library.extensions.state("essential-transitions"), "installed")
            w.stop()
        finally:
            w.dirty = False
            w.close()
            pump()

    def test_extensions_page_categories(self):
        from easycut.ui.panels import ExtensionsPage
        page = ExtensionsPage()
        page.set_category("Fonts")
        self.assertIn("of 2 fonts packs installed", page.summary.text())
        cards = [page.cards.itemAt(i).widget() for i in range(page.cards.count())]
        ids = {c.pack_id for c in cards if hasattr(c, "pack_id")}
        self.assertEqual(ids, {"display-fonts", "retro-fonts"})
        self.assertTrue(page.get_all.isVisible() or not page.isVisible())
        page.set_category("All")
        cards = [page.cards.itemAt(i).widget() for i in range(page.cards.count())]
        self.assertGreaterEqual(len([c for c in cards if hasattr(c, "pack_id")]), 13)


if __name__ == "__main__":
    unittest.main()
