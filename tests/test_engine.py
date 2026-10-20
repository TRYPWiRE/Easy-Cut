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
        st = animations.state(c, 2.0)
        self.assertAlmostEqual(st["scale"], 0.55, places=3)
        self.assertAlmostEqual(st["alpha"], 0.0)
        st = animations.state(c, 4.0)
        self.assertAlmostEqual((st["alpha"], st["scale"]), (1.0, 1.0))
        self.assertAlmostEqual(animations.state(c, 5.5)["alpha"], 0.5, places=3)

    def test_slides(self):
        c = project.Clip(start=0, duration=3, anim_in="slide_left", anim_in_dur=1.0)
        self.assertAlmostEqual(animations.state(c, 0)["dx"], -1.0)
        self.assertAlmostEqual(animations.state(c, 2)["dx"], 0.0)

    def test_ffmpeg_expressions(self):
        c = project.Clip(start=1, duration=3, anim_in="pop", anim_out="slide_up")
        ex = animations.ffmpeg_exprs(c)
        self.assertIn("sin", ex["scale"])
        self.assertIsNotNone(ex["dy"])
        self.assertIsNone(ex["dx"])
        self.assertIsNone(ex["rot"])
        self.assertEqual(animations.ffmpeg_exprs(project.Clip())["scale"], None)

    def test_expression_variables_dont_clash(self):
        # "PI" must not be treated as the progress variable P
        m = animations.Motion("t", "t", scale="(1+0*sin(PI*P))", rot="(10*E)")
        text = animations._ff(m.scale, "EE", "PP")
        self.assertIn("PI", text)
        self.assertIn("(PP)", text)

    def test_transition_pre_roll(self):
        a = project.Clip(start=0, duration=2)
        b = project.Clip(start=2, duration=2, trans_in="dissolve", trans_dur=0.8)
        self.assertAlmostEqual(animations.pre_roll(b), 0.8)
        self.assertAlmostEqual(b.vis_start, 1.2)
        self.assertAlmostEqual(animations.state(b, 1.6)["alpha"], 0.5, places=3)
        self.assertAlmostEqual(animations.pre_roll(a), 0.0)
        # a transition can't start before the timeline does
        c = project.Clip(start=0.3, duration=2, trans_in="dissolve", trans_dur=1.0)
        self.assertAlmostEqual(animations.pre_roll(c), 0.3)

    def test_transition_replaces_in_animation(self):
        b = project.Clip(start=2, duration=2, trans_in="slide", anim_in="zoom")
        kinds = [k for _, k, _, _ in animations.windows(b)]
        self.assertEqual(kinds, ["trans"])

    def test_dip_veil(self):
        b = project.Clip(start=2, duration=2, trans_in="dip_black", trans_dur=1.0)
        self.assertAlmostEqual(animations.state(b, 1.5)["veil"][1], 1.0, places=3)
        self.assertEqual(animations.state(b, 1.2)["alpha"], 0.0)
        self.assertAlmostEqual(animations.visible_from(b), 1.5)

    def test_split_drops_transition_on_right_piece(self):
        p = project.Project()
        a = p.place(project.Clip(kind="text", text="a", duration=2))
        b = p.place(project.Clip(kind="text", text="b", duration=4, trans_in="dissolve"))
        right = p.split(b, b["start"] + 1)
        self.assertEqual(b["trans_in"], "dissolve")
        self.assertEqual(right["trans_in"], "none")
        self.assertIsNotNone(a)


class TestTransitionRender(unittest.TestCase):
    def test_transitions_match_preview(self):
        for tid in ("dissolve", "dip_black", "slide"):
            p = project.Project()
            a = p.place(p.clip_from_media(media.probe(path("photo.png")), duration=1.5))
            a["filter"] = "bw"
            b = p.place(p.clip_from_media(media.probe(path("clip.mp4")), duration=1.5))
            b.update(trans_in=tid, trans_dur=0.8)
            out = tmp(f"tr_{tid}.mp4")
            render.Renderer(p, render.RenderOptions(out_path=out, encoder="cpu")).run()
            self.assertAlmostEqual(media.probe(out).duration, 3.0, delta=0.1)
            comp = compositor.Compositor()
            W, H = 480, 270
            r = media.FrameReader(out, (W, H))
            for f in range(20, 50, 3):          # exact frame times through the transition
                t = f / 30
                d = np.abs(comp.compose(p, t, W, H).astype(int) - r.frame_at(t).astype(int)).mean()
                self.assertLess(d, 5, f"{tid} t={t:.2f} differs by {d:.2f}")
            r.close()
            comp.close()


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


