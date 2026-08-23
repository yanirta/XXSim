"""Commission is charged per fill under an IB-shaped schedule (B4).

Before this, every simulated fill was free: `commission_per_fill` defaulted to 0.0
and nothing set it, so a backtest reported an edge the real book could not trade.
On a live paper window commissions ran $35.64 against $35.28 of gross P&L — the
whole result, not a rounding detail.

The shape that matters is the ORDER of the floor and the cap. IB's minimum is per
order and its cap is a fraction of trade value, and the cap outranks the minimum:
one share of a cheap stock is capped well below the $1.00 floor. Getting that
backwards overcharges exactly the small trades a one-share config is made of.
"""

import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from execEngine import ExecutionConfig, ExecutionEngine

# IB's published US-equities tiers, as a caller would configure them.
IB_FIXED = dict(commission_per_share=0.005, commission_minimum=1.00, commission_max_pct=0.01)
IB_TIERED = dict(commission_per_share=0.0035, commission_minimum=0.35, commission_max_pct=0.01)


def cost(shares: float, price: float, **config) -> float:
    return ExecutionEngine(ExecutionConfig(**config))._commission_for(shares, price).commission


class TestDefault:

    def test_free_by_default(self):
        """Every existing caller constructs ExecutionConfig without commission
        fields and must keep the fills it already has."""
        assert cost(100, 50.0) == 0.0

    def test_the_flat_field_still_works_alone(self):
        assert cost(100, 50.0, commission_per_fill=0.75) == 0.75
        assert cost(1, 50.0, commission_per_fill=0.75) == 0.75


class TestIBFixed:

    def test_per_share_applies_above_the_minimum(self):
        # 1000 × $0.005 = $5.00, over the $1.00 floor and under 1% of $50,000.
        assert cost(1000, 50.0, **IB_FIXED) == pytest.approx(5.00)

    def test_the_minimum_floors_a_small_order(self):
        # 22 × $0.005 = $0.11 → floored to $1.00. 1% of $7,048 is $70, no cap.
        assert cost(22, 320.36, **IB_FIXED) == pytest.approx(1.00)

    def test_the_cap_outranks_the_minimum(self):
        """The case a floor-then-return implementation gets wrong: one share of a
        $20 stock costs 1% of $20, not the $1.00 minimum."""
        assert cost(1, 20.0, **IB_FIXED) == pytest.approx(0.20)

    def test_a_single_expensive_share_still_pays_the_minimum(self):
        # 1% of $265.89 is $2.66, above the floor — so the floor is what binds.
        assert cost(1, 265.89, **IB_FIXED) == pytest.approx(1.00)

    def test_the_tiered_schedule_is_just_different_numbers(self):
        assert cost(1000, 50.0, **IB_TIERED) == pytest.approx(3.50)
        assert cost(22, 320.36, **IB_TIERED) == pytest.approx(0.35)


class TestComposition:

    def test_flat_and_per_share_add(self):
        assert cost(100, 50.0, commission_per_fill=0.50, commission_per_share=0.01) == pytest.approx(1.50)

    def test_a_zero_minimum_disables_the_floor(self):
        assert cost(10, 50.0, commission_per_share=0.005) == pytest.approx(0.05)

    def test_a_zero_cap_disables_the_ceiling(self):
        """Without a cap the minimum stands, however small the trade."""
        assert cost(1, 1.0, commission_per_share=0.005, commission_minimum=1.00) == pytest.approx(1.00)

    def test_a_sell_costs_the_same_as_a_buy(self):
        """Quantity reaches this as the order's own field; a short leg must not
        come out negative and refund the book."""
        assert cost(-100, 50.0, **IB_FIXED) == cost(100, 50.0, **IB_FIXED)
        assert cost(-100, 50.0, **IB_FIXED) > 0

    def test_the_currency_is_reported(self):
        report = ExecutionEngine(ExecutionConfig(**IB_FIXED))._commission_for(100, 50.0)
        assert report.currency == "USD"


class TestEveryFillPathCharges:
    """A model only some order types applied would read as an edge belonging to
    the order shape. These pin that the six fill paths share one implementation."""

    def test_no_fill_path_builds_its_own_report(self):
        source = (Path(__file__).resolve().parent.parent / "src" / "execEngine.py").read_text()
        # The only CommissionReport( construction left is the one inside _commission_for.
        assert source.count("CommissionReport(") == 1, "a fill path built its own report again"
        assert source.count("commission = self._commission_for(") == 6
