"""Signal package — parsing, validation, classification, inspection."""

from app.signals.classifier import MessageClassifier, MessageKind
from app.signals.inspector import InspectionResult, SignalInspector
from app.signals.models import (
    EntryDecision,
    ParsedSignal,
    SignalContext,
    SignalDirection,
    SignalStatus,
    ValidationResult,
)
from app.signals.parser import DefaultSignalParser, parse_signal
from app.signals.validator import SignalValidator

__all__ = [
    "DefaultSignalParser",
    "EntryDecision",
    "InspectionResult",
    "MessageClassifier",
    "MessageKind",
    "ParsedSignal",
    "SignalContext",
    "SignalDirection",
    "SignalInspector",
    "SignalStatus",
    "SignalValidator",
    "ValidationResult",
    "parse_signal",
]
