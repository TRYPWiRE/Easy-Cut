"""Updates updates/manifest.json with the installer just built (version, download URL, SHA-256).

Usage:  python tools/release.py release\\EasyCutSetup-0.1.0.exe ["release notes"]
"""
import hashlib
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from easycut import __version__  # noqa: E402
from easycut.config import REPO_URL  # noqa: E402

MANIFEST = os.path.join(ROOT, "updates", "manifest.json")


def load():
    try:
        with open(MANIFEST, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"app": {}, "extensions": []}


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    installer = sys.argv[1]
    notes = sys.argv[2] if len(sys.argv) > 2 else ""
    with open(installer, "rb") as f:
        sha = hashlib.sha256(f.read()).hexdigest()
    name = os.path.basename(installer)
    m = load()
    old = m.get("app") or {}
    if not notes and old.get("version") == __version__:
        notes = old.get("notes", "")
    m["app"] = {
        "version": __version__,
        "url": f"{REPO_URL}/releases/download/v{__version__}/{name}",
        "sha256": sha,
        "notes": notes,
    }
    os.makedirs(os.path.dirname(MANIFEST), exist_ok=True)
    with open(MANIFEST, "w", encoding="utf-8", newline="\n") as f:
        json.dump(m, f, indent=2)
        f.write("\n")
    print(f"manifest: app {__version__}  sha256 {sha[:16]}...")
    return 0


if __name__ == "__main__":
    sys.exit(main())
