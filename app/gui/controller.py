"""GUI application controller — bridges services to Qt signals."""

from __future__ import annotations

import logging
from pathlib import Path
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
        self.worker.started.connect(self._auto_connect_telegram)
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
        # Wait for Telegram/MT5 disconnect so the EXE process can actually exit
        try:
            self.worker.run_and_wait(self.service.stop(), timeout=6.0)
        except Exception:  # noqa: BLE001
            logger.warning("Telegram stop during shutdown failed", exc_info=True)
        if self.service.mt5:
            try:
                self.service.mt5.disconnect()
            except Exception:  # noqa: BLE001
                pass
        self.worker.stop()
        try:
            self.db.close()
        except Exception:  # noqa: BLE001
            pass
        root = logging.getLogger()
        for handler in list(root.handlers):
            try:
                handler.close()
            except Exception:  # noqa: BLE001
                pass
            root.removeHandler(handler)

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
            "recent_orders": self.orders.list_recent(100),
            "sources": self.sources.list_all(),
            "enabled_sources": len(self.sources.list_enabled()),
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

    def _auto_connect_telegram(self) -> None:
        """Reconnect Telegram and reload saved groups when a session already exists."""
        if not self.settings.telegram_api_id or not self.settings.telegram_api_hash:
            logger.info("Telegram API credentials missing — skip auto-load of groups")
            return
        session_file = Path(str(self.settings.telegram_session_path) + ".session")
        if not session_file.exists():
            logger.info("No Telegram session file — skip auto-load of groups")
            return
        self.connect_telegram(interactive=False, load_dialogs=True)

    def connect_telegram(self, *, interactive: bool = True, load_dialogs: bool = True) -> None:
        async def _connect():
            await self.service.connect(interactive_auth=False)
            if self.service.client_service.is_authorized:
                return True
            if interactive:
                raise RuntimeError(
                    "Telegram session not authorized. "
                    "Development: run 'python run.py auth'. "
                    "Packaged: put API credentials in "
                    "%LOCALAPPDATA%\\TelegramMT5Copier\\.env then run "
                    "'TelegramMT5Copier_debug.exe auth'."
                )
            return False

        def _done(ok: bool) -> None:
            self._tg_connected = bool(ok)
            if interactive or ok:
                self.auth_finished.emit(bool(ok), "authorized" if ok else "not authorized")
            elif not ok:
                logger.info("Telegram session not authorized — skipping auto-load of groups")
            self.refresh_status()
            if ok and load_dialogs:
                self.load_dialogs()

        self.worker.submit(_connect(), on_done=_done)

    def start_listening(self, selections: list[dict] | None = None) -> None:
        if selections is not None:
            self.save_source_selections(selections)
        enabled = self.sources.list_enabled()
        if not enabled:
            self.error_occurred.emit(
                "No Telegram groups are enabled. "
                "Open the Telegram page, check at least one group, then Start Listening."
            )
            return

        enabled_names = ", ".join(s.name for s in enabled)
        logger.info(
            "Start Listening: %s saved group(s): %s",
            len(enabled),
            enabled_names,
        )

        async def _listen():
            if not self.service.client_service.is_connected:
                await self.service.connect(interactive_auth=False)
            if self.service.mt5 is None or not self.service.mt5.is_connected:
                try:
                    self.service.connect_mt5()
                    self._mt5_connected = True
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Listen without MT5: %s", exc)
            still_enabled = self.sources.list_enabled()
            if not still_enabled:
                raise RuntimeError(
                    "No Telegram groups are enabled. "
                    "Open the Telegram page, check at least one group, then Start Listening."
                )
            await self.service.start_listening()
            return len(still_enabled)

        def _done(count) -> None:
            self._tg_connected = True
            self._listening = True
            self.refresh_status()
            logger.info("Listener running for %s group(s)", count)

        self.worker.submit(_listen(), on_done=_done)

    def save_source_selections(self, selections: list[dict]) -> int:
        """Persist the Telegram page checkbox state in one pass."""
        for item in selections:
            tid = int(item.get("telegram_id") or 0)
            if not tid:
                continue
            self._write_source(
                tid,
                str(item.get("name") or f"chat:{tid}"),
                str(item.get("type") or "unknown"),
                bool(item.get("enabled")),
            )
        enabled = self.sources.list_enabled()
        logger.info(
            "Saved Telegram selections: %s row(s), %s enabled",
            len(selections),
            len(enabled),
        )
        return len(enabled)

    def set_source_enabled(self, telegram_id: int, enabled: bool) -> None:
        self.sources.set_enabled(telegram_id, enabled)
        logger.info("Saved Telegram source %s enabled=%s", telegram_id, enabled)

    def upsert_source(self, telegram_id: int, name: str, source_type: str, enabled: bool) -> None:
        self._write_source(telegram_id, name, source_type, enabled)
        logger.info("Saved Telegram source %s (%s) enabled=%s", name, telegram_id, enabled)

    def _write_source(self, telegram_id: int, name: str, source_type: str, enabled: bool) -> None:
        from app.database.models import TelegramSourceRecord

        existing = next((s for s in self.sources.list_all() if s.telegram_id == telegram_id), None)
        if existing is None:
            self.sources.upsert(
                TelegramSourceRecord(
                    id=None,
                    telegram_id=telegram_id,
                    name=name,
                    source_type=source_type,
                    enabled=enabled,
                    connection_status="configured",
                )
            )
            return
        existing.name = name or existing.name
        existing.source_type = source_type or existing.source_type
        existing.enabled = enabled
        self.sources.upsert(existing)

    def delete_selected_dry_run_orders(self, order_ids: list[int]) -> int:
        deleted = self.orders.delete_by_ids(order_ids)
        logger.info("Deleted %s selected dry-run order(s)", deleted)
        self.refresh_status()
        return deleted

    def delete_all_dry_run_orders(self) -> int:
        deleted = self.orders.delete_dry_run()
        logger.info("Deleted %s dry-run order(s)", deleted)
        self.refresh_status()
        return deleted

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
                    "last_message_id": d.last_message_id,
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
