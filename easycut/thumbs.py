"""Preview thumbnails for every kind of library item (filters, transitions, animations, effects, text styles,
fonts). The app draws them live for installed items; tools/build_catalog.py uses the same code to bake the
thumbnails that locked (not yet downloaded) items show."""
import os

import numpy as np

TW, TH = 224, 140          # thumbnail size (shown at half size, so they stay sharp on high-DPI screens)


def scene_a(w=TW, h=TH):
    """Sunset landscape (BGR)."""
    y = np.linspace(0, 1, h)[:, None]
    x = np.linspace(0, 1, w)[None, :]
    img = np.zeros((h, w, 3), np.float32)
    img[:] = np.array([235, 120, 60]) * (1 - y[..., None]) + np.array([120, 170, 255]) * y[..., None]
    sun = ((x - 0.68) ** 2 + ((y - 0.55) * h / w) ** 2) < 0.012
    img[sun] = (120, 230, 255)
    hill = np.broadcast_to(y > 0.62 + 0.08 * np.sin(x * 7), (h, w))
    img[hill] = (60, 130, 70)
    person = np.broadcast_to((np.abs(x - 0.3) < 0.07) & (y > 0.4) & (y < 0.8), (h, w))
    img[person] = (140, 170, 230)
    return img.clip(0, 255).astype(np.uint8)


def scene_b(w=TW, h=TH):
    """Night city (BGR) - the 'incoming' clip in transition previews."""
    y = np.linspace(0, 1, h)[:, None]
    x = np.linspace(0, 1, w)[None, :]
    img = np.zeros((h, w, 3), np.float32)
    img[:] = np.array([90, 30, 40]) * (1 - y[..., None]) + np.array([170, 60, 120]) * y[..., None]
    rng = np.random.default_rng(7)
    for i in range(9):
        bx = i / 9
        bw = 0.08 + rng.random() * 0.03
        top = 0.35 + rng.random() * 0.35
        mask = np.broadcast_to((x > bx) & (x < bx + bw) & (y > top), (h, w))
        img[mask] = (50 + 20 * (i % 3), 30, 40 + 10 * i)
    moon = ((x - 0.2) ** 2 + ((y - 0.22) * h / w) ** 2) < 0.004
    img[np.broadcast_to(moon, (h, w))] = (210, 240, 255)
    return img.clip(0, 255).astype(np.uint8)


_files = {}


def _scene_file(name):
    """Scenes saved as PNGs once (the compositor reads clips from files)."""
    import cv2
    from .config import cache_dir
    p = _files.get(name)
    if p and os.path.exists(p):
        return p
    p = os.path.join(cache_dir("thumbs"), f"scene_{name}.png")
    img = scene_a(640, 400) if name == "a" else scene_b(640, 400)
    ok, buf = cv2.imencode(".png", img)
    buf.tofile(p)
    _files[name] = p
    return p


def _image_clip(path, **kw):
    from .project import Clip
    c = Clip(kind="image", path=path, name=os.path.basename(path), src_w=640, src_h=400, has_video=True,
             fit="fill")
    c.update(kw)
    return c


def _compose(project, t, w=TW, h=TH):
    from .compositor import Compositor
    comp = Compositor()
    try:
        return comp.compose(project, t, w, h)
    finally:
        comp.close()


def _thumb_project():
    from .project import Project
    p = Project()
    p.aspect = "classic"
    p.background = "#15151b"
    return p


def filter_thumb(fid):
    from . import filters
    return filters.apply_preview(scene_a(), {"filter": fid, "filter_amount": 1.0})


def effect_thumb(eid):
    from . import filters
    return filters.apply_preview(scene_a(), {"fx": [{"id": eid, "amount": 1.0}]})


def transition_thumb(tid):
    """The middle of the transition from scene A to scene B."""
    p = _thumb_project()
    a = _image_clip(_scene_file("a"), start=0.0, duration=2.0)
    b = _image_clip(_scene_file("b"), start=2.0, duration=2.0, trans_in=tid, trans_dur=1.0)
    p.clips = [a, b]
    for c in p.clips:
        c["track"] = 1
    return _compose(p, 1.3)


def animation_thumb(aid):
    """A moment part-way through the animation, with a faint 'ghost' of where the clip ends up."""
    from . import animations
    p = _thumb_project()
    c = _image_clip(_scene_file("a"), start=0.0, duration=3.0, anim_in=aid, anim_in_dur=1.0, fit="fit", scale=0.6)
    m = animations.get(aid)
    if m.reveal and m.steps == "chars":
        from .project import Clip
        c = Clip(kind="text", text="Hello", font_size=260, duration=3.0, anim_in=aid, anim_in_dur=1.0)
    c["track"] = 1
    p.clips = [c]
    ghost = _compose(p, 2.0).astype(np.float32)
    frame = _compose(p, 0.45).astype(np.float32)
    bg = np.array((0x1b, 0x15, 0x15), np.float32)
    out = frame * 0.85 + (ghost - bg) * 0.18 + bg * 0.15
    return out.clip(0, 255).astype(np.uint8)


def style_thumb(sid, text="Aa", font=None, color="#ff4f7b"):
    from . import textrender
    from .project import Clip
    c = Clip(kind="text", text=text, font_size=150, text_style=sid, text_color=color, font=font or "Segoe UI")
    img = textrender.render(c, 1.0)
    return _on_dark(img)


def font_thumb(fid):
    from . import textrender
    from .project import Clip
    f = textrender.FONTS.get(fid)
    fam = f["family"] if f else "Segoe UI"
    c = Clip(kind="text", text="Abc", font_size=150, font=fam, text_color="#ffffff", bold=False,
             text_outline=False)
    return _on_dark(textrender.render(c, 1.0))


def _on_dark(bgra):
    import cv2
    out = np.empty((TH, TW, 3), np.uint8)
    out[:] = (0x1b, 0x15, 0x15)
    h, w = bgra.shape[:2]
    s = min((TW - 16) / w, (TH - 16) / h, 1.0)
    img = cv2.resize(bgra, (max(1, int(w * s)), max(1, int(h * s))), interpolation=cv2.INTER_AREA)
    from .compositor import blend_onto
    blend_onto(out, img, TW / 2, TH / 2, 1.0)
    return out


MAKERS = {"filter": filter_thumb, "effect": effect_thumb, "transition": transition_thumb,
          "animation": animation_thumb, "text_style": style_thumb, "font": font_thumb}


def make(kind, item_id):
    """BGR thumbnail for an item, or None."""
    fn = MAKERS.get(kind)
    if fn is None:
        return None
    try:
        return fn(item_id)
    except Exception:
        return None
