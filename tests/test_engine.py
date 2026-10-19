"""Engine tests: model, effects, filters, animations, preview vs export, rendering."""
import json
import os
import subprocess
import unittest

from tests import _env  # noqa: F401  (sets up Qt + temp data first)
from tests._env import path, TMP, ff

import numpy as np
import cv2

from easycut import (animations, compositor, effects, filters, formats, media, project, render, settings,
                     textrender)


def tmp(name):
    return os.path.join(TMP, name)


def read_frame(p, t, size):
    r = media.FrameReader(p, max_size=size)
    f = r.frame_at(t)
    r.close()
    return f


def ff_filter_png(src_png, vf, out_png):
    ff("-i", src_png, "-vf", vf, "-frames:v", "1", out_png)
    return media.read_image(out_png)


def synthetic(w=96, h=64):
    y, x = np.mgrid[0:h, 0:w]
    img = np.zeros((h, w, 3), np.uint8)
    img[..., 0] = (x * 255 / w).astype(np.uint8)
    img[..., 1] = (y * 255 / h).astype(np.uint8)
    img[..., 2] = ((x + y) * 127 / (w + h) + 64).astype(np.uint8)
    return img


class TestFormats(unittest.TestCase):
    def test_sizes_even_and_short_side(self):
        for a in formats.ASPECT_ORDER:
            for q, short in formats.QUALITIES.items():
                w, h = formats.canvas_size(a, q)
                self.assertEqual(w % 2, 0)
                self.assertEqual(h % 2, 0)
                self.assertAlmostEqual(min(w, h), short, delta=2)

    def test_named_sizes(self):
        self.assertEqual(formats.canvas_size("movie", "1080p"), (1920, 1080))
        self.assertEqual(formats.canvas_size("tiktok", "1080p"), (1080, 1920))
        self.assertEqual(formats.canvas_size("movie", "1440p"), (2560, 1440))
        self.assertEqual(formats.canvas_size("movie", "2160p"), (3840, 2160))
        self.assertEqual(formats.canvas_size("square", "1080p"), (1080, 1080))

    def test_friendly_and_true_names(self):
        self.assertIn("Movie Style", formats.aspect_label("movie"))
        self.assertIn("16:9", formats.aspect_label("movie"))
        self.assertIn("TikTok Style", formats.aspect_label("tiktok"))
        self.assertIn("9:16", formats.aspect_label("tiktok"))

    def test_fps_options(self):
        self.assertEqual(formats.FPS_OPTIONS, [10, 30, 60])


class TestMedia(unittest.TestCase):
    def test_probe_video(self):
        i = media.probe(path("clip.mp4"))
        self.assertEqual(i.kind, "video")
        self.assertEqual((i.width, i.height), (640, 360))
        self.assertTrue(i.has_audio)
        self.assertAlmostEqual(i.duration, 4.0, delta=0.15)
        self.assertAlmostEqual(i.fps, 30, delta=0.5)

    def test_probe_audio_and_image(self):
        a = media.probe(path("tone.mp3"))
        self.assertEqual(a.kind, "audio")
        self.assertTrue(a.has_audio)
        self.assertAlmostEqual(a.duration, 5.0, delta=0.2)
        im = media.probe(path("photo.png"))
        self.assertEqual(im.kind, "image")
        self.assertEqual((im.width, im.height), (400, 300))

    def test_frame_reader_and_seek(self):
        r = media.FrameReader(path("clip.mp4"), max_size=(320, 180))
        a = r.frame_at(0.5)
        b = r.frame_at(0.5 + 1 / 30)
        c = r.frame_at(3.0)
        d = r.frame_at(0.5)
        r.close()
        self.assertEqual(a.shape, (180, 320, 3))
        self.assertTrue(np.array_equal(a, d))
        self.assertGreater(np.abs(a.astype(int) - c.astype(int)).mean(), 1)
        self.assertIsNotNone(b)

    def test_thumbnail_and_waveform(self):
        t = media.thumbnail(path("clip.mp4"), (160, 90))
        self.assertEqual(t.shape[2], 4)
        w = media.waveform(path("tone.mp3"), 100)
        self.assertGreater(len(w), 50)
        self.assertAlmostEqual(max(w), 1.0, delta=0.01)

    def test_media_kind(self):
        self.assertEqual(media.media_kind("a.MP4"), "video")
        self.assertEqual(media.media_kind("a.wav"), "audio")
        self.assertEqual(media.media_kind("a.jpeg"), "image")
        self.assertEqual(media.media_kind("a.txt"), "")


