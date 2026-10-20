"""Retro FX - video effects. Each has an FFmpeg chain for the export and a numpy preview.

Template values: {amount} (0..1 from the slider), {w} {h} {short} (picture size), {u} (unique label).
Sizes are worked out relative to the picture so the preview and the export look the same."""
import math

import numpy as np


def _shift(img, dx):
    """Shift columns by dx with edge smear (same as FFmpeg rgbashift edge=smear)."""
    if dx == 0:
        return img
    out = np.empty_like(img)
    if dx > 0:
        out[:, dx:] = img[:, :-dx]
        out[:, :dx] = img[:, :1]
    else:
        out[:, :dx] = img[:, -dx:]
        out[:, dx:] = img[:, -1:]
    return out


def _split_px(short, amount, k):
    return int(round(short * k * amount))


def _rgb_split(bgr, amount, k):
    s = _split_px(min(bgr.shape[:2]), amount, k)
    out = bgr.copy()
    out[:, :, 2] = _shift(bgr[:, :, 2], -s)
    out[:, :, 0] = _shift(bgr[:, :, 0], s)
    return out


def _noise(bgr, strength):
    n = np.random.default_rng().integers(-strength, strength + 1, bgr.shape, dtype=np.int16)
    return np.clip(bgr.astype(np.int16) + n, 0, 255).astype(np.uint8)


def vhs(bgr, amount):
    return _noise(_rgb_split(bgr, amount, 0.005), int(14 * amount))


def grain(bgr, amount):
    return _noise(bgr, int(22 * amount))


def vignette(bgr, amount):
    h, w = bgr.shape[:2]
    angle = 0.3 + 0.6 * amount
    y, x = np.ogrid[:h, :w]
    d = np.hypot(x - w / 2, y - h / 2) / math.hypot(w / 2, h / 2)
    c = np.cos(angle * np.minimum(d, 1.0))
    f = (c * c) * (c * c)
    return np.clip(bgr * f[..., None] + 0.5, 0, 255).astype(np.uint8)


def block_size(short, amount):
    return max(2, int(round(short * (0.008 + 0.035 * amount))))


def pixelate(bgr, amount):
    h, w = bgr.shape[:2]
    b = block_size(min(h, w), amount)
    out = bgr.copy()
    for y in range(0, h, b):
        for x in range(0, w, b):
            blk = bgr[y:y + b, x:x + b]
            out[y:y + b, x:x + b] = blk.reshape(-1, 3).mean(axis=0)
    return out


def rgb_split(bgr, amount):
    return _rgb_split(bgr, amount, 0.012)


def register(api):
    api.register_effect(
        "rfx-vhs", "VHS", preview=vhs,
        ffmpeg=lambda a, w, h, u: (f"rgbashift=rh={-_split_px(min(w, h), a, 0.005)}:bh={_split_px(min(w, h), a, 0.005)}"
                                   f":edge=smear,noise=c0s={int(14 * a)}:c1s={int(14 * a)}:c2s={int(14 * a)}:allf=t"))
    api.register_effect(
        "rfx-grain", "Film Grain", preview=grain,
        ffmpeg=lambda a, w, h, u: f"noise=c0s={int(22 * a)}:c1s={int(22 * a)}:c2s={int(22 * a)}:allf=t")
    api.register_effect(
        "rfx-vignette", "Vignette", preview=vignette,
        ffmpeg=lambda a, w, h, u: (f"[in]split[{u}a][{u}b];[{u}a]format=rgb24,vignette=angle={0.3 + 0.6 * a:.4f}"
                                   f",format=rgba[{u}c];[{u}b]alphaextract[{u}m];[{u}c][{u}m]alphamerge[out]"))
    api.register_effect(
        "rfx-pixelate", "Pixelate", preview=pixelate,
        ffmpeg=lambda a, w, h, u: f"pixelize=w={block_size(min(w, h), a)}:h={block_size(min(w, h), a)}")
    api.register_effect(
        "rfx-rgb-split", "RGB Split", preview=rgb_split,
        ffmpeg=lambda a, w, h, u: (f"rgbashift=rh={-_split_px(min(w, h), a, 0.012)}:bh={_split_px(min(w, h), a, 0.012)}"
                                   f":edge=smear"))
