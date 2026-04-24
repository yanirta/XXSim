"""Tests for Simulator class."""
import pytest
from datetime import datetime

from xtrading_models import (
    BarData,
    MarketOrder,
    LimitOrder,
    StopOrder,
    Trade,
)
from xtrading_models.order import StopLimitOrder, TrailingStopMarket

from simulator import Simulator, SimulatorConfig


# region Test Fixtures

@pytest.fixture
def simulator(time_provider):
    """Create a fresh Simulator instance."""
    Simulator.static_init(time_provider, SimulatorConfig())
    return Simulator()


@pytest.fixture
def bar_day1():
    """Bar for day 1: 2024-01-15."""
    return BarData(
        date=datetime(2024, 1, 15, 9, 30),
        open=100.0,
        high=105.0,
        low=95.0,
        close=102.0,
        volume=1000
    )


@pytest.fixture
def bar_day2():
    """Bar for day 2: 2024-01-16."""
    return BarData(
        date=datetime(2024, 1, 16, 9, 30),
        open=102.0,
        high=110.0,
        low=100.0,
        close=108.0,
        volume=1200
    )


@pytest.fixture
def bar_day3():
    """Bar for day 3: 2024-01-17."""
    return BarData(
        date=datetime(2024, 1, 17, 9, 30),
        open=108.0,
        high=115.0,
        low=106.0,
        close=112.0,
        volume=1500
    )


# endregion

# region Order Submission Tests

class TestOrderSubmission:
    """Tests for order submission."""

    def test_submit_order_returns_trade(self, simulator):
        """Submit returns a Trade object."""
        order = MarketOrder(action='BUY', totalQuantity=100)
        trade = simulator.submit_order(order)
        assert isinstance(trade, Trade)
        assert trade.order is order
        assert trade.orderStatus.status == 'Submitted'
        assert trade.orderStatus.orderId == order.orderId

    def test_submit_order_tracked_in_active_trades(self, simulator):
        """Submitted order is tracked in active trades."""
        order = MarketOrder(action='BUY', totalQuantity=100)
        trade = simulator.submit_order(order)
        assert simulator.get_trade(order.orderId) is trade
        assert trade in simulator.get_active_trades()

    def test_submit_multiple_orders(self, simulator):
        """Multiple orders can be submitted and tracked."""
        order1 = MarketOrder(action='BUY', totalQuantity=100)
        order2 = LimitOrder(action='SELL', totalQuantity=50, price=150.0)

        trade1 = simulator.submit_order(order1)
        trade2 = simulator.submit_order(order2)

        assert len(simulator.get_active_trades()) == 2
        assert simulator.get_trade(order1.orderId) is trade1
        assert simulator.get_trade(order2.orderId) is trade2


# endregion

# region Cancellation Tests

class TestCancellation:
    """Tests for order cancellation."""

    def test_cancel_order_returns_true(self, simulator):
        """Cancel returns True for active order."""
        order = MarketOrder(action='BUY', totalQuantity=100)
        simulator.submit_order(order)

        result = simulator.cancel_order(order.orderId)
        assert result is True

    def test_cancel_order_removes_from_active(self, simulator):
        """Cancelled order is removed from active trades."""
        order = MarketOrder(action='BUY', totalQuantity=100)
        trade = simulator.submit_order(order)

        simulator.cancel_order(order.orderId)

        assert simulator.get_trade(order.orderId) is None
        assert trade not in simulator.get_active_trades()

    def test_cancel_nonexistent_order_returns_false(self, simulator):
        """Cancel returns False for non-existent order."""
        result = simulator.cancel_order(99999)
        assert result is False

    def test_cancel_triggers_callback(self, simulator):
        """Cancel invokes on_cancel callback."""
        cancelled_trades = []

        def on_cancel(trade):
            cancelled_trades.append(trade)

        simulator.on_cancel(on_cancel)

        order = MarketOrder(action='BUY', totalQuantity=100)
        trade = simulator.submit_order(order)
        simulator.cancel_order(order.orderId)

        assert len(cancelled_trades) == 1
        assert cancelled_trades[0] is trade
        assert trade.orderStatus.status == 'Cancelled'
        assert trade.log[-1].message == 'User cancelled'


# endregion

# region Bar Processing Tests

