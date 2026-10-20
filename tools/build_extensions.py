"""Packages extensions/<id>/ folders into updates/extensions/<id>-<version>.zip and lists them in the manifest.

Usage:  python tools/build_extensions.py            (every extension)
        python tools/build_extensions.py my-ext     (just these ids)
Folders starting with "_" (like _template) are skipped.
Zips are built byte-for-byte reproducibly, and the SHA-256 in the manifest is taken from the zip that gets
committed, so the app's checksum check always matches what GitHub serves.
"""
import hashlib
import json
import os
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from easycut.config import RAW_BASE  # noqa: E402

SRC = os.path.join(ROOT, "extensions")
OUT = os.path.join(ROOT, "updates", "extensions")
MANIFEST = os.path.join(ROOT, "updates", "manifest.json")


def build_zip(folder, ext_id, dest):
    files = []
    for base, dirs, names in os.walk(folder):
        dirs[:] = sorted(d for d in dirs if d != "__pycache__")
        for n in sorted(names):
            if n.endswith((".pyc", ".pyo")):
                continue
            full = os.path.join(base, n)
            files.append((full, ext_id + "/" + os.path.relpath(full, folder).replace("\\", "/")))
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for full, arc in files:
            info = zipfile.ZipInfo(arc, date_time=(2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            with open(full, "rb") as f:
                data = f.read().replace(b"\r\n", b"\n") if arc.endswith((".py", ".json", ".md", ".txt")) else f.read()
            z.writestr(info, data)


def main():
    wanted = set(sys.argv[1:])
    os.makedirs(OUT, exist_ok=True)
    try:
        with open(MANIFEST, "r", encoding="utf-8") as f:
            manifest = json.load(f)
    except (OSError, ValueError):
        manifest = {"app": {}, "extensions": []}
    entries = {e["id"]: e for e in manifest.get("extensions", [])}
    if not os.path.isdir(SRC):
        print("No extensions folder.")
        return 0
    for name in sorted(os.listdir(SRC)):
        folder = os.path.join(SRC, name)
        mf = os.path.join(folder, "manifest.json")
        if name.startswith((".", "_")) or not os.path.isfile(mf):
            continue
        if wanted and name not in wanted:
            continue
        with open(mf, "r", encoding="utf-8") as f:
            meta = json.load(f)
        ext_id = meta["id"]
        ver = meta.get("version", "0.0.1")
        zname = f"{ext_id}-{ver}.zip"
        dest = os.path.join(OUT, zname)
        build_zip(folder, ext_id, dest)
        with open(dest, "rb") as f:
            sha = hashlib.sha256(f.read()).hexdigest()
        entries[ext_id] = {
            "id": ext_id, "name": meta.get("name", ext_id), "version": ver,
            "description": meta.get("description", ""), "provides": meta.get("provides", []),
            "category": meta.get("category", ""), "items": meta.get("items", []), "size": os.path.getsize(dest),
            "min_app": meta.get("min_app", "0.1.0"),
            "url": f"{RAW_BASE}/updates/extensions/{zname}", "sha256": sha,
        }
        # remove older zips of this extension
        for old in os.listdir(OUT):
            if old.startswith(ext_id + "-") and old != zname:
                os.remove(os.path.join(OUT, old))
        print(f"extension {ext_id} {ver}  sha256 {sha[:16]}...")
    manifest["extensions"] = sorted(entries.values(), key=lambda e: e["id"])
    with open(MANIFEST, "w", encoding="utf-8", newline="\n") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
