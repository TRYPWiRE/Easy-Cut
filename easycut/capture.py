"""Screen, webcam and audio recording.

One FFmpeg process records the screen, the webcam and the microphone together (so they share a clock and
stay in sync), writing each to its own file:

    screen  - DXGI desktop duplication ("ddagrab": the GPU hands frames over, ideal for games) or GDI
              ("gdigrab": works everywhere), encoded on the graphics card when one is available
    webcam  - DirectShow
    mic     - DirectShow, saved as lossless WAV

System audio ("what you hear" - game sound, music, voice chat) can't be captured by FFmpeg on Windows, so it
is recorded alongside with WASAPI loopback (the `soundcard` package) and its start offset is measured so the
timeline lines it up exactly.

Everything recorded goes onto separate timeline tracks afterwards, so each part can be edited on its own.
Files are written as MKV while recording (safe if the PC crashes) and turned into MP4 when you stop.
"""
import os
import re
import subprocess
import sys
import threading
import time
import wave

import numpy as np

from . import media

IS_WIN = sys.platform == "win32"


# ====================================================================== devices
def parse_dshow_devices(text):
    """{'video': [...], 'audio': [...]} from `ffmpeg -list_devices true -f dshow -i dummy` output."""
    out = {"video": [], "audio": []}
    section = None
    for line in text.splitlines():
        if "DirectShow video devices" in line:
            section = "video"
            continue
        if "DirectShow audio devices" in line:
            section = "audio"
            continue
        if "Alternative name" in line:
            continue
        m = re.search(r'"([^"]+)"\s*\((video|audio|none)\)', line)
        if m:
            kind = m.group(2)
            if kind == "none":
                continue
            out[kind].append(m.group(1))
            continue
        m = re.search(r'\]\s+"([^"]+)"\s*$', line)
        if m and section:
            out[section].append(m.group(1))
    for k in out:
        seen = []
        for n in out[k]:
            if n not in seen:
                seen.append(n)
        out[k] = seen
    return out


def list_devices():
    """Webcams and microphones available to FFmpeg (Windows), {'video': [...], 'audio': [...]}."""
    if not IS_WIN:
        return {"video": [], "audio": []}
    try:
        r = media.run(["-list_devices", "true", "-f", "dshow", "-i", "dummy"], timeout=20)
        return parse_dshow_devices(r.stderr.decode("utf-8", "replace"))
    except Exception:
        return {"video": [], "audio": []}


def monitors():
    """[{'name', 'x', 'y', 'w', 'h', 'primary', 'index'}] in physical pixels (index = capture output number)."""
    mons = []
    if IS_WIN:
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32

            class MONITORINFOEX(ctypes.Structure):
                _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                            ("dwFlags", wintypes.DWORD), ("szDevice", wintypes.WCHAR * 32)]

            def cb(hmon, hdc, rect, data):
                info = MONITORINFOEX()
                info.cbSize = ctypes.sizeof(MONITORINFOEX)
                if user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
                    r = info.rcMonitor
                    mons.append({"name": info.szDevice, "x": r.left, "y": r.top, "w": r.right - r.left,
                                 "h": r.bottom - r.top, "primary": bool(info.dwFlags & 1)})
                return True

            proc = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p,
                                      ctypes.POINTER(wintypes.RECT), ctypes.c_double)
            user32.EnumDisplayMonitors(None, None, proc(cb), 0)
        except Exception:
            mons = []
    if not mons:
        try:
            from PyQt6.QtGui import QGuiApplication
            for s in QGuiApplication.screens():
                g = s.geometry()
                dpr = s.devicePixelRatio()
                mons.append({"name": s.name(), "x": int(g.x() * dpr), "y": int(g.y() * dpr),
                             "w": int(g.width() * dpr), "h": int(g.height() * dpr),
                             "primary": s == QGuiApplication.primaryScreen()})
        except Exception:
            pass
    if not mons:
        mons = [{"name": "Screen", "x": 0, "y": 0, "w": 1920, "h": 1080, "primary": True}]
    for i, m in enumerate(mons):
        m["index"] = i
    for n, m in enumerate(sorted(mons, key=lambda m: (not m["primary"], m["x"], m["y"]))):
        m["label"] = f"Display {n + 1}" + ("  (main)" if m["primary"] else "") + f"  ·  {m['w']}×{m['h']}"
    return sorted(mons, key=lambda m: (not m["primary"], m["x"], m["y"]))


