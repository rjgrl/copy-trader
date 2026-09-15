"""Unit tests for intelligent entry validation."""

from __future__ import annotations

import pytest

from app.config.settings import EntrySettings, RiskSettings
from app.signals.models import ParsedSignal, SignalDirection
from app.trading.entry import EntryValidator, compute_entry_deviation, is_tp1_reached


def _sell_signal(
    entry: float = 4291.5,
    tp1: float = 4287.5,
    sl: float = 4306.5,
) -> ParsedSignal:
    return ParsedSignal(
        direction=SignalDirection.SELL,
        symbol="XAUUSD",
        entry=entry,
        take_profits=[tp1, 4283.0, 4277.0],
        stop_loss=sl,
    )


def _buy_signal(
    entry: float = 4291.5,
    tp1: float = 4295.5,
    sl: float = 4285.0,
) -> ParsedSignal:
    return ParsedSignal(
        direction=SignalDirection.BUY,
        symbol="XAUUSD",
        entry=entry,
        take_profits=[tp1],
        stop_loss=sl,
    )


class TestSellEntry:
    def test_valid_market_within_deviation(self) -> None:
        """SELL entry 4291.5, current 4293.2, max 3.0 → VALID MARKET."""
        validator = EntryValidator(EntrySettings(max_entry_deviation=3.0))
        decision = validator.evaluate(_sell_signal(), current_price=4293.2)
        assert decision.ok is True
        assert decision.action == "market"
        assert decision.deviation == pytest.approx(1.7)
        assert decision.tp1_reached is False

    def test_too_far_rejected(self) -> None:
        """SELL entry 4291.5, current 4298.0, max 3.0 → REJECTED."""
        validator = EntryValidator(EntrySettings(max_entry_deviation=3.0))
        decision = validator.evaluate(_sell_signal(), current_price=4298.0)
        assert decision.ok is False
        assert decision.action == "reject"
        assert decision.deviation == pytest.approx(6.5)

    def test_tp1_already_reached(self) -> None:
        """SELL TP1 4287.5, current 4285.8 → REJECTED (TP1 reached)."""
        validator = EntryValidator(EntrySettings(max_entry_deviation=3.0))
        decision = validator.evaluate(_sell_signal(), current_price=4285.8)
        assert decision.ok is False
        assert decision.tp1_reached is True
        assert "TP1 already reached" in decision.reason


class TestBuyEntry:
    def test_valid_market_within_deviation(self) -> None:
        """BUY entry 4291.5, current 4289.8, max 3.0 → VALID MARKET."""
        validator = EntryValidator(EntrySettings(max_entry_deviation=3.0))
        decision = validator.evaluate(
            _buy_signal(entry=4291.5, tp1=4295.5),
            current_price=4289.8,
        )
        assert decision.ok is True
        assert decision.action == "market"
        assert decision.deviation == pytest.approx(1.7)

    def test_tp1_already_reached(self) -> None:
        """BUY TP1 4295.5, current 4297.0 → REJECTED."""
        validator = EntryValidator(EntrySettings(max_entry_deviation=10.0))
        decision = validator.evaluate(
            _buy_signal(entry=4291.5, tp1=4295.5),
            current_price=4297.0,
        )
        assert decision.ok is False
        assert decision.tp1_reached is True


class TestHelpers:
    def test_sell_deviation_favorable_is_zero(self) -> None:
        assert compute_entry_deviation(SignalDirection.SELL, 4291.5, 4290.0) == 0.0

    def test_buy_deviation_favorable_is_zero(self) -> None:
        assert compute_entry_deviation(SignalDirection.BUY, 4291.5, 4292.0) == 0.0

    def test_tp1_helpers(self) -> None:
        assert is_tp1_reached(SignalDirection.SELL, 4287.5, 4285.8) is True
        assert is_tp1_reached(SignalDirection.SELL, 4287.5, 4290.0) is False
        assert is_tp1_reached(SignalDirection.BUY, 4295.5, 4297.0) is True
        assert is_tp1_reached(SignalDirection.BUY, 4295.5, 4293.0) is False


class TestSpreadAndSlDeviation:
    def test_spread_too_high(self) -> None:
        validator = EntryValidator(
            EntrySettings(max_entry_deviation=3.0),
            RiskSettings(max_spread=1.0),
        )
        decision = validator.evaluate(
            _sell_signal(),
            current_price=4293.2,
            spread=2.5,
        )
        assert decision.ok is False
        assert "Spread too high" in decision.reason

    def test_sl_percent_deviation_mode(self) -> None:
        settings = EntrySettings(
            max_entry_deviation=3.0,
            use_sl_based_deviation=True,
            entry_deviation_mode="sl_percent",
            max_sl_distance_percent=15.0,
        )
        validator = EntryValidator(settings)
        decision = validator.evaluate(_sell_signal(), current_price=4293.2)
        assert decision.ok is True
        assert decision.max_allowed_deviation == pytest.approx(2.25)

    def test_stricter_mode_uses_min(self) -> None:
        settings = EntrySettings(
            max_entry_deviation=1.0,
            entry_deviation_mode="stricter",
            max_sl_distance_percent=15.0,
        )
        validator = EntryValidator(settings)
        decision = validator.evaluate(_sell_signal(), current_price=4293.2)
        assert decision.ok is False
