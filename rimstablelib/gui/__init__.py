"""The manager window (`rimstable gui`). Needs PySide6; the CLI does not."""
import sys

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from . import theme


def main():
    app = QApplication(sys.argv[:1])
    app.setApplicationName("Rimstable")
    app.setDesktopFileName("rimstable")
    app.setStyle("Fusion")  # the same widgets on every platform; the stylesheet does the rest
    f = QFont(app.font())
    if f.pointSizeF() < 10:
        f.setPointSizeF(10)
        app.setFont(f)
    theme.apply(app)
    from .window import MainWindow
    w = MainWindow(app)
    w.show()
    return app.exec()
