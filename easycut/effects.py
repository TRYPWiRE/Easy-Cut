"""Video effects & compositing: crop, flip, mirror, chroma key, stabilization, speed/pitch.

Every effect has a preview implementation (numpy/OpenCV on small frames) and an FFmpeg implementation for the
export. Geometry helpers here are shared by both so sizes line up exactly.
"""
import math

import numpy as np

MIRROR_MODES = [
    ("none", "Off"),
    ("left", "Left → Right"),
    ("right", "Right → Left"),
    ("top", "Top → Bottom"),
    ("bottom", "Bottom → Top"),
]


def _even(v):
    return max(2, int(v) // 2 * 2)


# ---------------------------------------------------------------------- geometry
def crop_box(w, h, crop):
    """(x, y, cw, ch) integer crop rectangle - identical maths for preview and export."""
    l, t, r, b = [min(0.95, max(0.0, float(v))) for v in crop]
    if l + r > 0.95:
        r = 0.95 - l
    if t + b > 0.95:
        b = 0.95 - t
    cw = _even(w * (1 - l - r))
    ch = _even(h * (1 - t - b))
    x = int(w * l)
    y = int(h * t)
    x = min(x, max(0, w - cw))
    y = min(y, max(0, h - ch))
    return x, y, cw, ch


def has_crop(clip):
    return any(float(v) > 0.0005 for v in clip.get("crop", [0, 0, 0, 0]))


def content_size(clip, w, h):
    """Size of the clip's picture after crop and mirror, from a source size."""
    if has_crop(clip):
        _, _, w, h = crop_box(w, h, clip["crop"])
    m = clip.get("mirror", "none")
    if m in ("left", "right"):
        w = (w // 4) * 2 * 2
    elif m in ("top", "bottom"):
        h = (h // 4) * 2 * 2
    return max(2, w), max(2, h)


def fitted_size(clip, cw, ch, W, H, text_scale=None):
    """Clip's base on-canvas size (before animation) for content size cw x ch on a W x H canvas."""
    s = float(clip.get("scale", 1.0))
    if clip.get("kind") == "text":
        base = text_scale if text_scale is not None else 1.0
        return max(2.0, cw * s * base), max(2.0, ch * s * base)
    if clip.get("fit", "fit") == "fill":
        f = max(W / cw, H / ch)
    else:
        f = min(W / cw, H / ch)
    return max(2.0, cw * f * s), max(2.0, ch * f * s)


# ---------------------------------------------------------------------- preview implementations
def apply_crop(img, clip):
    if not has_crop(clip):
        return img
    h, w = img.shape[:2]
    x, y, cw, ch = crop_box(w, h, clip["crop"])
    return img[y:y + ch, x:x + cw]


def apply_flip(img, clip):
    if clip.get("flip_h"):
        img = img[:, ::-1]
    if clip.get("flip_v"):
        img = img[::-1]
    return img


def apply_mirror(img, clip):
    m = clip.get("mirror", "none")
    if m == "none":
        return img
    h, w = img.shape[:2]
    if m in ("left", "right"):
        hw = (w // 4) * 2
        if hw < 1:
            return img
        if m == "left":
            half = img[:, :hw]
            return np.concatenate([half, half[:, ::-1]], axis=1)
        half = img[:, w - hw:]
        return np.concatenate([half[:, ::-1], half], axis=1)
    hh = (h // 4) * 2
    if hh < 1:
        return img
    if m == "top":
        half = img[:hh]
        return np.concatenate([half, half[::-1]], axis=0)
    half = img[h - hh:]
    return np.concatenate([half[::-1], half], axis=0)


def hex_to_rgb(hexstr):
    hexstr = hexstr.lstrip("#")
    if len(hexstr) != 6:
        return 0, 255, 0
    return tuple(int(hexstr[i:i + 2], 16) for i in (0, 2, 4))


def _uv(r, g, b):
    """BT.601 limited-range chroma (as FFmpeg's chromakey uses), float arrays or scalars."""
    u = -0.148 * r - 0.291 * g + 0.439 * b + 128
    v = 0.439 * r - 0.368 * g - 0.071 * b + 128
    return u, v


def _uv_full(r, g, b):
    """Full-range BT.601 chroma - FFmpeg's chromakey converts the *key colour* this way."""
    u = -0.16874 * r - 0.33126 * g + 0.5 * b + 128
    v = 0.5 * r - 0.41869 * g - 0.08131 * b + 128
    return u, v


def chroma_alpha(bgr, color_hex, similarity, blend):
    """uint8 alpha mask matching FFmpeg's chromakey filter (key colour full-range, pixels limited-range)."""
    import cv2
    r0, g0, b0 = hex_to_rgb(color_hex)
    ku, kv = _uv_full(r0, g0, b0)
    f = bgr[:, :, :3].astype(np.float32)
    u, v = _uv(f[:, :, 2], f[:, :, 1], f[:, :, 0])
    diff = np.sqrt(((u - ku) ** 2 + (v - kv) ** 2) / (255.0 * 255.0 * 2))
    diff = cv2.blur(diff, (3, 3))
    similarity = max(0.00001, float(similarity))
    if float(blend) > 0.0001:
        a = np.clip((diff - similarity) / float(blend), 0, 1)
    else:
        a = (diff > similarity).astype(np.float32)
    return (a * 255).astype(np.uint8)


def to_bgra(img):
    import cv2
    if img.shape[2] == 4:
        return img
    return cv2.cvtColor(np.ascontiguousarray(img), cv2.COLOR_BGR2BGRA)


def apply_chroma(img, clip):
    if not clip.get("chroma"):
        return img
    img = to_bgra(np.ascontiguousarray(img))
    a = chroma_alpha(img, clip.get("chroma_color", "#00ff00"), clip.get("chroma_similarity", 0.15),
                     clip.get("chroma_blend", 0.08))
    img = img.copy()
    img[:, :, 3] = (img[:, :, 3].astype(np.uint16) * a // 255).astype(np.uint8)
    return img


def process_preview(img, clip):
    """Crop -> flip -> mirror -> chroma key on a BGR/BGRA frame (colour is applied afterwards)."""
    img = apply_crop(img, clip)
    img = apply_flip(img, clip)
    img = apply_mirror(img, clip)
    img = apply_chroma(np.ascontiguousarray(img), clip)
    return np.ascontiguousarray(img)


def rotate_bgra(img, degrees):
    """Rotate with expanded bounds and transparent corners (matches FFmpeg rotate rotw/roth)."""
    import cv2
    if abs(degrees) < 0.01:
        return img
    img = to_bgra(img)
    h, w = img.shape[:2]
    a = math.radians(degrees)
    nw = int(abs(w * math.cos(a)) + abs(h * math.sin(a)) + 0.5)
    nh = int(abs(w * math.sin(a)) + abs(h * math.cos(a)) + 0.5)
    m = cv2.getRotationMatrix2D((w / 2, h / 2), -degrees, 1.0)
    m[0, 2] += (nw - w) / 2
    m[1, 2] += (nh - h) / 2
    return cv2.warpAffine(img, m, (max(1, nw), max(1, nh)), flags=cv2.INTER_LINEAR,
                          borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))


# ---------------------------------------------------------------------- export (FFmpeg) chains
def crop_ffmpeg(clip, w, h):
    if not has_crop(clip):
        return []
    x, y, cw, ch = crop_box(w, h, clip["crop"])
    return [f"crop={cw}:{ch}:{x}:{y}"]


def flip_ffmpeg(clip):
    out = []
    if clip.get("flip_h"):
        out.append("hflip")
    if clip.get("flip_v"):
        out.append("vflip")
    return out


def mirror_graph(clip, inp, out, uid):
    """Filter-graph text that mirrors stream [inp] into [out]; '' when off."""
    m = clip.get("mirror", "none")
    if m == "none":
        return ""
    a, b, c = f"m{uid}a", f"m{uid}b", f"m{uid}c"
    if m == "left":
        return (f"[{inp}]crop=trunc(iw/4)*2:ih:0:0,split[{a}][{b}];[{b}]hflip[{c}];"
                f"[{a}][{c}]hstack=inputs=2[{out}]")
    if m == "right":
        return (f"[{inp}]crop=trunc(iw/4)*2:ih:iw-trunc(iw/4)*2:0,split[{a}][{b}];[{a}]hflip[{c}];"
                f"[{c}][{b}]hstack=inputs=2[{out}]")
    if m == "top":
        return (f"[{inp}]crop=iw:trunc(ih/4)*2:0:0,split[{a}][{b}];[{b}]vflip[{c}];"
                f"[{a}][{c}]vstack=inputs=2[{out}]")
    return (f"[{inp}]crop=iw:trunc(ih/4)*2:0:ih-trunc(ih/4)*2,split[{a}][{b}];[{a}]vflip[{c}];"
            f"[{c}][{b}]vstack=inputs=2[{out}]")


def chroma_ffmpeg(clip):
    if not clip.get("chroma"):
        return []
    col = clip.get("chroma_color", "#00ff00").lstrip("#")
    sim = max(0.00001, float(clip.get("chroma_similarity", 0.15)))
    blend = max(0.0, float(clip.get("chroma_blend", 0.08)))
    return [f"chromakey=color=0x{col}:similarity={sim:.4f}:blend={blend:.4f}"]


def stabilize_strength(clip):
    s = min(1.0, max(0.0, float(clip.get("stabilize_strength", 0.5))))
    shakiness = max(1, min(10, int(round(3 + s * 7))))
    smoothing = int(round(8 + s * 40))
    return shakiness, smoothing


# ---------------------------------------------------------------------- audio
def atempo_chain(factor):
    """atempo only accepts 0.5..100 per instance on older builds - chain instances for any factor."""
    parts = []
    f = float(factor)
    if abs(f - 1) < 1e-4:
        return parts
    while f < 0.5:
        parts.append("atempo=0.5")
        f /= 0.5
    while f > 2.0:
        parts.append("atempo=2.0")
        f /= 2.0
    parts.append(f"atempo={f:.6f}")
    return parts


def audio_speed_pitch(clip, sample_rate=48000):
    """Audio filters for the clip's speed, keep-pitch setting and pitch shift (semitones)."""
    speed = max(0.05, float(clip.get("speed", 1.0)))
    semis = float(clip.get("pitch", 0.0))
    sr = int(sample_rate or 48000)
    if not clip.get("keep_pitch", True):
        # tape-style: pitch follows speed
        semis += 12 * math.log2(speed)
    ratio = 2 ** (semis / 12.0)
    parts = []
    if abs(ratio - 1) > 1e-4:
        parts.append(f"asetrate={sr * ratio:.2f}")
        parts.append(f"aresample={sr}")
        parts += atempo_chain(speed / ratio)
    else:
        parts += atempo_chain(speed)
    return parts
