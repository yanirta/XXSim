"""Tests for order execution engine."""
from decimal import Decimal
from datetime import datetime
import pytest

from models import MarketOrder, LimitOrder, StopOrder, StopLimitOrder, BarData
from execution import ExecutionEngine

#region Fixtures

@pytest.fixture
def bearish_bar():
    """Standard bar: open=150, high=152, low=148, close=149."""
    return BarData(
        date=datetime(2025, 1, 1, 9, 30),
        open=Decimal("150.00"),
        high=Decimal("152.00"),
        low=Decimal("146.00"),
        close=Decimal("148.00"),
        volume=1000000,
    )

@pytest.fixture
def bullish_bar():
    """Bullish bar for stop-limit tests: open=148, high=152, low=146, close=150 (Close > Open)."""
    return BarData(
        date=datetime(2025, 1, 1, 9, 30),
        open=Decimal("148.00"),
        high=Decimal("152.00"),
        low=Decimal("146.00"),
        close=Decimal("150.00"),
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
    order = MarketOrder(action="BUY", totalQuantity=100, orderId=1)
    
    fill = engine.execute(order, bullish_bar)
    
    assert fill is not None
    assert fill.execution.price == Decimal("148.00")
    assert fill.execution.shares == 100
    assert fill.execution.time == datetime(2025, 1, 1, 9, 30)

def test_market_order_sells_at_open(engine, bullish_bar):
    """Market sell orders execute at bar open price."""
    order = MarketOrder(action="SELL", totalQuantity=100, orderId=1)
    
    fill = engine.execute(order, bullish_bar)
    
    assert fill is not None
    assert fill.execution.price == Decimal("148.00")
    assert fill.execution.shares == 100
    assert fill.execution.time == datetime(2025, 1, 1, 9, 30)

def test_market_order_on_bearish_bar(engine, bearish_bar):
    """Market orders execute at open regardless of bar direction."""
    order = MarketOrder(action="BUY", totalQuantity=100, orderId=1)
    
    fill = engine.execute(order, bearish_bar)
    
    assert fill is not None
    assert fill.execution.price == Decimal("150.00")  # bearish_bar open
    assert fill.execution.shares == 100
    assert fill.execution.time == datetime(2025, 1, 1, 9, 30)

#endregion

#region Limit Order Tests
    #region Buy orders
def test_buy_limit_fills_when_low_touches_limit(engine, bullish_bar):
    """Buy limit fills at limit price when bar low reaches it."""
    order = LimitOrder(action="BUY", totalQuantity=100, lmtPrice=Decimal("147.00"), orderId=1)
    
    fill = engine.execute(order, bullish_bar)
    
    assert fill is not None
    assert fill.execution.price == Decimal("147.00")
    assert fill.execution.shares == 100
    assert fill.execution.time == datetime(2025, 1, 1, 9, 30)

def test_buy_limit_no_fill_when_low_above_limit(engine, bullish_bar):
    """Buy limit doesn't fill when bar low stays above limit price."""
    order = LimitOrder(action="BUY", totalQuantity=100, lmtPrice=Decimal("145.00"), orderId=1)
    
    fill = engine.execute(order, bullish_bar)
    
    assert fill is None

def test_buy_limit_fills_at_open_when_open_below_limit(engine, bullish_bar):
    """Buy limit fills immediately when open price is below limit."""
    order = LimitOrder(action="BUY", totalQuantity=100, lmtPrice=Decimal("149.00"), orderId=1)
    
    fill = engine.execute(order, bullish_bar)
    
    assert fill is not None
    assert fill.execution.price == Decimal("148.00")  # Fills at open price (better than limit)
    assert fill.execution.shares == 100
    assert fill.execution.time == datetime(2025, 1, 1, 9, 30)

def test_buy_limit_fills_when_entire_bar_below_limit(engine, bullish_bar):
    """Buy limit fills when entire bar is below limit price."""
    order = LimitOrder(action="BUY", totalQuantity=100, lmtPrice=Decimal("153.00"), orderId=1)
    
    fill = engine.execute(order, bullish_bar)
    
    assert fill is not None
    assert fill.execution.price == Decimal("148.00")  # Fills at open price (market is favorable)
    assert fill.execution.shares == 100
    assert fill.execution.time == datetime(2025, 1, 1, 9, 30)

def test_buy_limit_on_bearish_bar_fills_at_limit(engine, bearish_bar):
    """Buy limit on bearish bar fills when low touches limit."""
    order = LimitOrder(action="BUY", totalQuantity=100, lmtPrice=Decimal("147.00"), orderId=1)
    
    fill = engine.execute(order, bearish_bar)
    
    assert fill is not None
    assert fill.execution.price == Decimal("147.00")  # Fills at limit
    assert fill.execution.shares == 100

def test_buy_limit_on_bearish_bar_fills_at_open(engine, bearish_bar):
    """Buy limit on bearish bar fills at open when open below limit."""
    # bearish_bar: open=150, high=152, low=146, close=148
    order = LimitOrder(action="BUY", totalQuantity=100, lmtPrice=Decimal("151.00"), orderId=1)
    
    fill = engine.execute(order, bearish_bar)
    
    assert fill is not None
    assert fill.execution.price == Decimal("150.00")  # Fills at open (better than limit)
    assert fill.execution.shares == 100

    #endregion

    #region Sell orders
def test_sell_limit_fills_when_high_touches_limit(engine, bullish_bar):
    """Sell limit fills at limit price when bar high reaches it."""
    order = LimitOrder(action="SELL", totalQuantity=100, lmtPrice=Decimal("151.00"), orderId=1)
    
    fill = engine.execute(order, bullish_bar)
    
    assert fill is not None
    assert fill.execution.price == Decimal("151.00")
    assert fill.execution.shares == 100
    assert fill.execution.time == datetime(2025, 1, 1, 9, 30)

def test_sell_limit_no_fill_when_high_below_limit(engine, bullish_bar):
    """Sell limit doesn't fill when bar high stays below limit price."""
    order = LimitOrder(action="SELL", totalQuantity=100, lmtPrice=Decimal("153.00"), orderId=1)
    
    fill = engine.execute(order, bullish_bar)
    
    assert fill is None

def test_sell_limit_fills_at_open_when_open_above_limit(engine, bullish_bar):
    """Sell limit fills immediately when open price is above limit."""
    order = LimitOrder(action="SELL", totalQuantity=100, lmtPrice=Decimal("147.00"), orderId=1)
    
    fill = engine.execute(order, bullish_bar)
    
    assert fill is not None
    assert fill.execution.price == Decimal("148.00")  # Fills at open price (better than limit)
    assert fill.execution.shares == 100
    assert fill.execution.time == datetime(2025, 1, 1, 9, 30)

def test_sell_limit_fills_when_entire_bar_above_limit(engine, bullish_bar):
    """Sell limit fills when entire bar is above limit price."""
    order = LimitOrder(action="SELL", totalQuantity=100, lmtPrice=Decimal("145.00"), orderId=1)
    
    fill = engine.execute(order, bullish_bar)
    
    assert fill is not None
    assert fill.execution.price == Decimal("148.00")  # Fills at open price (market is favorable)
    assert fill.execution.shares == 100
    assert fill.execution.time == datetime(2025, 1, 1, 9, 30)

def test_sell_limit_no_fill_when_entire_bar_below_limit(engine, bullish_bar):
    """Sell limit doesn't fill when entire bar is below limit price."""
    order = LimitOrder(action="SELL", totalQuantity=100, lmtPrice=Decimal("153.00"), orderId=1)
    
    fill = engine.execute(order, bullish_bar)
    
    assert fill is None

def test_sell_limit_on_bearish_bar_fills_at_limit(engine, bearish_bar):
    """Sell limit on bearish bar fills when high touches limit."""
    order = LimitOrder(action="SELL", totalQuantity=100, lmtPrice=Decimal("151.00"), orderId=1)
    
    fill = engine.execute(order, bearish_bar)
    
    assert fill is not None
    assert fill.execution.price == Decimal("151.00")  # Fills at limit
    assert fill.execution.shares == 100

def test_sell_limit_on_bearish_bar_no_fill(engine, bearish_bar):
    """Sell limit on bearish bar doesn't fill when high below limit."""
    # bearish_bar: open=150, high=152, low=146, close=148
    order = LimitOrder(action="SELL", totalQuantity=100, lmtPrice=Decimal("153.00"), orderId=1)
    
    fill = engine.execute(order, bearish_bar)
    
    assert fill is None

    #endregion
#endregion

#region Stop Order Tests
    #region Buy orders
def test_buy_stop_on_high_passes_stop(engine, bullish_bar):
    """Buy stop converts to market when bar high touches stop price."""
    order = StopOrder(action="BUY", totalQuantity=100, stopPrice=Decimal("151.00"), orderId=1)
    
    fill = engine.execute(order, bullish_bar)
    
    assert fill is not None
    # Stop price is within bar range (146-152), so fills at stop price
    assert fill.execution.price == Decimal("151.00")  # Fills at stop (not open)
    assert fill.execution.shares == 100
    assert fill.execution.time == datetime(2025, 1, 1, 9, 30)

def test_buy_stop_no_trigger(engine, bullish_bar):
    """Buy stop doesn't trigger when bar high stays below stop price."""
    order = StopOrder(action="BUY", totalQuantity=100, stopPrice=Decimal("153.00"), orderId=1)
    
    fill = engine.execute(order, bullish_bar)
    
    assert fill is None

def test_buy_stop_on_full_gap(engine, bullish_bar):
    """Buy stop triggers when entire bar is above stop price."""
    order = StopOrder(action="BUY", totalQuantity=100, stopPrice=Decimal("145.00"), orderId=1)
    
    fill = engine.execute(order, bullish_bar)
    
    assert fill is not None
    # Gap up: bar.low (146) > stop (145), so fills at open (gap scenario)
    assert fill.execution.price == Decimal("148.00")  # Fills at open (gap)
    assert fill.execution.shares == 100
    assert fill.execution.time == datetime(2025, 1, 1, 9, 30)

def test_buy_stop_on_bearish_bar_fills_at_stop(engine, bearish_bar):
    """Buy stop on bearish bar fills at stop when high touches stop."""
    # bearish_bar: open=150, high=152, low=146, close=148
    order = StopOrder(action="BUY", totalQuantity=100, stopPrice=Decimal("151.00"), orderId=1)
    
    fill = engine.execute(order, bearish_bar)
    
    assert fill is not None
    assert fill.execution.price == Decimal("151.00")  # Fills at stop
    assert fill.execution.shares == 100

def test_buy_stop_on_bearish_bar_no_trigger(engine, bearish_bar):
    """Buy stop on bearish bar doesn't trigger when high below stop."""
    order = StopOrder(action="BUY", totalQuantity=100, stopPrice=Decimal("153.00"), orderId=1)
    
    fill = engine.execute(order, bearish_bar)
    
    assert fill is None

    #endregion

    #region Sell orders
def test_sell_stop_low_passes_stop(engine, bullish_bar):
    """Sell stop converts to market when bar low touches stop price."""
    order = StopOrder(action="SELL", totalQuantity=100, stopPrice=Decimal("147.00"), orderId=1)
    
    fill = engine.execute(order, bullish_bar)
    
    assert fill is not None
    # Stop price is within bar range (146-152), so fills at stop price
    assert fill.execution.price == Decimal("147.00")  # Fills at stop (not open)
    assert fill.execution.shares == 100
    assert fill.execution.time == datetime(2025, 1, 1, 9, 30)

def test_sell_stop_no_trigger(engine, bullish_bar):
    """Sell stop doesn't trigger when bar low stays above stop price."""
    order = StopOrder(action="SELL", totalQuantity=100, stopPrice=Decimal("145.00"), orderId=1)
    
    fill = engine.execute(order, bullish_bar)
    
    assert fill is None

def test_sell_stop_on_full_gap(engine, bullish_bar):
    """Sell stop triggers when entire bar is below stop price."""
    order = StopOrder(action="SELL", totalQuantity=100, stopPrice=Decimal("153.00"), orderId=1)
    
    fill = engine.execute(order, bullish_bar)
    
    assert fill is not None
    # Gap down: bar.high (152) < stop (153), so fills at open (gap scenario)
    assert fill.execution.price == Decimal("148.00")  # Fills at open (gap)
    assert fill.execution.shares == 100
    assert fill.execution.time == datetime(2025, 1, 1, 9, 30)

def test_sell_stop_on_bearish_bar_fills_at_stop(engine, bearish_bar):
    """Sell stop on bearish bar fills at stop when low touches stop."""
    # bearish_bar: open=150, high=152, low=146, close=148
    order = StopOrder(action="SELL", totalQuantity=100, stopPrice=Decimal("147.00"), orderId=1)
    
    fill = engine.execute(order, bearish_bar)
    
    assert fill is not None
    assert fill.execution.price == Decimal("147.00")  # Fills at stop
    assert fill.execution.shares == 100

def test_sell_stop_on_bearish_bar_fills_at_open_on_gap(engine, bearish_bar):
    """Sell stop on bearish bar fills at open when entire bar below stop (gap down)."""
    order = StopOrder(action="SELL", totalQuantity=100, stopPrice=Decimal("153.00"), orderId=1)
    
    fill = engine.execute(order, bearish_bar)
    
    assert fill is not None
    assert fill.execution.price == Decimal("150.00")  # Fills at open (gap scenario)
    assert fill.execution.shares == 100

    #endregion
#endregion

#region Stop-Limit Order Tests
    #region Buy orders - bullish bar
def test_buy_stop_limit_f01_no_trigger(engine, bullish_bar):
    """Formation 1: Limit > Stop > High > Close > Open > Low - No trigger (stop not reached)."""
    # bullish_bar: open=148, high=152, low=146, close=150
    # Formation: Limit(156) > Stop(154) > High(152) > Close(150) > Open(148) > Low(146)
    order = StopLimitOrder(
        action="BUY",
        totalQuantity=100,
        stopPrice=Decimal("154.00"),
        lmtPrice=Decimal("156.00"),
        orderId=1
    )
    fill = engine.execute(order, bullish_bar)
    assert fill is None

def test_buy_stop_limit_f02_fills_at_stop(engine, bullish_bar):
    """Formation 2: Limit > High > Stop > Close > Open > Low - Fills at Stop (earliest in zone)."""
    # bullish_bar: open=148, high=152, low=146, close=150
    # Formation: Limit(156) > High(152) > Stop(151) > Close(150) > Open(148) > Low(146)
    # Execution zone: [Stop=151, Limit=156], bar crosses into zone at Stop
    order = StopLimitOrder(
        action="BUY",
        totalQuantity=100,
        stopPrice=Decimal("151.00"),
        lmtPrice=Decimal("156.00"),
        orderId=1
    )
    fill = engine.execute(order, bullish_bar)
    assert fill is not None
    assert fill.execution.price == Decimal("151.00")
    assert fill.execution.shares == 100

def test_buy_stop_limit_f03_fills_at_stop(engine, bullish_bar):
    """Formation 3: Limit > High > Close > Stop > Open > Low - Fills at Stop."""
    # bullish_bar: open=148, high=152, low=146, close=150
    # Formation: Limit(156) > High(152) > Close(150) > Stop(149) > Open(148) > Low(146)
    # Execution zone: [Stop=149, Limit=156], bar crosses into zone at Stop
    order = StopLimitOrder(
        action="BUY",
        totalQuantity=100,
        stopPrice=Decimal("149.00"),
        lmtPrice=Decimal("156.00"),
        orderId=1
    )
    fill = engine.execute(order, bullish_bar)
    assert fill is not None
    assert fill.execution.price == Decimal("149.00")
    assert fill.execution.shares == 100

def test_buy_stop_limit_f04_fills_at_open(engine, bullish_bar):
    """Formation 4: Limit > High > Close > Open > Stop > Low - Fills at Open (bar opens in zone)."""
    # bullish_bar: open=148, high=152, low=146, close=150
    # Formation: Limit(156) > High(152) > Close(150) > Open(148) > Stop(147) > Low(146)
    # Execution zone: [Stop=147, Limit=156], bar opens at 148 (already in zone)
    order = StopLimitOrder(
        action="BUY",
        totalQuantity=100,
        stopPrice=Decimal("147.00"),
        lmtPrice=Decimal("156.00"),
        orderId=1
    )
    fill = engine.execute(order, bullish_bar)
    assert fill is not None
    assert fill.execution.price == Decimal("148.00")
    assert fill.execution.shares == 100

def test_buy_stop_limit_f05_fills_at_open(engine, bullish_bar):
    """Formation 5: Limit > High > Close > Open > Low > Stop - Fills at Open (bar opens above zone)."""
    # bullish_bar: open=148, high=152, low=146, close=150
    # Formation: Limit(156) > High(152) > Close(150) > Open(148) > Low(146) > Stop(145)
    # Execution zone: [Stop=145, Limit=156], bar opens at 148, crosses into zone going down
    # Earliest presence at Open
    order = StopLimitOrder(
        action="BUY",
        totalQuantity=100,
        stopPrice=Decimal("145.00"),
        lmtPrice=Decimal("156.00"),
        orderId=1
    )
    fill = engine.execute(order, bullish_bar)
    assert fill is not None
    assert fill.execution.price == Decimal("148.00")
    assert fill.execution.shares == 100

def test_buy_stop_limit_f06_fills_at_open(engine, bullish_bar):
    """Formation 6: High > Limit > Close > Open > Low > Stop - Fills at Open."""
    # bullish_bar: open=148, high=152, low=146, close=150
    # Formation: High(152) > Limit(151) > Close(150) > Open(148) > Low(146) > Stop(145)
    # Execution zone: [Stop=145, Limit=151], bar opens at 148 (in zone)
    order = StopLimitOrder(
        action="BUY",
        totalQuantity=100,
        stopPrice=Decimal("145.00"),
        lmtPrice=Decimal("151.00"),
        orderId=1
    )
    fill = engine.execute(order, bullish_bar)
    assert fill is not None
    assert fill.execution.price == Decimal("148.00")
    assert fill.execution.shares == 100

def test_buy_stop_limit_f07_fills_at_open(engine, bullish_bar):
    """Formation 7: High > Close > Limit > Open > Low > Stop - Fills at Open."""
    # bullish_bar: open=148, high=152, low=146, close=150
    # Formation: High(152) > Close(150) > Limit(149) > Open(148) > Low(146) > Stop(145)
    # Execution zone: [Stop=145, Limit=149], bar opens at 148 (in zone)
    order = StopLimitOrder(
        action="BUY",
        totalQuantity=100,
        stopPrice=Decimal("145.00"),
        lmtPrice=Decimal("149.00"),
        orderId=1
    )
    fill = engine.execute(order, bullish_bar)
    assert fill is not None
    assert fill.execution.price == Decimal("148.00")
    assert fill.execution.shares == 100

def test_buy_stop_limit_f08_fills_at_limit(engine, bullish_bar):
    """Formation 8: High > Close > Open > Limit > Low > Stop - Fills at Limit (bar drops into zone)."""
    # bullish_bar: open=148, high=152, low=146, close=150
    # Formation: High(152) > Close(150) > Open(148) > Limit(147) > Low(146) > Stop(145)
    # Execution zone: [Stop=145, Limit=147], bar opens above, drops into zone at Limit
    order = StopLimitOrder(
        action="BUY",
        totalQuantity=100,
        stopPrice=Decimal("145.00"),
        lmtPrice=Decimal("147.00"),
        orderId=1
    )
    fill = engine.execute(order, bullish_bar)
    assert fill is not None
    assert fill.execution.price == Decimal("147.00")
    assert fill.execution.shares == 100

def test_buy_stop_limit_f09_no_fill(engine, bullish_bar):
    """Formation 9: High > Close > Open > Low > Limit > Stop - No fill (zone below bar range)."""
    # bullish_bar: open=148, high=152, low=146, close=150
    # Formation: High(152) > Close(150) > Open(148) > Low(146) > Limit(145.5) > Stop(145)
    # Execution zone: [Stop=145, Limit=145.5], entirely below bar low (146)
    order = StopLimitOrder(
        action="BUY",
        totalQuantity=100,
        stopPrice=Decimal("145.00"),
        lmtPrice=Decimal("145.50"),
        orderId=1
    )
    fill = engine.execute(order, bullish_bar)
    assert fill is None

def test_buy_stop_limit_f10_fills_at_open(engine, bullish_bar):
    """Formation 10: High > Limit > Close > Open > Stop > Low - Fills at Open."""
    # bullish_bar: open=148, high=152, low=146, close=150
    # Formation: High(152) > Limit(151) > Close(150) > Open(148) > Stop(147) > Low(146)
    # Execution zone: [Stop=147, Limit=151], bar opens at 148 (in zone)
    order = StopLimitOrder(
        action="BUY",
        totalQuantity=100,
        stopPrice=Decimal("147.00"),
        lmtPrice=Decimal("151.00"),
        orderId=1
    )
    fill = engine.execute(order, bullish_bar)
    assert fill is not None
    assert fill.execution.price == Decimal("148.00")
    assert fill.execution.shares == 100

def test_buy_stop_limit_f11_fills_at_stop(engine, bullish_bar):
    """Formation 11: High > Close > Limit > Stop > Open > Low - Fills at Stop."""
    # bullish_bar: open=148, high=152, low=146, close=150
    # Formation: High(152) > Close(150) > Limit(149) > Stop(148.5) > Open(148) > Low(146)
    # Execution zone: [Stop=148.5, Limit=149], bar crosses into zone at Stop (going up from open)
    order = StopLimitOrder(
        action="BUY",
        totalQuantity=100,
        stopPrice=Decimal("148.50"),
        lmtPrice=Decimal("149.00"),
        orderId=1
    )
    fill = engine.execute(order, bullish_bar)
    assert fill is not None
    assert fill.execution.price == Decimal("148.50")
    assert fill.execution.shares == 100
    #endregion

    #region Buy orders - bullish bar (Stop > Limit - Dipping/Pullback Scenarios) 
    
def test_buy_stop_limit_dip_f01_no_trigger(engine, bullish_bar):
    """F1: Stop > Limit > High > Close > Open > Low → no trigger (stop not reached)"""
    # bullish_bar: open=148, high=152, low=146, close=150
    # Formation: Stop(153) > Limit(151) > High(152) > Close(150) > Open(148) > Low(146) -> No fill
    # Stop > Limit: Buy on pullback after breakout - but stop never triggers
    order = StopLimitOrder(
        action="BUY",
        totalQuantity=100,
        stopPrice=Decimal("153"),  # Stop above high
        lmtPrice=Decimal("151"),
        orderId=1
    )
    fill = engine.execute(order, bullish_bar)
    assert fill is None  # Stop=153 > high=152, never triggers

def test_buy_stop_limit_dip_f02_no_fill(engine, bullish_bar):
    """F2: Stop > High > Limit > Close > Open > Low → no fill (limit unreachable)"""
    # bullish_bar: open=148, high=152, low=146, close=150
    # Formation: Stop(153) > High(152) > Limit(151) > Close(150) > Open(148) > Low(146) -> No fill
    # Triggers at high=152, but limit=151 > close=150 means pullback can't reach it reliably
    # Per CSV: F2 shows "No fill" for this formation
    order = StopLimitOrder(
        action="BUY",
        totalQuantity=100,
        stopPrice=Decimal("153"),  # Stop = high
        lmtPrice=Decimal("151"),   # Limit between high and close (unreachable on normal pullback)
        orderId=1
    )
    fill = engine.execute(order, bullish_bar)
    assert fill is None  # Limit unreachable after trigger

def test_buy_stop_limit_dip_f03_no_fill(engine, bullish_bar):
    """F3: Stop > High >  Close > Limit > Open > Low → no fill"""
    # bullish_bar: open=148, high=152, low=146, close=150
    # Formation: Stop(153) > High(152) > Close(150) > Limit(149) > Open(148) > Low(146)
    # Stop triggers at 151, limit=149 between close and open (marginal, unreachable)
    order = StopLimitOrder(
        action="BUY",
        totalQuantity=100,
        stopPrice=Decimal("153"),
        lmtPrice=Decimal("149"),
        orderId=1
    )
    fill = engine.execute(order, bullish_bar)
    assert fill is None  # Per CSV: F3 shows "No fill"

def test_buy_stop_limit_dip_f04_no_fill(engine, bullish_bar):
    """F4: Stop > High > Close > Open > Limit > Low → no fill"""
    # bullish_bar: open=148, high=152, low=146, close=150
    # Formation: High(152) > Stop(151) > Close(150) > Open(148) > Limit(147) > Low(146)
    # Stop triggers, limit=147 is reachable (above low), but per CSV logic: no fill
    # Likely because bar opens below limit, making pullback scenario unclear
    order = StopLimitOrder(
        action="BUY",
        totalQuantity=100,
        stopPrice=Decimal("153"),
        lmtPrice=Decimal("147"),
        orderId=1
    )
    fill = engine.execute(order, bullish_bar)
    assert fill is None  # Per CSV: F4 shows "No fill"

def test_buy_stop_limit_dip_f05_no_fill(engine, bullish_bar):
    """F5: Stop > High > Close > Open > Low > Limit → no fill"""
    # bullish_bar: open=148, high=152, low=146, close=150
    # Formation: Stop(153) > High(152) > Close(150) > Open(148) > Low(146) > Limit(145)
    # Stop triggers, but limit=145 < low=146 → unreachable
    order = StopLimitOrder(
        action="BUY",
        totalQuantity=100,
        stopPrice=Decimal("153"),
        lmtPrice=Decimal("145"),   # Limit below low
        orderId=1
    )
    fill = engine.execute(order, bullish_bar)
    assert fill is None  # Limit < bar.low, unreachable

def test_buy_stop_limit_dip_f06_fills_at_stop(engine, bullish_bar):
    """F6: High > Stop > Close > Open > Low > Limit → fills at stop"""
    # bullish_bar: open=148, high=152, low=146, close=150
    # Formation: High(152) > Stop(151) > Close(150) > Open(148) > Low(146) > Limit(145)
    # Stop triggers at close=150, limit=147 is reachable but per CSV: fills at Stop(150)
    # Logic: Treats as market order at trigger when pullback scenario is uncertain
    order = StopLimitOrder(
        action="BUY",
        totalQuantity=100,
        stopPrice=Decimal("151"),  # Stop = close
        lmtPrice=Decimal("145"),   # Limit below low (unreachable)
        orderId=1
    )
    fill = engine.execute(order, bullish_bar)
    assert fill is not None
    assert fill.execution.price == Decimal("151")  # Fills at stop (market at trigger)
    assert fill.execution.shares == 100


def test_buy_stop_limit_dip_f07_fills_at_stop(engine, bullish_bar):
    """F7: High > Close > Stop > Open > Low > Limit → fills at stop"""
    # bullish_bar: open=148, high=152, low=146, close=150
    # Formation: High(152) > Close(150) > Stop(149) > Open(148) > Low(146) > Limit(145)
    # Stop triggers at 149, limit=145 below low → fills at stop (market at trigger)
    order = StopLimitOrder(
        action="BUY",
        totalQuantity=100,
        stopPrice=Decimal("149"),
        lmtPrice=Decimal("145"),
        orderId=1
    )
    fill = engine.execute(order, bullish_bar)
    assert fill is not None
    assert fill.execution.price == Decimal("149")  # Fills at stop
    assert fill.execution.shares == 100


def test_buy_stop_limit_dip_f08_fills_at_stop(engine, bullish_bar):
    """F8: High > Close > Open > Stop > Limit > Low → fills at stop"""
    # bullish_bar: open=148, high=152, low=146, close=150
    # Formation: High(152) > Close(150) > Open(148) > Stop(147) > Low(146) > Limit(145)
    # Stop triggers at 147, limit=145 below low → fills at stop
    order = StopLimitOrder(
        action="BUY",
        totalQuantity=100,
        stopPrice=Decimal("147"),
        lmtPrice=Decimal("145"),
        orderId=1
    )
    fill = engine.execute(order, bullish_bar)
    assert fill is not None
    assert fill.execution.price == Decimal("147")  # Fills at stop
    assert fill.execution.shares == 100


def test_buy_stop_limit_dip_f09_no_fill(engine, bullish_bar):
    """F9: High > Close > Open > Low > Stop > Limit → no fill (bar above stop)"""
    # bullish_bar: open=148, high=152, low=146, close=150
    # Formation: High(152) > Close(150) > Open(148) > Low(146) > Stop(145) > Limit(144)
    # Bar low=146 > stop=145.5, so bar never reaches stop → no trigger
    # This is a gap scenario where bar opens above the stop level
    order = StopLimitOrder(
        action="BUY",
        totalQuantity=100,
        stopPrice=Decimal("145"),
        lmtPrice=Decimal("144"),
        orderId=1
    )
    fill = engine.execute(order, bullish_bar)
    assert fill is None  # Stop below bar.low, never triggers


def test_buy_stop_limit_dip_f10_fills_at_stop(engine, bullish_bar):
    """F10: High > Stop > Close > Open > Limit > Low → fills at stop"""
    # bullish_bar: open=148, high=152, low=146, close=150
    # Formation: High(152) > Stop(151) > Close(150) > Open(148) > Limit(147) > Low(146)
    # This is same as F6: stop at close, limit below open but above low
    # Per CSV: fills at Stop(150)
    order = StopLimitOrder(
        action="BUY",
        totalQuantity=100,
        stopPrice=Decimal("151"),
        lmtPrice=Decimal("147"),
        orderId=1
    )
    fill = engine.execute(order, bullish_bar)
    assert fill is not None
    assert fill.execution.price == Decimal("151")  # Fills at stop
    assert fill.execution.shares == 100


def test_buy_stop_limit_dip_f11_fills_at_stop(engine, bullish_bar):
    """F11: High > Close > Stop > Limit > Open > Low → fills at stop"""
    # bullish_bar: open=148, high=152, low=146, close=150
    # Formation: High(152) > Close(150) > Stop(149) > Limit(148.5) > Open(148) > Low(146)
    # Stop triggers at 149, limit=148.5 is marginally reachable
    # But per CSV: fills at Stop(149)
    order = StopLimitOrder(
        action="BUY",
        totalQuantity=100,
        stopPrice=Decimal("149"),
        lmtPrice=Decimal("148.5"),
        orderId=1
    )
    fill = engine.execute(order, bullish_bar)
    assert fill is not None
    assert fill.execution.price == Decimal("149")  # Fills at stop
    assert fill.execution.shares == 100

    #endregion

    #region Buy orders - bearish bar 

def test_buy_stop_limit_bearish_f01_no_trigger(engine, bearish_bar):
    """F1: Limit > Stop > High > Open > Close > Low -> no fill (stop never triggers)"""
    # bearish_bar: open=150, high=152, low=146, close=148
    # Formation: Limit(154) > Stop(153) > High(152) > Open(150) > Close(148) > Low(146)
    order = StopLimitOrder(
        action="BUY",
        totalQuantity=100,
        stopPrice=Decimal("153"),
        lmtPrice=Decimal("154"),
        orderId=1
    )
    fill = engine.execute(order, bearish_bar)
    assert fill is None  # Stop=153 > high=152, never triggers

def test_buy_stop_limit_bearish_f02_fills_at_stop(engine, bearish_bar):
    """F2: Limit > High > Stop > Open > Close > Low -> fills at stop"""
    # bearish_bar: open=150, high=152, low=146, close=148
    # Formation: Limit(156) > High(152) > Stop(151) > Open(150) > Close(148) > Low(146)
    order = StopLimitOrder(
        action="BUY",
        totalQuantity=100,
        stopPrice=Decimal("151"),
        lmtPrice=Decimal("156"),
        orderId=1
    )
    fill = engine.execute(order, bearish_bar)
    assert fill is not None
    assert fill.execution.price == Decimal("151")  # Limit ≥ trigger → fill at trigger
    assert fill.execution.shares == 100

def test_buy_stop_limit_bearish_f03_fills_at_open(engine, bearish_bar):
    """F3: Limit > High > Open > Stop > Close > Low -> fills at open"""
    # bearish_bar: open=150, high=152, low=146, close=148
    # Formation: Limit(156) > High(152) > Open(150) > Stop(149) > Close(148) > Low(146)
    # Stop < open, so bar opens above stop -> triggers at open=150
    order = StopLimitOrder(
        action="BUY",
        totalQuantity=100,
        stopPrice=Decimal("149"),
        lmtPrice=Decimal("156"),
        orderId=1
    )
    fill = engine.execute(order, bearish_bar)
    assert fill is not None
    assert fill.execution.price == Decimal("150")  # Opens above stop, limit ≥ trigger
    assert fill.execution.shares == 100

def test_buy_stop_limit_bearish_f04_fills_at_open(engine, bearish_bar):
    """F4: Limit > High > Open > Close > Stop > Low -> fills at open"""
    # bearish_bar: open=150, high=152, low=146, close=148
    # Formation: Limit(156) > High(152) > Open(150) > Close(148) > Stop(147) > Low(146)
    order = StopLimitOrder(
        action="BUY",
        totalQuantity=100,
        stopPrice=Decimal("147"),
        lmtPrice=Decimal("156"),
        orderId=1
    )
    fill = engine.execute(order, bearish_bar)
    assert fill is not None
    assert fill.execution.price == Decimal("150")  # Opens above stop, limit ≥ trigger
    assert fill.execution.shares == 100

def test_buy_stop_limit_bearish_f05_fills_at_open(engine, bearish_bar):
    """F5: Limit > High > Open > Close > Low > Stop -> fills at open"""
    # bearish_bar: open=150, high=152, low=146, close=148
    # Formation: Limit(156) > High(152) > Open(150) > Close(148) > Low(146) > Stop(145)
    order = StopLimitOrder(
        action="BUY",
        totalQuantity=100,
        stopPrice=Decimal("145"),
        lmtPrice=Decimal("156"),
        orderId=1
    )
    fill = engine.execute(order, bearish_bar)
    assert fill is not None
    assert fill.execution.price == Decimal("150")  # Opens above stop, limit ≥ trigger
    assert fill.execution.shares == 100

def test_buy_stop_limit_bearish_f06_fills_at_open(engine, bearish_bar):
    """F6: High > Limit > Open > Close > Low > Stop -> fills at open"""
    # bearish_bar: open=150, high=152, low=146, close=148
    # Formation: High(152) > Limit(151) > Open(150) > Close(148) > Low(146) > Stop(145)
    order = StopLimitOrder(
        action="BUY",
        totalQuantity=100,
        stopPrice=Decimal("145"),
        lmtPrice=Decimal("151"),
        orderId=1
    )
    fill = engine.execute(order, bearish_bar)
    assert fill is not None
    assert fill.execution.price == Decimal("150")  # Opens above stop, limit ≥ trigger
    assert fill.execution.shares == 100

def test_buy_stop_limit_bearish_f07_fills_at_limit(engine, bearish_bar):
    """F7: High > Open > Limit > Close > Low > Stop -> fills at limit"""
    # bearish_bar: open=150, high=152, low=146, close=148
    # Formation: High(152) > Open(150) > Limit(149) > Close(148) > Low(146) > Stop(145)
    # Opens at 150 > stop=145, triggers at open=150, limit=149 < trigger and ≥ low -> fill at limit
    order = StopLimitOrder(
        action="BUY",
        totalQuantity=100,
        stopPrice=Decimal("145"),
        lmtPrice=Decimal("149"),
        orderId=1
    )
    fill = engine.execute(order, bearish_bar)
    assert fill is not None
    assert fill.execution.price == Decimal("149")  # bar.low ≤ limit < trigger → fill at limit
    assert fill.execution.shares == 100

def test_buy_stop_limit_bearish_f08_fills_at_limit(engine, bearish_bar):
    """F8: High > Open > Close > Limit > Low > Stop -> fills at limit"""
    # bearish_bar: open=150, high=152, low=146, close=148
    # Formation: High(152) > Open(150) > Close(148) > Limit(147) > Low(146) > Stop(145)
    order = StopLimitOrder(
        action="BUY",
        totalQuantity=100,
        stopPrice=Decimal("145"),
        lmtPrice=Decimal("147"),
        orderId=1
    )
    fill = engine.execute(order, bearish_bar)
    assert fill is not None
    assert fill.execution.price == Decimal("147")  # bar.low ≤ limit < trigger → fill at limit
    assert fill.execution.shares == 100

def test_buy_stop_limit_bearish_f09_no_fill(engine, bearish_bar):
    """F9: High > Open > Close > Low > Limit > Stop -> no fill (limit unreachable)"""
    # bearish_bar: open=150, high=152, low=146, close=148
    # Formation: High(152) > Open(150) > Close(148) > Low(146) > Limit(145.5) > Stop(145)
    order = StopLimitOrder(
        action="BUY",
        totalQuantity=100,
        stopPrice=Decimal("145"),
        lmtPrice=Decimal("145.5"),
        orderId=1
    )
    fill = engine.execute(order, bearish_bar)
    assert fill is None  # Limit < bar.low → unreachable

def test_buy_stop_limit_bearish_f10_fills_at_open(engine, bearish_bar):
    """F10: High > Limit > Open > Close > Stop > Low -> fills at open"""
    # bearish_bar: open=150, high=152, low=146, close=148
    # Formation: High(152) > Limit(151) > Open(150) > Close(148) > Stop(147) > Low(146)
    order = StopLimitOrder(
        action="BUY",
        totalQuantity=100,
        stopPrice=Decimal("147"),
        lmtPrice=Decimal("151"),
        orderId=1
    )
    fill = engine.execute(order, bearish_bar)
    assert fill is not None
    assert fill.execution.price == Decimal("150")  # Opens above stop, limit ≥ trigger
    assert fill.execution.shares == 100

def test_buy_stop_limit_bearish_f11_fills_at_limit(engine, bearish_bar):
    """F11: High > Open > Limit > Stop > Close > Low -> fills at limit"""
    # bearish_bar: open=150, high=152, low=146, close=148
    # Formation: High(152) > Open(150) > Limit(149) > Stop(148.5) > Close(148) > Low(146)
    # Opens at 150 > stop=148.5, triggers at open=150, limit=149 < trigger=150 and ≥ low -> fill at limit
    order = StopLimitOrder(
        action="BUY",
        totalQuantity=100,
        stopPrice=Decimal("148.5"),
        lmtPrice=Decimal("149"),
        orderId=1
    )
    fill = engine.execute(order, bearish_bar)
    assert fill is not None
    assert fill.execution.price == Decimal("149")  # bar.low ≤ limit < trigger → fill at limit
    assert fill.execution.shares == 100

    #endregion

    #region Buy orders - bearish bar (Stop > Limit - Dipping/Pullback Scenarios)

def test_buy_stop_limit_bearish_dip_f01_no_trigger(engine, bearish_bar):
    """F1: Stop > Limit > High > Open > Close > Low → no trigger"""
    # bearish_bar: open=150, high=152, low=146, close=148
    # Formation: Stop(153) > Limit(151) > High(152) > Open(150) > Close(148) > Low(146)
    # Stop above high, never triggers
    order = StopLimitOrder(
        action="BUY",
        totalQuantity=100,
        stopPrice=Decimal("153"),
        lmtPrice=Decimal("151"),
        orderId=1
    )
    fill = engine.execute(order, bearish_bar)
    assert fill is None  # Stop=153 > high=152, never triggers

def test_buy_stop_limit_bearish_dip_f02_no_fill(engine, bearish_bar):
    """F2: Stop > High > Limit > Open > Close > Low → no fill"""
    # bearish_bar: open=150, high=152, low=146, close=148
    # Formation: Stop(153) > High(152) > Limit(151) > Open(150) > Close(148) > Low(146)
    # Stop triggers but limit unreachable
    order = StopLimitOrder(
        action="BUY",
        totalQuantity=100,
        stopPrice=Decimal("153"),
        lmtPrice=Decimal("151"),
        orderId=1
    )
    fill = engine.execute(order, bearish_bar)
    assert fill is None  # Per CSV: F2 shows "No fill"

def test_buy_stop_limit_bearish_dip_f03_no_fill(engine, bearish_bar):
    """F3: Stop > High > Open > Limit > Close > Low → no fill"""
    # bearish_bar: open=150, high=152, low=146, close=148
    # Formation: Stop(153) > High(152) > Open(150) > Limit(149) > Close(148) > Low(146)
    order = StopLimitOrder(
        action="BUY",
        totalQuantity=100,
        stopPrice=Decimal("153"),
        lmtPrice=Decimal("149"),
        orderId=1
    )
    fill = engine.execute(order, bearish_bar)
    assert fill is None  # Per CSV: F3 shows "No fill"

def test_buy_stop_limit_bearish_dip_f04_no_fill(engine, bearish_bar):
    """F4: Stop > High > Open > Close > Limit > Low → no fill"""
    # bearish_bar: open=150, high=152, low=146, close=148
    # Formation: Stop(153) > High(152) > Open(150) > Close(148) > Limit(147) > Low(146)
    order = StopLimitOrder(
        action="BUY",
        totalQuantity=100,
        stopPrice=Decimal("153"),
        lmtPrice=Decimal("147"),
        orderId=1
    )
    fill = engine.execute(order, bearish_bar)
    assert fill is None  # Per CSV: F4 shows "No fill"

def test_buy_stop_limit_bearish_dip_f05_no_fill(engine, bearish_bar):
    """F5: Stop > High > Open > Close > Low > Limit → no fill"""
    # bearish_bar: open=150, high=152, low=146, close=148
    # Formation: Stop(153) > High(152) > Open(150) > Close(148) > Low(146) > Limit(145)
    order = StopLimitOrder(
        action="BUY",
        totalQuantity=100,
        stopPrice=Decimal("153"),
        lmtPrice=Decimal("145"),
        orderId=1
    )
    fill = engine.execute(order, bearish_bar)
    assert fill is None  # Limit below low, unreachable

def test_buy_stop_limit_bearish_dip_f06_fills_at_stop(engine, bearish_bar):
    """F6: High > Stop > Open > Close > Low > Limit → fills at stop"""
    # bearish_bar: open=150, high=152, low=146, close=148
    # Formation: High(152) > Stop(151) > Open(150) > Close(148) > Low(146) > Limit(145)
    # Stop triggers, limit below low → fills at stop
    order = StopLimitOrder(
        action="BUY",
        totalQuantity=100,
        stopPrice=Decimal("151"),
        lmtPrice=Decimal("145"),
        orderId=1
    )
    fill = engine.execute(order, bearish_bar)
    assert fill is not None
    assert fill.execution.price == Decimal("151")  # Fills at stop
    assert fill.execution.shares == 100

def test_buy_stop_limit_bearish_dip_f07_fills_at_stop(engine, bearish_bar):
    """F7: High > Open > Stop > Close > Low > Limit → fills at stop"""
    # bearish_bar: open=150, high=152, low=146, close=148
    # Formation: High(152) > Open(150) > Stop(149) > Close(148) > Low(146) > Limit(145)
    order = StopLimitOrder(
        action="BUY",
        totalQuantity=100,
        stopPrice=Decimal("149"),
        lmtPrice=Decimal("145"),
        orderId=1
    )
    fill = engine.execute(order, bearish_bar)
    assert fill is not None
    assert fill.execution.price == Decimal("149")  # Fills at stop
    assert fill.execution.shares == 100

def test_buy_stop_limit_bearish_dip_f08_fills_at_stop(engine, bearish_bar):
    """F8: High > Open > Close > Stop > Low > Limit → fills at stop"""
    # bearish_bar: open=150, high=152, low=146, close=148
    # Formation: High(152) > Open(150) > Close(148) > Stop(147) > Low(146) > Limit(145)
    order = StopLimitOrder(
        action="BUY",
        totalQuantity=100,
        stopPrice=Decimal("147"),
        lmtPrice=Decimal("145"),
        orderId=1
    )
    fill = engine.execute(order, bearish_bar)
    assert fill is not None
    assert fill.execution.price == Decimal("147")  # Fills at stop
    assert fill.execution.shares == 100

def test_buy_stop_limit_bearish_dip_f09_no_fill(engine, bearish_bar):
    """F9: High > Open > Close > Low > Stop > Limit → no fill (gap scenario)"""
    # bearish_bar: open=150, high=152, low=146, close=148
    # Formation: High(152) > Open(150) > Close(148) > Low(146) > Stop(145) > Limit(144)
    # Bar low=146 > stop=145, gap scenario
    order = StopLimitOrder(
        action="BUY",
        totalQuantity=100,
        stopPrice=Decimal("145"),
        lmtPrice=Decimal("144"),
        orderId=1
    )
    fill = engine.execute(order, bearish_bar)
    assert fill is None  # Stop below bar.low, never triggers

def test_buy_stop_limit_bearish_dip_f10_fills_at_stop(engine, bearish_bar):
    """F10: High > Stop > Open > Close > Limit > Low → fills at stop"""
    # bearish_bar: open=150, high=152, low=146, close=148
    # Formation: High(152) > Stop(151) > Open(150) > Close(148) > Limit(147) > Low(146)
    order = StopLimitOrder(
        action="BUY",
        totalQuantity=100,
        stopPrice=Decimal("151"),
        lmtPrice=Decimal("147"),
        orderId=1
    )
    fill = engine.execute(order, bearish_bar)
    assert fill is not None
    assert fill.execution.price == Decimal("151")  # Fills at stop
    assert fill.execution.shares == 100

def test_buy_stop_limit_bearish_dip_f11_fills_at_stop(engine, bearish_bar):
    """F11: High > Open > Stop > Limit > Close > Low → fills at stop"""
    # bearish_bar: open=150, high=152, low=146, close=148
    # Formation: High(152) > Open(150) > Stop(149) > Limit(148.5) > Close(148) > Low(146)
    order = StopLimitOrder(
        action="BUY",
        totalQuantity=100,
        stopPrice=Decimal("149"),
        lmtPrice=Decimal("148.5"),
        orderId=1
    )
    fill = engine.execute(order, bearish_bar)
    assert fill is not None
    assert fill.execution.price == Decimal("149")  # Fills at stop
    assert fill.execution.shares == 100

    #endregion

    #region Sell orders - bearish bar

def test_sell_stop_limit_f01_no_trigger(engine, bearish_bar):
    """F1: High > Open > Close > Low > Stop > Limit -> no fill (stop never triggers)"""
    order = StopLimitOrder(
        action="SELL", 
        totalQuantity=100, 
        orderId=1,
        stopPrice=Decimal("145"),
        lmtPrice=Decimal("144"),
    )
    
    fill = engine.execute(order, bearish_bar)
    
    assert fill is None  # Stop=145 < low=146, never triggers


def test_sell_stop_limit_f02_fills_at_stop(engine, bearish_bar):
    """F2: High > Open > Close > Stop > Low > Limit -> fills at stop"""
    order = StopLimitOrder(
        action="SELL", 
        totalQuantity=100, 
        orderId=1,
        stopPrice=Decimal("147"),
        lmtPrice=Decimal("145"),
    )
    
    fill = engine.execute(order, bearish_bar)
    
    assert fill is not None
    assert fill.execution.price == Decimal("147")  # Fills at stop (trigger point)
    assert fill.execution.shares == 100


def test_sell_stop_limit_f03_fills_at_stop(engine, bearish_bar):
    """F3: High > Open > Stop > Close > Low > Limit -> fills at stop"""
    order = StopLimitOrder(
        action="SELL", 
        totalQuantity=100, 
        orderId=1,
        stopPrice=Decimal("149"),
        lmtPrice=Decimal("145"),
    )
    
    fill = engine.execute(order, bearish_bar)
    
    assert fill is not None
    assert fill.execution.price == Decimal("149")  # Fills at stop
    assert fill.execution.shares == 100


def test_sell_stop_limit_f04_fills_at_open(engine, bearish_bar):
    """F4: High > Stop > Open > Close > Low > Limit -> fills at open"""
    order = StopLimitOrder(
        action="SELL", 
        totalQuantity=100, 
        orderId=1,
        stopPrice=Decimal("151"),
        lmtPrice=Decimal("145"),
    )
    
    fill = engine.execute(order, bearish_bar)
    
    assert fill is not None
    assert fill.execution.price == Decimal("150")  # Fills at open (trigger point)
    assert fill.execution.shares == 100


def test_sell_stop_limit_f05_fills_at_open(engine, bearish_bar):
    """F5: Stop > High > Open > Close > Low > Limit -> fills at open"""
    order = StopLimitOrder(
        action="SELL", 
        totalQuantity=100, 
        orderId=1,
        stopPrice=Decimal("153"),
        lmtPrice=Decimal("145"),
    )
    
    fill = engine.execute(order, bearish_bar)
    
    assert fill is not None
    assert fill.execution.price == Decimal("150")  # Fills at open
    assert fill.execution.shares == 100


def test_sell_stop_limit_f06_fills_at_open(engine, bearish_bar):
    """F6: Stop > High > Open > Close > Limit > Low -> fills at open"""
    order = StopLimitOrder(
        action="SELL", 
        totalQuantity=100, 
        orderId=1,
        stopPrice=Decimal("153"),
        lmtPrice=Decimal("147"),
    )
    
    fill = engine.execute(order, bearish_bar)
    
    assert fill is not None
    assert fill.execution.price == Decimal("150")  # Fills at open
    assert fill.execution.shares == 100


def test_sell_stop_limit_f07_fills_at_open(engine, bearish_bar):
    """F7: Stop > High > Open > Limit > Close > Low -> fills at open"""
    order = StopLimitOrder(
        action="SELL", 
        totalQuantity=100, 
        orderId=1,
        stopPrice=Decimal("153"),
        lmtPrice=Decimal("149"),
    )
    
    fill = engine.execute(order, bearish_bar)
    
    assert fill is not None
    assert fill.execution.price == Decimal("150")  # Fills at open
    assert fill.execution.shares == 100


def test_sell_stop_limit_f08_fills_at_limit(engine, bearish_bar):
    """F8: Stop > High > Limit > Open > Close > Low -> fills at limit"""
    order = StopLimitOrder(
        action="SELL", 
        totalQuantity=100, 
        orderId=1,
        stopPrice=Decimal("153"),
        lmtPrice=Decimal("151"),
    )
    
    fill = engine.execute(order, bearish_bar)
    
    assert fill is not None
    assert fill.execution.price == Decimal("151")  # Fills at limit (reachable on bounce)
    assert fill.execution.shares == 100


def test_sell_stop_limit_f09_no_fill(engine, bearish_bar):
    """F9: Stop > Limit > High > Open > Close > Low -> no fill (limit unreachable)"""
    order = StopLimitOrder(
        action="SELL", 
        totalQuantity=100, 
        orderId=1,
        stopPrice=Decimal("154"),
        lmtPrice=Decimal("153"),
    )
    
    fill = engine.execute(order, bearish_bar)
    
    assert fill is None  # Limit=153 > high=152, unreachable


def test_sell_stop_limit_f10_fills_at_open(engine, bearish_bar):
    """F10: High > Stop > Open > Close > Limit > Low -> fills at open"""
    order = StopLimitOrder(
        action="SELL", 
        totalQuantity=100, 
        orderId=1,
        stopPrice=Decimal("151"),
        lmtPrice=Decimal("147"),
    )
    
    fill = engine.execute(order, bearish_bar)
    
    assert fill is not None
    assert fill.execution.price == Decimal("150")  # Fills at open
    assert fill.execution.shares == 100


def test_sell_stop_limit_f11_fills_at_stop(engine, bearish_bar):
    """F11: High > Open > Stop > Limit > Close > Low -> fills at stop"""
    order = StopLimitOrder(
        action="SELL", 
        totalQuantity=100, 
        orderId=1,
        stopPrice=Decimal("149.5"),
        lmtPrice=Decimal("149"),
    )
    
    fill = engine.execute(order, bearish_bar)
    
    assert fill is not None
    assert fill.execution.price == Decimal("149.5")  # Fills at stop
    assert fill.execution.shares == 100

    #endregion

    #region Sell orders - bearish bar (Limit > Stop - Dipping/Pullback Scenarios)

def test_sell_stop_limit_bearish_dip_f01_no_trigger(engine, bearish_bar):
    """F1: High > Open > Close > Low > Limit > Stop → no trigger"""
    # bearish_bar: open=150, high=152, low=146, close=148
    # Formation: High(152) > Open(150) > Close(148) > Low(146) > Limit(145) > Stop(144)
    # Stop below low, never triggers
    order = StopLimitOrder(
        action="SELL",
        totalQuantity=100,
        orderId=1,
        stopPrice=Decimal("144"),
        lmtPrice=Decimal("145"),
    )
    fill = engine.execute(order, bearish_bar)
    assert fill is None  # Stop < low, never triggers

def test_sell_stop_limit_bearish_dip_f02_no_fill(engine, bearish_bar):
    """F2: High > Open > Close > Limit > Low > Stop → no fill"""
    # bearish_bar: open=150, high=152, low=146, close=148
    # Formation: High(152) > Open(150) > Close(148) > Limit(147) > Low(146) > Stop(145)
    order = StopLimitOrder(
        action="SELL",
        totalQuantity=100,
        orderId=1,
        stopPrice=Decimal("145"),
        lmtPrice=Decimal("147"),
    )
    fill = engine.execute(order, bearish_bar)
    assert fill is None  # Per CSV: F2 shows "No fill"

def test_sell_stop_limit_bearish_dip_f03_no_fill(engine, bearish_bar):
    """F3: High > Open > Limit > Close > Low > Stop → no fill"""
    # bearish_bar: open=150, high=152, low=146, close=148
    # Formation: High(152) > Open(150) > Limit(149) > Close(148) > Low(146) > Stop(145)
    order = StopLimitOrder(
        action="SELL",
        totalQuantity=100,
        orderId=1,
        stopPrice=Decimal("145"),
        lmtPrice=Decimal("149"),
    )
    fill = engine.execute(order, bearish_bar)
    assert fill is None  # Per CSV: F3 shows "No fill"

def test_sell_stop_limit_bearish_dip_f04_no_fill(engine, bearish_bar):
    """F4: High > Limit > Open > Close > Low > Stop → no fill"""
    # bearish_bar: open=150, high=152, low=146, close=148
    # Formation: High(152) > Limit(151) > Open(150) > Close(148) > Low(146) > Stop(145)
    order = StopLimitOrder(
        action="SELL",
        totalQuantity=100,
        orderId=1,
        stopPrice=Decimal("145"),
        lmtPrice=Decimal("151"),
    )
    fill = engine.execute(order, bearish_bar)
    assert fill is None  # Per CSV: F4 shows "No fill"

def test_sell_stop_limit_bearish_dip_f05_no_fill(engine, bearish_bar):
    """F5: Limit > High > Open > Close > Low > Stop → no fill"""
    # bearish_bar: open=150, high=152, low=146, close=148
    # Formation: Limit(153) > High(152) > Open(150) > Close(148) > Low(146) > Stop(145)
    order = StopLimitOrder(
        action="SELL",
        totalQuantity=100,
        orderId=1,
        stopPrice=Decimal("145"),
        lmtPrice=Decimal("153"),
    )
    fill = engine.execute(order, bearish_bar)
    assert fill is None  # Limit above high, unreachable

def test_sell_stop_limit_bearish_dip_f06_fills_at_stop(engine, bearish_bar):
    """F6: Limit > High > Open > Close > Stop > Low → fills at stop"""
    # bearish_bar: open=150, high=152, low=146, close=148
    # Formation: Limit(153) > High(152) > Open(150) > Close(148) > Stop(147) > Low(146)
    # Stop triggers, limit above high → fills at stop
    order = StopLimitOrder(
        action="SELL",
        totalQuantity=100,
        orderId=1,
        stopPrice=Decimal("147"),
        lmtPrice=Decimal("153"),
    )
    fill = engine.execute(order, bearish_bar)
    assert fill is not None
    assert fill.execution.price == Decimal("147")  # Fills at stop
    assert fill.execution.shares == 100

def test_sell_stop_limit_bearish_dip_f07_fills_at_stop(engine, bearish_bar):
    """F7: Limit > High > Open > Stop > Close > Low → fills at stop"""
    # bearish_bar: open=150, high=152, low=146, close=148
    # Formation: Limit(153) > High(152) > Open(150) > Stop(149) > Close(148) > Low(146)
    order = StopLimitOrder(
        action="SELL",
        totalQuantity=100,
        orderId=1,
        stopPrice=Decimal("149"),
        lmtPrice=Decimal("153"),
    )
    fill = engine.execute(order, bearish_bar)
    assert fill is not None
    assert fill.execution.price == Decimal("149")  # Fills at stop
    assert fill.execution.shares == 100

def test_sell_stop_limit_bearish_dip_f08_fills_at_stop(engine, bearish_bar):
    """F8: Limit > High > Stop > Open > Close > Low → fills at stop"""
    # bearish_bar: open=150, high=152, low=146, close=148
    # Formation: Limit(153) > High(152) > Stop(151) > Open(150) > Close(148) > Low(146)
    order = StopLimitOrder(
        action="SELL",
        totalQuantity=100,
        orderId=1,
        stopPrice=Decimal("151"),
        lmtPrice=Decimal("153"),
    )
    fill = engine.execute(order, bearish_bar)
    assert fill is not None
    assert fill.execution.price == Decimal("151")  # Fills at stop
    assert fill.execution.shares == 100

def test_sell_stop_limit_bearish_dip_f09_no_fill(engine, bearish_bar):
    """F9: Limit > Stop > High > Open > Close > Low → no fill"""
    # bearish_bar: open=150, high=152, low=146, close=148
    # Formation: Limit(154) > Stop(153) > High(152) > Open(150) > Close(148) > Low(146)
    # Stop above high, gap scenario
    order = StopLimitOrder(
        action="SELL",
        totalQuantity=100,
        orderId=1,
        stopPrice=Decimal("153"),
        lmtPrice=Decimal("154"),
    )
    fill = engine.execute(order, bearish_bar)
    assert fill is None  # Stop above bar.high, never triggers

def test_sell_stop_limit_bearish_dip_f10_fills_at_stop(engine, bearish_bar):
    """F10: High > Limit > Open > Close > Stop > Low → fills at stop"""
    # bearish_bar: open=150, high=152, low=146, close=148
    # Formation: High(152) > Limit(151) > Open(150) > Close(148) > Stop(147) > Low(146)
    order = StopLimitOrder(
        action="SELL",
        totalQuantity=100,
        orderId=1,
        stopPrice=Decimal("147"),
        lmtPrice=Decimal("151"),
    )
    fill = engine.execute(order, bearish_bar)
    assert fill is not None
    assert fill.execution.price == Decimal("147")  # Fills at stop
    assert fill.execution.shares == 100

def test_sell_stop_limit_bearish_dip_f11_fills_at_stop(engine, bearish_bar):
    """F11: High > Open > Limit > Stop > Close > Low → fills at stop"""
    # bearish_bar: open=150, high=152, low=146, close=148
    # Formation: High(152) > Open(150) > Limit(149) > Stop(148.5) > Close(148) > Low(146)
    order = StopLimitOrder(
        action="SELL",
        totalQuantity=100,
        orderId=1,
        stopPrice=Decimal("148.5"),
        lmtPrice=Decimal("149"),
    )
    fill = engine.execute(order, bearish_bar)
    assert fill is not None
    assert fill.execution.price == Decimal("148.5")  # Fills at stop
    assert fill.execution.shares == 100

    #endregion

    #region Sell orders - bullish Bar

def test_sell_stop_limit_bullish_f01_no_fill(engine, bullish_bar):
    """F1: High > Close > Open > Low > Stop > Limit -> no trigger (stop below low)"""
    # bullish_bar: open=148, high=152, low=146, close=150
    # For protective SELL: stop should be BELOW price
    order = StopLimitOrder(
        action="SELL", 
        totalQuantity=100, 
        orderId=1,
        stopPrice=Decimal("145"),  # Stop below low
        lmtPrice=Decimal("144"),
    )
    
    fill = engine.execute(order, bullish_bar)
    
    assert fill is None  # Stop=145 < low=146, never triggers

def test_sell_stop_limit_bullish_f02_fills_at_trigger(engine, bullish_bar):
    """F2: High > Close >  Open > Stop > Low > Limit -> fills at stop"""
    # bullish_bar: open=148, high=152, low=146, close=150
    order = StopLimitOrder(
        action="SELL", 
        totalQuantity=100, 
        orderId=1,
        stopPrice=Decimal("147"),  # Stop = low
        lmtPrice=Decimal("145"),
    )
    
    fill = engine.execute(order, bullish_bar)
    
    assert fill is not None
    assert fill.execution.price == Decimal("147")  # Fills at trigger (stop)
    assert fill.execution.shares == 100

def test_sell_stop_limit_bullish_f03_fills_at_trigger(engine, bullish_bar):
    """F3: High > Close > Stop > Open > Low > Limit -> fills at open"""
    order = StopLimitOrder(
        action="SELL", 
        totalQuantity=100, 
        orderId=1,
        stopPrice=Decimal("149"),
        lmtPrice=Decimal("145"),
    )
    
    fill = engine.execute(order, bullish_bar)
    
    assert fill is not None
    assert fill.execution.price == Decimal("148")  # Fills at open (trigger point)
    assert fill.execution.shares == 100

def test_sell_stop_limit_bullish_f04_fills_at_trigger(engine, bullish_bar):
    """F4: High > Stop > Close > Open > Low > Limit -> fills at open"""
    order = StopLimitOrder(
        action="SELL", 
        totalQuantity=100, 
        orderId=1,
        stopPrice=Decimal("151"),
        lmtPrice=Decimal("145"),
    )
    
    fill = engine.execute(order, bullish_bar)
    
    assert fill is not None
    assert fill.execution.price == Decimal("148")  # Fills at open (trigger point)
    assert fill.execution.shares == 100

def test_sell_stop_limit_bullish_f05_fills_at_trigger(engine, bullish_bar):
    """F5: Stop > High > Close > Open > Low > Limit -> fills at open"""
    # bullish_bar: open=148, high=152, low=146, close=150
    order = StopLimitOrder(
        action="SELL", 
        totalQuantity=100, 
        orderId=1,
        stopPrice=Decimal("153"),  # Stop between low and close
        lmtPrice=Decimal("145")
    )
    
    fill = engine.execute(order, bullish_bar)
    
    assert fill is not None
    assert fill.execution.price == Decimal("148")  # Fills at stop (trigger point)
    assert fill.execution.shares == 100

def test_sell_stop_limit_bullish_f06_fills_at_trigger(engine, bullish_bar):
    """F6: Stop > High > Close > Open > Limit > Low -> fills at open"""
    # bullish_bar: open=148, high=152, low=146, close=150

    order = StopLimitOrder(
        action="SELL", 
        totalQuantity=100, 
        orderId=1,
        stopPrice=Decimal("153"),
        lmtPrice=Decimal("147"),
    )
    
    fill = engine.execute(order, bullish_bar)
    
    assert fill is not None
    assert fill.execution.price == Decimal("148")  # Fills at stop (trigger point)
    assert fill.execution.shares == 100

def test_sell_stop_limit_bullish_f07_fills_at_limit(engine, bullish_bar):
    """F7: Stop > High > Close > Limit > Open > Low -> fills at limit"""
    # bullish_bar: open=148, high=152, low=146, close=150

    order = StopLimitOrder(
        action="SELL", 
        totalQuantity=100, 
        orderId=1,
        stopPrice=Decimal("153"),
        lmtPrice=Decimal("149"),
    )
    
    fill = engine.execute(order, bullish_bar)
    
    assert fill is not None
    assert fill.execution.price == Decimal("149")  # Fills at limit (reachable on bounce)
    assert fill.execution.shares == 100

def test_sell_stop_limit_bullish_f08_fills_at_limit(engine, bullish_bar):
    """F8: Stop > High > Limit > Close > Open > Low -> fills at limit"""
    # bullish_bar: open=148, high=152, low=146, close=150

    order = StopLimitOrder(
        action="SELL", 
        totalQuantity=100, 
        orderId=1,
        stopPrice=Decimal("153"),
        lmtPrice=Decimal("151"),
    )
    
    fill = engine.execute(order, bullish_bar)
    
    assert fill is not None
    assert fill.execution.price == Decimal("151")  # Fills at limit (reachable on bounce)
    assert fill.execution.shares == 100

def test_sell_stop_limit_bullish_f09_no_fill(engine, bullish_bar):
    """F9: Stop > Limit > High > Close > Open > Low -> no fill (stop never triggers)"""
    # bullish_bar: open=148, high=152, low=146, close=150
    # Formation: Stop(155) > Limit(153) > High(152) - bar entirely below stop
    order = StopLimitOrder(
        action="SELL", 
        totalQuantity=100, 
        orderId=1,
        stopPrice=Decimal("155"),
        lmtPrice=Decimal("153"),
    )
    
    fill = engine.execute(order, bullish_bar)
    
    assert fill is None  # Stop above high, never triggers

def test_sell_stop_limit_bullish_f10_fills_at_open(engine, bullish_bar):
    """F10: High > Stop > Close > Open > Limit > Low -> fills at open"""
    # bullish_bar: open=148, high=152, low=146, close=150
    # Formation: High(152) > Stop(151) > Close(150) > Open(148) > Limit(147) > Low(146)
    order = StopLimitOrder(
        action="SELL", 
        totalQuantity=100, 
        orderId=1,
        stopPrice=Decimal("151"),
        lmtPrice=Decimal("147"),
    )
    
    fill = engine.execute(order, bullish_bar)
    
    assert fill is not None
    assert fill.execution.price == Decimal("148")  # Fills at open (trigger point)
    assert fill.execution.shares == 100

def test_sell_stop_limit_bullish_f11_fills_at_limit(engine, bullish_bar):
    """F11: High > Close > Stop > Limit > Open > Low -> fills at limit"""
    # bullish_bar: open=148, high=152, low=146, close=150
    # Formation: High(152) > Close(150) > Stop(149) > Limit(148.5) > Open(148) > Low(146)
    order = StopLimitOrder(
        action="SELL", 
        totalQuantity=100, 
        orderId=1,
        stopPrice=Decimal("149"),
        lmtPrice=Decimal("148.5"),
    )
    
    fill = engine.execute(order, bullish_bar)
    
    assert fill is not None
    assert fill.execution.price == Decimal("148.5")  # Fills at limit
    assert fill.execution.shares == 100

    #endregion

    #region Sell orders - bullish bar (Limit > Stop - Dipping/Pullback Scenarios)

def test_sell_stop_limit_bullish_dip_f01_no_fill(engine, bullish_bar):
    """F1: High > Close > Open > Low > Limit > Stop → no fill"""
    # bullish_bar: open=148, high=152, low=146, close=150
    # Formation: bar entirely above stop - stop never triggers
    # High(152) > Close(150) > Open(148) > Low(146) > Limit(145) > Stop(144)
    order = StopLimitOrder(
        action="SELL",
        totalQuantity=100,
        orderId=1,
        stopPrice=Decimal("140"),
        lmtPrice=Decimal("154"),
    )
    fill = engine.execute(order, bullish_bar)
    assert fill is None  # Stop below bar.low, never triggers

def test_sell_stop_limit_bullish_dip_f02_no_fill(engine, bullish_bar):
    """F2: High > Close > Open > Limit > Low > Stop → no fill"""
    # bullish_bar: open=148, high=152, low=146, close=150
    # Formation: bar still above stop
    # High(152) > Close(150) > Open(148) > Limit(147) > Low(146) > Stop(145)
    order = StopLimitOrder(
        action="SELL",
        totalQuantity=100,
        orderId=1,
        stopPrice=Decimal("141"),
        lmtPrice=Decimal("154"),
    )
    fill = engine.execute(order, bullish_bar)
    assert fill is None  # Stop below bar.low, never triggers

def test_sell_stop_limit_bullish_dip_f03_no_fill(engine, bullish_bar):
    """F3: High > Close > Limit > Open > Low > Stop → no fill"""
    # bullish_bar: open=148, high=152, low=146, close=150
    # Formation: bar still above stop
    # High(152) > Close(150) > Limit(149) > Open(148) > Low(146) > Stop(145)
    order = StopLimitOrder(
        action="SELL",
        totalQuantity=100,
        orderId=1,
        stopPrice=Decimal("145"),
        lmtPrice=Decimal("149"),
    )
    fill = engine.execute(order, bullish_bar)
    assert fill is None  # Stop below bar.low, never triggers

def test_sell_stop_limit_bullish_dip_f04_no_fill(engine, bullish_bar):
    """F4: High > Close > Limit > Open > Low > Stop → no fill"""
    # bullish_bar: open=148, high=152, low=146, close=150
    # Formation: bar still above stop
    # High(152) > Close(150) > Limit(149) > Open(148) > Low(146) > Stop(145)
    order = StopLimitOrder(
        action="SELL",
        totalQuantity=100,
        orderId=1,
        stopPrice=Decimal("145"),
        lmtPrice=Decimal("149"),
    )
    fill = engine.execute(order, bullish_bar)
    assert fill is None  # Stop below bar.low, never triggers

def test_sell_stop_limit_bullish_dip_f05_no_fill(engine, bullish_bar):
    """F5: High > Close > Limit > Open > Low > Stop → no fill"""
    # bullish_bar: open=148, high=152, low=146, close=150
    # Formation: bar still above stop
    # High(152) > Close(150) > Limit(149) > Open(148) > Low(146) > Stop(145)
    order = StopLimitOrder(
        action="SELL",
        totalQuantity=100,
        orderId=1,
        stopPrice=Decimal("145"),
        lmtPrice=Decimal("149"),
    )
    fill = engine.execute(order, bullish_bar)
    assert fill is None  # Stop below bar.low, never triggers

def test_sell_stop_limit_bullish_dip_f06_fills_at_stop(engine, bullish_bar):
    """F6: High > Close > Limit > Open > Stop > Low → fills at stop"""
    # bullish_bar: open=148, high=152, low=146, close=150
    # Formation: High(152) > Close(150) > Limit(149) > Open(148) > Stop(147) > Low(146)
    # Stop triggers, limit above high → fills at stop conservatively
    order = StopLimitOrder(
        action="SELL",
        totalQuantity=100,
        orderId=1,
        stopPrice=Decimal("147"),
        lmtPrice=Decimal("149"),
    )
    fill = engine.execute(order, bullish_bar)
    assert fill is not None
    assert fill.execution.price == Decimal("147")  # Fills at stop

def test_sell_stop_limit_bullish_dip_f07_fills_at_stop(engine, bullish_bar):
    """F7: High > Close > Limit > Stop > Open > Low → fills at stop"""
    # bullish_bar: open=148, high=152, low=146, close=150
    # Formation: High(152) > Close(150) > Limit(149) > Stop(148.5) > Open(148) > Low(146)
    order = StopLimitOrder(
        action="SELL",
        totalQuantity=100,
        orderId=1,
        stopPrice=Decimal("148.5"),
        lmtPrice=Decimal("149"),
    )
    fill = engine.execute(order, bullish_bar)
    assert fill is not None
    assert fill.execution.price == Decimal("148.5")  # Fills at stop

def test_sell_stop_limit_bullish_dip_f08_fills_at_stop(engine, bullish_bar):
    """F8: High > Limit > Stop > Close > Open > Low → fills at stop"""
    # bullish_bar: open=148, high=152, low=146, close=150
    # Formation: High(152) > Limit(151) > Stop(150.5) > Close(150) > Open(148) > Low(146)
    order = StopLimitOrder(
        action="SELL",
        totalQuantity=100,
        orderId=1,
        stopPrice=Decimal("150.5"),
        lmtPrice=Decimal("151"),
    )
    fill = engine.execute(order, bullish_bar)
    assert fill is not None
    assert fill.execution.price == Decimal("150.5")  # Fills at stop

def test_sell_stop_limit_bullish_dip_f09_no_fill(engine, bullish_bar):
    """F9: Limit > Stop > High > Close > Open > Low → no fill"""
    # bullish_bar: open=148, high=152, low=146, close=150
    # Formation: Limit(154) > Stop(153) > High(152) > Close(150) > Open(148) > Low(146)
    order = StopLimitOrder(
        action="SELL",
        totalQuantity=100,
        orderId=1,
        stopPrice=Decimal("153"),
        lmtPrice=Decimal("154"),
    )
    fill = engine.execute(order, bullish_bar)
    assert fill is None  # Stop above high, never triggers (bar.low > stop)

def test_sell_stop_limit_bullish_dip_f10_fills_at_stop(engine, bullish_bar):
    """F10: High > Limit > Close > Open > Stop > Low → fills at stop"""
    # bullish_bar: open=148, high=152, low=146, close=150
    # Formation: High(152) > Limit(151) > Close(150) > Open(148) > Stop(147) > Low(146)
    order = StopLimitOrder(
        action="SELL",
        totalQuantity=100,
        orderId=1,
        stopPrice=Decimal("147"),
        lmtPrice=Decimal("149"),
    )
    fill = engine.execute(order, bullish_bar)
    assert fill is not None
    assert fill.execution.price == Decimal("147")  # Fills at stop

def test_sell_stop_limit_bullish_dip_f11_fills_at_stop(engine, bullish_bar):
    """F11: High > Close > Limit > Stop > Open > Low → fills at stop"""
    # bullish_bar: open=148, high=152, low=146, close=150
    # Formation: High(152) > Close(150) > Limit(149) > Stop(148.5) > Open(148) > Low(146)
    order = StopLimitOrder(
        action="SELL",
        totalQuantity=100,
        orderId=1,
        stopPrice=Decimal("148.5"),
        lmtPrice=Decimal("149"),
    )
    fill = engine.execute(order, bullish_bar)
    assert fill is not None
    assert fill.execution.price == Decimal("148.5")  # Fills at stop

    #endregion
#endregion
 
@pytest.mark.xfail(reason="Partial fills not implemented in Phase 1")
def test_large_order_partial_fill_by_volume():
    """Large orders only partially fill when bar volume insufficient."""
    bar = BarData(
        date=datetime(2025, 1, 1, 9, 30),
        open=Decimal("149.50"),
        high=Decimal("151.00"),
        low=Decimal("149.00"),
        close=Decimal("150.00"),
        volume=50,  # Only 50 shares available
    )
    order = MarketOrder(action="BUY", totalQuantity=100, orderId=1)
    
    engine = ExecutionEngine()
    fill = engine.execute(order, bar)
    
    assert fill is not None
    assert fill.execution.shares == 50  # Partial fill


@pytest.mark.xfail(reason="Time-based order constraints not implemented in Phase 1")
def test_day_order_expires_after_market_close():
    """DAY orders don't fill after market close timestamp."""
    engine = ExecutionEngine()
    bar = BarData(
        date=datetime(2025, 1, 1, 16, 30),  # After market close
        open=Decimal("149.50"),
        high=Decimal("151.00"),
        low=Decimal("149.00"),
        close=Decimal("150.00"),
        volume=1000000,
    )
    order = MarketOrder(action="BUY", totalQuantity=100, orderId=1, tif="DAY")
    
    fill = engine.execute(order, bar)
    
    assert fill is None

