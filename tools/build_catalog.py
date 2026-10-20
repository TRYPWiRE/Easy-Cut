"""Builds the catalog that ships with the app: assets/catalog/catalog.json + a thumbnail for every pack item.

Run after adding or changing packs in extensions/ (build.bat runs it for you):
    python tools/build_catalog.py

It loads every pack, checks that each one registers exactly the items its manifest lists, and renders each
item's preview with the same code the app uses - so locked items look exactly like the real thing.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if sys.platform == "win32":
    # the hidden Qt platform has no fonts of its own on Windows
    os.environ.setdefault("QT_QPA_FONTDIR", os.path.join(os.environ.get("WINDIR", r"C:\\Windows"), "Fonts"))
os.environ.setdefault("EASYCUT_DATA_DIR", os.path.join(ROOT, "build", "catalog_appdata"))

from PyQt6.QtGui import QGuiApplication  # noqa: E402

app = QGuiApplication(sys.argv)

from PyQt6.QtGui import QFontDatabase  # noqa: E402
from easycut import animations, extensions, filters, textrender, thumbs  # noqa: E402
from build_extensions import build_zip  # noqa: E402

SRC = os.path.join(ROOT, "extensions")
OUT = os.path.join(ROOT, "assets", "catalog")
TYPES = {
    "filter": lambda: set(filters.FILTERS),
    "effect": lambda: set(filters.EFFECTS),
    "transition": lambda: set(animations.TRANSITIONS),
    "animation": lambda: set(animations.ANIMATIONS),
    "text_style": lambda: set(textrender.STYLES),
    "font": lambda: set(textrender.FONTS),
}


def snapshot():
    return {k: f() for k, f in TYPES.items()}


def main():
    import cv2
    if not QFontDatabase.families():
        sys.exit("No fonts found, so the catalog wasn't rebuilt.")
    os.makedirs(os.path.join(OUT, "thumbs"), exist_ok=True)
    for old in os.listdir(os.path.join(OUT, "thumbs")):
        os.remove(os.path.join(OUT, "thumbs", old))
    packs = []
    problems = []
    for name in sorted(os.listdir(SRC)):
        folder = os.path.join(SRC, name)
        mf = os.path.join(folder, "manifest.json")
        if name.startswith((".", "_")) or not os.path.isfile(mf):
            continue
        with open(mf, "r", encoding="utf-8") as f:
            meta = json.load(f)
        before = snapshot()
        ext = extensions.Installed(folder, meta)
        extensions.load_one(ext)
        if ext.error:
            problems.append(f"{name}: failed to load\n{ext.error}")
            continue
        after = snapshot()
        added = {(k, i) for k in TYPES for i in after[k] - before[k]}
        listed = {(it["type"], it["id"]) for it in meta.get("items", [])}
        if added != listed:
            problems.append(f"{name}: manifest items {sorted(listed - added)} not registered, "
                            f"registered but not listed {sorted(added - listed)}")
        tmp = os.path.join(OUT, "_size.zip")
        build_zip(folder, meta["id"], tmp)
        size = os.path.getsize(tmp)
        os.remove(tmp)
        packs.append({"id": meta["id"], "name": meta.get("name", meta["id"]), "version": meta.get("version", ""),
                      "category": meta.get("category", ""), "description": meta.get("description", ""),
                      "min_app": meta.get("min_app", ""), "size": size, "items": meta.get("items", [])})
        for it in meta.get("items", []):
            img = thumbs.make(it["type"], it["id"])
            if img is None:
                problems.append(f"{name}: no thumbnail for {it['type']} {it['id']}")
                continue
            ok, data = cv2.imencode(".png", img)
            data.tofile(os.path.join(OUT, "thumbs", f"{it['type']}-{it['id']}.png"))
    order = {c: i for i, c in enumerate(["Filters", "Transitions", "Animations", "Effects", "Text", "Fonts"])}
    packs.sort(key=lambda p: (order.get(p["category"], 99), p["name"]))
    with open(os.path.join(OUT, "catalog.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump({"packs": packs}, f, indent=2)
        f.write("\n")
    n = sum(len(p["items"]) for p in packs)
    print(f"catalog: {len(packs)} packs, {n} items")
    if problems:
        print("\n".join(problems))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