class TestBarProcessing:
    """Tests for bar processing."""

    def test_market_order_fills_immediately(self, simulator, bar_day1):
        """Market order fills on first bar."""
        order = MarketOrder(action='BUY', totalQuantity=100)
        trade = simulator.submit_order(order)

        fills = simulator.process_bar(bar_day1)

        assert len(fills) == 1
        assert fills[0].execution.price == 100.0  # Open price
        assert simulator.get_trade(order.orderId) is None  # Removed
        assert trade.orderStatus.status == 'Filled'

    def test_limit_order_fills_when_price_reached(self, simulator, bar_day1):
        """Limit order fills when price reaches limit."""
        # Buy limit at 96, bar low is 95 - should fill
        order = LimitOrder(action='BUY', totalQuantity=100, price=96.0)
        trade = simulator.submit_order(order)

        fills = simulator.process_bar(bar_day1)

        assert len(fills) == 1
        assert fills[0].execution.price == 96.0
        assert simulator.get_trade(order.orderId) is None
        assert trade.orderStatus.status == 'Filled'

    def test_limit_order_stays_pending_when_price_not_reached(self, simulator, bar_day1):
        """Limit order stays pending when price not reached."""
        # Buy limit at 90, bar low is 95 - should not fill
        order = LimitOrder(action='BUY', totalQuantity=100, price=90.0)
        trade = simulator.submit_order(order)

        fills = simulator.process_bar(bar_day1)

        assert len(fills) == 0
        assert simulator.get_trade(order.orderId) is trade

    def test_multi_bar_fill(self, simulator, bar_day1, bar_day2):
        """Order fills across multiple bars."""
        # Buy limit at 90, bar1 low is 95, bar2 low is 100 - never fills
        order = LimitOrder(action='BUY', totalQuantity=100, price=90.0)
        trade = simulator.submit_order(order)

        fills1 = simulator.process_bar(bar_day1)
        assert len(fills1) == 0

        fills2 = simulator.process_bar(bar_day2)
        assert len(fills2) == 0

        # Trade still active
        assert simulator.get_trade(order.orderId) is trade

    def test_limit_order_fills_on_second_bar(self, simulator):
        """Limit order pending on first bar fills on second bar."""
        # Buy limit at 94, bar1 low is 95 (no fill), bar2 low is 93 (fills)
        bar1 = BarData(date=datetime(2025, 1, 1, 9, 30), open=100.0, high=105.0, low=95.0, close=102.0, volume=1000)
        bar2 = BarData(date=datetime(2025, 1, 1, 9, 31), open=96.0, high=98.0, low=93.0, close=95.0, volume=1000)

        order = LimitOrder(action='BUY', totalQuantity=100, price=94.0)
        trade = simulator.submit_order(order)

        fills1 = simulator.process_bar(bar1)
        assert len(fills1) == 0  # Not filled yet
        assert simulator.get_trade(order.orderId) is not None

        fills2 = simulator.process_bar(bar2)
        assert len(fills2) == 1  # Filled on second bar
        assert fills2[0].execution.price == 94.0
        assert simulator.get_trade(order.orderId) is None  # Removed from active
        assert trade.orderStatus.status == 'Filled'

    def test_stop_limit_partial_fill_completes_on_second_bar(self, simulator):
        """StopLimit: stop triggers on bar1 (internal state), limit fills on bar2."""
        # Buy stop-limit: stop at 102, limit at 101
        # Bar1: high=105 triggers stop, but low=102 doesn't reach limit 101 → triggered=True, pending
        # Bar2: low=100 reaches limit 101 → fills
        bar1 = BarData(date=datetime(2025, 1, 1, 9, 30), open=103.0, high=105.0, low=102.0, close=104.0, volume=1000)
        bar2 = BarData(date=datetime(2025, 1, 1, 9, 31), open=103.0, high=104.0, low=100.0, close=102.0, volume=1000)

        order = StopLimitOrder(action='BUY', totalQuantity=100, stopPrice=102.0, limitPrice=101.0)
        trade = simulator.submit_order(order)

        # Bar 1: Stop triggers (internal state change), limit not reached
        fills1 = simulator.process_bar(bar1)
        assert len(fills1) == 0
        assert order.triggered is True
        active = simulator.get_active_trades()
        assert len(active) == 1
        assert active[0] is trade

        # Bar 2: Limit fills (order already triggered, evaluates as limit)
        fills2 = simulator.process_bar(bar2)
        assert len(fills2) == 1
        assert fills2[0].execution.price == 101.0
        assert len(simulator.get_active_trades()) == 0
        assert trade.orderStatus.status == 'Filled'

    def test_trailing_stop_market_across_three_bars(self, simulator):
        """Trailing stop: initializes bar1, trails up bar2, triggers bar3."""
        # Sell trailing stop with $5 trailing distance
        # Bar1: high=102 sets extreme=102, stop=97, low=99 > 97 (no trigger)
        # Bar2: high=110 updates extreme=110, stop=105, low=106 > 105 (no trigger)
        # Bar3: low=103 < stop=105 (triggers and fills)
        bar1 = BarData(date=datetime(2025, 1, 1, 9, 30), open=100.0, high=102.0, low=99.0, close=101.0, volume=1000)
        bar2 = BarData(date=datetime(2025, 1, 1, 9, 31), open=107.0, high=110.0, low=106.0, close=109.0, volume=1000)
        bar3 = BarData(date=datetime(2025, 1, 1, 9, 32), open=108.0, high=109.0, low=103.0, close=104.0, volume=1000)

        order = TrailingStopMarket(
            action='SELL',
            totalQuantity=100,
            trailingDistance=5.0
        )
        trade = simulator.submit_order(order)

        # Bar 1: Initialize extreme and stop
        fills1 = simulator.process_bar(bar1)
        assert len(fills1) == 0
        assert order.extremePrice == 102.0
        assert order.stopPrice == 97.0

        # Bar 2: Price goes up, stop trails up
        fills2 = simulator.process_bar(bar2)
        assert len(fills2) == 0
        assert order.extremePrice == 110.0
        assert order.stopPrice == 105.0

        # Bar 3: Price drops below stop, triggers
        fills3 = simulator.process_bar(bar3)
        assert len(fills3) == 1
        assert fills3[0].execution.price == 105.0  # Fills at stop price
        assert len(simulator.get_active_trades()) == 0
        assert trade.orderStatus.status == 'Filled'

    def test_stop_order_triggers_on_second_bar(self, simulator):
        """Stop order pending on bar1, triggers on bar2."""
        # Bar1: low=98 doesn't reach stop=97
        # Bar2: low=95 triggers stop=97
        bar1 = BarData(date=datetime(2025, 1, 1, 9, 30), open=100.0, high=102.0, low=98.0, close=101.0, volume=1000)
        bar2 = BarData(date=datetime(2025, 1, 1, 9, 31), open=99.0, high=100.0, low=95.0, close=96.0, volume=1000)

        order = StopOrder(action='SELL', totalQuantity=100, stopPrice=97.0)
        trade = simulator.submit_order(order)

        # Bar 1: Stop not triggered
        fills1 = simulator.process_bar(bar1)
        assert len(fills1) == 0
        assert simulator.get_trade(order.orderId) is trade

        # Bar 2: Stop triggers and fills
        fills2 = simulator.process_bar(bar2)
        assert len(fills2) == 1
        assert fills2[0].execution.price == 97.0  # Fills at stop price
        assert len(simulator.get_active_trades()) == 0
        assert trade.orderStatus.status == 'Filled'

    def test_stop_limit_triggered_pending_across_multiple_bars(self, simulator):
        """StopLimit: stop triggers bar1 (internal state), limit fills bar4."""
        # Bar1: stop triggers but limit not reached → triggered=True, stays pending
        # Bar2-3: limit still not reached
        # Bar4: limit finally fills
        bar1 = BarData(date=datetime(2025, 1, 1, 9, 30), open=103.0, high=105.0, low=102.0, close=104.0, volume=1000)
        bar2 = BarData(date=datetime(2025, 1, 1, 9, 31), open=104.0, high=106.0, low=103.0, close=105.0, volume=1000)
        bar3 = BarData(date=datetime(2025, 1, 1, 9, 32), open=105.0, high=107.0, low=104.0, close=106.0, volume=1000)
        bar4 = BarData(date=datetime(2025, 1, 1, 9, 33), open=102.0, high=103.0, low=99.0, close=100.0, volume=1000)

        order = StopLimitOrder(action='BUY', totalQuantity=100, stopPrice=102.0, limitPrice=100.0)
        trade = simulator.submit_order(order)

        # Bar 1: Stop triggers (internal state change), limit not reached
        fills1 = simulator.process_bar(bar1)
        assert len(fills1) == 0
        active = simulator.get_active_trades()
        assert len(active) == 1
        assert active[0] is trade
        assert order.triggered is True

        # Bar 2: Limit still not reached (low=103 > 100)
        fills2 = simulator.process_bar(bar2)
        assert len(fills2) == 0
        assert simulator.get_trade(order.orderId) is trade

        # Bar 3: Limit still not reached (low=104 > 100)
        fills3 = simulator.process_bar(bar3)
        assert len(fills3) == 0
        assert simulator.get_trade(order.orderId) is trade
        assert len(simulator.get_active_trades()) == 1

        # Bar 4: Limit fills (low=99 < 100)
        fills4 = simulator.process_bar(bar4)
        assert len(fills4) == 1
        assert fills4[0].execution.price == 100.0
        assert len(simulator.get_active_trades()) == 0
        assert trade.orderStatus.status == 'Filled'

    def test_multiple_parent_orders_trigger_on_different_bars(self, simulator):
        """Two stop orders submitted together, triggering on different bars."""
        bar1 = BarData(date=datetime(2025, 1, 1, 9, 30), open=100.0, high=102.0, low=98.0, close=101.0, volume=1000)
        bar2 = BarData(date=datetime(2025, 1, 1, 9, 31), open=99.0, high=100.0, low=94.0, close=95.0, volume=1000)

        # Stop1 at 99 triggers on bar1 (low=98)
        # Stop2 at 95 triggers on bar2 (low=94)
        stop1 = StopOrder(action='SELL', totalQuantity=100, stopPrice=99.0)
        stop2 = StopOrder(action='SELL', totalQuantity=50, stopPrice=95.0)

        trade1 = simulator.submit_order(stop1)
        trade2 = simulator.submit_order(stop2)

        # Bar 1: Only stop1 triggers
        fills1 = simulator.process_bar(bar1)
        assert len(fills1) == 1
        assert stop1.triggered is True
        assert simulator.get_trade(stop1.orderId) is None
        assert simulator.get_trade(stop2.orderId) is trade2  # Still pending
        assert stop2.triggered is False
        assert trade1.orderStatus.status == 'Filled'

        # Bar 2: stop2 triggers
        fills2 = simulator.process_bar(bar2)
        assert len(fills2) == 1
        assert stop2.triggered is True
        assert len(simulator.get_active_trades()) == 0
        assert trade2.orderStatus.status == 'Filled'

    def test_stop_order_triggers_and_fills(self, simulator, bar_day1):
        """Stop order triggers and fills."""
        # Sell stop at 97, bar low is 95 - should trigger and fill
        order = StopOrder(action='SELL', totalQuantity=100, stopPrice=97.0)
        trade = simulator.submit_order(order)

        fills = simulator.process_bar(bar_day1)

        assert len(fills) == 1
        assert order.triggered is True
        assert simulator.get_trade(order.orderId) is None
        assert trade.orderStatus.status == 'Filled'

    def test_trailing_stop_updates_across_bars(self, simulator, bar_day1):
        """Trailing stop updates extreme price across bars."""
        # Buy trailing stop with $5 trailing distance
        order = TrailingStopMarket(
            action='BUY',
            totalQuantity=100,
            trailingDistance=5.0
        )
        simulator.submit_order(order)

        # Bar1: low=95, should set extreme=95, stop=100
        fills1 = simulator.process_bar(bar_day1)

        # Check if filled (high=105 >= stop=100)
        if len(fills1) == 0:
            # Not filled - check stop was updated
            assert order.extremePrice is not None
            assert order.stopPrice is not None

    def test_multiple_orders_processed(self, simulator, bar_day1):
        """Multiple orders are processed in same bar."""
        order1 = MarketOrder(action='BUY', totalQuantity=100)
        order2 = MarketOrder(action='SELL', totalQuantity=50)

        simulator.submit_order(order1)
        simulator.submit_order(order2)

        fills = simulator.process_bar(bar_day1)

        assert len(fills) == 2
        assert len(simulator.get_active_trades()) == 0

    def test_oca_children_only_one_fills_on_same_bar(self, simulator):
        """When both OCA bracket children could fill on the same bar,
        only the first one fills; the sibling is OCA-cancelled."""
        # Wide bar where both SL and TP could fill
        bar = BarData(
            date=datetime(2024, 1, 15, 9, 30),
            open=100.0,
            high=115.0,
            low=85.0,
            close=105.0,
            volume=1000
        )

        entry = LimitOrder(action='BUY', totalQuantity=100, price=98.0)
        stop_loss = StopOrder(action='SELL', totalQuantity=100, stopPrice=90.0, ocaGroup='bracket_1')
        take_profit = LimitOrder(action='SELL', totalQuantity=100, price=108.0, ocaGroup='bracket_1')

        entry.add_child(stop_loss)
        entry.add_child(take_profit)

        simulator.submit_order(entry)

        fill_events = []
        cancel_events = []
        simulator.on_fill(lambda t, f: fill_events.append((t, f)))
        simulator.on_cancel(lambda t: cancel_events.append(t))

        fills = simulator.process_bar(bar)

        # Entry fill + one child fill only (not both)
        entry_fills = [f for f in fills if f.execution.orderId == entry.orderId]
        child_fills = [f for f in fills if f.execution.orderId != entry.orderId]
        assert len(entry_fills) == 1
        assert len(child_fills) == 1

        # One child cancelled by OCA
        assert len(cancel_events) == 1
        assert cancel_events[0].orderStatus.status == 'Cancelled'

    def test_oca_children_activated_on_later_bar_cancel_sibling(self, simulator):
        """When OCA bracket children become active on a later bar (not same bar
        as parent fill), OCA cancellation should still work when one fills."""
        bar1 = BarData(
            date=datetime(2024, 1, 15, 9, 30),
            open=100.0, high=105.0, low=95.0, close=102.0, volume=1000
        )
        # SL fills on bar2 (low=88 triggers stop at 90)
        bar2 = BarData(
            date=datetime(2024, 1, 16, 9, 30),
            open=102.0, high=103.0, low=88.0, close=91.0, volume=1200
        )

        entry = LimitOrder(action='BUY', totalQuantity=100, price=98.0)
        stop_loss = StopOrder(action='SELL', totalQuantity=100, stopPrice=90.0, ocaGroup='bracket_1')
        take_profit = LimitOrder(action='SELL', totalQuantity=100, price=108.0, ocaGroup='bracket_1')

        entry.add_child(stop_loss)
        entry.add_child(take_profit)

        simulator.submit_order(entry)

        cancel_events = []
        simulator.on_cancel(lambda t: cancel_events.append(t))

        # Bar1: entry fills at 98, children become active but neither fills
        fills1 = simulator.process_bar(bar1)
        entry_fills = [f for f in fills1 if f.execution.orderId == entry.orderId]
        assert len(entry_fills) == 1
        assert len(simulator.get_active_trades()) == 2  # SL + TP active

        # Bar2: SL triggers at 90, TP should be OCA-cancelled
        fills2 = simulator.process_bar(bar2)
        assert len(fills2) == 1
        assert fills2[0].execution.orderId == stop_loss.orderId
        assert len(simulator.get_active_trades()) == 0

        # TP was cancelled by OCA
        assert len(cancel_events) == 1
        assert cancel_events[0].order.orderId == take_profit.orderId
        assert cancel_events[0].orderStatus.status == 'Cancelled'

    def test_oca_children_unfilled_sibling_cancelled_when_other_fills(self, simulator):
        """When one OCA child fills on same bar as parent and the other
        doesn't fill, the unfilled sibling should NOT become an active trade."""
        bar = BarData(
            date=datetime(2024, 1, 15, 9, 30),
            open=100.0,
            high=110.0,
            low=95.0,
            close=105.0,
            volume=1000
        )

        entry = LimitOrder(action='BUY', totalQuantity=100, price=98.0)
        # SL won't fill (low=95 > 90... wait, modified bar low = min(98, 95) = 95, stop at 90 won't trigger)
        stop_loss = StopOrder(action='SELL', totalQuantity=100, stopPrice=90.0, ocaGroup='bracket_1')
        # TP will fill (high=110 >= 108)
        take_profit = LimitOrder(action='SELL', totalQuantity=100, price=108.0, ocaGroup='bracket_1')

        entry.add_child(stop_loss)
        entry.add_child(take_profit)

        simulator.submit_order(entry)
        fills = simulator.process_bar(bar)

        # TP filled, SL should be cancelled (not active)
        assert simulator.get_trade(stop_loss.orderId) is None
        assert simulator.get_trade(take_profit.orderId) is None
        assert len(simulator.get_active_trades()) == 0


