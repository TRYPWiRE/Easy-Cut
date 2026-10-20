"""Theme engine: Dark (default), Light, 🍏 Mode, Cyberpunk and user-made Custom themes.

Custom themes are stored in the hidden app-data folder (themes.json); the chosen default is kept in settings.
"""
import copy
import json
import os

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPalette

from . import settings
from .config import data_path

BASE_KEYS = [
    # key, label (shown in the custom theme editor)
    ("window", "Window background"),
    ("panel", "Panels"),
    ("panel2", "Cards & raised areas"),
    ("header", "Top bar"),
    ("border", "Borders"),
    ("text", "Text"),
    ("text_dim", "Secondary text"),
    ("text_strong", "Headings"),
    ("accent", "Accent"),
    ("accent_text", "Text on accent"),
    ("accent2", "Second accent"),
    ("timeline_bg", "Timeline background"),
    ("track_bg", "Timeline tracks"),
    ("clip_video", "Video clips"),
    ("clip_audio", "Audio clips"),
    ("clip_text", "Text clips"),
    ("clip_image", "Image clips"),
    ("playhead", "Playhead"),
]

PRESETS = {
    "dark": {
        "name": "Dark", "radius": 8, "font": "Segoe UI", "dark": True,
        "window": "#121216", "panel": "#19191e", "panel2": "#222229", "header": "#0e0e11",
        "border": "#2a2a33", "text": "#d9d9e0", "text_dim": "#8b8b98", "text_strong": "#ffffff",
        "accent": "#ff4f7b", "accent_text": "#ffffff", "accent2": "#7c5cff",
        "timeline_bg": "#0d0d10", "track_bg": "#16161b",
        "clip_video": "#3a6fe0", "clip_audio": "#1f9e74", "clip_text": "#d9822b", "clip_image": "#8f5bd6",
        "playhead": "#ff4f7b",
    },
    "light": {
        "name": "Light", "radius": 8, "font": "Segoe UI", "dark": False,
        "window": "#eef0f4", "panel": "#ffffff", "panel2": "#f3f4f7", "header": "#ffffff",
        "border": "#d9dce3", "text": "#2b2d36", "text_dim": "#6c7080", "text_strong": "#0d0e12",
        "accent": "#ff3d6e", "accent_text": "#ffffff", "accent2": "#6a4cff",
        "timeline_bg": "#e4e6ec", "track_bg": "#f6f7fa",
        "clip_video": "#4c82f0", "clip_audio": "#22a87b", "clip_text": "#e08a33", "clip_image": "#9a68dd",
        "playhead": "#ff3d6e",
    },
    "apple": {
        # Light, airy and precise: frosted grey sidebar & toolbar, white content, system blue, green switches
        "name": "🍏 Mode", "radius": 10, "font": "Inter", "dark": False, "apple": True,
        "window": "#f5f5f7", "panel": "#ffffff", "panel2": "#ffffff", "header": "#ececef",
        "border": "#d9d9de", "text": "#1d1d1f", "text_dim": "#86868b", "text_strong": "#000000",
        "accent": "#007aff", "accent_text": "#ffffff", "accent2": "#5856d6",
        "timeline_bg": "#f2f2f7", "track_bg": "#ffffff",
        "clip_video": "#0a84ff", "clip_audio": "#30b158", "clip_text": "#ff9f0a", "clip_image": "#af52de",
        "playhead": "#ff3b30",
        "sidebar": "#e8e8ed", "hover": "#ebebf0", "pressed": "#dedee3", "input": "#ffffff",
        "accent_soft": "#dcebff", "scroll": "#c7c7cc", "switch_on": "#34c759", "success": "#34c759",
        "danger": "#ff3b30",
    },
    "apple_dark": {
        "name": "🍏 Mode (Dark)", "radius": 10, "font": "Inter", "dark": True, "apple": True,
        "window": "#1e1e1f", "panel": "#28282a", "panel2": "#323234", "header": "#2b2b2d",
        "border": "#3a3a3d", "text": "#f2f2f7", "text_dim": "#98989f", "text_strong": "#ffffff",
        "accent": "#0a84ff", "accent_text": "#ffffff", "accent2": "#5e5ce6",
        "timeline_bg": "#1c1c1e", "track_bg": "#242426",
        "clip_video": "#0a84ff", "clip_audio": "#30d158", "clip_text": "#ff9f0a", "clip_image": "#bf5af2",
        "playhead": "#ff453a",
        "sidebar": "#252527", "hover": "#3a3a3c", "pressed": "#48484a", "input": "#1c1c1e",
        "accent_soft": "#173a63", "scroll": "#5a5a5e", "switch_on": "#30d158", "success": "#30d158",
        "danger": "#ff453a",
    },
    "cyberpunk": {
        "name": "Cyberpunk", "radius": 0, "font": "Bahnschrift", "dark": True, "cyber": True,
        "window": "#0a0a12", "panel": "#100f1b", "panel2": "#181628", "header": "#06060b",
        "border": "#3b2a63", "text": "#e8e4ff", "text_dim": "#9088bd", "text_strong": "#fcee0a",
        "accent": "#fcee0a", "accent_text": "#0a0a12", "accent2": "#b026ff",
        "timeline_bg": "#06060b", "track_bg": "#110f1d",
        "clip_video": "#b026ff", "clip_audio": "#00e5ff", "clip_text": "#fcee0a", "clip_image": "#ff2a6d",
        "playhead": "#00e5ff",
    },
}
PRESET_ORDER = ["dark", "light", "apple", "apple_dark", "cyberpunk"]

