"""Export formats, presets and encoder settings.

Beginners pick a preset card ("YouTube 1080p", "Discord - under 10 MB", "Music - WAV"...); pros open the
advanced panel, which is the same settings object with every knob exposed. Everything here is plain data +
small functions so the render engine, the dialog and the tests share one source of truth.
"""
import copy
import json
import math
import os

from . import formats

# ----------------------------------------------------------------------------- formats
# kind: video | audio | image
FORMATS = {
    # video
    "mp4_h264": dict(name="MP4 · H.264", ext=".mp4", kind="video", codec="h264", acodec="aac",
                     desc="Plays everywhere - phones, TVs, browsers, every website."),
    "mp4_hevc": dict(name="MP4 · H.265 / HEVC", ext=".mp4", kind="video", codec="hevc", acodec="aac",
                     desc="About half the size of H.264 at the same quality. Modern devices."),
    "webm_vp9": dict(name="WebM · VP9", ext=".webm", kind="video", codec="vp9", acodec="opus",
                     desc="Open web format with great quality for its size."),
    "webm_av1": dict(name="WebM · AV1", ext=".webm", kind="video", codec="av1", acodec="opus",
                     desc="The smallest files of all. Slow to export."),
    "mov_prores": dict(name="MOV · ProRes 422 HQ", ext=".mov", kind="video", codec="prores", acodec="pcm24",
                       desc="Near-lossless master for editing in other apps. Very large files."),
    "mkv_h264": dict(name="MKV · H.264", ext=".mkv", kind="video", codec="h264", acodec="aac",
                     desc="Same as MP4 in a flexible container (handy for archiving)."),
    "gif": dict(name="GIF (animated)", ext=".gif", kind="video", codec="gif", acodec=None,
                desc="Loops anywhere. No sound, limited colours - keep it short."),
    "webp_anim": dict(name="WebP (animated)", ext=".webp", kind="video", codec="webp", acodec=None,
                      desc="A modern GIF: smaller and full colour. No sound."),
    "png_seq": dict(name="PNG image sequence", ext=".png", kind="image", codec="png", acodec=None,
                    desc="Every frame as a lossless PNG in a folder."),
    # audio
    "mp3": dict(name="MP3", ext=".mp3", kind="audio", acodec="mp3", desc="The universal music format."),
    "wav": dict(name="WAV", ext=".wav", kind="audio", acodec="pcm", desc="Uncompressed studio quality."),
    "flac": dict(name="FLAC", ext=".flac", kind="audio", acodec="flac",
                 desc="Lossless - studio quality at about half the size of WAV."),
    "m4a": dict(name="M4A · AAC", ext=".m4a", kind="audio", acodec="aac", desc="Apple / iTunes friendly."),
    "alac": dict(name="M4A · Apple Lossless", ext=".m4a", kind="audio", acodec="alac",
                 desc="Lossless audio for Apple devices."),
    "ogg": dict(name="OGG · Vorbis", ext=".ogg", kind="audio", acodec="vorbis", desc="Open format for games."),
    "opus": dict(name="Opus", ext=".opus", kind="audio", acodec="opus",
                 desc="Best quality at low bitrates - voice and podcasts."),
    "aiff": dict(name="AIFF", ext=".aiff", kind="audio", acodec="pcm_be", desc="Uncompressed, for Mac apps."),
}
VIDEO_ORDER = ["mp4_h264", "mp4_hevc", "webm_vp9", "webm_av1", "mov_prores", "mkv_h264", "gif", "webp_anim",
               "png_seq"]
AUDIO_ORDER = ["mp3", "wav", "flac", "m4a", "alac", "ogg", "opus", "aiff"]
LEGACY = {"mp4": "mp4_h264", "webm": "webm_vp9", "gif": "gif", "wav": "wav"}

