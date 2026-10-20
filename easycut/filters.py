"""Colour filters.

Built-in filters are colour matrices plus tone settings (contrast / brightness / lifted blacks). The exact
same maths runs in the preview (numpy/OpenCV) and in the export (FFmpeg colorchannelmixer + lutrgb), so what
you see is what you get. Extensions can register more filters with `register()`.
"""
import numpy as np

LUMA = np.array([0.299, 0.587, 0.114])
I3 = np.eye(3)


def _sat(s):
    return (1 - s) * np.tile(LUMA, (3, 1)) + s * I3


SEPIA = np.array([[0.393, 0.769, 0.189], [0.349, 0.686, 0.168], [0.272, 0.534, 0.131]])
MONO = np.tile(LUMA, (3, 1))


class Filter:
    def __init__(self, fid, name, matrix=None, contrast=1.0, brightness=0.0, lift=0.0, swatch=None,
                 ffmpeg=None, preview=None, source="built-in"):
        self.id = fid
        self.name = name
        self.matrix = np.array(matrix if matrix is not None else I3, dtype=float)
        self.contrast = contrast
        self.brightness = brightness
        self.lift = lift
        self.swatch = swatch
        self.ffmpeg = ffmpeg          # optional custom chain for extension filters, may use {amount}
        self.preview = preview        # optional fn(bgr_uint8, amount) -> bgr_uint8
        self.source = source


FILTERS = {}
ORDER = []


def register(f: Filter):
    if f.id not in FILTERS:
        ORDER.append(f.id)
    FILTERS[f.id] = f
    return f


register(Filter("none", "None"))
register(Filter("vivid", "Vivid", _sat(1.4), contrast=1.08, swatch="#ff5c8a"))
register(Filter("warm", "Warm", np.diag([1.10, 1.0, 0.86]) @ _sat(1.08), brightness=0.02, swatch="#ffa94d"))
register(Filter("cool", "Cool", np.diag([0.88, 1.0, 1.12]), contrast=1.04, swatch="#4dabf7"))
register(Filter("bw", "B&W", MONO, contrast=1.05, swatch="#adb5bd"))
register(Filter("vintage", "Vintage", 0.55 * SEPIA + 0.45 * I3, contrast=0.9, lift=0.07, swatch="#c9a66b"))
register(Filter("noir", "Noir", MONO, contrast=1.4, brightness=-0.03, swatch="#343a40"))


def get(fid) -> Filter:
    return FILTERS.get(fid) or FILTERS["none"]


# Video effects added by extensions (stackable, stored on a clip as clip["fx"] = [{"id", "amount"}])
EFFECTS = {}
EFFECT_ORDER = []


def register_effect(f: Filter):
    if f.id not in EFFECTS:
        EFFECT_ORDER.append(f.id)
    EFFECTS[f.id] = f
    return f


# ---------------------------------------------------------------------- combined colour stage
def colour_params(clip):
    """(3x3 matrix, contrast, brightness, lift) combining the clip's filter and its Adjust sliders."""
    f = get(clip.get("filter", "none"))
    k = float(clip.get("filter_amount", 1.0)) if f.ffmpeg is None else 0.0
    m = (1 - k) * I3 + k * f.matrix
    m = _sat(float(clip.get("saturation", 1.0))) @ m
    c = (1 + (f.contrast - 1) * k) * float(clip.get("contrast", 1.0))
    b = f.brightness * k + float(clip.get("brightness", 0.0)) * 0.4
    lift = f.lift * k
    return m, c, b, lift


def is_identity(m, c, b, lift) -> bool:
    return np.allclose(m, I3, atol=1e-4) and abs(c - 1) < 1e-4 and abs(b) < 1e-4 and lift < 1e-4


def lut(c, b, lift) -> np.ndarray:
    v = np.arange(256, dtype=np.float64)
    x = v * (1 - lift) + lift * 255
    x = (x - 128) * c + 128 + b * 255
    return np.clip(np.round(x), 0, 255).astype(np.uint8)


