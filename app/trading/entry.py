"""Intelligent entry validation: deviation, TP proximity, spread checks.

This module is pure logic — it does not call MT5. Callers supply current
market price and optional symbol point size.
"""

from __future__ import annotations

import logging
from enum import Enum

from app.config.settings import EntrySettings, RiskSettings
from app.signals.models import EntryDecision, ParsedSignal, SignalDirection

logger = logging.getLogger(__name__)


class EntryAction(str, Enum):
    MARKET = "market"
    REJECT = "reject"
    SKIP = "skip"
    PENDING = "pending"
    MANUAL = "manual"


def price_to_points(price_diff: float, point: float) -> float:
    """Convert a price difference to MT5 points using the symbol's point size."""
    if point <= 0:
        return 0.0
    return price_diff / point


def compute_max_deviation(
    signal: ParsedSignal,
    settings: EntrySettings,
) -> float:
    """Compute the maximum allowed entry deviation in price units."""
    fixed = settings.max_entry_deviation
    sl_pct_limit: float | None = None

    if settings.use_sl_based_deviation or settings.entry_deviation_mode in {
        "sl_percent",
        "stricter",
        "permissive",
    }:
        sl_dist = signal.sl_distance()
        if sl_dist is not None and sl_dist > 0:
            sl_pct_limit = sl_dist * (settings.max_sl_distance_percent / 100.0)

    mode = settings.entry_deviation_mode
    if mode == "fixed" or sl_pct_limit is None:
        if settings.use_sl_based_deviation and sl_pct_limit is not None and mode == "fixed":
            # Legacy toggle: when SL-based is on with fixed mode, use SL % only
            return sl_pct_limit
        return fixed
    if mode == "sl_percent":
        return sl_pct_limit
    if mode == "stricter":
        return min(fixed, sl_pct_limit)
    if mode == "permissive":
        return max(fixed, sl_pct_limit)
    return fixed


def compute_entry_deviation(
    direction: SignalDirection,
    entry: float,
    current_price: float,
) -> float:
    """Directional adverse deviation from intended entry.

    SELL: positive when current is above entry (market ran up against a sell).
    BUY:  positive when current is below entry (market dropped against a buy).

    Favorable movement (price better than entry) returns 0.0 so the signal
    remains valid for market execution at the improved price.
    """
    if direction == SignalDirection.SELL:
        return max(0.0, current_price - entry)
    return max(0.0, entry - current_price)


def is_tp1_reached(
    direction: SignalDirection,
    tp1: float,
    current_price: float,
) -> bool:
    """Return True if the market has already reached/passed TP1."""
    if direction == SignalDirection.SELL:
        return current_price <= tp1
    return current_price >= tp1


class EntryValidator:
    """Intelligent entry decision engine."""

    def __init__(
        self,
        entry_settings: EntrySettings | None = None,
        risk_settings: RiskSettings | None = None,
    ) -> None:
        self.entry = entry_settings or EntrySettings()
        self.risk = risk_settings or RiskSettings()

    def evaluate(
        self,
        signal: ParsedSignal,
        current_price: float,
        *,
        spread: float | None = None,
        point: float | None = None,
    ) -> EntryDecision:
        """Evaluate whether a validated signal should be market-executed."""
        if signal.direction is None or signal.entry is None:
            return EntryDecision(
                ok=False,
                action=EntryAction.REJECT.value,
                reasons=["Missing direction or entry for entry check"],
                current_price=current_price,
            )

        direction = signal.direction
        entry = signal.entry
        reasons: list[str] = []

        # Spread filter
        if (
            spread is not None
            and self.risk.max_spread > 0
            and spread > self.risk.max_spread
        ):
            return EntryDecision(
                ok=False,
                action=EntryAction.REJECT.value,
                reasons=[f"Spread too high: {spread} > {self.risk.max_spread}"],
                current_price=current_price,
                signal_entry=entry,
                spread=spread,
            )

        # TP proximity protection
        tp1_reached = False
        if self.entry.tp_proximity_protection and signal.tp1 is not None:
            tp1_reached = is_tp1_reached(direction, signal.tp1, current_price)
            if tp1_reached:
                return EntryDecision(
                    ok=False,
                    action=EntryAction.REJECT.value,
                    reasons=["TP1 already reached before execution"],
                    current_price=current_price,
                    signal_entry=entry,
                    spread=spread,
                    tp1_reached=True,
                )

        deviation = compute_entry_deviation(direction, entry, current_price)
        max_dev = compute_max_deviation(signal, self.entry)

        logger.debug(
            "Entry check: entry=%s current=%s deviation=%s max=%s",
            entry,
            current_price,
            deviation,
            max_dev,
        )

        if deviation > max_dev:
            action = self._too_far_action()
            reasons.append(
                f"Entry moved too far from signal price "
                f"(deviation={deviation:.5f}, max={max_dev:.5f})"
            )
            if point and point > 0:
                reasons.append(
                    f"Deviation in points: {price_to_points(deviation, point):.1f}"
                )
            return EntryDecision(
                ok=False,
                action=action.value,
                reasons=reasons,
                current_price=current_price,
                signal_entry=entry,
                deviation=deviation,
                max_allowed_deviation=max_dev,
                spread=spread,
                tp1_reached=tp1_reached,
            )

        return EntryDecision(
            ok=True,
            action=EntryAction.MARKET.value,
            reasons=["Within entry deviation; TP1 not reached"],
            current_price=current_price,
            signal_entry=entry,
            deviation=deviation,
            max_allowed_deviation=max_dev,
            spread=spread,
            tp1_reached=False,
        )

    def _too_far_action(self) -> EntryAction:
        mapping = {
            "reject": EntryAction.REJECT,
            "pending": EntryAction.PENDING,
            "manual": EntryAction.MANUAL,
            "skip": EntryAction.SKIP,
        }
        return mapping.get(self.entry.too_far_behavior, EntryAction.REJECT)