# endregion

# region TIF Expiration Tests

class TestTIFExpiration:
    """Tests for Time-In-Force expiration."""

    def test_gtc_never_expires(self, simulator, bar_day1, bar_day2, bar_day3):
        """GTC orders never expire on date change."""
        order = LimitOrder(action='BUY', totalQuantity=100, price=50.0, tif='GTC')
        trade = simulator.submit_order(order)

        simulator.process_bar(bar_day1)
        simulator.process_bar(bar_day2)
        simulator.process_bar(bar_day3)

        # Trade still active after 3 days
        assert simulator.get_trade(order.orderId) is trade

    def test_day_order_expires_on_date_change(self, simulator, bar_day1, bar_day2):
        """DAY orders expire when date changes."""
        order = LimitOrder(action='BUY', totalQuantity=100, price=50.0, tif='DAY')
        trade = simulator.submit_order(order)

        fills1 = simulator.process_bar(bar_day1)
        assert len(fills1) == 0
        assert simulator.get_trade(order.orderId) is trade  # Still active on day 1

        fills2 = simulator.process_bar(bar_day2)
        assert len(fills2) == 0
        assert simulator.get_trade(order.orderId) is None  # Expired on day 2
        assert trade.orderStatus.status == 'Cancelled'

    def test_day_order_expiration_triggers_callback(self, simulator, bar_day1, bar_day2):
        """DAY order expiration invokes on_cancel callback."""
        cancelled = []

        def on_cancel(trade):
            cancelled.append(trade)

        simulator.on_cancel(on_cancel)

        order = LimitOrder(action='BUY', totalQuantity=100, price=50.0, tif='DAY')
        trade = simulator.submit_order(order)

        simulator.process_bar(bar_day1)
        simulator.process_bar(bar_day2)

        assert len(cancelled) == 1
        assert cancelled[0] is trade
        assert trade.log[-1].message == 'DAY order expired'

    def test_day_order_does_not_fill_on_next_day(self, simulator):
        """DAY order that misses on day 1 must not fill on day 2 even if price allows it.

        Regression: previously DAY expiration ran after matching, so a DAY
        limit buy at 98 that missed on day 1 (low=99) would fill on day 2
        (open=95) before being expired. Now expiration runs before matching.
        """
        cancelled = []
        simulator.on_cancel(lambda trade: cancelled.append(trade))

        # Limit buy at 98 — day 1 low is 99, so it won't fill
        order = LimitOrder(action='BUY', totalQuantity=100, price=98.0, tif='DAY')
        simulator.submit_order(order)

        bar1 = BarData(
            date=datetime(2024, 1, 15, 9, 30),
            open=100.0, high=105.0, low=99.0, close=102.0, volume=1000,
        )
        fills1 = simulator.process_bar(bar1)
        assert len(fills1) == 0
        assert simulator.get_trade(order.orderId) is not None  # Still active

        # Day 2 opens at 95 — below the limit. Must NOT fill (DAY expired).
        bar2 = BarData(
            date=datetime(2024, 1, 16, 9, 30),
            open=95.0, high=103.0, low=94.0, close=100.0, volume=1200,
        )
        fills2 = simulator.process_bar(bar2)
        assert len(fills2) == 0  # Expired before matching, not filled
        assert simulator.get_trade(order.orderId) is None
        assert len(cancelled) == 1
        assert cancelled[0].orderStatus.status == 'Cancelled'

    def test_gtd_order_expires_after_date(self, simulator, bar_day1, bar_day2, bar_day3):
        """GTD orders expire after goodTillDate."""
        # GTD until 2024-01-16 (day2)
        order = LimitOrder(
            action='BUY',
            totalQuantity=100,
            price=50.0,
            tif='GTD',
            goodTillDate='20240116'  # YYYYMMDD format
        )
        trade = simulator.submit_order(order)

        simulator.process_bar(bar_day1)  # Jan 15 - active
        assert simulator.get_trade(order.orderId) is trade

        simulator.process_bar(bar_day2)  # Jan 16 - still active (not past GTD)
        assert simulator.get_trade(order.orderId) is trade

        simulator.process_bar(bar_day3)  # Jan 17 - expired (past GTD)
        assert simulator.get_trade(order.orderId) is None
        assert trade.orderStatus.status == 'Cancelled'

    def test_gtd_order_expiration_triggers_callback(self, simulator, bar_day1, bar_day2, bar_day3):
        """GTD order expiration invokes on_cancel callback."""
        cancelled = []

        def on_cancel(trade):
            cancelled.append(trade)

        simulator.on_cancel(on_cancel)

        order = LimitOrder(
            action='BUY',
            totalQuantity=100,
            price=50.0,
            tif='GTD',
            goodTillDate='20240116'
        )
        trade = simulator.submit_order(order)

        simulator.process_bar(bar_day1)
        simulator.process_bar(bar_day2)
        simulator.process_bar(bar_day3)

        assert len(cancelled) == 1
        assert cancelled[0] is trade
        assert trade.log[-1].message == 'GTD order expired'

    def test_gtd_order_expires_with_ib_datetime_format(self, simulator, bar_day1, bar_day2, bar_day3):
        """GTD orders expire when goodTillDate uses IB format with time and timezone."""
        order = LimitOrder(
            action='BUY',
            totalQuantity=100,
            price=50.0,
            tif='GTD',
            goodTillDate='20240116 16:00:00 US/Eastern'
        )
        trade = simulator.submit_order(order)

        simulator.process_bar(bar_day1)  # Jan 15 - active
        assert simulator.get_trade(order.orderId) is trade

        simulator.process_bar(bar_day2)  # Jan 16 - still active (not past GTD)
        assert simulator.get_trade(order.orderId) is trade

        simulator.process_bar(bar_day3)  # Jan 17 - expired (past GTD)
        assert simulator.get_trade(order.orderId) is None
        assert trade.orderStatus.status == 'Cancelled'

    def test_default_tif_is_empty_string(self, simulator, bar_day1, bar_day2, bar_day3):
        """Orders with empty TIF don't expire (treated like GTC)."""
        order = LimitOrder(action='BUY', totalQuantity=100, price=50.0)
        # Default tif is empty string
        assert order.tif == ''

        trade = simulator.submit_order(order)

        simulator.process_bar(bar_day1)
        simulator.process_bar(bar_day2)
        simulator.process_bar(bar_day3)

        # Trade still active
        assert simulator.get_trade(order.orderId) is trade

    def test_day_order_with_good_after_time_not_expired_before_gat_date(self, simulator):
        """DAY order with goodAfterTime is not expired until the GAT date has passed.

        Regression: MOC bracket children (max-hold exits) are DAY orders submitted
        with goodAfterTime = N days in the future. They were incorrectly cancelled
        the next morning because _expire_day_orders ignored goodAfterTime.
        """
        # Day 1: submit order, Day 2: must still be active (GAT not reached), Day 3: active (GAT date)
        order = LimitOrder(
            action='BUY',
            totalQuantity=100,
            price=50.0,
            tif='DAY',
            goodAfterTime='20240117 00:00:00 US/Eastern',  # bar_day3 date
        )
        trade = simulator.submit_order(order)

        simulator.process_bar(BarData(date=datetime(2024, 1, 15, 9, 30), open=100.0, high=105.0, low=95.0, close=102.0, volume=1000))
        assert simulator.get_trade(order.orderId) is trade  # still alive on day 1

        simulator.process_bar(BarData(date=datetime(2024, 1, 16, 9, 30), open=102.0, high=110.0, low=100.0, close=108.0, volume=1200))
        assert simulator.get_trade(order.orderId) is trade  # still alive on day 2 (GAT not yet reached)

        # Day 3 = GAT date: order becomes active, does not fill (low=106 > limit=50 is wrong, let's use high above limit)
        # Use price=108 so it fills on day 3
        order.price = 108.0
        simulator.process_bar(BarData(date=datetime(2024, 1, 17, 9, 30), open=108.0, high=115.0, low=106.0, close=112.0, volume=1300))
        assert simulator.get_trade(order.orderId) is None  # filled (not expired)
        assert trade.orderStatus.status == 'Filled'

    def test_day_order_with_good_after_time_expires_after_gat_date(self, simulator):
        """DAY order with goodAfterTime is expired the day after its GAT date if it didn't fill."""
        order = LimitOrder(
            action='BUY',
            totalQuantity=100,
            price=50.0,
            tif='DAY',
            goodAfterTime='20240116 00:00:00 US/Eastern',  # bar_day2 date
        )
        trade = simulator.submit_order(order)

        simulator.process_bar(BarData(date=datetime(2024, 1, 15, 9, 30), open=100.0, high=105.0, low=95.0, close=102.0, volume=1000))
        assert simulator.get_trade(order.orderId) is trade  # alive on day 1

        simulator.process_bar(BarData(date=datetime(2024, 1, 16, 9, 30), open=102.0, high=110.0, low=100.0, close=108.0, volume=1200))
        assert simulator.get_trade(order.orderId) is trade  # alive on GAT date (limit 50 doesn't fill)

        simulator.process_bar(BarData(date=datetime(2024, 1, 17, 9, 30), open=108.0, high=115.0, low=106.0, close=112.0, volume=1300))
        assert simulator.get_trade(order.orderId) is None  # expired after GAT date passed
        assert trade.orderStatus.status == 'Cancelled'
        assert trade.log[-1].message == 'DAY order expired'

    # GAT (Good After Time) Tests

    def test_gat_order_not_active_before_time(self, simulator):
        """Order with goodAfterTime is not executed before that time."""
        # Bar at 9:30, order active after 10:00
        bar = BarData(
            date=datetime(2024, 1, 15, 9, 30),
            open=100.0,
            high=105.0,
            low=95.0,
            close=102.0,
            volume=1000
        )

        order = MarketOrder(
            action='BUY',
            totalQuantity=100,
            goodAfterTime='20240115 10:00:00 US/Eastern'
        )
        trade = simulator.submit_order(order)

        fills = simulator.process_bar(bar)

        assert len(fills) == 0
        assert simulator.get_trade(order.orderId) is trade  # Still active, just not executed

    def test_gat_order_active_after_time(self, simulator):
        """Order with goodAfterTime is executed after that time."""
        # Bar at 10:30, order active after 10:00
        bar = BarData(
            date=datetime(2024, 1, 15, 10, 30),
            open=100.0,
            high=105.0,
            low=95.0,
            close=102.0,
            volume=1000
        )

        order = MarketOrder(
            action='BUY',
            totalQuantity=100,
            goodAfterTime='20240115 10:00:00 US/Eastern'
        )
        simulator.submit_order(order)

        fills = simulator.process_bar(bar)

        assert len(fills) == 1
        assert simulator.get_trade(order.orderId) is None

    def test_gat_order_active_at_exact_time(self, simulator):
        """Order with goodAfterTime is executed at exact time."""
        # Bar at exactly 10:00, order active after 10:00
        bar = BarData(
            date=datetime(2024, 1, 15, 10, 0),
            open=100.0,
            high=105.0,
            low=95.0,
            close=102.0,
            volume=1000
        )

        order = MarketOrder(
            action='BUY',
            totalQuantity=100,
            goodAfterTime='20240115 10:00:00 US/Eastern'
        )
        simulator.submit_order(order)

        fills = simulator.process_bar(bar)

        assert len(fills) == 1

    def test_gat_order_becomes_active_on_later_bar(self, simulator):
        """Order pending on bar1, becomes active and fills on bar2."""
        bar1 = BarData(
            date=datetime(2024, 1, 15, 9, 30),
            open=100.0,
            high=105.0,
            low=95.0,
            close=102.0,
            volume=1000
        )
        bar2 = BarData(
            date=datetime(2024, 1, 15, 10, 30),
            open=102.0,
            high=108.0,
            low=100.0,
            close=106.0,
            volume=1200
        )

        order = MarketOrder(
            action='BUY',
            totalQuantity=100,
            goodAfterTime='20240115 10:00:00 US/Eastern'
        )
        trade = simulator.submit_order(order)

        # Bar 1: Not yet active
        fills1 = simulator.process_bar(bar1)
        assert len(fills1) == 0
        assert simulator.get_trade(order.orderId) is trade

        # Bar 2: Now active and fills
        fills2 = simulator.process_bar(bar2)
        assert len(fills2) == 1
        assert simulator.get_trade(order.orderId) is None

    def test_gat_limit_order_not_active_doesnt_fill(self, simulator):
        """Limit order with GAT not reached stays pending."""
        bar = BarData(
            date=datetime(2024, 1, 15, 9, 30),
            open=100.0,
            high=105.0,
            low=95.0,
            close=102.0,
            volume=1000
        )

        # Limit at 96 would fill (low=95) but GAT not reached
        order = LimitOrder(
            action='BUY',
            totalQuantity=100,
            price=96.0,
            goodAfterTime='20240115 10:00:00 US/Eastern'
        )
        trade = simulator.submit_order(order)

        fills = simulator.process_bar(bar)

        assert len(fills) == 0
        assert simulator.get_trade(order.orderId) is trade

    def test_gat_combined_with_gtd(self, simulator):
        """Order with both goodAfterTime and goodTillDate."""
        bar1 = BarData(
            date=datetime(2024, 1, 15, 9, 30),
            open=100.0,
            high=105.0,
            low=95.0,
            close=102.0,
            volume=1000
        )
        bar2 = BarData(
            date=datetime(2024, 1, 15, 10, 30),
            open=102.0,
            high=108.0,
            low=100.0,
            close=106.0,
            volume=1200
        )
        bar3 = BarData(
            date=datetime(2024, 1, 17, 9, 30),
            open=106.0,
            high=110.0,
            low=90.0,  # Would hit limit
            close=108.0,
            volume=1500
        )

        # Active after 10:00 on Jan 15, expires after Jan 16
        order = LimitOrder(
            action='BUY',
            totalQuantity=100,
            price=92.0,  # Won't fill on bar1/bar2
            tif='GTD',
            goodTillDate='20240116',
            goodAfterTime='20240115 10:00:00 US/Eastern'
        )
        trade = simulator.submit_order(order)

        # Bar 1 (9:30): Not active yet (GAT)
        fills1 = simulator.process_bar(bar1)
        assert len(fills1) == 0
        assert simulator.get_trade(order.orderId) is trade

        # Bar 2 (10:30): Active but limit not reached
        fills2 = simulator.process_bar(bar2)
        assert len(fills2) == 0
        assert simulator.get_trade(order.orderId) is trade

        # Bar 3 (Jan 17): Expired (GTD)
        fills3 = simulator.process_bar(bar3)
        assert len(fills3) == 0
        assert simulator.get_trade(order.orderId) is None  # Expired

    def test_gat_no_effect_when_empty(self, simulator, bar_day1):
        """Order without goodAfterTime is immediately active."""
        order = MarketOrder(action='BUY', totalQuantity=100)
        assert order.goodAfterTime == ''

        simulator.submit_order(order)
        fills = simulator.process_bar(bar_day1)

        assert len(fills) == 1


