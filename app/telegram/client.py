"""Telethon client wrapper with connect, auth, and reconnect."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from telethon import TelegramClient
from telethon.tl.types import User

from app.config.defaults import (
    DEFAULT_RECONNECT_INITIAL_DELAY_SEC,
    DEFAULT_RECONNECT_MAX_ATTEMPTS,
    DEFAULT_RECONNECT_MAX_DELAY_SEC,
)
from app.config.settings import AppSettings
from app.telegram.auth import (
    TelegramAuthError,
    TelegramAuthenticator,
    cli_code_provider,
    cli_password_provider,
    cli_phone_provider,
)
from app.telegram.models import AuthStatus, AuthStep, TelegramConnectionStatus
from app.utils.reconnect import ReconnectPolicy

logger = logging.getLogger(__name__)

StatusCallback = Callable[[TelegramConnectionStatus], None]


class TelegramClientService:
    """Owns the Telethon session and connection lifecycle.

    Does not download chat history on connect. Callers register listeners
    for future NewMessage events only.
    """

    def __init__(
        self,
        settings: AppSettings,
        *,
        on_status: StatusCallback | None = None,
    ) -> None:
        self.settings = settings
        self._on_status = on_status
        self._client: TelegramClient | None = None
        self.status = TelegramConnectionStatus.DISCONNECTED
        self.auth_status = AuthStatus()
        self._reconnect = ReconnectPolicy(
            initial_delay=DEFAULT_RECONNECT_INITIAL_DELAY_SEC,
            max_delay=DEFAULT_RECONNECT_MAX_DELAY_SEC,
            max_attempts=DEFAULT_RECONNECT_MAX_ATTEMPTS,
        )

    @property
    def client(self) -> TelegramClient:
        if self._client is None:
            raise RuntimeError("Telegram client is not initialized")
        return self._client

    @property
    def is_connected(self) -> bool:
        return (
            self._client is not None
            and self._client.is_connected()
            and self.status == TelegramConnectionStatus.CONNECTED
        )

    @property
    def is_authorized(self) -> bool:
        return self.auth_status.step == AuthStep.AUTHORIZED

    def _set_status(self, status: TelegramConnectionStatus) -> None:
        self.status = status
        if self._on_status:
            try:
                self._on_status(status)
            except Exception:  # noqa: BLE001
                logger.exception("Status callback failed")

    def _build_client(self) -> TelegramClient:
        api_id = self.settings.telegram_api_id
        api_hash = self.settings.telegram_api_hash
        if not api_id or not api_hash:
            raise TelegramAuthError(
                "Telegram API ID and API Hash are required. "
                "Set TELEGRAM_API_ID and TELEGRAM_API_HASH in .env "
                "(create an app at https://my.telegram.org/apps)."
            )

        session_path = self.settings.telegram_session_path
        session_path.parent.mkdir(parents=True, exist_ok=True)
        # Telethon appends .session; pass path without forcing extension twice
        session = str(session_path)
        logger.info("Using Telegram session file: %s.session", session)
        return TelegramClient(
            session,
            api_id,
            api_hash,
            # Receive updates for new messages; do not catch up history aggressively
            receive_updates=True,
        )

    async def connect(
        self,
        *,
        interactive_auth: bool = False,
        get_phone=None,
        get_code=None,
        get_password=None,
    ) -> AuthStatus:
        """Connect to Telegram. Optionally run interactive auth."""
        self._set_status(TelegramConnectionStatus.CONNECTING)
        try:
            if self._client is None:
                self._client = self._build_client()

            await self._client.connect()

            if not await self._client.is_user_authorized():
                self._set_status(TelegramConnectionStatus.AUTH_REQUIRED)
                if not interactive_auth and get_phone is None:
                    self.auth_status = AuthStatus(
                        step=AuthStep.AWAITING_PHONE,
                        error="Session not authorized — complete Telegram login",
                    )
                    return self.auth_status

                authenticator = TelegramAuthenticator(
                    self._client,
                    get_phone=get_phone or (cli_phone_provider if interactive_auth else None),
                    get_code=get_code or (cli_code_provider if interactive_auth else None),
                    get_password=get_password
                    or (cli_password_provider if interactive_auth else None),
                )
                self.auth_status = await authenticator.ensure_authorized()
            else:
                authenticator = TelegramAuthenticator(self._client)
                self.auth_status = await authenticator._mark_authorized()

            self._reconnect.reset()
            self._set_status(TelegramConnectionStatus.CONNECTED)
            return self.auth_status
        except TelegramAuthError:
            self._set_status(TelegramConnectionStatus.AUTH_REQUIRED)
            raise
        except Exception:
            self._set_status(TelegramConnectionStatus.ERROR)
            logger.exception("Telegram connect failed")
            raise

    async def disconnect(self) -> None:
        if self._client is not None and self._client.is_connected():
            await self._client.disconnect()
        self._set_status(TelegramConnectionStatus.DISCONNECTED)
        logger.info("Telegram disconnected")

    async def reconnect(self) -> bool:
        """Attempt a controlled reconnect. Returns True on success."""
        self._set_status(TelegramConnectionStatus.RECONNECTING)
        while True:
            if not await self._reconnect.wait():
                self._set_status(TelegramConnectionStatus.ERROR)
                return False
            try:
                if self._client is None:
                    self._client = self._build_client()
                if not self._client.is_connected():
                    await self._client.connect()
                if not await self._client.is_user_authorized():
                    self._set_status(TelegramConnectionStatus.AUTH_REQUIRED)
                    return False
                self._reconnect.reset()
                self._set_status(TelegramConnectionStatus.CONNECTED)
                logger.info("Telegram reconnected")
                return True
            except Exception:
                logger.exception("Telegram reconnect attempt failed")

    async def get_me(self) -> User | None:
        if not self.is_connected:
            return None
        me = await self.client.get_me()
        return me if isinstance(me, User) else None

    async def run_until_disconnected(self) -> None:
        """Block until the client disconnects (used by listener loops)."""
        await self.client.run_until_disconnected()

    def session_file_exists(self) -> bool:
        path = Path(str(self.settings.telegram_session_path) + ".session")
        return path.exists()


async def create_connected_client(
    settings: AppSettings,
    *,
    interactive_auth: bool = False,
) -> TelegramClientService:
    """Factory helper used by CLI tools."""
    service = TelegramClientService(settings)
    await service.connect(interactive_auth=interactive_auth)
    return service