def system_audio_available():
    if not IS_WIN:
        return False
    try:
        import soundcard  # noqa: F401
        return True
    except Exception:
        return False


# ====================================================================== settings
class CaptureConfig:
    def __init__(self, **kw):
        self.screen = True
        self.monitor = None              # dict from monitors()
        self.method = "auto"             # auto | dxgi | gdi
        self.fps = 60
        self.scale = "native"            # native | 1440p | 1080p | 720p
        self.quality = "high"            # standard | high | ultra
        self.encoder = "auto"            # auto | cpu | h264_nvenc | h264_qsv | h264_amf
        self.show_mouse = True
        self.webcam = None               # DirectShow device name
        self.mic = None                  # DirectShow device name
        self.system_audio = False
        self.out_dir = ""
        self.basename = ""
        self.test = False                # synthetic sources (tests / machines without devices)
        self.__dict__.update(kw)


QUALITY_CQ = {"standard": 26, "high": 21, "ultra": 17}
SCALE_H = {"1440p": 1440, "1080p": 1080, "720p": 720}


def _venc_args(enc, quality, live=True, label="v"):
    q = QUALITY_CQ.get(quality, 21)
    if enc == "h264_nvenc":
        return [f"-c:{label}", enc, "-preset", "p4", "-tune", "ll" if live else "hq", "-rc", "vbr", "-cq", str(q),
                "-b:v", "0", "-bf", "0"]
    if enc == "h264_qsv":
        return [f"-c:{label}", enc, "-preset", "veryfast", "-global_quality", str(q)]
    if enc == "h264_amf":
        return [f"-c:{label}", enc, "-usage", "lowlatency", "-quality", "speed", "-rc", "cqp", "-qp_i", str(q),
                "-qp_p", str(q + 2)]
    return [f"-c:{label}", "libx264", "-preset", "superfast" if live else "veryfast", "-crf", str(q),
            "-tune", "zerolatency"]


def pick_encoder(cfg):
    if cfg.encoder == "cpu":
        return "libx264"
    try:
        hw = [e for e, _ in media.hardware_encoders()]
    except Exception:
        hw = []
    if cfg.encoder in hw:
        return cfg.encoder
    return hw[0] if (cfg.encoder == "auto" and hw) else "libx264"