def apply_preview(bgr: np.ndarray, clip) -> np.ndarray:
    """Apply the clip's colour stage to a BGR or BGRA uint8 image."""
    import cv2
    f = get(clip.get("filter", "none"))
    m, c, b, lift = colour_params(clip)
    out = bgr
    if not is_identity(m, c, b, lift):
        rgb_to_bgr = np.array([[0, 0, 1], [0, 1, 0], [1, 0, 0]], dtype=float)
        mb = rgb_to_bgr @ m @ rgb_to_bgr
        alpha = out[:, :, 3:4] if out.shape[2] == 4 else None
        col = out[:, :, :3]
        if not np.allclose(m, I3, atol=1e-4):
            col = cv2.transform(col, mb.astype(np.float32))
        if abs(c - 1) > 1e-4 or abs(b) > 1e-4 or lift > 1e-4:
            col = cv2.LUT(col, lut(c, b, lift))
        out = np.concatenate([col, alpha], axis=2) if alpha is not None else col
    if f.preview is not None and float(clip.get("filter_amount", 1.0)) > 0:
        try:
            res = f.preview(out[:, :, :3].copy(), float(clip.get("filter_amount", 1.0)))
            if out.shape[2] == 4:
                out = np.concatenate([res, out[:, :, 3:4]], axis=2)
            else:
                out = res
        except Exception:
            pass
    for fx in clip.get("fx", []) or []:
        e = EFFECTS.get(fx.get("id"))
        if e is None or e.preview is None:
            continue
        try:
            res = e.preview(out[:, :, :3].copy(), float(fx.get("amount", 1.0)))
            out = np.concatenate([res, out[:, :, 3:4]], axis=2) if out.shape[2] == 4 else res
        except Exception:
            pass
    return np.ascontiguousarray(out)


def _fmt(template, amount, w, h, uid):
    """An effect's FFmpeg step: a template string ({amount} {w} {h} {short} {u}) or fn(amount, w, h, uid)."""
    w = int(w or 1920)
    h = int(h or 1080)
    if callable(template):
        return template(amount, w, h, uid)
    return template.format(amount=amount, w=w, h=h, short=min(w, h), u=uid)


def ffmpeg_chain(clip, w=None, h=None, uid="x") -> list:
    """FFmpeg steps for the clip's colour stage and effects (expects rgba frames).

    Items are plain filter strings, or ("graph", text) for effects that need a small sub-graph; those use
    the labels [in] and [out]. `w`/`h` is the picture size so effects can scale with it."""
    f = get(clip.get("filter", "none"))
    m, c, b, lift = colour_params(clip)
    parts = []
    if not np.allclose(m, I3, atol=1e-4):
        names = ["rr", "rg", "rb", "gr", "gg", "gb", "br", "bg", "bb"]
        vals = m.flatten()
        parts.append("colorchannelmixer=" + ":".join(f"{n}={v:.5f}" for n, v in zip(names, vals)))
    if abs(c - 1) > 1e-4 or abs(b) > 1e-4 or lift > 1e-4:
        expr = f"clip(((val*{1 - lift:.5f}+{lift * 255:.4f})-128)*{c:.5f}+128+{b * 255 + 0.5:.4f}\\,0\\,255)"
        parts.append(f"lutrgb=r='{expr}':g='{expr}':b='{expr}'")
    if f.ffmpeg:
        parts.append(_fmt(f.ffmpeg, float(clip.get("filter_amount", 1.0)), w, h, uid + "f"))
    for i, fx in enumerate(clip.get("fx", []) or []):
        e = EFFECTS.get(fx.get("id"))
        if e is None or not e.ffmpeg:
            continue
        amount = float(fx.get("amount", 1.0))
        if amount <= 0.001:
            continue
        text = _fmt(e.ffmpeg, amount, w, h, f"{uid}e{i}")
        parts.append(("graph", text) if "[in]" in text else text)
    return parts


def chain_to_graph(parts, inp, out, uid):
    """Turn ffmpeg_chain() output into filter-graph text from label [inp] to label [out]."""
    segs = []
    cur = inp
    linear = []
    n = 0
    for item in parts + [None]:
        if item is None or isinstance(item, tuple):
            if linear or item is None:
                nxt = out if item is None else f"{uid}c{n}"
                segs.append(f"[{cur}]" + (",".join(linear) if linear else "null") + f"[{nxt}]")
                cur = nxt
                linear = []
                n += 1
            if item is not None:
                nxt = f"{uid}c{n}"
                segs.append(item[1].replace("[in]", f"[{cur}]").replace("[out]", f"[{nxt}]"))
                cur = nxt
                n += 1
        else:
            linear.append(item)
    return ";".join(segs)
