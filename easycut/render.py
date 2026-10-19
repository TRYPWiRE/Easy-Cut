"""Export: turns the whole timeline into one FFmpeg filter graph and encodes it.

FFmpeg does every pixel operation in native, multi-threaded code (and can use the GPU's video encoder),
which keeps exports fast and light compared with compositing frames in Python.
"""
import hashlib
import os
import re
import subprocess
import sys
import tempfile
import time

from . import animations, effects, filters, formats, media, textrender
from .config import cache_dir

BELOW_NORMAL = 0x00004000 if sys.platform == "win32" else 0


class RenderCancelled(Exception):
    pass


class RenderError(Exception):
    pass


class RenderOptions:
    def __init__(self, aspect="movie", quality="1080p", fps=30, fmt="mp4", out_path="", encoder="auto",
                 audio=True, low_impact=True):
        self.aspect = aspect
        self.quality = quality
        self.fps = int(fps)
        self.fmt = fmt
        self.out_path = out_path
        self.encoder = encoder          # auto | cpu | h264_nvenc | h264_qsv | h264_amf
        self.audio = audio
        self.low_impact = low_impact

    @property
    def size(self):
        return formats.canvas_size(self.aspect, self.quality)


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
    if opts.fmt != "mp4":
        return None
    if opts.encoder == "cpu":
        return "libx264"
    hw = [e for e, _ in media.hardware_encoders()]
    if opts.encoder in hw:
        return opts.encoder
    if opts.encoder == "auto" and hw:
        return hw[0]
    return "libx264"


def encoder_args(enc, opts):
    w, h = opts.size
    if opts.fmt == "gif":
        return ["-loop", "0"]
    if opts.fmt == "webm":
        crf = 30 if h <= 1080 else 28
        args = ["-c:v", "libvpx-vp9", "-crf", str(crf), "-b:v", "0", "-row-mt", "1", "-deadline", "good",
                "-cpu-used", "4", "-pix_fmt", "yuv420p"]
        return args + (["-c:a", "libopus", "-b:a", "160k"] if opts.audio else [])
    if enc == "h264_nvenc":
        v = ["-c:v", enc, "-preset", "p5", "-rc", "vbr", "-cq", "19", "-b:v", "0"]
    elif enc == "h264_qsv":
        v = ["-c:v", enc, "-preset", "medium", "-global_quality", "20"]
    elif enc == "h264_amf":
        v = ["-c:v", enc, "-quality", "balanced", "-rc", "cqp", "-qp_i", "19", "-qp_p", "21"]
    else:
        v = ["-c:v", "libx264", "-preset", "faster", "-crf", "18"]
    if h > 2000 or w > 2000:
        v += ["-level:v", "5.2"] if enc == "libx264" else []
    v += ["-pix_fmt", "yuv420p", "-movflags", "+faststart"]
    if opts.audio:
        v += ["-c:a", "aac", "-b:a", "192k"]
    return v


