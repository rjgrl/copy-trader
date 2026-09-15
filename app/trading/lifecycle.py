"""Signal lifecycle state machine."""

from __future__ import annotations

from app.signals.models import ALLOWED_TRANSITIONS, SignalStatus


class InvalidTransitionError(ValueError):
    """Raised when a signal status transition is not allowed."""


def can_transition(current: SignalStatus, new: SignalStatus) -> bool:
    if current == new:
        return True
    return new in ALLOWED_TRANSITIONS.get(current, set())


def transition(current: SignalStatus, new: SignalStatus) -> SignalStatus:
    """Validate and return the new status, or raise InvalidTransitionError."""
    if not can_transition(current, new):
        raise InvalidTransitionError(
            f"Invalid signal status transition: {current.value} → {new.value}"
        )
    return new
