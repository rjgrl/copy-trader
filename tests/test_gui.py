"""Smoke test: GUI modules import and MainWindow constructs offscreen."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def qapp():
    import sys

    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)
    yield app


def test_gui_imports() -> None:
    from app.gui import run_gui
    from app.gui.controller import AppController
    from app.gui.main_window import MainWindow

    assert callable(run_gui)
    assert AppController is not None
    assert MainWindow is not None


def test_gui_command_in_parser() -> None:
    import argparse

    from app.main import run

    parser = argparse.ArgumentParser()
    # Mirror choices from run() — smoke that gui is wired
    import inspect

    src = inspect.getsource(run)
    assert '"gui"' in src or "'gui'" in src


def test_main_window_builds(qapp, tmp_path) -> None:
    from app.config.settings import AppSettings, reset_settings_cache
    from app.database.database import Database
    from app.gui.controller import AppController
    from app.gui.main_window import MainWindow

    reset_settings_cache()
    settings = AppSettings(data_dir=tmp_path / "data", log_dir=tmp_path / "logs")
    settings.ensure_directories()
    db = Database(settings.database_path)
    db.initialize()
    controller = AppController(settings, db)
    window = MainWindow(controller)
    assert window.windowTitle() == "Telegram MT5 Copier"
    assert window.stack.count() == 6
    controller.shutdown()