LOSSLESS_AUDIO = {"pcm", "pcm_be", "flac", "alac"}
RESOLUTIONS = ["480p", "720p", "1080p", "1440p", "2160p", "custom"]
RES_SHORT = {"480p": 480, "720p": 720, "1080p": 1080, "1440p": 1440, "2160p": 2160}
FPS_CHOICES = [10, 15, 24, 25, 30, 50, 60]
SPEEDS = ["fastest", "fast", "balanced", "small", "smallest"]
SPEED_LABELS = {"fastest": "Fastest export", "fast": "Fast", "balanced": "Balanced", "small": "Smaller file",
                "smallest": "Smallest file (slow)"}
LOUDNESS = {"off": None, "streaming": -14.0, "podcast": -16.0, "broadcast": -23.0}
LOUDNESS_LABELS = {"off": "Off", "streaming": "Streaming / YouTube / Spotify (-14 LUFS)",
                   "podcast": "Podcast (-16 LUFS)", "broadcast": "Broadcast / TV (-23 LUFS)"}


def fmt(key):
    return FORMATS[LEGACY.get(key, key)]


def kind(key):
    return fmt(key)["kind"]


def has_audio(key):
    f = fmt(key)
    return f["kind"] == "audio" or bool(f.get("acodec"))


def supports_rate_control(key):
    """Formats where quality/bitrate/target-size make sense."""
    return fmt(key).get("codec") in ("h264", "hevc", "vp9", "av1")


def supports_hw(key):
    return fmt(key).get("codec") in ("h264", "hevc")


# ----------------------------------------------------------------------------- settings
DEFAULTS = {
    "fmt": "mp4_h264",
    "aspect": "movie",
    "resolution": "1080p",
    "width": 1920,
    "height": 1080,
    "fps": 30,
    "rate_mode": "quality",       # quality | bitrate | size
    "quality": 80,                # 0..100 (100 = best)
    "video_kbps": 8000,
    "target_mb": 50.0,
    "speed": "balanced",
    "encoder": "auto",            # auto | cpu | a specific hardware encoder
    "ten_bit": False,
    "audio_kbps": 192,
    "sample_rate": 48000,
    "channels": 2,
    "bit_depth": 16,
    "loudness": "off",
    "include_audio": True,
    "range": "all",               # all | selection | custom
    "range_start": 0.0,
    "range_end": 0.0,
}


def settings_for(**kw):
    s = copy.deepcopy(DEFAULTS)
    s.update(kw)
    s["fmt"] = LEGACY.get(s["fmt"], s["fmt"])
    return s


def frame_size(s):
    """(w, h) for the settings: from aspect + resolution, or custom; always even."""
    if s.get("resolution") == "custom":
        w = max(16, int(s.get("width") or 1920))
        h = max(16, int(s.get("height") or 1080))
        return w // 2 * 2, h // 2 * 2
    res = s.get("resolution", "1080p")
    if res in formats.QUALITIES:
        return formats.canvas_size(s.get("aspect", "movie"), res)
    short = RES_SHORT.get(res, 1080)
    _, _, rw, rh, _ = formats.ASPECTS.get(s.get("aspect", "movie"), formats.ASPECTS["movie"])
    if rw >= rh:
        h, w = short, round(short * rw / rh)
    else:
        w, h = short, round(short * rh / rw)
    return int(w) // 2 * 2, int(h) // 2 * 2


# ----------------------------------------------------------------------------- quality mapping
def crf_for(codec, quality):
    """Map the 0..100 quality slider to each encoder's constant-quality number (lower = better)."""
    q = max(0.0, min(100.0, float(quality)))
    if codec in ("h264",):
        return int(round(36 - q * 0.2))          # 100 -> 16, 80 -> 20, 50 -> 26
    if codec == "hevc":
        return int(round(38 - q * 0.2))          # HEVC numbers run ~2 higher for the same look
    if codec == "vp9":
        return int(round(50 - q * 0.26))         # 100 -> 24, 50 -> 37
    if codec == "av1":
        return int(round(52 - q * 0.28))
    return 20


def quality_label(q):
    q = float(q)
    if q >= 92:
        return "Visually lossless"
    if q >= 75:
        return "High"
    if q >= 55:
        return "Good"
    if q >= 35:
        return "Medium"
    return "Low"