class TestProject(unittest.TestCase):
    def make(self):
        p = project.Project()
        a = p.place(p.clip_from_media(media.probe(path("clip.mp4"))))
        b = p.place(p.clip_from_media(media.probe(path("photo.png")), duration=2))
        return p, a, b

    def test_place_appends_on_main_track(self):
        p, a, b = self.make()
        self.assertEqual(a["track"], b["track"])
        self.assertAlmostEqual(b["start"], a.end)
        self.assertAlmostEqual(p.duration(), a.end + 2)

    def test_audio_goes_to_audio_track(self):
        p, a, b = self.make()
        t = p.place(p.clip_from_media(media.probe(path("tone.mp3"))))
        self.assertEqual(p.tracks[t["track"]]["type"], "audio")

    def test_busy_track_creates_new_track(self):
        p, a, b = self.make()
        before = len(p.tracks_of("video"))
        c = p.clip_from_media(media.probe(path("clip.mp4")))
        for t in p.tracks_of("video"):
            p.place(project.Clip(kind="text", text="x", duration=10), preferred_track=t, at=0) \
                if p.track_free(t, 0, 10) else None
        p.place(c, at=0.5)
        self.assertGreater(len(p.tracks_of("video")), before)
        self.assertTrue(all(p.track_free(c["track"], c["start"], c.end, ignore=c) for _ in [0]))

    def test_split(self):
        p, a, b = self.make()
        right = p.split(a, 1.5)
        self.assertIsNotNone(right)
        self.assertAlmostEqual(a["duration"], 1.5)
        self.assertAlmostEqual(right["start"], 1.5)
        self.assertAlmostEqual(right["in_point"], 1.5)
        self.assertAlmostEqual(a.end, right["start"])
        self.assertIsNone(p.split(a, 0.01))

    def test_split_respects_speed(self):
        p, a, b = self.make()
        p.set_speed(a, 2.0)
        self.assertAlmostEqual(a["duration"], 2.0, delta=0.08)
        right = p.split(a, 1.0)
        self.assertAlmostEqual(right["in_point"], 2.0, delta=0.01)

    def test_set_speed_keeps_footage(self):
        p, a, b = self.make()
        span = a.source_span()
        p.set_speed(a, 0.5)
        self.assertAlmostEqual(a.source_span(), span, delta=0.01)
        self.assertAlmostEqual(a["duration"], span * 2, delta=0.01)

    def test_save_load_roundtrip(self):
        p, a, b = self.make()
        a["filter"] = "vivid"
        a["chroma"] = True
        f = tmp("rt.ecut")
        p.save(f)
        q = project.Project.load(f)
        self.assertEqual(q.name, "rt")
        self.assertEqual(len(q.clips), 2)
        self.assertEqual(q.clip(a["id"])["filter"], "vivid")
        self.assertTrue(q.clip(a["id"])["chroma"])
        with open(f, encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["app"], "Easy-Cut")

    def test_history(self):
        p, a, b = self.make()
        h = project.History(p)
        a["scale"] = 2.0
        self.assertTrue(h.commit(p))
        self.assertFalse(h.commit(p))
        q = h.undo()
        self.assertEqual(q.clip(a["id"])["scale"], 1.0)
        r = h.redo()
        self.assertEqual(r.clip(a["id"])["scale"], 2.0)

    def test_tracks_add_remove(self):
        p, a, b = self.make()
        old_track = a["track"]
        p.add_track("video")
        self.assertEqual(a["track"], old_track + 1)
        n = len(p.tracks)
        p.remove_track(0)
        self.assertEqual(len(p.tracks), n - 1)
        self.assertEqual(a["track"], old_track)
        only_audio = p.tracks_of("audio")
        p.remove_track(only_audio[0])     # last audio track can't be removed
        self.assertEqual(len(p.tracks_of("audio")), 1)

    def test_close_gaps(self):
        p, a, b = self.make()
        b["start"] = a.end + 3
        p.ripple_close(a["track"])
        self.assertAlmostEqual(b["start"], a.end)


