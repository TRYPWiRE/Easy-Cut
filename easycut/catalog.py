"""Catalog of downloadable packs and the items inside them.

A copy ships with the app (assets/catalog/catalog.json + baked thumbnails), so every pack's items show in the
browsers straight away - greyed out until the pack is downloaded. When the online update manifest arrives, its
entries are merged in, so packs released later appear without an app update.
"""
import json
import os

from .config import asset

CATEGORIES = ["Filters", "Transitions", "Animations", "Effects", "Text", "Fonts"]

_packs = None          # id -> pack dict (catalog order kept in _order)
_order = []
_index = {}            # (type, item id) -> pack id


def _load_bundled():
    global _packs, _order
    _packs, _order = {}, []
    try:
        with open(asset("catalog", "catalog.json"), "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    for p in data.get("packs", []):
        _add(p)


def _add(p):
    if not p.get("id"):
        return
    if p["id"] not in _packs:
        _order.append(p["id"])
        _packs[p["id"]] = dict(p)
    else:
        _packs[p["id"]].update({k: v for k, v in p.items() if v not in (None, "", [])})
    for it in _packs[p["id"]].get("items", []):
        _index[(it.get("type"), it.get("id"))] = p["id"]


def _ensure():
    if _packs is None:
        _load_bundled()


def merge_manifest(entries):
    """Merge the online manifest's extension entries (adds url/sha/version and any new packs)."""
    _ensure()
    for e in entries or []:
        if e.get("items") or e["id"] in _packs:
            _add(e)


def packs(category=None):
    _ensure()
    out = [_packs[i] for i in _order]
    if category and category != "All":
        out = [p for p in out if p.get("category") == category]
    return out


def pack(pack_id):
    _ensure()
    return _packs.get(pack_id)


def pack_for(kind, item_id):
    """The pack that contains an item, or None."""
    _ensure()
    pid = _index.get((kind, item_id))
    return _packs.get(pid) if pid else None


def items(kind):
    """[(item id, name, pack)] of one type, in catalog order."""
    _ensure()
    out = []
    for pid in _order:
        p = _packs[pid]
        for it in p.get("items", []):
            if it.get("type") == kind:
                out.append((it["id"], it.get("name", it["id"]), p))
    return out


def thumb_path(kind, item_id):
    p = asset("catalog", "thumbs", f"{kind}-{item_id}.png")
    return p if os.path.exists(p) else None


def size_label(p):
    n = int(p.get("size") or 0)
    if n <= 0:
        return ""
    if n < 1024 * 1024:
        return f"{max(1, n // 1024)} KB"
    return f"{n / (1024 * 1024):.1f} MB"


def reset():
    """Forget everything (used by tests)."""
    global _packs
    _packs = None
    _order.clear()
    _index.clear()
