"""Message classification — reject chatter, updates, and analysis before trading.

Conservative: when uncertain, treat as non-executable.
Structured signals with TP+SL are prioritized over trailing analysis text.
"""

from __future__ import annotations

import re
from enum import Enum

from pydantic import BaseModel, Field

from app.signals.normalizer import prepare_message_for_parse


class MessageKind(str, Enum):
    """High-level classification of a Telegram message."""

    EXECUTABLE_CANDIDATE = "executable_candidate"
    TRADE_UPDATE = "trade_update"
    ANALYSIS = "analysis"
    CHATTER = "chatter"
    CANCELLATION = "cancellation"
    EMPTY = "empty"
    UNKNOWN = "unknown"


UPDATE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bTP\s*\d*\s*(HIT|REACHED|DONE|BOOKED|SECURED)\b", re.I),
    re.compile(r"\b(TAKE\s*PROFIT|TARGET)\s*(HIT|REACHED)\b", re.I),
    re.compile(r"\b(MOVE|MOVED|MOVING)\s+(SL|STOP|STOP\s*LOSS)\b", re.I),
    re.compile(r"\bSL\s*(MOVED|TO\s*(BE|BREAKEVEN|BREAK\s*EVEN|ENTRY))\b", re.I),
    re.compile(r"\b(BREAKEVEN|BREAK\s*EVEN|BE\s*HIT)\b", re.I),
    re.compile(r"\bCLOSE\s+(HALF|PARTIAL|ALL|TRADE|POSITION)\b", re.I),
    re.compile(r"\b(TRADE|POSITION)\s+(CLOSED|CLOSING)\b", re.I),
    re.compile(r"\bBOOK\s+PARTIAL\b", re.I),
    re.compile(r"\bSECURE\s+PROFITS?\b", re.I),
]

ANALYSIS_PATTERNS: list[re.Pattern[str]] = [
    re.compile(
        r"\b(LOOKS?\s+STRONG|LOOKING\s+(BULLISH|BEARISH)|IS\s+(BULLISH|BEARISH))\b",
        re.I,
    ),
    re.compile(r"\b(WAITING\s+FOR|WAIT\s+FOR|WAIT)\b.{0,40}\b(BUY|SELL)\b", re.I),
    re.compile(r"\b(POSSIBLE|POTENTIAL|MAYBE|MIGHT|COULD)\s+(BUY|SELL)\b", re.I),
    re.compile(r"\b(BUY|SELL)\s+IF\b", re.I),
    re.compile(r"\bIF\s+PRICE\s+(BREAKS?|BREAKS?\s+ABOVE|BREAKS?\s+BELOW|REACHES?)\b", re.I),
    re.compile(r"\b(AROUND|NEAR|NEARBY)\s+\d", re.I),
    re.compile(r"\b(ANALYSIS|MARKET\s+UPDATE|NEWS|OUTLOOK|FORECAST)\b", re.I),
    re.compile(r"\b(HOLD|HOLDING)\b", re.I),
    re.compile(r"\b(CONFIRMATION|CONFIRMED?\s+ENTRY)\b", re.I),
    re.compile(r"\b(IDEA|SETUP\s+WATCHING|WATCHING\s+FOR)\b", re.I),
]

CANCEL_PATTERN = re.compile(
    r"\b(CANCEL(?:\s+SIGNAL)?|CLOSE\s+ALL|DELETE\s+SIGNAL)\b",
    re.I,
)

STRUCTURED_HINT = re.compile(
    r"\b(BUY|SELL|LONG|SHORT)\b.+\b[A-Z]{3,}|\b[A-Z]{3,}.+\b(BUY|SELL|LONG|SHORT)\b"
    r"|\bGOLD\b.+\b(BUY|SELL|LONG|SHORT)\b|\b(BUY|SELL|LONG|SHORT)\b.+\bGOLD\b",
    re.I | re.S,
)
HAS_TP = re.compile(r"\b(TP|TAKE\s*PROFIT|TAKEPROFIT|TARGET)\b", re.I)
HAS_SL = re.compile(r"\b(SL|STOP\s*LOSS|STOPLOSS|STOP)\b", re.I)
HAS_ENTRY_NUMBER = re.compile(r"\d+\.\d+|\b\d{3,}\b")
HAS_RANGE = re.compile(r"\d[\d.,]*\s*-\s*\d[\d.,]*")


