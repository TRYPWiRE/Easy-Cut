"""Motion engine: clip animations (in / out) and transitions.

Every motion is written once as small expressions. The same text is evaluated by Python for the preview and
handed to FFmpeg (per-frame scale / rotate / overlay / geq expressions) for the export, so both always agree.

Expression variables
    E   eased progress 0..1  (0 = hidden state, 1 = normal state)
    P   linear progress 0..1
    PI, sin, cos, pow, abs, exp, floor, max, min are available.

Motion fields
    scale   multiplier on the clip's size
    dx, dy  offset as a fraction of the canvas width / height
    rot     rotation in degrees (added to the clip's own rotation)
    fade    True: opacity follows P
    reveal  None | "left" | "right" | "up" | "down" - wipe the clip in from that edge
    steps   0 = smooth reveal, N = reveal in N jumps, "chars" = one jump per character (typewriter)

An in-animation runs over the start of the clip, an out-animation over its end (progress runs 1 -> 0), so one
definition serves both directions.

A transition runs on the incoming clip, *before* its start, over the end of the previous clip: the clip is
drawn early (its "pre-roll") on top of the outgoing clip. Transitions add:
    alpha   "fade" (dissolve), "half" (appears at the midpoint) or "none"
    veil    None or "#rrggbb" - a full-screen colour that rises then falls (dip / flash)
"""
import math
import re


class Motion:
    def __init__(self, mid, name, scale="1", dx="0", dy="0", rot="0", fade=False, reveal=None, steps=0,
                 kinds=("in", "out"), source="built-in", icon="", alpha=None, veil=None):
        self.id = mid
        self.name = name
        self.scale = str(scale)
        self.dx = str(dx)
        self.dy = str(dy)
        self.rot = str(rot)
        self.fade = bool(fade)
        self.reveal = reveal
        self.steps = steps
        self.kinds = kinds
        self.source = source
        self.icon = icon
        self.alpha = alpha            # transitions only
        self.veil = veil              # transitions only

    @property
    def has_scale(self):
        return self.scale.strip() != "1"

    @property
    def has_rot(self):
        return self.rot.strip() != "0"


Animation = Motion            # kept for older extensions


class Transition(Motion):
    def __init__(self, tid, name, scale="1", dx="0", dy="0", rot="0", alpha="fade", veil=None, reveal=None,
                 steps=0, source="built-in", icon=""):
        super().__init__(tid, name, scale, dx, dy, rot, fade=False, reveal=reveal, steps=steps, kinds=("trans",),
                         source=source, icon=icon, alpha=alpha, veil=veil)


ANIMATIONS = {}
ORDER = []
TRANSITIONS = {}
TRANSITION_ORDER = []


def register(a: Motion):
    if a.id not in ANIMATIONS:
        ORDER.append(a.id)
    ANIMATIONS[a.id] = a
    return a


def register_transition(t: Transition):
    if t.id not in TRANSITIONS:
        TRANSITION_ORDER.append(t.id)
    TRANSITIONS[t.id] = t
    return t


register(Motion("none", "None"))
register(Motion("fade", "Fade", fade=True, icon="fade"))
register(Motion("zoom", "Zoom", scale="(0.55+0.45*E)", fade=True, icon="zoom"))
register(Motion("pop", "Pop", scale="max(0.05,E*(1+0.25*sin(PI*E)))", icon="pop"))
register(Motion("slide_left", "Slide Left", dx="(-(1-E))", icon="left"))
register(Motion("slide_right", "Slide Right", dx="(1-E)", icon="right"))
register(Motion("slide_up", "Slide Up", dy="(1-E)", icon="up"))
register(Motion("drop", "Drop", dy="(-(1-E)*0.35)", fade=True, icon="down"))

register_transition(Transition("none", "None", alpha="none"))
register_transition(Transition("dissolve", "Cross Dissolve", alpha="fade"))
register_transition(Transition("dip_black", "Dip to Black", alpha="half", veil="#000000"))
register_transition(Transition("slide", "Slide", dx="(1-E)", alpha="none"))


def get(aid) -> Motion:
    return ANIMATIONS.get(aid) or ANIMATIONS["none"]


def get_transition(tid) -> Transition:
    return TRANSITIONS.get(tid) or TRANSITIONS["none"]