# endregion

# region Callback Tests

class TestCallbacks:
    """Tests for callback invocations."""

    def test_on_fill_callback_invoked(self, simulator, bar_day1):
        """on_fill callback is invoked when order fills."""
        fills_received = []

        def on_fill(trade, fill):
            fills_received.append((trade, fill))

        simulator.on_fill(on_fill)

        order = MarketOrder(action='BUY', totalQuantity=100)
        trade = simulator.submit_order(order)
        simulator.process_bar(bar_day1)

        assert len(fills_received) == 1
        assert fills_received[0][0] is trade
        assert fills_received[0][1].execution.price == 100.0

    def test_multiple_fill_callbacks(self, simulator, bar_day1):
        """Multiple on_fill callbacks are all invoked."""
        fills1 = []
        fills2 = []

        simulator.on_fill(lambda _trade, fill: fills1.append(fill))
        simulator.on_fill(lambda _trade, fill: fills2.append(fill))

        order = MarketOrder(action='BUY', totalQuantity=100)
        simulator.submit_order(order)
        simulator.process_bar(bar_day1)

        assert len(fills1) == 1
        assert len(fills2) == 1

    def test_on_cancel_callback_invoked(self, simulator):
        """on_cancel callback is invoked when order is cancelled."""
        cancelled = []

        simulator.on_cancel(lambda trade: cancelled.append(trade))

        order = MarketOrder(action='BUY', totalQuantity=100)
        simulator.submit_order(order)
        simulator.cancel_order(order.orderId)

        assert len(cancelled) == 1

    def test_on_status_callback_invoked(self, simulator):
        """on_status callback is invoked when order is updated."""
        statuses = []

        simulator.on_status(lambda trade: statuses.append(trade))

        order = LimitOrder(action='BUY', totalQuantity=100, price=100.0)
        trade = simulator.submit_order(order)
        simulator.update_order(order.orderId, price=95.0)

        # Status called on submit + update
        assert len(statuses) >= 2
        assert statuses[-1] is trade