C = {}
current_id = "dark"


class _Notifier(QObject):
    changed = pyqtSignal()


notifier = _Notifier()


# ---------------------------------------------------------------------- colour helpers
def mix(a, b, t):
    ca, cb = QColor(a), QColor(b)
    return QColor(int(ca.red() + (cb.red() - ca.red()) * t), int(ca.green() + (cb.green() - ca.green()) * t),
                  int(ca.blue() + (cb.blue() - ca.blue()) * t)).name()


def is_dark(hexcol):
    c = QColor(hexcol)
    return (0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()) < 128


def complete(t: dict) -> dict:
    """Fill in derived colours (hover, pressed, inputs...) for a theme."""
    t = dict(t)
    base = PRESETS["dark"] if t.get("dark", is_dark(t.get("window", "#000"))) else PRESETS["light"]
    for k, _ in BASE_KEYS:
        t.setdefault(k, base[k])
    t.setdefault("radius", 8)
    t.setdefault("font", "Segoe UI")
    dark = is_dark(t["window"])
    t["dark"] = dark
    toward = "#ffffff" if dark else "#000000"
    t.setdefault("hover", mix(t["panel"], toward, 0.07))
    t.setdefault("pressed", mix(t["panel"], toward, 0.13))
    t.setdefault("input", mix(t["window"], "#000000" if dark else "#ffffff", 0.35 if dark else 0.7))
    t.setdefault("accent_hover", mix(t["accent"], toward if not dark else "#ffffff", 0.12))
    t.setdefault("accent_soft", mix(t["panel"], t["accent"], 0.18))
    t.setdefault("scroll", mix(t["panel"], toward, 0.2))
    t.setdefault("danger", "#ff453a")
    t.setdefault("sidebar", t["header"])
    t.setdefault("switch_on", t["accent"])
    t.setdefault("success", "#30d158")
    return t


# ---------------------------------------------------------------------- custom theme storage
def _themes_file():
    return data_path("themes.json")


def custom_themes() -> dict:
    try:
        with open(_themes_file(), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_custom(name: str, colours: dict):
    data = custom_themes()
    keep = {k: colours[k] for k, _ in BASE_KEYS if k in colours}
    keep["radius"] = int(colours.get("radius", 8))
    keep["font"] = colours.get("font", "Segoe UI")
    keep["name"] = name
    data[name] = keep
    tmp = _themes_file() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, _themes_file())


