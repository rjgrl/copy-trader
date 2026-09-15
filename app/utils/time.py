"""Time helpers for latency tracking."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


def utc_now() -> datetime:
    """Current UTC time with timezone awareness."""
    return datetime.now(timezone.utc)


def ensure_utc(dt: datetime) -> datetime:
    """Normalize naive datetimes to UTC-aware."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def ms_between(start: datetime, end: datetime) -> float:
    """Milliseconds between two datetimes."""
    return (ensure_utc(end) - ensure_utc(start)).total_seconds() * 1000.0


@dataclass(slots=True)
class LatencyTimestamps:
    """Three-point latency record for a signal."""

    telegram_at: datetime | None = None
    received_at: datetime | None = None
    executed_at: datetime | None = None

    @property
    def telegram_to_app_ms(self) -> float | None:
        if self.telegram_at is None or self.received_at is None:
            return None
        return ms_between(self.telegram_at, self.received_at)

    @property
    def app_to_mt5_ms(self) -> float | None:
        if self.received_at is None or self.executed_at is None:
            return None
        return ms_between(self.received_at, self.executed_at)

    @property
    def total_ms(self) -> float | None:
        if self.telegram_at is None or self.executed_at is None:
            return None
        return ms_between(self.telegram_at, self.executed_at)