# ====================================================================== expression helpers
EASE_PY = lambda p: 1 - (1 - p) ** 3          # noqa: E731
_E = re.compile(r"\bE\b")
_P = re.compile(r"\bP\b")


def _clip(x, a, b):
    return max(a, min(b, x))


_env = {"sin": math.sin, "cos": math.cos, "PI": math.pi, "max": max, "min": min, "pow": pow, "abs": abs,
        "exp": math.exp, "floor": math.floor, "clip": _clip, "__builtins__": {}}


def _eval(expr, e, p, default=1.0):
    try:
        return float(eval(expr, dict(_env, E=e, P=p)))   # expressions are app/extension-defined, not user input
    except Exception:
        return default


def _ff(expr, e_ff, p_ff):
    return _P.sub("(" + p_ff + ")", _E.sub("(" + e_ff + ")", expr))


def step_count(m, clip):
    s = m.steps
    if s == "chars":
        txt = (clip.get("text") or "").replace("\n", "")
        return max(1, len(txt))
    try:
        return max(0, int(s))
    except (TypeError, ValueError):
        return 0


def pre_roll(clip) -> float:
    """Seconds the clip is drawn before its start because of its transition."""
    if clip.get("trans_in", "none") in (None, "", "none"):
        return 0.0
    pre = min(float(clip.get("trans_dur", 0.5)), float(clip.get("start", 0.0)))
    return pre if pre >= 0.04 else 0.0


def windows(clip):
    """Active motions of a clip: [(motion, kind, window_start, window_duration)].

    A transition replaces the in-animation (they would fight over the same moment)."""
    out = []
    start = float(clip["start"])
    end = start + float(clip["duration"])
    pre = pre_roll(clip)
    if pre > 0:
        out.append((get_transition(clip.get("trans_in")), "trans", start - pre, pre))
    elif clip.get("anim_in", "none") != "none":
        d = min(max(0.01, float(clip.get("anim_in_dur", 0.5))), max(0.01, end - start))
        out.append((get(clip["anim_in"]), "in", start, d))
    if clip.get("anim_out", "none") != "none":
        d = min(max(0.01, float(clip.get("anim_out_dur", 0.5))), max(0.01, end - start))
        out.append((get(clip["anim_out"]), "out", end - d, d))
    return out


def _progress(kind, a, d, t):
    if kind == "out":
        return _clip((a + d - t) / d, 0.0, 1.0)
    return _clip((t - a) / d, 0.0, 1.0)


def _p_ff(kind, a, d, tvar="t"):
    if kind == "out":
        return f"clip(({a + d:.4f}-{tvar})/{d:.4f},0,1)"
    return f"clip(({tvar}-{a:.4f})/{d:.4f},0,1)"


def reveal_amount(m, clip, p):
    n = step_count(m, clip)
    if n:
        return math.floor(p * n + 1e-6) / n
    return EASE_PY(p)


# ====================================================================== preview
def state(clip, t):
    """Preview state at timeline time t: dict(alpha, scale, dx, dy, rot, reveals=[(dir, amount)], veil)."""
    st = {"alpha": 1.0, "scale": 1.0, "dx": 0.0, "dy": 0.0, "rot": 0.0, "reveals": [], "veil": None}
    for m, kind, a, d in windows(clip):
        if m.id == "none":
            continue
        p = _progress(kind, a, d, t)
        e = EASE_PY(p)
        st["scale"] *= _eval(m.scale, e, p)
        st["dx"] += _eval(m.dx, e, p, 0.0)
        st["dy"] += _eval(m.dy, e, p, 0.0)
        st["rot"] += _eval(m.rot, e, p, 0.0)
        if m.reveal:
            st["reveals"].append((m.reveal, reveal_amount(m, clip, p)))
        if kind == "trans":
            if m.alpha == "fade":
                st["alpha"] *= p
            elif m.alpha == "half" and p < 0.5:
                st["alpha"] = 0.0
            if m.veil and a <= t <= a + d:
                st["veil"] = (m.veil, 1 - abs(2 * p - 1))
        elif m.fade:
            st["alpha"] *= p
    st["scale"] = max(0.0, st["scale"])
    return st


