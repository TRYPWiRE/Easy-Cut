"""Stylize FX - video effects (FFmpeg for the export, OpenCV/numpy for the preview)."""
import numpy as np


def sigma(short, amount):
    return max(0.3, short * 0.012 * amount)


def blur(bgr, amount):
    import cv2
    return cv2.GaussianBlur(bgr, (0, 0), sigma(min(bgr.shape[:2]), amount))


def _kernel_sharpen(amount):
    m = int(round(10 * amount))
    k = np.array([[0, -m, 0], [-m, 10 + 4 * m, -m], [0, -m, 0]], np.float32)
    return k, m


def sharpen(bgr, amount):
    import cv2
    k, _ = _kernel_sharpen(amount)
    return cv2.filter2D(bgr, -1, k / 10.0, borderType=cv2.BORDER_REPLICATE)


def _sharpen_ff(a, w, h, u):
    k, m = _kernel_sharpen(a)
    mat = " ".join(str(int(v)) for v in k.flatten())
    return f"convolution=0m='{mat}':1m='{mat}':2m='{mat}':0rdiv=0.1:1rdiv=0.1:2rdiv=0.1"


def glow(bgr, amount):
    import cv2
    b = cv2.GaussianBlur(bgr, (0, 0), max(0.3, min(bgr.shape[:2]) * 0.02)).astype(np.float32)
    a = bgr.astype(np.float32)
    screen = 255 - (255 - a) * (255 - b) / 255
    return np.clip(a + (screen - a) * amount + 0.5, 0, 255).astype(np.uint8)


def _glow_ff(a, w, h, u):
    s = max(0.3, min(w, h) * 0.02)
    return (f"[in]split[{u}a][{u}b];[{u}b]gblur=sigma={s:.3f}[{u}g];"
            f"[{u}a][{u}g]blend=c0_mode=screen:c1_mode=screen:c2_mode=screen:c3_mode=normal"
            f":c0_opacity={a:.3f}:c1_opacity={a:.3f}:c2_opacity={a:.3f}:c3_opacity=0[out]")


def levels(amount):
    return max(3, int(round(16 - 13 * amount)))


def _poster_lut(amount):
    n = levels(amount)
    v = np.arange(256)
    return (np.floor(v * n / 256) * 255 / (n - 1) + 0.5).astype(np.uint8)


def posterize(bgr, amount):
    import cv2
    return cv2.LUT(bgr, _poster_lut(amount))


def _poster_ff(a, w, h, u):
    n = levels(a)
    e = f"floor(val*{n}/256)*255/{n - 1}+0.5"
    return f"lutrgb=r='{e}':g='{e}':b='{e}'"


EMBOSS = np.array([[-2, -1, 0], [-1, 1, 1], [0, 1, 2]], np.float32)


def _emboss_kernel(amount):
    ident = np.zeros((3, 3), np.float32)
    ident[1, 1] = 1
    return np.round((ident + amount * (EMBOSS - ident)) * 10)


def emboss(bgr, amount):
    import cv2
    return cv2.filter2D(bgr, -1, _emboss_kernel(amount) / 10.0, borderType=cv2.BORDER_REPLICATE)


def _emboss_ff(a, w, h, u):
    mat = " ".join(str(int(v)) for v in _emboss_kernel(a).flatten())
    return f"convolution=0m='{mat}':1m='{mat}':2m='{mat}':0rdiv=0.1:1rdiv=0.1:2rdiv=0.1"


def register(api):
    api.register_effect("sfx-blur", "Blur", preview=blur,
                        ffmpeg=lambda a, w, h, u: f"gblur=sigma={sigma(min(w, h), a):.3f}")
    api.register_effect("sfx-sharpen", "Sharpen", preview=sharpen, ffmpeg=_sharpen_ff)
    api.register_effect("sfx-glow", "Glow", preview=glow, ffmpeg=_glow_ff)
    api.register_effect("sfx-posterize", "Posterize", preview=posterize, ffmpeg=_poster_ff)
    api.register_effect("sfx-emboss", "Emboss", preview=emboss, ffmpeg=_emboss_ff)
