"""Telegram authentication helpers.

Never logs OTP codes, 2FA passwords, or API secrets.
Password is only requested when Telegram raises SessionPasswordNeededError.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from telethon.errors import (
    FloodWaitError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    PhoneNumberInvalidError,
    SessionPasswordNeededError,
)

from app.telegram.models import AuthStatus, AuthStep

if TYPE_CHECKING:
    from telethon import TelegramClient

logger = logging.getLogger(__name__)

PhoneProvider = Callable[[], Awaitable[str]]
CodeProvider = Callable[[], Awaitable[str]]
PasswordProvider = Callable[[], Awaitable[str]]


class TelegramAuthError(Exception):
    """Raised when interactive Telegram authentication fails."""


class TelegramAuthenticator:
    """Drive Telethon sign-in using injectable phone/code/password providers."""

    def __init__(
        self,
        client: TelegramClient,
        *,
        get_phone: PhoneProvider | None = None,
        get_code: CodeProvider | None = None,
        get_password: PasswordProvider | None = None,
    ) -> None:
        self._client = client
        self._get_phone = get_phone
        self._get_code = get_code
        self._get_password = get_password
        self.status = AuthStatus()

    async def ensure_authorized(self) -> AuthStatus:
        """Connect and authorize if needed. Returns final auth status."""
        if not self._client.is_connected():
            await self._client.connect()

        if await self._client.is_user_authorized():
            return await self._mark_authorized()

        self.status = AuthStatus(step=AuthStep.AWAITING_PHONE)
        phone = await self._require_phone()
        self.status.phone = _mask_phone(phone)
        logger.info("Sending Telegram login code to %s", self.status.phone)

        try:
            await self._client.send_code_request(phone)
        except PhoneNumberInvalidError as exc:
            self.status = AuthStatus(step=AuthStep.FAILED, error="Invalid phone number")
            raise TelegramAuthError("Invalid phone number") from exc
        except FloodWaitError as exc:
            msg = f"Flood wait: retry after {exc.seconds}s"
            self.status = AuthStatus(step=AuthStep.FAILED, error=msg)
            raise TelegramAuthError(msg) from exc

        self.status.step = AuthStep.AWAITING_CODE
        code = await self._require_code()
        # Intentionally do not log the code

        try:
            await self._client.sign_in(phone=phone, code=code)
        except SessionPasswordNeededError:
            self.status.step = AuthStep.AWAITING_PASSWORD
            logger.info("Telegram 2FA password required")
            password = await self._require_password()
            try:
                await self._client.sign_in(password=password)
            except Exception as exc:  # noqa: BLE001
                self.status = AuthStatus(
                    step=AuthStep.FAILED,
                    error="2FA authentication failed",
                )
                raise TelegramAuthError("2FA authentication failed") from exc
        except PhoneCodeInvalidError as exc:
            self.status = AuthStatus(step=AuthStep.FAILED, error="Invalid login code")
            raise TelegramAuthError("Invalid login code") from exc
        except PhoneCodeExpiredError as exc:
            self.status = AuthStatus(step=AuthStep.FAILED, error="Login code expired")
            raise TelegramAuthError("Login code expired") from exc

        if not await self._client.is_user_authorized():
            self.status = AuthStatus(step=AuthStep.FAILED, error="Authorization failed")
            raise TelegramAuthError("Authorization failed")

        return await self._mark_authorized()

    async def _mark_authorized(self) -> AuthStatus:
        me = await self._client.get_me()
        self.status = AuthStatus(
            step=AuthStep.AUTHORIZED,
            user_id=getattr(me, "id", None),
            username=getattr(me, "username", None),
            phone=_mask_phone(getattr(me, "phone", None) or self.status.phone),
        )
        logger.info(
            "Telegram authorized (user_id=%s username=%s)",
            self.status.user_id,
            self.status.username or "—",
        )
        return self.status

    async def _require_phone(self) -> str:
        if self._get_phone is None:
            raise TelegramAuthError("Phone provider not configured")
        phone = (await self._get_phone()).strip()
        if not phone:
            raise TelegramAuthError("Phone number is required")
        return phone

    async def _require_code(self) -> str:
        if self._get_code is None:
            raise TelegramAuthError("Code provider not configured")
        code = (await self._get_code()).strip()
        if not code:
            raise TelegramAuthError("Login code is required")
        return code

    async def _require_password(self) -> str:
        if self._get_password is None:
            raise TelegramAuthError(
                "Telegram 2FA password required but no password provider configured"
            )
        password = await self._get_password()
        if not password:
            raise TelegramAuthError("2FA password is required")
        return password


def _mask_phone(phone: str | None) -> str | None:
    if not phone:
        return None
    digits = "".join(ch for ch in phone if ch.isdigit() or ch == "+")
    if len(digits) <= 4:
        return "****"
    return f"{digits[:3]}****{digits[-2:]}"


async def cli_phone_provider() -> str:
    return input("Telegram phone (with country code, e.g. +60123456789): ").strip()


async def cli_code_provider() -> str:
    return input("Telegram login code: ").strip()


async def cli_password_provider() -> str:
    # getpass avoids echoing; still never logged
    import getpass

    return getpass.getpass("Telegram 2FA password: ")
