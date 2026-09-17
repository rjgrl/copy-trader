"""Tests for false-positive protection, inspector, math validation, startup safety."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config.settings import AppSettings, reset_settings_cache
from app.database.database import Database
from app.database.models import SignalRecord
from app.database.repositories import SignalRepository
from app.signals.classifier import MessageClassifier, MessageKind
from app.signals.confidence import check_price_relationships
from app.signals.inspector import SignalInspector
from app.signals.models import ParsedSignal, SignalDirection, SignalStatus
from app.signals.validator import SignalValidator
from app.telegram.models import IncomingTelegramMessage
from app.telegram.pipeline import SignalPipeline
from app.telegram.simulator import SAMPLE_SELL_XAUUSD
from app.trading.startup import LiveListeningPoint, StartupSafetyService
from app.utils.time import utc_now


@pytest.fixture
def settings(tmp_path: Path) -> AppSettings:
    reset_settings_cache()
    s = AppSettings(data_dir=tmp_path / "data", log_dir=tmp_path / "logs")
    s.ensure_directories()
    return s


@pytest.fixture
def pipeline(settings: AppSettings) -> SignalPipeline:
    db = Database(settings.database_path)
    db.initialize()
    return SignalPipeline(settings, SignalRepository(db))


class TestMessageClassifier:
    def setup_method(self) -> None:
        self.clf = MessageClassifier()

    def test_valid_structured_signal(self) -> None:
        result = self.clf.classify(SAMPLE_SELL_XAUUSD)
        assert result.kind == MessageKind.EXECUTABLE_CANDIDATE
        assert result.executable_candidate is True

    @pytest.mark.parametrize(
        "text",
        [
            "BUY looks strong",
            "Gold is bullish",
            "Waiting for BUY confirmation",
            "Possible SELL around 4290",
            "BUY if price breaks 4300",
            "Analysis",
            "Market update",
            "News",
            "Hold",
        ],
    )
    def test_analysis_and_chatter(self, text: str) -> None:
        result = self.clf.classify(text)
        assert result.kind in {
            MessageKind.ANALYSIS,
            MessageKind.CHATTER,
        }
        assert result.executable_candidate is False

    @pytest.mark.parametrize(
        "text",
        [
            "TP1 HIT",
            "TP2 reached",
            "Move SL to 4295",
            "SL moved to BE",
            "Close half",
            "Trade closed",
        ],
    )
    def test_trade_updates(self, text: str) -> None:
        result = self.clf.classify(text)
        assert result.kind == MessageKind.TRADE_UPDATE

    def test_buy_alone_ignored(self) -> None:
        assert self.clf.classify("BUY XAUUSD").executable_candidate is False

    def test_cancellation(self) -> None:
        assert self.clf.classify("CANCEL SIGNAL").kind == MessageKind.CANCELLATION


class TestMathValidation:
    def test_buy_requires_sl_lt_entry_lt_tp(self) -> None:
        signal = ParsedSignal(
            direction=SignalDirection.BUY,
            symbol="XAUUSD",
            entry=4291.5,
            take_profits=[4295.0],
            stop_loss=4285.0,
        )
        assert check_price_relationships(signal) == []
        assert SignalValidator().validate(signal).ok is True

    def test_buy_invalid_sl(self) -> None:
        signal = ParsedSignal(
            direction=SignalDirection.BUY,
            symbol="XAUUSD",
            entry=4291.5,
            take_profits=[4295.0],
            stop_loss=4300.0,
        )
        reasons = check_price_relationships(signal)
        assert any("SL below the entry zone" in r or "SL < Entry" in r for r in reasons)

    def test_sell_all_tps_must_be_below_entry(self) -> None:
        signal = ParsedSignal(
            direction=SignalDirection.SELL,
            symbol="XAUUSD",
            entry=4291.5,
            take_profits=[4287.5, 4295.0],  # TP2 wrong side
            stop_loss=4306.5,
        )
        result = SignalValidator().validate(signal)
        assert result.ok is False
        assert any("TP2" in r for r in result.reasons)

    def test_incomplete_buy_rejected(self) -> None:
        raw = "BUY XAUUSD 4291.5\nTP 4295"
        # Pipeline path
        pass  # covered below


class TestPipelineFalsePositives:
    def test_chatter_skipped(self, pipeline: SignalPipeline) -> None:
        msg = IncomingTelegramMessage(
            chat_id=1, message_id=1, text="Gold is looking bearish today.", date=utc_now()
        )
        result = pipeline.process(msg)
        assert result.status == SignalStatus.SKIPPED
        assert result.message_kind in {"chatter", "analysis"}

    def test_tp_hit_skipped(self, pipeline: SignalPipeline) -> None:
        msg = IncomingTelegramMessage(
            chat_id=1, message_id=2, text="TP1 HIT", date=utc_now()
        )
        result = pipeline.process(msg)
        assert result.status == SignalStatus.SKIPPED
        assert result.message_kind == "trade_update"

    def test_missing_sl_rejected(self, pipeline: SignalPipeline) -> None:
        msg = IncomingTelegramMessage(
            chat_id=1,
            message_id=3,
            text="BUY XAUUSD 4291.5\nTP 4295",
            date=utc_now(),
        )
        result = pipeline.process(msg)
        assert result.status == SignalStatus.REJECTED
        assert "Missing Stop Loss" in (result.reason or "")

    def test_valid_still_validates(self, pipeline: SignalPipeline) -> None:
        msg = IncomingTelegramMessage(
            chat_id=1, message_id=4, text=SAMPLE_SELL_XAUUSD, date=utc_now()
        )
        result = pipeline.process(msg)
        assert result.status == SignalStatus.VALIDATED

    def test_historical_skipped(self, pipeline: SignalPipeline) -> None:
        point = LiveListeningPoint(
            established_at=utc_now(),
            session_id="test",
            watermarks={1: 100},
            active=True,
        )
        pipeline.listening_point = point
        msg = IncomingTelegramMessage(
            chat_id=1,
            message_id=50,  # below watermark
            text=SAMPLE_SELL_XAUUSD,
            date=utc_now(),
        )
        result = pipeline.process(msg)
        assert result.status == SignalStatus.SKIPPED
        assert result.reason == "HISTORICAL_SIGNAL_SKIPPED"

    def test_above_watermark_allowed(self, pipeline: SignalPipeline) -> None:
        point = LiveListeningPoint(
            established_at=utc_now(),
            session_id="test",
            watermarks={1: 100},
            active=True,
        )
        pipeline.listening_point = point
        msg = IncomingTelegramMessage(
            chat_id=1,
            message_id=101,
            text=SAMPLE_SELL_XAUUSD,
            date=utc_now(),
        )
        result = pipeline.process(msg)
        assert result.status == SignalStatus.VALIDATED

    def test_inactive_listening_point_blocks_all(self, pipeline: SignalPipeline) -> None:
        point = LiveListeningPoint(
            established_at=utc_now(),
            session_id="test",
            watermarks={},
            active=False,
        )
        pipeline.listening_point = point
        msg = IncomingTelegramMessage(
            chat_id=1, message_id=999, text=SAMPLE_SELL_XAUUSD, date=utc_now()
        )
        result = pipeline.process(msg)
        assert result.status == SignalStatus.SKIPPED
        assert "HISTORICAL" in (result.reason or "")


class TestSignalInspector:
    def test_valid_report(self) -> None:
        result = SignalInspector().inspect(SAMPLE_SELL_XAUUSD)
        assert result.signal_detected is True
        assert result.direction == "SELL"
        assert result.symbol == "XAUUSD"
        assert result.tp_count == 3
        assert result.validation_ok is True
        assert "VALID SIGNAL" in result.summary

    def test_chatter_report(self) -> None:
        result = SignalInspector().inspect("Gold is looking bearish today.")
        assert result.signal_detected is False
        assert "NO EXECUTABLE SIGNAL" in result.summary

    def test_missing_sl_report(self) -> None:
        result = SignalInspector().inspect("BUY XAUUSD 4291.5\nTP 4295")
        assert result.signal_detected is False
        assert any("Stop Loss" in r for r in result.rejection_reasons)


class TestStartupReconciliation:
    def test_executing_marked_requires_review(self, settings: AppSettings) -> None:
        db = Database(settings.database_path)
        db.initialize()
        repo = SignalRepository(db)
        repo.insert(
            SignalRecord(
                id=None,
                telegram_chat_id=-100,
                telegram_message_id=18392,
                telegram_message_date=None,
                source_name="VIP",
                raw_message=SAMPLE_SELL_XAUUSD,
                direction="SELL",
                symbol="XAUUSD",
                mapped_mt5_symbol="XAUUSD",
                entry_price=4291.5,
                tp1=4287.5,
                tp2=None,
                tp3=None,
                additional_tps=None,
                stop_loss=4306.5,
                received_at=utc_now(),
                processed_at=None,
                actual_execution_price=None,
                entry_deviation=None,
                status=SignalStatus.EXECUTING.value,
                failure_reason=None,
                signal_hash=None,
            )
        )
        service = StartupSafetyService(repo)
        report = service.reconcile_incomplete_executions()
        assert report.marked_requires_review == 1
        row = repo.get_by_telegram_ids(-100, 18392)
        assert row is not None
        assert row.status == SignalStatus.EXECUTION_REQUIRES_REVIEW.value
        # Restart must not re-execute
        assert repo.exists(-100, 18392)
