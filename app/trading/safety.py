"""Safety limit checks (max trades, lots, etc.). Stub for Phase 5+."""

from __future__ import annotations

from dataclasses import dataclass

from app.config.settings import RiskSettings


@dataclass(slots=True)
class SafetyCheckResult:
    ok: bool
    reasons: list[str]


class SafetyGuard:
    """Reject signals that would breach configured safety limits."""

    def __init__(self, settings: RiskSettings | None = None) -> None:
        self.settings = settings or RiskSettings()

    def check_order_count(self, tp_count: int) -> SafetyCheckResult:
        if tp_count > self.settings.max_orders_per_signal:
            return SafetyCheckResult(
                ok=False,
                reasons=[
                    f"Orders per signal {tp_count} > max "
                    f"{self.settings.max_orders_per_signal}"
                ],
            )
        return SafetyCheckResult(ok=True, reasons=[])

    def check_simultaneous(
        self, current_open: int, new_orders: int
    ) -> SafetyCheckResult:
        if current_open + new_orders > self.settings.max_simultaneous_trades:
            return SafetyCheckResult(
                ok=False,
                reasons=[
                    f"Would exceed max simultaneous trades "
                    f"({current_open}+{new_orders} > "
                    f"{self.settings.max_simultaneous_trades})"
                ],
            )
        return SafetyCheckResult(ok=True, reasons=[])
