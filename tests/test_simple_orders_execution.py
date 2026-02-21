"""Tests for order execution engine."""
from datetime import datetime
import pytest

from xtrading_models import MarketOrder, LimitOrder, StopOrder, StopLimitOrder, BarData
from execEngine import ExecutionEngine

#region Fixtures

@pytest.fixture
def bearish_bar():
    """Standard bar: open=150, high=152, low=148, close=149."""
    return BarData(
        date=datetime(2025, 1, 1, 9, 30),
        open=150.0,
        high=152.0,
        low=146.0,
        close=148.0,
        volume=1000000,
    )

@pytest.fixture
def bullish_bar():
    """Bullish bar for stop-limit tests: open=148, high=152, low=146, close=150 (Close > Open)."""
    return BarData(
        date=datetime(2025, 1, 1, 9, 30),
        open=148.0,
        high=152.0,
        low=146.0,
        close=150.0,
        volume=1000000,
    )

@pytest.fixture
def engine():
    """Execution engine instance."""
    return ExecutionEngine()

#endregion

#region Market Order Tests

def test_market_order_buys_at_open(engine, bullish_bar):
    """Market orders execute at bar open price."""
    order = MarketOrder(action="BUY", totalQuantity=100)
    
    fills = engine.execute(order, bullish_bar)
    
    assert len(fills) == 1
    assert fills[0].execution.price == 148.0
    assert fills[0].execution.shares == 100
    assert fills[0].execution.time == datetime(2025, 1, 1, 9, 30)

def test_market_order_sells_at_open(engine, bullish_bar):
    """Market sell orders execute at bar open price."""
    order = MarketOrder(action="SELL", totalQuantity=100)
    
    fills = engine.execute(order, bullish_bar)
    
    assert len(fills) == 1
    assert fills[0].execution.price == 148.0
    assert fills[0].execution.shares == 100
    assert fills[0].execution.time == datetime(2025, 1, 1, 9, 30)

def test_market_order_on_bearish_bar(engine, bearish_bar):
    """Market orders execute at open regardless of bar direction."""
    order = MarketOrder(action="BUY", totalQuantity=100)
    
    fills = engine.execute(order, bearish_bar)
    
    assert len(fills) == 1
    assert fills[0].execution.price == 150.0  # bearish_bar open
    assert fills[0].execution.shares == 100
    assert fills[0].execution.time == datetime(2025, 1, 1, 9, 30)

#endregion

#region Limit Order Tests
    #region Buy orders
def test_buy_limit_fills_when_low_touches_limit(engine, bullish_bar):
    """Buy limit fills at limit price when bar low reaches it."""
    order = LimitOrder(action="BUY", totalQuantity=100, price=147.0)
    
    fills = engine.execute(order, bullish_bar)
    
    assert len(fills) == 1
    assert fills[0].execution.price == 147.0
    assert fills[0].execution.shares == 100
    assert fills[0].execution.time == datetime(2025, 1, 1, 9, 30)

def test_buy_limit_no_fill_when_low_above_limit(engine, bullish_bar):
    """Buy limit doesn't fill when bar low stays above limit price."""
    order = LimitOrder(action="BUY", totalQuantity=100, price=145.0)
    
    fills = engine.execute(order, bullish_bar)
    
    assert len(fills) == 0

def test_buy_limit_fills_at_open_when_open_below_limit(engine, bullish_bar):
    """Buy limit fills immediately when open price is below limit."""
    order = LimitOrder(action="BUY", totalQuantity=100, price=149.0)
    
    fills = engine.execute(order, bullish_bar)
    
    assert len(fills) == 1
    assert fills[0].execution.price == 148.0  # Fills at open price (better than limit)
    assert fills[0].execution.shares == 100
    assert fills[0].execution.time == datetime(2025, 1, 1, 9, 30)

def test_buy_limit_fills_when_entire_bar_below_limit(engine, bullish_bar):
    """Buy limit fills when entire bar is below limit price."""
    order = LimitOrder(action="BUY", totalQuantity=100, price=153.0)
    
    fills = engine.execute(order, bullish_bar)
    
    assert len(fills) == 1
    assert fills[0].execution.price == 148.0  # Fills at open price (market is favorable)
    assert fills[0].execution.shares == 100
    assert fills[0].execution.time == datetime(2025, 1, 1, 9, 30)

