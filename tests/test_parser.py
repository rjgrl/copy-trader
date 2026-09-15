"""Unit tests for the signal parser."""

from __future__ import annotations

import pytest

from app.signals.models import SignalDirection
from app.signals.parser import DefaultSignalParser, parse_signal


@pytest.fixture
def parser() -> DefaultSignalParser:
    return DefaultSignalParser()


class TestPrimaryFormat:
    def test_sell_xauusd_multi_tp(self, parser: DefaultSignalParser) -> None:
        raw = """SELL XAUUSD 4291.5
TP 4287.5
TP 4283
TP 4277
SL 4306.5"""
        signal = parser.parse(raw)
        assert signal.direction == SignalDirection.SELL
        assert signal.symbol == "XAUUSD"
        assert signal.entry == 4291.5
        assert signal.tp_count == 3
        assert signal.take_profits == [4287.5, 4283.0, 4277.0]
        assert signal.stop_loss == 4306.5

    def test_buy_signal(self, parser: DefaultSignalParser) -> None:
        raw = """BUY EURUSD 1.0850
TP 1.0870
TP 1.0890
SL 1.0820"""
        signal = parser.parse(raw)
        assert signal.direction == SignalDirection.BUY
        assert signal.symbol == "EURUSD"
        assert signal.entry == 1.0850
        assert signal.tp_count == 2
        assert signal.stop_loss == 1.0820

    def test_one_tp(self, parser: DefaultSignalParser) -> None:
        raw = """SELL XAUUSD 4291.5
TP 4287.5
SL 4306.5"""
        signal = parser.parse(raw)
        assert signal.tp_count == 1
        assert signal.tp1 == 4287.5

    def test_two_tps(self, parser: DefaultSignalParser) -> None:
        raw = """BUY XAUUSD 2000
TP 2010
TP 2020
SL 1990"""
        signal = parser.parse(raw)
        assert signal.tp_count == 2

    def test_five_tps(self, parser: DefaultSignalParser) -> None:
        raw = """SELL XAUUSD 4291.5
TP 4287.5
TP 4283
TP 4277
TP 4270
TP 4260
SL 4306.5"""
        signal = parser.parse(raw)
        assert signal.tp_count == 5
        assert signal.additional_tps() == [4270.0, 4260.0]


class TestFormatVariations:
    def test_at_entry_and_numbered_tps(self, parser: DefaultSignalParser) -> None:
        raw = """SELL XAUUSD @ 4291.5
TP1: 4287.5
TP2: 4283
TP3: 4277
SL: 4306.5"""
        signal = parser.parse(raw)
        assert signal.direction == SignalDirection.SELL
        assert signal.symbol == "XAUUSD"
        assert signal.entry == 4291.5
        assert signal.take_profits == [4287.5, 4283.0, 4277.0]
        assert signal.stop_loss == 4306.5

    def test_symbol_before_direction(self, parser: DefaultSignalParser) -> None:
        raw = """XAUUSD SELL 4291.5
TP1 4287.5
TP2 4283
TP3 4277
SL 4306.5"""
        signal = parser.parse(raw)
        assert signal.direction == SignalDirection.SELL
        assert signal.symbol == "XAUUSD"
        assert signal.entry == 4291.5
        assert signal.tp_count == 3

    def test_gold_alias_entry_keyword_inline_tps(self, parser: DefaultSignalParser) -> None:
        raw = """SELL GOLD
ENTRY 4291.5
TP 4287.5 / 4283 / 4277
SL 4306.5"""
        signal = parser.parse(raw)
        assert signal.direction == SignalDirection.SELL
        assert signal.symbol == "XAUUSD"
        assert signal.entry == 4291.5
        assert signal.take_profits == [4287.5, 4283.0, 4277.0]
        assert signal.stop_loss == 4306.5

    def test_extra_spacing(self, parser: DefaultSignalParser) -> None:
        raw = """SELL   XAUUSD    4291.5

TP   4287.5
TP  4283
SL    4306.5"""
        signal = parser.parse(raw)
        assert signal.direction == SignalDirection.SELL
        assert signal.entry == 4291.5
        assert signal.tp_count == 2
        assert signal.stop_loss == 4306.5

    def test_long_short_aliases(self, parser: DefaultSignalParser) -> None:
        buy = parser.parse("LONG XAUUSD 2000\nTP 2010\nSL 1990")
        sell = parser.parse("SHORT XAUUSD 2000\nTP 1990\nSL 2010")
        assert buy.direction == SignalDirection.BUY
        assert sell.direction == SignalDirection.SELL


class TestMalformedAndMissing:
    def test_empty_message(self, parser: DefaultSignalParser) -> None:
        signal = parser.parse("")
        assert signal.direction is None
        assert signal.entry is None

    def test_missing_sl(self, parser: DefaultSignalParser) -> None:
        raw = """SELL XAUUSD 4291.5
TP 4287.5
TP 4283"""
        signal = parser.parse(raw)
        assert signal.direction == SignalDirection.SELL
        assert signal.stop_loss is None
        assert signal.tp_count == 2

    def test_missing_tp(self, parser: DefaultSignalParser) -> None:
        raw = """SELL XAUUSD 4291.5
SL 4306.5"""
        signal = parser.parse(raw)
        assert signal.tp_count == 0
        assert signal.stop_loss == 4306.5

    def test_missing_entry(self, parser: DefaultSignalParser) -> None:
        raw = """SELL XAUUSD
TP 4287.5
SL 4306.5"""
        signal = parser.parse(raw)
        assert signal.entry is None
        assert signal.symbol == "XAUUSD"

    def test_no_trading_content(self, parser: DefaultSignalParser) -> None:
        signal = parser.parse("Good morning traders! Have a great day.")
        assert signal.direction is None
        assert signal.entry is None
        assert signal.tp_count == 0

    def test_cancellation_detected(self, parser: DefaultSignalParser) -> None:
        signal = parser.parse("CANCEL XAUUSD")
        assert signal.is_cancellation is True
        assert "CANCELLATION_SIGNAL_DETECTED" in signal.parse_notes

    def test_cancel_signal_phrase(self, parser: DefaultSignalParser) -> None:
        signal = parser.parse("CANCEL SIGNAL")
        assert signal.is_cancellation is True


class TestConvenienceFunction:
    def test_parse_signal_helper(self) -> None:
        signal = parse_signal("BUY XAUUSD 2000\nTP 2010\nSL 1990")
        assert signal.direction == SignalDirection.BUY
        assert signal.symbol == "XAUUSD"
