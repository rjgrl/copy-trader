"""MT5 symbol service — mapping, validation, and specifications."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.config.settings import AppSettings
from app.mt5.client import MT5Client, MT5Error
from app.mt5.models import (
    SymbolSpec,
    SymbolTradeMode,
    SymbolValidationResult,
    Tick,
    map_trade_mode,
)

logger = logging.getLogger(__name__)


class MT5SymbolService:
    """Resolve Telegram symbols to broker symbols and validate tradability."""

    def __init__(self, client: MT5Client, settings: AppSettings) -> None:
        self._client = client
        self.settings = settings

    def map_symbol(self, telegram_symbol: str) -> str:
        return self.settings.map_symbol(telegram_symbol)

    def get_spec(self, mt5_symbol: str) -> SymbolSpec | None:
        self._client.require_connected()
        raw = self._client.gateway.symbol_info(mt5_symbol)
        if raw is None:
            return None
        return self._to_spec(raw)

    def ensure_selected(self, mt5_symbol: str) -> bool:
        """Add symbol to Market Watch if needed."""
        self._client.require_connected()
        info = self._client.gateway.symbol_info(mt5_symbol)
        if info is None:
            return False
        if getattr(info, "select", False):
            return True
        ok = self._client.gateway.symbol_select(mt5_symbol, True)
        if not ok:
            code, msg = self._client.gateway.last_error()
            logger.warning(
                "symbol_select(%s) failed: %s %s", mt5_symbol, code, msg
            )
        return ok

    def find_symbols(self, query: str, *, limit: int = 50) -> list[str]:
        """Search broker symbols by substring (case-insensitive)."""
        self._client.require_connected()
        all_syms = self._client.gateway.symbols_get()
        if not all_syms:
            return []
        q = query.upper()
        names = []
        for s in all_syms:
            name = str(getattr(s, "name", ""))
            if q in name.upper():
                names.append(name)
            if len(names) >= limit:
                break
        return names

    def validate(
        self,
        telegram_symbol: str,
        *,
        direction: str | None = None,
    ) -> SymbolValidationResult:
        """Map + exist + select + tradable checks. Does not place orders."""
        mt5_symbol = self.map_symbol(telegram_symbol)
        reasons: list[str] = []

        try:
            self._client.require_connected()
        except MT5Error as exc:
            return SymbolValidationResult(
                ok=False,
                telegram_symbol=telegram_symbol,
                mt5_symbol=mt5_symbol,
                reasons=[str(exc)],
            )

        if not self.ensure_selected(mt5_symbol):
            hints = self.find_symbols(telegram_symbol[:3], limit=10)
            # Brokers often rename gold (GOLD#, XAUUSDm, etc.)
            upper = telegram_symbol.upper()
            if upper in {"XAUUSD", "XAU", "GOLD"}:
                extra = self.find_symbols("GOLD", limit=8) + self.find_symbols("XAU", limit=8)
                for h in extra:
                    if h not in hints:
                        hints.append(h)
            hint_txt = f" Similar: {', '.join(hints[:12])}" if hints else ""
            return SymbolValidationResult(
                ok=False,
                telegram_symbol=telegram_symbol,
                mt5_symbol=mt5_symbol,
                reasons=[
                    f"Symbol unavailable or not selectable: {mt5_symbol}.{hint_txt} "
                    f"Configure symbol_mappings in data/config.json "
                    f'(e.g. "{{"XAUUSD": "GOLD#"}}").'
                ],
            )

        spec = self.get_spec(mt5_symbol)
        if spec is None:
            return SymbolValidationResult(
                ok=False,
                telegram_symbol=telegram_symbol,
                mt5_symbol=mt5_symbol,
                reasons=[f"symbol_info returned None for {mt5_symbol}"],
            )

        if spec.trade_mode == SymbolTradeMode.DISABLED:
            reasons.append(f"Trading disabled for {mt5_symbol}")
        elif spec.trade_mode == SymbolTradeMode.CLOSEONLY:
            reasons.append(f"Symbol {mt5_symbol} is close-only — cannot open new orders")
        elif direction:
            d = direction.upper()
            if d in {"BUY", "LONG"} and spec.trade_mode == SymbolTradeMode.SHORTONLY:
                reasons.append(f"Symbol {mt5_symbol} is short-only")
            if d in {"SELL", "SHORT"} and spec.trade_mode == SymbolTradeMode.LONGONLY:
                reasons.append(f"Symbol {mt5_symbol} is long-only")

        if spec.volume_min <= 0 or spec.volume_step <= 0:
            reasons.append("Invalid volume constraints from broker")

        account = self._client.get_account_info()
        if account and not account.trade_allowed:
            reasons.append("Account trading not allowed")
        if account and not account.trade_expert:
            reasons.append("Expert/algorithmic trading disabled on account")

        terminal = self._client.get_terminal_info()
        if terminal and not terminal.trade_allowed:
            reasons.append("Terminal trading not allowed")

        tick = None
        raw_tick = self._client.gateway.symbol_info_tick(mt5_symbol)
        if raw_tick is None:
            reasons.append(f"No tick data for {mt5_symbol} (market closed?)")
        else:
            tick = self._to_tick(mt5_symbol, raw_tick)
            if tick.bid <= 0 or tick.ask <= 0:
                reasons.append("Invalid bid/ask tick")

        ok = len(reasons) == 0
        if ok:
            logger.info(
                "Symbol OK: %s -> %s digits=%s point=%s tick_size=%s "
                "vol_min=%s vol_step=%s mode=%s",
                telegram_symbol,
                mt5_symbol,
                spec.digits,
                spec.point,
                spec.trade_tick_size,
                spec.volume_min,
                spec.volume_step,
                spec.trade_mode.value,
            )
        else:
            logger.warning("Symbol validation failed for %s: %s", mt5_symbol, reasons)

        return SymbolValidationResult(
            ok=ok,
            telegram_symbol=telegram_symbol,
            mt5_symbol=mt5_symbol,
            reasons=reasons,
            spec=spec,
            tick=tick,
        )

    @staticmethod
    def _to_spec(raw) -> SymbolSpec:
        mode_raw = int(getattr(raw, "trade_mode", 0) or 0)
        return SymbolSpec(
            name=str(raw.name),
            digits=int(raw.digits),
            point=float(raw.point),
            trade_tick_size=float(getattr(raw, "trade_tick_size", 0.0) or 0.0),
            trade_tick_value=float(getattr(raw, "trade_tick_value", 0.0) or 0.0),
            trade_contract_size=float(getattr(raw, "trade_contract_size", 0.0) or 0.0),
            volume_min=float(raw.volume_min),
            volume_max=float(raw.volume_max),
            volume_step=float(raw.volume_step),
            trade_mode=map_trade_mode(mode_raw),
            trade_mode_raw=mode_raw,
            spread_points=int(getattr(raw, "spread", 0) or 0),
            stops_level=int(getattr(raw, "trade_stops_level", 0) or 0),
            visible=bool(getattr(raw, "visible", True)),
            selected=bool(getattr(raw, "select", False)),
        )

    @staticmethod
    def _to_tick(symbol: str, raw) -> Tick:
        time_msc = getattr(raw, "time_msc", None)
        time_s = getattr(raw, "time", None)
        dt = None
        if time_msc:
            dt = datetime.fromtimestamp(int(time_msc) / 1000.0, tz=timezone.utc)
        elif time_s:
            dt = datetime.fromtimestamp(int(time_s), tz=timezone.utc)
        return Tick(
            symbol=symbol,
            bid=float(raw.bid),
            ask=float(raw.ask),
            last=float(getattr(raw, "last", 0.0) or 0.0),
            time=dt,
            time_msc=int(time_msc) if time_msc else None,
        )
