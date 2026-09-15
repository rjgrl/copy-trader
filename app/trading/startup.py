"""Safe startup: live listening watermarks and incomplete-execution recovery.

Startup sequence:
  CONNECT → RESTORE STATE → RECONCILE INCOMPLETE → ESTABLISH LIVE LISTENER → WAIT

Never: CONNECT → DOWNLOAD OLD SIGNALS → EXECUTE
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

from app.database.repositories import OrderRepository, SignalRepository
from app.signals.models import SignalStatus
from app.utils.time import utc_now

logger = logging.getLogger(__name__)

INCOMPLETE_STATUSES = (
    SignalStatus.EXECUTING.value,
    SignalStatus.PARTIALLY_EXECUTED.value,
)


@dataclass(slots=True)
class LiveListeningPoint:
    """Authoritative 'live' boundary — messages at or below watermark are historical.

    Identity for duplicate prevention remains (chat_id, message_id).
    Timestamps are stored for latency/display only — never as the primary gate.
    """

    established_at: datetime
    session_id: str
    # chat_id → highest message_id known at listener start (inclusive skip)
    watermarks: dict[int, int] = field(default_factory=dict)
    active: bool = False

    def is_historical(self, chat_id: int, message_id: int) -> bool:
        """Return True if this message must not be executed (at/below live point)."""
        if not self.active:
            # Listener not live yet — treat everything as unsafe/historical
            return True
        watermark = self.watermarks.get(chat_id)
        if watermark is None:
            # Unknown chat watermark: only allow if we explicitly added the source
            # with watermark 0 meaning "no prior messages known"
            return False
        return message_id <= watermark

    def set_watermark(self, chat_id: int, message_id: int) -> None:
        current = self.watermarks.get(chat_id, 0)
        self.watermarks[chat_id] = max(current, message_id)


@dataclass(slots=True)
class ReconciliationReport:
    reviewed: int = 0
    marked_requires_review: int = 0
    already_terminal: int = 0
    details: list[str] = field(default_factory=list)


class StartupSafetyService:
    """Restore DB state and freeze incomplete executions pending MT5 reconciliation."""

    def __init__(
        self,
        signal_repo: SignalRepository,
        order_repo: OrderRepository | None = None,
        *,
        magic_number: int = 123456,
    ) -> None:
        self._signals = signal_repo
        self._orders = order_repo
        self.magic_number = magic_number
        self.listening_point: LiveListeningPoint | None = None

    def create_listening_point(self, session_id: str | None = None) -> LiveListeningPoint:
        sid = session_id or utc_now().strftime("%Y%m%dT%H%M%S%fZ")
        self.listening_point = LiveListeningPoint(
            established_at=utc_now(),
            session_id=sid,
            watermarks={},
            active=False,
        )
        logger.info(
            "Live listening point created (session=%s at=%s) — not active until watermarks set",
            sid,
            self.listening_point.established_at.isoformat(),
        )
        return self.listening_point

    def activate_listening_point(self) -> None:
        if self.listening_point is None:
            raise RuntimeError("No listening point to activate")
        self.listening_point.active = True
        logger.info(
            "LIVE LISTENING ACTIVE session=%s watermarks=%s — historical messages will be SKIPPED",
            self.listening_point.session_id,
            self.listening_point.watermarks,
        )

    def reconcile_incomplete_executions(self) -> ReconciliationReport:
        """On startup: do NOT resent orders. Mark ambiguous states for review.

        Full MT5 ticket matching is wired in Phase 4–6. Until then, incomplete
        EXECUTING / PARTIALLY_EXECUTED signals become EXECUTION_REQUIRES_REVIEW.
        """
        report = ReconciliationReport()
        rows = self._signals.list_by_statuses(list(INCOMPLETE_STATUSES))
        for row in rows:
            report.reviewed += 1
            # Without MT5 client yet we cannot confidently confirm tickets.
            # Safe default: require manual/automated review — never auto-retry.
            self._signals.update_status(
                row.id,  # type: ignore[arg-type]
                SignalStatus.EXECUTION_REQUIRES_REVIEW.value,
                failure_reason=(
                    "Incomplete execution found on startup — "
                    "MT5 reconciliation required before any retry"
                ),
                processed_at=utc_now(),
            )
            report.marked_requires_review += 1
            detail = (
                f"signal_id={row.id} chat={row.telegram_chat_id} "
                f"msg={row.telegram_message_id} was {row.status} "
                f"-> EXECUTION_REQUIRES_REVIEW"
            )
            report.details.append(detail)
            logger.warning("RECONCILE: %s", detail)

        if report.reviewed == 0:
            logger.info("Startup reconciliation: no incomplete executions found")
        else:
            logger.warning(
                "Startup reconciliation: %s signal(s) marked EXECUTION_REQUIRES_REVIEW",
                report.marked_requires_review,
            )
        return report