def delete_custom(name: str):
    data = custom_themes()
    if name in data:
        del data[name]
        with open(_themes_file(), "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)


def resolve(theme_id: str) -> dict:
    if theme_id.startswith("custom:"):
        t = custom_themes().get(theme_id[7:])
        if t:
            return complete(t)
        theme_id = "dark"
    return complete(PRESETS.get(theme_id, PRESETS["dark"]))


def display_name(theme_id: str) -> str:
    if theme_id.startswith("custom:"):
        return theme_id[7:]
    return PRESETS.get(theme_id, PRESETS["dark"])["name"]


# ---------------------------------------------------------------------- stylesheet
def stylesheet(c: dict) -> str:
    if c.get("apple"):
        return apple_stylesheet(c)
    r = int(c["radius"])
    rs = max(0, r - 3)
    rb = r + 6 if c.get("apple") else r
    border_w = 2 if c.get("cyber") else 1
    font = c["font"]
    fallback = '"Segoe UI Variable", "Segoe UI", "Helvetica Neue", Arial' if not c.get("cyber") else \
        '"Bahnschrift", "Rajdhani", "Orbitron", "Segoe UI", Arial'
    if c.get("apple"):
        fallback = '"SF Pro Text", "-apple-system", "Segoe UI Variable Display", "Segoe UI", "Helvetica Neue", Arial'
    return f"""
* {{ font-family: "{font}", {fallback}; font-size: 13px; color: {c['text']}; outline: none; }}
QWidget {{ background: transparent; }}
QMainWindow, QDialog, QMessageBox, QWidget#Root {{ background: {c['window']}; }}
QToolTip {{ background: {c['panel2']}; color: {c['text']}; border: 1px solid {c['border']}; padding: 5px 8px; border-radius: {rs}px; }}
QFrame#Panel, QWidget#Panel {{ background: {c['panel']}; border: {border_w if c.get('cyber') else 1}px solid {c['border']}; border-radius: {r}px; }}
QFrame#Card {{ background: {c['panel2']}; border: 1px solid {c['border']}; border-radius: {r}px; }}
QFrame#TopBar {{ background: {c['header']}; border-bottom: {border_w}px solid {c['accent2'] if c.get('cyber') else c['border']}; }}
QFrame#SideRail {{ background: {c['header']}; border-right: 1px solid {c['border']}; }}
QLabel {{ background: transparent; }}
QLabel#H1 {{ font-size: 20px; font-weight: 700; color: {c['text_strong']}; }}
QLabel#H2 {{ font-size: 15px; font-weight: 700; color: {c['text_strong']}; }}
QLabel#Section {{ font-size: 11px; font-weight: 700; color: {c['text_dim']}; padding-top: 6px; }}
QLabel#Dim {{ color: {c['text_dim']}; }}
QLabel#Brand {{ font-size: 17px; font-weight: 800; color: {c['text_strong']}; }}
QLabel#Badge {{ background: {c['accent']}; color: {c['accent_text']}; border-radius: {max(4, rs)}px; padding: 1px 6px; font-size: 10px; font-weight: 800; }}
QLabel#Timecode {{ font-family: "Consolas", "SF Mono", monospace; font-size: 13px; color: {c['text_strong']}; }}

QPushButton {{ background: {c['panel2']}; border: {border_w}px solid {c['border']}; border-radius: {rb}px; padding: 6px 14px; color: {c['text']}; }}
QPushButton:hover {{ background: {c['hover']}; border-color: {c['accent'] if c.get('cyber') else c['border']}; }}
QPushButton:pressed {{ background: {c['pressed']}; }}
QPushButton:checked {{ background: {c['accent_soft']}; border-color: {c['accent']}; color: {c['text_strong']}; }}
QPushButton:disabled {{ color: {c['text_dim']}; background: {c['panel']}; }}
QPushButton#Primary {{ background: {c['accent']}; color: {c['accent_text']}; border: {border_w}px solid {c['accent']}; font-weight: 700; padding: 7px 18px; }}
QPushButton#Primary:hover {{ background: {c['accent_hover']}; }}
QPushButton#Primary:disabled {{ background: {c['pressed']}; color: {c['text_dim']}; border-color: {c['border']}; }}
QPushButton#Flat, QToolButton {{ background: transparent; border: 1px solid transparent; border-radius: {rs}px; padding: 4px; }}
QPushButton#Flat:hover, QToolButton:hover {{ background: {c['hover']}; }}
QToolButton:checked {{ background: {c['accent_soft']}; border-color: {c['accent']}; }}
QToolButton:pressed {{ background: {c['pressed']}; }}
QToolButton::menu-indicator {{ image: none; }}
QPushButton#Rail {{ background: transparent; border: none; border-radius: {r}px; padding: 8px 2px; color: {c['text_dim']}; font-size: 11px; }}
QPushButton#Rail:hover {{ background: {c['hover']}; color: {c['text']}; }}
QPushButton#Rail:checked {{ background: {c['accent_soft']}; color: {c['text_strong']}; }}
QPushButton#RailExt {{ background: {c['accent_soft']}; border: {border_w}px solid {c['accent']}; border-radius: {r}px; padding: 8px 2px; color: {c['text_strong']}; font-size: 11px; font-weight: 700; }}
QPushButton#RailExt:hover {{ background: {mix(c['accent_soft'], c['accent'], 0.25)}; }}
QPushButton#RailExt:checked {{ background: {c['accent']}; color: {c['accent_text']}; }}
QFrame#Hero {{ border: {border_w}px solid {c['accent']}; border-radius: {r + 4}px; background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {mix(c['panel2'], c['accent'], 0.22)}, stop:1 {mix(c['panel2'], c['accent2'], 0.22)}); }}
QLabel#Chip {{ background: {c['panel2']}; border: 1px solid {c['border']}; border-radius: {max(4, r)}px; padding: 5px 10px; color: {c['text_strong']}; font-weight: 600; }}
QPushButton#Tile {{ background: {c['panel2']}; border: {border_w}px solid {c['border']}; border-radius: {r}px; padding: 6px; text-align: center; }}
QPushButton#Tile:hover {{ border-color: {c['accent']}; }}
QPushButton#Tile:checked {{ border: 2px solid {c['accent']}; background: {c['accent_soft']}; }}

QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: {c['input']}; border: {border_w}px solid {c['border']}; border-radius: {rs}px; padding: 4px 8px;
    selection-background-color: {c['accent']}; selection-color: {c['accent_text']}; }}
QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{ border-color: {c['accent']}; }}
QComboBox::drop-down {{ border: none; width: 20px; }}
QComboBox QAbstractItemView {{ background: {c['panel2']}; border: 1px solid {c['border']}; selection-background-color: {c['accent']}; selection-color: {c['accent_text']}; padding: 4px; }}
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 0; border: none; }}

QSlider::groove:horizontal {{ height: 4px; background: {c['pressed']}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {c['accent']}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {c['text_strong'] if not c.get('cyber') else c['accent']}; width: 14px; height: 14px; margin: -5px 0; border-radius: {7 if r > 0 else 0}px; border: 2px solid {c['accent']}; }}
QSlider::handle:horizontal:hover {{ background: {c['accent']}; }}

QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: {min(4, rs)}px; border: {border_w}px solid {c['border']}; background: {c['input']}; }}
QCheckBox::indicator:checked {{ background: {c['accent']}; border-color: {c['accent']}; }}
QRadioButton::indicator {{ width: 14px; height: 14px; border-radius: 8px; border: 1px solid {c['border']}; background: {c['input']}; }}
QRadioButton::indicator:checked {{ background: {c['accent']}; border-color: {c['accent']}; }}

QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {c['scroll']}; border-radius: 3px; min-height: 30px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {c['scroll']}; border-radius: 3px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ background: none; border: none; width: 0; height: 0; }}

QMenu {{ background: {c['panel2']}; border: 1px solid {c['border']}; border-radius: {r}px; padding: 5px; }}
QMenu::item {{ padding: 6px 22px 6px 12px; border-radius: {rs}px; }}
QMenu::item:selected {{ background: {c['accent']}; color: {c['accent_text']}; }}
QMenu::separator {{ height: 1px; background: {c['border']}; margin: 4px 6px; }}
QTabWidget::pane {{ border: none; }}
QTabBar::tab {{ background: transparent; color: {c['text_dim']}; padding: 6px 12px; border-bottom: 2px solid transparent; }}
QTabBar::tab:selected {{ color: {c['text_strong']}; border-bottom: 2px solid {c['accent']}; }}
QTabBar::tab:hover {{ color: {c['text']}; }}
QHeaderView::section {{ background: {c['panel']}; color: {c['text_dim']}; border: none; border-bottom: 1px solid {c['border']}; padding: 5px 8px; font-weight: 600; }}
QTreeView, QListView, QTreeWidget {{ background: transparent; border: none; selection-background-color: {c['accent_soft']}; selection-color: {c['text_strong']}; }}
QTreeView::item {{ padding: 4px 2px; border: none; }}
QTreeView::item:hover {{ background: {c['hover']}; }}
QTreeView::item:selected {{ background: {c['accent_soft']}; color: {c['text_strong']}; }}
QListWidget {{ background: {c['input']}; border: 1px solid {c['border']}; border-radius: {rs}px; }}
QListWidget::item {{ padding: 6px; border-radius: {rs}px; }}
QListWidget::item:selected {{ background: {c['accent_soft']}; color: {c['text_strong']}; }}
QProgressBar {{ background: {c['pressed']}; border: none; border-radius: 3px; height: 6px; text-align: center; color: transparent; }}
QProgressBar::chunk {{ background: {c['accent']}; border-radius: 3px; }}
QSplitter::handle {{ background: {c['window']}; }}
QSplitter::handle:hover {{ background: {c['accent_soft']}; }}
QStatusBar {{ background: {c['header']}; color: {c['text_dim']}; border-top: 1px solid {c['border']}; }}
QMessageBox QLabel {{ color: {c['text']}; }}
""" + (f"""
QFrame#Panel, QWidget#Panel {{ border-top: 3px solid {c['accent']}; }}
QFrame#SideRail {{ border-right: 2px solid {c['accent2']}; }}
QPushButton#Primary {{ border-bottom: 3px solid {c['accent2']}; }}
QTabBar::tab:selected {{ background: {c['accent']}; color: {c['accent_text']}; }}
""" if c.get("cyber") else "")



def apple_stylesheet(c: dict) -> str:
    """🍏 Mode: a desktop-OS look built from scratch - frosted sidebar, segmented tabs, pill buttons,
    white knobs, thin overlay scrollbars and generous spacing. (No Apple artwork or fonts are used.)"""
    dark = c.get("dark")
    shade = "rgba(255,255,255,0.10)" if dark else "rgba(0,0,0,0.06)"
    shade2 = "rgba(255,255,255,0.16)" if dark else "rgba(0,0,0,0.10)"
    knob = "#e9e9ec" if dark else "#ffffff"
    seg_track = "#1c1c1e" if dark else "#e4e4e9"
    seg_on = "#5b5b5f" if dark else "#ffffff"
    btn_bg = "#4a4a4e" if dark else "#ffffff"
    btn_border = "#4f4f53" if dark else "#d2d2d7"
    focus = "#3a8dff" if dark else "#7ab4ff"
    return f"""
* {{ font-family: "Inter", "Segoe UI Variable Text", "Segoe UI", "Helvetica Neue", Arial; font-size: 13px; color: {c['text']}; outline: none; }}
QWidget {{ background: transparent; }}
QMainWindow, QDialog, QMessageBox, QWidget#Root {{ background: {c['window']}; }}
QToolTip {{ background: {c['panel2']}; color: {c['text']}; border: 1px solid {c['border']}; padding: 5px 9px; border-radius: 7px; }}

QFrame#TopBar {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {c['header']}, stop:1 {c['sidebar']}); border-bottom: 1px solid {c['border']}; }}
QFrame#SideRail {{ background: {c['sidebar']}; border: none; border-right: 1px solid {c['border']}; }}
QFrame#Panel, QWidget#Panel {{ background: {c['panel']}; border: 1px solid {c['border']}; border-radius: 12px; }}
QFrame#Card {{ background: {c['panel2']}; border: 1px solid {c['border']}; border-radius: 12px; }}
QFrame#Hero {{ background: {c['panel2']}; border: 1px solid {c['border']}; border-radius: 14px; }}
QLabel {{ background: transparent; }}
QLabel#H1 {{ font-size: 22px; font-weight: 700; color: {c['text_strong']}; }}
QLabel#H2 {{ font-size: 15px; font-weight: 600; color: {c['text_strong']}; }}
QLabel#Section {{ font-size: 11px; font-weight: 600; color: {c['text_dim']}; padding-top: 8px; }}
QLabel#Dim {{ color: {c['text_dim']}; }}
QLabel#Brand {{ font-size: 15px; font-weight: 700; color: {c['text_strong']}; }}
QLabel#Badge {{ background: {c['accent']}; color: #ffffff; border-radius: 8px; padding: 1px 7px; font-size: 10px; font-weight: 700; }}
QLabel#Chip {{ background: {shade}; border: none; border-radius: 9px; padding: 5px 11px; color: {c['text_strong']}; font-weight: 500; }}
QLabel#Timecode {{ font-family: "Inter", "Consolas", monospace; font-size: 13px; font-weight: 600; color: {c['text_strong']}; }}

QPushButton {{ background: {btn_bg}; border: 1px solid {btn_border}; border-bottom-color: {"#3e3e42" if dark else "#c1c1c6"}; border-radius: 7px; padding: 5px 14px; color: {c['text_strong']}; font-weight: 500; }}
QPushButton:hover {{ background: {"#545458" if dark else "#fafafa"}; }}
QPushButton:pressed {{ background: {c['pressed']}; }}
QPushButton:checked {{ background: {c['accent']}; border-color: {c['accent']}; color: #ffffff; }}
QPushButton:disabled {{ color: {c['text_dim']}; background: {shade}; border-color: transparent; }}
QPushButton#Primary {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {"#2b95ff" if not dark else "#2a93ff"}, stop:1 {c['accent']}); color: #ffffff; border: 1px solid {"#0062cc" if not dark else c['accent']}; font-weight: 600; padding: 5px 18px; border-radius: 7px; }}
QPushButton#Primary:hover {{ background: {"#1a8cff" if not dark else "#3a9bff"}; }}
QPushButton#Primary:pressed {{ background: {"#0062cc" if not dark else "#0a6fd6"}; }}
QPushButton#Primary:disabled {{ background: {shade2}; color: {c['text_dim']}; border-color: transparent; }}
QPushButton#Flat, QToolButton {{ background: transparent; border: 1px solid transparent; border-radius: 6px; padding: 4px; }}
QPushButton#Flat:hover, QToolButton:hover {{ background: {shade}; }}
QPushButton#Flat:checked, QToolButton:checked {{ background: {shade2}; border-color: transparent; color: {c['text_strong']}; }}
QToolButton::menu-indicator {{ image: none; }}
QPushButton#Rail, QPushButton#RailExt {{ background: transparent; border: none; border-radius: 7px; padding: 0; }}
QPushButton#Rail:hover, QPushButton#RailExt:hover {{ background: {shade}; }}
QPushButton#Rail:checked, QPushButton#RailExt:checked {{ background: {shade2}; }}
QPushButton#Tile {{ background: {c['panel2']}; border: 1px solid {c['border']}; border-radius: 10px; padding: 6px; color: {c['text']}; font-weight: 500; }}
QPushButton#Tile:hover {{ border-color: {"#6a6a70" if dark else "#b9b9bf"}; }}
QPushButton#Tile:checked {{ border: 2px solid {c['accent']}; background: {c['accent_soft']}; color: {c['text_strong']}; }}
QPushButton#Traffic {{ border: none; border-radius: 6px; padding: 0; }}

QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: {c['input']}; border: 1px solid {btn_border}; border-radius: 6px; padding: 4px 8px;
    selection-background-color: {c['accent']}; selection-color: #ffffff; }}
QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{ border: 2px solid {focus}; padding: 3px 7px; }}
QComboBox {{ background: {btn_bg}; border-bottom-color: {"#3e3e42" if dark else "#c1c1c6"}; padding-right: 22px; }}
QComboBox:focus {{ border: 2px solid {focus}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{ background: {c['panel2']}; border: 1px solid {c['border']}; border-radius: 8px; padding: 5px; selection-background-color: {c['accent']}; selection-color: #ffffff; outline: none; }}
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 0; border: none; }}

QSlider::groove:horizontal {{ height: 4px; background: {"#48484a" if dark else "#d6d6db"}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {c['accent']}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {knob}; width: 18px; height: 18px; margin: -8px 0; border-radius: 9px; border: 1px solid {"#5a5a5e" if dark else "#c4c4c9"}; }}
QSlider::handle:horizontal:hover {{ background: {"#ffffff" if dark else "#f7f7f7"}; }}

QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 4px; border: 1px solid {btn_border}; background: {btn_bg}; }}
QCheckBox::indicator:checked {{ background: {c['accent']}; border-color: {c['accent']}; }}
QRadioButton::indicator {{ width: 15px; height: 15px; border-radius: 8px; border: 1px solid {btn_border}; background: {btn_bg}; }}
QRadioButton::indicator:checked {{ background: {c['accent']}; border: 4px solid {knob}; }}

QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 9px; margin: 3px 1px; }}
QScrollBar::handle:vertical {{ background: {c['scroll']}; border-radius: 3px; min-height: 36px; }}
QScrollBar::handle:vertical:hover {{ background: {"#7a7a7f" if dark else "#a0a0a6"}; }}
QScrollBar:horizontal {{ background: transparent; height: 9px; margin: 1px 3px; }}
QScrollBar::handle:horizontal {{ background: {c['scroll']}; border-radius: 3px; min-width: 36px; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ background: none; border: none; width: 0; height: 0; }}

QMenu {{ background: {c['panel2']}; border: 1px solid {c['border']}; border-radius: 10px; padding: 6px; }}
QMenu::item {{ padding: 5px 24px 5px 12px; border-radius: 5px; }}
QMenu::item:selected {{ background: {c['accent']}; color: #ffffff; }}
QMenu::separator {{ height: 1px; background: {c['border']}; margin: 5px 8px; }}
QMenu::section {{ color: {c['text_dim']}; font-weight: 600; padding: 6px 10px 2px 10px; }}

QTabWidget::pane {{ border: none; }}
QTabWidget::tab-bar {{ alignment: center; }}
QTabBar {{ background: {seg_track}; border-radius: 8px; }}
QTabBar::tab {{ background: transparent; color: {c['text']}; padding: 4px 14px; margin: 2px; border-radius: 6px; border: none; font-weight: 500; }}
QTabBar::tab:selected {{ background: {seg_on}; color: {c['text_strong']}; border: 1px solid {"#6a6a6e" if dark else "#d2d2d7"}; }}
QTabBar::tab:hover:!selected {{ background: {shade}; }}

QHeaderView::section {{ background: {c['panel']}; color: {c['text_dim']}; border: none; border-bottom: 1px solid {c['border']}; padding: 5px 8px; font-weight: 600; }}
QTreeView, QListView, QTreeWidget {{ background: transparent; border: none; selection-background-color: {c['accent']}; selection-color: #ffffff; }}
QTreeView::item {{ padding: 4px 2px; border: none; border-radius: 5px; }}
QTreeView::item:hover {{ background: {shade}; }}
QTreeView::item:selected {{ background: {c['accent']}; color: #ffffff; }}
QListWidget {{ background: {c['input']}; border: 1px solid {c['border']}; border-radius: 10px; }}
QListWidget::item {{ padding: 6px; border-radius: 6px; }}
QListWidget::item:selected {{ background: {c['accent']}; color: #ffffff; }}
QProgressBar {{ background: {shade2}; border: none; border-radius: 3px; height: 6px; color: transparent; }}
QProgressBar::chunk {{ background: {c['accent']}; border-radius: 3px; }}
QSplitter::handle {{ background: {c['window']}; }}
QSplitter::handle:hover {{ background: {c['accent_soft']}; }}
QStatusBar {{ background: {c['sidebar']}; color: {c['text_dim']}; border-top: 1px solid {c['border']}; }}
QMessageBox QLabel {{ color: {c['text']}; }}
"""


_fonts_loaded = False


def load_bundled_fonts():
    """Inter (open-licence UI font) ships with the app for 🍏 Mode."""
    global _fonts_loaded
    if _fonts_loaded:
        return
    _fonts_loaded = True
    try:
        from PyQt6.QtGui import QFontDatabase
        from .config import asset
        p = asset("fonts", "Inter.ttf")
        if os.path.exists(p):
            QFontDatabase.addApplicationFont(p)
    except Exception:
        pass


def apply(app, theme_id: str = None, remember=False):
    """Apply a theme to the whole app (live)."""
    global current_id
    if theme_id is None:
        theme_id = settings.get("theme", "dark")
    C.clear()
    C.update(resolve(theme_id))
    current_id = theme_id if (not theme_id.startswith("custom:") or theme_id[7:] in custom_themes()) else "dark"
    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window, QColor(C["window"]))
    pal.setColor(QPalette.ColorRole.Base, QColor(C["input"]))
    pal.setColor(QPalette.ColorRole.Text, QColor(C["text"]))
    pal.setColor(QPalette.ColorRole.WindowText, QColor(C["text"]))
    pal.setColor(QPalette.ColorRole.Button, QColor(C["panel2"]))
    pal.setColor(QPalette.ColorRole.ButtonText, QColor(C["text"]))
    pal.setColor(QPalette.ColorRole.Highlight, QColor(C["accent"]))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor(C["accent_text"]))
    pal.setColor(QPalette.ColorRole.ToolTipBase, QColor(C["panel2"]))
    pal.setColor(QPalette.ColorRole.ToolTipText, QColor(C["text"]))
    pal.setColor(QPalette.ColorRole.PlaceholderText, QColor(C["text_dim"]))
    app.setPalette(pal)
    if C.get("apple"):
        load_bundled_fonts()
    f = QFont(C["font"])
    f.setPointSizeF(9.75)
    if C.get("apple"):
        f.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 99.2)
        f.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    if C.get("cyber"):
        f.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 104)
    app.setFont(f)
    if C.get("cyber"):
        bf = QFont(f)
        bf.setCapitalization(QFont.Capitalization.AllUppercase)
        bf.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 110)
        app.setFont(bf, "QPushButton")
    else:
        app.setFont(f, "QPushButton")
    app.setStyleSheet(stylesheet(C))
    if remember:
        settings.set("theme", current_id)
    notifier.changed.emit()
    return C


def ensure_loaded():
    if not C:
        C.update(resolve(settings.get("theme", "dark")))


def copy_current():
    return copy.deepcopy(C)
