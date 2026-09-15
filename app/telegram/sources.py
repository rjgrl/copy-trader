"""Telegram source (dialog) management."""

from __future__ import annotations

import logging
from datetime import datetime

from telethon.tl.types import Channel, Chat, User

from app.database.models import TelegramSourceRecord
from app.database.repositories import TelegramSourceRepository
from app.telegram.client import TelegramClientService
from app.telegram.models import DialogType, TelegramDialog
from app.utils.time import utc_now

logger = logging.getLogger(__name__)


def classify_entity(entity: object) -> DialogType:
    if isinstance(entity, Channel):
        if getattr(entity, "megagroup", False) or getattr(entity, "gigagroup", False):
            return DialogType.GROUP
        return DialogType.CHANNEL
    if isinstance(entity, Chat):
        return DialogType.GROUP
    if isinstance(entity, User):
        if getattr(entity, "bot", False):
            return DialogType.BOT
        return DialogType.USER
    return DialogType.UNKNOWN


def entity_display_name(entity: object) -> str:
    title = getattr(entity, "title", None)
    if title:
        return str(title)
    first = getattr(entity, "first_name", "") or ""
    last = getattr(entity, "last_name", "") or ""
    name = f"{first} {last}".strip()
    if name:
        return name
    username = getattr(entity, "username", None)
    if username:
        return f"@{username}"
    return f"id:{getattr(entity, 'id', '?')}"


class TelegramSourceManager:
    """List Telegram dialogs and persist enabled monitoring sources."""

    def __init__(
        self,
        client_service: TelegramClientService,
        repository: TelegramSourceRepository,
    ) -> None:
        self._client_service = client_service
        self._repo = repository

    def list_saved(self) -> list[TelegramSourceRecord]:
        return self._repo.list_all()

    def list_enabled(self) -> list[TelegramSourceRecord]:
        return self._repo.list_enabled()

    def enabled_chat_ids(self) -> set[int]:
        return {s.telegram_id for s in self._repo.list_enabled()}

    def is_enabled(self, chat_id: int) -> bool:
        return chat_id in self.enabled_chat_ids()

    def set_enabled(self, telegram_id: int, enabled: bool) -> None:
        self._repo.set_enabled(telegram_id, enabled)
        logger.info(
            "Telegram source %s %s",
            telegram_id,
            "enabled" if enabled else "disabled",
        )

    def remove(self, telegram_id: int) -> None:
        self._repo.delete(telegram_id)
        logger.info("Removed Telegram source %s", telegram_id)

    def upsert_source(
        self,
        *,
        telegram_id: int,
        name: str,
        source_type: str,
        enabled: bool = True,
    ) -> int:
        record = TelegramSourceRecord(
            id=None,
            telegram_id=telegram_id,
            name=name,
            source_type=source_type,
            enabled=enabled,
            connection_status="configured",
        )
        return self._repo.upsert(record)

    async def fetch_dialogs(self, *, limit: int | None = None) -> list[TelegramDialog]:
        """Fetch dialogs from the live Telegram account for GUI selection."""
        if not self._client_service.is_connected:
            raise RuntimeError("Telegram is not connected")

        monitored = {s.telegram_id: s for s in self._repo.list_all()}
        results: list[TelegramDialog] = []

        async for dialog in self._client_service.client.iter_dialogs(limit=limit):
            entity = dialog.entity
            telegram_id = int(dialog.id)
            dtype = classify_entity(entity)
            # Prefer groups/channels for signal sources, but still list others
            results.append(
                TelegramDialog(
                    telegram_id=telegram_id,
                    name=dialog.name or entity_display_name(entity),
                    dialog_type=dtype,
                    username=getattr(entity, "username", None),
                    unread_count=int(dialog.unread_count or 0),
                    is_monitored=telegram_id in monitored and monitored[telegram_id].enabled,
                )
            )

        results.sort(key=lambda d: (not d.is_monitored, d.name.lower()))
        logger.info("Fetched %s Telegram dialogs", len(results))
        return results

    async def sync_selected(
        self,
        selections: list[tuple[int, str, str, bool]],
    ) -> None:
        """Upsert a batch of (telegram_id, name, type, enabled) selections."""
        for telegram_id, name, source_type, enabled in selections:
            self.upsert_source(
                telegram_id=telegram_id,
                name=name,
                source_type=source_type,
                enabled=enabled,
            )

    def touch_last_message(
        self,
        telegram_id: int,
        message_id: int,
        *,
        at: datetime | None = None,
        signal: bool = False,
    ) -> None:
        """Update last received message metadata for a source."""
        existing = None
        for src in self._repo.list_all():
            if src.telegram_id == telegram_id:
                existing = src
                break
        if existing is None:
            return
        now = at or utc_now()
        existing.last_message_id = message_id
        existing.last_message_at = now
        if signal:
            existing.last_signal_at = now
        existing.connection_status = "listening"
        self._repo.upsert(existing)

    def get_source_name(self, chat_id: int) -> str:
        for src in self._repo.list_all():
            if src.telegram_id == chat_id:
                return src.name
        return f"chat:{chat_id}"
