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
    assert window.page_dashboard.orders_table is not None
    assert window.page_orders.btn_delete_selected is not None
    assert window.page_orders.btn_delete_all_dry is not None
    controller.shutdown()


DIALOGS = [
    {"telegram_id": -1001, "name": "Gold VIP", "type": "channel", "monitored": False},
    {"telegram_id": -1002, "name": "News", "type": "group", "monitored": False},
]


def test_telegram_page_collects_checked_groups(qapp) -> None:
    from app.gui.telegram_page import TelegramPage

    page = TelegramPage()
    page.set_dialogs(DIALOGS)
    qapp.processEvents()
    assert page.has_rows()
    assert page.enabled_count() == 0
    assert page.set_checked(-1001, True)
    qapp.processEvents()
    selected = {s["telegram_id"]: s for s in page.collect_selections()}
    assert selected[-1001]["enabled"] is True
    assert selected[-1001]["name"] == "Gold VIP"
    assert selected[-1002]["enabled"] is False
    assert page.enabled_count() == 1
    page.deleteLater()


def test_telegram_page_preserves_checks_across_rebuild(qapp) -> None:
    from app.gui.telegram_page import TelegramPage

    page = TelegramPage()
    emitted: list[tuple] = []
    page.source_toggled.connect(lambda *args: emitted.append(args))
    page.set_dialogs(DIALOGS)
    qapp.processEvents()
    assert page.set_checked(-1001, True)
    page.set_dialogs(
        [
            {"telegram_id": -1001, "name": "Gold VIP", "type": "channel", "monitored": False},
            {"telegram_id": -1002, "name": "News", "type": "group", "monitored": False},
            {"telegram_id": -1003, "name": "Extra", "type": "channel", "monitored": False},
        ]
    )
    qapp.processEvents()
    selected = {s["telegram_id"]: s for s in page.collect_selections()}
    assert selected[-1001]["enabled"] is True
    assert selected[-1002]["enabled"] is False
    assert selected[-1003]["enabled"] is False
    assert not any(tid == -1001 and enabled is False for tid, enabled, *_ in emitted)
    page.deleteLater()


def test_save_source_selections_enables_groups(qapp, tmp_path) -> None:
    from app.config.settings import AppSettings, reset_settings_cache
    from app.database.database import Database
    from app.gui.controller import AppController

    reset_settings_cache()
    settings = AppSettings(data_dir=tmp_path / "data", log_dir=tmp_path / "logs")
    settings.ensure_directories()
    db = Database(settings.database_path)
    db.initialize()
    controller = AppController(settings, db)
    count = controller.save_source_selections(
        [
            {
                "telegram_id": -1001,
                "name": "Gold VIP",
                "type": "channel",
                "enabled": True,
            },
            {
                "telegram_id": -1002,
                "name": "News",
                "type": "group",
                "enabled": False,
            },
        ]
    )
    assert count == 1
    enabled = controller.sources.list_enabled()
    assert len(enabled) == 1
    assert enabled[0].telegram_id == -1001
    controller.shutdown()


def test_start_listening_uses_checked_table_rows(qapp, tmp_path) -> None:
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
    window.page_telegram.set_dialogs(DIALOGS)
    qapp.processEvents()
    assert window.page_telegram.set_checked(-1001, True)
    captured: dict = {}

    def fake_start(selections=None):
        captured["selections"] = selections

    window.controller.start_listening = fake_start  # type: ignore[method-assign]
    window._start_listening()
    assert captured["selections"]
    enabled = [s for s in captured["selections"] if s["enabled"]]
    assert enabled == [
        {
            "telegram_id": -1001,
            "name": "Gold VIP",
            "type": "channel",
            "enabled": True,
        }
    ]
    window._on_data()
    qapp.processEvents()
    still = {s["telegram_id"]: s for s in window.page_telegram.collect_selections()}
    assert still[-1001]["enabled"] is True
    controller.shutdown()
    window.deleteLater()


def test_start_listening_saves_checks_before_listen(qapp, tmp_path) -> None:
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
    window.page_telegram.set_dialogs(DIALOGS)
    qapp.processEvents()
    assert window.page_telegram.set_checked(-1001, True)

    submitted: dict = {}
    original_submit = controller.worker.submit

    def fake_submit(coro, on_done=None):
        submitted["started"] = True
        coro.close()

    controller.worker.submit = fake_submit  # type: ignore[method-assign]
    window._start_listening()
    enabled = controller.sources.list_enabled()
    assert [s.telegram_id for s in enabled] == [-1001]
    assert submitted.get("started") is True
    controller.worker.submit = original_submit  # type: ignore[method-assign]
    controller.shutdown()
    window.deleteLater()

