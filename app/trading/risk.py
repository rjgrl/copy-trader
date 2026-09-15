"""Lot size calculation respecting broker volume constraints."""

from __future__ import annotations

import math
from dataclasses import dataclass

from app.config.settings import RiskSettings


@dataclass(slots=True, frozen=True)
class VolumeConstraints:
    """Broker symbol volume rules from MT5 symbol_info."""

    volume_min: float = 0.01
    volume_max: float = 100.0
    volume_step: float = 0.01


def round_volume(volume: float, constraints: VolumeConstraints) -> float | None:
    """Round volume down to the nearest valid step; return None if below min."""
    if volume <= 0:
        return None
    step = constraints.volume_step
    if step <= 0:
        step = 0.01
    steps = math.floor(volume / step + 1e-12)
    rounded = round(steps * step, 8)
    if rounded < constraints.volume_min:
        return None
    if rounded > constraints.volume_max:
        rounded = constraints.volume_max
        # Re-align to step
        steps = math.floor(rounded / step + 1e-12)
        rounded = round(steps * step, 8)
    return rounded


def calculate_lots_per_tp(
    tp_count: int,
    settings: RiskSettings,
    constraints: VolumeConstraints | None = None,
) -> list[float]:
    """Return per-TP lot sizes for a signal.

    Modes:
    - fixed: each TP gets fixed_lot
    - total_split: total_lot divided across TPs
    """
    if tp_count <= 0:
        return []
    constraints = constraints or VolumeConstraints()

    if settings.lot_mode == "total_split":
        raw_each = settings.total_lot / tp_count
    else:
        raw_each = settings.fixed_lot

    # Cap per-order
    raw_each = min(raw_each, settings.max_lot_per_order)

    lots: list[float] = []
    for _ in range(tp_count):
        vol = round_volume(raw_each, constraints)
        if vol is None:
            raise ValueError(
                f"Calculated volume {raw_each} is below broker minimum "
                f"{constraints.volume_min}"
            )
        lots.append(vol)

    total = sum(lots)
    if total > settings.max_total_lot + 1e-9:
        raise ValueError(
            f"Total lot {total} exceeds max_total_lot {settings.max_total_lot}"
        )
    return lots
