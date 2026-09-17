"""Telegram domain models."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class TelegramConnectionStatus(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    AUTH_REQUIRED = "auth_required"
    RECONNECTING = "reconnecting"
    ERROR = "error"


class AuthStep(str, Enum):
    IDLE = "idle"
    AWAITING_PHONE = "awaiting_phone"
    AWAITING_CODE = "awaiting_code"
    AWAITING_PASSWORD = "awaiting_password"
    AUTHORIZED = "authorized"
    FAILED = "failed"


class DialogType(str, Enum):
    GROUP = "group"
    CHANNEL = "channel"
    USER = "user"
    BOT = "bot"
    UNKNOWN = "unknown"


class TelegramDialog(BaseModel):
    """A chat/dialog available for monitoring selection."""

    telegram_id: int
    name: str
    dialog_type: DialogType = DialogType.UNKNOWN
    username: str | None = None
    unread_count: int = 0
    is_monitored: bool = False
    last_message_id: int | None = None


class IncomingTelegramMessage(BaseModel):
    """Normalized Telegram message event for the signal pipeline."""

    chat_id: int
    message_id: int
    text: str
    date: datetime | None = None
    source_name: str = ""
    source_type: str = "unknown"
    is_edit: bool = False
    is_deleted: bool = False
    sender_id: int | None = None
    reply_to_msg_id: int | None = None
    is_forwarded: bool = False
    raw: dict[str, Any] = Field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        return not (self.text or "").strip()


class AuthStatus(BaseModel):
    step: AuthStep = AuthStep.IDLE
    phone: str | None = None
    user_id: int | None = None
    username: str | None = None
    error: str | None = None
