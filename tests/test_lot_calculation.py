"""Unit tests for lot size calculation."""

from __future__ import annotations

import pytest

from app.config.settings import RiskSettings
from app.trading.risk import VolumeConstraints, calculate_lots_per_tp, round_volume


def test_fixed_lot_three_tps() -> None:
    settings = RiskSettings(lot_mode="fixed", fixed_lot=0.01)
    lots = calculate_lots_per_tp(3, settings)
    assert lots == [0.01, 0.01, 0.01]


def test_total_split_three_tps() -> None:
    settings = RiskSettings(lot_mode="total_split", total_lot=0.03)
    lots = calculate_lots_per_tp(3, settings)
    assert lots == [0.01, 0.01, 0.01]


def test_total_split_respects_volume_step() -> None:
    settings = RiskSettings(lot_mode="total_split", total_lot=0.05)
    constraints = VolumeConstraints(volume_min=0.01, volume_step=0.01)
    lots = calculate_lots_per_tp(3, settings, constraints)
    # 0.05/3 ≈ 0.0166 → rounds down to 0.01 each
    assert lots == [0.01, 0.01, 0.01]


def test_below_minimum_raises() -> None:
    settings = RiskSettings(lot_mode="fixed", fixed_lot=0.001)
    constraints = VolumeConstraints(volume_min=0.01, volume_step=0.01)
    with pytest.raises(ValueError, match="below broker minimum"):
        calculate_lots_per_tp(1, settings, constraints)


def test_round_volume() -> None:
    c = VolumeConstraints(volume_min=0.01, volume_max=10.0, volume_step=0.01)
    assert round_volume(0.019, c) == 0.01
    assert round_volume(0.01, c) == 0.01
    assert round_volume(0.005, c) is None


def test_max_total_lot_enforced() -> None:
    settings = RiskSettings(
        lot_mode="fixed",
        fixed_lot=1.0,
        max_lot_per_order=1.0,
        max_total_lot=2.0,
    )
    with pytest.raises(ValueError, match="max_total_lot"):
        calculate_lots_per_tp(3, settings)
