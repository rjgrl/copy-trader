"""Phase 5 — intelligent entry engine tests (mock MT5 only)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config.settings import AppSettings, reset_settings_cache
from app.database.database import Database
from app.database.repositories import SignalRepository
from app.mt5.gateway import MockMT5Gateway
from app.mt5.service import MT5Service
from app.signals.models import SignalStatus
from app.signals.parser import parse_signal
from app.telegram.models import IncomingTelegramMessage
from app.telegram.pipeline import SignalPipeline
from app.telegram.simulator import SAMPLE_SELL_XAUUSD
from app.trading.engine import IntelligentEntryEngine
from app.utils.time import utc_now


@pytest.fixture
def settings(tmp_path: Path) -> AppSettings:
    reset_settings_cache()
    s = AppSettings(
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "logs",
        symbol_mappings={"XAUUSD": "GOLD#", "GOLD": "GOLD#"},
        dry_run=True,
    )
    s.ensure_directories()
    return s


@pytest.fixture
def mock_gw() -> MockMT5Gateway:
    gw = MockMT5Gateway()
    gw.set_tick("GOLD#", bid=4293.2, ask=4293.5)
    return gw


@pytest.fixture
def engine(settings: AppSettings, mock_gw: MockMT5Gateway) -> IntelligentEntryEngine:
    mt5 = MT5Service(settings, gateway=mock_gw)
    mt5.connect()
    return IntelligentEntryEngine(settings, mt5)


class TestIntelligentEntryEngine:
    def test_valid_market_sell(self, engine: IntelligentEntryEngine) -> None:
        signal = parse_signal(SAMPLE_SELL_XAUUSD)
        result = engine.evaluate(signal)
        assert result.ok is True
        assert result.status == SignalStatus.ENTRY_CHECKED
        assert result.mapped_symbol == "GOLD#"
        assert result.decision.action == "market"
        assert result.decision.current_price == pytest.approx(4293.2)  # bid for SELL
        assert result.decision.deviation == pytest.approx(1.7)
        assert result.decision.tp1_reached is False
        assert len(result.would_execute) == 3

    def test_maps_gold_alias(self, engine: IntelligentEntryEngine) -> None:
        signal = parse_signal(
            """SELL GOLD
ENTRY 4291.5
TP 4287.5 / 4283 / 4277
SL 4306.5"""
        )
        result = engine.evaluate(signal)
        assert result.ok is True
        assert result.mapped_symbol == "GOLD#"

    def test_too_far_rejected(self, settings: AppSettings, mock_gw: MockMT5Gateway) -> None:
        mock_gw.set_tick("GOLD#", bid=4298.0, ask=4298.3)
        mt5 = MT5Service(settings, gateway=mock_gw)
        mt5.connect()
        engine = IntelligentEntryEngine(settings, mt5)
        result = engine.evaluate(parse_signal(SAMPLE_SELL_XAUUSD))
        assert result.ok is False
        assert result.status == SignalStatus.REJECTED
        assert result.decision.deviation == pytest.approx(6.5)

    def test_tp1_reached(self, settings: AppSettings, mock_gw: MockMT5Gateway) -> None:
        mock_gw.set_tick("GOLD#", bid=4285.8, ask=4286.1)
        mt5 = MT5Service(settings, gateway=mock_gw)
        mt5.connect()
        engine = IntelligentEntryEngine(settings, mt5)
        result = engine.evaluate(parse_signal(SAMPLE_SELL_XAUUSD))
        assert result.ok is False
        assert result.decision.tp1_reached is True
        assert "TP1 already reached" in result.reason

    def test_spread_too_high(self, settings: AppSettings, mock_gw: MockMT5Gateway) -> None:
        settings.risk.max_spread = 0.1
        mock_gw.set_tick("GOLD#", bid=4293.2, ask=4293.5)  # spread 0.3
        mt5 = MT5Service(settings, gateway=mock_gw)
        mt5.connect()
        engine = IntelligentEntryEngine(settings, mt5)
        result = engine.evaluate(parse_signal(SAMPLE_SELL_XAUUSD))
        assert result.ok is False
        assert "Spread too high" in result.reason

    def test_buy_uses_ask(self, settings: AppSettings, mock_gw: MockMT5Gateway) -> None:
        mock_gw.set_tick("GOLD#", bid=4289.8, ask=4290.1)
        mt5 = MT5Service(settings, gateway=mock_gw)
        mt5.connect()
        engine = IntelligentEntryEngine(settings, mt5)
        signal = parse_signal(
            """BUY XAUUSD 4291.5
TP 4295.5
TP 4298
SL 4285"""
        )
        result = engine.evaluate(signal)
        assert result.ok is True
        assert result.decision.current_price == pytest.approx(4290.1)  # ask
        assert result.decision.deviation == pytest.approx(1.4)  # 4291.5 - 4290.1


class TestPipelineWithEntryEngine:
    def test_pipeline_reaches_entry_checked(
        self, settings: AppSettings, mock_gw: MockMT5Gateway
    ) -> None:
        db = Database(settings.database_path)
        db.initialize()
        mt5 = MT5Service(settings, gateway=mock_gw)
        mt5.connect()
        engine = IntelligentEntryEngine(settings, mt5)
        pipeline = SignalPipeline(
            settings,
            SignalRepository(db),
            entry_engine=engine,
        )
        result = pipeline.process(
            IncomingTelegramMessage(
                chat_id=-1,
                message_id=5001,
                text=SAMPLE_SELL_XAUUSD,
                date=utc_now(),
                source_name="Sim",
            )
        )
        assert result.status == SignalStatus.ENTRY_CHECKED
        assert result.entry_check is not None
        assert result.entry_check.mapped_symbol == "GOLD#"
        row = SignalRepository(db).get_by_telegram_ids(-1, 5001)
        assert row is not None
        assert row.status == SignalStatus.ENTRY_CHECKED.value
        assert row.mapped_mt5_symbol == "GOLD#"
        assert row.actual_execution_price == pytest.approx(4293.2)
        assert row.entry_deviation == pytest.approx(1.7)
