"""Clip animations (in / out).

An animation is written once as small expressions in terms of `E` (eased progress 0..1, where 0 is the
hidden state and 1 is the normal state). The same expression text is evaluated by Python for the preview
and handed to FFmpeg (scale / overlay `eval=frame` expressions) for the export.

* scale - multiplier on the clip's size
* dx/dy - offset as a fraction of the canvas width/height
* fade  - True to fade the clip's opacity with linear progress

For an in-animation progress runs 0 -> 1 over its duration at the start of the clip; for an
out-animation it runs 1 -> 0 over the end of the clip, so one definition serves both directions.
"""
import math


class Animation:
    def __init__(self, aid, name, scale="1", dx="0", dy="0", fade=False, kinds=("in", "out"),
                 source="built-in", icon=""):
        self.id = aid
        self.name = name
        self.scale = scale
        self.dx = dx
        self.dy = dy
        self.fade = fade
        self.kinds = kinds
        self.source = source
        self.icon = icon


ANIMATIONS = {}
ORDER = []


def register(a: Animation):
    if a.id not in ANIMATIONS:
        ORDER.append(a.id)
    ANIMATIONS[a.id] = a
    return a


register(Animation("none", "None"))
register(Animation("fade", "Fade", fade=True, icon="fade"))
register(Animation("zoom", "Zoom", scale="(0.55+0.45*E)", fade=True, icon="zoom"))
register(Animation("pop", "Pop", scale="max(0.05,E*(1+0.25*sin(PI*E)))", icon="pop"))
register(Animation("slide_left", "Slide Left", dx="(-(1-E))", icon="left"))
register(Animation("slide_right", "Slide Right", dx="(1-E)", icon="right"))
register(Animation("slide_up", "Slide Up", dy="(1-E)", icon="up"))
register(Animation("drop", "Drop", dy="(-(1-E)*0.35)", fade=True, icon="down"))


def get(aid) -> Animation:
    return ANIMATIONS.get(aid) or ANIMATIONS["none"]


EASE_PY = lambda p: 1 - (1 - p) ** 3          # noqa: E731
EASE_FF = "(1-pow(1-({p}),3))"

_env = {"sin": math.sin, "cos": math.cos, "PI": math.pi, "max": max, "min": min, "pow": pow,
        "abs": abs, "exp": math.exp, "__builtins__": {}}


def _eval(expr, e):
    try:
        return float(eval(expr, dict(_env, E=e)))   # expressions are app-defined, never user input
    except Exception:
        return 1.0


def progress(clip, t):
    """(p_in, p_out) linear progress values at timeline time t (1 = fully shown)."""
    p_in = p_out = 1.0
    if clip.get("anim_in", "none") != "none":
        d = max(0.01, float(clip.get("anim_in_dur", 0.5)))
        p_in = min(1.0, max(0.0, (t - clip["start"]) / d))
    if clip.get("anim_out", "none") != "none":
        d = max(0.01, float(clip.get("anim_out_dur", 0.5)))
        p_out = min(1.0, max(0.0, (clip["start"] + clip["duration"] - t) / d))
    return p_in, p_out


def state(clip, t):
    """(alpha, scale, dx, dy) for the preview at timeline time t."""
    alpha, scale, dx, dy = 1.0, 1.0, 0.0, 0.0
    p_in, p_out = progress(clip, t)
    for aid, p in ((clip.get("anim_in", "none"), p_in), (clip.get("anim_out", "none"), p_out)):
        a = get(aid)
        if a.id == "none":
            continue
        e = EASE_PY(p)
        scale *= _eval(a.scale, e)
        dx += _eval(a.dx, e)
        dy += _eval(a.dy, e)
        if a.fade:
            alpha *= p
    return alpha, max(0.0, scale), dx, dy


def ffmpeg_exprs(clip):
    """FFmpeg expressions in terms of `t` (timeline time): dict(scale, dx, dy) - each None if constant."""
    start = float(clip["start"])
    end = start + float(clip["duration"])
    scale_terms, dx_terms, dy_terms = [], [], []
    for which in ("in", "out"):
        a = get(clip.get(f"anim_{which}", "none"))
        if a.id == "none":
            continue
        d = max(0.01, float(clip.get(f"anim_{which}_dur", 0.5)))
        p = f"clip((t-{start:.4f})/{d:.4f},0,1)" if which == "in" else f"clip(({end:.4f}-t)/{d:.4f},0,1)"
        e = EASE_FF.format(p=p)
        if a.scale.strip() != "1":
            scale_terms.append("(" + a.scale.replace("E", e) + ")")
        if a.dx.strip() != "0":
            dx_terms.append("(" + a.dx.replace("E", e) + ")")
        if a.dy.strip() != "0":
            dy_terms.append("(" + a.dy.replace("E", e) + ")")
    return {
        "scale": "*".join(scale_terms) if scale_terms else None,
        "dx": "+".join(dx_terms) if dx_terms else None,
        "dy": "+".join(dy_terms) if dy_terms else None,
    }


def fades(clip):
    """[(type, start, duration)] alpha fades for FFmpeg's fade filter."""
    out = []
    a_in, a_out = get(clip.get("anim_in", "none")), get(clip.get("anim_out", "none"))
    if a_in.fade:
        out.append(("in", float(clip["start"]), max(0.01, float(clip.get("anim_in_dur", 0.5)))))
    if a_out.fade:
        d = max(0.01, float(clip.get("anim_out_dur", 0.5)))
        out.append(("out", float(clip["start"]) + float(clip["duration"]) - d, d))
    return out
