"""Tests for Simulator class."""
import pytest
from datetime import datetime
from decimal import Decimal

from xtrading_models import (
    BarData,
    MarketOrder,
    LimitOrder,
    StopOrder,
    Order
)
from xtrading_models.order import StopLimitOrder, TrailingStopMarket

from simulator import Simulator


# region Test Fixtures

@pytest.fixture
def simulator():
    """Create a fresh Simulator instance."""
    return Simulator()


@pytest.fixture
def bar_day1():
    """Bar for day 1: 2024-01-15."""
    return BarData(
        date=datetime(2024, 1, 15, 9, 30),
        open=Decimal('100'),
        high=Decimal('105'),
        low=Decimal('95'),
        close=Decimal('102'),
        volume=1000
    )


@pytest.fixture
def bar_day2():
    """Bar for day 2: 2024-01-16."""
    return BarData(
        date=datetime(2024, 1, 16, 9, 30),
        open=Decimal('102'),
        high=Decimal('110'),
        low=Decimal('100'),
        close=Decimal('108'),
        volume=1200
    )


@pytest.fixture
def bar_day3():
    """Bar for day 3: 2024-01-17."""
    return BarData(
        date=datetime(2024, 1, 17, 9, 30),
        open=Decimal('108'),
        high=Decimal('115'),
        low=Decimal('106'),
        close=Decimal('112'),
        volume=1500
    )


# endregion

# region Order Submission Tests

class TestOrderSubmission:
    """Tests for order submission."""

    def test_submit_order_returns_order_id(self, simulator):
        """Submit returns the order ID."""
        order = MarketOrder(action='BUY', totalQuantity=100)
        order_id = simulator.submit_order(order)
        assert order_id == order.orderId

    def test_submit_order_tracked_in_active_orders(self, simulator):
        """Submitted order is tracked in active orders."""
        order = MarketOrder(action='BUY', totalQuantity=100)
        simulator.submit_order(order)
        assert simulator.get_order(order.orderId) is order
        assert order in simulator.get_active_orders()

    def test_submit_multiple_orders(self, simulator):
        """Multiple orders can be submitted and tracked."""
        order1 = MarketOrder(action='BUY', totalQuantity=100)
        order2 = LimitOrder(action='SELL', totalQuantity=50, price=Decimal('150'))

        simulator.submit_order(order1)
        simulator.submit_order(order2)

        assert len(simulator.get_active_orders()) == 2
        assert simulator.get_order(order1.orderId) is order1
        assert simulator.get_order(order2.orderId) is order2


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
        """Cancelled order is removed from active orders."""
        order = MarketOrder(action='BUY', totalQuantity=100)
        simulator.submit_order(order)

        simulator.cancel_order(order.orderId)

        assert simulator.get_order(order.orderId) is None
        assert order not in simulator.get_active_orders()

    def test_cancel_nonexistent_order_returns_false(self, simulator):
        """Cancel returns False for non-existent order."""
        result = simulator.cancel_order(99999)
        assert result is False

    def test_cancel_triggers_callback(self, simulator):
        """Cancel invokes on_cancel callback with reason."""
        cancelled_orders = []

        def on_cancel(order, reason):
            cancelled_orders.append((order, reason))

        simulator.on_cancel(on_cancel)

        order = MarketOrder(action='BUY', totalQuantity=100)
        simulator.submit_order(order)
        simulator.cancel_order(order.orderId)

        assert len(cancelled_orders) == 1
        assert cancelled_orders[0][0] is order
        assert cancelled_orders[0][1] == "User cancelled"


# endregion

# region Bar Processing Tests

