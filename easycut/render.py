"""Export: turns the whole timeline into one FFmpeg filter graph and encodes it.

FFmpeg does every pixel operation in native, multi-threaded code (and can use the GPU's video encoder),
which keeps exports fast and light compared with compositing frames in Python. The same audio chain is used
for the preview mix, so what you hear while editing is what gets exported.
"""
import hashlib
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

from . import animations, effects, exportfmt, filters, media, textrender
from .config import cache_dir

BELOW_NORMAL = 0x00004000 if sys.platform == "win32" else 0


class RenderCancelled(Exception):
    pass


class RenderError(Exception):
    pass


class RenderOptions:
    """What to export and how. Wraps an export-settings dict (see exportfmt.DEFAULTS).

    The short keyword form (aspect, quality, fps, fmt...) is kept for simple uses and older code."""

    def __init__(self, aspect="movie", quality="1080p", fps=30, fmt="mp4_h264", out_path="", encoder="auto",
                 audio=True, low_impact=True, settings=None, name=""):
        s = exportfmt.settings_for(fmt=fmt, aspect=aspect, resolution=quality, fps=int(fps), encoder=encoder,
                                   include_audio=audio)
        if settings:
            s.update(settings)
            s["fmt"] = exportfmt.LEGACY.get(s["fmt"], s["fmt"])
        self.s = s
        self.out_path = out_path
        self.low_impact = low_impact
        self.name = name

    # convenient views
    @property
    def fmt(self):
        return self.s["fmt"]

    @property
    def fps(self):
        return int(self.s.get("fps", 30))

    @property
    def encoder(self):
        return self.s.get("encoder", "auto")

    @encoder.setter
    def encoder(self, v):
        self.s["encoder"] = v

    @property
    def audio(self):
        return exportfmt.has_audio(self.fmt) and self.s.get("include_audio", True)

    @property
    def aspect(self):
        return self.s.get("aspect", "movie")

    @property
    def size(self):
        return exportfmt.frame_size(self.s)

    @property
    def kind(self):
        return exportfmt.kind(self.fmt)


def _q(expr):
    """Quote an expression for use as a filter option value."""
    return "'" + expr.replace("'", "\\'") + "'"


_script_flag = None


def script_flag():
    """'-/filter_complex' on FFmpeg 7+, '-filter_complex_script' on older builds."""
    global _script_flag
    if _script_flag is None:
        try:
            out = media.run(["-version"], timeout=15).stdout.decode("utf-8", "replace")
            m = re.search(r"ffmpeg version n?(\d+)", out)
            major = int(m.group(1)) if m else 0
        except Exception:
            major = 0
        _script_flag = "-/filter_complex" if major >= 7 else "-filter_complex_script"
    return _script_flag


def pick_encoder(opts):
    """Which video encoder to use (None for formats that only have one)."""
    f = exportfmt.fmt(opts.fmt)
    codec = f.get("codec")
    if codec not in ("h264", "hevc"):
        return None
    lib = "libx264" if codec == "h264" else "libx265"
    if opts.encoder == "cpu":
        return lib
    hw = [e for e, _ in media.hardware_encoders()]
    if codec == "hevc":
        hw = [e.replace("h264_", "hevc_") for e in hw]
    want = opts.encoder.replace("h264_", "hevc_") if codec == "hevc" else opts.encoder
    if want in hw:
        return want
    if opts.encoder == "auto" and hw and opts.s.get("rate_mode") != "size":
        return hw[0]
    return lib