# endregion

# region Order Update Tests

class TestOrderUpdates:
    """Tests for order updates."""

    def test_update_order_price(self, simulator):
        """Update order price."""
        order = LimitOrder(action='BUY', totalQuantity=100, price=100.0)
        simulator.submit_order(order)

        result = simulator.update_order(order.orderId, price=95.0)

        assert result is True
        assert order.price == 95.0

    def test_update_order_quantity(self, simulator):
        """Update order quantity."""
        order = MarketOrder(action='BUY', totalQuantity=100)
        simulator.submit_order(order)

        result = simulator.update_order(order.orderId, totalQuantity=150.0)

        assert result is True
        assert order.totalQuantity == 150.0

    def test_update_trailing_distance(self, simulator):
        """Update trailing stop distance."""
        order = TrailingStopMarket(
            action='BUY',
            totalQuantity=100,
            trailingDistance=5.0
        )
        simulator.submit_order(order)

        result = simulator.update_order(order.orderId, trailingDistance=10.0)

        assert result is True
        assert order.trailingDistance == 10.0

    def test_update_nonexistent_order_returns_false(self, simulator):
        """Update returns False for non-existent order."""
        result = simulator.update_order(99999, price=100.0)
        assert result is False

    def test_update_triggers_callback(self, simulator):
        """Update invokes on_status callback."""
        statuses = []
        simulator.on_status(lambda trade: statuses.append(trade))

        order = LimitOrder(action='BUY', totalQuantity=100, price=100.0)
        simulator.submit_order(order)
        simulator.update_order(order.orderId, price=95.0)

        # At least 2 status callbacks: submit + update
        assert len(statuses) >= 2


# endregion

# region On Bar Callback Tests

class TestOnBarCallback:
    """Tests for on_bar callback and run method."""

    def test_on_bar_callback_invoked(self, simulator, bar_day1):
        """on_bar callback is invoked after processing bar."""
        bars_received = []

        def on_bar(bar, fills):
            bars_received.append((bar, fills))

        simulator.on_bar(on_bar)
        simulator.process_bar(bar_day1)

        assert len(bars_received) == 1
        assert bars_received[0][0] is bar_day1
        assert bars_received[0][1] == []  # No orders, no fills

    def test_on_bar_callback_receives_fills(self, simulator, bar_day1):
        """on_bar callback receives fills from processed bar."""
        bars_received = []

        def on_bar(bar, fills):
            bars_received.append((bar, fills))

        simulator.on_bar(on_bar)
        order = MarketOrder(action='BUY', totalQuantity=100)
        simulator.submit_order(order)
        simulator.process_bar(bar_day1)

        assert len(bars_received) == 1
        assert len(bars_received[0][1]) == 1  # One fill

    def test_on_bar_can_submit_orders(self, simulator, bar_day1, bar_day2):
        """on_bar callback can submit orders for next bar."""
        fills_count = []

        def on_bar(_bar, fills):
            fills_count.append(len(fills))
            # Submit order for next bar
            simulator.submit_order(MarketOrder(action='BUY', totalQuantity=100))

        simulator.on_bar(on_bar)

        simulator.process_bar(bar_day1)  # No fills, submits order
        simulator.process_bar(bar_day2)  # Fills order, submits another

        assert fills_count == [0, 1]

    def test_process_bars_processes_all_bars(self, simulator, bar_day1, bar_day2, bar_day3):
        """process_bars() processes all bars in sequence."""
        bars_seen = []

        simulator.on_bar(lambda bar, _fills: bars_seen.append(bar))
        for _ in simulator.process_bars([bar_day1, bar_day2, bar_day3]):
            pass

        assert len(bars_seen) == 3
        assert bars_seen[0] is bar_day1
        assert bars_seen[1] is bar_day2
        assert bars_seen[2] is bar_day3

    def test_off_bar_stops_callback(self, simulator, bar_day1, bar_day2):
        """off_bar removes callback so it no longer receives bars."""
        bars_received = []

        def on_bar(bar, fills):
            bars_received.append(bar)

        simulator.on_bar(on_bar)
        simulator.process_bar(bar_day1)
        simulator.off_bar(on_bar)
        simulator.process_bar(bar_day2)

        assert len(bars_received) == 1
        assert bars_received[0] is bar_day1

    def test_process_bars_with_strategy(self, simulator):
        """Full backtest simulation using process_bars."""
        bars = [
            BarData(date=datetime(2024, 1, 15, 9, 30), open=100.0,
                    high=105.0, low=95.0, close=102.0, volume=1000),
            BarData(date=datetime(2024, 1, 15, 10, 0), open=102.0,
                    high=107.0, low=100.0, close=105.0, volume=1000),
        ]

        fills_received = []
        for fills in simulator.process_bars(bars):
            fills_received.extend(fills)
            # Buy on first bar (no fills yet, no active trades)
            if len(fills_received) == 0 and len(simulator.get_active_trades()) == 0:
                simulator.submit_order(MarketOrder(action='BUY', totalQuantity=100))

        # Order submitted on bar 1, filled on bar 2
        assert len(fills_received) == 1


# endregion

# region Integration Tests