class TestEffectsMatchExport(unittest.TestCase):
    """The preview maths must match FFmpeg's output closely."""

    @classmethod
    def setUpClass(cls):
        cls.src = tmp("syn.png")
        cv2.imwrite(cls.src, synthetic())

    def test_filters_match_ffmpeg(self):
        img = synthetic()
        for fid in filters.ORDER:
            for clip in ({"filter": fid, "filter_amount": 1.0},
                         {"filter": fid, "filter_amount": 0.5, "brightness": 0.2, "contrast": 1.3,
                          "saturation": 0.6}):
                chain = filters.ffmpeg_chain(clip)
                pv = filters.apply_preview(img.copy(), clip)
                if not chain:
                    self.assertTrue(np.array_equal(pv, img))
                    continue
                out = ff_filter_png(self.src, "format=rgba," + ",".join(chain) + ",format=rgb24", tmp(f"f_{fid}.png"))
                diff = np.abs(out[:, :, :3].astype(int) - pv.astype(int)).max()
                self.assertLessEqual(diff, 5, f"{fid} {clip} differs by {diff}")

    def test_chroma_matches_ffmpeg(self):
        img = np.zeros((64, 96, 3), np.uint8)
        img[:] = (0, 255, 0)
        img[16:48, 24:72] = (30, 30, 220)
        img[16:48, 40:56] = (60, 200, 60)      # greenish - partially keyed
        src = tmp("key.png")
        cv2.imwrite(src, img)
        clip = {"chroma": True, "chroma_color": "#00ff00", "chroma_similarity": 0.12, "chroma_blend": 0.08}
        pv = effects.apply_chroma(img.copy(), clip)
        out = ff_filter_png(src, "format=yuv444p," + effects.chroma_ffmpeg(clip)[0] + ",format=rgba", tmp("key_o.png"))
        diff = np.abs(out[:, :, 3].astype(int) - pv[:, :, 3].astype(int))
        self.assertLess(diff.mean(), 6)
        self.assertEqual(int(pv[2, 2, 3]), 0)
        self.assertEqual(int(pv[30, 30, 3]), 255)

    def test_crop_flip_mirror_sizes(self):
        img = synthetic(101, 67)
        src = tmp("odd.png")
        cv2.imwrite(src, img)
        for mirror in ("none", "left", "right", "top", "bottom"):
            clip = {"crop": [0.1, 0.05, 0.2, 0.1], "flip_h": True, "mirror": mirror}
            pv = effects.process_preview(img.copy(), clip)
            vf = ",".join(effects.crop_ffmpeg(clip, 101, 67) + effects.flip_ffmpeg(clip)) or "null"
            mg = effects.mirror_graph(clip, "x", "y", 0)
            if mg:
                graph = f"[0:v]{vf}[x];{mg}"
                out_p = tmp(f"m_{mirror}.png")
                ff("-i", src, "-filter_complex", graph, "-map", "[y]", "-frames:v", "1", out_p)
            else:
                out_p = tmp(f"m_{mirror}.png")
                ff("-i", src, "-vf", vf, "-frames:v", "1", out_p)
            out = media.read_image(out_p)
            self.assertEqual(out.shape[:2], pv.shape[:2], mirror)
            self.assertEqual(effects.content_size(clip, 101, 67), (pv.shape[1], pv.shape[0]))
            self.assertLess(np.abs(out[:, :, :3].astype(int) - pv[:, :, :3].astype(int)).mean(), 2, mirror)

    def test_atempo_chain(self):
        self.assertEqual(effects.atempo_chain(1.0), [])
        self.assertEqual(len(effects.atempo_chain(4.0)), 2)
        self.assertEqual(len(effects.atempo_chain(0.2)), 3)
        prod = 1.0
        for part in effects.atempo_chain(0.2):
            prod *= float(part.split("=")[1])
        self.assertAlmostEqual(prod, 0.2, places=4)

    def test_rotate_bounds(self):
        img = np.zeros((100, 200, 4), np.uint8)
        r = effects.rotate_bgra(img, 90)
        self.assertEqual(r.shape[:2], (200, 100))


