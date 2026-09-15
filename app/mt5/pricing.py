"""Market pricing helpers — ticks, spreads, execution prices.

All point conversions use the live SymbolSpec.point from MT5.
Never hard-code XAUUSD point size.
"""

from __future__ import annotations

import logging

from app.mt5.client import MT5Client, MT5Error
from app.mt5.models import MarketSnapshot, SymbolSpec, Tick
from app.mt5.symbols import MT5SymbolService

logger = logging.getLogger(__name__)


class MT5PricingService:
    """Fetch current market prices and compute spread in price / points."""

    def __init__(self, client: MT5Client, symbols: MT5SymbolService) -> None:
        self._client = client
        self._symbols = symbols

    def get_tick(self, mt5_symbol: str) -> Tick:
        self._client.require_connected()
        if not self._symbols.ensure_selected(mt5_symbol):
            raise MT5Error(f"Cannot select symbol {mt5_symbol}")
        raw = self._client.gateway.symbol_info_tick(mt5_symbol)
        if raw is None:
            raise MT5Error(f"No tick for {mt5_symbol}")
        return MT5SymbolService._to_tick(mt5_symbol, raw)

    def get_spec(self, mt5_symbol: str) -> SymbolSpec:
        spec = self._symbols.get_spec(mt5_symbol)
        if spec is None:
            raise MT5Error(f"No symbol_info for {mt5_symbol}")
        return spec

    def spread(self, mt5_symbol: str) -> tuple[float, float]:
        """Return (spread_price, spread_points) using live bid/ask and point size."""
        tick = self.get_tick(mt5_symbol)
        spec = self.get_spec(mt5_symbol)
        spread_price = tick.spread_price
        spread_points = spec.price_to_points(spread_price)
        return spread_price, spread_points

    def snapshot(self, mt5_symbol: str, direction: str) -> MarketSnapshot:
        """Full pricing snapshot for entry validation."""
        tick = self.get_tick(mt5_symbol)
        spec = self.get_spec(mt5_symbol)
        spread_price = tick.spread_price
        spread_points = spec.price_to_points(spread_price)
        execution_price = tick.execution_price(direction)
        logger.debug(
            "Market %s %s bid=%.5f ask=%.5f exec=%.5f spread=%.5f (%.1f pts) point=%s",
            mt5_symbol,
            direction,
            tick.bid,
            tick.ask,
            execution_price,
            spread_price,
            spread_points,
            spec.point,
        )
        return MarketSnapshot(
            symbol=mt5_symbol,
            tick=tick,
            spec=spec,
            spread_price=spread_price,
            spread_points=spread_points,
            execution_price=execution_price,
            direction=direction.upper(),
        )

    def format_price_diff(
        self,
        price_diff: float,
        spec: SymbolSpec,
    ) -> dict[str, float]:
        """Display helper: both price units and MT5 points."""
        return {
            "price_difference": abs(price_diff),
            "mt5_points": spec.price_to_points(price_diff),
            "point_size": spec.point,
            "digits": float(spec.digits),
        }
