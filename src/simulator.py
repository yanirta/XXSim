"""Bar sequence simulator for managing order lifecycle across multiple bars."""
import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import Callable, Optional

logger = logging.getLogger(__name__)

from xtrading_models import Order, Fill, BarData
from execution import ExecutionEngine


@dataclass
class SimulatorConfig:
    """Configuration for Simulator behavior."""
    pass  # Reserved for future configuration options


class Simulator:
    """Manages order lifecycle across multiple bars.

    Wraps ExecutionEngine to provide:
    - Order book management (submit, cancel, update)
    - TIF expiration (GTC, DAY, GTD)
    - Callback notifications (on_fill, on_cancel, on_update)

    Example:
        sim = Simulator()
        sim.on_fill(lambda fill: print(f"Filled: {fill.execution.price}"))
        sim.submit_order(MarketOrder(action='BUY', totalQuantity=100))
        fills = sim.process_bar(bar)
    """

    def __init__(self, config: Optional[SimulatorConfig] = None):
        """Initialize simulator with optional configuration.

        Args:
            config: Optional SimulatorConfig for customization
        """
        self._config = config or SimulatorConfig()
        self._engine = ExecutionEngine()
        self._active_orders: dict[int, Order] = {}
        self._last_bar_date: Optional[date] = None

        # Callbacks
        self._on_fill_callbacks: list[Callable[[Fill], None]] = []
        self._on_cancel_callbacks: list[Callable[[Order, str], None]] = []
        self._on_update_callbacks: list[Callable[[Order], None]] = []
        self._on_bar_callbacks: list[Callable[[BarData, list[Fill]], None]] = []

    # region Order Management

    def submit_order(self, order: Order) -> int:
        """Submit an order to the simulator.

        Args:
            order: Order to submit

        Returns:
            The order ID
        """
        self._active_orders[order.orderId] = order
        return order.orderId

    def cancel_order(self, order_id: int) -> bool:
        """Cancel an active order.

        Args:
            order_id: ID of order to cancel

        Returns:
            True if order was found and cancelled, False otherwise
        """
        order = self._active_orders.pop(order_id, None)
        if order is not None:
            self._invoke_cancel_callbacks(order, "User cancelled")
            return True
        return False

    def update_order(self, order_id: int, **kwargs) -> bool:
        """Update an active order's parameters.

        Supports updating: price, totalQuantity, trailingDistance, trailingPercent

        Args:
            order_id: ID of order to update
            **kwargs: Fields to update (price, totalQuantity, etc.)

        Returns:
            True if order was found and updated, False otherwise
        """
        order = self._active_orders.get(order_id)
        if order is None:
            return False

        # Update allowed fields
        allowed_fields = {'price', 'totalQuantity', 'trailingDistance', 'trailingPercent'}
        for key, value in kwargs.items():
            if key in allowed_fields and hasattr(order, key):
                setattr(order, key, value)

        self._invoke_update_callbacks(order)
        return True

    # endregion

    # region Queries

    def get_order(self, order_id: int) -> Optional[Order]:
        """Get an active order by ID.

        Args:
            order_id: ID of order to retrieve

        Returns:
            Order if found, None otherwise
        """
        return self._active_orders.get(order_id)

    def get_active_orders(self) -> list[Order]:
        """Get all active orders.

        Returns:
            List of all active orders
        """
        return list(self._active_orders.values())

    # endregion

    # region Bar Processing

    def process_bar(self, bar: BarData) -> list[Fill]:
        """Process a bar against all active orders.

        Algorithm:
        1. Expire DAY orders if date changed
        2. Expire GTD orders past goodTillDate
        3. For each active order:
           a. Execute via ExecutionEngine
           b. If FILLED: remove order, invoke on_fill
           c. If PARTIAL: remove parent, add child(ren) as active
           d. If PENDING: keep (state already mutated in-place)
        4. Return all fills

        Args:
            bar: Bar data to process

        Returns:
            List of all fills from this bar
        """
        current_date = bar.date.date() if isinstance(bar.date, datetime) else bar.date

        # 1. Expire DAY orders if date changed
        if self._last_bar_date is not None and current_date != self._last_bar_date:
            self._expire_day_orders()

        # 2. Expire GTD orders past goodTillDate
        self._expire_gtd_orders(current_date)

        # Update last bar date
        self._last_bar_date = current_date

        # 3. Process each active order
        all_fills: list[Fill] = []
        orders_to_remove: list[int] = []
        orders_to_add: list[Order] = []

        for order_id, order in list(self._active_orders.items()):
            result = self._engine.execute(order, bar)

            if result.status == 'FILLED':
                # Completely filled - remove order
                orders_to_remove.append(order_id)
                all_fills.extend(result.fills)
                for fill in result.fills:
                    self._invoke_fill_callbacks(fill)

            elif result.status == 'PARTIAL':
                # Parent filled, children pending - remove parent, add children
                orders_to_remove.append(order_id)
                orders_to_add.extend(result.pending_orders)
                all_fills.extend(result.fills)
                for fill in result.fills:
                    self._invoke_fill_callbacks(fill)

            # PENDING: keep order (state already mutated in-place by engine)

        # Apply removals and additions
        for order_id in orders_to_remove:
            self._active_orders.pop(order_id, None)
        for order in orders_to_add:
            self._active_orders[order.orderId] = order

        # Invoke on_bar callbacks
        self._invoke_bar_callbacks(bar, all_fills)

        return all_fills

    def run(self, bars) -> None:
        """Process a sequence of bars.

        Convenience method that iterates through bars and calls process_bar
        for each. Use on_bar callback to react to each bar.

        Args:
            bars: Iterable of BarData objects
        """
        for bar in bars:
            self.process_bar(bar)

    def _expire_day_orders(self) -> None:
        """Expire all DAY orders (called on date change)."""
        orders_to_expire = [
            (order_id, order)
            for order_id, order in self._active_orders.items()
            if order.tif == 'DAY'
        ]

        for order_id, order in orders_to_expire:
            self._active_orders.pop(order_id)
            self._invoke_cancel_callbacks(order, "DAY order expired")

    def _expire_gtd_orders(self, current_date: date) -> None:
        """Expire GTD orders past their goodTillDate.

        Args:
            current_date: Current bar date
        """
        orders_to_expire: list[tuple[int, Order]] = []

        for order_id, order in self._active_orders.items():
            if order.tif == 'GTD' and order.goodTillDate:
                # Parse goodTillDate string to date
                try:
                    gtd = datetime.strptime(order.goodTillDate, '%Y%m%d').date()
                    if current_date > gtd:
                        orders_to_expire.append((order_id, order))
                except ValueError:
                    # Invalid date format - skip
                    pass

        for order_id, order in orders_to_expire:
            self._active_orders.pop(order_id)
            self._invoke_cancel_callbacks(order, "GTD order expired")

    # endregion

    # region Callbacks

    def on_fill(self, callback: Callable[[Fill], None]) -> None:
        """Register a callback for fill events.

        Args:
            callback: Function called with Fill when order is filled
        """
        self._on_fill_callbacks.append(callback)

    def on_cancel(self, callback: Callable[[Order, str], None]) -> None:
        """Register a callback for cancel events.

        Args:
            callback: Function called with (Order, reason) when order is cancelled
        """
        self._on_cancel_callbacks.append(callback)

    def on_update(self, callback: Callable[[Order], None]) -> None:
        """Register a callback for update events.

        Args:
            callback: Function called with Order when order is updated
        """
        self._on_update_callbacks.append(callback)

    def on_bar(self, callback: Callable[[BarData, list[Fill]], None]) -> None:
        """Register a callback for bar processing events.

        Called after each bar is processed, similar to ib_insync's updateEvent.
        Use this to implement strategy logic that reacts to bars.

        Args:
            callback: Function called with (BarData, list[Fill]) after each bar
        """
        self._on_bar_callbacks.append(callback)

    def _invoke_fill_callbacks(self, fill: Fill) -> None:
        """Invoke all registered fill callbacks. Exceptions are logged and ignored."""
        for callback in self._on_fill_callbacks:
            try:
                callback(fill)
            except Exception:
                logger.exception("Error in fill callback %s", callback.__name__)

    def _invoke_cancel_callbacks(self, order: Order, reason: str) -> None:
        """Invoke all registered cancel callbacks. Exceptions are logged and ignored."""
        for callback in self._on_cancel_callbacks:
            try:
                callback(order, reason)
            except Exception:
                logger.exception("Error in cancel callback %s", callback.__name__)

    def _invoke_update_callbacks(self, order: Order) -> None:
        """Invoke all registered update callbacks. Exceptions are logged and ignored."""
        for callback in self._on_update_callbacks:
            try:
                callback(order)
            except Exception:
                logger.exception("Error in update callback %s", callback.__name__)

    def _invoke_bar_callbacks(self, bar: BarData, fills: list[Fill]) -> None:
        """Invoke all registered bar callbacks. Exceptions are logged and ignored."""
        for callback in self._on_bar_callbacks:
            try:
                callback(bar, fills)
            except Exception:
                logger.exception("Error in bar callback %s", callback.__name__)

    # endregion