def build_command(cfg, method=None):
    """(args, outputs) where outputs = {'screen': path, 'webcam': path, 'mic': path} (MKV/WAV while recording)."""
    method = method or ("dxgi" if cfg.method in ("auto", "dxgi") else "gdi")
    base = os.path.join(cfg.out_dir, cfg.basename)
    enc = pick_encoder(cfg)
    args = [media.ffmpeg_exe(), "-hide_banner", "-loglevel", "warning", "-y", "-progress", "pipe:1", "-nostats"]
    outputs = {}
    n = 0
    screen_in = cam_in = mic_in = None
    fps = int(cfg.fps)
    if cfg.screen:
        mon = cfg.monitor or monitors()[0]
        if cfg.test:
            args += ["-re", "-f", "lavfi", "-i", f"testsrc2=size=1280x720:rate={fps}"]
        elif method == "dxgi":
            args += ["-f", "lavfi", "-thread_queue_size", "1024", "-i",
                     f"ddagrab=output_idx={0 if mon.get('primary', True) else mon.get('index', 0)}:framerate={fps}:draw_mouse={1 if cfg.show_mouse else 0}"]
        else:
            args += ["-f", "gdigrab", "-thread_queue_size", "1024", "-framerate", str(fps),
                     "-offset_x", str(mon["x"]), "-offset_y", str(mon["y"]), "-video_size", f"{mon['w']}x{mon['h']}",
                     "-draw_mouse", "1" if cfg.show_mouse else "0", "-i", "desktop"]
        screen_in = n
        n += 1
    if cfg.webcam:
        if cfg.test:
            args += ["-re", "-f", "lavfi", "-i", "testsrc=size=640x360:rate=30"]
        else:
            args += ["-f", "dshow", "-rtbufsize", "512M", "-thread_queue_size", "1024", "-i", f"video={cfg.webcam}"]
        cam_in = n
        n += 1
    if cfg.mic:
        if cfg.test:
            args += ["-re", "-f", "lavfi", "-i", "sine=frequency=330:sample_rate=48000"]
        else:
            args += ["-f", "dshow", "-thread_queue_size", "1024", "-audio_buffer_size", "50", "-i", f"audio={cfg.mic}"]
        mic_in = n
        n += 1
    graph = []
    if screen_in is not None:
        chain = []
        if method == "dxgi" and not cfg.test:
            chain.append("hwdownload,format=bgra")
        h = SCALE_H.get(cfg.scale)
        if h:
            chain.append(f"scale=-2:'min({h},ih)':flags=bicubic")
        chain.append("format=nv12" if enc in ("h264_nvenc", "h264_qsv", "h264_amf") else "format=yuv420p")
        graph.append(f"[{screen_in}:v]" + ",".join(chain) + "[sv]")
    if graph:
        args += ["-filter_complex", ";".join(graph)]
    if screen_in is not None:
        outputs["screen"] = base + " - screen.mkv"
        args += ["-map", "[sv]", "-r", str(fps), "-fps_mode", "cfr"] + _venc_args(enc, cfg.quality) + \
                ["-g", str(fps * 2), outputs["screen"]]
    if cam_in is not None:
        outputs["webcam"] = base + " - webcam.mkv"
        args += ["-map", f"{cam_in}:v", "-pix_fmt", "yuv420p"] + _venc_args("libx264", cfg.quality, label="v") + \
                [outputs["webcam"]]
    if mic_in is not None:
        outputs["mic"] = base + " - microphone.wav"
        args += ["-map", f"{mic_in}:a", "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2", outputs["mic"]]
    return args, outputs, enc


# ====================================================================== system audio (WASAPI loopback)
class SoundcardBackend:
    """Default speaker loopback through the `soundcard` package."""

    def recorder(self, samplerate, channels):
        import soundcard as sc
        speaker = sc.default_speaker()
        mic = sc.get_microphone(id=str(speaker.name), include_loopback=True)
        return mic.recorder(samplerate=samplerate, channels=channels)