def audio_clip_chain(c, rate, src_offset=0.0):
    """Everything between a clip's source sound and the mix: trim, speed/pitch, mixing-desk effects, fades,
    placement on the timeline. Shared by the export and the preview mix."""
    chain = []
    if src_offset > 0.0005:
        chain.append(f"atrim=start={src_offset:.4f}")
    chain.append("asetpts=PTS-STARTPTS")
    chain += effects.audio_speed_pitch(c, c.get("sample_rate") or 48000)
    chain.append(f"atrim=duration={c['duration']:.4f}")
    chain += effects.audio_fx_chain(c, float(c["duration"]))
    for typ, st, d in animations.audio_fades(c):
        chain.append(f"afade=t={typ}:st={st - c['start']:.4f}:d={d:.4f}")
    chain.append(f"aresample={rate}")
    chain.append("aformat=sample_fmts=fltp:channel_layouts=stereo")
    ms = int(round(c["start"] * 1000))
    if ms > 0:
        chain.append(f"adelay={ms}:all=1")
    return chain


def audible_clips(project):
    """Clips whose sound is heard: respects mute, hidden video tracks and solo."""
    solo = project.soloed()
    out = []
    for c in sorted(project.clips, key=lambda c: (c["track"], c["start"])):
        tr = project.tracks[c["track"]] if c["track"] < len(project.tracks) else {}
        if tr.get("muted") or c.get("muted") or float(c.get("volume", 1)) <= 0.0001:
            continue
        if tr.get("type") == "video" and tr.get("hidden"):
            continue
        if solo and c["track"] not in solo:
            continue
        if c.has_sound and c["duration"] > 0.01:
            out.append(c)
    return out