class Renderer:
    def __init__(self, project, opts: RenderOptions):
        self.project = project
        self.opts = opts
        self.proc = None
        self.cancelled = False
        self.workdir = tempfile.mkdtemp(prefix="render_", dir=cache_dir("render"))
        self.log = []

    # ----------------------------------------------------------------- graph
    def visual_clips(self):
        out = []
        for ti in self.project.video_track_indices_bottom_up():
            if self.project.tracks[ti]["hidden"]:
                continue
            out += [c for c in self.project.clips_on(ti) if c.is_visual and c["duration"] > 0.01]
        return out

    def audio_clips(self):
        out = []
        for c in sorted(self.project.clips, key=lambda c: (c["track"], c["start"])):
            tr = self.project.tracks[c["track"]] if c["track"] < len(self.project.tracks) else {}
            if tr.get("muted") or c.get("muted") or float(c.get("volume", 1)) <= 0.0001:
                continue
            if tr.get("type") == "video" and tr.get("hidden"):
                continue
            if c.has_sound and c["duration"] > 0.01:
                out.append(c)
        return out

    def _trf_name(self, clip):
        key = f"{clip['path']}|{os.path.getmtime(clip['path']) if os.path.exists(clip['path']) else 0}|" \
              f"{clip['in_point']:.3f}|{clip.source_span():.3f}|{effects.stabilize_strength(clip)}"
        return "stab_" + hashlib.sha1(key.encode()).hexdigest()[:16] + ".trf"

    def prepare(self, progress=None):
        """Text images and stabilization analysis passes. Returns nothing; raises on cancel."""
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

    def build(self):
        """(input args, filter graph text, video label, audio label or None, total duration)."""
        W, H = self.opts.size
        fps = self.opts.fps
        D = max(0.1, self.project.duration())
        inputs, graph = [], []
        base = "base"
        bg = self.project.background.lstrip("#")
        graph.append(f"color=c=0x{bg}:s={W}x{H}:r={fps}:d={D:.4f},format=yuv420p[{base}]")
        prev = base
        input_index = {}
        n = 0

        def add_input(args, key):
            nonlocal n
            inputs.extend(args)
            input_index[key] = n
            n += 1
            return n - 1

        for ci, c in enumerate(self.visual_clips()):
            span = c.source_span()
            if c["kind"] == "video":
                if not os.path.exists(c["path"]):
                    continue
                k = add_input(["-ss", f"{c['in_point']:.4f}", "-t", f"{span + 0.1:.4f}", "-i", c["path"]],
                              c["id"])
            elif c["kind"] == "image":
                if not os.path.exists(c["path"]):
                    continue
                k = add_input(["-loop", "1", "-framerate", str(fps), "-t", f"{c['duration'] + 0.1:.4f}",
                               "-i", c["path"]], c["id"])
            else:
                k = add_input(["-loop", "1", "-framerate", str(fps), "-t", f"{c['duration'] + 0.1:.4f}",
                               "-i", self.text_files[c["id"]]], c["id"])
            lbl = f"v{ci}"
            chain = []
            if c["kind"] == "video" and c.get("stabilize"):
                shakiness, smoothing = effects.stabilize_strength(c)
                trf = os.path.join(getattr(self, "stab_dir", ""), self._trf_name(c))
                if getattr(self, "use_vidstab", False) and os.path.exists(trf):
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
            speed = max(0.05, float(c.get("speed", 1.0))) if c["kind"] == "video" else 1.0
            chain.append(f"setpts=(PTS-STARTPTS)/{speed:.6f}")
            chain.append(f"fps={fps}")
            chain.append(f"trim=duration={c['duration']:.4f}")
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
            chain = effects.chroma_ffmpeg(c) + ["format=rgba"] + filters.ffmpeg_chain(c)
            cw, ch = effects.content_size(c, sw, sh)
            fw, fh = effects.fitted_size(c, cw, ch, W, H, text_scale=1.0)
            fw, fh = max(2, int(round(fw / 2)) * 2), max(2, int(round(fh / 2)) * 2)
            chain.append(f"scale={fw}:{fh}:flags=bicubic")
            rot = float(c.get("rotation", 0.0))
            if abs(rot) > 0.01:
                import math
                ar = math.radians(rot)
                nw = int(abs(fw * math.cos(ar)) + abs(fh * math.sin(ar)) + 0.5) // 2 * 2 + 2
                nh = int(abs(fw * math.sin(ar)) + abs(fh * math.cos(ar)) + 0.5) // 2 * 2 + 2
                chain.append(f"rotate=a={ar:.6f}:ow={nw}:oh={nh}:c=none:bilinear=1")
            chain.append(f"setpts=PTS+{c['start']:.4f}/TB")
            ex = animations.ffmpeg_exprs(c)
            if ex["scale"]:
                sw_expr = "max(2,trunc(iw*(%s)/2)*2)" % ex["scale"]
                sh_expr = "max(2,trunc(ih*(%s)/2)*2)" % ex["scale"]
                chain.append(f"scale=w={_q(sw_expr)}:h={_q(sh_expr)}:eval=frame")
            op = float(c.get("opacity", 1.0))
            if op < 0.999:
                chain.append(f"colorchannelmixer=aa={max(0.0, op):.4f}")
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
            enable = "between(t,%.4f,%.4f)" % (c["start"], c.end)
            graph.append(f"[{prev}][{lbl}f]overlay=x={_q(x)}:y={_q(y)}:eval=frame:eof_action=pass"
                         f":enable={_q(enable)}[{out}]")
            prev = out

        vout = prev
        if self.opts.fmt == "gif":
            graph.append(f"[{prev}]split[g1][g2];[g1]palettegen=stats_mode=diff[pal];"
                         f"[g2][pal]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle[gif]")
            vout = "gif"
        else:
            graph.append(f"[{prev}]format=yuv420p[vout]")
            vout = "vout"

        aout = None
        if self.opts.audio and self.opts.fmt != "gif":
            graph.append(f"anullsrc=r=48000:cl=stereo,atrim=duration={D:.4f}[abase]")
            labels = ["abase"]
            for ai, c in enumerate(self.audio_clips()):
                if not os.path.exists(c["path"]):
                    continue
                if c["id"] in input_index:
                    k = input_index[c["id"]]
                else:
                    k = add_input(["-ss", f"{c['in_point']:.4f}", "-t", f"{c.source_span() + 0.1:.4f}",
                                   "-i", c["path"]], "a" + c["id"])
                chain = ["asetpts=PTS-STARTPTS"]
                chain += effects.audio_speed_pitch(c, c.get("sample_rate") or 48000)
                chain.append(f"atrim=duration={c['duration']:.4f}")
                chain.append(f"volume={float(c.get('volume', 1.0)):.4f}")
                for typ, st, d in animations.fades(c):
                    chain.append(f"afade=t={typ}:st={st - c['start']:.4f}:d={d:.4f}")
                chain.append("aresample=48000")
                chain.append("aformat=sample_fmts=fltp:channel_layouts=stereo")
                ms = int(round(c["start"] * 1000))
                chain.append(f"adelay={ms}:all=1")
                lbl = f"a{ai}"
                graph.append(f"[{k}:a]" + ",".join(chain) + f"[{lbl}]")
                labels.append(lbl)
            if len(labels) == 1:
                aout = "abase"
            else:
                graph.append("".join(f"[{l}]" for l in labels) +
                             f"amix=inputs={len(labels)}:duration=first:dropout_transition=0:normalize=0[aout]")
                aout = "aout"
        return inputs, ";\n".join(graph), vout, aout, D

    def command(self):
        inputs, graph, vout, aout, D = self.build()
        script = os.path.join(self.workdir, "graph.txt")
        with open(script, "w", encoding="utf-8") as f:
            f.write(graph)
        enc = pick_encoder(self.opts)
        self.encoder = enc
        args = [media.ffmpeg_exe(), "-hide_banner", "-nostdin", "-y", "-loglevel", "error",
                "-progress", "pipe:1", "-nostats"]
        if self.opts.low_impact:
            threads = max(2, (os.cpu_count() or 4) - 1)
            args += ["-filter_complex_threads", str(threads)]
        args += inputs
        args += [script_flag(), "graph.txt", "-map", f"[{vout}]"]
        if aout:
            args += ["-map", f"[{aout}]"]
        args += ["-r", str(self.opts.fps)]
        args += encoder_args(enc, self.opts)
        args += ["-t", f"{D:.4f}", self.opts.out_path]
        return args, D

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
        args, D = self.command()
        try:
            self._encode(args, D, report)
        except RenderError:
            if self.encoder not in (None, "libx264") and not self.cancelled:
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
            if os.path.exists(self.opts.out_path):
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
        import shutil
        shutil.rmtree(self.workdir, ignore_errors=True)


