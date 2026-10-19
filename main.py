"""Easy-Cut entry point."""
import os
import sys


def main():
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("TRYPWiRE.EasyCut")
        except Exception:
            pass
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import Qt
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    from easycut import APP_NAME, theme, extensions, icons
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("TRYPWiRE")
    app.setWindowIcon(icons.app_icon())
    theme.apply(app)
    try:
        extensions.load_all()
    except Exception:
        pass
    from easycut.ui.mainwindow import MainWindow
    path = next((a for a in sys.argv[1:] if not a.startswith("-")), None)
    win = MainWindow(app, open_path=path)
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
