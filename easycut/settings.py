"""Tiny JSON settings store in the hidden app-data folder."""
import json
import os

from .config import data_path

DEFAULTS = {
    "theme": "dark",                 # dark | light | apple | cyberpunk | custom:<name>
    "check_updates": True,
    "auto_update_extensions": False,
    "hardware_encoding": True,
    "ffmpeg_path": "",
    "recent_projects": [],
    "last_export_dir": "",
    "last_import_dir": "",
    "preview_quality": "balanced",   # performance | balanced | quality
    "snap": True,
}

_cache = None


def _file():
    return data_path("settings.json")


def load() -> dict:
    global _cache
    if _cache is None:
        data = dict(DEFAULTS)
        try:
            with open(_file(), "r", encoding="utf-8") as f:
                stored = json.load(f)
            if isinstance(stored, dict):
                data.update(stored)
        except (OSError, ValueError):
            pass
        _cache = data
    return _cache


def get(key, default=None):
    return load().get(key, DEFAULTS.get(key, default))


def set(key, value):  # noqa: A001 - deliberate, reads nicely as settings.set
    load()[key] = value
    save()


def save():
    data = load()
    tmp = _file() + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, _file())
    except OSError:
        pass


def add_recent(path):
    rec = [p for p in get("recent_projects", []) if p != path]
    rec.insert(0, path)
    set("recent_projects", rec[:10])


def reset_cache():
    """Forget the in-memory copy (used by tests)."""
    global _cache
    _cache = None
