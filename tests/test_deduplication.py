"""Unit tests for duplicate detection and signal hashing."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.database.database import Database
from app.database.models import SignalRecord
from app.database.repositories import SignalRepository
from app.signals.deduplicator import SignalDeduplicator
from app.signals.models import ParsedSignal, SignalDirection, SignalStatus
from app.utils.time import utc_now


@pytest.fixture
def repo(tmp_path: Path) -> SignalRepository:
    db = Database(tmp_path / "test.db")
    db.initialize()
    return SignalRepository(db)


def test_not_duplicate_when_empty(repo: SignalRepository) -> None:
    dedup = SignalDeduplicator(repo)
    assert dedup.is_duplicate(123, 18392) is False


def test_duplicate_after_insert(repo: SignalRepository) -> None:
    signal = SignalRecord(
        id=None,
        telegram_chat_id=123,
        telegram_message_id=18392,
        telegram_message_date=None,
        source_name="Gold VIP",
        raw_message="SELL XAUUSD 4291.5\nTP 4287.5\nSL 4306.5",
        direction="SELL",
        symbol="XAUUSD",
        mapped_mt5_symbol="XAUUSDm",
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
        status=SignalStatus.EXECUTED.value,
        failure_reason=None,
        signal_hash=None,
    )
    repo.insert(signal)
    dedup = SignalDeduplicator(repo)
    assert dedup.is_duplicate(123, 18392) is True
    assert dedup.is_duplicate(123, 18393) is False
    assert dedup.is_duplicate(999, 18392) is False


def test_signal_hash_stable() -> None:
    a = ParsedSignal(
        direction=SignalDirection.SELL,
        symbol="XAUUSD",
        entry=4291.5,
        take_profits=[4287.5, 4283.0],
        stop_loss=4306.5,
    )
    b = ParsedSignal(
        direction=SignalDirection.SELL,
        symbol="XAUUSD",
        entry=4291.5,
        take_profits=[4287.5, 4283.0],
        stop_loss=4306.5,
    )
    assert SignalDeduplicator.compute_hash(a) == SignalDeduplicator.compute_hash(b)