class ClassificationResult(BaseModel):
    kind: MessageKind
    reasons: list[str] = Field(default_factory=list)
    executable_candidate: bool = False

    @property
    def reason(self) -> str:
        return "; ".join(self.reasons) if self.reasons else self.kind.value


class MessageClassifier:
    """Deterministic pre-filter before the structured parser."""

    def classify(self, text: str) -> ClassificationResult:
        raw = (text or "").strip()
        if not raw:
            return ClassificationResult(
                kind=MessageKind.EMPTY,
                reasons=["Empty message"],
            )

        normalized, _ = prepare_message_for_parse(raw)
        probe = normalized or raw

        if CANCEL_PATTERN.search(probe):
            return ClassificationResult(
                kind=MessageKind.CANCELLATION,
                reasons=["CANCELLATION_SIGNAL_DETECTED"],
            )

        for pattern in UPDATE_PATTERNS:
            if pattern.search(probe):
                return ClassificationResult(
                    kind=MessageKind.TRADE_UPDATE,
                    reasons=[
                        "TRADE_UPDATE_DETECTED",
                        f"Matched update pattern: {pattern.pattern[:48]}",
                    ],
                )

        has_dir = bool(re.search(r"\b(BUY|SELL|LONG|SHORT)\b", probe, re.I))
        has_tp = bool(HAS_TP.search(probe))
        has_sl = bool(HAS_SL.search(probe))
        has_numbers = bool(HAS_ENTRY_NUMBER.search(probe))
        structured = bool(STRUCTURED_HINT.search(probe)) or bool(HAS_RANGE.search(probe))

        # Strong structured body wins over trailing analysis / disclaimers
        strong_structured = has_dir and has_numbers and has_tp and has_sl and (
            structured or bool(re.search(r"\bGOLD\b", probe, re.I))
        )
        if strong_structured:
            return ClassificationResult(
                kind=MessageKind.EXECUTABLE_CANDIDATE,
                reasons=["Structured trade signal body (TP+SL) — analysis text ignored"],
                executable_candidate=True,
            )

        for pattern in ANALYSIS_PATTERNS:
            if pattern.search(probe):
                return ClassificationResult(
                    kind=MessageKind.ANALYSIS,
                    reasons=[
                        "ANALYSIS_OR_CONDITIONAL_LANGUAGE",
                        f"Matched: {pattern.pattern[:48]}",
                    ],
                )

        if has_dir and not (has_tp or has_sl):
            if not has_numbers or not structured:
                return ClassificationResult(
                    kind=MessageKind.CHATTER,
                    reasons=["Direction mentioned without structured TP/SL trade body"],
                )

        if has_dir and structured and has_numbers and (has_tp or has_sl):
            return ClassificationResult(
                kind=MessageKind.EXECUTABLE_CANDIDATE,
                reasons=["Structured trade-like message"],
                executable_candidate=True,
            )

        if has_dir and structured and has_numbers:
            return ClassificationResult(
                kind=MessageKind.EXECUTABLE_CANDIDATE,
                reasons=["Direction+symbol+price present; validator will enforce TP/SL"],
                executable_candidate=True,
            )

        if has_dir or has_tp or has_sl:
            return ClassificationResult(
                kind=MessageKind.CHATTER,
                reasons=["Trading terminology without complete structured signal"],
            )

        return ClassificationResult(
            kind=MessageKind.CHATTER,
            reasons=["No structured trade signal detected"],
        )
