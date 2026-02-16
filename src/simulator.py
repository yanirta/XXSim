"""Bar sequence simulator for managing order lifecycle across multiple bars."""
import logging
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Callable, Optional

logger = logging.getLogger(__name__)

from xtrading_models import Order, Fill, BarData, Trade, OrderStatus, TradeLogEntry
from execEngine import ExecutionEngine


@dataclass
class SimulatorConfig:
    """Configuration for Simulator behavior."""
    pass  # Reserved for future configuration options


class Simulator:
    """Manages order lifecycle across multiple bars using Trade objects.

    Wraps ExecutionEngine to provide:
    - Trade lifecycle management (submit, cancel, update)
    - TIF expiration (GTC, DAY, GTD)
    - Callback notifications (on_fill, on_cancel, on_status)

    Example:
        sim = Simulator()
        sim.on_fill(lambda trade, fill: print(f"Filled: {fill.execution.price}"))
        trade = sim.submit_order(MarketOrder(action='BUY', totalQuantity=100))
        fills = sim.process_bar(bar)
    """

    def __init__(self, config: Optional[SimulatorConfig] = None):
        self._config = config or SimulatorConfig()
        self._engine = ExecutionEngine()
        self._active_trades: dict[int, Trade] = {}
        self._oca_groups: dict[str, set[int]] = {}  # ocaGroup -> {orderId, ...}
        self._last_bar_date: Optional[date] = None

        # Callbacks
        self._on_fill_callbacks: list[Callable[[Trade, Fill], None]] = []
        self._on_cancel_callbacks: list[Callable[[Trade], None]] = []
        self._on_status_callbacks: list[Callable[[Trade], None]] = []
        self._on_bar_callbacks: list[Callable[[BarData, list[Fill]], None]] = []

    # region Order Management

    def submit_order(self, order: Order) -> Trade:
        """Submit an order to the simulator.

        Creates a Trade wrapping the order with Submitted status.

        Args:
            order: Order to submit. Set order.ocaGroup to link orders in an
                   OCA group (one-cancels-all).

        Returns:
            The Trade object wrapping this order
        """
        trade = Trade(
            order=order,
            orderStatus=OrderStatus(
                orderId=order.orderId,
                status='Submitted',
                remaining=Decimal(str(order.totalQuantity)),
            ),
            log=[TradeLogEntry(
                time=datetime.now(),
                status='Submitted',
                message='Order submitted',
            )],
        )

        if order.ocaGroup:
            if order.ocaGroup not in self._oca_groups:
                self._oca_groups[order.ocaGroup] = set()
            self._oca_groups[order.ocaGroup].add(order.orderId)

        self._active_trades[order.orderId] = trade
        self._invoke_status_callbacks(trade)
        return trade

    def cancel_order(self, order_id: int) -> bool:
        """Cancel an active order.

        Args:
            order_id: ID of order to cancel

        Returns:
            True if order was found and cancelled, False otherwise
        """
        trade = self._active_trades.pop(order_id, None)
        if trade is not None:
            trade.orderStatus.status = 'Cancelled'
            trade.log.append(TradeLogEntry(
                time=datetime.now(),
                status='Cancelled',
                message='User cancelled',
            ))
            self._invoke_cancel_callbacks(trade)
            self._invoke_status_callbacks(trade)
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
        trade = self._active_trades.get(order_id)
        if trade is None:
            return False

        order = trade.order
        allowed_fields = {'price', 'totalQuantity', 'trailingDistance', 'trailingPercent'}
        for key, value in kwargs.items():
            if key in allowed_fields and hasattr(order, key):
                setattr(order, key, value)

        self._invoke_status_callbacks(trade)
        return True

    # endregion

    # region Queries

    def get_trade(self, order_id: int) -> Optional[Trade]:
        """Get an active trade by order ID.

        Args:
            order_id: ID of order to retrieve

        Returns:
            Trade if found, None otherwise
        """
        return self._active_trades.get(order_id)

    def get_active_trades(self) -> list[Trade]:
        """Get all active trades.

        Returns:
            List of all active trades
        """
        return list(self._active_trades.values())

    # endregion

    # region Bar Processing

    def process_bar(self, bar: BarData) -> list[Fill]:
        """Process a bar against all active orders.

        Algorithm:
        1. Expire DAY orders if date changed
        2. Expire GTD orders past goodTillDate
        3. Sort orders by distance to bar.open (for OCO priority)
        4. For each active trade (skipping OCO-cancelled, skipping GAT not yet active):
           a. Execute order via ExecutionEngine
           b. If filled: update trade status, cancel OCO siblings, invoke on_fill,
              submit unfilled bracket children as new trades
           c. If not filled: keep (state already mutated in-place by engine)
        5. Return all fills

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

        # 3. Sort trades by distance to open price for OCO priority
        trades_to_process = sorted(
            self._active_trades.items(),
            key=lambda x: self._distance_to_open(x[1].order, bar)
        )

        # 4. Process each active trade
        all_fills: list[Fill] = []
        trades_to_add: list[Trade] = []

        for order_id, trade in trades_to_process:
            # Skip if already cancelled by OCO sibling
            if order_id not in self._active_trades:
                continue

            # Skip if goodAfterTime not yet reached
            if not self._is_order_active(trade.order, bar.date):
                continue

            fills = self._engine.execute(trade.order, bar)

            if fills:
                self._active_trades.pop(order_id, None)
                self._update_trade_filled(trade, fills, bar.date)
                all_fills.extend(fills)
                for fill in fills:
                    self._invoke_fill_callbacks(trade, fill)
                self._cancel_oca_siblings(trade)
                # Submit unfilled bracket children as new trades
                filled_order_ids = {f.execution.orderId for f in fills}
                for child in trade.order.children:
                    if child.orderId not in filled_order_ids:
                        child_trade = Trade(
                            order=child,
                            orderStatus=OrderStatus(
                                orderId=child.orderId,
                                status='Submitted',
                                remaining=Decimal(child.totalQuantity),
                            ),
                            log=[TradeLogEntry(
                                time=bar.date,
                                status='Submitted',
                                message=f'Child of order {order_id}',
                            )],
                        )
                        trades_to_add.append(child_trade)

            # else: PENDING — keep trade (state already mutated in-place by engine)

        # Apply additions
        for child_trade in trades_to_add:
            self._active_trades[child_trade.order.orderId] = child_trade

        # Invoke on_bar callbacks
        self._invoke_bar_callbacks(bar, all_fills)

        return all_fills

    def _update_trade_filled(self, trade: Trade, fills: list[Fill], time: datetime) -> None:
        """Update trade status to Filled with fill details."""
        total_filled = Decimal(sum(f.execution.shares for f in fills))
        avg_price = sum(Decimal(str(f.execution.shares)) * f.execution.price for f in fills) / total_filled if total_filled > 0 else Decimal('0')

        trade.orderStatus.status = 'Filled'
        trade.orderStatus.filled = Decimal(str(total_filled))
        trade.orderStatus.remaining = Decimal('0')
        trade.orderStatus.avgFillPrice = avg_price
        trade.orderStatus.lastFillPrice = fills[-1].execution.price if fills else Decimal('0')
        trade.fills.extend(fills)
        trade.log.append(TradeLogEntry(
            time=time,
            status='Filled',
            message=f'Filled {total_filled} @ {avg_price}',
        ))
        self._invoke_status_callbacks(trade)

    def _distance_to_open(self, order: Order, bar: BarData) -> Decimal:
        """Calculate distance from order's trigger price to bar.open.

        Used to determine OCO priority - order closest to open fills first.
        """
        if order.orderType == 'MKT':
            return Decimal('0')
        price = order.price or bar.open
        return abs(price - bar.open)

    def _is_order_active(self, order: Order, bar_time: datetime) -> bool:
        """Check if order is active based on goodAfterTime."""
        if not order.goodAfterTime:
            return True
        try:
            gat = datetime.strptime(order.goodAfterTime, '%Y%m%d %H:%M:%S')
            return bar_time >= gat
        except ValueError:
            try:
                gat = datetime.strptime(order.goodAfterTime, '%Y%m%d')
                bar_date = bar_time.date() if isinstance(bar_time, datetime) else bar_time
                return bar_date >= gat.date()
            except ValueError:
                return True

    def _cancel_oca_siblings(self, filled_trade: Trade) -> None:
        """Cancel all other orders in the same OCA group."""
        order = filled_trade.order
        if not order.ocaGroup:
            return
        siblings = self._oca_groups.get(order.ocaGroup, set())
        for sibling_id in list(siblings):
            if sibling_id != order.orderId and sibling_id in self._active_trades:
                sibling_trade = self._active_trades.pop(sibling_id)
                sibling_trade.orderStatus.status = 'Cancelled'
                sibling_trade.log.append(TradeLogEntry(
                    time=datetime.now(),
                    status='Cancelled',
                    message=f'OCO: order {order.orderId} filled',
                ))
                self._invoke_cancel_callbacks(sibling_trade)
                self._invoke_status_callbacks(sibling_trade)
        # Clean up the group
        self._oca_groups.pop(order.ocaGroup, None)

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
        trades_to_expire = [
            (order_id, trade)
            for order_id, trade in self._active_trades.items()
            if trade.order.tif == 'DAY'
        ]

        for order_id, trade in trades_to_expire:
            self._active_trades.pop(order_id)
            trade.orderStatus.status = 'Cancelled'
            trade.log.append(TradeLogEntry(
                time=datetime.now(),
                status='Cancelled',
                message='DAY order expired',
            ))
            self._invoke_cancel_callbacks(trade)
            self._invoke_status_callbacks(trade)

    def _expire_gtd_orders(self, current_date: date) -> None:
        """Expire GTD orders past their goodTillDate."""
        trades_to_expire: list[tuple[int, Trade]] = []

        for order_id, trade in self._active_trades.items():
            order = trade.order
            if order.tif == 'GTD' and order.goodTillDate:
                try:
                    gtd = datetime.strptime(order.goodTillDate, '%Y%m%d').date()
                    if current_date > gtd:
                        trades_to_expire.append((order_id, trade))
                except ValueError:
                    pass

        for order_id, trade in trades_to_expire:
            self._active_trades.pop(order_id)
            trade.orderStatus.status = 'Cancelled'
            trade.log.append(TradeLogEntry(
                time=datetime.now(),
                status='Cancelled',
                message='GTD order expired',
            ))
            self._invoke_cancel_callbacks(trade)
            self._invoke_status_callbacks(trade)

    # endregion

    # region Callbacks

    def on_fill(self, callback: Callable[[Trade, Fill], None]) -> None:
        """Register a callback for fill events.

        Args:
            callback: Function called with (Trade, Fill) when order is filled
        """
        self._on_fill_callbacks.append(callback)

    def on_cancel(self, callback: Callable[[Trade], None]) -> None:
        """Register a callback for cancel events.

        Args:
            callback: Function called with Trade when order is cancelled.
                      Cancel reason is in trade.log[-1].message.
        """
        self._on_cancel_callbacks.append(callback)

    def on_status(self, callback: Callable[[Trade], None]) -> None:
        """Register a callback for any status change events.

        Args:
            callback: Function called with Trade on any status change
        """
        self._on_status_callbacks.append(callback)

    def on_bar(self, callback: Callable[[BarData, list[Fill]], None]) -> None:
        """Register a callback for bar processing events.

        Called after each bar is processed, similar to ib_insync's updateEvent.

        Args:
            callback: Function called with (BarData, list[Fill]) after each bar
        """
        self._on_bar_callbacks.append(callback)

    def _invoke_fill_callbacks(self, trade: Trade, fill: Fill) -> None:
        """Invoke all registered fill callbacks."""
        for callback in self._on_fill_callbacks:
            try:
                callback(trade, fill)
            except Exception:
                logger.exception("Error in fill callback %s", callback.__name__)

    def _invoke_cancel_callbacks(self, trade: Trade) -> None:
        """Invoke all registered cancel callbacks."""
        for callback in self._on_cancel_callbacks:
            try:
                callback(trade)
            except Exception:
                logger.exception("Error in cancel callback %s", callback.__name__)

    def _invoke_status_callbacks(self, trade: Trade) -> None:
        """Invoke all registered status callbacks."""
        for callback in self._on_status_callbacks:
            try:
                callback(trade)
            except Exception:
                logger.exception("Error in status callback %s", callback.__name__)

    def _invoke_bar_callbacks(self, bar: BarData, fills: list[Fill]) -> None:
        """Invoke all registered bar callbacks."""
        for callback in self._on_bar_callbacks:
            try:
                callback(bar, fills)
            except Exception:
                logger.exception("Error in bar callback %s", callback.__name__)

    # endregion