class TestExportFormats(unittest.TestCase):
    """v2 export: every format, rate control, range, loudness and the audio tools."""

    @classmethod
    def setUpClass(cls):
        p = project.Project()
        v = p.place(p.clip_from_media(media.probe(path("clip.mp4"))))
        v["duration"] = 1.5
        au = p.place(p.clip_from_media(media.probe(path("tone.mp3"))))
        au.update(duration=1.5, afade_in=0.3, afade_out=0.3, eq_low=3.0, eq_high=-2.0, pan=0.4, compress=True,
                  denoise=0.3, reverb=0.2)
        cls.p = p

    def _render(self, fmt, name, **extra):
        from easycut import exportfmt
        s = exportfmt.settings_for(fmt=fmt, resolution="480p", fps=15, encoder="cpu", **extra)
        out = tmp(name + exportfmt.FORMATS[fmt]["ext"])
        r = render.Renderer(self.p, render.RenderOptions(settings=s, out_path=out))
        r.run()
        return r, out

    def test_every_format(self):
        from easycut import exportfmt
        for fmt, info in exportfmt.FORMATS.items():
            if fmt in ("webm_av1",):
                continue                     # slow; covered by the encoder availability check below
            with self.subTest(fmt=fmt):
                r, out = self._render(fmt, "fmt_" + fmt)
                if info["kind"] == "image":
                    folder = os.path.splitext(out)[0]
                    self.assertTrue(any(f.endswith(".png") for f in os.listdir(folder)))
                    continue
                self.assertGreater(os.path.getsize(out), 1000)
                if fmt == "webp_anim":
                    continue                 # FFmpeg can't read animated WebP back, only write it
                i = media.probe(out)
                self.assertAlmostEqual(i.duration, 1.5, delta=0.25)
                if info["kind"] == "audio":
                    self.assertTrue(i.has_audio)
                    self.assertFalse(i.has_video)
                elif info.get("acodec"):
                    self.assertTrue(i.has_audio and i.has_video)

    def test_target_size_two_pass(self):
        r, out = self._render("mp4_h264", "target", rate_mode="size", target_mb=0.25)
        self.assertLess(os.path.getsize(out), 0.25 * 1024 * 1024 * 1.15)

    def test_range_export(self):
        r, out = self._render("mp4_h264", "range", range="custom", range_start=0.5, range_end=1.25)
        self.assertAlmostEqual(media.probe(out).duration, 0.75, delta=0.15)

    def test_loudness(self):
        r, out = self._render("wav", "loud", loudness="streaming")
        self.assertTrue(media.probe(out).has_audio)

    def test_audio_fx_chain(self):
        c = self.p.clips_on(self.p.tracks_of("audio")[0])[0]
        self.assertTrue(effects.has_audio_fx(c))
        chain = effects.audio_fx_chain(c, 1.5)
        joined = ",".join(chain) if isinstance(chain, list) else chain
        for part in ("afftdn", "acompressor", "aecho", "afade"):
            self.assertIn(part, joined)

    def test_presets_and_estimate(self):
        from easycut import exportfmt
        for pr in exportfmt.PRESETS:
            pid = pr[0]
            s = exportfmt.preset_settings(pid, 30, "movie")
            self.assertIn(s["fmt"], exportfmt.FORMATS)
            self.assertGreater(exportfmt.estimate_bytes(s, 10.0), 0)


class TestCapture(unittest.TestCase):
    def test_parse_dshow_devices(self):
        from easycut import capture
        text = '''[dshow @ 0x1] "Integrated Camera" (video)
[dshow @ 0x1]   Alternative name "@device_pnp_\\?\\usb#vid"
[dshow @ 0x1] "OBS Virtual Camera" (video)
[dshow @ 0x1] "Microphone (Realtek(R) Audio)" (audio)
[dshow @ 0x1]   Alternative name "@device_cm_{33D9A762}"
[dshow @ 0x1] "Microphone (Realtek(R) Audio)" (audio)'''
        d = capture.parse_dshow_devices(text)
        self.assertEqual(d["video"], ["Integrated Camera", "OBS Virtual Camera"])
        self.assertEqual(d["audio"], ["Microphone (Realtek(R) Audio)"])
        old = '''[dshow @ 0x2] DirectShow video devices (some may be both video and audio devices)
[dshow @ 0x2]  "USB Cam"
[dshow @ 0x2] DirectShow audio devices
[dshow @ 0x2]  "Mic 1"'''
        d = capture.parse_dshow_devices(old)
        self.assertEqual(d, {"video": ["USB Cam"], "audio": ["Mic 1"]})

    def test_commands(self):
        from easycut import capture
        mon = {"x": 0, "y": 0, "w": 2560, "h": 1440, "primary": True, "index": 0}
        cfg = capture.CaptureConfig(monitor=mon, webcam="Cam", mic="Mic", out_dir=TMP, basename="R",
                                    encoder="cpu", scale="1080p")
        args, outs, enc = capture.build_command(cfg, "dxgi")
        joined = " ".join(args)
        self.assertIn("ddagrab", joined)
        self.assertIn("hwdownload", joined)
        self.assertIn("video=Cam", joined)
        self.assertIn("audio=Mic", joined)
        self.assertEqual(set(outs), {"screen", "webcam", "mic"})
        args, outs, enc = capture.build_command(cfg, "gdi")
        self.assertIn("gdigrab", args)
        self.assertIn("2560x1440", args)

    def test_pip_corners(self):
        from easycut import capture
        x, y, s = capture.pip_transform(1920, 1080, 1280, 720, 0.25, "tl")
        self.assertLess(x, 0)
        self.assertLess(y, 0)
        self.assertAlmostEqual(s, 0.25, places=3)
        x, y, s = capture.pip_transform(1920, 1080, 1280, 720, 0.25, "br")
        self.assertGreater(x, 0)
        self.assertGreater(y, 0)
        self.assertLess(x + 0.125, 0.5)                 # stays inside the canvas

    def test_system_audio_wall_clock(self):
        """Loopback delivers nothing in silence; the file must still match real time."""
        import time as _t
        from easycut import capture

        class Rec:
            def __init__(self):
                self.n = 0

            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

            def record(self, numframes):
                self.n += 1
                _t.sleep(0.25 if self.n % 3 == 0 else numframes / 48000)   # gaps, like a silent PC
                return np.zeros((numframes, 2), np.float32)

        class Backend:
            def recorder(self, sr, ch):
                return Rec()
        out = tmp("loop.wav")
        r = capture.SystemAudioRecorder(out, Backend())
        t0 = _t.perf_counter()
        r.start()
        _t.sleep(1.5)
        r.stop()
        real = _t.perf_counter() - t0
        self.assertAlmostEqual(r.frames / 48000, real, delta=0.35)


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