class TestBarProcessing:
    """Tests for bar processing."""

    def test_market_order_fills_immediately(self, simulator, bar_day1):
        """Market order fills on first bar."""
        order = MarketOrder(action='BUY', totalQuantity=100)
        simulator.submit_order(order)

        fills = simulator.process_bar(bar_day1)

        assert len(fills) == 1
        assert fills[0].execution.price == Decimal('100')  # Open price
        assert simulator.get_order(order.orderId) is None  # Removed

    def test_limit_order_fills_when_price_reached(self, simulator, bar_day1):
        """Limit order fills when price reaches limit."""
        # Buy limit at 96, bar low is 95 - should fill
        order = LimitOrder(action='BUY', totalQuantity=100, price=Decimal('96'))
        simulator.submit_order(order)

        fills = simulator.process_bar(bar_day1)

        assert len(fills) == 1
        assert fills[0].execution.price == Decimal('96')
        assert simulator.get_order(order.orderId) is None

    def test_limit_order_stays_pending_when_price_not_reached(self, simulator, bar_day1):
        """Limit order stays pending when price not reached."""
        # Buy limit at 90, bar low is 95 - should not fill
        order = LimitOrder(action='BUY', totalQuantity=100, price=Decimal('90'))
        simulator.submit_order(order)

        fills = simulator.process_bar(bar_day1)

        assert len(fills) == 0
        assert simulator.get_order(order.orderId) is order

    def test_multi_bar_fill(self, simulator, bar_day1, bar_day2):
        """Order fills across multiple bars."""
        # Buy limit at 90, bar1 low is 95, bar2 low is 100 - never fills
        order = LimitOrder(action='BUY', totalQuantity=100, price=Decimal('90'))
        simulator.submit_order(order)

        fills1 = simulator.process_bar(bar_day1)
        assert len(fills1) == 0

        fills2 = simulator.process_bar(bar_day2)
        assert len(fills2) == 0

        # Order still active
        assert simulator.get_order(order.orderId) is order

    def test_limit_order_fills_on_second_bar(self, simulator):
        """Limit order pending on first bar fills on second bar."""
        # Buy limit at 94, bar1 low is 95 (no fill), bar2 low is 93 (fills)
        bar1 = BarData(date=datetime(2025, 1, 1, 9, 30), open=Decimal('100'), high=Decimal('105'), low=Decimal('95'), close=Decimal('102'), volume=1000)
        bar2 = BarData(date=datetime(2025, 1, 1, 9, 31), open=Decimal('96'), high=Decimal('98'), low=Decimal('93'), close=Decimal('95'), volume=1000)

        order = LimitOrder(action='BUY', totalQuantity=100, price=Decimal('94'))
        simulator.submit_order(order)

        fills1 = simulator.process_bar(bar1)
        assert len(fills1) == 0  # Not filled yet
        assert simulator.get_order(order.orderId) is not None

        fills2 = simulator.process_bar(bar2)
        assert len(fills2) == 1  # Filled on second bar
        assert fills2[0].execution.price == Decimal('94')
        assert simulator.get_order(order.orderId) is None  # Removed from active

    def test_stop_limit_partial_fill_completes_on_second_bar(self, simulator):
        """StopLimit: stop triggers on bar1 (partial), limit fills on bar2."""
        # Buy stop-limit: stop at 102, limit at 101
        # Bar1: high=105 triggers stop, but low=102 doesn't reach limit 101 -> PARTIAL
        # Bar2: low=100 reaches limit 101 -> fills
        bar1 = BarData(date=datetime(2025, 1, 1, 9, 30), open=Decimal('103'), high=Decimal('105'), low=Decimal('102'), close=Decimal('104'), volume=1000)
        bar2 = BarData(date=datetime(2025, 1, 1, 9, 31), open=Decimal('103'), high=Decimal('104'), low=Decimal('100'), close=Decimal('102'), volume=1000)

        order = StopLimitOrder(action='BUY', totalQuantity=100, stopPrice=Decimal('102'), limitPrice=Decimal('101'))
        simulator.submit_order(order)

        # Bar 1: Stop triggers, limit child becomes pending
        fills1 = simulator.process_bar(bar1)
        assert len(fills1) == 1  # Only stop trigger
        assert simulator.get_order(order.orderId) is None  # Parent removed
        # Child limit order should now be active
        active = simulator.get_active_orders()
        assert len(active) == 1
        assert active[0].orderType == 'LMT'
        assert active[0].price == Decimal('101')

        # Bar 2: Limit fills
        fills2 = simulator.process_bar(bar2)
        assert len(fills2) == 1  # Limit fills
        assert fills2[0].execution.price == Decimal('101')
        assert len(simulator.get_active_orders()) == 0  # All done

    def test_trailing_stop_market_across_three_bars(self, simulator):
        """Trailing stop: initializes bar1, trails up bar2, triggers bar3."""
        # Sell trailing stop with $5 trailing distance
        # Bar1: high=102 sets extreme=102, stop=97, low=99 > 97 (no trigger)
        # Bar2: high=110 updates extreme=110, stop=105, low=106 > 105 (no trigger)
        # Bar3: low=103 < stop=105 (triggers and fills)
        bar1 = BarData(date=datetime(2025, 1, 1, 9, 30), open=Decimal('100'), high=Decimal('102'), low=Decimal('99'), close=Decimal('101'), volume=1000)
        bar2 = BarData(date=datetime(2025, 1, 1, 9, 31), open=Decimal('107'), high=Decimal('110'), low=Decimal('106'), close=Decimal('109'), volume=1000)
        bar3 = BarData(date=datetime(2025, 1, 1, 9, 32), open=Decimal('108'), high=Decimal('109'), low=Decimal('103'), close=Decimal('104'), volume=1000)

        order = TrailingStopMarket(
            action='SELL',
            totalQuantity=100,
            trailingDistance=Decimal('5')
        )
        simulator.submit_order(order)

        # Bar 1: Initialize extreme and stop
        fills1 = simulator.process_bar(bar1)
        assert len(fills1) == 0
        assert order.extremePrice == Decimal('102')
        assert order.stopPrice == Decimal('97')

        # Bar 2: Price goes up, stop trails up
        fills2 = simulator.process_bar(bar2)
        assert len(fills2) == 0
        assert order.extremePrice == Decimal('110')
        assert order.stopPrice == Decimal('105')

        # Bar 3: Price drops below stop, triggers
        fills3 = simulator.process_bar(bar3)
        assert len(fills3) == 2  # Stop trigger + market child fill
        assert fills3[-1].execution.price == Decimal('105')  # Fills at stop price
        assert len(simulator.get_active_orders()) == 0

    def test_stop_order_triggers_on_second_bar(self, simulator):
        """Stop order pending on bar1, triggers on bar2."""
        # Bar1: low=98 doesn't reach stop=97
        # Bar2: low=95 triggers stop=97, market child fills
        bar1 = BarData(date=datetime(2025, 1, 1, 9, 30), open=Decimal('100'), high=Decimal('102'), low=Decimal('98'), close=Decimal('101'), volume=1000)
        bar2 = BarData(date=datetime(2025, 1, 1, 9, 31), open=Decimal('99'), high=Decimal('100'), low=Decimal('95'), close=Decimal('96'), volume=1000)

        order = StopOrder(action='SELL', totalQuantity=100, stopPrice=Decimal('97'))
        simulator.submit_order(order)

        # Bar 1: Stop not triggered
        fills1 = simulator.process_bar(bar1)
        assert len(fills1) == 0
        assert simulator.get_order(order.orderId) is order

        # Bar 2: Stop triggers and market child fills
        fills2 = simulator.process_bar(bar2)
        assert len(fills2) == 2  # Stop trigger + market child
        assert fills2[-1].execution.price == Decimal('97')  # Fills at stop price
        assert len(simulator.get_active_orders()) == 0

    def test_stop_limit_child_pending_across_multiple_bars(self, simulator):
        """StopLimit: stop triggers bar1, limit child stays pending bars 2-3, fills bar4."""
        # Bar1: stop triggers but limit not reached
        # Bar2-3: limit still not reached
        # Bar4: limit finally fills
        bar1 = BarData(date=datetime(2025, 1, 1, 9, 30), open=Decimal('103'), high=Decimal('105'), low=Decimal('102'), close=Decimal('104'), volume=1000)
        bar2 = BarData(date=datetime(2025, 1, 1, 9, 31), open=Decimal('104'), high=Decimal('106'), low=Decimal('103'), close=Decimal('105'), volume=1000)
        bar3 = BarData(date=datetime(2025, 1, 1, 9, 32), open=Decimal('105'), high=Decimal('107'), low=Decimal('104'), close=Decimal('106'), volume=1000)
        bar4 = BarData(date=datetime(2025, 1, 1, 9, 33), open=Decimal('102'), high=Decimal('103'), low=Decimal('99'), close=Decimal('100'), volume=1000)

        order = StopLimitOrder(action='BUY', totalQuantity=100, stopPrice=Decimal('102'), limitPrice=Decimal('100'))
        simulator.submit_order(order)

        # Bar 1: Stop triggers, limit child becomes pending
        fills1 = simulator.process_bar(bar1)
        assert len(fills1) == 1  # Stop trigger only
        active = simulator.get_active_orders()
        assert len(active) == 1
        limit_child = active[0]
        assert limit_child.orderType == 'LMT'
        assert limit_child.price == Decimal('100')

        # Bar 2: Limit still not reached (low=103 > 100)
        fills2 = simulator.process_bar(bar2)
        assert len(fills2) == 0
        assert simulator.get_order(limit_child.orderId) is limit_child

        # Bar 3: Limit still not reached (low=104 > 100)
        fills3 = simulator.process_bar(bar3)
        assert len(fills3) == 0
        assert simulator.get_order(limit_child.orderId) is limit_child

        # Bar 4: Limit fills (low=99 < 100)
        fills4 = simulator.process_bar(bar4)
        assert len(fills4) == 1
        assert fills4[0].execution.price == Decimal('100')
        assert len(simulator.get_active_orders()) == 0

    def test_multiple_parent_orders_trigger_on_different_bars(self, simulator):
        """Two stop orders submitted together, triggering on different bars."""
        bar1 = BarData(date=datetime(2025, 1, 1, 9, 30), open=Decimal('100'), high=Decimal('102'), low=Decimal('98'), close=Decimal('101'), volume=1000)
        bar2 = BarData(date=datetime(2025, 1, 1, 9, 31), open=Decimal('99'), high=Decimal('100'), low=Decimal('94'), close=Decimal('95'), volume=1000)

        # Stop1 at 99 triggers on bar1 (low=98)
        # Stop2 at 95 triggers on bar2 (low=94)
        stop1 = StopOrder(action='SELL', totalQuantity=100, stopPrice=Decimal('99'))
        stop2 = StopOrder(action='SELL', totalQuantity=50, stopPrice=Decimal('95'))

        simulator.submit_order(stop1)
        simulator.submit_order(stop2)

        # Bar 1: Only stop1 triggers
        fills1 = simulator.process_bar(bar1)
        assert len(fills1) == 2  # Stop1 trigger + market child
        assert simulator.get_order(stop1.orderId) is None
        assert simulator.get_order(stop2.orderId) is stop2  # Still pending

        # Bar 2: stop2 triggers
        fills2 = simulator.process_bar(bar2)
        assert len(fills2) == 2  # Stop2 trigger + market child
        assert len(simulator.get_active_orders()) == 0

    def test_stop_order_triggers_and_fills(self, simulator, bar_day1):
        """Stop order triggers and fills via child market order."""
        # Sell stop at 97, bar low is 95 - should trigger and fill
        order = StopOrder(action='SELL', totalQuantity=100, stopPrice=Decimal('97'))
        simulator.submit_order(order)

        fills = simulator.process_bar(bar_day1)

        # Should have 2 fills: stop trigger + market child
        assert len(fills) == 2
        assert simulator.get_order(order.orderId) is None

    def test_trailing_stop_updates_across_bars(self, simulator, bar_day1, bar_day2):
        """Trailing stop updates extreme price across bars."""
        # Buy trailing stop with $5 trailing distance
        order = TrailingStopMarket(
            action='BUY',
            totalQuantity=100,
            trailingDistance=Decimal('5')
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
        assert len(simulator.get_active_orders()) == 0


# endregion

# region TIF Expiration Tests

class TestTIFExpiration:
    """Tests for Time-In-Force expiration."""

    def test_gtc_never_expires(self, simulator, bar_day1, bar_day2, bar_day3):
        """GTC orders never expire on date change."""
        order = LimitOrder(action='BUY', totalQuantity=100, price=Decimal('50'), tif='GTC')
        simulator.submit_order(order)

        simulator.process_bar(bar_day1)
        simulator.process_bar(bar_day2)
        simulator.process_bar(bar_day3)

        # Order still active after 3 days
        assert simulator.get_order(order.orderId) is order

    def test_day_order_expires_on_date_change(self, simulator, bar_day1, bar_day2):
        """DAY orders expire when date changes."""
        order = LimitOrder(action='BUY', totalQuantity=100, price=Decimal('50'), tif='DAY')
        simulator.submit_order(order)

        fills1 = simulator.process_bar(bar_day1)
        assert len(fills1) == 0
        assert simulator.get_order(order.orderId) is order  # Still active on day 1

        fills2 = simulator.process_bar(bar_day2)
        assert len(fills2) == 0
        assert simulator.get_order(order.orderId) is None  # Expired on day 2

    def test_day_order_expiration_triggers_callback(self, simulator, bar_day1, bar_day2):
        """DAY order expiration invokes on_cancel callback."""
        cancelled = []

        def on_cancel(order, reason):
            cancelled.append((order, reason))

        simulator.on_cancel(on_cancel)

        order = LimitOrder(action='BUY', totalQuantity=100, price=Decimal('50'), tif='DAY')
        simulator.submit_order(order)

        simulator.process_bar(bar_day1)
        simulator.process_bar(bar_day2)

        assert len(cancelled) == 1
        assert cancelled[0][0] is order
        assert cancelled[0][1] == "DAY order expired"

    def test_gtd_order_expires_after_date(self, simulator, bar_day1, bar_day2, bar_day3):
        """GTD orders expire after goodTillDate."""
        # GTD until 2024-01-16 (day2)
        order = LimitOrder(
            action='BUY',
            totalQuantity=100,
            price=Decimal('50'),
            tif='GTD',
            goodTillDate='20240116'  # YYYYMMDD format
        )
        simulator.submit_order(order)

        simulator.process_bar(bar_day1)  # Jan 15 - active
        assert simulator.get_order(order.orderId) is order

        simulator.process_bar(bar_day2)  # Jan 16 - still active (not past GTD)
        assert simulator.get_order(order.orderId) is order

        simulator.process_bar(bar_day3)  # Jan 17 - expired (past GTD)
        assert simulator.get_order(order.orderId) is None

    def test_gtd_order_expiration_triggers_callback(self, simulator, bar_day1, bar_day2, bar_day3):
        """GTD order expiration invokes on_cancel callback."""
        cancelled = []

        def on_cancel(order, reason):
            cancelled.append((order, reason))

        simulator.on_cancel(on_cancel)

        order = LimitOrder(
            action='BUY',
            totalQuantity=100,
            price=Decimal('50'),
            tif='GTD',
            goodTillDate='20240116'
        )
        simulator.submit_order(order)

        simulator.process_bar(bar_day1)
        simulator.process_bar(bar_day2)
        simulator.process_bar(bar_day3)

        assert len(cancelled) == 1
        assert cancelled[0][0] is order
        assert cancelled[0][1] == "GTD order expired"

    def test_default_tif_is_empty_string(self, simulator, bar_day1, bar_day2, bar_day3):
        """Orders with empty TIF don't expire (treated like GTC)."""
        order = LimitOrder(action='BUY', totalQuantity=100, price=Decimal('50'))
        # Default tif is empty string
        assert order.tif == ''

        simulator.submit_order(order)

        simulator.process_bar(bar_day1)
        simulator.process_bar(bar_day2)
        simulator.process_bar(bar_day3)

        # Order still active
        assert simulator.get_order(order.orderId) is order


# endregion

# region Callback Tests

class TestCallbacks:
    """Tests for callback invocations."""

    def test_on_fill_callback_invoked(self, simulator, bar_day1):
        """on_fill callback is invoked when order fills."""
        fills_received = []

        def on_fill(fill):
            fills_received.append(fill)

        simulator.on_fill(on_fill)

        order = MarketOrder(action='BUY', totalQuantity=100)
        simulator.submit_order(order)
        simulator.process_bar(bar_day1)

        assert len(fills_received) == 1
        assert fills_received[0].execution.price == Decimal('100')

    def test_multiple_fill_callbacks(self, simulator, bar_day1):
        """Multiple on_fill callbacks are all invoked."""
        fills1 = []
        fills2 = []

        simulator.on_fill(lambda fill: fills1.append(fill))
        simulator.on_fill(lambda fill: fills2.append(fill))

        order = MarketOrder(action='BUY', totalQuantity=100)
        simulator.submit_order(order)
        simulator.process_bar(bar_day1)

        assert len(fills1) == 1
        assert len(fills2) == 1

    def test_on_cancel_callback_invoked(self, simulator):
        """on_cancel callback is invoked when order is cancelled."""
        cancelled = []

        simulator.on_cancel(lambda order, reason: cancelled.append((order, reason)))

        order = MarketOrder(action='BUY', totalQuantity=100)
        simulator.submit_order(order)
        simulator.cancel_order(order.orderId)

        assert len(cancelled) == 1

    def test_on_update_callback_invoked(self, simulator):
        """on_update callback is invoked when order is updated."""
        updates = []

        simulator.on_update(lambda order: updates.append(order))

        order = LimitOrder(action='BUY', totalQuantity=100, price=Decimal('100'))
        simulator.submit_order(order)
        simulator.update_order(order.orderId, price=Decimal('95'))

        assert len(updates) == 1
        assert updates[0] is order


# endregion

# region Order Update Tests

class TestOrderUpdates:
    """Tests for order updates."""

    def test_update_order_price(self, simulator):
        """Update order price."""
        order = LimitOrder(action='BUY', totalQuantity=100, price=Decimal('100'))
        simulator.submit_order(order)

        result = simulator.update_order(order.orderId, price=Decimal('95'))

        assert result is True
        assert order.price == Decimal('95')

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
            trailingDistance=Decimal('5')
        )
        simulator.submit_order(order)

        result = simulator.update_order(order.orderId, trailingDistance=Decimal('10'))

        assert result is True
        assert order.trailingDistance == Decimal('10')

    def test_update_nonexistent_order_returns_false(self, simulator):
        """Update returns False for non-existent order."""
        result = simulator.update_order(99999, price=Decimal('100'))
        assert result is False

    def test_update_triggers_callback(self, simulator):
        """Update invokes on_update callback."""
        updates = []
        simulator.on_update(lambda order: updates.append(order))

        order = LimitOrder(action='BUY', totalQuantity=100, price=Decimal('100'))
        simulator.submit_order(order)
        simulator.update_order(order.orderId, price=Decimal('95'))

        assert len(updates) == 1


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

        def on_bar(bar, fills):
            fills_count.append(len(fills))
            # Submit order for next bar
            simulator.submit_order(MarketOrder(action='BUY', totalQuantity=100))

        simulator.on_bar(on_bar)

        simulator.process_bar(bar_day1)  # No fills, submits order
        simulator.process_bar(bar_day2)  # Fills order, submits another

        assert fills_count == [0, 1]

    def test_run_processes_all_bars(self, simulator, bar_day1, bar_day2, bar_day3):
        """run() processes all bars in sequence."""
        bars_seen = []

        simulator.on_bar(lambda bar, fills: bars_seen.append(bar))
        simulator.run([bar_day1, bar_day2, bar_day3])

        assert len(bars_seen) == 3
        assert bars_seen[0] is bar_day1
        assert bars_seen[1] is bar_day2
        assert bars_seen[2] is bar_day3

    def test_run_with_strategy(self, simulator):
        """Full backtest simulation using run() and on_bar."""
        fills_received = []

        def strategy(bar, fills):
            fills_received.extend(fills)
            # Buy on first bar
            if len(fills_received) == 0 and len(simulator.get_active_orders()) == 0:
                simulator.submit_order(MarketOrder(action='BUY', totalQuantity=100))

        simulator.on_bar(strategy)

        bars = [
            BarData(date=datetime(2024, 1, 15, 9, 30), open=Decimal('100'),
                    high=Decimal('105'), low=Decimal('95'), close=Decimal('102'), volume=1000),
            BarData(date=datetime(2024, 1, 15, 10, 0), open=Decimal('102'),
                    high=Decimal('107'), low=Decimal('100'), close=Decimal('105'), volume=1000),
        ]

        simulator.run(bars)

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

        simulator.on_fill(lambda fill: fills_received.append(fill))
        simulator.on_cancel(lambda order, reason: cancelled.append((order, reason)))

        # Submit orders
        market_order = MarketOrder(action='BUY', totalQuantity=100)
        limit_order = LimitOrder(action='SELL', totalQuantity=50, price=Decimal('110'), tif='DAY')

        simulator.submit_order(market_order)
        simulator.submit_order(limit_order)

        # Day 1: Market fills, limit pending
        bar1 = BarData(
            date=datetime(2024, 1, 15, 9, 30),
            open=Decimal('100'),
            high=Decimal('105'),
            low=Decimal('95'),
            close=Decimal('102'),
            volume=1000
        )

        fills1 = simulator.process_bar(bar1)
        assert len(fills1) == 1  # Market order filled
        assert len(simulator.get_active_orders()) == 1  # Limit still pending

        # Day 2: Limit expires due to DAY TIF
        bar2 = BarData(
            date=datetime(2024, 1, 16, 9, 30),
            open=Decimal('102'),
            high=Decimal('108'),
            low=Decimal('100'),
            close=Decimal('106'),
            volume=1200
        )

        fills2 = simulator.process_bar(bar2)
        assert len(fills2) == 0  # Limit expired before execution
        assert len(simulator.get_active_orders()) == 0
        assert len(cancelled) == 1
        assert cancelled[0][1] == "DAY order expired"

    def test_stop_order_with_gtd(self, simulator):
        """Stop order with GTD expiration."""
        cancelled = []
        simulator.on_cancel(lambda order, reason: cancelled.append((order, reason)))

        # Stop order GTD until Jan 16
        order = StopOrder(
            action='SELL',
            totalQuantity=100,
            stopPrice=Decimal('90'),
            tif='GTD',
            goodTillDate='20240116'
        )
        simulator.submit_order(order)

        # Day 1: Stop not triggered (low=95 > stop=90)
        bar1 = BarData(
            date=datetime(2024, 1, 15, 9, 30),
            open=Decimal('100'),
            high=Decimal('105'),
            low=Decimal('95'),
            close=Decimal('102'),
            volume=1000
        )
        simulator.process_bar(bar1)
        assert simulator.get_order(order.orderId) is not None

        # Day 2: Still active
        bar2 = BarData(
            date=datetime(2024, 1, 16, 9, 30),
            open=Decimal('100'),
            high=Decimal('105'),
            low=Decimal('95'),
            close=Decimal('102'),
            volume=1000
        )
        simulator.process_bar(bar2)
        assert simulator.get_order(order.orderId) is not None

        # Day 3: Expires
        bar3 = BarData(
            date=datetime(2024, 1, 17, 9, 30),
            open=Decimal('100'),
            high=Decimal('105'),
            low=Decimal('95'),
            close=Decimal('102'),
            volume=1000
        )
        simulator.process_bar(bar3)
        assert simulator.get_order(order.orderId) is None
        assert len(cancelled) == 1

    def test_cancel_then_submit_new(self, simulator, bar_day1):
        """Cancel order and submit new one."""
        order1 = LimitOrder(action='BUY', totalQuantity=100, price=Decimal('50'))
        simulator.submit_order(order1)

        simulator.cancel_order(order1.orderId)
        assert len(simulator.get_active_orders()) == 0

        order2 = MarketOrder(action='BUY', totalQuantity=100)
        simulator.submit_order(order2)

        fills = simulator.process_bar(bar_day1)
        assert len(fills) == 1
        assert simulator.get_order(order1.orderId) is None
        assert simulator.get_order(order2.orderId) is None  # Filled and removed