def reveal_mask(h, w, reveals):
    """Float mask (h, w) that is 1 where the clip is visible, or None when nothing is hidden."""
    import numpy as np
    if not reveals:
        return None
    mask = np.ones((h, w), np.float32)
    for direction, r in reveals:
        if r >= 0.9999:
            continue
        if direction == "left":
            mask[:, int(round(w * r)):] = 0
        elif direction == "right":
            mask[:, :int(round(w * (1 - r)))] = 0
        elif direction == "up":
            mask[:int(round(h * (1 - r))), :] = 0
        elif direction == "down":
            mask[int(round(h * r)):, :] = 0
    return mask


# ====================================================================== export
EASE_FF = "(1-pow(1-({p}),3))"


def max_scale(clip):
    """Largest size multiplier the clip's motions reach (sampled) - used to size FFmpeg's rotation box."""
    total = 1.0
    for m, kind, a, d in windows(clip):
        if not m.has_scale:
            continue
        best = 1.0
        for i in range(101):
            p = i / 100
            best = max(best, _eval(m.scale, EASE_PY(p), p))
        total *= best
    return total


def ffmpeg_exprs(clip, tvar="t"):
    """FFmpeg expressions in terms of timeline time: dict(scale, dx, dy, rot) - each None when constant."""
    terms = {"scale": [], "dx": [], "dy": [], "rot": []}
    for m, kind, a, d in windows(clip):
        if m.id == "none":
            continue
        p = _p_ff(kind, a, d, tvar)
        e = EASE_FF.format(p=p)
        if m.has_scale:
            terms["scale"].append("(" + _ff(m.scale, e, p) + ")")
        if m.dx.strip() != "0":
            terms["dx"].append("(" + _ff(m.dx, e, p) + ")")
        if m.dy.strip() != "0":
            terms["dy"].append("(" + _ff(m.dy, e, p) + ")")
        if m.has_rot:
            terms["rot"].append("(" + _ff(m.rot, e, p) + ")")
    return {
        "scale": "*".join(terms["scale"]) or None,
        "dx": "+".join(terms["dx"]) or None,
        "dy": "+".join(terms["dy"]) or None,
        "rot": "+".join(terms["rot"]) or None,
    }


def reveal_ffmpeg(clip):
    """geq filters that wipe the clip in/out ([] when it has no reveal motions)."""
    out = []
    for m, kind, a, d in windows(clip):
        if not m.reveal:
            continue
        p = _p_ff(kind, a, d, "T")
        n = step_count(m, clip)
        r = f"(floor(({p})*{n}+0.000001)/{n})" if n else EASE_FF.format(p=p)
        cond = {"left": f"lt(X,W*{r})", "right": f"gte(X,W*(1-{r}))",
                "up": f"gte(Y,H*(1-{r}))", "down": f"lt(Y,H*{r})"}[m.reveal]
        expr = f"alpha(X,Y)*{cond}"
        out.append(f"geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='{expr}'"
                   f":enable='between(t,{a:.4f},{a + d:.4f})'")
    return out


def fades(clip):
    """[(type, start, duration)] linear alpha fades for FFmpeg's fade filter (animations + dissolves)."""
    out = []
    for m, kind, a, d in windows(clip):
        if kind == "trans":
            if m.alpha == "fade":
                out.append(("in", a, d))
        elif m.fade:
            out.append(("in" if kind == "in" else "out", a, d))
    return out


def audio_fades(clip):
    """Fades that also apply to the clip's sound (animations only - transitions leave audio alone)."""
    return [(("in" if kind == "in" else "out"), a, d) for m, kind, a, d in windows(clip)
            if kind != "trans" and m.fade]


def visible_from(clip):
    """Timeline time the clip first appears (pre-roll, and 'half' transitions appear at the midpoint)."""
    pre = pre_roll(clip)
    if pre <= 0:
        return float(clip["start"])
    t = get_transition(clip.get("trans_in"))
    if t.alpha == "half":
        return float(clip["start"]) - pre / 2
    return float(clip["start"]) - pre


def veil(clip):
    """(colour, start, duration) of a transition's colour veil, or None."""
    pre = pre_roll(clip)
    if pre <= 0:
        return None
    t = get_transition(clip.get("trans_in"))
    if not t.veil:
        return None
    return t.veil, float(clip["start"]) - pre, pre