class Renderer:
    def __init__(self, project, opts: RenderOptions):
        self.project = project
        self.opts = opts
        self.proc = None
        self.cancelled = False
        self.workdir = tempfile.mkdtemp(prefix="render_", dir=cache_dir("render"))
        self.log = []
        self.encoder = None
        self.src_from = {}

    # ----------------------------------------------------------------- what to render
    def visual_clips(self):
        out = []
        for ti in self.project.video_track_indices_bottom_up():
            if self.project.tracks[ti]["hidden"]:
                continue
            out += [c for c in self.project.clips_on(ti) if c.is_visual and c["duration"] > 0.01]
        return out

    def audio_clips(self):
        return audible_clips(self.project)

    def span(self):
        """(start, end) of the part of the timeline being exported."""
        D = max(0.1, self.project.duration())
        s = self.opts.s
        if s.get("range") in ("custom", "selection"):
            a = max(0.0, min(float(s.get("range_start", 0)), D))
            b = max(0.0, min(float(s.get("range_end", D)), D))
            if b - a > 0.05:
                return a, b
        return 0.0, D

    def _trf_name(self, clip):
        key = f"{clip['path']}|{os.path.getmtime(clip['path']) if os.path.exists(clip['path']) else 0}|" \
              f"{clip['in_point']:.3f}|{clip.source_span():.3f}|{effects.stabilize_strength(clip)}"
        return "stab_" + hashlib.sha1(key.encode()).hexdigest()[:16] + ".trf"

    def prepare(self, progress=None):
        """Text images and stabilization analysis passes. Returns nothing; raises on cancel."""
        self.text_files, self.text_sizes = {}, {}
        if self.opts.kind == "audio":
            return
        W, H = self.opts.size
        scale = min(W, H) / 1080.0
        self.text_files = {}
        self.text_sizes = {}
        for c in self.visual_clips():
            if c["kind"] == "text":
                p = os.path.join(self.workdir, f"text_{c['id']}.png")
                self.text_sizes[c["id"]] = textrender.save_png(c, scale, p)
                self.text_files[c["id"]] = p
        stab = [c for c in self.visual_clips() if c.get("stabilize") and c["kind"] == "video"]
        self.use_vidstab = media.has_filter("vidstabdetect") and media.has_filter("vidstabtransform")
        self.stab_dir = cache_dir("stabilize")
        if not self.use_vidstab:
            return
        for i, c in enumerate(stab):
            name = self._trf_name(c)
            if os.path.exists(os.path.join(self.stab_dir, name)):
                continue
            shakiness, _ = effects.stabilize_strength(c)
            args = [media.ffmpeg_exe(), "-hide_banner", "-nostdin", "-loglevel", "error", "-ss",
                    f"{c['in_point']:.4f}", "-t", f"{c.source_span() + 0.1:.4f}", "-i", c["path"], "-an", "-vf",
                    f"vidstabdetect=shakiness={shakiness}:accuracy=12:result={name}", "-f", "null", "-"]
            if progress:
                progress(f"Analysing camera shake ({i + 1}/{len(stab)})", i / max(1, len(stab)))
            self._run_simple(args, cwd=self.stab_dir)

    def _run_simple(self, args, cwd=None):
        self.proc = subprocess.Popen(args, cwd=cwd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                     creationflags=media.NO_WINDOW | BELOW_NORMAL)
        _, err = self.proc.communicate()
        self.proc.stderr.close()
        if self.cancelled:
            raise RenderCancelled()
        if self.proc.returncode != 0:
            raise RenderError(err.decode("utf-8", "replace")[-2000:])


    def build(self, with_audio=True):
        """(input args, filter graph text, video label or None, audio label or None, output duration)."""
        W, H = self.opts.size
        fps = self.opts.fps
        D = max(0.1, self.project.duration())
        a0, a1 = self.span()
        inputs, graph = [], []
        input_index = {}
        n = 0
        self.src_from = {}

        def add_input(args, key):
            nonlocal n
            inputs.extend(args)
            input_index[key] = n
            n += 1
            return n - 1

        vout = None
        if self.opts.kind != "audio":
            base = "base"
            bg = self.project.background.lstrip("#")
            graph.append(f"color=c=0x{bg}:s={W}x{H}:r={fps}:d={D:.4f},format=yuv420p[{base}]")
            prev = base
            for ci, c in enumerate(self.visual_clips()):
                pre = animations.pre_roll(c)
                vis_start = c["start"] - pre
                total = c["duration"] + pre                     # how long the layer is on screen
                speed = max(0.05, float(c.get("speed", 1.0))) if c["kind"] == "video" else 1.0
                missing = 0.0                                   # pre-roll seconds with no footage before in_point
                if c["kind"] == "video":
                    if not os.path.exists(c["path"]):
                        continue
                    src_from = c["in_point"] - pre * speed
                    if src_from < 0:
                        missing = -src_from / speed
                        src_from = 0.0
                    self.src_from[c["id"]] = src_from
                    span = c["in_point"] + c.source_span() - src_from
                    k = add_input(["-ss", f"{src_from:.4f}", "-t", f"{span + 0.1:.4f}", "-i", c["path"]], c["id"])
                elif c["kind"] == "image":
                    if not os.path.exists(c["path"]):
                        continue
                    k = add_input(["-loop", "1", "-framerate", str(fps), "-t", f"{total + 0.1:.4f}",
                                   "-i", c["path"]], c["id"])
                else:
                    k = add_input(["-loop", "1", "-framerate", str(fps), "-t", f"{total + 0.1:.4f}",
                                   "-i", self.text_files[c["id"]]], c["id"])
                lbl = f"v{ci}"
                chain = []
                if c["kind"] == "video" and c.get("stabilize"):
                    shakiness, smoothing = effects.stabilize_strength(c)
                    trf = os.path.join(getattr(self, "stab_dir", ""), self._trf_name(c))
                    if getattr(self, "use_vidstab", False) and os.path.exists(trf) and missing == 0 and pre == 0:
                        rel = os.path.relpath(trf, self.workdir).replace("\\", "/")
                        # pin planar YUV around vidstab: letting it negotiate packed RGBA crashes FFmpeg
                        chain.append("format=yuv420p")
                        chain.append(f"vidstabtransform=input={rel}:smoothing={smoothing}:optzoom=1:interpol=bicubic")
                        chain.append("format=yuv420p")
                    else:
                        r = 8 + int(effects.stabilize_strength(c)[0] * 3)
                        chain.append("format=yuv420p")
                        chain.append(f"deshake=rx={min(64, r * 2)}:ry={min(64, r * 2)}:edge=mirror")
                        chain.append("format=yuv420p")
                chain.append(f"setpts=(PTS-STARTPTS)/{speed:.6f}")
                chain.append(f"fps={fps}")
                if missing > 0.0005:
                    chain.append(f"tpad=start_duration={missing:.4f}:start_mode=clone")
                chain.append(f"trim=duration={total:.4f}")
                sw = c.get("src_w") or W
                sh = c.get("src_h") or H
                if c["kind"] == "text":
                    sw, sh = self.text_sizes[c["id"]]
                chain += effects.crop_ffmpeg(c, sw, sh)
                chain += effects.flip_ffmpeg(c)
                graph.append(f"[{k}:v]" + ",".join(chain) + f"[{lbl}a]")
                cur = f"{lbl}a"
                mg = effects.mirror_graph(c, cur, f"{lbl}m", ci)
                if mg:
                    graph.append(mg)
                    cur = f"{lbl}m"
                cw, ch = effects.content_size(c, sw, sh)
                look = filters.ffmpeg_chain(c, cw, ch, lbl)
                if any(isinstance(x, tuple) for x in look):
                    # effects with their own sub-graph: run the colour/effect stage as a separate segment
                    pre_chain = ",".join(effects.chroma_ffmpeg(c) + ["format=rgba"])
                    graph.append(f"[{cur}]{pre_chain}[{lbl}k]")
                    graph.append(filters.chain_to_graph(look + ["format=rgba"], f"{lbl}k", f"{lbl}l", lbl))
                    cur = f"{lbl}l"
                    chain = []
                else:
                    chain = effects.chroma_ffmpeg(c) + ["format=rgba"] + look + ["format=rgba"]
                fw, fh = effects.fitted_size(c, cw, ch, W, H, text_scale=1.0)
                fw, fh = max(2, int(round(fw / 2)) * 2), max(2, int(round(fh / 2)) * 2)
                chain.append(f"scale={fw}:{fh}:flags=bicubic")
                chain.append(f"setpts=PTS+{vis_start:.4f}/TB")
                op = float(c.get("opacity", 1.0))
                if op < 0.999:
                    chain.append(f"colorchannelmixer=aa={max(0.0, op):.4f}")
                chain += animations.reveal_ffmpeg(c)
                ex = animations.ffmpeg_exprs(c)
                rot = float(c.get("rotation", 0.0))
                if abs(rot) > 0.01 and not ex["rot"]:
                    ar = math.radians(rot)
                    nw = int(abs(fw * math.cos(ar)) + abs(fh * math.sin(ar)) + 0.5) // 2 * 2 + 2
                    nh = int(abs(fw * math.sin(ar)) + abs(fh * math.cos(ar)) + 0.5) // 2 * 2 + 2
                    chain.append(f"rotate=a={ar:.6f}:ow={nw}:oh={nh}:c=black@0:bilinear=1")
                if ex["scale"]:
                    sw_expr = "max(2,trunc(iw*(%s)/2)*2)" % ex["scale"]
                    sh_expr = "max(2,trunc(ih*(%s)/2)*2)" % ex["scale"]
                    chain.append(f"scale=w={_q(sw_expr)}:h={_q(sh_expr)}:eval=frame")
                if ex["rot"]:
                    ms = animations.max_scale(c)
                    bw = int(math.ceil(fw * ms / 2)) * 2 + 2
                    bh = int(math.ceil(fh * ms / 2)) * 2 + 2
                    if ex["scale"]:
                        # fixed-size box so the rotation sees one frame size
                        chain.append(f"pad=w={bw}:h={bh}:x=(ow-iw)/2:y=(oh-ih)/2:color=black@0:eval=frame")
                    else:
                        bw, bh = fw, fh
                    diag = int(math.ceil(math.hypot(bw, bh) / 2)) * 2 + 2
                    a_expr = f"({rot:.4f}+{ex['rot']})*PI/180"
                    chain.append(f"rotate=a={_q(a_expr)}:ow={diag}:oh={diag}:c=black@0:bilinear=1")
                for typ, st, d in animations.fades(c):
                    chain.append(f"fade=t={typ}:st={st:.4f}:d={d:.4f}:alpha=1")
                graph.append(f"[{cur}]" + ",".join(chain) + f"[{lbl}f]")
                x = f"(W-w)/2+({float(c.get('x', 0)):.5f})*W"
                y = f"(H-h)/2+({float(c.get('y', 0)):.5f})*H"
                if ex["dx"]:
                    x += f"+({ex['dx']})*W"
                if ex["dy"]:
                    y += f"+({ex['dy']})*H"
                out = f"o{ci}"
                enable = "between(t,%.4f,%.4f)" % (animations.visible_from(c), c.end)
                graph.append(f"[{prev}][{lbl}f]overlay=x={_q(x)}:y={_q(y)}:eval=frame:eof_action=pass"
                             f":enable={_q(enable)}[{out}]")
                prev = out
                v = animations.veil(c)
                if v is not None:
                    col, vst, vd = v
                    half = vd / 2
                    graph.append(f"color=c=0x{col.lstrip('#')}:s={W}x{H}:r={fps}:d={vd:.4f},format=rgba,"
                                 f"fade=t=in:st=0:d={half:.4f}:alpha=1,fade=t=out:st={half:.4f}:d={half:.4f}:alpha=1,"
                                 f"setpts=PTS+{vst:.4f}/TB[{lbl}veil]")
                    graph.append(f"[{prev}][{lbl}veil]overlay=eof_action=pass"
                                 f":enable={_q('between(t,%.4f,%.4f)' % (vst, vst + vd))}[{out}v]")
                    prev = f"{out}v"

            codec = exportfmt.fmt(self.opts.fmt).get("codec")
            last = prev
            if a0 > 0.0005 or a1 < D - 0.0005:
                graph.append(f"[{last}]trim=start={a0:.4f}:end={a1:.4f},setpts=PTS-STARTPTS[vrange]")
                last = "vrange"
            if codec == "gif":
                graph.append(f"[{last}]split[g1][g2];[g1]palettegen=stats_mode=diff[pal];"
                             f"[g2][pal]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle[vout]")
            elif codec == "webp":
                graph.append(f"[{last}]format=yuva420p[vout]")
            elif codec == "png":
                graph.append(f"[{last}]format=rgb24[vout]")
            elif codec == "prores":
                graph.append(f"[{last}]format=yuv422p10le[vout]")
            else:
                pix = "yuv420p10le" if self.opts.s.get("ten_bit") and codec in ("hevc", "vp9", "av1") else "yuv420p"
                graph.append(f"[{last}]format={pix}[vout]")
            vout = "vout"

        aout = None
        if self.opts.audio and with_audio:
            rate = 48000
            graph.append(f"anullsrc=r={rate}:cl=stereo,atrim=duration={D:.4f}[abase]")
            labels = ["abase"]
            for ai, c in enumerate(self.audio_clips()):
                if not os.path.exists(c["path"]):
                    continue
                offset = 0.0
                if c["id"] in input_index and self.opts.kind != "audio":
                    k = input_index[c["id"]]
                    offset = max(0.0, c["in_point"] - self.src_from.get(c["id"], c["in_point"]))
                else:
                    k = add_input(["-ss", f"{c['in_point']:.4f}", "-t", f"{c.source_span() + 0.1:.4f}",
                                   "-i", c["path"]], "a" + c["id"])
                lbl = f"a{ai}"
                graph.append(f"[{k}:a]" + ",".join(audio_clip_chain(c, rate, offset)) + f"[{lbl}]")
                labels.append(lbl)
            if len(labels) == 1:
                mix = "abase"
            else:
                graph.append("".join(f"[{l}]" for l in labels) +
                             f"amix=inputs={len(labels)}:duration=first:dropout_transition=0:normalize=0[amix]")
                mix = "amix"
            post = []
            if a0 > 0.0005 or a1 < D - 0.0005:
                post += [f"atrim=start={a0:.4f}:end={a1:.4f}", "asetpts=PTS-STARTPTS"]
            target = exportfmt.LOUDNESS.get(self.opts.s.get("loudness", "off"))
            if target is not None:
                post.append(f"loudnorm=I={target:.1f}:TP=-1.5:LRA=11")
                post.append(f"aresample={int(self.opts.s.get('sample_rate', 48000))}")
            else:
                post.append("alimiter=limit=0.98:level=disabled:latency=1")   # never clip the master
            graph.append(f"[{mix}]" + ",".join(post) + "[aout]")
            aout = "aout"
        return inputs, ";\n".join(graph), vout, aout, a1 - a0

    def command(self, pass_no=None):
        inputs, graph, vout, aout, D = self.build(with_audio=pass_no != 1)
        script = os.path.join(self.workdir, "graph.txt")
        with open(script, "w", encoding="utf-8") as f:
            f.write(graph)
        enc = pick_encoder(self.opts)
        self.encoder = enc
        s = self.opts.s
        args = [media.ffmpeg_exe(), "-hide_banner", "-nostdin", "-y", "-loglevel", "error",
                "-progress", "pipe:1", "-nostats"]
        if self.opts.low_impact:
            threads = max(2, (os.cpu_count() or 4) - 1)
            args += ["-filter_complex_threads", str(threads)]
        args += inputs
        args += [script_flag(), "graph.txt"]
        if vout:
            args += ["-map", f"[{vout}]", "-r", str(self.opts.fps)]
            args += exportfmt.video_args(s, enc, D, pass_no, os.path.join(self.workdir, "pass"))
        if aout and pass_no != 1:
            args += ["-map", f"[{aout}]"] + exportfmt.audio_args(s)
        elif vout:
            args += ["-an"]
        args += exportfmt.container_args(s)
        args += ["-t", f"{D:.4f}"]
        if pass_no == 1:
            args += ["-f", "null", os.devnull]
        else:
            if self.opts.kind == "image":
                os.makedirs(os.path.dirname(self.out_pattern()) or ".", exist_ok=True)
                args += [self.out_pattern()]
            else:
                args += [self.opts.out_path]
        return args, D

    def out_pattern(self):
        """Image sequences: <folder>/<name>_00001.png next to the chosen path."""
        root, _ = os.path.splitext(self.opts.out_path)
        folder = root
        return os.path.join(folder, os.path.basename(root) + "_%05d.png")

    def two_pass(self):
        s = self.opts.s
        codec = exportfmt.fmt(self.opts.fmt).get("codec")
        return s.get("rate_mode") == "size" and codec in ("h264", "hevc", "vp9", "av1") and \
            pick_encoder(self.opts) in ("libx264", "libx265", None)

    # ----------------------------------------------------------------- run
    def run(self, progress=None):
        """Render synchronously. progress(phase_text, fraction 0..1, eta_seconds or None)."""
        def report(text, frac, eta=None):
            if progress:
                progress(text, frac, eta)

        if not self.project.clips:
            raise RenderError("The timeline is empty - add some media first.")
        report("Preparing", 0.0)
        self.prepare(lambda t, f: report(t, 0.0))
        if self.two_pass():
            # pass 1 measures the video so pass 2 can hit the target file size exactly
            args, D = self.command(pass_no=1)
            self._encode(args, D, lambda t, f, eta=None: report("Analysing (pass 1 of 2)", f * 0.5, None))
            args, D = self.command(pass_no=2)
            self._encode(args, D, lambda t, f, eta=None: report("Rendering (pass 2 of 2)", 0.5 + f * 0.5, eta))
            report("Done", 1.0, 0)
            return self.opts.out_path
        args, D = self.command()
        try:
            self._encode(args, D, report)
        except RenderError:
            if self.encoder not in (None, "libx264", "libx265") and not self.cancelled:
                # hardware encoder failed (driver / resolution limits): retry on the CPU
                self.opts.encoder = "cpu"
                report("Retrying with the CPU encoder", 0.0)
                args, D = self.command()
                self._encode(args, D, report)
            else:
                raise
        report("Done", 1.0, 0)
        return self.opts.out_path

    def _encode(self, args, D, report):
        report("Starting the encoder", 0.0)
        started = time.time()
        self.proc = subprocess.Popen(args, cwd=self.workdir, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     creationflags=media.NO_WINDOW | (BELOW_NORMAL if self.opts.low_impact else 0))
        import threading
        err_chunks = []
        t = threading.Thread(target=lambda: err_chunks.append(self.proc.stderr.read()), daemon=True)
        t.start()
        for raw in self.proc.stdout:
            if self.cancelled:
                break
            line = raw.decode("utf-8", "replace").strip()
            m = re.match(r"out_time_us=(\d+)", line)
            if m:
                done = int(m.group(1)) / 1_000_000
                frac = max(0.0, min(0.999, done / D))
                el = time.time() - started
                eta = (el / frac - el) if frac > 0.02 else None
                report("Rendering", frac, eta)
        self.proc.wait()
        t.join(timeout=5)
        for pipe in (self.proc.stdout, self.proc.stderr):
            try:
                pipe.close()
            except Exception:
                pass
        if self.cancelled:
            self._cleanup_output()
            raise RenderCancelled()
        if self.proc.returncode != 0:
            err = b"".join(c for c in err_chunks if c).decode("utf-8", "replace")
            self.log.append(err)
            self._cleanup_output()
            raise RenderError(err.strip()[-3000:] or "FFmpeg stopped unexpectedly.")

    def _cleanup_output(self):
        try:
            if self.opts.kind == "image":
                shutil.rmtree(os.path.dirname(self.out_pattern()), ignore_errors=True)
            elif os.path.exists(self.opts.out_path):
                os.remove(self.opts.out_path)
        except OSError:
            pass

    def cancel(self):
        self.cancelled = True
        if self.proc is not None and self.proc.poll() is None:
            try:
                self.proc.kill()
            except Exception:
                pass

    def cleanup(self):
        shutil.rmtree(self.workdir, ignore_errors=True)


