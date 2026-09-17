"""Phase 6 — MT5 trade execution tests (mock only, never real order_send to broker)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config.settings import AppSettings, reset_settings_cache
from app.database.database import Database
from app.database.repositories import OrderRepository, SignalRepository
from app.mt5.execution import TRADE_RETCODE_NO_MONEY
from app.mt5.gateway import MockMT5Gateway
from app.mt5.service import MT5Service
from app.signals.models import SignalStatus
from app.telegram.models import IncomingTelegramMessage
from app.telegram.pipeline import SignalPipeline
from app.telegram.simulator import SAMPLE_SELL_XAUUSD
from app.trading.engine import IntelligentEntryEngine
from app.trading.executor import SignalTradeExecutor
from app.utils.time import utc_now


@pytest.fixture
def settings(tmp_path: Path) -> AppSettings:
    reset_settings_cache()
    s = AppSettings(
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "logs",
        symbol_mappings={"XAUUSD": "GOLD#", "GOLD": "GOLD#"},
        dry_run=True,
        copy_trading_enabled=False,
        magic_number=123456,
    )
    s.ensure_directories()
    return s


@pytest.fixture
def mock_gw() -> MockMT5Gateway:
    gw = MockMT5Gateway()
    gw.set_tick("GOLD#", bid=4293.2, ask=4293.5)
    return gw


@pytest.fixture
def wired(settings: AppSettings, mock_gw: MockMT5Gateway, tmp_path: Path):
    db = Database(settings.database_path)
    db.initialize()
    mt5 = MT5Service(settings, gateway=mock_gw)
    mt5.connect()
    entry = IntelligentEntryEngine(settings, mt5)
    orders = OrderRepository(db)
    trade = SignalTradeExecutor(settings, mt5, orders)
    pipeline = SignalPipeline(
        settings,
        SignalRepository(db),
        entry_engine=entry,
        trade_executor=trade,
    )
    return settings, mock_gw, mt5, pipeline, orders, db


class TestDryRunExecution:
    def test_dry_run_executes_three_orders_without_order_send(
        self, wired
    ) -> None:
        settings, mock_gw, mt5, pipeline, orders, db = wired
        result = pipeline.process(
            IncomingTelegramMessage(
                chat_id=-10,
                message_id=6001,
                text=SAMPLE_SELL_XAUUSD,
                date=utc_now(),
                source_name="Sim",
            )
        )
        assert result.status == SignalStatus.EXECUTED
        assert result.execution is not None
        assert result.execution.dry_run is True
        assert result.execution.success_count == 3
        assert mock_gw.orders_sent == []  # dry_run must not call order_send
        saved = orders.list_for_signal(result.db_id)
        assert len(saved) == 3
        assert all(o.dry_run for o in saved)
        assert all(o.status == "DRY_RUN" for o in saved)
        assert saved[0].take_profit == 4287.5
        assert saved[1].take_profit == 4283.0
        assert saved[2].take_profit == 4277.0
        assert saved[0].comment == "TG-XAUUSD-6001-TP1"
        assert saved[0].stop_loss == 4306.5

    def test_delete_dry_run_orders_keeps_live(self, wired) -> None:
        settings, mock_gw, mt5, pipeline, orders, db = wired
        result = pipeline.process(
            IncomingTelegramMessage(
                chat_id=-10,
                message_id=6001,
                text=SAMPLE_SELL_XAUUSD,
                date=utc_now(),
                source_name="Sim",
            )
        )
        dry_ids = [o.id for o in orders.list_recent(20) if o.id is not None]
        assert len(dry_ids) == 3
        from app.database.models import OrderRecord

        live_id = orders.insert(
            OrderRecord(
                id=None,
                signal_id=int(result.db_id),
                mt5_ticket=999,
                symbol="GOLD#",
                direction="SELL",
                volume=0.01,
                entry_price=4293.2,
                stop_loss=4306.5,
                take_profit=4287.5,
                tp_index=9,
                status="FILLED",
                retcode=10009,
                retcode_description="DONE",
                comment="LIVE",
                created_at=utc_now(),
                updated_at=utc_now(),
                dry_run=False,
            )
        )
        removed = orders.delete_by_ids(dry_ids[:1])
        assert removed == 1
        remaining_dry = [o for o in orders.list_recent(20) if o.dry_run]
        assert len(remaining_dry) == 2
        cleared = orders.delete_dry_run()
        assert cleared == 2
        leftover = orders.list_recent(20)
        assert len(leftover) == 1
        assert leftover[0].id == live_id
        assert leftover[0].dry_run is False

    def test_far_from_entry_still_places_sell(self, wired) -> None:
        settings, mock_gw, mt5, pipeline, orders, db = wired
        mock_gw.set_tick("GOLD#", bid=4298.0, ask=4298.3)
        result = pipeline.process(
            IncomingTelegramMessage(
                chat_id=-10,
                message_id=6010,
                text=SAMPLE_SELL_XAUUSD,
                date=utc_now(),
                source_name="Sim",
            )
        )
        assert result.status == SignalStatus.EXECUTED
        assert result.execution is not None
        assert result.execution.success_count == 3
        saved = orders.list_for_signal(result.db_id)
        assert len(saved) == 3
        assert all(o.direction == "SELL" for o in saved)

    def test_past_all_tps_still_places_one_market_order(self, wired) -> None:
        settings, mock_gw, mt5, pipeline, orders, db = wired
        mock_gw.set_tick("GOLD#", bid=4270.0, ask=4270.3)
        result = pipeline.process(
            IncomingTelegramMessage(
                chat_id=-10,
                message_id=6011,
                text=SAMPLE_SELL_XAUUSD,
                date=utc_now(),
                source_name="Sim",
            )
        )
        assert result.status == SignalStatus.EXECUTED
        assert result.execution is not None
        assert result.execution.success_count == 1
        saved = orders.list_for_signal(result.db_id)
        assert len(saved) == 1
        assert saved[0].direction == "SELL"
        assert saved[0].take_profit is None
        assert saved[0].stop_loss == 4306.5


class TestLiveExecutionMock:
    def test_live_calls_order_send(self, settings: AppSettings, mock_gw: MockMT5Gateway) -> None:
        settings.dry_run = False
        settings.copy_trading_enabled = True
        db = Database(settings.database_path)
        db.initialize()
        mt5 = MT5Service(settings, gateway=mock_gw)
        mt5.connect()
        pipeline = SignalPipeline(
            settings,
            SignalRepository(db),
            entry_engine=IntelligentEntryEngine(settings, mt5),
            trade_executor=SignalTradeExecutor(settings, mt5, OrderRepository(db)),
        )
        result = pipeline.process(
            IncomingTelegramMessage(
                chat_id=-10,
                message_id=6002,
                text=SAMPLE_SELL_XAUUSD,
                date=utc_now(),
            )
        )
        assert result.status == SignalStatus.EXECUTED
        assert len(mock_gw.orders_sent) == 3
        assert all(r["magic"] == 123456 for r in mock_gw.orders_sent)
        assert mock_gw.orders_sent[0]["type"] == 1  # SELL
        assert mock_gw.orders_sent[0]["sl"] == 4306.5
        assert mock_gw.orders_sent[0]["tp"] == 4287.5
        assert mock_gw.orders_sent[0]["symbol"] == "GOLD#"

    def test_partial_execution(self, settings: AppSettings, mock_gw: MockMT5Gateway) -> None:
        settings.dry_run = False
        settings.copy_trading_enabled = True
        # TP1 ok, TP2 ok, TP3 fail
        mock_gw.fail_retcodes = [None, None, TRADE_RETCODE_NO_MONEY]
        db = Database(settings.database_path)
        db.initialize()
        mt5 = MT5Service(settings, gateway=mock_gw)
        mt5.connect()
        pipeline = SignalPipeline(
            settings,
            SignalRepository(db),
            entry_engine=IntelligentEntryEngine(settings, mt5),
            trade_executor=SignalTradeExecutor(settings, mt5, OrderRepository(db)),
        )
        result = pipeline.process(
            IncomingTelegramMessage(
                chat_id=-10,
                message_id=6003,
                text=SAMPLE_SELL_XAUUSD,
                date=utc_now(),
            )
        )
        assert result.status == SignalStatus.PARTIALLY_EXECUTED
        assert result.execution is not None
        assert result.execution.success_count == 2
        assert result.execution.fail_count == 1
        failed = [o for o in result.execution.outcomes if not o.result.ok][0]
        assert failed.tp_index == 3
        assert failed.result.retcode == TRADE_RETCODE_NO_MONEY

    def test_copy_trading_off_blocks_live(
        self, settings: AppSettings, mock_gw: MockMT5Gateway
    ) -> None:
        settings.dry_run = False
        settings.copy_trading_enabled = False
        db = Database(settings.database_path)
        db.initialize()
        mt5 = MT5Service(settings, gateway=mock_gw)
        mt5.connect()
        pipeline = SignalPipeline(
            settings,
            SignalRepository(db),
            entry_engine=IntelligentEntryEngine(settings, mt5),
            trade_executor=SignalTradeExecutor(settings, mt5, OrderRepository(db)),
        )
        result = pipeline.process(
            IncomingTelegramMessage(
                chat_id=-10,
                message_id=6004,
                text=SAMPLE_SELL_XAUUSD,
                date=utc_now(),
            )
        )
        assert result.status == SignalStatus.ENTRY_CHECKED
        assert mock_gw.orders_sent == []


class TestTradeExecutorUnit:
    def test_executor_with_real_signal_row(
        self, settings: AppSettings, mock_gw: MockMT5Gateway
    ) -> None:
        db = Database(settings.database_path)
        db.initialize()
        mt5 = MT5Service(settings, gateway=mock_gw)
        mt5.connect()
        pipeline = SignalPipeline(
            settings,
            SignalRepository(db),
            entry_engine=IntelligentEntryEngine(settings, mt5),
            trade_executor=SignalTradeExecutor(settings, mt5, OrderRepository(db)),
        )
        result = pipeline.process(
            IncomingTelegramMessage(
                chat_id=-99,
                message_id=18392,
                text=SAMPLE_SELL_XAUUSD,
                date=utc_now(),
            )
        )
        assert result.status == SignalStatus.EXECUTED
        assert result.execution is not None
        comments = [o.result.comment for o in result.execution.outcomes]
        assert comments[0].startswith("TG-XAUUSD-18392-TP1")
