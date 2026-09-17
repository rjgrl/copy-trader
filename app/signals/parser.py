"""Extensible trading signal parser.

Supports real-world Telegram formats: ranges, limit orders, aliases,
markdown/emoji noise, and long analysis/disclaimer tails.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from typing import Protocol

from app.signals.models import (
    EntryType,
    OrderType,
    ParsedSignal,
    SignalDirection,
)
from app.signals.normalizer import (
    extract_floats,
    normalize_symbol,
    parse_float,
    prepare_message_for_parse,
)

logger = logging.getLogger(__name__)

CANCEL_PATTERN = re.compile(
    r"\b(CANCEL(?:\s+SIGNAL)?|CLOSE\s+ALL|DELETE\s+SIGNAL)\b",
    re.IGNORECASE,
)

DIRECTION_PATTERN = re.compile(r"\b(BUY|SELL|LONG|SHORT)\b", re.IGNORECASE)

SYMBOL_TOKEN = r"(?:XAUUSD|XAGUSD|EURUSD|GBPUSD|BTCUSD|NAS100|US30|GOLD|SILVER|XAU|XAG|[A-Za-z]{3,12})"

PRICE = r"[-+]?\d[\d.,]*"

# Explicit limit/stop + optional range or single
LIMIT_RANGE_PATTERNS: list[re.Pattern[str]] = [
    # Gold BUY LIMIT 4280 - 4277  |  XAUUSD SELL LIMIT 4295-4292
    re.compile(
        rf"\b(?P<symbol>{SYMBOL_TOKEN})\s+"
        rf"(?P<direction>BUY|SELL|LONG|SHORT)\s+"
        rf"(?P<kind>LIMIT|STOP)\s+"
        rf"(?P<a>{PRICE})\s*-\s*(?P<b>{PRICE})",
        re.IGNORECASE,
    ),
    # BUY LIMIT GOLD 4280 - 4277
    re.compile(
        rf"\b(?P<direction>BUY|SELL|LONG|SHORT)\s+"
        rf"(?P<kind>LIMIT|STOP)\s+"
        rf"(?P<symbol>{SYMBOL_TOKEN})\s+"
        rf"(?P<a>{PRICE})\s*-\s*(?P<b>{PRICE})",
        re.IGNORECASE,
    ),
    # BUY LIMIT 4280 - 4277 GOLD (rare)
    re.compile(
        rf"\b(?P<direction>BUY|SELL|LONG|SHORT)\s+"
        rf"(?P<kind>LIMIT|STOP)\s+"
        rf"(?P<a>{PRICE})\s*-\s*(?P<b>{PRICE})",
        re.IGNORECASE,
    ),
]

# Implicit range (no LIMIT keyword): XAUUSD SELL 4292 - 4295
IMPLICIT_RANGE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(
        rf"\b(?P<symbol>{SYMBOL_TOKEN})\s+"
        rf"(?P<direction>BUY|SELL|LONG|SHORT)\s+"
        rf"(?P<a>{PRICE})\s*-\s*(?P<b>{PRICE})",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?P<direction>BUY|SELL|LONG|SHORT)\s+"
        rf"(?P<symbol>{SYMBOL_TOKEN})\s+"
        rf"(?P<a>{PRICE})\s*-\s*(?P<b>{PRICE})",
        re.IGNORECASE,
    ),
]

# Single-entry headers
HEADER_PATTERNS: list[re.Pattern[str]] = [
    re.compile(
        rf"\b(?P<direction>BUY|SELL|LONG|SHORT)\s+"
        rf"(?P<symbol>{SYMBOL_TOKEN})\s+"
        rf"(?:(?P<kind>LIMIT|STOP)\s+)?"
        rf"(?:@\s*)?(?P<entry>{PRICE})",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?P<symbol>{SYMBOL_TOKEN})\s+"
        rf"(?P<direction>BUY|SELL|LONG|SHORT)\s+"
        rf"(?:(?P<kind>LIMIT|STOP)\s+)?"
        rf"(?:@\s*)?(?P<entry>{PRICE})",
        re.IGNORECASE,
    ),
    # Direction + symbol without price (ENTRY line may follow)
    re.compile(
        rf"\b(?P<direction>BUY|SELL|LONG|SHORT)\s+(?P<symbol>{SYMBOL_TOKEN})\b",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?P<symbol>{SYMBOL_TOKEN})\s+(?P<direction>BUY|SELL|LONG|SHORT)\b",
        re.IGNORECASE,
    ),
]

ENTRY_LINE = re.compile(
    rf"\b(?:ENTRY|ENTER|PRICE|OPEN)\s*[:=]?\s*(?:@\s*)?(?P<entry>{PRICE})"
    rf"(?:\s*-\s*(?P<entry2>{PRICE}))?",
    re.IGNORECASE,
)

TP_LINE = re.compile(
    r"\b(?:TP|TAKE\s*PROFIT|TAKEPROFIT|TARGET)(?P<idx>\d{1,2})?\b\s*[:=]?\s*"
    r"(?P<body>.+)",
    re.IGNORECASE,
)

SL_LINE = re.compile(
    rf"\b(?:SL|S\.?L\.?|STOP\s*LOSS|STOPLOSS|STOP)\s*[:=]?\s*(?P<sl>{PRICE})",
    re.IGNORECASE,
)

TP_SPLIT = re.compile(r"[/,|;]|-\s+(?=\d)")

HEADER_NOISE = re.compile(
    r"(?i)\b(SIGNAL|SETUP|TRADE\s+SETUP|VIP\s+SIGNAL|GOLD\s+SIGNAL)\s*#?\s*\d+\b"
)


class SignalFormatHandler(Protocol):
    name: str

    def try_parse(self, text: str) -> ParsedSignal | None: ...


ParseHandler = Callable[[str], ParsedSignal | None]


def _to_direction(raw: str) -> SignalDirection:
    upper = raw.strip().upper()
    if upper in {"BUY", "LONG"}:
        return SignalDirection.BUY
    return SignalDirection.SELL


def _order_from_kind(
    direction: SignalDirection,
    kind: str | None,
    *,
    is_range: bool,
    range_as: str,
) -> OrderType:
    k = (kind or "").upper()
    if k == "LIMIT":
        return OrderType.BUY_LIMIT if direction == SignalDirection.BUY else OrderType.SELL_LIMIT
    if k == "STOP":
        return OrderType.BUY_STOP if direction == SignalDirection.BUY else OrderType.SELL_STOP
    if is_range:
        mode = (range_as or "limit").lower()
        if mode == "market":
            return (
                OrderType.MARKET_BUY
                if direction == SignalDirection.BUY
                else OrderType.MARKET_SELL
            )
        if mode == "entry_zone":
            return OrderType.ENTRY_ZONE
        # default: limit
        return OrderType.BUY_LIMIT if direction == SignalDirection.BUY else OrderType.SELL_LIMIT
    return OrderType.MARKET_BUY if direction == SignalDirection.BUY else OrderType.MARKET_SELL


class DefaultSignalParser:
    """Primary multi-format signal parser with range/limit support."""

    def __init__(
        self,
        extra_handlers: list[ParseHandler] | None = None,
        *,
        range_as: str = "limit",
        parser_name: str = "standard",
        profile_name: str | None = None,
    ) -> None:
        self._extra_handlers: list[ParseHandler] = list(extra_handlers or [])
        self.range_as = range_as
        self.parser_name = parser_name
        self.profile_name = profile_name

    def register_handler(self, handler: ParseHandler) -> None:
        self._extra_handlers.append(handler)

    def parse(self, raw_message: str) -> ParsedSignal:
        text, norm_notes = prepare_message_for_parse(raw_message or "")
        ignored = [n for n in norm_notes if n.startswith(("Stripped", "Removed", "Ignored"))]

        if not text:
            return ParsedSignal(
                raw_message=raw_message or "",
                normalized_message="",
                parse_notes=norm_notes or ["Empty message"],
                ignored_categories=ignored,
                parser_name=self.parser_name,
                provider_profile=self.profile_name,
            )

        if CANCEL_PATTERN.search(text):
            return ParsedSignal(
                raw_message=raw_message or "",
                normalized_message=text,
                is_cancellation=True,
                parse_notes=norm_notes + ["CANCELLATION_SIGNAL_DETECTED"],
                ignored_categories=ignored,
                parser_name=self.parser_name,
                provider_profile=self.profile_name,
            )

        for handler in self._extra_handlers:
            try:
                result = handler(text)
                if result is not None:
                    result.raw_message = raw_message or ""
                    result.normalized_message = text
                    result.parser_name = self.parser_name
                    result.provider_profile = self.profile_name
                    return result
            except Exception as exc:  # noqa: BLE001
                logger.warning("Extra parse handler failed: %s", exc)

        return self._parse_default(text, raw_message or "", norm_notes, ignored)

    def _parse_default(
        self,
        text: str,
        raw_message: str,
        norm_notes: list[str],
        ignored: list[str],
    ) -> ParsedSignal:
        notes = list(norm_notes)
        if HEADER_NOISE.search(text):
            notes.append("Ignored signal/setup header numbering")
            ignored.append("header_numbering")

        direction: SignalDirection | None = None
        symbol: str | None = None
        entry: float | None = None
        entry_low: float | None = None
        entry_high: float | None = None
        entry_type = EntryType.SINGLE
        order_type: OrderType | None = None
        kind: str | None = None

        # 1) Explicit LIMIT/STOP ranges
        for pattern in LIMIT_RANGE_PATTERNS:
            match = pattern.search(text)
            if not match:
                continue
            direction = _to_direction(match.group("direction"))
            sym = match.groupdict().get("symbol")
            if sym:
                symbol = normalize_symbol(sym)
            kind = match.group("kind")
            a = parse_float(match.group("a"))
            b = parse_float(match.group("b"))
            if a is not None and b is not None:
                entry_low, entry_high = min(a, b), max(a, b)
                entry_type = EntryType.RANGE
                order_type = _order_from_kind(
                    direction, kind, is_range=True, range_as=self.range_as
                )
                notes.append(f"Explicit {kind.upper()} range {entry_low}-{entry_high}")
            break

        # 2) Implicit ranges (provider profile decides LIMIT vs zone vs market)
        if entry_low is None:
            for pattern in IMPLICIT_RANGE_PATTERNS:
                match = pattern.search(text)
                if not match:
                    continue
                direction = _to_direction(match.group("direction"))
                symbol = normalize_symbol(match.group("symbol"))
                a = parse_float(match.group("a"))
                b = parse_float(match.group("b"))
                if a is not None and b is not None:
                    entry_low, entry_high = min(a, b), max(a, b)
                    entry_type = EntryType.RANGE
                    order_type = _order_from_kind(
                        direction, None, is_range=True, range_as=self.range_as
                    )
                    notes.append(
                        f"Implicit entry range {entry_low}-{entry_high} "
                        f"(range_as={self.range_as} → {order_type.value})"
                    )
                break

        # 3) Single-entry headers
        if entry_low is None and entry is None:
            for pattern in HEADER_PATTERNS:
                match = pattern.search(text)
                if not match:
                    continue
                direction = _to_direction(match.group("direction"))
                symbol = normalize_symbol(match.group("symbol"))
                kind = match.groupdict().get("kind")
                entry_raw = match.groupdict().get("entry")
                if entry_raw:
                    entry = parse_float(entry_raw)
                order_type = _order_from_kind(
                    direction, kind, is_range=False, range_as=self.range_as
                )
                notes.append("Header matched (single/partial)")
                break

        if direction is None:
            dir_match = DIRECTION_PATTERN.search(text)
            if dir_match:
                direction = _to_direction(dir_match.group(1))
                notes.append("Direction found without full header")

        # ENTRY line (single or range)
        entry_match = ENTRY_LINE.search(text)
        if entry_match:
            e1 = parse_float(entry_match.group("entry"))
            e2 = parse_float(entry_match.group("entry2")) if entry_match.group("entry2") else None
            if e1 is not None and e2 is not None:
                entry_low, entry_high = min(e1, e2), max(e1, e2)
                entry_type = EntryType.RANGE
                entry = None
                if direction and order_type is None:
                    order_type = _order_from_kind(
                        direction, None, is_range=True, range_as=self.range_as
                    )
                notes.append("Entry range from ENTRY line")
            elif e1 is not None:
                entry = e1
                notes.append("Entry from ENTRY line")

        take_profits = self._extract_take_profits(text)
        if take_profits:
            notes.append(f"Found {len(take_profits)} TP(s)")

        stop_loss: float | None = None
        sl_match = SL_LINE.search(text)
        if sl_match:
            stop_loss = parse_float(sl_match.group("sl"))
            notes.append("Stop loss found")

        if symbol is None:
            for alias in ("XAUUSD", "GOLD", "EURUSD", "GBPUSD", "BTCUSD", "NAS100", "US30"):
                if re.search(rf"\b{re.escape(alias)}\b", text, re.IGNORECASE):
                    symbol = normalize_symbol(alias)
                    notes.append(f"Symbol inferred as {symbol}")
                    break

        if direction and order_type is None:
            order_type = _order_from_kind(
                direction, kind, is_range=entry_type == EntryType.RANGE, range_as=self.range_as
            )

        return ParsedSignal(
            direction=direction,
            symbol=symbol,
            entry=entry,
            entry_low=entry_low,
            entry_high=entry_high,
            entry_type=entry_type,
            order_type=order_type,
            take_profits=take_profits,
            stop_loss=stop_loss,
            raw_message=raw_message,
            normalized_message=text,
            parse_notes=notes,
            ignored_categories=ignored,
            parser_name=self.parser_name,
            provider_profile=self.profile_name,
        )

    def _extract_take_profits(self, text: str) -> list[float]:
        tps: list[float] = []
        for line in text.split("\n"):
            match = TP_LINE.search(line)
            if not match:
                continue
            body = match.group("body")
            parts = TP_SPLIT.split(body)
            for part in parts:
                values = extract_floats(part)
                if values:
                    tps.append(values[0])
        seen: set[float] = set()
        unique: list[float] = []
        for tp in tps:
            if tp not in seen:
                seen.add(tp)
                unique.append(tp)
        return unique


_default_parser = DefaultSignalParser()


def parse_signal(raw_message: str) -> ParsedSignal:
    """Parse using the default shared parser instance."""
    return _default_parser.parse(raw_message)