def test_buy_limit_on_bearish_bar_fills_at_limit(engine, bearish_bar):
    """Buy limit on bearish bar fills when low touches limit."""
    order = LimitOrder(action="BUY", totalQuantity=100, price=147.0)
    
    fills = engine.execute(order, bearish_bar)
    
    assert len(fills) == 1
    assert fills[0].execution.price == 147.0  # Fills at limit
    assert fills[0].execution.shares == 100

def test_buy_limit_on_bearish_bar_fills_at_open(engine, bearish_bar):
    """Buy limit on bearish bar fills at open when open below limit."""
    # bearish_bar: open=150, high=152, low=146, close=148
    order = LimitOrder(action="BUY", totalQuantity=100, price=151.0)
    
    fills = engine.execute(order, bearish_bar)
    
    assert len(fills) == 1
    assert fills[0].execution.price == 150.0  # Fills at open (better than limit)
    assert fills[0].execution.shares == 100

    #endregion

    #region Sell orders
def test_sell_limit_fills_when_high_touches_limit(engine, bullish_bar):
    """Sell limit fills at limit price when bar high reaches it."""
    order = LimitOrder(action="SELL", totalQuantity=100, price=151.0)
    
    fills = engine.execute(order, bullish_bar)
    
    assert len(fills) == 1
    assert fills[0].execution.price == 151.0
    assert fills[0].execution.shares == 100
    assert fills[0].execution.time == datetime(2025, 1, 1, 9, 30)

def test_sell_limit_no_fill_when_high_below_limit(engine, bullish_bar):
    """Sell limit doesn't fill when bar high stays below limit price."""
    order = LimitOrder(action="SELL", totalQuantity=100, price=153.0)
    
    fills = engine.execute(order, bullish_bar)
    
    assert len(fills) == 0

def test_sell_limit_fills_at_open_when_open_above_limit(engine, bullish_bar):
    """Sell limit fills immediately when open price is above limit."""
    order = LimitOrder(action="SELL", totalQuantity=100, price=147.0)
    
    fills = engine.execute(order, bullish_bar)
    
    assert len(fills) == 1
    assert fills[0].execution.price == 148.0  # Fills at open price (better than limit)
    assert fills[0].execution.shares == 100
    assert fills[0].execution.time == datetime(2025, 1, 1, 9, 30)

def test_sell_limit_fills_when_entire_bar_above_limit(engine, bullish_bar):
    """Sell limit fills when entire bar is above limit price."""
    order = LimitOrder(action="SELL", totalQuantity=100, price=145.0)
    
    fills = engine.execute(order, bullish_bar)
    
    assert len(fills) == 1
    assert fills[0].execution.price == 148.0  # Fills at open price (market is favorable)
    assert fills[0].execution.shares == 100
    assert fills[0].execution.time == datetime(2025, 1, 1, 9, 30)

def test_sell_limit_no_fill_when_entire_bar_below_limit(engine, bullish_bar):
    """Sell limit doesn't fill when entire bar is below limit price."""
    order = LimitOrder(action="SELL", totalQuantity=100, price=153.0)
    
    fills = engine.execute(order, bullish_bar)
    
    assert len(fills) == 0

def test_sell_limit_on_bearish_bar_fills_at_limit(engine, bearish_bar):
    """Sell limit on bearish bar fills when high touches limit."""
    order = LimitOrder(action="SELL", totalQuantity=100, price=151.0)
    
    fills = engine.execute(order, bearish_bar)
    
    assert len(fills) == 1
    assert fills[0].execution.price == 151.0  # Fills at limit
    assert fills[0].execution.shares == 100

def test_sell_limit_on_bearish_bar_no_fill(engine, bearish_bar):
    """Sell limit on bearish bar doesn't fill when high below limit."""
    # bearish_bar: open=150, high=152, low=146, close=148
    order = LimitOrder(action="SELL", totalQuantity=100, price=153.0)
    
    fills = engine.execute(order, bearish_bar)
    
    assert len(fills) == 0

    #endregion
#endregion

#region Stop Order Tests
    #region Buy orders
