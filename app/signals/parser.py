"""Extensible trading signal parser.

Supports multiple common Telegram signal formats and normalizes them into
a single ParsedSignal model. Additional format handlers can be registered
without rewriting the pipeline.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from typing import Protocol

from app.signals.models import ParsedSignal, SignalDirection
from app.signals.normalizer import (
    extract_floats,
    normalize_symbol,
    normalize_whitespace,
    parse_float,
)

logger = logging.getLogger(__name__)

# Cancellation patterns (V1: detect & log only)
CANCEL_PATTERN = re.compile(
    r"\b(CANCEL(?:\s+SIGNAL)?|CLOSE\s+ALL|DELETE\s+SIGNAL)\b",
    re.IGNORECASE,
)

DIRECTION_PATTERN = re.compile(r"\b(BUY|SELL|LONG|SHORT)\b", re.IGNORECASE)

# Symbol tokens (letters/digits, optional separators) — refined during parse
SYMBOL_TOKEN = r"[A-Za-z][A-Za-z0-9._/#-]{1,20}"

# Header patterns: direction + symbol + optional entry
HEADER_PATTERNS: list[re.Pattern[str]] = [
    # SELL XAUUSD 4291.5  |  SELL XAUUSD @ 4291.5
    re.compile(
        rf"\b(?P<direction>BUY|SELL|LONG|SHORT)\s+"
        rf"(?P<symbol>{SYMBOL_TOKEN})\s*"
        rf"(?:@\s*)?(?P<entry>[-+]?\d[\d.,]*)?",
        re.IGNORECASE,
    ),
    # XAUUSD SELL 4291.5
    re.compile(
        rf"\b(?P<symbol>{SYMBOL_TOKEN})\s+"
        rf"(?P<direction>BUY|SELL|LONG|SHORT)\s*"
        rf"(?:@\s*)?(?P<entry>[-+]?\d[\d.,]*)?",
        re.IGNORECASE,
    ),
]

ENTRY_LINE = re.compile(
    r"\b(?:ENTRY|ENTER|PRICE|OPEN)\s*[:=]?\s*(?:@\s*)?(?P<entry>[-+]?\d[\d.,]*)",
    re.IGNORECASE,
)

# TP lines: TP 4287.5 | TP1: 4287.5 | TP1 4287.5 | TAKE PROFIT 4287.5
# Index must be 1–2 digits glued to TP (TP1) or clearly separated — never eat the price.
TP_LINE = re.compile(
    r"\b(?:TP|TAKE\s*PROFIT|TARGET)(?P<idx>\d{1,2})?\b\s*[:=]?\s*"
    r"(?P<body>.+)",
    re.IGNORECASE,
)

# SL lines
SL_LINE = re.compile(
    r"\b(?:SL|S\.?L\.?|STOP\s*LOSS|STOP)\s*[:=]?\s*(?P<sl>[-+]?\d[\d.,]*)",
    re.IGNORECASE,
)

# Inline multi-TP: TP 4287.5 / 4283 / 4277  or  TP: 1.1 - 1.2 - 1.3
TP_SPLIT = re.compile(r"[/,|;]|-\s+(?=\d)")


class SignalFormatHandler(Protocol):
    """Protocol for pluggable format handlers."""

    name: str

    def try_parse(self, text: str) -> ParsedSignal | None: ...


ParseHandler = Callable[[str], ParsedSignal | None]


def _to_direction(raw: str) -> SignalDirection:
    upper = raw.strip().upper()
    if upper in {"BUY", "LONG"}:
        return SignalDirection.BUY
    return SignalDirection.SELL


class DefaultSignalParser:
    """Primary multi-format signal parser.

    Recognizes common VIP-channel layouts including:
    - SELL XAUUSD 4291.5 / TP lines / SL
    - SELL XAUUSD @ 4291.5 / TP1: ... / SL:
    - XAUUSD SELL 4291.5
    - SELL GOLD / ENTRY 4291.5 / TP a / b / c / SL
    """

    def __init__(self, extra_handlers: list[ParseHandler] | None = None) -> None:
        self._extra_handlers: list[ParseHandler] = list(extra_handlers or [])

    def register_handler(self, handler: ParseHandler) -> None:
        """Register an additional format handler tried before the default logic."""
        self._extra_handlers.append(handler)

    def parse(self, raw_message: str) -> ParsedSignal:
        """Parse a raw Telegram message into a ParsedSignal.

        Never raises for malformed input — returns a partial ParsedSignal
        with notes explaining what was / was not found.
        """
        text = normalize_whitespace(raw_message or "")
        if not text:
            return ParsedSignal(raw_message=raw_message or "", parse_notes=["Empty message"])

        # Cancellation detection (V1: flag only)
        if CANCEL_PATTERN.search(text):
            return ParsedSignal(
                raw_message=raw_message,
                is_cancellation=True,
                parse_notes=["CANCELLATION_SIGNAL_DETECTED"],
            )

        for handler in self._extra_handlers:
            try:
                result = handler(text)
                if result is not None:
                    result.raw_message = raw_message
                    return result
            except Exception as exc:  # noqa: BLE001
                logger.warning("Extra parse handler failed: %s", exc)

        return self._parse_default(text, raw_message)

    def _parse_default(self, text: str, raw_message: str) -> ParsedSignal:
        notes: list[str] = []
        direction: SignalDirection | None = None
        symbol: str | None = None
        entry: float | None = None
        take_profits: list[float] = []
        stop_loss: float | None = None

        # --- Header: direction + symbol + optional entry ---
        header_matched = False
        for pattern in HEADER_PATTERNS:
            match = pattern.search(text)
            if match:
                direction = _to_direction(match.group("direction"))
                symbol = normalize_symbol(match.group("symbol"))
                entry_raw = match.groupdict().get("entry")
                if entry_raw:
                    entry = parse_float(entry_raw)
                header_matched = True
                notes.append(f"Header matched via {pattern.pattern[:40]}...")
                break

        if not header_matched:
            # Fallback: find direction anywhere
            dir_match = DIRECTION_PATTERN.search(text)
            if dir_match:
                direction = _to_direction(dir_match.group(1))
                notes.append("Direction found without full header")

        # Explicit ENTRY line overrides / fills entry
        entry_match = ENTRY_LINE.search(text)
        if entry_match:
            entry = parse_float(entry_match.group("entry"))
            notes.append("Entry from ENTRY line")

        # --- Take profits ---
        take_profits = self._extract_take_profits(text)
        if take_profits:
            notes.append(f"Found {len(take_profits)} TP(s)")

        # --- Stop loss ---
        sl_match = SL_LINE.search(text)
        if sl_match:
            stop_loss = parse_float(sl_match.group("sl"))
            notes.append("Stop loss found")

        # If symbol still missing, try common commodity aliases on their own line
        if symbol is None:
            for alias in ("XAUUSD", "GOLD", "EURUSD", "GBPUSD", "BTCUSD", "NAS100", "US30"):
                if re.search(rf"\b{re.escape(alias)}\b", text, re.IGNORECASE):
                    symbol = normalize_symbol(alias)
                    notes.append(f"Symbol inferred as {symbol}")
                    break

        return ParsedSignal(
            direction=direction,
            symbol=symbol,
            entry=entry,
            take_profits=take_profits,
            stop_loss=stop_loss,
            raw_message=raw_message,
            parse_notes=notes,
        )

    def _extract_take_profits(self, text: str) -> list[float]:
        tps: list[float] = []
        for line in text.split("\n"):
            match = TP_LINE.search(line)
            if not match:
                continue
            body = match.group("body")
            # Split multi-value TP lines
            parts = TP_SPLIT.split(body)
            for part in parts:
                values = extract_floats(part)
                # Take first number in each segment (ignore labels like "TP1")
                if values:
                    tps.append(values[0])
        # Deduplicate while preserving order
        seen: set[float] = set()
        unique: list[float] = []
        for tp in tps:
            if tp not in seen:
                seen.add(tp)
                unique.append(tp)
        return unique


# Module-level convenience
_default_parser = DefaultSignalParser()


def parse_signal(raw_message: str) -> ParsedSignal:
    """Parse using the default shared parser instance."""
    return _default_parser.parse(raw_message)
