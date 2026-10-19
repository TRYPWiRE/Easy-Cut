"""Canvas shapes, render qualities, frame rates and output formats."""

# key: (friendly name, true name, ratio w, ratio h, typical use)
ASPECTS = {
    "movie":     ("Movie Style",      "Landscape 16:9",     16, 9,  "YouTube, TV, monitors"),
    "tiktok":    ("TikTok Style",     "Portrait 9:16",      9, 16,  "TikTok, Reels, Shorts, Stories"),
    "square":    ("Insta Square",     "Square 1:1",         1, 1,   "Instagram & Facebook feed"),
    "portrait45": ("Insta Portrait",  "Vertical 4:5",       4, 5,   "Instagram portrait posts"),
    "cinema":    ("Cinematic",        "Ultrawide 21:9",     21, 9,  "Cinematic widescreen"),
    "classic":   ("Classic TV",       "Standard 4:3",       4, 3,   "Retro look, presentations"),
    "twitter":   ("Feed Landscape",   "Landscape 5:4",      5, 4,   "X / Twitter, LinkedIn"),
}
ASPECT_ORDER = ["movie", "tiktok", "square", "portrait45", "cinema", "classic", "twitter"]

# quality key: short-side pixels
QUALITIES = {"1080p": 1080, "1440p": 1440, "2160p": 2160}
QUALITY_LABELS = {"1080p": "1080p  (Full HD)", "1440p": "1440p  (2K / QHD)", "2160p": "2160p  (4K / UHD)"}
FPS_OPTIONS = [10, 30, 60]
FPS_LABELS = {10: "10 fps  (GIFs)", 30: "30 fps  (standard)", 60: "60 fps  (smooth)"}

FORMATS = {
    "mp4": ("MP4 (H.264)", ".mp4"),
    "webm": ("WebM (VP9)", ".webm"),
    "gif": ("GIF (animated)", ".gif"),
}


def aspect_label(key: str) -> str:
    name, true, *_ = ASPECTS[key]
    return f"{name}  -  {true}"


def canvas_size(aspect: str, quality: str = "1080p") -> tuple:
    """Pixel size for an aspect at a quality (the short side equals the quality number; even numbers)."""
    _, _, rw, rh, _ = ASPECTS.get(aspect, ASPECTS["movie"])
    short = QUALITIES.get(quality, 1080)
    if rw >= rh:
        h = short
        w = round(short * rw / rh)
    else:
        w = short
        h = round(short * rh / rw)
    return int(w) // 2 * 2, int(h) // 2 * 2


def preview_size(aspect: str, max_w=960, max_h=540) -> tuple:
    w, h = canvas_size(aspect, "1080p")
    s = min(max_w / w, max_h / h)
    return max(2, int(w * s) // 2 * 2), max(2, int(h * s) // 2 * 2)