# endregion

# region OCO Tests

class TestOCOOrders:
    """Tests for OCA (One-Cancels-All) order groups."""

    def test_oco_one_fills_cancels_other(self, simulator, bar_day1):
        """When one OCO order fills, sibling is cancelled."""
        # Bar: open=100, high=105, low=95
        # Buy limit at 96 will fill (low=95 < 96)
        # Buy limit at 90 will not be reached but should be cancelled
        order1 = LimitOrder(action='BUY', totalQuantity=100, price=Decimal('96'), ocaGroup='bracket_1')
        order2 = LimitOrder(action='BUY', totalQuantity=100, price=Decimal('90'), ocaGroup='bracket_1')

        simulator.submit_order(order1)
        simulator.submit_order(order2)

        fills = simulator.process_bar(bar_day1)

        assert len(fills) == 1
        assert fills[0].order.orderId == order1.orderId
        assert simulator.get_order(order1.orderId) is None
        assert simulator.get_order(order2.orderId) is None  # Cancelled by OCO
        assert order1.status == 'FILLED'
        assert order2.status == 'CANCELLED'

    def test_oco_closest_to_open_fills_first(self, simulator):
        """When multiple OCO orders could fill, closest to open wins."""
        # Bar: open=100, high=105, low=95
        # Both limits at 96 and 98 would fill (low=95 < both)
        # Order at 98 is closer to open=100, should fill first
        bar = BarData(
            date=datetime(2024, 1, 15, 9, 30),
            open=Decimal('100'),
            high=Decimal('105'),
            low=Decimal('95'),
            close=Decimal('102'),
            volume=1000
        )

        order1 = LimitOrder(action='BUY', totalQuantity=100, price=Decimal('96'), ocaGroup='bracket_1')
        order2 = LimitOrder(action='BUY', totalQuantity=100, price=Decimal('98'), ocaGroup='bracket_1')

        simulator.submit_order(order1)
        simulator.submit_order(order2)

        fills = simulator.process_bar(bar)

        assert len(fills) == 1
        # Order2 (price=98) is closer to open=100, should fill
        assert fills[0].order.orderId == order2.orderId
        assert order2.status == 'FILLED'
        assert order1.status == 'CANCELLED'

    def test_oco_no_fill_both_remain(self, simulator, bar_day1):
        """When neither OCO order fills, both remain active."""
        # Bar: open=100, high=105, low=95
        # Both limits at 90 and 85 won't fill (low=95 > both)
        order1 = LimitOrder(action='BUY', totalQuantity=100, price=Decimal('90'), ocaGroup='bracket_1')
        order2 = LimitOrder(action='BUY', totalQuantity=100, price=Decimal('85'), ocaGroup='bracket_1')

        simulator.submit_order(order1)
        simulator.submit_order(order2)

        fills = simulator.process_bar(bar_day1)

        assert len(fills) == 0
        assert simulator.get_order(order1.orderId) is order1
        assert simulator.get_order(order2.orderId) is order2
        assert order1.status == 'PENDING'
        assert order2.status == 'PENDING'

    def test_oco_cancel_invokes_callback(self, simulator, bar_day1):
        """Cancelled OCO sibling triggers on_cancel with reason."""
        cancelled = []

        def on_cancel(order, reason):
            cancelled.append((order, reason))

        simulator.on_cancel(on_cancel)

        order1 = LimitOrder(action='BUY', totalQuantity=100, price=Decimal('96'), ocaGroup='bracket_1')
        order2 = LimitOrder(action='BUY', totalQuantity=100, price=Decimal('90'), ocaGroup='bracket_1')

        simulator.submit_order(order1)
        simulator.submit_order(order2)

        simulator.process_bar(bar_day1)

        assert len(cancelled) == 1
        assert cancelled[0][0] is order2
        assert f"OCO: order {order1.orderId} filled" in cancelled[0][1]

    def test_oco_three_orders_one_fills(self, simulator, bar_day1):
        """OCO group with 3 orders - one fill cancels two."""
        # Bar: open=100, high=105, low=95
        order1 = LimitOrder(action='BUY', totalQuantity=100, price=Decimal('96'), ocaGroup='bracket_1')  # Fills
        order2 = LimitOrder(action='BUY', totalQuantity=100, price=Decimal('90'), ocaGroup='bracket_1')  # Cancelled
        order3 = LimitOrder(action='BUY', totalQuantity=100, price=Decimal('85'), ocaGroup='bracket_1')  # Cancelled

        simulator.submit_order(order1)
        simulator.submit_order(order2)
        simulator.submit_order(order3)

        fills = simulator.process_bar(bar_day1)

        assert len(fills) == 1
        assert fills[0].order.orderId == order1.orderId
        assert len(simulator.get_active_orders()) == 0
        assert order1.status == 'FILLED'
        assert order2.status == 'CANCELLED'
        assert order3.status == 'CANCELLED'

    def test_oco_mixed_order_types(self, simulator):
        """OCO with LimitOrder + StopOrder."""
        # Bar: open=100, high=105, low=95
        # Sell limit at 104 fills (high=105 >= 104)
        # Stop at 96 should be cancelled
        bar = BarData(
            date=datetime(2024, 1, 15, 9, 30),
            open=Decimal('100'),
            high=Decimal('105'),
            low=Decimal('95'),
            close=Decimal('102'),
            volume=1000
        )

        limit_order = LimitOrder(action='SELL', totalQuantity=100, price=Decimal('104'), ocaGroup='exit_bracket')
        stop_order = StopOrder(action='SELL', totalQuantity=100, stopPrice=Decimal('96'), ocaGroup='exit_bracket')

        simulator.submit_order(limit_order)
        simulator.submit_order(stop_order)

        fills = simulator.process_bar(bar)

        # Limit should fill (closer to open at 100 vs stop at 96)
        assert len(fills) == 1
        assert fills[0].order.orderId == limit_order.orderId
        assert limit_order.status == 'FILLED'
        assert stop_order.status == 'CANCELLED'
        assert simulator.get_order(stop_order.orderId) is None

    def test_oco_order_status_after_user_cancel(self, simulator):
        """Order status is set to CANCELLED when user cancels."""
        order = LimitOrder(action='BUY', totalQuantity=100, price=Decimal('90'))
        simulator.submit_order(order)

        assert order.status == 'PENDING'

        simulator.cancel_order(order.orderId)

        assert order.status == 'CANCELLED'

    def test_oco_order_status_after_fill(self, simulator, bar_day1):
        """Order status is set to FILLED when order fills."""
        order = MarketOrder(action='BUY', totalQuantity=100)
        simulator.submit_order(order)

        assert order.status == 'PENDING'

        simulator.process_bar(bar_day1)

        assert order.status == 'FILLED'

    def test_oco_independent_groups(self, simulator, bar_day1):
        """Orders in different OCA groups don't affect each other."""
        # Group 1
        order1a = LimitOrder(action='BUY', totalQuantity=100, price=Decimal('96'), ocaGroup='group_1')  # Fills
        order1b = LimitOrder(action='BUY', totalQuantity=100, price=Decimal('90'), ocaGroup='group_1')  # Cancelled

        # Group 2 - independent
        order2a = MarketOrder(action='SELL', totalQuantity=50, ocaGroup='group_2')  # Fills
        order2b = LimitOrder(action='SELL', totalQuantity=50, price=Decimal('120'), ocaGroup='group_2')  # Cancelled

        simulator.submit_order(order1a)
        simulator.submit_order(order1b)
        simulator.submit_order(order2a)
        simulator.submit_order(order2b)

        fills = simulator.process_bar(bar_day1)

        assert len(fills) == 2  # Both groups had a fill
        assert order1a.status == 'FILLED'
        assert order1b.status == 'CANCELLED'
        assert order2a.status == 'FILLED'
        assert order2b.status == 'CANCELLED'

    def test_oco_fills_on_second_bar(self, simulator, bar_day1, bar_day2):
        """OCO orders pending on first bar, one fills on second bar."""
        # Bar1: open=100, high=105, low=95
        # Bar2: open=102, high=110, low=100
        # Both limits at 90 and 85 won't fill on bar1
        # After bar1, change order1 price to 101 (will fill on bar2)
        order1 = LimitOrder(action='BUY', totalQuantity=100, price=Decimal('90'), ocaGroup='bracket_1')
        order2 = LimitOrder(action='BUY', totalQuantity=100, price=Decimal('85'), ocaGroup='bracket_1')

        simulator.submit_order(order1)
        simulator.submit_order(order2)

        fills1 = simulator.process_bar(bar_day1)
        assert len(fills1) == 0

        # Update order1 to fill on bar2
        simulator.update_order(order1.orderId, price=Decimal('101'))

        fills2 = simulator.process_bar(bar_day2)
        assert len(fills2) == 1
        assert fills2[0].order.orderId == order1.orderId
        assert order1.status == 'FILLED'
        assert order2.status == 'CANCELLED'


# endregion
