"""Auto-updates for Easy-Cut and its extensions (same system as Lumen).

On every start the app reads updates/manifest.json from the GitHub repo in the background:
    {
      "app": {"version": "0.1.1", "url": ".../EasyCutSetup-0.1.1.exe", "sha256": "...", "notes": "..."},
      "extensions": [{"id", "name", "version", "description", "provides", "url", "sha256", "min_app"}]
    }
App updates download the installer, check its SHA-256, close Easy-Cut, upgrade silently and reopen it.
"""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import urllib.request

from . import __version__, extensions
from .config import MANIFEST_URL, is_frozen
from .extensions import version_tuple

USER_AGENT = f"Easy-Cut/{__version__}"


def _get(url, timeout=15) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def fetch_manifest(url=None) -> dict:
    data = json.loads(_get(url or MANIFEST_URL).decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Bad update manifest")
    return data


def newer(a, b) -> bool:
    return version_tuple(a) > version_tuple(b)


def check(manifest: dict) -> dict:
    """{"app": entry-or-None, "extensions": [entries with updates], "available": [not-installed entries]}"""
    out = {"app": None, "extensions": [], "available": []}
    app = manifest.get("app") or {}
    if app.get("version") and newer(app["version"], __version__):
        out["app"] = app
    inst = extensions.installed()
    for e in manifest.get("extensions", []) or []:
        if not e.get("id"):
            continue
        if version_tuple(e.get("min_app", "0")) > version_tuple(__version__):
            continue
        if e["id"] in inst:
            if newer(e.get("version", "0"), inst[e["id"]].version):
                out["extensions"].append(e)
        else:
            out["available"].append(e)
    return out


def download(url, sha256=None, progress=None) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as r:
        total = int(r.headers.get("Content-Length") or 0)
        chunks, got = [], 0
        while True:
            b = r.read(256 * 1024)
            if not b:
                break
            chunks.append(b)
            got += len(b)
            if progress and total:
                progress(got / total)
    data = b"".join(chunks)
    if sha256 and hashlib.sha256(data).hexdigest().lower() != sha256.lower():
        raise ValueError("The download didn't match its checksum, so it was not installed.")
    return data


def install_extension(entry, progress=None):
    data = download(entry["url"], entry.get("sha256"), progress)
    return extensions.install_zip(data)


def can_self_update() -> bool:
    return sys.platform == "win32" and is_frozen()


def run_installer(data: bytes, version: str):
    """Save the installer and launch it silently; the caller should then quit the app."""
    path = os.path.join(tempfile.gettempdir(), f"EasyCutSetup-{version}.exe")
    with open(path, "wb") as f:
        f.write(data)
    flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    subprocess.Popen([path, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/RELAUNCH=1"],
                     creationflags=flags, close_fds=True)
    return path
