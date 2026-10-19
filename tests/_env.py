"""Shared test setup: hidden Qt, a throwaway app-data folder and generated test media."""
import atexit
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["QT_LOGGING_RULES"] = "qt.multimedia*=false;qt.qpa.*=false"
if sys.platform == "win32":
    # the hidden test platform has no fonts of its own on Windows - point it at the system ones
    os.environ.setdefault("QT_QPA_FONTDIR", os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"))
TMP = tempfile.mkdtemp(prefix="easycut_tests_")
os.environ["EASYCUT_DATA_DIR"] = os.path.join(TMP, "appdata")
os.environ["EASYCUT_MANIFEST_URL"] = "http://127.0.0.1:9/none.json"
atexit.register(lambda: shutil.rmtree(TMP, ignore_errors=True))

from PyQt6.QtWidgets import QApplication  # noqa: E402

APP = QApplication.instance() or QApplication([])

from easycut import media, theme  # noqa: E402

theme.apply(APP, "dark")

MEDIA = os.path.join(TMP, "media")
os.makedirs(MEDIA, exist_ok=True)
_made = False


def ff(*args):
    r = subprocess.run([media.ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y", *args],
                       capture_output=True, creationflags=media.NO_WINDOW)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.decode("utf-8", "replace"))


def make_media():
    """Generate small test files once: a 1280x720 video with sound, a green-screen video, a photo, a tone."""
    global _made
    if _made:
        return MEDIA
    ff("-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=4", "-f", "lavfi", "-i", "sine=f=440:d=4",
       "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", os.path.join(MEDIA, "clip.mp4"))
    ff("-f", "lavfi", "-i", "color=0x00ff00:s=480x360:r=30:d=3,drawbox=x=150:y=100:w=120:h=120:color=red:t=fill",
       "-c:v", "libx264", "-pix_fmt", "yuv420p", os.path.join(MEDIA, "green.mp4"))
    ff("-f", "lavfi", "-i", "testsrc=s=320x240:r=30:d=3", "-c:v", "libx264", "-pix_fmt", "yuv420p",
       os.path.join(MEDIA, "portrait_src.mp4"))
    ff("-f", "lavfi", "-i", "mandelbrot=s=400x300", "-frames:v", "1", os.path.join(MEDIA, "photo.png"))
    ff("-f", "lavfi", "-i", "sine=f=220:d=5", os.path.join(MEDIA, "tone.mp3"))
    ff("-f", "lavfi", "-i", "testsrc2=s=360x640:r=30:d=2", "-c:v", "libx264", "-pix_fmt", "yuv420p",
       os.path.join(MEDIA, "portrait.mp4"))
    _made = True
    return MEDIA


def path(name):
    return os.path.join(make_media(), name)
