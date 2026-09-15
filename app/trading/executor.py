"""Signal trade executor — one MT5 market order per TP.

Respects dry_run, copy_trading_enabled, kill switch, lot rules, and magic number.
Persists each order result; supports PARTIALLY_EXECUTED.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.config.settings import AppSettings
from app.database.models import OrderRecord
from app.database.repositories import OrderRepository
from app.mt5.execution import MT5TradeExecutor, OrderRequest, OrderResult
from app.mt5.service import MT5Service
from app.signals.models import ParsedSignal, SignalStatus
from app.trading.engine import EntryCheckResult
from app.trading.risk import VolumeConstraints, calculate_lots_per_tp
from app.utils.formatting import build_order_comment
from app.utils.time import utc_now

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class TpOrderOutcome:
    tp_index: int
    take_profit: float
    volume: float
    result: OrderResult
    order_db_id: int | None = None


@dataclass(slots=True)
class ExecutionResult:
    status: SignalStatus
    outcomes: list[TpOrderOutcome] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    dry_run: bool = False

    @property
    def ok(self) -> bool:
        return self.status in {
            SignalStatus.EXECUTED,
        }

    @property
    def success_count(self) -> int:
        return sum(1 for o in self.outcomes if o.result.ok)

    @property
    def fail_count(self) -> int:
        return sum(1 for o in self.outcomes if not o.result.ok)

    @property
    def reason(self) -> str:
        return "; ".join(self.reasons) if self.reasons else self.status.value


class SignalTradeExecutor:
    """Execute a validated + entry-checked signal as N market orders."""

    def __init__(
        self,
        settings: AppSettings,
        mt5: MT5Service,
        order_repo: OrderRepository,
        *,
        trade_executor: MT5TradeExecutor | None = None,
    ) -> None:
        self.settings = settings
        self.mt5 = mt5
        self.orders = order_repo
        self.executor = trade_executor or MT5TradeExecutor(mt5.client)

    def execute(
        self,
        signal: ParsedSignal,
        entry: EntryCheckResult,
        *,
        signal_db_id: int,
        telegram_message_id: int,
        kill_switch_active: bool = False,
    ) -> ExecutionResult:
        if not entry.ok or entry.snapshot is None:
            return ExecutionResult(
                status=SignalStatus.REJECTED,
                reasons=["Entry check not passed — refusing execution"],
            )

        if kill_switch_active:
            return ExecutionResult(
                status=SignalStatus.SKIPPED,
                reasons=["Kill switch active — execution blocked"],
            )

        dry_run = bool(self.settings.dry_run)
        if not dry_run and not self.settings.copy_trading_enabled:
            return ExecutionResult(
                status=SignalStatus.ENTRY_CHECKED,
                reasons=["Copy trading disabled — not sending live orders"],
                dry_run=False,
            )

        spec = entry.snapshot.spec
        constraints = VolumeConstraints(
            volume_min=spec.volume_min,
            volume_max=spec.volume_max,
            volume_step=spec.volume_step,
        )
        try:
            lots = calculate_lots_per_tp(
                signal.tp_count,
                self.settings.risk,
                constraints,
            )
        except ValueError as exc:
            return ExecutionResult(
                status=SignalStatus.REJECTED,
                reasons=[str(exc)],
            )

        direction = signal.direction.value if signal.direction else "SELL"
        exec_price = entry.decision.current_price or entry.snapshot.execution_price
        # Slippage allowance in points (price deviation / point)
        deviation_points = max(
            10,
            int(round((self.settings.entry.max_entry_deviation / spec.point)))
            if spec.point > 0
            else 50,
        )

        outcomes: list[TpOrderOutcome] = []
        for i, (tp, volume) in enumerate(
            zip(signal.take_profits, lots, strict=True), start=1
        ):
            # Prefer telegram symbol for comment readability; fall back to mapped
            comment_symbol = (signal.symbol or entry.mapped_symbol).replace("#", "")
            comment = build_order_comment(comment_symbol, telegram_message_id, i)
            logger.info(
                "Sending TP%s order: %s %s vol=%s @ %s TP=%s SL=%s",
                i,
                direction,
                entry.mapped_symbol,
                volume,
                exec_price,
                tp,
                signal.stop_loss,
            )
            result = self.executor.send_market_order(
                OrderRequest(
                    symbol=entry.mapped_symbol,
                    direction=direction,
                    volume=volume,
                    price=float(exec_price),
                    stop_loss=signal.stop_loss,
                    take_profit=tp,
                    magic=self.settings.magic_number,
                    comment=comment,
                    deviation_points=deviation_points,
                ),
                dry_run=dry_run,
                spec=spec,
            )
            order_id = self.orders.insert(
                OrderRecord(
                    id=None,
                    signal_id=signal_db_id,
                    mt5_ticket=result.ticket,
                    symbol=entry.mapped_symbol,
                    direction=direction,
                    volume=volume,
                    entry_price=result.price,
                    stop_loss=signal.stop_loss,
                    take_profit=tp,
                    tp_index=i,
                    status=result.status_label,
                    retcode=result.retcode,
                    retcode_description=result.retcode_description,
                    comment=comment,
                    created_at=utc_now(),
                    updated_at=utc_now(),
                    dry_run=result.dry_run,
                )
            )
            outcomes.append(
                TpOrderOutcome(
                    tp_index=i,
                    take_profit=tp,
                    volume=volume,
                    result=result,
                    order_db_id=order_id,
                )
            )
            if result.ok:
                logger.info("TP%s executed ticket=%s", i, result.ticket)
            else:
                logger.error(
                    "TP%s failed retcode=%s (%s)",
                    i,
                    result.retcode,
                    result.retcode_description,
                )

        success = sum(1 for o in outcomes if o.result.ok)
        failed = len(outcomes) - success
        if success == len(outcomes) and success > 0:
            status = SignalStatus.EXECUTED
            reasons = [f"All {success} TP orders {'dry-run ' if dry_run else ''}ok"]
        elif success > 0:
            status = SignalStatus.PARTIALLY_EXECUTED
            reasons = [
                f"{success} succeeded, {failed} failed",
                *[
                    f"TP{o.tp_index}: {o.result.retcode_description}"
                    for o in outcomes
                    if not o.result.ok
                ],
            ]
        else:
            status = SignalStatus.EXECUTION_FAILED
            reasons = [
                "All TP orders failed",
                *[
                    f"TP{o.tp_index}: {o.result.retcode_description}"
                    for o in outcomes
                ],
            ]

        return ExecutionResult(
            status=status,
            outcomes=outcomes,
            reasons=reasons,
            dry_run=dry_run,
        )