def render_audio_preview(project, out_path):
    """Mixes the timeline's audio into a small WAV for preview playback. Returns True if audio exists."""
    opts = RenderOptions(fmt="wav", out_path=out_path, audio=True)
    r = Renderer(project, opts)
    try:
        if not r.audio_clips():
            return False
        D = max(0.1, project.duration())
        inputs, graph = [], [f"anullsrc=r=44100:cl=stereo,atrim=duration={D:.4f}[abase]"]
        labels = ["abase"]
        for ai, c in enumerate(r.audio_clips()):
            if not os.path.exists(c["path"]):
                continue
            inputs += ["-ss", f"{c['in_point']:.4f}", "-t", f"{c.source_span() + 0.1:.4f}", "-i", c["path"]]
            k = len(labels) - 1
            chain = ["asetpts=PTS-STARTPTS"] + effects.audio_speed_pitch(c, c.get("sample_rate") or 48000)
            chain += [f"atrim=duration={c['duration']:.4f}", f"volume={float(c.get('volume', 1.0)):.4f}"]
            for typ, st, d in animations.fades(c):
                chain.append(f"afade=t={typ}:st={st - c['start']:.4f}:d={d:.4f}")
            chain += ["aresample=44100", "aformat=sample_fmts=fltp:channel_layouts=stereo",
                      f"adelay={int(round(c['start'] * 1000))}:all=1"]
            graph.append(f"[{k}:a]" + ",".join(chain) + f"[a{ai}]")
            labels.append(f"a{ai}")
        if len(labels) == 1:
            return False
        graph.append("".join(f"[{l}]" for l in labels) +
                     f"amix=inputs={len(labels)}:duration=first:dropout_transition=0:normalize=0[aout]")
        script = os.path.join(r.workdir, "agraph.txt")
        with open(script, "w", encoding="utf-8") as f:
            f.write(";\n".join(graph))
        args = [media.ffmpeg_exe(), "-hide_banner", "-nostdin", "-y", "-loglevel", "error", *inputs,
                script_flag(), "agraph.txt", "-map", "[aout]", "-c:a", "pcm_s16le", "-t", f"{D:.4f}",
                out_path]
        p = subprocess.run(args, cwd=r.workdir, capture_output=True, timeout=600,
                           creationflags=media.NO_WINDOW | BELOW_NORMAL)
        return p.returncode == 0 and os.path.exists(out_path)
    finally:
        r.cleanup()
