"""FocusMic application entry point + single-instance guard."""
from __future__ import annotations

import logging
import sys

from PySide6.QtGui import QFont
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

from .logging_setup import setup_logging
from .ui import MainWindow

SERVER_NAME = "FocusMic-single-instance"


def main() -> int:
    log = setup_logging()
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setFont(QFont("Microsoft YaHei UI", 10))
    app.setApplicationName("FocusMic")
    app.setOrganizationName("FocusMic")

    socket = QLocalSocket()
    socket.connectToServer(SERVER_NAME)
    if socket.waitForConnected(300):
        socket.write(b"show")
        socket.flush()
        socket.waitForBytesWritten(300)
        socket.disconnectFromServer()
        return 0

    server = QLocalServer()
    QLocalServer.removeServer(SERVER_NAME)
    if not server.listen(SERVER_NAME):
        log.warning("single-instance server unavailable: %s", server.errorString())

    window = MainWindow()

    def show_existing():
        window.showNormal()
        window.raise_()
        window.activateWindow()

    server.newConnection.connect(show_existing)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
