"""Window chrome for 🍏 Mode: a frameless window with our own toolbar-as-title-bar.

- WindowDots: the three round close / minimise / zoom buttons (glyphs appear on hover)
- DragBar: the toolbar becomes the title bar - drag to move (with Windows snapping), double-click to zoom
- EdgeResizer: lets the frameless window be resized from its edges
- win_round_corners: asks Windows 11 for rounded corners + a shadow on the frameless window
"""
import sys

from PyQt6.QtCore import Qt, QRectF, QPointF, QEvent, QObject
from PyQt6.QtGui import QPainter, QColor, QPen
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QFrame, QApplication

from .. import theme

DOTS = (("close", "#ff5f57", "#e0443e"), ("minimise", "#febc2e", "#dea123"), ("zoom", "#28c840", "#1aab29"))


class _Dot(QWidget):
    def __init__(self, kind, fill, edge, parent=None):
        super().__init__(parent)
        self.kind, self.fill, self.edge = kind, fill, edge
        self.setFixedSize(14, 14)
        self.hover = False
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.setToolTip({"close": "Close", "minimise": "Minimise", "zoom": "Zoom"}[kind])

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        active = self.window().isActiveWindow()
        grey = "#4b4b4f" if theme.C.get("dark") else "#d4d4d8"
        p.setPen(QPen(QColor(self.edge if active else grey), 0.8))
        p.setBrush(QColor(self.fill if active else grey))
        p.drawEllipse(QRectF(1, 1, 12, 12))
        if self.parent() is not None and getattr(self.parent(), "hover", False):
            p.setPen(QPen(QColor(0, 0, 0, 150), 1.3))
            c = QPointF(7, 7)
            if self.kind == "close":
                p.drawLine(c + QPointF(-2.6, -2.6), c + QPointF(2.6, 2.6))
                p.drawLine(c + QPointF(-2.6, 2.6), c + QPointF(2.6, -2.6))
            elif self.kind == "minimise":
                p.drawLine(c + QPointF(-3, 0), c + QPointF(3, 0))
            else:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(0, 0, 0, 150))
                from PyQt6.QtGui import QPolygonF
                p.drawPolygon(QPolygonF([c + QPointF(-3, 1.2), c + QPointF(-3, -3), c + QPointF(1.2, -3)]))
                p.drawPolygon(QPolygonF([c + QPointF(3, -1.2), c + QPointF(3, 3), c + QPointF(-1.2, 3)]))

    def mouseReleaseEvent(self, ev):
        if ev.button() != Qt.MouseButton.LeftButton or not self.rect().contains(ev.position().toPoint()):
            return
        w = self.window()
        if self.kind == "close":
            w.close()
        elif self.kind == "minimise":
            w.showMinimized()
        else:
            w.showNormal() if w.isMaximized() else w.showMaximized()


class WindowDots(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.hover = False
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 0, 8, 0)
        lay.setSpacing(8)
        self.dots = [_Dot(k, f, e, self) for k, f, e in DOTS]
        for d in self.dots:
            lay.addWidget(d)

    def enterEvent(self, ev):
        self.hover = True
        for d in self.dots:
            d.update()

    def leaveEvent(self, ev):
        self.hover = False
        for d in self.dots:
            d.update()


class DragBar(QFrame):
    """Toolbar that doubles as the title bar when the window is frameless."""

    def mousePressEvent(self, ev):
        w = self.window()
        if ev.button() == Qt.MouseButton.LeftButton and w.windowFlags() & Qt.WindowType.FramelessWindowHint:
            h = w.windowHandle()
            if h is not None:
                h.startSystemMove()
                return
        super().mousePressEvent(ev)

    def mouseDoubleClickEvent(self, ev):
        w = self.window()
        if w.windowFlags() & Qt.WindowType.FramelessWindowHint:
            w.showNormal() if w.isMaximized() else w.showMaximized()
            return
        super().mouseDoubleClickEvent(ev)


class EdgeResizer(QObject):
    """Resize a frameless window from its edges (uses the OS's own resize, so snapping still works)."""
    M = 6

    def __init__(self, window):
        super().__init__(window)
        self.w = window
        self.active = False
        self._cursor_set = False

    def edges(self, gpos):
        w = self.w
        if not self.active or w.isMaximized() or w.isFullScreen():
            return Qt.Edge(0)
        r = w.frameGeometry()
        m = self.M
        e = Qt.Edge(0)
        if abs(gpos.x() - r.left()) <= m:
            e |= Qt.Edge.LeftEdge
        elif abs(gpos.x() - r.right()) <= m:
            e |= Qt.Edge.RightEdge
        if abs(gpos.y() - r.top()) <= m:
            e |= Qt.Edge.TopEdge
        elif abs(gpos.y() - r.bottom()) <= m:
            e |= Qt.Edge.BottomEdge
        return e

    def eventFilter(self, obj, ev):
        if not self.active:
            return False
        t = ev.type()
        if t in (QEvent.Type.MouseMove, QEvent.Type.HoverMove, QEvent.Type.MouseButtonPress):
            if not isinstance(obj, QWidget) or obj.window() is not self.w:
                return False
            try:
                gpos = ev.globalPosition().toPoint()
            except AttributeError:
                return False
            e = self.edges(gpos)
            if t == QEvent.Type.MouseButtonPress and e and ev.button() == Qt.MouseButton.LeftButton:
                h = self.w.windowHandle()
                if h is not None:
                    h.startSystemResize(e)
                    return True
            if e:
                L, R, T, B = Qt.Edge.LeftEdge, Qt.Edge.RightEdge, Qt.Edge.TopEdge, Qt.Edge.BottomEdge
                if e in (L | T, R | B):
                    cur = Qt.CursorShape.SizeFDiagCursor
                elif e in (R | T, L | B):
                    cur = Qt.CursorShape.SizeBDiagCursor
                elif e & (L | R):
                    cur = Qt.CursorShape.SizeHorCursor
                else:
                    cur = Qt.CursorShape.SizeVerCursor
                if not self._cursor_set:
                    QApplication.setOverrideCursor(cur)
                    self._cursor_set = True
                else:
                    QApplication.changeOverrideCursor(cur)
            elif self._cursor_set:
                QApplication.restoreOverrideCursor()
                self._cursor_set = False
        return False


def win_round_corners(window):
    """Windows 11: rounded corners and a drop shadow for a frameless window (no-op elsewhere)."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        from ctypes import wintypes
        hwnd = int(window.winId())
        dwm = ctypes.windll.dwmapi
        pref = ctypes.c_int(2)                         # DWMWCP_ROUND
        dwm.DwmSetWindowAttribute(wintypes.HWND(hwnd), 33, ctypes.byref(pref), ctypes.sizeof(pref))

        class MARGINS(ctypes.Structure):
            _fields_ = [("l", ctypes.c_int), ("r", ctypes.c_int), ("t", ctypes.c_int), ("b", ctypes.c_int)]
        m = MARGINS(1, 1, 1, 1)
        dwm.DwmExtendFrameIntoClientArea(wintypes.HWND(hwnd), ctypes.byref(m))
    except Exception:
        pass
