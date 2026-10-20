"""FFmpeg discovery, media probing, thumbnails and frame readers for the preview."""
import os
import re
import shutil
import subprocess
import sys
import threading

import numpy as np

from . import settings

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".wmv", ".flv", ".mpg", ".mpeg", ".ts", ".3gp", ".gif"}
AUDIO_EXTS = {".mp3", ".wav", ".aac", ".m4a", ".flac", ".ogg", ".opus", ".wma"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff"}

NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0   # CREATE_NO_WINDOW: no console flashes


def media_kind(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext in IMAGE_EXTS:
        return "image"
    if ext in AUDIO_EXTS:
        return "audio"
    if ext in VIDEO_EXTS:
        return "video"
    return ""


# ------------------------------------------------------------------ ffmpeg
_ffmpeg = None


def ffmpeg_exe() -> str:
    """Path to ffmpeg: user setting > bundled copy > imageio-ffmpeg > PATH."""
    global _ffmpeg
    if _ffmpeg and os.path.exists(_ffmpeg):
        return _ffmpeg
    candidates = []
    custom = settings.get("ffmpeg_path")
    if custom:
        candidates.append(custom)
    from .config import bundle_dir
    exe = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    candidates.append(os.path.join(bundle_dir(), "ffmpeg", exe))
    try:
        import imageio_ffmpeg
        candidates.append(imageio_ffmpeg.get_ffmpeg_exe())
    except Exception:
        pass
    found = shutil.which("ffmpeg")
    if found:
        candidates.append(found)
    for c in candidates:
        if c and os.path.isfile(c):
            _ffmpeg = c
            return c
    raise FileNotFoundError("FFmpeg could not be found.")


def reset_ffmpeg():
    global _ffmpeg, _hw_cache, _filters_cache
    _ffmpeg = None
    _hw_cache = None
    _filters_cache = None


def run(args, timeout=60, **kw):
    return subprocess.run([ffmpeg_exe(), "-hide_banner", *args], capture_output=True, timeout=timeout,
                          creationflags=NO_WINDOW, **kw)


_filters_cache = None


def has_filter(name: str) -> bool:
    global _filters_cache
    if _filters_cache is None:
        try:
            out = run(["-filters"], timeout=20).stdout.decode("utf-8", "replace")
            _filters_cache = set(m.group(1) for m in re.finditer(r"^\s*[TSC.]{3}\s+(\w+)", out, re.M))
        except Exception:
            _filters_cache = set()
    return name in _filters_cache


_hw_cache = None
HW_ENCODERS = [("h264_nvenc", "NVIDIA NVENC"), ("h264_qsv", "Intel Quick Sync"), ("h264_amf", "AMD AMF")]


def hardware_encoders() -> list:
    """H.264 hardware encoders that actually work on this machine (tested with a tiny encode)."""
    global _hw_cache
    if _hw_cache is not None:
        return _hw_cache
    found = []
    try:
        listed = run(["-encoders"], timeout=20).stdout.decode("utf-8", "replace")
    except Exception:
        listed = ""
    for enc, label in HW_ENCODERS:
        if enc not in listed:
            continue
        try:
            r = run(["-loglevel", "error", "-f", "lavfi", "-i", "color=black:s=256x256:r=30:d=0.2",
                     "-c:v", enc, "-f", "null", "-"], timeout=20)
            if r.returncode == 0:
                found.append((enc, label))
        except Exception:
            pass
    _hw_cache = found
    return found


# ------------------------------------------------------------------ probing
class MediaInfo:
    def __init__(self, path):
        self.path = path
        self.kind = media_kind(path)
        self.duration = 0.0
        self.width = 0
        self.height = 0
        self.fps = 30.0
        self.has_video = False
        self.has_audio = False
        self.sample_rate = 48000

    def to_dict(self):
        return dict(self.__dict__)

    def __repr__(self):
        return f"<MediaInfo {os.path.basename(self.path)} {self.kind} {self.width}x{self.height} {self.duration:.2f}s>"


_probe_cache = {}
_probe_lock = threading.Lock()


def probe(path: str) -> MediaInfo:
    key = (path, os.path.getmtime(path) if os.path.exists(path) else 0)
    with _probe_lock:
        if key in _probe_cache:
            return _probe_cache[key]
    info = MediaInfo(path)
    if info.kind == "image":
        img = read_image(path)
        if img is not None:
            info.height, info.width = img.shape[:2]
            info.has_video = True
        info.duration = 5.0
    else:
        try:
            err = run(["-i", path], timeout=30).stderr.decode("utf-8", "replace")
        except Exception:
            err = ""
        m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", err)
        if m:
            info.duration = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
        vm = re.search(r"Stream #\d+:\d+.*?: Video: .*?(\d{2,5})x(\d{2,5})", err)
        if vm and "attached pic" not in vm.group(0):
            info.has_video = True
            info.width, info.height = int(vm.group(1)), int(vm.group(2))
            line = err[vm.start():err.find("\n", vm.start())]
            fm = re.search(r"([\d.]+) fps", line) or re.search(r"([\d.]+) tbr", line)
            if fm:
                try:
                    info.fps = max(1.0, min(240.0, float(fm.group(1))))
                except ValueError:
                    pass
            rm = re.search(r"rotation of (-?[\d.]+) degrees", err)
            if rm and abs(abs(float(rm.group(1))) - 90) < 1:
                info.width, info.height = info.height, info.width
        am = re.search(r"Stream #\d+:\d+.*?: Audio: .*?(\d+) Hz", err)
        if am:
            info.has_audio = True
            info.sample_rate = int(am.group(1))
        if info.kind == "video" and not info.has_video and info.has_audio:
            info.kind = "audio"
        if info.duration <= 0 and info.kind == "video" and info.has_video:
            info.duration = 1.0
    with _probe_lock:
        _probe_cache[key] = info
    return info


# ------------------------------------------------------------------ images
def read_image(path: str):
    """BGRA uint8 image (handles unicode paths on Windows), or None."""
    import cv2
    try:
        data = np.fromfile(path, dtype=np.uint8)
        img = cv2.imdecode(data, cv2.IMREAD_UNCHANGED)
    except Exception:
        return None
    if img is None:
        return None
    if img.dtype != np.uint8:
        img = (img / 256).astype(np.uint8) if img.dtype == np.uint16 else img.astype(np.uint8)
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGRA)
    elif img.shape[2] == 3:
        img = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)
    return img


