"""Re-renders assets/easycut.ico (multi-size) and assets/easycut.png from the app's icon drawing code.

Only needed after changing the icon design (build.bat uses the committed .ico):  python tools/make_icon.py   (needs Pillow: pip install pillow)
"""
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if sys.platform == "win32":
    # the hidden (offscreen) Qt platform has no fonts of its own on Windows - without this the
    # letters render as empty boxes
    os.environ.setdefault("QT_QPA_FONTDIR", os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"))

from PyQt6.QtCore import QBuffer, QIODevice  # noqa: E402
from PyQt6.QtGui import QGuiApplication  # noqa: E402

app = QGuiApplication(sys.argv)
from easycut import icons  # noqa: E402
from PIL import Image  # noqa: E402


def to_pil(pm):
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    pm.save(buf, "PNG")
    return Image.open(io.BytesIO(bytes(buf.data()))).convert("RGBA")


from PyQt6.QtGui import QFontDatabase  # noqa: E402

if not QFontDatabase.families():
    sys.exit("No fonts found, so the icon wasn't changed (assets/easycut.ico is untouched).")

sizes = [16, 20, 24, 32, 40, 48, 64, 128, 256]
images = [to_pil(icons.app_pixmap(s)) for s in sizes]
out = os.path.join(ROOT, "assets", "easycut.ico")
images[-1].save(out, format="ICO", sizes=[(s, s) for s in sizes], append_images=images[:-1])
to_pil(icons.app_pixmap(512)).save(os.path.join(ROOT, "assets", "easycut.png"))
print("wrote", out)