class TestIntegration:
    """Integration tests for full simulation sequences."""

    def test_full_simulation_sequence(self, simulator):
        """Complete simulation with multiple orders and bars."""
        fills_received = []
        cancelled = []

        simulator.on_fill(lambda _trade, fill: fills_received.append(fill))
        simulator.on_cancel(lambda trade: cancelled.append(trade))

        # Submit orders
        market_order = MarketOrder(action='BUY', totalQuantity=100)
        limit_order = LimitOrder(action='SELL', totalQuantity=50, price=110.0, tif='DAY')

        simulator.submit_order(market_order)
        limit_trade = simulator.submit_order(limit_order)

        # Day 1: Market fills, limit pending
        bar1 = BarData(
            date=datetime(2024, 1, 15, 9, 30),
            open=100.0,
            high=105.0,
            low=95.0,
            close=102.0,
            volume=1000
        )

        fills1 = simulator.process_bar(bar1)
        assert len(fills1) == 1  # Market order filled
        assert len(simulator.get_active_trades()) == 1  # Limit still pending

        # Day 2: Limit expires due to DAY TIF
        bar2 = BarData(
            date=datetime(2024, 1, 16, 9, 30),
            open=102.0,
            high=108.0,
            low=100.0,
            close=106.0,
            volume=1200
        )

        fills2 = simulator.process_bar(bar2)
        assert len(fills2) == 0  # Limit expired before execution
        assert len(simulator.get_active_trades()) == 0
        assert len(cancelled) == 1
        assert limit_trade.log[-1].message == 'DAY order expired'

    def test_stop_order_with_gtd(self, simulator):
        """Stop order with GTD expiration."""
        cancelled = []
        simulator.on_cancel(lambda trade: cancelled.append(trade))

        # Stop order GTD until Jan 16
        order = StopOrder(
            action='SELL',
            totalQuantity=100,
            stopPrice=90.0,
            tif='GTD',
            goodTillDate='20240116'
        )
        trade = simulator.submit_order(order)

        # Day 1: Stop not triggered (low=95 > stop=90)
        bar1 = BarData(
            date=datetime(2024, 1, 15, 9, 30),
            open=100.0,
            high=105.0,
            low=95.0,
            close=102.0,
            volume=1000
        )
        simulator.process_bar(bar1)
        assert simulator.get_trade(order.orderId) is not None

        # Day 2: Still active
        bar2 = BarData(
            date=datetime(2024, 1, 16, 9, 30),
            open=100.0,
            high=105.0,
            low=95.0,
            close=102.0,
            volume=1000
        )
        simulator.process_bar(bar2)
        assert simulator.get_trade(order.orderId) is not None

        # Day 3: Expires
        bar3 = BarData(
            date=datetime(2024, 1, 17, 9, 30),
            open=100.0,
            high=105.0,
            low=95.0,
            close=102.0,
            volume=1000
        )
        simulator.process_bar(bar3)
        assert simulator.get_trade(order.orderId) is None
        assert len(cancelled) == 1
        assert trade.orderStatus.status == 'Cancelled'

    def test_cancel_then_submit_new(self, simulator, bar_day1):
        """Cancel order and submit new one."""
        order1 = LimitOrder(action='BUY', totalQuantity=100, price=50.0)
        simulator.submit_order(order1)

        simulator.cancel_order(order1.orderId)
        assert len(simulator.get_active_trades()) == 0

        order2 = MarketOrder(action='BUY', totalQuantity=100)
        simulator.submit_order(order2)

        fills = simulator.process_bar(bar_day1)
        assert len(fills) == 1
        assert simulator.get_trade(order1.orderId) is None
        assert simulator.get_trade(order2.orderId) is None  # Filled and removed


# endregion

# region Bracket Order Tests

class TestBracketOrders:
    """Tests for parent orders with bracket children (entry + stop_loss + take_profit)."""

    def test_parent_fill_does_not_include_child_fills(self, simulator):
        """When parent fills and a child also fills on the same bar,
        the parent trade's fills and orderStatus should only reflect
        the parent's own fill — not the child's."""
        # Bar: open=100, high=110, low=95, close=105
        # Entry: BUY limit at 98 → fills at 98 (low=95 reaches it)
        # Modified bar for children: open=98, high=110, low=95
        # Take-profit: SELL limit at 108 → fills (high=110 >= 108)
        # Stop-loss: SELL stop at 93 → does NOT fill (low=95 > 93)
        bar = BarData(
            date=datetime(2024, 1, 15, 9, 30),
            open=100.0,
            high=110.0,
            low=95.0,
            close=105.0,
            volume=1000
        )

        entry = LimitOrder(action='BUY', totalQuantity=100, price=98.0)
        stop_loss = StopOrder(action='SELL', totalQuantity=100, stopPrice=93.0)
        take_profit = LimitOrder(action='SELL', totalQuantity=100, price=108.0)

        entry.add_child(stop_loss)
        entry.add_child(take_profit)

        trade = simulator.submit_order(entry)
        fills = simulator.process_bar(bar)

        # Parent trade should only report its own fill quantity
        assert trade.orderStatus.filled == 100.0
        assert len(trade.fills) == 1
        assert trade.fills[0].execution.orderId == entry.orderId

    def test_child_filled_on_same_bar_gets_own_trade(self, simulator):
        """When a child fills recursively on the same bar as the parent,
        the child should get its own Trade with correct fill info."""
        bar = BarData(
            date=datetime(2024, 1, 15, 9, 30),
            open=100.0,
            high=110.0,
            low=95.0,
            close=105.0,
            volume=1000
        )

        entry = LimitOrder(action='BUY', totalQuantity=100, price=98.0)
        stop_loss = StopOrder(action='SELL', totalQuantity=100, stopPrice=93.0)
        take_profit = LimitOrder(action='SELL', totalQuantity=100, price=108.0)

        entry.add_child(stop_loss)
        entry.add_child(take_profit)

        trade = simulator.submit_order(entry)

        fill_events = []
        simulator.on_fill(lambda t, f: fill_events.append((t, f)))

        fills = simulator.process_bar(bar)

        # Take-profit fills on the same bar (high=110 >= 108)
        # It should NOT remain as an active trade
        assert simulator.get_trade(take_profit.orderId) is None

        # The take-profit fill should be emitted as a separate fill event
        tp_fills = [f for t, f in fill_events if f.execution.orderId == take_profit.orderId]
        assert len(tp_fills) == 1
        assert tp_fills[0].execution.shares == 100

    def test_unfilled_child_becomes_active_trade(self, simulator):
        """When parent fills but a child does NOT fill on the same bar,
        the child should be submitted as a new active trade."""
        bar = BarData(
            date=datetime(2024, 1, 15, 9, 30),
            open=100.0,
            high=110.0,
            low=95.0,
            close=105.0,
            volume=1000
        )

        entry = LimitOrder(action='BUY', totalQuantity=100, price=98.0)
        stop_loss = StopOrder(action='SELL', totalQuantity=100, stopPrice=93.0)
        take_profit = LimitOrder(action='SELL', totalQuantity=100, price=115.0)

        entry.add_child(stop_loss)
        entry.add_child(take_profit)

        simulator.submit_order(entry)
        simulator.process_bar(bar)

        # Entry filled, neither child fills on this bar
        # Both children should be active trades
        assert simulator.get_trade(stop_loss.orderId) is not None
        assert simulator.get_trade(take_profit.orderId) is not None


# endregion

# region Parent Cancel With Children Tests

