"""Extensions: optional add-ons (more filters, animations and video effects) installed from GitHub.

Each extension is a folder in %APPDATA%\\Easy-Cut\\extensions\\<id>\\ holding:
    manifest.json   {"id", "name", "version", "description", "provides": ["filters", ...], "min_app"}
    main.py         defines register(api)

`api` exposes register_filter / register_animation / register_effect, so an extension adds items to the
same lists the built-ins live in - they appear in the Filters, Animations and Effects panels automatically.
"""
import importlib.util
import io
import json
import os
import shutil
import sys
import traceback
import zipfile

from . import __version__, animations, filters, textrender
from .config import cache_dir, data_path


def ext_dir():
    return cache_dir("extensions")


def state_file():
    return data_path("extensions.json")


def _state():
    try:
        with open(state_file(), "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"disabled": []}


def _save_state(s):
    with open(state_file(), "w", encoding="utf-8") as f:
        json.dump(s, f, indent=2)


def version_tuple(v):
    out = []
    for part in str(v).split("."):
        num = "".join(ch for ch in part if ch.isdigit())
        out.append(int(num) if num else 0)
    while len(out) < 3:
        out.append(0)
    return tuple(out)


class API:
    """What an extension's register(api) receives."""
    app_version = __version__
    Filter = filters.Filter
    Animation = animations.Motion

    def __init__(self, ext_id, folder=""):
        self.ext_id = ext_id
        self.folder = folder          # the extension's own folder (for bundled files like fonts)

    def path(self, *parts):
        return os.path.join(self.folder, *parts)

    def register_filter(self, fid, name, matrix=None, contrast=1.0, brightness=0.0, lift=0.0, ffmpeg=None,
                        preview=None, swatch=None):
        """A colour filter: 3x3 RGB matrix + tone settings (or an FFmpeg chain + numpy preview)."""
        return filters.register(filters.Filter(fid, name, matrix, contrast, brightness, lift, swatch, ffmpeg,
                                               preview, source=self.ext_id))

    def register_animation(self, aid, name, scale="1", dx="0", dy="0", fade=False, rot="0", reveal=None,
                           steps=0, kinds=("in", "out")):
        """An in/out animation - expressions in E (eased) and P (linear) progress. See animations.py."""
        return animations.register(animations.Motion(aid, name, scale, dx, dy, rot, fade, reveal, steps, kinds,
                                                     source=self.ext_id))

    def register_transition(self, tid, name, scale="1", dx="0", dy="0", rot="0", alpha="fade", veil=None,
                            reveal=None, steps=0):
        """A transition drawn on the incoming clip over the end of the outgoing one."""
        return animations.register_transition(animations.Transition(tid, name, scale, dx, dy, rot, alpha, veil,
                                                                    reveal, steps, source=self.ext_id))

    def register_effect(self, eid, name, ffmpeg, preview=None, swatch=None):
        """A video effect: an FFmpeg filter chain (may use {amount}) plus an optional preview function."""
        return filters.register_effect(filters.Filter(eid, name, ffmpeg=ffmpeg, preview=preview, swatch=swatch,
                                                      source=self.ext_id))

    def register_text_style(self, sid, name, paint, pad=0.0, swatch=None):
        """A text style: paint(painter, ctx) draws ctx.path (the letters) however it likes."""
        return textrender.register_style(textrender.TextStyle(sid, name, paint, pad, self.ext_id, swatch))

    def register_font(self, fid, name, filename):
        """Load a font file bundled with the extension (path relative to the extension folder)."""
        return textrender.register_font(fid, name, self.path(filename), self.ext_id)


class Installed:
    def __init__(self, folder, manifest):
        self.folder = folder
        self.manifest = manifest
        self.id = manifest.get("id") or os.path.basename(folder)
        self.name = manifest.get("name", self.id)
        self.version = manifest.get("version", "0.0.0")
        self.description = manifest.get("description", "")
        self.provides = manifest.get("provides", [])
        self.category = manifest.get("category", "")
        self.items = manifest.get("items", [])
        self.loaded = False
        self.error = ""


loaded = {}


def installed() -> dict:
    out = {}
    base = ext_dir()
    for name in sorted(os.listdir(base)):
        folder = os.path.join(base, name)
        mf = os.path.join(folder, "manifest.json")
        if name.startswith((".", "_")) or not os.path.isfile(mf):
            continue
        try:
            with open(mf, "r", encoding="utf-8") as f:
                out[name] = Installed(folder, json.load(f))
        except (OSError, ValueError):
            continue
    return out


def is_disabled(ext_id):
    return ext_id in _state().get("disabled", [])


def set_disabled(ext_id, disabled):
    s = _state()
    dis = set(s.get("disabled", []))
    if disabled:
        dis.add(ext_id)
    else:
        dis.discard(ext_id)
    s["disabled"] = sorted(dis)
    _save_state(s)


def load_one(ext: Installed):
    if ext.id in loaded:
        return loaded[ext.id]
    if version_tuple(ext.manifest.get("min_app", "0")) > version_tuple(__version__):
        ext.error = f"Needs Easy-Cut {ext.manifest.get('min_app')} or newer"
        return ext
    main = os.path.join(ext.folder, "main.py")
    try:
        spec = importlib.util.spec_from_file_location(f"easycut_ext_{ext.id.replace('-', '_')}", main)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        mod.register(API(ext.id, ext.folder))
        ext.loaded = True
    except Exception:
        ext.error = traceback.format_exc(limit=3)
    loaded[ext.id] = ext
    return ext


def load_all():
    apply_pending()
    for ext in installed().values():
        if not is_disabled(ext.id):
            load_one(ext)
    return loaded


# ---------------------------------------------------------------------- install / remove
def _pending_dir():
    return cache_dir("extensions_pending")


def install_zip(data: bytes, live=True):
    """Install an extension from zip bytes. Returns (Installed, needs_restart)."""
    zf = zipfile.ZipFile(io.BytesIO(data))
    names = zf.namelist()
    mf_name = next((n for n in names if n.endswith("manifest.json") and n.count("/") <= 1), None)
    if not mf_name:
        raise ValueError("This zip has no manifest.json, so it isn't an Easy-Cut extension.")
    manifest = json.loads(zf.read(mf_name).decode("utf-8"))
    ext_id = manifest.get("id")
    if not ext_id or any(ch in ext_id for ch in "/\\:. ") :
        raise ValueError("The extension's manifest has no valid id.")
    prefix = mf_name[: -len("manifest.json")]
    target_root = ext_dir()
    already = ext_id in loaded or os.path.isdir(os.path.join(target_root, ext_id))
    needs_restart = already and ext_id in loaded
    dest = os.path.join(_pending_dir() if needs_restart else target_root, ext_id)
    if os.path.isdir(dest):
        shutil.rmtree(dest, ignore_errors=True)
    os.makedirs(dest, exist_ok=True)
    for n in names:
        if not n.startswith(prefix) or n.endswith("/"):
            continue
        rel = n[len(prefix):]
        if ".." in rel.replace("\\", "/").split("/"):
            continue
        out = os.path.join(dest, rel)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "wb") as f:
            f.write(zf.read(n))
    ext = Installed(dest, manifest)
    if not needs_restart and live:
        load_one(ext)
    return ext, needs_restart


def apply_pending():
    """Finish installs/removals that had to wait for a restart (updates first, removals last)."""
    pend = _pending_dir()
    names = sorted(os.listdir(pend), key=lambda n: n.endswith(".remove"))
    for name in names:
        src = os.path.join(pend, name)
        if name.endswith(".remove"):
            shutil.rmtree(os.path.join(ext_dir(), name[:-7]), ignore_errors=True)
            shutil.rmtree(src, ignore_errors=True)
            continue
        dst = os.path.join(ext_dir(), name)
        shutil.rmtree(dst, ignore_errors=True)
        shutil.move(src, dst)


def uninstall(ext_id):
    """Remove an extension. Returns True when a restart is needed to finish."""
    folder = os.path.join(ext_dir(), ext_id)
    shutil.rmtree(os.path.join(_pending_dir(), ext_id), ignore_errors=True)   # drop any pending update
    if ext_id in loaded:
        os.makedirs(os.path.join(_pending_dir(), ext_id + ".remove"), exist_ok=True)
        return True
    shutil.rmtree(folder, ignore_errors=True)
    return False