_SPEED_X264 = {"fastest": "ultrafast", "fast": "veryfast", "balanced": "medium", "small": "slow",
               "smallest": "veryslow"}
_SPEED_NVENC = {"fastest": "p1", "fast": "p3", "balanced": "p5", "small": "p6", "smallest": "p7"}
_SPEED_VPX = {"fastest": 8, "fast": 6, "balanced": 4, "small": 2, "smallest": 1}
_SPEED_AOM = {"fastest": 8, "fast": 7, "balanced": 6, "small": 5, "smallest": 4}
_SPEED_QSV = {"fastest": "veryfast", "fast": "faster", "balanced": "medium", "small": "slower",
              "smallest": "veryslow"}
_SPEED_AMF = {"fastest": "speed", "fast": "speed", "balanced": "balanced", "small": "quality",
              "smallest": "quality"}


def audio_kbps_effective(s):
    f = fmt(s["fmt"])
    ac = f.get("acodec")
    if not ac or not s.get("include_audio", True):
        return 0
    ch = int(s.get("channels", 2))
    sr = int(s.get("sample_rate", 48000))
    if ac in ("pcm", "pcm_be", "pcm24"):
        depth = 24 if ac == "pcm24" else int(s.get("bit_depth", 16))
        return sr * depth * ch / 1000
    if ac in ("flac", "alac"):
        return sr * int(s.get("bit_depth", 16)) * ch / 1000 * 0.58
    return int(s.get("audio_kbps", 192))


def video_kbps_for_size(s, duration):
    """Video bitrate that hits the target file size (leaving room for audio and container overhead)."""
    total_kbits = float(s.get("target_mb", 50)) * 8 * 1024 * 0.97
    v = total_kbits / max(0.5, duration) - audio_kbps_effective(s)
    return max(80, int(v))


def estimate_bytes(s, duration):
    """Rough output size in bytes (good to ~±30% for quality mode, exact-ish for bitrate/size modes)."""
    f = fmt(s["fmt"])
    duration = max(0.0, float(duration))
    a_kbps = audio_kbps_effective(s)
    if f["kind"] == "audio":
        return int(a_kbps * 1000 / 8 * duration)
    w, h = frame_size(s)
    fps = int(s.get("fps", 30))
    codec = f.get("codec")
    if codec == "png":
        return int(w * h * 0.3 * fps * duration)
    if codec == "gif":
        return int(w * h * 0.07 * fps * duration)
    if codec == "webp":
        return int(w * h * 0.03 * fps * duration)
    if codec == "prores":
        return int((220_000 * (w * h * fps) / (1920 * 1080 * 30) + a_kbps) * 1000 / 8 * duration)
    mode = s.get("rate_mode", "quality")
    if mode == "size":
        return int(float(s.get("target_mb", 50)) * 1024 * 1024)
    if mode == "bitrate":
        v_kbps = float(s.get("video_kbps", 8000))
    else:
        base = {"h264": 0.085, "hevc": 0.05, "vp9": 0.055, "av1": 0.042}.get(codec, 0.085)
        bpp = base * 2 ** ((float(s.get("quality", 80)) - 80) / 14.0)
        # motion matters less per pixel at high resolutions / frame rates
        v_kbps = w * h * fps * bpp / 1000 * (1080 * 1920 / max(1, w * h)) ** 0.25 * (30 / max(1, fps)) ** 0.35
    return int((v_kbps + a_kbps) * 1000 / 8 * duration * 1.02)


def size_label(n):
    n = float(n)
    if n < 1024 * 1024:
        return f"{max(1, n / 1024):.0f} KB"
    if n < 1024 ** 3:
        return f"{n / 1024 / 1024:.1f} MB" if n < 100 * 1024 * 1024 else f"{n / 1024 / 1024:.0f} MB"
    return f"{n / 1024 ** 3:.2f} GB"


