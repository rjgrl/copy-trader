"""Real-world Telegram signal format parser upgrade tests."""

from __future__ import annotations

import pytest

from app.signals.classifier import MessageClassifier, MessageKind
from app.signals.inspector import SignalInspector
from app.signals.models import EntryType, OrderType, SignalDirection
from app.signals.parser import DefaultSignalParser
from app.signals.profiles import ProfileRegistry
from app.signals.validator import SignalValidator


EXAMPLE_1 = """SIGNAL 6 🔼
Gold buy limit 4280 - 4277
SL 4274.00
Tp 4284
Tp 4290
Tp 4300

This is a reference trading plan shared for educational purposes only.
We are not responsible for any financial decisions.
Trade smart not emotional.
"""

EXAMPLE_2 = """Victor B Gold & Forex VIP
Trade Setup #05 - SEPTEMBER 15
XAU/USD SELL 4292 - 4295
Stoploss: 4300
Take Profit: 4287
Take Profit: 4272

Price is retracing into the 4292–4295 resistance zone after a strong bearish move from the highs.
"""


@pytest.fixture
def parser() -> DefaultSignalParser:
    return DefaultSignalParser(range_as="limit")


@pytest.fixture
def inspector() -> SignalInspector:
    return SignalInspector()


class TestRequiredExamples:
    def test_example_1_buy_limit_range(self, parser: DefaultSignalParser) -> None:
        signal = parser.parse(EXAMPLE_1)
        assert signal.direction == SignalDirection.BUY
        assert signal.symbol == "XAUUSD"
        assert signal.order_type == OrderType.BUY_LIMIT
        assert signal.entry_type == EntryType.RANGE
        assert signal.entry_low == 4277.0
        assert signal.entry_high == 4280.0
        assert signal.stop_loss == 4274.0
        assert signal.take_profits == [4284.0, 4290.0, 4300.0]
        assert signal.raw_message == EXAMPLE_1

        result = SignalValidator().validate(signal)
        assert result.ok
        assert SignalInspector().inspect(EXAMPLE_1).summary.startswith("VALID SIGNAL")

    def test_example_2_sell_limit_range(self) -> None:
        registry = ProfileRegistry()
        parser = registry.get_parser_for_profile("victor_b")
        signal = parser.parse(EXAMPLE_2)
        assert signal.direction == SignalDirection.SELL
        assert signal.symbol == "XAUUSD"
        assert signal.entry_type == EntryType.RANGE
        assert signal.entry_low == 4292.0
        assert signal.entry_high == 4295.0
        assert signal.stop_loss == 4300.0
        assert signal.take_profits == [4287.0, 4272.0]
        assert signal.order_type == OrderType.SELL_LIMIT

        result = SignalValidator().validate(signal)
        assert result.ok
        report = SignalInspector(profiles=registry).inspect(EXAMPLE_2, profile_name="victor_b")
        assert report.summary.startswith("VALID SIGNAL")


class TestCoreFormats:
    def test_standard_buy(self, parser: DefaultSignalParser) -> None:
        raw = "BUY XAUUSD 4291.5\nTP 4295\nTP 4300\nSL 4285"
        signal = parser.parse(raw)
        assert signal.direction == SignalDirection.BUY
        assert signal.symbol == "XAUUSD"
        assert signal.entry == 4291.5
        assert signal.entry_type == EntryType.SINGLE
        assert signal.order_type == OrderType.MARKET_BUY
        assert SignalValidator().validate(signal).ok

    def test_standard_sell(self, parser: DefaultSignalParser) -> None:
        raw = "SELL XAUUSD 4291.5\nTP 4287.5\nTP 4283\nSL 4306.5"
        signal = parser.parse(raw)
        assert signal.direction == SignalDirection.SELL
        assert signal.order_type == OrderType.MARKET_SELL
        assert SignalValidator().validate(signal).ok

    def test_buy_limit_range(self, parser: DefaultSignalParser) -> None:
        raw = "XAUUSD BUY LIMIT 4280 - 4277\nSL 4274\nTP 4284\nTP 4290"
        signal = parser.parse(raw)
        assert signal.order_type == OrderType.BUY_LIMIT
        assert signal.entry_low == 4277.0
        assert signal.entry_high == 4280.0

    def test_sell_limit_range(self, parser: DefaultSignalParser) -> None:
        raw = "XAUUSD SELL LIMIT 4295 - 4292\nSL 4300\nTP 4287"
        signal = parser.parse(raw)
        assert signal.order_type == OrderType.SELL_LIMIT
        assert signal.entry_low == 4292.0
        assert signal.entry_high == 4295.0

    def test_xau_slash_usd(self, parser: DefaultSignalParser) -> None:
        raw = "XAU/USD SELL 4292 - 4295\nStoploss: 4300\nTake Profit: 4287"
        signal = parser.parse(raw)
        assert signal.symbol == "XAUUSD"
        assert signal.entry_type == EntryType.RANGE

    def test_gold_alias(self, parser: DefaultSignalParser) -> None:
        raw = "Gold BUY LIMIT 4280 - 4277\nSL 4274\nTp 4284"
        signal = parser.parse(raw)
        assert signal.symbol == "XAUUSD"

    def test_tp_capitalization(self, parser: DefaultSignalParser) -> None:
        raw = "SELL XAUUSD 4291.5\nTp 4287.5\nSL 4306.5"
        signal = parser.parse(raw)
        assert signal.take_profits == [4287.5]

    def test_take_profit_label(self, parser: DefaultSignalParser) -> None:
        raw = "SELL XAUUSD 4291.5\nTake Profit: 4287\nTake Profit: 4272\nSL 4300"
        signal = parser.parse(raw)
        assert signal.take_profits == [4287.0, 4272.0]

    def test_stoploss_label(self, parser: DefaultSignalParser) -> None:
        raw = "BUY XAUUSD 4280\nTP 4290\nStoploss: 4274"
        signal = parser.parse(raw)
        assert signal.stop_loss == 4274.0

    def test_markdown_formatting(self, parser: DefaultSignalParser) -> None:
        raw = "**SELL** `XAUUSD` 4291.5\n*TP* 4287.5\n__SL__ 4306.5"
        signal = parser.parse(raw)
        assert signal.direction == SignalDirection.SELL
        assert signal.symbol == "XAUUSD"
        assert signal.entry == 4291.5
        assert signal.stop_loss == 4306.5

    def test_emoji_heavy(self, parser: DefaultSignalParser) -> None:
        raw = "🔥 SIGNAL 6 🔼\nGold buy limit 4280 - 4277\n❌ SL 4274\n✅ Tp 4284"
        signal = parser.parse(raw)
        assert signal.order_type == OrderType.BUY_LIMIT
        assert signal.entry_low == 4277.0

    def test_disclaimer_ignored(self, parser: DefaultSignalParser) -> None:
        signal = parser.parse(EXAMPLE_1)
        assert signal.stop_loss == 4274.0
        assert signal.tp_count == 3
        assert SignalValidator().validate(signal).ok
        # Disclaimer text must not invent extra TPs / entries
        assert signal.take_profits == [4284.0, 4290.0, 4300.0]

    def test_long_analysis_paragraph(self, parser: DefaultSignalParser) -> None:
        signal = parser.parse(EXAMPLE_2)
        assert signal.direction == SignalDirection.SELL
        assert signal.tp_count == 2
        # Analysis numbers must not become extra TPs
        assert 4290.0 not in signal.take_profits or signal.take_profits == [4287.0, 4272.0]

    def test_multiple_tps(self, parser: DefaultSignalParser) -> None:
        raw = "BUY XAUUSD 2000\nTP 2010\nTP 2020\nTP 2030\nTP 2040\nSL 1990"
        signal = parser.parse(raw)
        assert signal.tp_count == 4

    def test_entry_range_model(self, parser: DefaultSignalParser) -> None:
        raw = "BUY XAUUSD 4280 - 4277\nSL 4274\nTP 4284"
        signal = parser.parse(raw)
        assert signal.entry_type == EntryType.RANGE
        assert signal.entry_low == 4277.0
        assert signal.entry_high == 4280.0
        assert signal.entry_low != signal.entry_high


