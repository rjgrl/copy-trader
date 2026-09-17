"""Intelligent entry engine — wires EntryValidator to live MT5 pricing.

Phase 5: symbol validation, market snapshot, deviation, TP1 protection, spread.
Does NOT call order_send (Phase 6).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.config.settings import AppSettings
from app.mt5.client import MT5Error
from app.mt5.models import MarketSnapshot, SymbolValidationResult
from app.mt5.service import MT5Service
from app.signals.models import EntryDecision, ParsedSignal, SignalStatus
from app.trading.entry import EntryAction, EntryValidator
from app.trading.safety import SafetyGuard

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class EntryCheckResult:
    """Full Phase 5 outcome for a structurally validated signal."""

    ok: bool
    status: SignalStatus
    decision: EntryDecision
    mapped_symbol: str
    symbol_validation: SymbolValidationResult | None = None
    snapshot: MarketSnapshot | None = None
    would_execute: list[dict] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    @property
    def reason(self) -> str:
        if self.reasons:
            return "; ".join(self.reasons)
        return self.decision.reason


class IntelligentEntryEngine:
    """Validate entry conditions using live (or mock) MT5 market data."""

    def __init__(
        self,
        settings: AppSettings,
        mt5: MT5Service,
        *,
        entry_validator: EntryValidator | None = None,
        safety: SafetyGuard | None = None,
    ) -> None:
        self.settings = settings
        self.mt5 = mt5
        self.validator = entry_validator or EntryValidator(
            settings.entry,
            settings.risk,
        )
        self.safety = safety or SafetyGuard(settings.risk)

    def evaluate(self, signal: ParsedSignal) -> EntryCheckResult:
        """Run symbol + market + entry + safety checks. Never sends orders."""
        if signal.direction is None or signal.symbol is None or not signal.has_entry():
            decision = EntryDecision(
                ok=False,
                action=EntryAction.REJECT.value,
                reasons=["Incomplete signal for entry check"],
            )
            return EntryCheckResult(
                ok=False,
                status=SignalStatus.REJECTED,
                decision=decision,
                mapped_symbol="",
                reasons=decision.reasons,
            )

        direction = signal.direction.value
        mapped = self.mt5.symbols.map_symbol(signal.symbol)

        # 1) Symbol must exist and be tradable
        try:
            if not self.mt5.is_connected:
                raise MT5Error("MT5 is not connected")
            sym_val = self.mt5.validate_symbol(signal.symbol, direction=direction)
        except MT5Error as exc:
            decision = EntryDecision(
                ok=False,
                action=EntryAction.REJECT.value,
                reasons=[str(exc)],
                signal_entry=signal.entry,
            )
            return EntryCheckResult(
                ok=False,
                status=SignalStatus.REJECTED,
                decision=decision,
                mapped_symbol=mapped,
                reasons=[str(exc)],
            )

        if not sym_val.ok:
            decision = EntryDecision(
                ok=False,
                action=EntryAction.REJECT.value,
                reasons=list(sym_val.reasons),
                signal_entry=signal.entry,
                current_price=sym_val.tick.bid if sym_val.tick else None,
            )
            return EntryCheckResult(
                ok=False,
                status=SignalStatus.REJECTED,
                decision=decision,
                mapped_symbol=mapped,
                symbol_validation=sym_val,
                reasons=list(sym_val.reasons),
            )

        # 2) Live market snapshot (BUY=ask, SELL=bid)
        try:
            snapshot = self.mt5.pricing.snapshot(mapped, direction)
        except MT5Error as exc:
            decision = EntryDecision(
                ok=False,
                action=EntryAction.REJECT.value,
                reasons=[f"Market price unavailable: {exc}"],
                signal_entry=signal.entry,
            )
            return EntryCheckResult(
                ok=False,
                status=SignalStatus.REJECTED,
                decision=decision,
                mapped_symbol=mapped,
                symbol_validation=sym_val,
                reasons=[str(exc)],
            )

        exec_price = snapshot.execution_price
        spread = snapshot.spread_price
        point = snapshot.spec.point

        logger.info(
            "Entry market: %s %s signal_entry=%s exec=%s (bid=%s ask=%s) "
            "spread=%.5f (%.1f pts) point=%s",
            direction,
            mapped,
            signal.entry,
            exec_price,
            snapshot.tick.bid,
            snapshot.tick.ask,
            spread,
            snapshot.spread_points,
            point,
        )

        # 3) Intelligent entry validation (pure logic)
        # New Telegram messages always market-execute at the live price.
        decision = self.validator.evaluate(
            signal,
            exec_price,
            spread=spread,
            point=point,
            is_new_message=True,
        )

        # 4) Safety: max orders per signal
        safety = self.safety.check_order_count(signal.tp_count)
        if not safety.ok:
            decision = EntryDecision(
                ok=False,
                action=EntryAction.REJECT.value,
                reasons=list(safety.reasons),
                current_price=exec_price,
                signal_entry=signal.entry,
                deviation=decision.deviation,
                max_allowed_deviation=decision.max_allowed_deviation,
                spread=spread,
                tp1_reached=decision.tp1_reached,
            )

        if not decision.ok:
            status = (
                SignalStatus.SKIPPED
                if decision.action in {EntryAction.SKIP.value, EntryAction.PENDING.value}
                else SignalStatus.REJECTED
            )
            logger.info(
                "Entry check failed: action=%s reason=%s",
                decision.action,
                decision.reason,
            )
            return EntryCheckResult(
                ok=False,
                status=status,
                decision=decision,
                mapped_symbol=mapped,
                symbol_validation=sym_val,
                snapshot=snapshot,
                reasons=list(decision.reasons),
            )

        # Build dry-run preview of would-be orders (one per TP)
        would_execute = []
        for i, tp in enumerate(signal.take_profits, start=1):
            would_execute.append(
                {
                    "tp_index": i,
                    "direction": direction,
                    "symbol": mapped,
                    "volume": self.settings.risk.fixed_lot
                    if self.settings.risk.lot_mode == "fixed"
                    else None,
                    "execution_price": exec_price,
                    "signal_entry": signal.entry,
                    "deviation": decision.deviation,
                    "take_profit": tp,
                    "stop_loss": signal.stop_loss,
                    "dry_run": self.settings.dry_run,
                }
            )

        logger.info(
            "Entry check PASSED: MARKET %s %s @ %s (signal entry %s, deviation %s) "
            "TPs=%s SL=%s dry_run=%s notes=%s",
            direction,
            mapped,
            exec_price,
            signal.entry,
            decision.deviation,
            signal.take_profits,
            signal.stop_loss,
            self.settings.dry_run,
            decision.reason,
        )

        return EntryCheckResult(
            ok=True,
            status=SignalStatus.ENTRY_CHECKED,
            decision=decision,
            mapped_symbol=mapped,
            symbol_validation=sym_val,
            snapshot=snapshot,
            would_execute=would_execute,
            reasons=["VALID_MARKET_EXECUTION"],
        )
