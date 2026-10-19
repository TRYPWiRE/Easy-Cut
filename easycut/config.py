"""App-wide paths and URLs.

All user data (settings, themes, extensions, caches, autosaves) lives in the hidden per-user app-data
folder - %APPDATA%\\Easy-Cut on Windows - so nothing is ever written next to the user's own files.
"""
import os
import sys

from . import APP_NAME

GITHUB_OWNER = "TRYPWiRE"
GITHUB_REPO = "Easy-Cut"
GITHUB_URL = f"https://github.com/{GITHUB_OWNER}"
REPO_URL = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}"
RAW_BASE = f"https://raw.githubusercontent.com/{GITHUB_OWNER}/{GITHUB_REPO}/main"
MANIFEST_URL = os.environ.get("EASYCUT_MANIFEST_URL", f"{RAW_BASE}/updates/manifest.json")
RELEASES_URL = f"{REPO_URL}/releases/latest"
TOPTRACKING_URL = "https://discord.gg/wSGNAa5aCk"
TKO_URL = "https://www.discord.gg/TKO1"

PROJECT_EXT = ".ecut"


def app_data_dir() -> str:
    """Hidden per-user data folder (created on first use)."""
    override = os.environ.get("EASYCUT_DATA_DIR")
    if override:
        base = override
    elif sys.platform == "win32":
        base = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~\\AppData\\Roaming"), APP_NAME)
    elif sys.platform == "darwin":
        base = os.path.expanduser(f"~/Library/Application Support/{APP_NAME}")
    else:
        base = os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"), APP_NAME)
    os.makedirs(base, exist_ok=True)
    return base


def data_path(*parts) -> str:
    p = os.path.join(app_data_dir(), *parts)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    return p


def cache_dir(name="cache") -> str:
    p = os.path.join(app_data_dir(), name)
    os.makedirs(p, exist_ok=True)
    return p


def bundle_dir() -> str:
    """Folder holding bundled assets (PyInstaller's _MEIPASS when frozen)."""
    return getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def asset(*parts) -> str:
    return os.path.join(bundle_dir(), "assets", *parts)


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))