def test_buy_stop_on_high_passes_stop(engine, bullish_bar):
    """Buy stop triggers and fills at stop price."""
    order = StopOrder(action="BUY", totalQuantity=100, stopPrice=151.0)

    fills = engine.execute(order, bullish_bar)

    assert len(fills) == 1
    assert fills[0].execution.price == 151.0
    assert fills[0].execution.shares == 100
    assert fills[0].order.orderType == "STP"
    assert fills[0].execution.time == datetime(2025, 1, 1, 9, 30)

def test_buy_stop_no_trigger(engine, bullish_bar):
    """Buy stop doesn't trigger when bar high stays below stop price."""
    order = StopOrder(action="BUY", totalQuantity=100, stopPrice=153.0)
    
    fills = engine.execute(order, bullish_bar)
    
    assert len(fills) == 0

def test_buy_stop_on_full_gap(engine, bullish_bar):
    """Buy stop triggers when entire bar is above stop price."""
    order = StopOrder(action="BUY", totalQuantity=100, stopPrice=145.0)

    fills = engine.execute(order, bullish_bar)

    assert len(fills) == 1
    assert fills[0].execution.price == 148.0  # Fills at open (gap)
    assert fills[0].order.orderType == "STP"
    assert fills[0].execution.shares == 100

def test_buy_stop_on_bearish_bar_fills_at_stop(engine, bearish_bar):
    """Buy stop on bearish bar fills at stop when high touches stop."""
    # bearish_bar: open=150, high=152, low=146, close=148
    order = StopOrder(action="BUY", totalQuantity=100, stopPrice=151.0)

    fills = engine.execute(order, bearish_bar)

    assert len(fills) == 1
    assert fills[0].execution.price == 151.0
    assert fills[0].order.orderType == "STP"
    assert fills[0].execution.shares == 100

def test_buy_stop_on_bearish_bar_no_trigger(engine, bearish_bar):
    """Buy stop on bearish bar doesn't trigger when high below stop."""
    order = StopOrder(action="BUY", totalQuantity=100, stopPrice=153.0)
    
    fills = engine.execute(order, bearish_bar)
    
    assert len(fills) == 0

    #endregion

    #region Sell orders
def test_sell_stop_low_passes_stop(engine, bullish_bar):
    """Sell stop triggers and fills at stop price."""
    order = StopOrder(action="SELL", totalQuantity=100, stopPrice=147.0)

    fills = engine.execute(order, bullish_bar)

    assert len(fills) == 1
    assert fills[0].execution.price == 147.0
    assert fills[0].order.orderType == "STP"
    assert fills[0].execution.shares == 100
    assert fills[0].execution.time == datetime(2025, 1, 1, 9, 30)

def test_sell_stop_no_trigger(engine, bullish_bar):
    """Sell stop doesn't trigger when bar low stays above stop price."""
    order = StopOrder(action="SELL", totalQuantity=100, stopPrice=145.0)
    
    fills = engine.execute(order, bullish_bar)
    
    assert len(fills) == 0

def test_sell_stop_on_full_gap(engine, bullish_bar):
    """Sell stop triggers when entire bar is below stop price."""
    order = StopOrder(action="SELL", totalQuantity=100, stopPrice=153.0)

    fills = engine.execute(order, bullish_bar)

    assert len(fills) == 1
    assert fills[0].execution.price == 148.0  # Fills at open (gap)
    assert fills[0].order.orderType == "STP"
    assert fills[0].execution.shares == 100

def test_sell_stop_on_bearish_bar_fills_at_stop(engine, bearish_bar):
    """Sell stop on bearish bar fills at stop when low touches stop."""
    # bearish_bar: open=150, high=152, low=146, close=148
    order = StopOrder(action="SELL", totalQuantity=100, stopPrice=147.0)

    fills = engine.execute(order, bearish_bar)

    assert len(fills) == 1
    assert fills[0].execution.price == 147.0
    assert fills[0].order.orderType == "STP"
    assert fills[0].execution.shares == 100

def test_sell_stop_on_bearish_bar_fills_at_open_on_gap(engine, bearish_bar):
    """Sell stop on bearish bar fills at open when entire bar below stop (gap down)."""
    order = StopOrder(action="SELL", totalQuantity=100, stopPrice=153.0)

    fills = engine.execute(order, bearish_bar)

    assert len(fills) == 1
    assert fills[0].execution.price == 150.0  # Fills at open (gap)
    assert fills[0].order.orderType == "STP"
    assert fills[0].execution.shares == 100

    #endregion
#endregion