# ----------------------------------------------------------------------------- encoder arguments
def video_args(s, enc, duration, pass_no=None, passlog=None):
    """FFmpeg output arguments for the video stream."""
    f = fmt(s["fmt"])
    codec = f["codec"]
    mode = s.get("rate_mode", "quality")
    speed = s.get("speed", "balanced")
    kbps = int(s.get("video_kbps", 8000)) if mode == "bitrate" else video_kbps_for_size(s, duration) \
        if mode == "size" else None
    ten = bool(s.get("ten_bit")) and codec in ("hevc", "av1", "vp9")
    pix = "yuv420p10le" if ten else "yuv420p"
    if codec == "gif":
        return ["-loop", "0"]
    if codec == "webp":
        q = int(max(10, min(100, float(s.get("quality", 80)))))
        return ["-c:v", "libwebp_anim", "-lossless", "0", "-q:v", str(q), "-loop", "0", "-pix_fmt", "yuva420p"]
    if codec == "png":
        return ["-c:v", "png", "-pix_fmt", "rgb24"]
    if codec == "prores":
        return ["-c:v", "prores_ks", "-profile:v", "3", "-vendor", "apl0", "-pix_fmt", "yuv422p10le"]
    out = []
    if codec in ("h264", "hevc"):
        if enc in ("h264_nvenc", "hevc_nvenc"):
            out = ["-c:v", enc, "-preset", _SPEED_NVENC[speed], "-tune", "hq"]
            if kbps:
                out += ["-rc", "vbr", "-b:v", f"{kbps}k", "-maxrate", f"{int(kbps * 1.5)}k",
                        "-bufsize", f"{kbps * 2}k"]
            else:
                out += ["-rc", "vbr", "-cq", str(crf_for(codec, s.get("quality", 80))), "-b:v", "0"]
            if ten:
                pix = "p010le"
        elif enc in ("h264_qsv", "hevc_qsv"):
            out = ["-c:v", enc, "-preset", _SPEED_QSV[speed]]
            out += ["-b:v", f"{kbps}k", "-maxrate", f"{int(kbps * 1.5)}k"] if kbps else \
                ["-global_quality", str(crf_for(codec, s.get("quality", 80)))]
            pix = "p010le" if ten else "nv12"
        elif enc in ("h264_amf", "hevc_amf"):
            out = ["-c:v", enc, "-quality", _SPEED_AMF[speed]]
            if kbps:
                out += ["-rc", "vbr_peak", "-b:v", f"{kbps}k", "-maxrate", f"{int(kbps * 1.5)}k"]
            else:
                q = crf_for(codec, s.get("quality", 80))
                out += ["-rc", "cqp", "-qp_i", str(q), "-qp_p", str(q + 2)]
                if codec == "h264":
                    out += ["-qp_b", str(q + 4)]
        else:
            lib = "libx264" if codec == "h264" else "libx265"
            out = ["-c:v", lib, "-preset", _SPEED_X264[speed]]
            if kbps:
                out += ["-b:v", f"{kbps}k"]
                if mode == "bitrate":
                    out += ["-maxrate", f"{int(kbps * 1.5)}k", "-bufsize", f"{kbps * 2}k"]
            else:
                out += ["-crf", str(crf_for(codec, s.get("quality", 80)))]
            if lib == "libx265":
                params = "log-level=error"
                if pass_no:
                    params += f":pass={pass_no}:stats={passlog}.log"
                out += ["-x265-params", params]
            elif pass_no:
                out += ["-pass", str(pass_no), "-passlogfile", passlog]
        if codec == "hevc":
            out += ["-tag:v", "hvc1"]
        out += ["-pix_fmt", pix]
    elif codec == "vp9":
        out = ["-c:v", "libvpx-vp9", "-row-mt", "1", "-deadline", "good", "-cpu-used", str(_SPEED_VPX[speed]),
               "-pix_fmt", pix]
        out += ["-b:v", f"{kbps}k"] if kbps else ["-crf", str(crf_for("vp9", s.get("quality", 80))), "-b:v", "0"]
        if pass_no:
            out += ["-pass", str(pass_no), "-passlogfile", passlog]
    elif codec == "av1":
        out = ["-c:v", "libaom-av1", "-row-mt", "1", "-cpu-used", str(_SPEED_AOM[speed]), "-pix_fmt", pix,
               "-tiles", "2x2"]
        out += ["-b:v", f"{kbps}k"] if kbps else ["-crf", str(crf_for("av1", s.get("quality", 80))), "-b:v", "0"]
        if pass_no:
            out += ["-pass", str(pass_no), "-passlogfile", passlog]
    w, h = frame_size(s)
    if codec == "h264" and enc in (None, "libx264", "cpu", "auto") and (w * h > 1920 * 1088 or s.get("fps", 30) > 30):
        out += ["-level:v", "5.2"]
    return out


