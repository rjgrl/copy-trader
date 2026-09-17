"""Structural + mathematical signal validation.

Hard requirements cannot be overridden by confidence scores.
"""

from __future__ import annotations

import logging

from app.config.settings import ValidationRules
from app.signals.confidence import (
    ConfidenceBreakdown,
    check_price_relationships,
    compute_confidence,
)
from app.signals.models import ParsedSignal, SignalStatus, ValidationResult

logger = logging.getLogger(__name__)


class SignalValidator:
    """Validate that a parsed signal has the required fields for execution."""

    def __init__(
        self,
        rules: ValidationRules | None = None,
        *,
        validate_tp_ordering: bool = True,
        provider_matched: bool = True,
    ) -> None:
        self.rules = rules or ValidationRules()
        self.validate_tp_ordering = validate_tp_ordering
        self.provider_matched = provider_matched

    def validate(self, signal: ParsedSignal) -> ValidationResult:
        if signal.is_cancellation:
            return ValidationResult(
                ok=False,
                status=SignalStatus.SKIPPED,
                reasons=["CANCELLATION_SIGNAL_DETECTED"],
                signal=signal,
                confidence=compute_confidence(
                    signal, relationship_ok=False, provider_matched=self.provider_matched
                ),
            )

        reasons: list[str] = []

        if self.rules.require_direction and signal.direction is None:
            reasons.append("Missing Direction")
        if self.rules.require_symbol and not signal.symbol:
            reasons.append("Missing Symbol")
        if self.rules.require_entry and not signal.has_entry():
            reasons.append("Missing Entry Price")
        if self.rules.require_tp:
            if signal.tp_count < self.rules.min_tp_count:
                reasons.append(
                    f"Missing Take Profit (need >= {self.rules.min_tp_count})"
                )
        if self.rules.require_sl and signal.stop_loss is None:
            reasons.append("Missing Stop Loss")

        relationship_reasons = check_price_relationships(signal)
        if relationship_reasons:
            reasons.extend(relationship_reasons)

        if self.validate_tp_ordering and signal.direction and signal.tp_count > 1:
            reasons.extend(self._check_tp_ordering(signal))

        relationship_ok = not relationship_reasons
        confidence = compute_confidence(
            signal,
            relationship_ok=relationship_ok and not reasons,
            provider_matched=self.provider_matched,
        )

        if reasons:
            logger.info("Signal rejected: %s", "; ".join(reasons))
            return ValidationResult(
                ok=False,
                status=SignalStatus.REJECTED,
                reasons=reasons,
                signal=signal,
                confidence=confidence,
            )

        return ValidationResult(
            ok=True,
            status=SignalStatus.VALIDATED,
            reasons=[],
            signal=signal,
            confidence=confidence,
        )

    @staticmethod
    def _check_tp_ordering(signal: ParsedSignal) -> list[str]:
        """Optional: TPs should progress away from entry in order."""
        from app.signals.models import SignalDirection

        reasons: list[str] = []
        tps = signal.take_profits
        if signal.direction == SignalDirection.BUY:
            for i in range(1, len(tps)):
                if tps[i] <= tps[i - 1]:
                    reasons.append(
                        f"BUY TP ordering invalid: TP{i + 1}={tps[i]} should be > TP{i}={tps[i - 1]}"
                    )
        elif signal.direction == SignalDirection.SELL:
            for i in range(1, len(tps)):
                if tps[i] >= tps[i - 1]:
                    reasons.append(
                        f"SELL TP ordering invalid: TP{i + 1}={tps[i]} should be < TP{i}={tps[i - 1]}"
                    )
        return reasons