# ------------------------------------------------------------------ frame readers
class FrameReader:
    """Reads BGR frames of a video at a given time, scaled to fit `max_size`.

    Uses OpenCV (fast seeks, sequential reads during playback); falls back to an FFmpeg pipe when
    OpenCV can't open the file (e.g. unusual codecs or paths).
    """

    def __init__(self, path, max_size=(960, 540)):
        import cv2
        self.path = path
        self.max_size = max_size
        self.info = probe(path)
        self.fps = self.info.fps or 30.0
        self.cap = None
        self.pos = -1
        self.last = None
        self.last_index = -2
        self.pipe = None
        self.pipe_index = -1
        self.lock = threading.Lock()
        try:
            cap = cv2.VideoCapture(path)
            if cap.isOpened() and cap.read()[0]:
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                self.cap = cap
            else:
                cap.release()
        except Exception:
            self.cap = None
        self.out_w, self.out_h = self._fit(self.info.width or 640, self.info.height or 360)

    def _fit(self, w, h):
        mw, mh = self.max_size
        s = min(1.0, mw / max(1, w), mh / max(1, h))
        return max(2, int(w * s) // 2 * 2), max(2, int(h * s) // 2 * 2)

    def frame_at(self, t: float):
        with self.lock:
            idx = max(0, int(round(t * self.fps + 1e-6)))
            total = max(1, int(self.info.duration * self.fps))
            idx = min(idx, total - 1)
            if idx == self.last_index and self.last is not None:
                return self.last
            frame = self._read_cv(idx) if self.cap is not None else self._read_pipe(idx)
            if frame is None:
                return self.last
            self.last, self.last_index = frame, idx
            return frame

    def _read_cv(self, idx):
        import cv2
        if idx != self.pos + 1 or self.pos < 0:
            if 0 < idx - self.pos <= 8:          # small jump forward: grab instead of seeking
                for _ in range(idx - self.pos - 1):
                    self.cap.grab()
            else:
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ok, frame = self.cap.read()
        self.pos = idx
        if not ok or frame is None:
            self.pos = -1
            return None
        if frame.shape[1] != self.out_w or frame.shape[0] != self.out_h:
            frame = cv2.resize(frame, (self.out_w, self.out_h), interpolation=cv2.INTER_AREA)
        return frame

    def _read_pipe(self, idx):
        w, h = self.out_w, self.out_h
        if self.pipe is None or idx != self.pipe_index + 1:
            self._close_pipe()
            t = idx / self.fps
            self.pipe = subprocess.Popen(
                [ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-ss", f"{t:.3f}", "-i", self.path,
                 "-vf", f"scale={w}:{h}", "-f", "rawvideo", "-pix_fmt", "bgr24", "-r", f"{self.fps}", "-"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=NO_WINDOW)
        size = w * h * 3
        data = self.pipe.stdout.read(size)
        if len(data) < size:
            self._close_pipe()
            return None
        self.pipe_index = idx
        return np.frombuffer(data, np.uint8).reshape(h, w, 3)

    def _close_pipe(self):
        if self.pipe is not None:
            try:
                self.pipe.kill()
                self.pipe.wait(timeout=2)
            except Exception:
                pass
            self.pipe = None
            self.pipe_index = -1

    def close(self):
        with self.lock:
            if self.cap is not None:
                self.cap.release()
                self.cap = None
            self._close_pipe()


def thumbnail(path: str, size=(160, 90), t=None):
    """BGRA thumbnail for the media bin (None on failure)."""
    import cv2
    kind = media_kind(path)
    img = None
    if kind == "image":
        img = read_image(path)
    elif kind == "video":
        try:
            r = FrameReader(path, max_size=(size[0] * 2, size[1] * 2))
            info = r.info
            img = r.frame_at(min(1.0, info.duration * 0.25) if t is None else t)
            r.close()
            if img is not None:
                img = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)
        except Exception:
            img = None
    if img is None:
        return None
    h, w = img.shape[:2]
    s = min(size[0] / w, size[1] / h)
    return cv2.resize(img, (max(1, int(w * s)), max(1, int(h * s))), interpolation=cv2.INTER_AREA)


def waveform(path: str, points=400):
    """Peak envelope (0..1 floats) for drawing audio clips; [] on failure."""
    try:
        r = subprocess.run([ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-i", path, "-vn", "-ac", "1",
                            "-ar", "2000", "-f", "s16le", "-"], capture_output=True, timeout=60,
                           creationflags=NO_WINDOW)
        a = np.frombuffer(r.stdout, dtype=np.int16).astype(np.float32)
    except Exception:
        return []
    if a.size == 0:
        return []
    n = max(1, a.size // points)
    a = np.abs(a[: n * (a.size // n)]).reshape(-1, n).max(axis=1)
    peak = a.max() or 1
    return (a / peak).tolist()


def peak_db(path, start=0.0, duration=None):
    """Loudest sample of a file's audio in dBFS (None if it can't be measured)."""
    args = ["-ss", f"{max(0.0, start):.3f}"]
    if duration:
        args += ["-t", f"{duration:.3f}"]
    try:
        err = run(args + ["-i", path, "-vn", "-af", "volumedetect", "-f", "null", "-"], timeout=300).stderr
    except Exception:
        return None
    m = re.search(r"max_volume:\s*(-?[\d.]+) dB", err.decode("utf-8", "replace"))
    return float(m.group(1)) if m else None