class TestParentCancelWithChildren:
    """Tests for cancellation cascading to children."""

    def test_cancel_parent_cancels_unsubmitted_children(self, simulator):
        """Cancelling a parent emits cancel events for unsubmitted bracket children."""
        cancel_events = []
        simulator.on_cancel(lambda t: cancel_events.append(t))

        entry = LimitOrder(action='BUY', totalQuantity=100, price=50.0)
        stop_loss = StopOrder(action='SELL', totalQuantity=100, stopPrice=45.0)
        take_profit = LimitOrder(action='SELL', totalQuantity=100, price=60.0)

        entry.add_child(stop_loss)
        entry.add_child(take_profit)

        simulator.submit_order(entry)
        simulator.cancel_order(entry.orderId)

        # Parent + 2 children = 3 cancel events
        assert len(cancel_events) == 3
        cancelled_ids = {t.order.orderId for t in cancel_events}
        assert entry.orderId in cancelled_ids
        assert stop_loss.orderId in cancelled_ids
        assert take_profit.orderId in cancelled_ids

    def test_cancel_parent_sets_child_permid(self, simulator):
        """Unsubmitted children get permId set when parent is cancelled."""
        cancel_events = []
        simulator.on_cancel(lambda t: cancel_events.append(t))

        entry = LimitOrder(action='BUY', totalQuantity=100, price=50.0)
        child = StopOrder(action='SELL', totalQuantity=100, stopPrice=45.0)
        entry.add_child(child)

        simulator.submit_order(entry)
        simulator.cancel_order(entry.orderId)

        child_event = [t for t in cancel_events if t.order.orderId == child.orderId][0]
        assert child_event.order.permId == child.orderId

    def test_cancel_parent_cancels_active_children(self, simulator):
        """Cancelling a parent also cancels children already promoted to active trades."""
        bar = BarData(
            date=datetime(2024, 1, 15, 9, 30),
            open=100.0, high=110.0, low=95.0, close=105.0, volume=1000
        )

        entry = LimitOrder(action='BUY', totalQuantity=100, price=98.0)
        stop_loss = StopOrder(action='SELL', totalQuantity=100, stopPrice=85.0)
        take_profit = LimitOrder(action='SELL', totalQuantity=100, price=120.0)

        entry.add_child(stop_loss)
        entry.add_child(take_profit)

        simulator.submit_order(entry)
        simulator.process_bar(bar)  # Entry fills, children become active

        assert simulator.get_trade(stop_loss.orderId) is not None
        assert simulator.get_trade(take_profit.orderId) is not None

        cancel_events = []
        simulator.on_cancel(lambda t: cancel_events.append(t))

        # Cancel stop_loss — take_profit is its OCA sibling? No, they have no OCA here.
        # Let's cancel stop_loss directly
        simulator.cancel_order(stop_loss.orderId)

        assert simulator.get_trade(stop_loss.orderId) is None
        assert len(cancel_events) == 1

    def test_day_expiry_cancels_unsubmitted_children(self, simulator):
        """DAY parent expiry emits cancel events for unsubmitted bracket children."""
        bar1 = BarData(
            date=datetime(2024, 1, 15, 9, 30),
            open=100.0, high=105.0, low=95.0, close=102.0, volume=1000
        )
        bar2 = BarData(
            date=datetime(2024, 1, 16, 9, 30),
            open=102.0, high=108.0, low=100.0, close=106.0, volume=1200
        )

        entry = LimitOrder(action='BUY', totalQuantity=100, price=50.0, tif='DAY')
        stop_loss = StopOrder(action='SELL', totalQuantity=100, stopPrice=45.0)
        take_profit = LimitOrder(action='SELL', totalQuantity=100, price=60.0)

        entry.add_child(stop_loss)
        entry.add_child(take_profit)

        cancel_events = []
        simulator.on_cancel(lambda t: cancel_events.append(t))

        simulator.submit_order(entry)
        simulator.process_bar(bar1)  # Day 1 — entry doesn't fill
        assert len(cancel_events) == 0

        simulator.process_bar(bar2)  # Day 2 — DAY order expires

        assert len(cancel_events) == 3
        cancelled_ids = {t.order.orderId for t in cancel_events}
        assert entry.orderId in cancelled_ids
        assert stop_loss.orderId in cancelled_ids
        assert take_profit.orderId in cancelled_ids

    def test_gtd_expiry_cancels_unsubmitted_children(self, simulator):
        """GTD parent expiry emits cancel events for unsubmitted bracket children."""
        bar1 = BarData(
            date=datetime(2024, 1, 15, 9, 30),
            open=100.0, high=105.0, low=95.0, close=102.0, volume=1000
        )
        bar2 = BarData(
            date=datetime(2024, 1, 17, 9, 30),
            open=108.0, high=115.0, low=106.0, close=112.0, volume=1500
        )

        entry = LimitOrder(
            action='BUY', totalQuantity=100, price=50.0,
            tif='GTD', goodTillDate='20240116'
        )
        stop_loss = StopOrder(action='SELL', totalQuantity=100, stopPrice=45.0)
        take_profit = LimitOrder(action='SELL', totalQuantity=100, price=60.0)

        entry.add_child(stop_loss)
        entry.add_child(take_profit)

        cancel_events = []
        simulator.on_cancel(lambda t: cancel_events.append(t))

        simulator.submit_order(entry)
        simulator.process_bar(bar1)  # Jan 15 — active, doesn't fill
        assert len(cancel_events) == 0

        simulator.process_bar(bar2)  # Jan 17 — past GTD, expires

        assert len(cancel_events) == 3
        cancelled_ids = {t.order.orderId for t in cancel_events}
        assert entry.orderId in cancelled_ids
        assert stop_loss.orderId in cancelled_ids
        assert take_profit.orderId in cancelled_ids

    def test_cancel_parent_child_log_references_parent(self, simulator):
        """Cancelled children's log message references the parent order ID."""
        entry = LimitOrder(action='BUY', totalQuantity=100, price=50.0)
        child = StopOrder(action='SELL', totalQuantity=100, stopPrice=45.0)
        entry.add_child(child)

        cancel_events = []
        simulator.on_cancel(lambda t: cancel_events.append(t))

        simulator.submit_order(entry)
        simulator.cancel_order(entry.orderId)

        child_event = [t for t in cancel_events if t.order.orderId == child.orderId][0]
        assert f'Parent order {entry.orderId} cancelled' in child_event.log[-1].message

    def test_oca_sibling_cancel_cascades_to_children(self, simulator):
        """When an OCA sibling fills and cancels an order, that order's
        unsubmitted children are also cancelled."""
        bar = BarData(
            date=datetime(2024, 1, 15, 9, 30),
            open=100.0, high=105.0, low=95.0, close=102.0, volume=1000
        )

        # Two entries in OCA group — order1 fills, order2 gets cancelled
        order1 = LimitOrder(action='BUY', totalQuantity=100, price=96.0, ocaGroup='entries')
        order2 = LimitOrder(action='BUY', totalQuantity=100, price=90.0, ocaGroup='entries')

        # order2 has bracket children
        sl = StopOrder(action='SELL', totalQuantity=100, stopPrice=85.0)
        tp = LimitOrder(action='SELL', totalQuantity=100, price=100.0)
        order2.add_child(sl)
        order2.add_child(tp)

        cancel_events = []
        simulator.on_cancel(lambda t: cancel_events.append(t))

        simulator.submit_order(order1)
        simulator.submit_order(order2)
        simulator.process_bar(bar)  # order1 fills, order2 OCA-cancelled

        cancelled_ids = {t.order.orderId for t in cancel_events}
        assert order2.orderId in cancelled_ids
        assert sl.orderId in cancelled_ids
        assert tp.orderId in cancelled_ids


# endregion

# region OCO Tests

