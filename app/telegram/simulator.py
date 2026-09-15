"""Feed synthetic Telegram messages without a live Telegram connection.

Useful for development, Dry Run testing, and Phase 3 verification.
"""

from __future__ import annotations

import itertools
import logging
from datetime import datetime

from app.telegram.models import IncomingTelegramMessage
from app.telegram.pipeline import PipelineResult, SignalPipeline
from app.utils.time import utc_now

logger = logging.getLogger(__name__)

_msg_counter = itertools.count(900_000)


class TelegramSimulator:
    """Inject test signals into the pipeline as if they came from Telegram."""

    def __init__(
        self,
        pipeline: SignalPipeline,
        *,
        default_chat_id: int = -100999,
        default_source_name: str = "Simulation",
    ) -> None:
        self.pipeline = pipeline
        self.default_chat_id = default_chat_id
        self.default_source_name = default_source_name

    def inject(
        self,
        text: str,
        *,
        chat_id: int | None = None,
        message_id: int | None = None,
        source_name: str | None = None,
        date: datetime | None = None,
    ) -> PipelineResult:
        msg = IncomingTelegramMessage(
            chat_id=chat_id if chat_id is not None else self.default_chat_id,
            message_id=message_id if message_id is not None else next(_msg_counter),
            text=text,
            date=date or utc_now(),
            source_name=source_name or self.default_source_name,
            source_type="channel",
            is_edit=False,
        )
        logger.info("Simulating Telegram message id=%s", msg.message_id)
        return self.pipeline.process(msg)


SAMPLE_SELL_XAUUSD = """SELL XAUUSD 4291.5
TP 4287.5
TP 4283
TP 4277
SL 4306.5"""
