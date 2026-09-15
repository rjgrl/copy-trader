"""Lifecycle / state machine tests."""

from __future__ import annotations

import pytest

from app.signals.models import SignalStatus
from app.trading.lifecycle import InvalidTransitionError, can_transition, transition


def test_happy_path_transitions() -> None:
    status = SignalStatus.RECEIVED
    for nxt in (
        SignalStatus.PARSED,
        SignalStatus.VALIDATED,
        SignalStatus.ENTRY_CHECKED,
        SignalStatus.EXECUTING,
        SignalStatus.EXECUTED,
    ):
        assert can_transition(status, nxt)
        status = transition(status, nxt)
    assert status == SignalStatus.EXECUTED


def test_reject_from_validated() -> None:
    assert transition(SignalStatus.VALIDATED, SignalStatus.REJECTED) == SignalStatus.REJECTED


def test_invalid_transition_raises() -> None:
    with pytest.raises(InvalidTransitionError):
        transition(SignalStatus.EXECUTED, SignalStatus.RECEIVED)


def test_partial_execution() -> None:
    status = transition(SignalStatus.EXECUTING, SignalStatus.PARTIALLY_EXECUTED)
    assert status == SignalStatus.PARTIALLY_EXECUTED


def test_requires_review_from_executing() -> None:
    status = transition(SignalStatus.EXECUTING, SignalStatus.EXECUTION_REQUIRES_REVIEW)
    assert status == SignalStatus.EXECUTION_REQUIRES_REVIEW


def test_requires_review_from_partial() -> None:
    status = transition(
        SignalStatus.PARTIALLY_EXECUTED, SignalStatus.EXECUTION_REQUIRES_REVIEW
    )
    assert status == SignalStatus.EXECUTION_REQUIRES_REVIEW
