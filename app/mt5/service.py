"""MT5 subsystem facade for CLI and future GUI / trade engine."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.mt5.client import MT5Client, MT5Error
from app.mt5.gateway import MT5Gateway
from app.mt5.pricing import MT5PricingService
from app.mt5.symbols import MT5SymbolService

if TYPE_CHECKING:
    from app.config.settings import AppSettings

logger = logging.getLogger(__name__)


class MT5Service:
    """High-level MT5 access: connect, account, symbols, pricing."""

    def __init__(
        self,
        settings: AppSettings,
        gateway: MT5Gateway | None = None,
    ) -> None:
        self.settings = settings
        self.client = MT5Client(settings, gateway=gateway)
        self.symbols = MT5SymbolService(self.client, settings)
        self.pricing = MT5PricingService(self.client, self.symbols)

    def connect(self, *, path: str | None = None):
        return self.client.connect(path=path)

    def disconnect(self) -> None:
        self.client.disconnect()

    @property
    def is_connected(self) -> bool:
        return self.client.is_connected

    def validate_symbol(self, telegram_symbol: str, *, direction: str | None = None):
        return self.symbols.validate(telegram_symbol, direction=direction)

    def market_snapshot(self, telegram_symbol: str, direction: str):
        mapped = self.symbols.map_symbol(telegram_symbol)
        validation = self.symbols.validate(telegram_symbol, direction=direction)
        if not validation.ok:
            raise MT5Error(validation.reason)
        return self.pricing.snapshot(mapped, direction)
