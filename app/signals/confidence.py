"""Diagnostic confidence scoring — never overrides hard validation."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.signals.models import ParsedSignal, SignalDirection


class ConfidenceBreakdown(BaseModel):
    direction_valid: bool = False
    symbol_recognized: bool = False
    entry_valid: bool = False
    tp_present: bool = False
    sl_present: bool = False
    relationship_valid: bool = False
    provider_format_matched: bool = False
    score: float = 0.0  # 0–100 diagnostic only
    notes: list[str] = Field(default_factory=list)


def compute_confidence(
    signal: ParsedSignal,
    *,
    relationship_ok: bool,
    provider_matched: bool = True,
) -> ConfidenceBreakdown:
    """Build a diagnostic score. Missing SL keeps the signal non-executable
    regardless of a high score elsewhere.
    """
    parts = ConfidenceBreakdown(
        direction_valid=signal.direction is not None,
        symbol_recognized=bool(signal.symbol),
        entry_valid=signal.entry is not None,
        tp_present=signal.tp_count > 0,
        sl_present=signal.stop_loss is not None,
        relationship_valid=relationship_ok,
        provider_format_matched=provider_matched,
    )
    flags = [
        parts.direction_valid,
        parts.symbol_recognized,
        parts.entry_valid,
        parts.tp_present,
        parts.sl_present,
        parts.relationship_valid,
        parts.provider_format_matched,
    ]
    parts.score = round(100.0 * sum(1 for f in flags if f) / len(flags), 1)
    if not parts.sl_present:
        parts.notes.append("Missing SL — non-executable regardless of score")
    if not parts.relationship_valid:
        parts.notes.append("TP/SL relationship invalid")
    return parts


def check_price_relationships(signal: ParsedSignal) -> list[str]:
    """Hard mathematical rules for BUY/SELL vs entry/TP/SL."""
    reasons: list[str] = []
    if signal.direction is None or signal.entry is None:
        return reasons

    entry = signal.entry
    direction = signal.direction

    if signal.stop_loss is not None:
        if direction == SignalDirection.BUY and not (signal.stop_loss < entry):
            reasons.append("BUY requires SL < Entry")
        if direction == SignalDirection.SELL and not (signal.stop_loss > entry):
            reasons.append("SELL requires Entry < SL")

    for i, tp in enumerate(signal.take_profits, start=1):
        if direction == SignalDirection.BUY and not (tp > entry):
            reasons.append(f"BUY requires Entry < TP{i} (got TP{i}={tp})")
        if direction == SignalDirection.SELL and not (tp < entry):
            reasons.append(f"SELL requires TP{i} < Entry (got TP{i}={tp})")

    # Full chain when SL and at least one TP exist
    if signal.stop_loss is not None and signal.tp1 is not None:
        if direction == SignalDirection.BUY:
            if not (signal.stop_loss < entry < signal.tp1):
                reasons.append("BUY requires SL < Entry < TP1")
        else:
            if not (signal.tp1 < entry < signal.stop_loss):
                reasons.append("SELL requires TP1 < Entry < SL")

    return reasons