def render_audio_preview(project, out_path):
    """Mixes the timeline's audio into a WAV for preview playback (same chain as the export).
    Returns True if there is any audio."""
    clips = [c for c in audible_clips(project) if os.path.exists(c["path"])]
    if not clips:
        return False
    work = tempfile.mkdtemp(prefix="apreview_", dir=cache_dir("render"))
    try:
        D = max(0.1, project.duration())
        rate = 44100
        inputs, graph = [], [f"anullsrc=r={rate}:cl=stereo,atrim=duration={D:.4f}[abase]"]
        labels = ["abase"]
        for ai, c in enumerate(clips):
            inputs += ["-ss", f"{c['in_point']:.4f}", "-t", f"{c.source_span() + 0.1:.4f}", "-i", c["path"]]
            graph.append(f"[{ai}:a]" + ",".join(audio_clip_chain(c, rate)) + f"[a{ai}]")
            labels.append(f"a{ai}")
        graph.append("".join(f"[{l}]" for l in labels) +
                     f"amix=inputs={len(labels)}:duration=first:dropout_transition=0:normalize=0,"
                     f"alimiter=limit=0.98:level=disabled:latency=1[aout]")
        with open(os.path.join(work, "agraph.txt"), "w", encoding="utf-8") as f:
            f.write(";\n".join(graph))
        args = [media.ffmpeg_exe(), "-hide_banner", "-nostdin", "-y", "-loglevel", "error", *inputs,
                script_flag(), "agraph.txt", "-map", "[aout]", "-c:a", "pcm_s16le", "-t", f"{D:.4f}",
                out_path]
        p = subprocess.run(args, cwd=work, capture_output=True, timeout=900,
                           creationflags=media.NO_WINDOW | BELOW_NORMAL)
        return p.returncode == 0 and os.path.exists(out_path)
    finally:
        shutil.rmtree(work, ignore_errors=True)
