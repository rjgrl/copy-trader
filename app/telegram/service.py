"""Telegram service facade — safe startup sequence and subsystem wiring."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.database.repositories import OrderRepository, SignalRepository, TelegramSourceRepository
from app.mt5.gateway import MT5Gateway
from app.mt5.service import MT5Service
from app.telegram.client import TelegramClientService
from app.telegram.listener import TelegramListener
from app.telegram.pipeline import KillSwitch, PipelineResult, SignalPipeline
from app.telegram.simulator import TelegramSimulator
from app.telegram.sources import TelegramSourceManager
from app.trading.engine import IntelligentEntryEngine
from app.trading.executor import SignalTradeExecutor
from app.trading.startup import ReconciliationReport, StartupSafetyService

if TYPE_CHECKING:
    from app.config.settings import AppSettings
    from app.database.database import Database

logger = logging.getLogger(__name__)


class TelegramService:
    """High-level Telegram subsystem used by CLI and (later) the GUI."""

    def __init__(
        self,
        settings: AppSettings,
        db: Database,
        *,
        mt5_gateway: MT5Gateway | None = None,
        attach_mt5: bool = False,
    ) -> None:
        self.settings = settings
        self.db = db
        self.kill_switch = KillSwitch()
        self.client_service = TelegramClientService(settings)
        self.source_repo = TelegramSourceRepository(db)
        self.signal_repo = SignalRepository(db)
        self.order_repo = OrderRepository(db)
        self.startup = StartupSafetyService(
            self.signal_repo,
            self.order_repo,
            magic_number=settings.magic_number,
        )
        self.sources = TelegramSourceManager(self.client_service, self.source_repo)

        self.mt5: MT5Service | None = None
        self.entry_engine: IntelligentEntryEngine | None = None
        self.trade_executor: SignalTradeExecutor | None = None
        if attach_mt5 or mt5_gateway is not None:
            self._attach_mt5(gateway=mt5_gateway)

        self.pipeline = SignalPipeline(
            settings,
            self.signal_repo,
            source_repo=self.source_repo,
            listening_point=None,
            entry_engine=self.entry_engine,
            trade_executor=self.trade_executor,
        )
        self.simulator = TelegramSimulator(self.pipeline)
        self.listener = TelegramListener(
            self.client_service,
            self.sources,
            on_message=self._on_new_message,
            on_edit=self._on_edit,
            on_delete=self._on_delete,
            listening_point=None,
        )
        self.last_result: PipelineResult | None = None
        self.last_reconciliation: ReconciliationReport | None = None

    def _attach_mt5(self, gateway: MT5Gateway | None = None) -> None:
        self.mt5 = MT5Service(self.settings, gateway=gateway)
        self.entry_engine = IntelligentEntryEngine(self.settings, self.mt5)
        self.trade_executor = SignalTradeExecutor(
            self.settings, self.mt5, self.order_repo
        )

    async def _on_new_message(self, message) -> None:
        self.pipeline.kill_switch_active = self.kill_switch.active
        if self.kill_switch.active:
            logger.warning(
                "Kill switch active — execution blocked for msg=%s",
                message.message_id,
            )
        self.last_result = await self.pipeline.handle_message(message)
        if self.last_result.status.value in {
            "VALIDATED",
            "ENTRY_CHECKED",
            "EXECUTED",
            "PARTIALLY_EXECUTED",
        }:
            self.sources.touch_last_message(
                message.chat_id,
                message.message_id,
                signal=True,
            )

    async def _on_edit(self, message) -> None:
        self.last_result = await self.pipeline.handle_edit(message)

    async def _on_delete(self, message) -> None:
        self.last_result = await self.pipeline.handle_delete(message)

    async def connect(self, *, interactive_auth: bool = False) -> None:
        await self.client_service.connect(interactive_auth=interactive_auth)

    def connect_mt5(self, *, path: str | None = None) -> None:
        if self.mt5 is None:
            self._attach_mt5()
            self.pipeline.entry_engine = self.entry_engine
            self.pipeline.trade_executor = self.trade_executor
        assert self.mt5 is not None
        self.mt5.connect(path=path)

    def restore_and_reconcile(self) -> ReconciliationReport:
        self.last_reconciliation = self.startup.reconcile_incomplete_executions()
        return self.last_reconciliation

    async def start_listening(self) -> None:
        if not self.client_service.is_connected:
            raise RuntimeError("Connect Telegram before starting the listener")

        self.restore_and_reconcile()

        if self.mt5 is None:
            try:
                self.connect_mt5()
            except Exception as exc:
                logger.warning(
                    "MT5 not available at listen start — signals will stop at VALIDATED: %s",
                    exc,
                )

        point = self.startup.create_listening_point()
        self.pipeline.listening_point = point
        self.listener.listening_point = point

        await self.listener.establish_watermarks()
        self.startup.activate_listening_point()
        self.listener.start()
        logger.info(
            "Safe startup complete — waiting for NEW signals only (session=%s)",
            point.session_id,
        )

    async def stop(self) -> None:
        self.listener.stop()
        await self.client_service.disconnect()
        if self.mt5 and self.mt5.is_connected:
            self.mt5.disconnect()
