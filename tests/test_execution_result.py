"""Tests for Phase 2.1 ExecutionResult and recursive execution."""
from decimal import Decimal
from datetime import datetime
import pytest

from xtrading_models import BarData, MarketOrder, LimitOrder, StopOrder, StopLimitOrder, ExecutionResult
from execution import ExecutionEngine


@pytest.fixture
def bullish_bar():
    """Standard bullish bar for testing."""
    return BarData(
        date=datetime(2025, 1, 1, 9, 30),
        open=Decimal('148.00'),
        high=Decimal('152.00'),
        low=Decimal('146.00'),
        close=Decimal('150.00'),
        volume=1000000
    )


@pytest.fixture
def engine():
    """Execution engine instance."""
    return ExecutionEngine()


# region ExecutionResult Tests

def test_execution_result_pending_status():
    """Pending orders without fills should have PENDING status."""
    result = ExecutionResult()
    # Add pending order (no fill)
    result.pending_orders.append(MarketOrder(action="BUY", totalQuantity=100))
    assert result.status == 'PENDING'
    assert len(result.fills) == 0
    assert len(result.pending_orders) == 1


def test_execution_result_filled_status(engine, bullish_bar):
    """Result with fills and no pending should be FILLED."""
    order = MarketOrder(action="BUY", totalQuantity=100)
    result = engine.execute(order, bullish_bar)
    
    assert result.status == 'FILLED'
    assert len(result.fills) == 1
    assert len(result.pending_orders) == 0


def test_execution_result_partial_status(engine, bullish_bar):
    """Stop triggered but limit not filled should be PARTIAL."""
    # Stop triggers at high, but limit below low
    order = StopLimitOrder(
        action="BUY",
        totalQuantity=100,
        stopPrice=Decimal("151.00"),  # Triggers
        limitPrice=Decimal("145.00")   # Below bar low, won't fill
    )
    result = engine.execute(order, bullish_bar)
    
    assert result.status == 'PARTIAL'
    assert len(result.fills) == 1  # Stop fill
    assert len(result.pending_orders) == 1  # Limit pending


def test_execution_result_empty_is_invalid():
    """Empty result (no fills, no pending) should raise error."""
    result = ExecutionResult()
    
    with pytest.raises(ValueError, match="Invalid ExecutionResult state: empty result"):
        _ = result.status

# endregion


# region Market Order Tests

def test_market_order_fills_at_open(engine, bullish_bar):
    """Market order should fill at bar open."""
    order = MarketOrder(action="BUY", totalQuantity=100)
    result = engine.execute(order, bullish_bar)
    
    assert result.status == 'FILLED'
    assert len(result.fills) == 1
    assert result.fills[0].execution.price == Decimal('148.00')  # open

# endregion


# region Limit Order Tests

def test_limit_buy_fills_when_low_touches(engine, bullish_bar):
    """Buy limit should fill when low touches limit price."""
    order = LimitOrder(action="BUY", totalQuantity=100, price=Decimal("147.00"))
    result = engine.execute(order, bullish_bar)
    
    assert result.status == 'FILLED'
    assert len(result.fills) == 1
    assert result.fills[0].execution.price == Decimal('147.00')  # limit


def test_limit_buy_no_fill_when_low_above(engine, bullish_bar):
    """Buy limit should not fill when low stays above limit."""
    order = LimitOrder(action="BUY", totalQuantity=100, price=Decimal("145.00"))
    result = engine.execute(order, bullish_bar)
    
    assert result.status == 'PENDING'
    assert len(result.fills) == 0

# endregion


# region Stop Order Tests

def test_stop_buy_fills_when_high_touches(engine, bullish_bar):
    """Buy stop should trigger and fill when high touches stop."""
    order = StopOrder(action="BUY", totalQuantity=100, stopPrice=Decimal("151.00"))
    result = engine.execute(order, bullish_bar)
    
    assert result.status == 'FILLED'
    # Stop parent fill + Market child fill
    assert len(result.fills) == 2
    assert result.fills[0].execution.price == Decimal('151.00')  # Stop trigger
    assert result.fills[1].execution.price == Decimal('151.00')  # Market at trigger


def test_stop_buy_no_trigger_when_high_below(engine, bullish_bar):
    """Buy stop should not trigger when high stays below stop."""
    order = StopOrder(action="BUY", totalQuantity=100, stopPrice=Decimal("153.00"))
    result = engine.execute(order, bullish_bar)
    
    assert result.status == 'PENDING'
    assert len(result.fills) == 0

# endregion


# region StopLimit Order Tests

def test_stop_limit_both_fill(engine, bullish_bar):
    """StopLimit where both stop and limit fill."""
    # Stop triggers at 151, limit at 149 (reachable from modified bar)
    order = StopLimitOrder(
        action="BUY",
        totalQuantity=100,
        stopPrice=Decimal("151.00"),
        limitPrice=Decimal("149.00")
    )
    result = engine.execute(order, bullish_bar)
    
    assert result.status == 'FILLED'
    assert len(result.fills) == 2  # Stop fill + Limit fill


def test_stop_limit_stop_only(engine, bullish_bar):
    """StopLimit where stop fills but limit doesn't."""
    # Stop triggers at 151, but limit at 145 (below bar low)
    order = StopLimitOrder(
        action="BUY",
        totalQuantity=100,
        stopPrice=Decimal("151.00"),
        limitPrice=Decimal("145.00")
    )
    result = engine.execute(order, bullish_bar)
    
    assert result.status == 'PARTIAL'
    assert len(result.fills) == 1  # Only stop fill
    assert len(result.pending_orders) == 1  # Limit pending


def test_stop_limit_no_trigger(engine, bullish_bar):
    """StopLimit where stop doesn't trigger."""
    order = StopLimitOrder(
        action="BUY",
        totalQuantity=100,
        stopPrice=Decimal("153.00"),
        limitPrice=Decimal("156.00")
    )
    result = engine.execute(order, bullish_bar)
    
    assert result.status == 'PENDING'
    assert len(result.fills) == 0
    assert len(result.pending_orders) == 1  # Parent order pending

# endregion