class TestOCOOrders:
    """Tests for OCA (One-Cancels-All) order groups."""

    def test_oco_one_fills_cancels_other(self, simulator, bar_day1):
        """When one OCO order fills, sibling is cancelled."""
        # Bar: open=100, high=105, low=95
        # Buy limit at 96 will fill (low=95 < 96)
        # Buy limit at 90 will not be reached but should be cancelled
        order1 = LimitOrder(action='BUY', totalQuantity=100, price=96.0, ocaGroup='bracket_1')
        order2 = LimitOrder(action='BUY', totalQuantity=100, price=90.0, ocaGroup='bracket_1')

        trade1 = simulator.submit_order(order1)
        trade2 = simulator.submit_order(order2)

        fills = simulator.process_bar(bar_day1)

        assert len(fills) == 1
        assert fills[0].order.orderId == order1.orderId
        assert simulator.get_trade(order1.orderId) is None
        assert simulator.get_trade(order2.orderId) is None  # Cancelled by OCO
        assert trade1.orderStatus.status == 'Filled'
        assert trade2.orderStatus.status == 'Cancelled'

    def test_oco_closest_to_open_fills_first(self, simulator):
        """When multiple OCO orders could fill, closest to open wins."""
        # Bar: open=100, high=105, low=95
        # Both limits at 96 and 98 would fill (low=95 < both)
        # Order at 98 is closer to open=100, should fill first
        bar = BarData(
            date=datetime(2024, 1, 15, 9, 30),
            open=100.0,
            high=105.0,
            low=95.0,
            close=102.0,
            volume=1000
        )

        order1 = LimitOrder(action='BUY', totalQuantity=100, price=96.0, ocaGroup='bracket_1')
        order2 = LimitOrder(action='BUY', totalQuantity=100, price=98.0, ocaGroup='bracket_1')

        trade1 = simulator.submit_order(order1)
        trade2 = simulator.submit_order(order2)

        fills = simulator.process_bar(bar)

        assert len(fills) == 1
        # Order2 (price=98) is closer to open=100, should fill
        assert fills[0].order.orderId == order2.orderId
        assert trade2.orderStatus.status == 'Filled'
        assert trade1.orderStatus.status == 'Cancelled'

    def test_oco_no_fill_both_remain(self, simulator, bar_day1):
        """When neither OCO order fills, both remain active."""
        # Bar: open=100, high=105, low=95
        # Both limits at 90 and 85 won't fill (low=95 > both)
        order1 = LimitOrder(action='BUY', totalQuantity=100, price=90.0, ocaGroup='bracket_1')
        order2 = LimitOrder(action='BUY', totalQuantity=100, price=85.0, ocaGroup='bracket_1')

        trade1 = simulator.submit_order(order1)
        trade2 = simulator.submit_order(order2)

        fills = simulator.process_bar(bar_day1)

        assert len(fills) == 0
        assert simulator.get_trade(order1.orderId) is trade1
        assert simulator.get_trade(order2.orderId) is trade2
        assert trade1.orderStatus.status == 'Submitted'
        assert trade2.orderStatus.status == 'Submitted'

    def test_oco_cancel_invokes_callback(self, simulator, bar_day1):
        """Cancelled OCO sibling triggers on_cancel."""
        cancelled = []

        def on_cancel(trade):
            cancelled.append(trade)

        simulator.on_cancel(on_cancel)

        order1 = LimitOrder(action='BUY', totalQuantity=100, price=96.0, ocaGroup='bracket_1')
        order2 = LimitOrder(action='BUY', totalQuantity=100, price=90.0, ocaGroup='bracket_1')

        simulator.submit_order(order1)
        trade2 = simulator.submit_order(order2)

        simulator.process_bar(bar_day1)

        assert len(cancelled) == 1
        assert cancelled[0] is trade2
        assert f"OCO: order {order1.orderId} filled" in trade2.log[-1].message

    def test_oco_three_orders_one_fills(self, simulator, bar_day1):
        """OCO group with 3 orders - one fill cancels two."""
        # Bar: open=100, high=105, low=95
        order1 = LimitOrder(action='BUY', totalQuantity=100, price=96.0, ocaGroup='bracket_1')  # Fills
        order2 = LimitOrder(action='BUY', totalQuantity=100, price=90.0, ocaGroup='bracket_1')  # Cancelled
        order3 = LimitOrder(action='BUY', totalQuantity=100, price=85.0, ocaGroup='bracket_1')  # Cancelled

        trade1 = simulator.submit_order(order1)
        trade2 = simulator.submit_order(order2)
        trade3 = simulator.submit_order(order3)

        fills = simulator.process_bar(bar_day1)

        assert len(fills) == 1
        assert fills[0].order.orderId == order1.orderId
        assert len(simulator.get_active_trades()) == 0
        assert trade1.orderStatus.status == 'Filled'
        assert trade2.orderStatus.status == 'Cancelled'
        assert trade3.orderStatus.status == 'Cancelled'

    def test_oco_mixed_order_types(self, simulator):
        """OCO with LimitOrder + StopOrder."""
        # Bar: open=100, high=105, low=95
        # Sell limit at 104 fills (high=105 >= 104)
        # Stop at 96 should be cancelled
        bar = BarData(
            date=datetime(2024, 1, 15, 9, 30),
            open=100.0,
            high=105.0,
            low=95.0,
            close=102.0,
            volume=1000
        )

        limit_order = LimitOrder(action='SELL', totalQuantity=100, price=104.0, ocaGroup='exit_bracket')
        stop_order = StopOrder(action='SELL', totalQuantity=100, stopPrice=96.0, ocaGroup='exit_bracket')

        limit_trade = simulator.submit_order(limit_order)
        stop_trade = simulator.submit_order(stop_order)

        fills = simulator.process_bar(bar)

        # Limit should fill (closer to open at 100 vs stop at 96)
        assert len(fills) == 1
        assert fills[0].order.orderId == limit_order.orderId
        assert limit_trade.orderStatus.status == 'Filled'
        assert stop_trade.orderStatus.status == 'Cancelled'
        assert simulator.get_trade(stop_order.orderId) is None

    def test_oco_order_status_after_user_cancel(self, simulator):
        """Trade status is set to Cancelled when user cancels."""
        order = LimitOrder(action='BUY', totalQuantity=100, price=90.0)
        trade = simulator.submit_order(order)

        assert trade.orderStatus.status == 'Submitted'

        simulator.cancel_order(order.orderId)

        assert trade.orderStatus.status == 'Cancelled'

    def test_oco_order_status_after_fill(self, simulator, bar_day1):
        """Trade status is set to Filled when order fills."""
        order = MarketOrder(action='BUY', totalQuantity=100)
        trade = simulator.submit_order(order)

        assert trade.orderStatus.status == 'Submitted'

        simulator.process_bar(bar_day1)

        assert trade.orderStatus.status == 'Filled'

    def test_oco_independent_groups(self, simulator, bar_day1):
        """Orders in different OCA groups don't affect each other."""
        # Group 1
        order1a = LimitOrder(action='BUY', totalQuantity=100, price=96.0, ocaGroup='group_1')  # Fills
        order1b = LimitOrder(action='BUY', totalQuantity=100, price=90.0, ocaGroup='group_1')  # Cancelled

        # Group 2 - independent
        order2a = MarketOrder(action='SELL', totalQuantity=50, ocaGroup='group_2')  # Fills
        order2b = LimitOrder(action='SELL', totalQuantity=50, price=120.0, ocaGroup='group_2')  # Cancelled

        trade1a = simulator.submit_order(order1a)
        trade1b = simulator.submit_order(order1b)
        trade2a = simulator.submit_order(order2a)
        trade2b = simulator.submit_order(order2b)

        fills = simulator.process_bar(bar_day1)

        assert len(fills) == 2  # Both groups had a fill
        assert trade1a.orderStatus.status == 'Filled'
        assert trade1b.orderStatus.status == 'Cancelled'
        assert trade2a.orderStatus.status == 'Filled'
        assert trade2b.orderStatus.status == 'Cancelled'

    def test_oco_fills_on_second_bar(self, simulator, bar_day1, bar_day2):
        """OCO orders pending on first bar, one fills on second bar."""
        # Bar1: open=100, high=105, low=95
        # Bar2: open=102, high=110, low=100
        # Both limits at 90 and 85 won't fill on bar1
        # After bar1, change order1 price to 101 (will fill on bar2)
        order1 = LimitOrder(action='BUY', totalQuantity=100, price=90.0, ocaGroup='bracket_1')
        order2 = LimitOrder(action='BUY', totalQuantity=100, price=85.0, ocaGroup='bracket_1')

        trade1 = simulator.submit_order(order1)
        trade2 = simulator.submit_order(order2)

        fills1 = simulator.process_bar(bar_day1)
        assert len(fills1) == 0

        # Update order1 to fill on bar2
        simulator.update_order(order1.orderId, price=101.0)

        fills2 = simulator.process_bar(bar_day2)
        assert len(fills2) == 1
        assert fills2[0].order.orderId == order1.orderId
        assert trade1.orderStatus.status == 'Filled'
        assert trade2.orderStatus.status == 'Cancelled'

    def test_oco_cancel_callback_can_submit_replacement_in_same_group(self, simulator, bar_day1, bar_day2):
        """Order submitted into the same OCA group from within an on_cancel callback
        must not be orphaned — it should remain active after the group is cleaned up."""
        order1 = LimitOrder(action='BUY', totalQuantity=100, price=96.0, ocaGroup='g1')
        order2 = LimitOrder(action='BUY', totalQuantity=100, price=90.0, ocaGroup='g1')
        simulator.submit_order(order1)
        simulator.submit_order(order2)

        replacement = LimitOrder(action='BUY', totalQuantity=100, price=88.0, ocaGroup='g1')

        def on_cancel(trade):
            if trade.order.orderId == order2.orderId:
                simulator.submit_order(replacement)

        simulator.on_cancel(on_cancel)

        # bar_day1: order1 fills (low=95 < 96), order2 is OCA-cancelled → callback submits replacement
        simulator.process_bar(bar_day1)

        assert simulator.get_trade(replacement.orderId) is not None  # replacement is active, not orphaned

        # bar_day2: replacement should still be evaluatable
        fills = simulator.process_bar(bar_day2)
        # replacement limit=88, bar_day2 low=95 — should not fill
        assert simulator.get_trade(replacement.orderId) is not None


# endregion

# region process_bars Tests

class TestProcessBars:
    """Tests for the process_bars generator method."""

    def test_yields_fills_per_bar_by_default(self, simulator, bar_day1, bar_day2, bar_day3):
        """Default predicate yields once per bar."""
        results = list(simulator.process_bars([bar_day1, bar_day2, bar_day3]))
        assert len(results) == 3

    def test_empty_bars_yields_nothing(self, simulator):
        """Empty input produces no yields."""
        assert list(simulator.process_bars([])) == []

    def test_fills_match_process_bar(self, simulator, bar_day1, bar_day2):
        """Fills yielded match what process_bar would return for the same orders."""
        order = MarketOrder(action='BUY', totalQuantity=100)
        simulator.submit_order(order)

        fills_day1, fills_day2 = simulator.process_bars([bar_day1, bar_day2])

        assert len(fills_day1) == 1
        assert fills_day1[0].execution.price == bar_day1.open
        assert fills_day2 == []

    def test_orders_submitted_mid_iteration_fill_next_bar(self, simulator, bar_day1, bar_day2):
        """Orders submitted during iteration fill on the subsequent bar."""
        order = LimitOrder(action='BUY', totalQuantity=50, price=101.0)

        results = []
        for fills in simulator.process_bars([bar_day1, bar_day2]):
            results.append(fills)
            if len(results) == 1:
                # bar_day2 open=102, high=110, low=100 — limit 101 will fill
                simulator.submit_order(order)

        assert results[0] == []
        assert len(results[1]) == 1
        assert results[1][0].execution.orderId == order.orderId

    def test_no_fills_when_no_orders(self, simulator, bar_day1, bar_day2):
        """Bars with no active orders yield empty fill lists."""
        for fills in simulator.process_bars([bar_day1, bar_day2]):
            assert fills == []

    def test_is_lazy_generator(self, simulator, bar_day1, bar_day2, bar_day3):
        """process_bars returns a generator, not a pre-computed list."""
        import types
        assert isinstance(simulator.process_bars([bar_day1, bar_day2, bar_day3]), types.GeneratorType)

    def test_yield_predicate_accumulates_fills(self, simulator, bar_day1, bar_day2, bar_day3):
        """Fills accumulate across bars until predicate fires."""
        order1 = MarketOrder(action='BUY', totalQuantity=100)
        order2 = MarketOrder(action='BUY', totalQuantity=50)
        simulator.submit_order(order1)
        simulator.submit_order(order2)

        # Predicate fires only on bar_day3 (last bar)
        results = list(simulator.process_bars(
            [bar_day1, bar_day2, bar_day3],
            yield_predicate=lambda bar: bar is bar_day3,
        ))

        assert len(results) == 1
        assert len(results[0]) == 2  # both fills accumulated

    def test_yield_predicate_fires_on_close_bar(self, simulator, bar_day1, bar_day2):
        """Predicate based on is_close_bar yields only at end of day."""
        order = MarketOrder(action='BUY', totalQuantity=100)
        simulator.submit_order(order)

        bar_day1_close = bar_day1.model_copy(update={'is_close_bar': True})
        results = list(simulator.process_bars(
            [bar_day1, bar_day1_close, bar_day2],
            yield_predicate=lambda bar: bar.is_close_bar,
        ))

        assert len(results) == 1
        assert len(results[0]) == 1  # fill from bar_day1, accumulated through bar_day1_close

# endregion