class SystemAudioRecorder:
    """Records loopback audio to a WAV in a thread, keeping it locked to the wall clock.

    WASAPI delivers nothing while the PC is silent, so the recorder pads silence (and trims any excess) to keep
    the file exactly as long as the real time that passed - otherwise the sound would drift out of sync."""
    RATE = 48000
    BLOCK = 2400            # 50 ms

    def __init__(self, path, backend=None):
        self.path = path
        self.backend = backend or SoundcardBackend()
        self.thread = None
        self.stop_flag = threading.Event()
        self.t0 = None
        self.frames = 0
        self.error = ""
        self.level = 0.0

    def start(self):
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        try:
            import warnings
            warnings.filterwarnings("ignore")
            if IS_WIN:
                try:    # this thread needs its own COM apartment for WASAPI
                    import ctypes
                    ctypes.windll.ole32.CoInitializeEx(None, 0)
                except Exception:
                    pass
            with wave.open(self.path, "wb") as wf:
                wf.setnchannels(2)
                wf.setsampwidth(2)
                wf.setframerate(self.RATE)
                with self.backend.recorder(self.RATE, 2) as rec:
                    while not self.stop_flag.is_set():
                        data = rec.record(numframes=self.BLOCK)
                        now = time.perf_counter()
                        if self.t0 is None:
                            self.t0 = now - len(data) / self.RATE
                        data = np.asarray(data, np.float32)
                        if data.ndim == 1:
                            data = np.stack([data, data], axis=1)
                        expected = int((now - self.t0) * self.RATE)
                        behind = expected - (self.frames + len(data))
                        if behind > self.RATE // 10:                 # fell behind: pad silence
                            wf.writeframes(np.zeros((behind, 2), np.int16).tobytes())
                            self.frames += behind
                        elif behind < -(self.RATE // 10):            # ran ahead: drop the excess
                            data = data[:max(0, len(data) + behind)]
                        self.level = float(np.abs(data).max()) if len(data) else 0.0
                        pcm = np.clip(data * 32767, -32768, 32767).astype(np.int16)
                        wf.writeframes(pcm.tobytes())
                        self.frames += len(pcm)
        except Exception as e:  # noqa: BLE001
            self.error = str(e)

    def stop(self):
        self.stop_flag.set()
        if self.thread is not None:
            self.thread.join(timeout=5)


# ====================================================================== the recorder
class RecordingResult:
    def __init__(self):
        self.files = {}            # kind -> final path
        self.offsets = {}          # kind -> seconds after the screen recording started
        self.duration = 0.0
        self.encoder = ""
        self.method = ""
        self.warnings = []


class Recorder:
    """Start / stop a recording. Progress is polled from the attributes (thread-safe enough for the UI)."""

    def __init__(self, cfg: CaptureConfig, system_backend=None):
        self.cfg = cfg
        self.proc = None
        self.outputs = {}
        self.elapsed = 0.0
        self.fps = 0.0
        self.dropped = 0
        self.size = 0
        self.t_started = None        # perf_counter at FFmpeg's first frame
        self.error = ""
        self.method = ""
        self.encoder = ""
        self.sys_rec = None
        self.system_backend = system_backend
        self._err = []
        self.running = False

    # ------------------------------------------------------------------ start
    def start(self):
        os.makedirs(self.cfg.out_dir, exist_ok=True)
        if not self.cfg.basename:
            self.cfg.basename = time.strftime("Recording %Y-%m-%d %H-%M-%S")
        methods = ["dxgi", "gdi"] if self.cfg.method == "auto" else [self.cfg.method]
        mon = self.cfg.monitor or {}
        if self.cfg.method == "auto" and mon and not mon.get("primary", True) and not self.cfg.test:
            methods = ["gdi"]      # DXGI output numbers don't always match Windows' display order
        last_err = ""
        for m in methods:
            if self._launch(m):
                self.method = m
                break
            last_err = self.error
        else:
            if self.cfg.encoder != "cpu" and self.encoder != "libx264":
                # the graphics-card encoder refused: retry on the CPU
                self.cfg.encoder = "cpu"
                for m in methods:
                    if self._launch(m):
                        self.method = m
                        break
                else:
                    raise RuntimeError(self.error or last_err or "The recording couldn't start.")
            else:
                raise RuntimeError(self.error or last_err or "The recording couldn't start.")
        if self.cfg.system_audio and (self.system_backend is not None or system_audio_available()):
            path = os.path.join(self.cfg.out_dir, self.cfg.basename + " - system audio.wav")
            self.sys_rec = SystemAudioRecorder(path, self.system_backend)
            self.sys_rec.start()
        self.running = True

    def _launch(self, method):
        args, self.outputs, self.encoder = build_command(self.cfg, method)
        self._err = []
        self.t_started = None
        self.proc = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     creationflags=media.NO_WINDOW)
        threading.Thread(target=self._read_err, daemon=True).start()
        threading.Thread(target=self._read_progress, daemon=True).start()
        t0 = time.time()
        while time.time() - t0 < 8:          # wait for the first frame (or a failure)
            if self.t_started is not None:
                return True
            if self.proc.poll() is not None:
                break
            time.sleep(0.02)
        if self.proc.poll() is None and self.t_started is not None:
            return True
        if self.proc.poll() is None:
            self.proc.kill()
        self.proc.wait()
        self.error = self._error_text()
        for p in self.outputs.values():
            try:
                os.remove(p)
            except OSError:
                pass
        return False

    def _read_err(self):
        for raw in self.proc.stderr:
            self._err.append(raw.decode("utf-8", "replace").rstrip())
            del self._err[:-60]

    def _error_text(self):
        lines = [ln for ln in self._err if ln.strip()]
        return "\n".join(lines[-8:])

    def _read_progress(self):
        proc = self.proc
        for raw in proc.stdout:
            line = raw.decode("utf-8", "replace").strip()
            k, _, v = line.partition("=")
            try:
                if k == "out_time_us" and v.lstrip("-").isdigit():
                    t = int(v) / 1_000_000
                    if t > 0 and self.t_started is None:
                        self.t_started = time.perf_counter() - t
                    self.elapsed = max(0.0, t)
                elif k == "fps":
                    self.fps = float(v)
                elif k in ("drop_frames", "dup_frames") and k == "drop_frames":
                    self.dropped = int(v)
                elif k == "total_size" and v.isdigit():
                    self.size = int(v)
            except ValueError:
                pass

    # ------------------------------------------------------------------ stop
    def stop(self, progress=None):
        """Stop, finish the files (MKV -> MP4) and return a RecordingResult."""
        res = RecordingResult()
        res.encoder, res.method = self.encoder, self.method
        stopped_at = time.perf_counter()
        if self.proc is not None and self.proc.poll() is None:
            try:
                self.proc.stdin.write(b"q")
                self.proc.stdin.flush()
            except Exception:
                pass
            try:
                self.proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        if self.sys_rec is not None:
            self.sys_rec.stop()
        self.running = False
        if progress:
            progress("Finishing your files…")
        for kind, path in self.outputs.items():
            if not os.path.exists(path) or os.path.getsize(path) < 1024:
                res.warnings.append(f"The {kind} recording is empty.")
                continue
            final = path
            if path.endswith(".mkv"):
                mp4 = path[:-4] + ".mp4"
                r = media.run(["-y", "-loglevel", "error", "-i", path, "-c", "copy", "-movflags", "+faststart", mp4],
                              timeout=600)
                if r.returncode == 0 and os.path.exists(mp4):
                    try:
                        os.remove(path)
                    except OSError:
                        pass
                    final = mp4
            res.files[kind] = final
            res.offsets[kind] = 0.0
        if self.sys_rec is not None:
            if self.sys_rec.error:
                res.warnings.append("System audio couldn't be recorded: " + self.sys_rec.error)
            elif self.sys_rec.frames > 0 and self.sys_rec.t0 is not None:
                res.files["system"] = self.sys_rec.path
                base_t = self.t_started if self.t_started is not None else stopped_at - self.elapsed
                res.offsets["system"] = round(self.sys_rec.t0 - base_t, 3)
        res.duration = self.elapsed
        return res

    def cancel(self):
        if self.proc is not None and self.proc.poll() is None:
            self.proc.kill()
        if self.sys_rec is not None:
            self.sys_rec.stop()
        self.running = False


# ====================================================================== timeline placement
CORNERS = {"br": (1, 1), "bl": (-1, 1), "tr": (1, -1), "tl": (-1, -1)}


def pip_transform(canvas_w, canvas_h, cam_w, cam_h, size=0.28, corner="br", margin=0.025):
    """x, y, scale for a picture-in-picture webcam in a canvas corner."""
    from . import effects
    fw, fh = effects.fitted_size({"fit": "fit", "scale": 1.0}, cam_w, cam_h, canvas_w, canvas_h)
    # scale so the webcam's width is `size` of the canvas width (or height, for portrait canvases)
    if canvas_w >= canvas_h:
        s = size * canvas_w / fw
    else:
        s = size * canvas_h / fh * 0.6
    w_frac = fw * s / canvas_w
    h_frac = fh * s / canvas_h
    sx, sy = CORNERS.get(corner, (1, 1))
    mx = margin
    my = margin * canvas_w / canvas_h
    x = sx * (0.5 - w_frac / 2 - mx)
    y = sy * (0.5 - h_frac / 2 - my)
    return x, y, s
