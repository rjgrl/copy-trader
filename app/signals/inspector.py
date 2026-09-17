"""Signal Inspector — paste a message and see detection/validation results.

Development and testing tool. Does not send MT5 orders.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.signals.classifier import ClassificationResult, MessageClassifier, MessageKind
from app.signals.confidence import ConfidenceBreakdown
from app.signals.models import EntryType, OrderType, ParsedSignal, SignalStatus
from app.signals.profiles import ProfileRegistry, ProviderProfile
from app.signals.validator import SignalValidator


class InspectionResult(BaseModel):
    """Human-readable inspection outcome for a pasted Telegram message."""

    signal_detected: bool
    message_kind: MessageKind
    classification_reasons: list[str] = Field(default_factory=list)
    direction: str | None = None
    symbol: str | None = None
    entry: float | None = None
    entry_low: float | None = None
    entry_high: float | None = None
    entry_type: str | None = None
    order_type: str | None = None
    take_profits: list[float] = Field(default_factory=list)
    stop_loss: float | None = None
    tp_count: int = 0
    validation_status: str = "N/A"
    validation_ok: bool = False
    rejection_reasons: list[str] = Field(default_factory=list)
    provider_profile: str = "standard"
    ignored_categories: list[str] = Field(default_factory=list)
    confidence: ConfidenceBreakdown | None = None
    parsed: ParsedSignal | None = None
    summary: str = ""

    def format_report(self) -> str:
        lines = [
            "=" * 50,
            "SIGNAL INSPECTOR",
            "=" * 50,
            f"Detection:    {'YES' if self.signal_detected else 'NO'}",
            f"Kind:         {self.message_kind.value}",
            f"Provider:     {self.provider_profile}",
        ]
        if self.classification_reasons:
            lines.append(f"Classified:   {'; '.join(self.classification_reasons)}")

        if self.signal_detected or self.parsed:
            lines.extend(
                [
                    f"Signal type:  {self.order_type or '—'}",
                    f"Symbol:       {self.symbol or '—'}",
                    f"Direction:    {self.direction or '—'}",
                    f"Order type:   {self.order_type or '—'}",
                    f"Entry type:   {self.entry_type or '—'}",
                ]
            )
            if self.entry_type == EntryType.RANGE.value or (
                self.entry_low is not None and self.entry_high is not None
            ):
                lines.append(f"Entry low:    {self.entry_low}")
                lines.append(f"Entry high:   {self.entry_high}")
            lines.append(f"Entry:        {self.entry if self.entry is not None else '—'}")
            lines.append(f"SL:           {self.stop_loss if self.stop_loss is not None else '—'}")
            lines.append(f"TP count:     {self.tp_count}")
            lines.append(f"TPs:          {self.take_profits or '—'}")
            lines.append(
                f"Validation:   {'PASS' if self.validation_ok else self.validation_status}"
            )

        if self.ignored_categories:
            lines.append(f"Ignored:      {', '.join(self.ignored_categories)}")

        if self.rejection_reasons:
            lines.append("Reasons:")
            for reason in self.rejection_reasons:
                lines.append(f"  - {reason}")

        if self.confidence:
            lines.append(f"Confidence:   {self.confidence.score}/100 (diagnostic only)")

        lines.append("-" * 50)
        lines.append(self.summary)
        lines.append("=" * 50)
        return "\n".join(lines)


class SignalInspector:
    """Inspect raw text without Telegram or MT5 side effects."""

    def __init__(
        self,
        *,
        profiles: ProfileRegistry | None = None,
        classifier: MessageClassifier | None = None,
    ) -> None:
        self.profiles = profiles or ProfileRegistry()
        self.classifier = classifier or MessageClassifier()

    def inspect(
        self,
        text: str,
        *,
        chat_id: int | None = None,
        profile_name: str | None = None,
    ) -> InspectionResult:
        profile = (
            self.profiles.get_profile_by_name(profile_name)
            if profile_name
            else self.profiles.get_profile(chat_id)
        )
        parser = (
            self.profiles.get_parser_for_profile(profile.name)
            if profile_name
            else self.profiles.get_parser(chat_id)
        )
        classification = self.classifier.classify(text)

        if classification.kind in {
            MessageKind.EMPTY,
            MessageKind.CHATTER,
            MessageKind.ANALYSIS,
            MessageKind.TRADE_UPDATE,
            MessageKind.CANCELLATION,
        }:
            summary = {
                MessageKind.EMPTY: "NO EXECUTABLE SIGNAL — empty message.",
                MessageKind.CHATTER: "NO EXECUTABLE SIGNAL — missing structured trade information.",
                MessageKind.ANALYSIS: "NO EXECUTABLE SIGNAL — analysis/conditional language.",
                MessageKind.TRADE_UPDATE: "NO EXECUTABLE SIGNAL — trade update (TP hit / SL move / close).",
                MessageKind.CANCELLATION: "CANCELLATION detected — will not close trades in V1.",
            }.get(classification.kind, "NO EXECUTABLE SIGNAL")
            return InspectionResult(
                signal_detected=False,
                message_kind=classification.kind,
                classification_reasons=classification.reasons,
                provider_profile=profile.name,
                summary=summary,
            )

        parsed = parser.parse(text)
        if parsed.is_cancellation:
            return InspectionResult(
                signal_detected=False,
                message_kind=MessageKind.CANCELLATION,
                classification_reasons=["CANCELLATION_SIGNAL_DETECTED"],
                provider_profile=profile.name,
                parsed=parsed,
                ignored_categories=list(parsed.ignored_categories),
                summary="CANCELLATION detected — will not close trades in V1.",
            )

        validator = SignalValidator(
            profile.to_validation_rules(),
            validate_tp_ordering=profile.validate_tp_ordering,
            provider_matched=True,
        )
        validation = validator.validate(parsed)
        detected = validation.ok

        if detected:
            summary = "VALID SIGNAL"
        else:
            reason = validation.reason or "failed validation"
            # Prefer a single clear primary reason for the summary line
            primary = validation.reasons[0] if validation.reasons else reason
            summary = f"INVALID SIGNAL\nReason:\n{primary}"

        return InspectionResult(
            signal_detected=detected,
            message_kind=(
                MessageKind.EXECUTABLE_CANDIDATE
                if classification.executable_candidate
                else classification.kind
            ),
            classification_reasons=classification.reasons,
            direction=parsed.direction.value if parsed.direction else None,
            symbol=parsed.symbol,
            entry=parsed.entry,
            entry_low=parsed.entry_low,
            entry_high=parsed.entry_high,
            entry_type=parsed.entry_type.value if parsed.entry_type else None,
            order_type=parsed.order_type.value if parsed.order_type else None,
            take_profits=list(parsed.take_profits),
            stop_loss=parsed.stop_loss,
            tp_count=parsed.tp_count,
            validation_status=validation.status.value,
            validation_ok=validation.ok,
            rejection_reasons=list(validation.reasons),
            provider_profile=profile.name,
            ignored_categories=list(parsed.ignored_categories),
            confidence=validation.confidence,
            parsed=parsed,
            summary=summary,
        )
