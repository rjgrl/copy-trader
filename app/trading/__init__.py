"""Trading package — entry validation, risk, lifecycle, safety, startup, engine."""

__all__ = [
    "EntryCheckResult",
    "EntryValidator",
    "IntelligentEntryEngine",
    "InvalidTransitionError",
    "LiveListeningPoint",
    "StartupSafetyService",
    "can_transition",
    "transition",
]


def __getattr__(name: str):
    if name == "EntryValidator":
        from app.trading.entry import EntryValidator

        return EntryValidator
    if name in {"EntryCheckResult", "IntelligentEntryEngine"}:
        from app.trading.engine import EntryCheckResult, IntelligentEntryEngine

        return {
            "EntryCheckResult": EntryCheckResult,
            "IntelligentEntryEngine": IntelligentEntryEngine,
        }[name]
    if name in {"InvalidTransitionError", "can_transition", "transition"}:
        from app.trading import lifecycle

        return getattr(lifecycle, name)
    if name in {"LiveListeningPoint", "StartupSafetyService"}:
        from app.trading import startup

        return getattr(startup, name)
    raise AttributeError(name)
