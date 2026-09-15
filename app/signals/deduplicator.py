"""Duplicate detection for Telegram messages and optional signal hashing."""

from __future__ import annotations

import hashlib
import logging

from app.database.repositories import SignalRepository
from app.signals.models import ParsedSignal

logger = logging.getLogger(__name__)


class SignalDeduplicator:
    """Prevent re-execution of the same Telegram message.

    Primary key: (telegram_chat_id, telegram_message_id)
    Optional secondary: content hash of normalized signal fields.
    """

    def __init__(self, repository: SignalRepository) -> None:
        self._repo = repository

    def is_duplicate(self, chat_id: int, message_id: int) -> bool:
        exists = self._repo.exists(chat_id, message_id)
        if exists:
            logger.info(
                "Duplicate signal detected: chat_id=%s message_id=%s",
                chat_id,
                message_id,
            )
        return exists

    @staticmethod
    def compute_hash(signal: ParsedSignal) -> str:
        """Stable hash of core signal fields (not used as sole duplicate key)."""
        parts = [
            signal.direction.value if signal.direction else "",
            signal.symbol or "",
            f"{signal.entry:.5f}" if signal.entry is not None else "",
            ",".join(f"{tp:.5f}" for tp in signal.take_profits),
            f"{signal.stop_loss:.5f}" if signal.stop_loss is not None else "",
        ]
        payload = "|".join(parts)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]
