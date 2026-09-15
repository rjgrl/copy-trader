"""MT5 domain models — account, terminal, symbol specs, ticks."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class MT5ConnectionStatus(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    ERROR = "error"
    UNAVAILABLE = "unavailable"


class SymbolTradeMode(str, Enum):
    DISABLED = "disabled"
    LONGONLY = "longonly"
    SHORTONLY = "shortonly"
    CLOSEONLY = "closeonly"
    FULL = "full"
    UNKNOWN = "unknown"


# MetaTrader5 SYMBOL_TRADE_MODE_* integers
_TRADE_MODE_MAP = {
    0: SymbolTradeMode.DISABLED,
    1: SymbolTradeMode.LONGONLY,
    2: SymbolTradeMode.SHORTONLY,
    3: SymbolTradeMode.CLOSEONLY,
    4: SymbolTradeMode.FULL,
}


def map_trade_mode(value: int | None) -> SymbolTradeMode:
    if value is None:
        return SymbolTradeMode.UNKNOWN
    return _TRADE_MODE_MAP.get(int(value), SymbolTradeMode.UNKNOWN)


class MT5AccountInfo(BaseModel):
    login: int
    name: str = ""
    server: str = ""
    company: str = ""
    currency: str = "USD"
    balance: float = 0.0
    equity: float = 0.0
    margin: float = 0.0
    margin_free: float = 0.0
    margin_level: float = 0.0
    profit: float = 0.0
    leverage: int = 0
    trade_allowed: bool = False
    trade_expert: bool = False
    trade_mode: int = 0  # 0 demo, 1 contest, 2 real


class MT5TerminalInfo(BaseModel):
    connected: bool = False
    trade_allowed: bool = False
    name: str = ""
    company: str = ""
    path: str = ""
    build: int = 0
    ping_last: int = 0


class SymbolSpec(BaseModel):
    """Broker symbol specification — never hard-code point sizes."""

    name: str
    digits: int
    point: float
    trade_tick_size: float
    trade_tick_value: float
    trade_contract_size: float
    volume_min: float
    volume_max: float
    volume_step: float
    trade_mode: SymbolTradeMode = SymbolTradeMode.UNKNOWN
    trade_mode_raw: int = 0
    spread_points: int = 0  # broker-reported spread in points (may be stale)
    stops_level: int = 0
    visible: bool = True
    selected: bool = False

    @property
    def is_tradable_for_new_orders(self) -> bool:
        return self.trade_mode in {
            SymbolTradeMode.FULL,
            SymbolTradeMode.LONGONLY,
            SymbolTradeMode.SHORTONLY,
        }

    def price_to_points(self, price_diff: float) -> float:
        if self.point <= 0:
            return 0.0
        return abs(price_diff) / self.point

    def points_to_price(self, points: float) -> float:
        return points * self.point


class Tick(BaseModel):
    symbol: str
    bid: float
    ask: float
    last: float = 0.0
    time: datetime | None = None
    time_msc: int | None = None

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0

    @property
    def spread_price(self) -> float:
        return max(0.0, self.ask - self.bid)

    def execution_price(self, direction: str) -> float:
        """BUY uses ask; SELL uses bid."""
        d = direction.upper()
        if d in {"BUY", "LONG"}:
            return self.ask
        return self.bid


class SymbolValidationResult(BaseModel):
    ok: bool
    telegram_symbol: str
    mt5_symbol: str
    reasons: list[str] = Field(default_factory=list)
    spec: SymbolSpec | None = None
    tick: Tick | None = None

    @property
    def reason(self) -> str:
        return "; ".join(self.reasons) if self.reasons else ""


class MarketSnapshot(BaseModel):
    """Pricing snapshot used by intelligent entry validation."""

    symbol: str
    tick: Tick
    spec: SymbolSpec
    spread_price: float
    spread_points: float
    execution_price: float
    direction: str
