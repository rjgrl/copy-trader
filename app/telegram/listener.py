"""Event-driven Telegram listener for NEW messages only.

Startup safety:
  1. Establish per-chat message-ID watermarks (current top IDs).
  2. Activate the live listening point.
  3. Ignore any message with id <= watermark (historical / downtime).
  4. Never download history for execution.

Duplicate identity remains (chat_id, message_id) in SQLite.
Timestamps are stored for latency/display — never as the primary gate.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from telethon import events

from app.telegram.client import TelegramClientService
from app.telegram.models import IncomingTelegramMessage
from app.telegram.sources import TelegramSourceManager, classify_entity, entity_display_name
from app.trading.startup import LiveListeningPoint
from app.utils.time import utc_now

logger = logging.getLogger(__name__)

MessageHandler = Callable[[IncomingTelegramMessage], Awaitable[None]]


class TelegramListener:
    """Listen for future Telegram messages from enabled sources only."""

    def __init__(
        self,
        client_service: TelegramClientService,
        source_manager: TelegramSourceManager,
        *,
        on_message: MessageHandler,
        on_edit: MessageHandler | None = None,
        on_delete: MessageHandler | None = None,
        listening_point: LiveListeningPoint | None = None,
    ) -> None:
        self._client_service = client_service
        self._sources = source_manager
        self._on_message = on_message
        self._on_edit = on_edit
        self._on_delete = on_delete
        self.listening_point = listening_point
        self._started_at: datetime | None = None
        self._handlers_registered = False
        self._listening = False

    @property
    def is_listening(self) -> bool:
        return self._listening

    @property
    def started_at(self) -> datetime | None:
        return self._started_at

    async def establish_watermarks(self) -> LiveListeningPoint:
        """Query current top message IDs for enabled sources — do NOT execute them.

        This is the live listening boundary. Messages at or below these IDs are
        treated as historical (including anything received during downtime).
        """
        if self.listening_point is None:
            raise RuntimeError("listening_point is required before establish_watermarks")
        if not self._client_service.is_connected:
            raise RuntimeError("Telegram must be connected to establish watermarks")

        client = self._client_service.client
        for source in self._sources.list_enabled():
            chat_id = source.telegram_id
            top_id = 0
            try:
                messages = await client.get_messages(chat_id, limit=1)
                if messages:
                    top_id = int(messages[0].id)
                logger.info(
                    "Watermark for %s (%s): top_message_id=%s (will NOT execute <= this)",
                    source.name,
                    chat_id,
                    top_id,
                )
            except Exception:
                logger.exception(
                    "Failed to fetch top message for %s (%s) — using DB last_message_id=%s",
                    source.name,
                    chat_id,
                    source.last_message_id,
                )
                top_id = int(source.last_message_id or 0)

            if source.last_message_id:
                top_id = max(top_id, int(source.last_message_id))
            self.listening_point.set_watermark(chat_id, top_id)

        return self.listening_point

    def start(self) -> None:
        """Register event handlers. Does not fetch history for execution."""
        if self._handlers_registered:
            logger.debug("Telegram handlers already registered")
            self._listening = True
            return
        if not self._client_service.is_connected:
            raise RuntimeError("Cannot start listener: Telegram not connected")
        if self.listening_point is None or not self.listening_point.active:
            raise RuntimeError(
                "Cannot start listener: live listening point not active. "
                "Call establish_watermarks() and activate_listening_point() first."
            )

        client = self._client_service.client

        @client.on(events.NewMessage)
        async def _on_new_message(event: events.NewMessage.Event) -> None:
            await self._handle_event(event, is_edit=False)

        @client.on(events.MessageEdited)
        async def _on_edited(event: events.MessageEdited.Event) -> None:
            await self._handle_event(event, is_edit=True)

        @client.on(events.MessageDeleted)
        async def _on_deleted(event: events.MessageDeleted.Event) -> None:
            await self._handle_deleted(event)

        self._handlers_registered = True
        self._listening = True
        self._started_at = utc_now()
        enabled = self._sources.enabled_chat_ids()
        logger.info(
            "Telegram listener started (NEW messages only). Enabled sources: %s",
            len(enabled),
        )
        logger.info(
            "Live point session=%s established_at=%s — history will NOT be executed",
            self.listening_point.session_id,
            self.listening_point.established_at.isoformat(),
        )

    def stop(self) -> None:
        """Mark listener stopped. Handlers remain but ignore events."""
        self._listening = False
        if self.listening_point:
            self.listening_point.active = False
        logger.info("Telegram listener stopped")

    async def _handle_deleted(self, event: events.MessageDeleted.Event) -> None:
        """V1: log deletion only — never close or modify MT5 positions."""
        if not self._listening:
            return
        chat_id = getattr(event, "chat_id", None)
        deleted_ids = list(getattr(event, "deleted_ids", []) or [])
        logger.info(
            "MESSAGE_DELETED chat=%s ids=%s — not modifying MT5 positions (V1)",
            chat_id,
            deleted_ids,
        )
        if not self._on_delete or chat_id is None:
            return
        for msg_id in deleted_ids:
            incoming = IncomingTelegramMessage(
                chat_id=int(chat_id),
                message_id=int(msg_id),
                text="",
                date=utc_now(),
                source_name=self._sources.get_source_name(int(chat_id)),
                is_deleted=True,
            )
            await self._on_delete(incoming)

    async def _handle_event(self, event, *, is_edit: bool) -> None:
        if not self._listening:
            return

        try:
            chat_id = int(event.chat_id)
        except Exception:  # noqa: BLE001
            logger.debug("Ignoring event without chat_id")
            return

        if not self._sources.is_enabled(chat_id):
            return

        message = event.message
        if message is None:
            return
        text = (message.message or message.text or "") if message else ""
        if not text.strip() and not is_edit:
            return

        message_id = int(message.id)

        # Historical / downtime gate — authoritative by message ID, not PC clock
        if (
            not is_edit
            and self.listening_point is not None
            and self.listening_point.is_historical(chat_id, message_id)
        ):
            logger.warning(
                "HISTORICAL_SIGNAL_SKIPPED chat=%s msg=%s watermark=%s — "
                "received during/before live point; will NOT execute",
                chat_id,
                message_id,
                self.listening_point.watermarks.get(chat_id),
            )
            # Still advance touch metadata but do not execute
            self._sources.touch_last_message(chat_id, message_id, at=utc_now())
            if self._on_message:
                incoming = IncomingTelegramMessage(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=text,
                    date=_msg_date(message),
                    source_name=self._sources.get_source_name(chat_id),
                    raw={"historical": True},
                )
                # Pipeline will mark SKIPPED when historical flag set — pass via raw
                await self._on_message(incoming)
            return

        source_name = self._sources.get_source_name(chat_id)
        source_type = "unknown"
        sender_id = None
        reply_to = None
        is_forwarded = False
        try:
            chat = await event.get_chat()
            source_type = classify_entity(chat).value
            if source_name.startswith("chat:"):
                source_name = entity_display_name(chat)
        except Exception:  # noqa: BLE001
            pass
        try:
            sender = await event.get_sender()
            sender_id = int(getattr(sender, "id", 0)) or None
        except Exception:  # noqa: BLE001
            pass
        reply_to = getattr(message, "reply_to_msg_id", None)
        is_forwarded = bool(getattr(message, "fwd_from", None))

        incoming = IncomingTelegramMessage(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            date=_msg_date(message),
            source_name=source_name,
            source_type=source_type,
            is_edit=is_edit,
            sender_id=sender_id,
            reply_to_msg_id=int(reply_to) if reply_to else None,
            is_forwarded=is_forwarded,
        )

        self._sources.touch_last_message(chat_id, message_id, at=utc_now())

        if is_edit:
            logger.info(
                "Telegram message edited: chat=%s msg=%s source=%s",
                chat_id,
                message_id,
                source_name,
            )
            if self._on_edit:
                await self._on_edit(incoming)
            return

        logger.info(
            "Telegram message received: chat=%s msg=%s source=%s",
            chat_id,
            message_id,
            source_name,
        )
        await self._on_message(incoming)


def _msg_date(message) -> datetime | None:
    msg_date = getattr(message, "date", None)
    if msg_date is not None and msg_date.tzinfo is None:
        msg_date = msg_date.replace(tzinfo=timezone.utc)
    return msg_date
