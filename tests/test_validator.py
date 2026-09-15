"""Unit tests for structural signal validation."""

from __future__ import annotations

from app.config.settings import ValidationRules
from app.signals.models import ParsedSignal, SignalDirection, SignalStatus
from app.signals.parser import parse_signal
from app.signals.validator import SignalValidator


def test_valid_sell_signal() -> None:
    parsed = parse_signal(
        """SELL XAUUSD 4291.5
TP 4287.5
TP 4283
TP 4277
SL 4306.5"""
    )
    result = SignalValidator().validate(parsed)
    assert result.ok is True
    assert result.status == SignalStatus.VALIDATED


def test_missing_stop_loss_rejected() -> None:
    parsed = parse_signal(
        """SELL XAUUSD 4291.5
TP 4287
TP 4283"""
    )
    result = SignalValidator().validate(parsed)
    assert result.ok is False
    assert result.status == SignalStatus.REJECTED
    assert "Missing Stop Loss" in result.reason


def test_missing_tp_rejected() -> None:
    parsed = parse_signal("SELL XAUUSD 4291.5\nSL 4306.5")
    result = SignalValidator().validate(parsed)
    assert result.ok is False
    assert "Missing Take Profit" in result.reason


def test_missing_entry_rejected() -> None:
    parsed = parse_signal("SELL XAUUSD\nTP 4287.5\nSL 4306.5")
    result = SignalValidator().validate(parsed)
    assert result.ok is False
    assert "Missing Entry Price" in result.reason


def test_sl_wrong_side_buy() -> None:
    signal = ParsedSignal(
        direction=SignalDirection.BUY,
        symbol="XAUUSD",
        entry=2000.0,
        take_profits=[2010.0],
        stop_loss=2015.0,  # wrong side
    )
    result = SignalValidator().validate(signal)
    assert result.ok is False
    assert "SL < Entry" in result.reason


def test_sl_wrong_side_sell() -> None:
    signal = ParsedSignal(
        direction=SignalDirection.SELL,
        symbol="XAUUSD",
        entry=2000.0,
        take_profits=[1990.0],
        stop_loss=1980.0,  # wrong side
    )
    result = SignalValidator().validate(signal)
    assert result.ok is False
    assert "Entry < SL" in result.reason


def test_cancellation_skipped() -> None:
    parsed = parse_signal("CANCEL SIGNAL")
    result = SignalValidator().validate(parsed)
    assert result.ok is False
    assert result.status == SignalStatus.SKIPPED


def test_optional_sl_when_disabled() -> None:
    rules = ValidationRules(require_sl=False)
    parsed = parse_signal("SELL XAUUSD 4291.5\nTP 4287.5")
    result = SignalValidator(rules).validate(parsed)
    assert result.ok is True
