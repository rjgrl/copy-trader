"""GUI application controller — bridges services to Qt signals."""

from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import QObject, QTimer, Signal

from app.config.settings import AppSettings, get_settings, reset_settings_cache
from app.database.database import Database
from app.database.repositories import (
    OrderRepository,
    SignalRepository,
    TelegramSourceRepository,
)
from app.gui.worker import AsyncWorker
from app.mt5.client import MT5Error
from app.signals.inspector import SignalInspector
from app.telegram.service import TelegramService
from app.telegram.simulator import SAMPLE_SELL_XAUUSD, TelegramSimulator
from app.utils.logging import GuiLogHandler

logger = logging.getLogger(__name__)


class AppController(QObject):
    """Owns settings/DB/services and emits UI-friendly updates."""

    status_changed = Signal(dict)
    log_received = Signal(str, str)  # message, level
    error_occurred = Signal(str)
    data_refreshed = Signal()
    dialogs_loaded = Signal(list)
    auth_finished = Signal(bool, str)

    def __init__(self, settings: AppSettings | None = None, db: Database | None = None) -> None:
        super().__init__()
        self.settings = settings or get_settings()
        if db is None:
            self.settings.ensure_directories()
            db = Database(self.settings.database_path)
            db.initialize()
        self.db = db
        self.signals = SignalRepository(db)
        self.orders = OrderRepository(db)
        self.sources = TelegramSourceRepository(db)
        self.service = TelegramService(self.settings, db, attach_mt5=False)
        self.inspector = SignalInspector()
        self.worker = AsyncWorker()
        self.worker.error.connect(self.error_occurred.emit)
        self.worker.start()

        self._tg_connected = False
        self._mt5_connected = False
        self._listening = False
        self._account: dict[str, Any] | None = None
        self._shutting_down = False

        handler = GuiLogHandler(self._on_log)
        logging.getLogger().addHandler(handler)

        self._poll = QTimer(self)
        self._poll.setInterval(2000)
        self._poll.timeout.connect(self.refresh_status)
        self._poll.start()

    def _on_log(self, message: str, level: str) -> None:
        self.log_received.emit(message, level)

    def shutdown(self) -> None:
        if self._shutting_down:
            return
        self._shutting_down = True
        self._poll.stop()

        async def _stop():
            await self.service.stop()

        if self._tg_connected or self.service.listener.is_listening:
            self.worker.submit(_stop())
        if self.service.mt5 and self.service.mt5.is_connected:
            try:
                self.service.mt5.disconnect()
            except Exception:  # noqa: BLE001
                pass
        self.worker.stop()
        self.db.close()

    # ------------------------------------------------------------------ status
    def snapshot(self) -> dict[str, Any]:
        kill = self.service.kill_switch.active
        return {
            "telegram": "connected" if self._tg_connected else "disconnected",
            "mt5": "connected" if self._mt5_connected else "disconnected",
            "listening": self._listening,
            "dry_run": self.settings.dry_run,
            "copy_trading": self.settings.copy_trading_enabled,
            "kill_switch": kill,
            "account": self._account,
            "mappings": dict(self.settings.symbol_mappings),
            "recent_signals": self.signals.list_recent(20),
            "recent_orders": self.orders.list_recent(50),
            "sources": self.sources.list_all(),
        }

    def refresh_status(self) -> None:
        if self.service.mt5 and self.service.mt5.is_connected:
            try:
                info = self.service.mt5.client.get_account_info()
                if info:
                    self._account = info.model_dump()
                    self._mt5_connected = True
            except Exception:  # noqa: BLE001
                self._mt5_connected = False
                self._account = None
        self._listening = self.service.listener.is_listening
        self.status_changed.emit(self.snapshot())
        self.data_refreshed.emit()

    # ------------------------------------------------------------------ actions
    def connect_mt5(self) -> None:
        try:
            if self.service.mt5 is None:
                self.service.connect_mt5()
            else:
                self.service.mt5.connect()
            info = self.service.mt5.client.get_account_info() if self.service.mt5 else None
            self._account = info.model_dump() if info else None
            self._mt5_connected = True
            self.refresh_status()
        except MT5Error as exc:
            self._mt5_connected = False
            self.error_occurred.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            self._mt5_connected = False
            self.error_occurred.emit(str(exc))

    def disconnect_mt5(self) -> None:
        if self.service.mt5 and self.service.mt5.is_connected:
            self.service.mt5.disconnect()
        self._mt5_connected = False
        self._account = None
        self.refresh_status()

    def connect_telegram(self, *, interactive: bool = True) -> None:
        async def _connect():
            await self.service.connect(interactive_auth=False)
            if self.service.client_service.is_authorized:
                return True
            if interactive:
                raise RuntimeError(
                    "Telegram session not authorized. "
                    "Run 'python run.py auth' once in a terminal, then reconnect here."
                )
            return False

        def _done(ok: bool) -> None:
            self._tg_connected = bool(ok)
            self.auth_finished.emit(bool(ok), "authorized" if ok else "not authorized")
            self.refresh_status()

        self.worker.submit(_connect(), on_done=_done)

    def start_listening(self) -> None:
        async def _listen():
            if not self.service.client_service.is_connected:
                await self.service.connect(interactive_auth=False)
            if self.service.mt5 is None or not self.service.mt5.is_connected:
                try:
                    self.service.connect_mt5()
                    self._mt5_connected = True
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Listen without MT5: %s", exc)
            await self.service.start_listening()
            return True

        def _done(_result) -> None:
            self._tg_connected = True
            self._listening = True
            self.refresh_status()

        self.worker.submit(_listen(), on_done=_done)

    def stop_listening(self) -> None:
        self.service.listener.stop()
        self._listening = False
        self.refresh_status()

    def activate_kill_switch(self) -> None:
        self.service.kill_switch.activate()
        self.settings.kill_switch_active = True
        self.refresh_status()

    def deactivate_kill_switch(self) -> None:
        self.service.kill_switch.deactivate()
        self.settings.kill_switch_active = False
        self.refresh_status()

    def set_source_enabled(self, telegram_id: int, enabled: bool) -> None:
        self.sources.set_enabled(telegram_id, enabled)
        self.refresh_status()

    def upsert_source(self, telegram_id: int, name: str, source_type: str, enabled: bool) -> None:
        from app.database.models import TelegramSourceRecord

        self.sources.upsert(
            TelegramSourceRecord(
                id=None,
                telegram_id=telegram_id,
                name=name,
                source_type=source_type,
                enabled=enabled,
            )
        )
        self.refresh_status()

    def load_dialogs(self) -> None:
        async def _fetch():
            if not self.service.client_service.is_connected:
                await self.service.connect(interactive_auth=False)
            return await self.service.sources.fetch_dialogs()

        def _done(dialogs) -> None:
            payload = [
                {
                    "telegram_id": d.telegram_id,
                    "name": d.name,
                    "type": d.dialog_type.value,
                    "monitored": d.is_monitored,
                }
                for d in dialogs
            ]
            self.dialogs_loaded.emit(payload)

        self.worker.submit(_fetch(), on_done=_done)

    def simulate_sample(self) -> None:
        from app.mt5.gateway import MockMT5Gateway

        # Ensure entry+execution path with mock prices near sample entry
        mock = MockMT5Gateway()
        mock.set_tick("GOLD#", bid=4293.2, ask=4293.5)
        if self.service.mt5 is None:
            self.service._attach_mt5(gateway=mock)
            self.service.pipeline.entry_engine = self.service.entry_engine
            self.service.pipeline.trade_executor = self.service.trade_executor
        else:
            # Use live if connected; otherwise swap to mock for demo
            if not self.service.mt5.is_connected:
                self.service._attach_mt5(gateway=mock)
                self.service.pipeline.entry_engine = self.service.entry_engine
                self.service.pipeline.trade_executor = self.service.trade_executor
                self.service.mt5.connect()
        try:
            if self.service.mt5 and not self.service.mt5.is_connected:
                self.service.mt5.connect()
        except Exception:  # noqa: BLE001
            self.service._attach_mt5(gateway=mock)
            self.service.pipeline.entry_engine = self.service.entry_engine
            self.service.pipeline.trade_executor = self.service.trade_executor
            self.service.mt5.connect()

        from time import time_ns

        sim = TelegramSimulator(self.service.pipeline)
        result = sim.inject(SAMPLE_SELL_XAUUSD, message_id=int(time_ns() % 2_000_000_000) + 1)
        logger.info("GUI simulate => %s", result.status.value)
        self.refresh_status()

    def save_settings_from_dict(self, data: dict[str, Any]) -> None:
        for key in (
            "dry_run",
            "copy_trading_enabled",
            "magic_number",
            "mt5_terminal_path",
            "log_level",
            "symbol_mappings",
        ):
            if key in data and data[key] is not None:
                setattr(self.settings, key, data[key])
        if "entry" in data and isinstance(data["entry"], dict):
            from app.config.settings import EntrySettings

            self.settings.entry = EntrySettings(
                **{**self.settings.entry.model_dump(), **data["entry"]}
            )
        if "risk" in data and isinstance(data["risk"], dict):
            from app.config.settings import RiskSettings

            self.settings.risk = RiskSettings(
                **{**self.settings.risk.model_dump(), **data["risk"]}
            )
        self.settings.save_config_json()
        reset_settings_cache()
        logger.info("Settings saved to %s", self.settings.config_json_path)
        self.refresh_status()

    def inspect_text(self, text: str) -> str:
        return self.inspector.inspect(text).format_report()
