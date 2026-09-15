"""MT5 order execution — market orders with retcode verification.

Never assumes success from a bare order_send() return. Inspects retcode.
Filling mode is derived from the broker symbol specification.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.mt5.client import MT5Client, MT5Error
from app.mt5.models import SymbolSpec

logger = logging.getLogger(__name__)

# Common MetaTrader5 retcodes
TRADE_RETCODE_DONE = 10009
TRADE_RETCODE_DONE_PARTIAL = 10010
TRADE_RETCODE_PLACED = 10008
TRADE_RETCODE_REQUOTE = 10004
TRADE_RETCODE_REJECT = 10006
TRADE_RETCODE_CANCEL = 10007
TRADE_RETCODE_INVALID_VOLUME = 10014
TRADE_RETCODE_INVALID_PRICE = 10015
TRADE_RETCODE_INVALID_STOPS = 10016
TRADE_RETCODE_TRADE_DISABLED = 10017
TRADE_RETCODE_MARKET_CLOSED = 10018
TRADE_RETCODE_NO_MONEY = 10019
TRADE_RETCODE_PRICE_CHANGED = 10020
TRADE_RETCODE_PRICE_OFF = 10021
TRADE_RETCODE_INVALID_FILL = 10030
TRADE_RETCODE_CONNECTION = 10031

SUCCESS_RETCODES = {
    TRADE_RETCODE_DONE,
    TRADE_RETCODE_DONE_PARTIAL,
    TRADE_RETCODE_PLACED,
}

RETCODE_DESCRIPTIONS: dict[int, str] = {
    10004: "Requote",
    10006: "Request rejected",
    10007: "Request canceled by trader",
    10008: "Order placed",
    10009: "Request completed",
    10010: "Request partially completed",
    10011: "Request processing error",
    10012: "Request timeout",
    10013: "Invalid request",
    10014: "Invalid volume",
    10015: "Invalid price",
    10016: "Invalid stops",
    10017: "Trade disabled",
    10018: "Market closed",
    10019: "Not enough money",
    10020: "Prices changed",
    10021: "No quotes",
    10022: "Invalid expiration",
    10024: "Too many requests",
    10026: "Autotrading disabled by server",
    10027: "Autotrading disabled by client",
    10030: "Invalid fill type",
    10031: "No connection",
    10033: "Limit orders reached",
    10034: "Volume limit reached",
    10035: "Invalid order",
    10036: "Position already closed",
    10038: "Invalid close volume",
    10040: "Position limit reached",
    10042: "Long only",
    10043: "Short only",
    10044: "Close only",
}


@dataclass(slots=True)
class OrderRequest:
    symbol: str
    direction: str  # BUY | SELL
    volume: float
    price: float
    stop_loss: float | None
    take_profit: float | None
    magic: int
    comment: str
    deviation_points: int = 50  # max price slippage in points


@dataclass(slots=True)
class OrderResult:
    ok: bool
    retcode: int
    retcode_description: str
    ticket: int | None = None
    deal: int | None = None
    volume: float | None = None
    price: float | None = None
    comment: str = ""
    dry_run: bool = False
    request: dict[str, Any] | None = None
    raw: Any = None

    @property
    def status_label(self) -> str:
        if self.dry_run and self.ok:
            return "DRY_RUN"
        return "EXECUTED" if self.ok else "FAILED"


def describe_retcode(retcode: int) -> str:
    return RETCODE_DESCRIPTIONS.get(retcode, f"Unknown retcode {retcode}")


def pick_filling_mode(filling_mode_flags: int) -> int:
    """Choose ORDER_FILLING_* from symbol filling_mode bit flags.

    MQL5: FOK=1, IOC=2, RETURN=4.
    ORDER_FILLING_FOK=0, IOC=1, RETURN=2.
    """
    ORDER_FILLING_FOK = 0
    ORDER_FILLING_IOC = 1
    ORDER_FILLING_RETURN = 2
    if filling_mode_flags & 2:  # IOC
        return ORDER_FILLING_IOC
    if filling_mode_flags & 1:  # FOK
        return ORDER_FILLING_FOK
    if filling_mode_flags & 4:  # RETURN
        return ORDER_FILLING_RETURN
    return ORDER_FILLING_IOC


class MT5TradeExecutor:
    """Send and verify MT5 market orders. Isolated from GUI/Telegram."""

    def __init__(self, client: MT5Client) -> None:
        self._client = client

    def send_market_order(
        self,
        request: OrderRequest,
        *,
        dry_run: bool = False,
        spec: SymbolSpec | None = None,
    ) -> OrderResult:
        """Place a market deal. dry_run=True never calls order_send."""
        self._client.require_connected()
        direction = request.direction.upper()
        if direction not in {"BUY", "SELL"}:
            return OrderResult(
                ok=False,
                retcode=-1,
                retcode_description=f"Invalid direction: {direction}",
            )

        order_type = 0 if direction == "BUY" else 1  # ORDER_TYPE_BUY / SELL
        filling = 1  # IOC default
        raw_info = self._client.gateway.symbol_info(request.symbol)
        if raw_info is not None:
            filling = pick_filling_mode(int(getattr(raw_info, "filling_mode", 2) or 2))

        trade_request: dict[str, Any] = {
            "action": 1,  # TRADE_ACTION_DEAL
            "symbol": request.symbol,
            "volume": float(request.volume),
            "type": order_type,
            "price": float(request.price),
            "deviation": int(request.deviation_points),
            "magic": int(request.magic),
            "comment": request.comment[:31],
            "type_time": 0,  # ORDER_TIME_GTC
            "type_filling": filling,
        }
        if request.stop_loss is not None:
            trade_request["sl"] = float(request.stop_loss)
        if request.take_profit is not None:
            trade_request["tp"] = float(request.take_profit)

        logger.info(
            "Order request: %s %s vol=%s price=%s sl=%s tp=%s magic=%s comment=%s dry_run=%s",
            direction,
            request.symbol,
            request.volume,
            request.price,
            request.stop_loss,
            request.take_profit,
            request.magic,
            request.comment,
            dry_run,
        )

        if dry_run:
            logger.info(
                "DRY RUN - would send order_send (not calling MT5): %s",
                {k: trade_request[k] for k in trade_request if k != "comment"}
                | {"comment": trade_request["comment"]},
            )
            return OrderResult(
                ok=True,
                retcode=TRADE_RETCODE_DONE,
                retcode_description="DRY_RUN - order not sent",
                ticket=None,
                deal=None,
                volume=request.volume,
                price=request.price,
                comment=request.comment,
                dry_run=True,
                request=trade_request,
            )

        result = self._client.gateway.order_send(trade_request)
        if result is None:
            code, msg = self._client.gateway.last_error()
            return OrderResult(
                ok=False,
                retcode=code,
                retcode_description=f"order_send returned None ({code}: {msg})",
                comment=request.comment,
                request=trade_request,
            )

        retcode = int(getattr(result, "retcode", -1))
        desc = describe_retcode(retcode)
        ok = retcode in SUCCESS_RETCODES
        ticket = getattr(result, "order", None) or getattr(result, "deal", None)
        deal = getattr(result, "deal", None)
        price = getattr(result, "price", None)
        volume = getattr(result, "volume", None)

        if ok:
            logger.info(
                "Order OK retcode=%s ticket=%s deal=%s price=%s volume=%s",
                retcode,
                ticket,
                deal,
                price,
                volume,
            )
        else:
            logger.error(
                "Order FAILED retcode=%s (%s) comment=%s",
                retcode,
                desc,
                getattr(result, "comment", ""),
            )

        return OrderResult(
            ok=ok,
            retcode=retcode,
            retcode_description=desc,
            ticket=int(ticket) if ticket else None,
            deal=int(deal) if deal else None,
            volume=float(volume) if volume is not None else request.volume,
            price=float(price) if price else request.price,
            comment=request.comment,
            dry_run=False,
            request=trade_request,
            raw=result,
        )