def audio_args(s):
    """FFmpeg output arguments for the audio stream ([] when the format has no sound)."""
    f = fmt(s["fmt"])
    ac = f.get("acodec")
    if not ac or not s.get("include_audio", True):
        return ["-an"]
    sr = int(s.get("sample_rate", 48000))
    ch = int(s.get("channels", 2))
    kbps = int(s.get("audio_kbps", 192))
    depth = int(s.get("bit_depth", 16))
    if ac == "opus" and sr not in (8000, 12000, 16000, 24000, 48000):
        sr = 48000
    if ac == "aac":
        a = ["-c:a", "aac", "-b:a", f"{kbps}k"]
    elif ac == "mp3":
        a = ["-c:a", "libmp3lame", "-b:a", f"{kbps}k"]
    elif ac == "opus":
        a = ["-c:a", "libopus", "-b:a", f"{kbps}k", "-vbr", "on"]
    elif ac == "vorbis":
        a = ["-c:a", "libvorbis", "-b:a", f"{kbps}k"]
    elif ac == "flac":
        a = ["-c:a", "flac", "-compression_level", "8", "-sample_fmt", "s32" if depth == 24 else "s16"]
        if depth == 24:
            a += ["-bits_per_raw_sample", "24"]
    elif ac == "alac":
        a = ["-c:a", "alac", "-sample_fmt", "s32p" if depth == 24 else "s16p"]
    elif ac == "pcm":
        a = ["-c:a", "pcm_s24le" if depth == 24 else "pcm_s16le"]
    elif ac == "pcm_be":
        a = ["-c:a", "pcm_s24be" if depth == 24 else "pcm_s16be"]
    elif ac == "pcm24":
        a = ["-c:a", "pcm_s24le"]
    else:
        a = ["-c:a", "aac", "-b:a", f"{kbps}k"]
    return a + ["-ar", str(sr), "-ac", str(ch)]


def container_args(s):
    f = fmt(s["fmt"])
    if f["ext"] in (".mp4", ".m4a", ".mov"):
        return ["-movflags", "+faststart"]
    return []


