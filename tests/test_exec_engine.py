"""Tests for ExecutionEngine order execution."""
from datetime import datetime
import pytest

from xtrading_models import BarData, MarketOrder, LimitOrder, StopOrder, StopLimitOrder
from execEngine import ExecutionEngine


@pytest.fixture
def bullish_bar():
    """Standard bullish bar for testing."""
    return BarData(
        date=datetime(2025, 1, 1, 9, 30),
        open=148.0,
        high=152.0,
        low=146.0,
        close=150.0,
        volume=1000000
    )


@pytest.fixture
def engine():
    """Execution engine instance."""
    return ExecutionEngine()


# region Market Order Tests

def test_market_order_fills_at_open(engine, bullish_bar):
    """Market order should fill at bar open."""
    order = MarketOrder(action="BUY", totalQuantity=100)
    fills = engine.execute(order, bullish_bar)

    assert len(fills) == 1
    assert fills[0].execution.price == 148.0  # open

# endregion


# region Limit Order Tests

def test_limit_buy_fills_when_low_touches(engine, bullish_bar):
    """Buy limit should fill when low touches limit price."""
    order = LimitOrder(action="BUY", totalQuantity=100, price=147.0)
    fills = engine.execute(order, bullish_bar)

    assert len(fills) == 1
    assert fills[0].execution.price == 147.0  # limit


def test_limit_buy_no_fill_when_low_above(engine, bullish_bar):
    """Buy limit should not fill when low stays above limit."""
    order = LimitOrder(action="BUY", totalQuantity=100, price=145.0)
    fills = engine.execute(order, bullish_bar)

    assert len(fills) == 0

# endregion


# region Stop Order Tests

def test_stop_buy_fills_when_high_touches(engine, bullish_bar):
    """Buy stop should trigger and fill when high touches stop."""
    order = StopOrder(action="BUY", totalQuantity=100, stopPrice=151.0)
    fills = engine.execute(order, bullish_bar)

    assert len(fills) == 1
    assert fills[0].execution.price == 151.0


def test_stop_buy_no_trigger_when_high_below(engine, bullish_bar):
    """Buy stop should not trigger when high stays below stop."""
    order = StopOrder(action="BUY", totalQuantity=100, stopPrice=153.0)
    fills = engine.execute(order, bullish_bar)

    assert len(fills) == 0

# endregion


# region StopLimit Order Tests

def test_stop_limit_both_fill(engine, bullish_bar):
    """StopLimit where both stop triggers and limit fills -> single fill at limit price."""
    # Stop triggers at 151, limit at 149 (reachable from modified bar)
    order = StopLimitOrder(
        action="BUY",
        totalQuantity=100,
        stopPrice=151.0,
        limitPrice=149.0
    )
    fills = engine.execute(order, bullish_bar)

    assert len(fills) == 1
    assert fills[0].execution.price == 149.0


def test_stop_limit_triggered_but_not_filled(engine, bullish_bar):
    """Stop-limit: stop triggered but limit not filled -> 0 fills, triggered=True."""
    # Stop triggers at high, but limit below low
    order = StopLimitOrder(
        action="BUY",
        totalQuantity=100,
        stopPrice=151.0,  # Triggers
        limitPrice=145.0   # Below bar low, won't fill
    )
    fills = engine.execute(order, bullish_bar)

    assert len(fills) == 0
    assert order.triggered is True


def test_stop_limit_stop_only(engine, bullish_bar):
    """StopLimit where stop triggers but limit doesn't fill -> triggered=True, 0 fills."""
    # Stop triggers at 151, but limit at 145 (below bar low)
    order = StopLimitOrder(
        action="BUY",
        totalQuantity=100,
        stopPrice=151.0,
        limitPrice=145.0
    )
    fills = engine.execute(order, bullish_bar)

    assert len(fills) == 0
    assert order.triggered is True


def test_stop_limit_no_trigger(engine, bullish_bar):
    """StopLimit where stop doesn't trigger."""
    order = StopLimitOrder(
        action="BUY",
        totalQuantity=100,
        stopPrice=153.0,
        limitPrice=156.0
    )
    fills = engine.execute(order, bullish_bar)

    assert len(fills) == 0
    assert order.triggered is False

# endregion