class TestAnimations(unittest.TestCase):
    def test_in_out_progress(self):
        c = project.Clip(start=2.0, duration=4.0, anim_in="zoom", anim_in_dur=1.0, anim_out="fade", anim_out_dur=1.0)
        a, s, dx, dy = animations.state(c, 2.0)
        self.assertAlmostEqual(s, 0.55, places=3)
        self.assertAlmostEqual(a, 0.0)
        a, s, dx, dy = animations.state(c, 4.0)
        self.assertAlmostEqual((a, s), (1.0, 1.0))
        a, s, dx, dy = animations.state(c, 5.5)
        self.assertAlmostEqual(a, 0.5, places=3)

    def test_slides(self):
        c = project.Clip(start=0, duration=3, anim_in="slide_left", anim_in_dur=1.0)
        self.assertAlmostEqual(animations.state(c, 0)[2], -1.0)
        self.assertAlmostEqual(animations.state(c, 2)[2], 0.0)

    def test_ffmpeg_expressions(self):
        c = project.Clip(start=1, duration=3, anim_in="pop", anim_out="slide_up")
        ex = animations.ffmpeg_exprs(c)
        self.assertIn("sin", ex["scale"])
        self.assertIsNotNone(ex["dy"])
        self.assertIsNone(ex["dx"])
        self.assertEqual(animations.ffmpeg_exprs(project.Clip())["scale"], None)


