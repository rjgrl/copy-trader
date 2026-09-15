"""MT5 gateway abstraction — real package vs mock for tests.

Unit tests MUST use MockMT5Gateway. Never call order_send in Phase 4.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class MT5Gateway(Protocol):
    """Minimal MT5 surface used by the application."""

    def initialize(self, path: str | None = None) -> bool: ...

    def shutdown(self) -> None: ...

    def last_error(self) -> tuple[int, str]: ...

    def terminal_info(self) -> Any | None: ...

    def account_info(self) -> Any | None: ...

    def symbol_info(self, symbol: str) -> Any | None: ...

    def symbol_info_tick(self, symbol: str) -> Any | None: ...

    def symbol_select(self, symbol: str, enable: bool = True) -> bool: ...

    def symbols_get(self, group: str | None = None) -> tuple | None: ...

    def order_send(self, request: dict) -> Any | None: ...

    def order_check(self, request: dict) -> Any | None: ...


class RealMT5Gateway:
    """Thin wrapper around the official MetaTrader5 package."""

    def __init__(self) -> None:
        import MetaTrader5 as mt5

        self._mt5 = mt5

    def initialize(self, path: str | None = None) -> bool:
        if path:
            return bool(self._mt5.initialize(path=path))
        return bool(self._mt5.initialize())

    def shutdown(self) -> None:
        self._mt5.shutdown()

    def last_error(self) -> tuple[int, str]:
        err = self._mt5.last_error()
        if err is None:
            return (0, "OK")
        return (int(err[0]), str(err[1]))

    def terminal_info(self) -> Any | None:
        return self._mt5.terminal_info()

    def account_info(self) -> Any | None:
        return self._mt5.account_info()

    def symbol_info(self, symbol: str) -> Any | None:
        return self._mt5.symbol_info(symbol)

    def symbol_info_tick(self, symbol: str) -> Any | None:
        return self._mt5.symbol_info_tick(symbol)

    def symbol_select(self, symbol: str, enable: bool = True) -> bool:
        return bool(self._mt5.symbol_select(symbol, enable))

    def symbols_get(self, group: str | None = None) -> tuple | None:
        if group:
            return self._mt5.symbols_get(group=group)
        return self._mt5.symbols_get()

    def order_send(self, request: dict) -> Any | None:
        return self._mt5.order_send(request)

    def order_check(self, request: dict) -> Any | None:
        return self._mt5.order_check(request)


@dataclass
class _FakeNamed:
    """Simple attribute bag mimicking MT5 namedtuples."""

    _data: dict[str, Any] = field(default_factory=dict)

    def __getattr__(self, item: str) -> Any:
        if item.startswith("_"):
            raise AttributeError(item)
        try:
            return self._data[item]
        except KeyError as exc:
            raise AttributeError(item) from exc

    def _asdict(self) -> dict[str, Any]:
        return dict(self._data)


@dataclass
class MockSymbol:
    name: str
    digits: int = 2
    point: float = 0.01
    trade_tick_size: float = 0.01
    trade_tick_value: float = 1.0
    trade_contract_size: float = 100.0
    volume_min: float = 0.01
    volume_max: float = 100.0
    volume_step: float = 0.01
    trade_mode: int = 4  # FULL
    spread: int = 30
    trade_stops_level: int = 0
    filling_mode: int = 2  # IOC bit flag
    visible: bool = True
    select: bool = True
    bid: float = 4293.2
    ask: float = 4293.5


class MockMT5Gateway:
    """In-memory MT5 stub for unit tests — never sends real trades."""

    def __init__(self, symbols: dict[str, MockSymbol] | None = None) -> None:
        self.initialized = False
        self.init_fail = False
        self.path: str | None = None
        self._error = (1, "Success")
        self.account = _FakeNamed(
            {
                "login": 12345678,
                "name": "Demo Trader",
                "server": "Mock-Server",
                "company": "Mock Broker",
                "currency": "USD",
                "balance": 10000.0,
                "equity": 10050.0,
                "margin": 100.0,
                "margin_free": 9950.0,
                "margin_level": 10050.0,
                "profit": 50.0,
                "leverage": 100,
                "trade_allowed": True,
                "trade_expert": True,
                "trade_mode": 0,  # demo
            }
        )
        self.terminal = _FakeNamed(
            {
                "connected": True,
                "trade_allowed": True,
                "name": "Mock MetaTrader 5",
                "company": "Mock Broker",
                "path": r"C:\Mock\terminal64.exe",
                "build": 4000,
                "ping_last": 12000,
            }
        )
        default = {
            "XAUUSD": MockSymbol("XAUUSD"),
            "XAUUSDm": MockSymbol("XAUUSDm", bid=4293.2, ask=4293.5),
            "GOLD#": MockSymbol("GOLD#", bid=4293.2, ask=4293.5),
            "EURUSD": MockSymbol(
                "EURUSD",
                digits=5,
                point=0.00001,
                trade_tick_size=0.00001,
                trade_tick_value=1.0,
                trade_contract_size=100000.0,
                spread=20,
                bid=1.08500,
                ask=1.08520,
            ),
        }
        self.symbols = symbols if symbols is not None else default
        self.select_calls: list[tuple[str, bool]] = []
        self.orders_sent: list[dict] = []
        self._ticket_seq = itertools.count(90001)
        self.fail_retcodes: list[int | None] = []  # queue of retcodes per order_send

    def initialize(self, path: str | None = None) -> bool:
        self.path = path
        if self.init_fail:
            self._error = (-10005, "IPC initialize failed")
            self.initialized = False
            return False
        self.initialized = True
        self._error = (1, "Success")
        return True

    def shutdown(self) -> None:
        self.initialized = False

    def last_error(self) -> tuple[int, str]:
        return self._error

    def terminal_info(self) -> Any | None:
        if not self.initialized:
            return None
        return self.terminal

    def account_info(self) -> Any | None:
        if not self.initialized:
            return None
        return self.account

    def symbol_info(self, symbol: str) -> Any | None:
        if not self.initialized:
            return None
        sym = self.symbols.get(symbol)
        if sym is None:
            return None
        return _FakeNamed(
            {
                "name": sym.name,
                "digits": sym.digits,
                "point": sym.point,
                "trade_tick_size": sym.trade_tick_size,
                "trade_tick_value": sym.trade_tick_value,
                "trade_contract_size": sym.trade_contract_size,
                "volume_min": sym.volume_min,
                "volume_max": sym.volume_max,
                "volume_step": sym.volume_step,
                "trade_mode": sym.trade_mode,
                "spread": sym.spread,
                "trade_stops_level": sym.trade_stops_level,
                "filling_mode": sym.filling_mode,
                "visible": sym.visible,
                "select": sym.select,
            }
        )

    def symbol_info_tick(self, symbol: str) -> Any | None:
        if not self.initialized:
            return None
        sym = self.symbols.get(symbol)
        if sym is None:
            return None
        now = datetime.now(timezone.utc)
        return _FakeNamed(
            {
                "bid": sym.bid,
                "ask": sym.ask,
                "last": sym.bid,
                "time": int(now.timestamp()),
                "time_msc": int(now.timestamp() * 1000),
                "volume": 0,
                "flags": 0,
                "volume_real": 0.0,
            }
        )

    def symbol_select(self, symbol: str, enable: bool = True) -> bool:
        self.select_calls.append((symbol, enable))
        if symbol not in self.symbols:
            self._error = (-1, "Symbol not found")
            return False
        self.symbols[symbol].select = enable
        return True

    def symbols_get(self, group: str | None = None) -> tuple | None:
        if not self.initialized:
            return None
        items = []
        for sym in self.symbols.values():
            if group and group not in sym.name:
                continue
            info = self.symbol_info(sym.name)
            if info:
                items.append(info)
        return tuple(items)

    def set_tick(self, symbol: str, bid: float, ask: float) -> None:
        self.symbols[symbol].bid = bid
        self.symbols[symbol].ask = ask

    def order_send(self, request: dict) -> Any | None:
        if not self.initialized:
            self._error = (-1, "Not initialized")
            return None
        self.orders_sent.append(dict(request))
        override = None
        if self.fail_retcodes:
            override = self.fail_retcodes.pop(0)
        retcode = 10009 if override is None else int(override)
        ticket = next(self._ticket_seq)
        return _FakeNamed(
            {
                "retcode": retcode,
                "deal": ticket if retcode in {10009, 10010} else 0,
                "order": ticket if retcode in {10009, 10010, 10008} else 0,
                "volume": float(request.get("volume", 0)),
                "price": float(request.get("price", 0)),
                "bid": 0.0,
                "ask": 0.0,
                "comment": str(request.get("comment", "")),
                "request_id": 1,
                "retcode_external": 0,
            }
        )

    def order_check(self, request: dict) -> Any | None:
        return _FakeNamed(
            {
                "retcode": 0,
                "balance": 10000.0,
                "equity": 10000.0,
                "profit": 0.0,
                "margin": 10.0,
                "margin_free": 9990.0,
                "margin_level": 0.0,
                "comment": "ok",
            }
        )
