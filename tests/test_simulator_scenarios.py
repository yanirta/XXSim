"""Real-data simulator scenarios using SPY Jan 28-29, 2026.

Tests bracket order scenarios (entry + trailing stop + take profit with OCA)
using actual market data and order parameters from a daily midpoint backtest.
"""
import pytest
from datetime import datetime

from xtrading_models import BarData, LimitOrder
from xtrading_models.order import TrailingStopMarket

from simulator import Simulator


# region Fixtures

@pytest.fixture
def simulator(time_provider):
    return Simulator(time_provider)


@pytest.fixture
def spy_bar_jan28():
    """SPY daily bar for 2026-01-28."""
    return BarData(
        date=datetime(2026, 1, 28),
        open=697.06,
        high=697.84,
        low=693.94,
        close=695.42,
        volume=46863286,
    )


@pytest.fixture
def spy_bar_jan29():
    """SPY daily bar for 2026-01-29."""
    return BarData(
        date=datetime(2026, 1, 29),
        open=696.35,
        high=697.06,
        low=684.83,
        close=694.04,
        volume=81117277,
    )

# endregion


# region Bracket Scenarios

class TestBracketScenarios:
    """Full bracket order scenarios from daily midpoint backtest."""

    def test_jan29_trailing_stop_loss(self, simulator, spy_bar_jan28, spy_bar_jan29):
        """Jan 29: Entry fills, trailing stop triggers for a loss.

        Prev day (Jan 28): H=697.84, L=693.94
        Midpoint = 695.89, trail_amount = 1.95, TP = 697.84

        Entry limit BUY at 695.89 fills (bar low 684.83 < 695.89).
        Modified bar for children opens at 695.89.
        Trailing stop tracks up to 697.06, stop = 697.06 - 1.95 = 695.11, fills.
        TP at 697.84 cancelled by OCA.
        P&L = 5 * (695.11 - 695.89) = -3.90
        """
        jan28 = spy_bar_jan28
        limit = (jan28.high + jan28.low) / 2  # 695.89
        stop_distance = limit - jan28.low  # 1.95
        take_profit = limit + stop_distance  # 697.84
        entry = LimitOrder(action='BUY', totalQuantity=5, price=limit)
        entry.tif = 'DAY'

        stop = TrailingStopMarket(action='SELL', totalQuantity=5, trailingDistance=stop_distance)
        stop.tif = 'GTC'
        stop.ocaGroup = 'SPY_exit_jan29'

        tp = LimitOrder(action='SELL', totalQuantity=5, price=take_profit)
        tp.tif = 'GTC'
        tp.ocaGroup = 'SPY_exit_jan29'

        entry.add_child(stop)
        entry.add_child(tp)

        simulator.submit_order(entry)
        fills = simulator.process_bar(spy_bar_jan29)

        # Entry fill + trailing stop fill = 2 fills
        assert len(fills) == 2

        entry_fill = fills[0]
        assert entry_fill.execution.side == 'BUY'
        assert entry_fill.execution.price == limit
        assert entry_fill.execution.shares == 5

        stop_fill = fills[1]
        assert stop_fill.execution.side == 'SELL'
        # Trailing stop tracks extreme up to 697.06, stop = 697.06 - 1.95 = 695.11
        assert stop_fill.execution.price == pytest.approx(697.06 - stop_distance)
        assert stop_fill.execution.shares == 5

        # P&L (loss): (695.11 - 695.89) * 5 = -3.90
        pnl = (stop_fill.execution.price - entry_fill.execution.price) * 5
        assert pnl == pytest.approx(-3.90, abs=0.01)

# endregion