class TestRender(unittest.TestCase):
    """Full exports through FFmpeg, compared with the preview compositor."""

    @classmethod
    def setUpClass(cls):
        p = project.Project()
        a = p.place(p.clip_from_media(media.probe(path("clip.mp4"))))
        a.update(filter="warm", crop=[0.05, 0, 0.05, 0], anim_in="zoom", anim_in_dur=0.8)
        g = p.clip_from_media(media.probe(path("green.mp4")))
        g.update(chroma=True, scale=0.45, x=0.22, y=0.15, rotation=12, opacity=0.9)
        p.place(g, preferred_track=0, at=0.4)
        im = p.clip_from_media(media.probe(path("photo.png")), duration=1.5)
        im.update(mirror="left", flip_v=True, anim_out="slide_right", fit="fill")
        p.place(im, at=a.end)
        t = project.Clip(kind="text", text="Hello", duration=2.0, anim_in="pop", y=-0.3)
        p.place(t, preferred_track=0, at=2.0)
        au = p.place(p.clip_from_media(media.probe(path("tone.mp3"))))
        au.update(start=0.5, volume=0.6, anim_out="fade")
        cls.p = p
        cls.out = tmp("render.mp4")
        render.Renderer(p, render.RenderOptions(out_path=cls.out, encoder="cpu")).run()

    def test_output_properties(self):
        i = media.probe(self.out)
        self.assertEqual((i.width, i.height), (1920, 1080))
        self.assertTrue(i.has_audio)
        self.assertAlmostEqual(i.duration, self.p.duration(), delta=0.1)

    def test_preview_matches_export(self):
        comp = compositor.Compositor()
        W, H = formats.preview_size("movie")
        for t in (0.3, 0.9, 1.6, 2.5, 3.2, 4.6, 5.2):
            pv = comp.compose(self.p, t, W, H)
            rd = read_frame(self.out, t, (W, H))
            d = np.abs(pv.astype(int) - rd.astype(int)).mean()
            self.assertLess(d, 6, f"t={t}: preview and export differ (mean {d:.2f})")
        comp.close()

    def test_tiktok_gif_10fps(self):
        out = tmp("r.gif")
        render.Renderer(self.p, render.RenderOptions(aspect="tiktok", fps=10, fmt="gif", out_path=out)).run()
        i = media.probe(out)
        self.assertEqual((i.width, i.height), (1080, 1920))
        self.assertAlmostEqual(i.fps, 10, delta=0.5)

    def test_webm_and_60fps(self):
        out = tmp("r.webm")
        render.Renderer(self.p, render.RenderOptions(aspect="square", fps=60, fmt="webm", out_path=out)).run()
        i = media.probe(out)
        self.assertEqual((i.width, i.height), (1080, 1080))
        self.assertAlmostEqual(i.fps, 60, delta=1)

    def test_1440p(self):
        p = project.Project()
        p.place(p.clip_from_media(media.probe(path("clip.mp4")), duration=1.0))
        out = tmp("r1440.mp4")
        render.Renderer(p, render.RenderOptions(quality="1440p", out_path=out, encoder="cpu")).run()
        self.assertEqual((media.probe(out).width, media.probe(out).height), (2560, 1440))

    def test_progress_and_cancel(self):
        seen = []
        p = project.Project()
        p.place(p.clip_from_media(media.probe(path("clip.mp4"))))
        out = tmp("cancel.mp4")
        r = render.Renderer(p, render.RenderOptions(quality="2160p", fps=60, out_path=out, encoder="cpu"))

        def prog(ph, f, eta=None):
            seen.append(f)
            if f > 0.05:
                r.cancel()
        with self.assertRaises(render.RenderCancelled):
            r.run(prog)
        self.assertFalse(os.path.exists(out))
        r.cleanup()

    def test_speed_and_pitch_audio(self):
        p = project.Project()
        c = p.place(p.clip_from_media(media.probe(path("tone.mp3"))))
        p.set_speed(c, 2.0)
        c["pitch"] = 12
        p.place(project.Clip(kind="text", text="x", duration=c["duration"]))
        out = tmp("speed.mp4")
        render.Renderer(p, render.RenderOptions(out_path=out, encoder="cpu")).run()
        self.assertAlmostEqual(media.probe(out).duration, 2.5, delta=0.1)
        # dominant frequency of a 220 Hz tone shifted up an octave is ~440 Hz
        r = subprocess.run([media.ffmpeg_exe(), "-v", "error", "-i", out, "-ac", "1", "-ar", "8000", "-f", "s16le",
                            "-"], capture_output=True)
        a = np.frombuffer(r.stdout, np.int16).astype(float)[2000:10000]
        freqs = np.fft.rfftfreq(len(a), 1 / 8000)
        peak = freqs[np.argmax(np.abs(np.fft.rfft(a)))]
        self.assertAlmostEqual(peak, 440, delta=15)

    def test_tape_speed_changes_pitch(self):
        p = project.Project()
        c = p.place(p.clip_from_media(media.probe(path("tone.mp3"))))
        p.set_speed(c, 0.5)
        c["keep_pitch"] = False
        out = tmp("tape.wav")
        self.assertTrue(render.render_audio_preview(p, out))
        r = subprocess.run([media.ffmpeg_exe(), "-v", "error", "-i", out, "-ac", "1", "-ar", "8000", "-f", "s16le",
                            "-"], capture_output=True)
        a = np.frombuffer(r.stdout, np.int16).astype(float)[4000:20000]
        freqs = np.fft.rfftfreq(len(a), 1 / 8000)
        self.assertAlmostEqual(freqs[np.argmax(np.abs(np.fft.rfft(a)))], 110, delta=8)

    def test_stabilize_renders(self):
        p = project.Project()
        c = p.place(p.clip_from_media(media.probe(path("clip.mp4")), duration=2.0))
        c["stabilize"] = True
        out = tmp("stab.mp4")
        render.Renderer(p, render.RenderOptions(out_path=out, encoder="cpu")).run()
        self.assertAlmostEqual(media.probe(out).duration, 2.0, delta=0.1)

    def test_empty_timeline_errors(self):
        with self.assertRaises(render.RenderError):
            render.Renderer(project.Project(), render.RenderOptions(out_path=tmp("x.mp4"))).run()

    def test_hidden_track_and_muted(self):
        p = project.Project()
        c = p.place(p.clip_from_media(media.probe(path("clip.mp4")), duration=1.0))
        p.tracks[c["track"]]["hidden"] = True
        p.place(project.Clip(kind="text", text="only", duration=1.0), preferred_track=0, at=0)
        c["muted"] = True
        r = render.Renderer(p, render.RenderOptions(out_path=tmp("h.mp4")))
        self.assertEqual([x["kind"] for x in r.visual_clips()], ["text"])
        self.assertEqual(r.audio_clips(), [])

    def test_text_render_size_scales(self):
        c = project.Clip(kind="text", text="Scale me", font_size=80)
        a = textrender.render(c, 1.0)
        b = textrender.render(c, 2.0)
        self.assertAlmostEqual(b.shape[0] / a.shape[0], 2.0, delta=0.15)
        self.assertGreater(a[:, :, 3].max(), 200)

    def test_portrait_rotation_metadata(self):
        out = tmp("rot.mp4")
        ff("-display_rotation", "90", "-i", path("portrait_src.mp4"), "-c", "copy", out)
        i = media.probe(out)
        self.assertGreater(i.height, i.width)


class TestSettings(unittest.TestCase):
    def test_persist(self):
        settings.set("snap", False)
        settings.reset_cache()
        self.assertFalse(settings.get("snap"))
        settings.set("snap", True)

    def test_data_dir_is_private(self):
        from easycut.config import app_data_dir
        self.assertTrue(app_data_dir().startswith(TMP))


if __name__ == "__main__":
    unittest.main()