# ----------------------------------------------------------------------------- presets
# (id, group, name, sub-heading, icon, settings)
PRESETS = [
    ("yt1080", "Video", "YouTube 1080p", "Full HD for YouTube & Vimeo", "export",
     dict(fmt="mp4_h264", aspect="movie", resolution="1080p", quality=82, loudness="streaming")),
    ("yt4k", "Video", "YouTube 4K", "2160p - the sharpest upload", "export",
     dict(fmt="mp4_h264", aspect="movie", resolution="2160p", quality=82, loudness="streaming")),
    ("tiktok", "Video", "TikTok · Reels · Shorts", "Vertical 1080×1920", "media",
     dict(fmt="mp4_h264", aspect="tiktok", resolution="1080p", quality=80, loudness="streaming")),
    ("insta", "Video", "Instagram Post", "4:5 portrait feed post", "image",
     dict(fmt="mp4_h264", aspect="portrait45", resolution="1080p", quality=80, loudness="streaming")),
    ("discord", "Video", "Discord (under 10 MB)", "Fits the free upload limit", "export",
     dict(fmt="mp4_h264", resolution="720p", rate_mode="size", target_mb=9.5, audio_kbps=96,
          speed="small")),
    ("email", "Video", "Small file (under 25 MB)", "Email, WhatsApp & chats", "export",
     dict(fmt="mp4_h264", resolution="720p", rate_mode="size", target_mb=24, audio_kbps=128,
          speed="small")),
    ("hevc", "Video", "High quality, small size", "H.265 - half the size", "export",
     dict(fmt="mp4_hevc", resolution="1080p", quality=82)),
    ("master", "Video", "Master for editing", "ProRes 422 HQ · near-lossless", "save",
     dict(fmt="mov_prores", resolution="1080p", sample_rate=48000)),
    ("gif", "Video", "GIF", "Short looping clip, 10 fps", "image",
     dict(fmt="gif", resolution="480p", fps=10)),
    ("mp3", "Audio", "Music · MP3 320", "Best-quality MP3", "music",
     dict(fmt="mp3", audio_kbps=320, sample_rate=44100, loudness="streaming")),
    ("wav", "Audio", "Studio · WAV 24-bit", "Uncompressed master", "music",
     dict(fmt="wav", bit_depth=24, sample_rate=48000)),
    ("flac", "Audio", "Lossless · FLAC", "Studio quality, smaller", "music",
     dict(fmt="flac", bit_depth=16, sample_rate=44100)),
    ("podcast", "Audio", "Podcast", "MP3 128k mono · -16 LUFS", "audio",
     dict(fmt="mp3", audio_kbps=128, channels=1, sample_rate=44100, loudness="podcast")),
    ("apple", "Audio", "Apple Music · M4A", "AAC 256k", "music",
     dict(fmt="m4a", audio_kbps=256, sample_rate=44100, loudness="streaming")),
]


def preset(pid):
    for p in PRESETS:
        if p[0] == pid:
            return p
    return None


def preset_settings(pid, project_fps=30, project_aspect="movie"):
    """Settings for a built-in preset; presets without a fixed shape follow the project's canvas."""
    p = preset(pid)
    s = settings_for(fps=project_fps if project_fps in FPS_CHOICES else 30, aspect=project_aspect)
    if p:
        s.update(copy.deepcopy(p[5]))
    return s


def describe(s, duration=None):
    """Short human summary: '1920×1080 · 30 fps · MP4 · H.264 · ≈ 45 MB'."""
    f = fmt(s["fmt"])
    parts = []
    if f["kind"] == "audio":
        ac = f["acodec"]
        parts.append(f["name"])
        if ac in LOSSLESS_AUDIO:
            parts.append(f"{int(s.get('bit_depth', 16))}-bit")
        else:
            parts.append(f"{int(s.get('audio_kbps', 192))} kbps")
        parts.append(f"{int(s.get('sample_rate', 48000)) / 1000:g} kHz")
        parts.append("stereo" if int(s.get("channels", 2)) == 2 else "mono")
    else:
        w, h = frame_size(s)
        parts += [f"{w}×{h}", f"{int(s.get('fps', 30))} fps", f["name"]]
    if duration:
        parts.append("≈ " + size_label(estimate_bytes(s, duration)))
    return "  ·  ".join(parts)


# ----------------------------------------------------------------------------- user presets
def _user_file():
    from .config import data_path
    return data_path("export_presets.json")


def user_presets():
    try:
        with open(_user_file(), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_user_preset(name, s):
    data = user_presets()
    data[name] = {k: s[k] for k in DEFAULTS if k in s and k not in ("range", "range_start", "range_end")}
    tmp = _user_file() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, _user_file())


def delete_user_preset(name):
    data = user_presets()
    if name in data:
        del data[name]
        with open(_user_file(), "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)


def sanitize(name):
    bad = '<>:"/\\|?*'
    out = "".join("_" if ch in bad or ord(ch) < 32 else ch for ch in name).strip().rstrip(".")
    return out or "Easy-Cut export"


def isclose(a, b):
    return math.isclose(float(a), float(b), rel_tol=1e-6, abs_tol=1e-6)
