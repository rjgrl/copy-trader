"""MT5 client — connection lifecycle, account/terminal status.

Does not place orders. Execution belongs to Phase 5–6 trade engine.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timezone

from app.config.defaults import (
    DEFAULT_RECONNECT_INITIAL_DELAY_SEC,
    DEFAULT_RECONNECT_MAX_ATTEMPTS,
    DEFAULT_RECONNECT_MAX_DELAY_SEC,
)
from app.config.settings import AppSettings
from app.mt5.gateway import MT5Gateway, RealMT5Gateway
from app.mt5.models import (
    MT5AccountInfo,
    MT5ConnectionStatus,
    MT5TerminalInfo,
)
from app.utils.reconnect import ReconnectPolicy

logger = logging.getLogger(__name__)

StatusCallback = Callable[[MT5ConnectionStatus], None]


class MT5Error(Exception):
    """Raised for MT5 connection / query failures."""


class MT5Client:
    """Owns the MetaTrader 5 terminal connection."""

    def __init__(
        self,
        settings: AppSettings,
        gateway: MT5Gateway | None = None,
        *,
        on_status: StatusCallback | None = None,
    ) -> None:
        self.settings = settings
        self._gateway = gateway
        self._on_status = on_status
        self.status = MT5ConnectionStatus.DISCONNECTED
        self._reconnect = ReconnectPolicy(
            initial_delay=DEFAULT_RECONNECT_INITIAL_DELAY_SEC,
            max_delay=DEFAULT_RECONNECT_MAX_DELAY_SEC,
            max_attempts=DEFAULT_RECONNECT_MAX_ATTEMPTS,
        )
        self.connected_at: datetime | None = None
        self.last_error: str | None = None

    @property
    def gateway(self) -> MT5Gateway:
        if self._gateway is None:
            self._gateway = RealMT5Gateway()
        return self._gateway

    @property
    def is_connected(self) -> bool:
        return self.status == MT5ConnectionStatus.CONNECTED

    def _set_status(self, status: MT5ConnectionStatus) -> None:
        self.status = status
        if self._on_status:
            try:
                self._on_status(status)
            except Exception:  # noqa: BLE001
                logger.exception("MT5 status callback failed")

    def connect(self, *, path: str | None = None) -> MT5AccountInfo:
        """Initialize connection to the local MT5 terminal."""
        self._set_status(MT5ConnectionStatus.CONNECTING)
        terminal_path = path or self.settings.mt5_terminal_path
        try:
            ok = self.gateway.initialize(terminal_path)
            if not ok:
                code, msg = self.gateway.last_error()
                self.last_error = f"{code}: {msg}"
                self._set_status(MT5ConnectionStatus.UNAVAILABLE)
                raise MT5Error(
                    f"MT5 initialize failed ({self.last_error}). "
                    "Is MetaTrader 5 installed and running?"
                )

            terminal = self.get_terminal_info()
            if terminal and not terminal.connected:
                self.last_error = "Terminal reported not connected to trade server"
                logger.warning(self.last_error)

            account = self.get_account_info()
            if account is None:
                code, msg = self.gateway.last_error()
                self.last_error = f"{code}: {msg}"
                self.gateway.shutdown()
                self._set_status(MT5ConnectionStatus.ERROR)
                raise MT5Error(f"MT5 account_info failed ({self.last_error})")

            self._reconnect.reset()
            self.connected_at = datetime.now(timezone.utc)
            self.last_error = None
            self._set_status(MT5ConnectionStatus.CONNECTED)
            logger.info(
                "MT5 connected login=%s server=%s balance=%.2f equity=%.2f",
                account.login,
                account.server,
                account.balance,
                account.equity,
            )
            return account
        except MT5Error:
            raise
        except Exception as exc:
            self.last_error = str(exc)
            self._set_status(MT5ConnectionStatus.ERROR)
            logger.exception("MT5 connect failed")
            raise MT5Error(f"MT5 connect failed: {exc}") from exc

    def disconnect(self) -> None:
        try:
            self.gateway.shutdown()
        except Exception:  # noqa: BLE001
            logger.exception("MT5 shutdown error")
        self._set_status(MT5ConnectionStatus.DISCONNECTED)
        self.connected_at = None
        logger.info("MT5 disconnected")

    async def reconnect(self) -> bool:
        """Controlled reconnect with exponential backoff."""
        import asyncio

        self._set_status(MT5ConnectionStatus.RECONNECTING)
        try:
            self.gateway.shutdown()
        except Exception:  # noqa: BLE001
            pass

        while True:
            if not await self._reconnect.wait():
                self._set_status(MT5ConnectionStatus.ERROR)
                return False
            try:
                self.connect()
                return True
            except MT5Error:
                logger.warning("MT5 reconnect attempt failed")

    def require_connected(self) -> None:
        if not self.is_connected:
            raise MT5Error("MT5 is not connected")

    def get_account_info(self) -> MT5AccountInfo | None:
        raw = self.gateway.account_info()
        if raw is None:
            return None
        return MT5AccountInfo(
            login=int(raw.login),
            name=str(getattr(raw, "name", "") or ""),
            server=str(getattr(raw, "server", "") or ""),
            company=str(getattr(raw, "company", "") or ""),
            currency=str(getattr(raw, "currency", "USD") or "USD"),
            balance=float(raw.balance),
            equity=float(raw.equity),
            margin=float(raw.margin),
            margin_free=float(raw.margin_free),
            margin_level=float(getattr(raw, "margin_level", 0.0) or 0.0),
            profit=float(getattr(raw, "profit", 0.0) or 0.0),
            leverage=int(getattr(raw, "leverage", 0) or 0),
            trade_allowed=bool(getattr(raw, "trade_allowed", False)),
            trade_expert=bool(getattr(raw, "trade_expert", False)),
            trade_mode=int(getattr(raw, "trade_mode", 0) or 0),
        )

    def get_terminal_info(self) -> MT5TerminalInfo | None:
        raw = self.gateway.terminal_info()
        if raw is None:
            return None
        return MT5TerminalInfo(
            connected=bool(getattr(raw, "connected", False)),
            trade_allowed=bool(getattr(raw, "trade_allowed", False)),
            name=str(getattr(raw, "name", "") or ""),
            company=str(getattr(raw, "company", "") or ""),
            path=str(getattr(raw, "path", "") or ""),
            build=int(getattr(raw, "build", 0) or 0),
            ping_last=int(getattr(raw, "ping_last", 0) or 0),
        )

    def status_summary(self) -> dict:
        account = self.get_account_info() if self.is_connected else None
        terminal = self.get_terminal_info() if self.is_connected else None
        return {
            "status": self.status.value,
            "last_error": self.last_error,
            "connected_at": self.connected_at.isoformat() if self.connected_at else None,
            "account": account.model_dump() if account else None,
            "terminal": terminal.model_dump() if terminal else None,
        }
