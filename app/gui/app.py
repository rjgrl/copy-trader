"""PySide6 application entrypoint."""

from __future__ import annotations

import logging
import os
import sys

from PySide6.QtWidgets import QApplication

from app.config.settings import get_settings
from app.database.database import Database
from app.gui.controller import AppController
from app.gui.main_window import MainWindow
from app.utils.logging import setup_logging

logger = logging.getLogger(__name__)


def run_gui() -> int:
    """Launch the desktop GUI. Returns process exit code."""
    from app.utils.paths import is_frozen

    settings = get_settings()
    # Windowed EXE has no console — log to file + GUI only
    setup_logging(settings.log_dir, settings.log_level, console=not is_frozen())
    settings.ensure_directories()
    db = Database(settings.database_path)
    db.initialize()

    app = QApplication(sys.argv)
    app.setApplicationName("Telegram MT5 Copier")
    app.setOrganizationName("CopyTrader")
    app.setQuitOnLastWindowClosed(True)

    controller = AppController(settings, db)
    window = MainWindow(controller)
    app.aboutToQuit.connect(controller.shutdown)
    window.show()
    logger.info("GUI started — use Dashboard to connect MT5 / Telegram")
    code = 0
    try:
        code = int(app.exec())
    finally:
        controller.shutdown()
        logging.shutdown()
    # Frozen EXE can otherwise linger on Telethon/MT5/Qt threads and lock the folder
    if is_frozen():
        os._exit(code)
    return code
