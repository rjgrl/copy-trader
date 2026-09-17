"""Signal domain models and lifecycle status enum."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


class SignalDirection(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    """Intended order style derived from the signal text / provider profile."""

    MARKET_BUY = "MARKET_BUY"
    MARKET_SELL = "MARKET_SELL"
    BUY_LIMIT = "BUY_LIMIT"
    SELL_LIMIT = "SELL_LIMIT"
    BUY_STOP = "BUY_STOP"
    SELL_STOP = "SELL_STOP"
    ENTRY_ZONE = "ENTRY_ZONE"


class EntryType(str, Enum):
    SINGLE = "SINGLE"
    RANGE = "RANGE"


class SignalStatus(str, Enum):
    """Signal lifecycle states. Invalid transitions are rejected by the state machine."""

    RECEIVED = "RECEIVED"
    PARSED = "PARSED"
    VALIDATED = "VALIDATED"
    ENTRY_CHECKED = "ENTRY_CHECKED"
    EXECUTING = "EXECUTING"
    EXECUTED = "EXECUTED"
    PARTIALLY_EXECUTED = "PARTIALLY_EXECUTED"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    EXECUTION_REQUIRES_REVIEW = "EXECUTION_REQUIRES_REVIEW"
    REJECTED = "REJECTED"
    SKIPPED = "SKIPPED"
    DUPLICATE = "DUPLICATE"


# Allowed transitions for the signal state machine
ALLOWED_TRANSITIONS: dict[SignalStatus, set[SignalStatus]] = {
    SignalStatus.RECEIVED: {
        SignalStatus.PARSED,
        SignalStatus.REJECTED,
        SignalStatus.SKIPPED,
        SignalStatus.DUPLICATE,
    },
    SignalStatus.PARSED: {
        SignalStatus.VALIDATED,
        SignalStatus.REJECTED,
        SignalStatus.SKIPPED,
    },
    SignalStatus.VALIDATED: {
        SignalStatus.ENTRY_CHECKED,
        SignalStatus.REJECTED,
        SignalStatus.SKIPPED,
    },
    SignalStatus.ENTRY_CHECKED: {
        SignalStatus.EXECUTING,
        SignalStatus.REJECTED,
        SignalStatus.SKIPPED,
    },
    SignalStatus.EXECUTING: {
        SignalStatus.EXECUTED,
        SignalStatus.PARTIALLY_EXECUTED,
        SignalStatus.EXECUTION_FAILED,
        SignalStatus.EXECUTION_REQUIRES_REVIEW,
    },
    SignalStatus.PARTIALLY_EXECUTED: {
        SignalStatus.EXECUTED,
        SignalStatus.EXECUTION_REQUIRES_REVIEW,
        SignalStatus.EXECUTION_FAILED,
    },
    # Terminal states
    SignalStatus.EXECUTED: set(),
    SignalStatus.EXECUTION_FAILED: set(),
    SignalStatus.EXECUTION_REQUIRES_REVIEW: set(),
    SignalStatus.REJECTED: set(),
    SignalStatus.SKIPPED: set(),
    SignalStatus.DUPLICATE: set(),
}


class ParsedSignal(BaseModel):
    """Normalized trading signal produced by the parser."""

    direction: SignalDirection | None = None
    symbol: str | None = None
    entry: float | None = None  # single price or representative price for ranges
    entry_low: float | None = None
    entry_high: float | None = None
    entry_type: EntryType = EntryType.SINGLE
    order_type: OrderType | None = None
    take_profits: list[float] = Field(default_factory=list)
    stop_loss: float | None = None
    raw_message: str = ""
    normalized_message: str = ""
    is_cancellation: bool = False
    message_kind: str | None = None
    parse_notes: list[str] = Field(default_factory=list)
    ignored_categories: list[str] = Field(default_factory=list)
    parser_name: str = "standard"
    provider_profile: str | None = None

    @field_validator("symbol", mode="before")
    @classmethod
    def _normalize_symbol(cls, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip().upper()
        return text or None

    @field_validator("take_profits", mode="before")
    @classmethod
    def _coerce_tps(cls, value: Any) -> list[float]:
        if value is None:
            return []
        return [float(v) for v in value]

    @model_validator(mode="after")
    def _dedupe_tps_and_sync_entry(self) -> ParsedSignal:
        seen: set[float] = set()
        unique: list[float] = []
        for tp in self.take_profits:
            if tp not in seen:
                seen.add(tp)
                unique.append(tp)
        self.take_profits = unique

        # Normalize range bounds and keep a representative `entry` for legacy paths
        if self.entry_low is not None and self.entry_high is not None:
            low = min(self.entry_low, self.entry_high)
            high = max(self.entry_low, self.entry_high)
            self.entry_low = low
            self.entry_high = high
            self.entry_type = EntryType.RANGE
            if self.entry is None:
                # Near-market edge for limits; midpoint otherwise
                if self.order_type == OrderType.BUY_LIMIT:
                    self.entry = high
                elif self.order_type == OrderType.SELL_LIMIT:
                    self.entry = low
                else:
                    self.entry = (low + high) / 2.0
        elif self.entry is not None and self.entry_type == EntryType.SINGLE:
            if self.entry_low is None and self.entry_high is None:
                pass
        return self

    def has_entry(self) -> bool:
        if self.entry is not None:
            return True
        return self.entry_low is not None and self.entry_high is not None

    def entry_low_bound(self) -> float | None:
        if self.entry_low is not None:
            return self.entry_low
        return self.entry

    def entry_high_bound(self) -> float | None:
        if self.entry_high is not None:
            return self.entry_high
        return self.entry

    @property
    def tp_count(self) -> int:
        return len(self.take_profits)

    @property
    def tp1(self) -> float | None:
        return self.take_profits[0] if self.take_profits else None

    @property
    def tp2(self) -> float | None:
        return self.take_profits[1] if len(self.take_profits) > 1 else None

    @property
    def tp3(self) -> float | None:
        return self.take_profits[2] if len(self.take_profits) > 2 else None

    def additional_tps(self) -> list[float]:
        return self.take_profits[3:] if len(self.take_profits) > 3 else []

    def sl_distance(self) -> float | None:
        if self.stop_loss is None:
            return None
        low = self.entry_low_bound()
        high = self.entry_high_bound()
        if low is None or high is None:
            return None
        # Distance from SL to nearer edge of the entry zone
        if self.stop_loss < low:
            return low - self.stop_loss
        if self.stop_loss > high:
            return self.stop_loss - high
        return 0.0


class ValidationResult(BaseModel):
    """Outcome of structural signal validation (fields present / consistent)."""

    ok: bool
    status: SignalStatus
    reasons: list[str] = Field(default_factory=list)
    signal: ParsedSignal | None = None
    confidence: Any = None  # ConfidenceBreakdown | None — avoid circular import at runtime

    @property
    def reason(self) -> str:
        return "; ".join(self.reasons) if self.reasons else ""


class EntryDecision(BaseModel):
    """Outcome of intelligent entry / market condition checks."""

    ok: bool
    action: str  # market | reject | skip | pending | manual
    reasons: list[str] = Field(default_factory=list)
    current_price: float | None = None
    signal_entry: float | None = None
    deviation: float | None = None
    max_allowed_deviation: float | None = None
    spread: float | None = None
    tp1_reached: bool = False

    @property
    def reason(self) -> str:
        return "; ".join(self.reasons) if self.reasons else ""


class SignalContext(BaseModel):
    """Full processing context for one Telegram message."""

    telegram_chat_id: int
    telegram_message_id: int
    telegram_message_date: datetime | None = None
    source_name: str = ""
    raw_message: str
    received_at: datetime
    status: SignalStatus = SignalStatus.RECEIVED
    parsed: ParsedSignal | None = None
    mapped_mt5_symbol: str | None = None
    validation: ValidationResult | None = None
    entry_decision: EntryDecision | None = None
    failure_reason: str | None = None
    signal_hash: str | None = None
    db_id: int | None = None

    model_config = {"arbitrary_types_allowed": True}