class TestFalsePositivesAndInvalid:
    def test_bullish_discussion(self) -> None:
        text = "Gold looks strong today, maybe buy around 4290"
        kind = MessageClassifier().classify(text).kind
        assert kind in {MessageKind.ANALYSIS, MessageKind.CHATTER}
        assert not SignalInspector().inspect(text).signal_detected

    def test_buy_if_price_reaches(self) -> None:
        text = "BUY if price reaches 4290"
        result = MessageClassifier().classify(text)
        assert result.kind == MessageKind.ANALYSIS
        assert not SignalInspector().inspect(text).signal_detected

    def test_tp_hit_update(self) -> None:
        text = "TP1 HIT on XAUUSD, move SL to entry"
        assert MessageClassifier().classify(text).kind == MessageKind.TRADE_UPDATE

    def test_sl_modification(self) -> None:
        text = "Move SL to breakeven on gold trade"
        assert MessageClassifier().classify(text).kind == MessageKind.TRADE_UPDATE

    def test_missing_sl(self, parser: DefaultSignalParser) -> None:
        raw = "SELL XAUUSD 4291.5\nTP 4287.5"
        signal = parser.parse(raw)
        result = SignalValidator().validate(signal)
        assert not result.ok
        assert any("Stop Loss" in r for r in result.reasons)
        report = SignalInspector().inspect(raw)
        assert "INVALID SIGNAL" in report.summary
        assert "Missing Stop Loss" in report.summary

    def test_missing_tp(self, parser: DefaultSignalParser) -> None:
        raw = "SELL XAUUSD 4291.5\nSL 4306.5"
        signal = parser.parse(raw)
        result = SignalValidator().validate(signal)
        assert not result.ok
        assert any("Take Profit" in r for r in result.reasons)

    def test_invalid_tp_sl_relationship(self, parser: DefaultSignalParser) -> None:
        raw = "SELL XAUUSD 4292 - 4295\nSL 4300\nTP 4305"
        signal = parser.parse(raw)
        result = SignalValidator().validate(signal)
        assert not result.ok
        assert any("above the entry zone" in r or "not below" in r for r in result.reasons)

    def test_analysis_numbers_not_entry(self, parser: DefaultSignalParser) -> None:
        raw = (
            "XAUUSD SELL 4292 - 4295\n"
            "Stoploss: 4300\n"
            "Take Profit: 4287\n"
            "Price moved from 4290 to 4300 and may retrace to 4280.\n"
        )
        signal = parser.parse(raw)
        assert signal.entry_low == 4292.0
        assert signal.entry_high == 4295.0
        assert signal.take_profits == [4287.0]
        assert signal.stop_loss == 4300.0


class TestInspectorReport:
    def test_valid_report_fields(self, inspector: SignalInspector) -> None:
        report = inspector.inspect(EXAMPLE_1)
        assert report.signal_detected
        assert report.order_type == OrderType.BUY_LIMIT.value
        assert report.entry_type == EntryType.RANGE.value
        assert report.entry_low == 4277.0
        assert report.entry_high == 4280.0
        assert "VALID SIGNAL" in report.format_report()
