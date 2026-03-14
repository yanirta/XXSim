"""Bar sequence simulator for managing order lifecycle across multiple bars."""
import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import Callable, Literal, Optional

logger = logging.getLogger(__name__)

from xtrading_models import Order, Fill, BarData, Trade, OrderStatus, TradeLogEntry, TimeProvider
from execEngine import ExecutionEngine, ExecutionConfig
from event_emitter import EventEmitter


@dataclass
class SimulatorConfig:
    """Configuration for Simulator behavior."""
    commission_per_fill: float = 0.0
    fill_drift_model: Literal["none", "normal"] = "none"
    std_divider: int = 1000
    random_seed: Optional[int] = None


class Simulator:
    """Manages order lifecycle across multiple bars using Trade objects.

    Wraps ExecutionEngine to provide:
    - Trade lifecycle management (submit, cancel, update)
    - TIF expiration (GTC, DAY, GTD)
    - Callback notifications (on_fill, on_cancel, on_status)

    Example:
        sim = Simulator(time_provider)
        sim.on_fill(lambda trade, fill: print(f"Filled: {fill.execution.price}"))
        trade = sim.submit_order(MarketOrder(action='BUY', totalQuantity=100))
        fills = sim.process_bar(bar)
    """

    def __init__(self, time_provider: TimeProvider, config: Optional[SimulatorConfig] = None):
        self._time_provider = time_provider
        self._config = config or SimulatorConfig()
        self._engine = ExecutionEngine(
            ExecutionConfig(
                commission_per_fill=self._config.commission_per_fill,
                fill_drift_model=self._config.fill_drift_model,
                std_divider=self._config.std_divider,
                random_seed=self._config.random_seed)
            )
        self._active_trades: dict[int, Trade] = {}
        self._oca_groups: dict[str, set[int]] = {}  # ocaGroup -> {orderId, ...}
        self._last_bar_date: Optional[date] = None

        self._events = EventEmitter()

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
        # In simulation, permId mirrors orderId (in live IB assigns it)
        if order.permId == 0:
            order.permId = order.orderId

        trade = Trade(
            order=order,
            orderStatus=OrderStatus(
                orderId=order.orderId,
                status='Submitted',
                remaining=order.totalQuantity,
            ),
            log=[TradeLogEntry(
                time=self._time_provider.now(),
                status='Submitted',
                message='Order submitted',
            )],
        )

        if order.ocaGroup:
            if order.ocaGroup not in self._oca_groups:
                self._oca_groups[order.ocaGroup] = set()
            self._oca_groups[order.ocaGroup].add(order.orderId)

        self._active_trades[order.orderId] = trade
        self._events.emit('status', trade)
        return trade

    def cancel_order(self, order_id: int) -> bool:
        """Cancel an active order.

        Args:
            order_id: ID of order to cancel

        Returns:
            True if order was found and cancelled, False otherwise
        """
        trade = self._active_trades.get(order_id)
        if trade is not None:
            self._cancel_trade(order_id, trade, 'User cancelled')
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

        self._events.emit('status', trade)
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
        1. Expire GTD orders past goodTillDate
        2. Expire DAY orders if date changed (before matching — DAY orders
           must not survive into the next trading day)
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
        date_changed = self._last_bar_date is not None and current_date != self._last_bar_date

        # 1. Expire GTD orders past goodTillDate
        self._expire_gtd_orders(current_date)

        # 2. Expire DAY orders before matching on date change
        #    Only expire orders submitted on a prior day — orders submitted
        #    today (during execute() before exec bars run) must not be cancelled.
        if date_changed:
            self._expire_day_orders(current_date)

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
                # Separate parent fills from child fills
                parent_fills = [f for f in fills if f.execution.orderId == order_id]
                child_fills = [f for f in fills if f.execution.orderId != order_id]

                self._active_trades.pop(order_id, None)
                self._update_trade_filled(trade, parent_fills, bar.date)
                all_fills.extend(parent_fills)
                for fill in parent_fills:
                    self._events.emit('fill', trade, fill)
                self._cancel_oca_siblings(trade)

                # Create trades for children (filled or unfilled)
                # Apply OCA: if one child filled, cancel siblings in same group
                child_fills_by_id = {}
                for f in child_fills:
                    child_fills_by_id.setdefault(f.execution.orderId, []).append(f)

                # Pre-compute which OCA groups have a child fill
                # Pick the first filled child per group (closest to open)
                oca_winner: dict[str, int] = {}  # ocaGroup -> winning orderId
                for child in trade.order.children:
                    if child.ocaGroup and child.orderId in child_fills_by_id:
                        if child.ocaGroup not in oca_winner:
                            oca_winner[child.ocaGroup] = child.orderId

                for child in trade.order.children:
                    if child.permId == 0:
                        child.permId = child.orderId

                    # Cancel if OCA sibling is the winner (not this child)
                    if child.ocaGroup and child.ocaGroup in oca_winner and oca_winner[child.ocaGroup] != child.orderId:
                        child_trade = Trade(
                            order=child,
                            orderStatus=OrderStatus(
                                orderId=child.orderId,
                                status='Cancelled',
                                remaining=0.0,
                            ),
                            log=[TradeLogEntry(
                                time=bar.date,
                                status='Cancelled',
                                message=f'OCO: sibling filled on same bar',
                            )],
                        )
                        self._events.emit('cancel', child_trade)
                        self._events.emit('status', child_trade)
                        continue

                    cf = child_fills_by_id.get(child.orderId)
                    if cf:
                        child_trade = Trade(
                            order=child,
                            orderStatus=OrderStatus(
                                orderId=child.orderId,
                                status='Filled',
                                remaining=0.0,
                            ),
                            log=[TradeLogEntry(
                                time=bar.date,
                                status='Submitted',
                                message=f'Child of order {order_id}',
                            )],
                        )
                        self._update_trade_filled(child_trade, cf, bar.date)
                        all_fills.extend(cf)
                        for fill in cf:
                            self._events.emit('fill', child_trade, fill)
                    else:
                        # Unfilled child — but if OCA sibling already filled, cancel
                        if child.ocaGroup and child.ocaGroup in oca_winner:
                            child_trade = Trade(
                                order=child,
                                orderStatus=OrderStatus(
                                    orderId=child.orderId,
                                    status='Cancelled',
                                    remaining=0.0,
                                ),
                                log=[TradeLogEntry(
                                    time=bar.date,
                                    status='Cancelled',
                                    message=f'OCO: sibling filled on same bar',
                                )],
                            )
                            self._events.emit('cancel', child_trade)
                            self._events.emit('status', child_trade)
                        else:
                            child_trade = Trade(
                                order=child,
                                orderStatus=OrderStatus(
                                    orderId=child.orderId,
                                    status='Submitted',
                                    remaining=child.totalQuantity,
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
            if child_trade.order.ocaGroup:
                if child_trade.order.ocaGroup not in self._oca_groups:
                    self._oca_groups[child_trade.order.ocaGroup] = set()
                self._oca_groups[child_trade.order.ocaGroup].add(child_trade.order.orderId)

        # Invoke on_bar callbacks
        self._events.emit('bar', bar, all_fills)

        return all_fills

    def _update_trade_filled(self, trade: Trade, fills: list[Fill], time: datetime) -> None:
        """Update trade status to Filled with fill details."""
        total_filled = sum(f.execution.shares for f in fills)
        avg_price = sum(f.execution.shares * f.execution.price for f in fills) / total_filled if total_filled > 0 else 0.0

        trade.orderStatus.status = 'Filled'
        trade.orderStatus.filled = total_filled
        trade.orderStatus.remaining = 0.0
        trade.orderStatus.avgFillPrice = avg_price
        trade.orderStatus.lastFillPrice = fills[-1].execution.price if fills else 0.0
        trade.fills.extend(fills)
        trade.log.append(TradeLogEntry(
            time=time,
            status='Filled',
            message=f'Filled {total_filled} @ {avg_price:.3f}',
        ))
        self._events.emit('status', trade)

    def _distance_to_open(self, order: Order, bar: BarData) -> float:
        """Calculate distance from order's trigger price to bar.open.

        Used to determine OCO priority - order closest to open fills first.
        """
        if order.orderType == 'MKT':
            return 0.0
        price = order.price or bar.open
        return abs(price - bar.open)

    def _is_order_active(self, order: Order, bar_time: datetime) -> bool:
        """Check if order is active based on goodAfterTime."""
        if not order.goodAfterTime:
            return True
        # Normalize to naive for comparison — GAT strings have no tz semantics in sim
        naive_bar_time = bar_time.replace(tzinfo=None) if bar_time.tzinfo else bar_time
        try:
            gat = datetime.strptime(order.goodAfterTime, '%Y%m%d %H:%M:%S')
            return naive_bar_time >= gat
        except ValueError:
            pass
        # Strip timezone suffix (e.g. 'US/Eastern') and retry datetime format
        gat_str = order.goodAfterTime.rsplit(' ', 1)[0]
        try:
            gat = datetime.strptime(gat_str, '%Y%m%d %H:%M:%S')
            return naive_bar_time >= gat
        except ValueError:
            pass
        try:
            gat = datetime.strptime(order.goodAfterTime, '%Y%m%d')
            bar_date = naive_bar_time.date() if isinstance(naive_bar_time, datetime) else naive_bar_time
            return bar_date >= gat.date()
        except ValueError:
            return True

    def _cancel_trade(self, order_id: int, trade: Trade, reason: str) -> None:
        """Cancel a trade and its OCA siblings and unsubmitted children.

        This is the single cancellation path used by all cancel scenarios:
        user cancel, OCA sibling fill, DAY expiry, GTD expiry.

        Args:
            order_id: ID of the order to cancel
            trade: The Trade object to cancel
            reason: Human-readable cancellation reason for log
        """
        self._active_trades.pop(order_id, None)
        trade.orderStatus.status = 'Cancelled'
        trade.log.append(TradeLogEntry(
            time=self._time_provider.now(),
            status='Cancelled',
            message=reason,
        ))
        self._events.emit('cancel', trade)
        self._events.emit('status', trade)

        # Cancel children — recurse for active ones, create ephemeral Trade for unsubmitted
        for child in trade.order.children:
            if child.permId == 0:
                child.permId = child.orderId
            child_trade = self._active_trades.get(child.orderId)
            if child_trade is None:
                child_trade = Trade(
                    order=child,
                    orderStatus=OrderStatus(
                        orderId=child.orderId,
                        status='Submitted',
                        remaining=child.totalQuantity,
                    ),
                    log=[],
                )
            self._cancel_trade(child.orderId, child_trade, f'Parent order {order_id} cancelled - {reason}')


        # Cancel OCA siblings
        oca_group = trade.order.ocaGroup
        if oca_group:
            siblings = self._oca_groups.get(oca_group, set())
            for sibling_id in list(siblings):
                if sibling_id != order_id and sibling_id in self._active_trades:
                    sibling_trade = self._active_trades.pop(sibling_id)
                    sibling_trade.orderStatus.status = 'Cancelled'
                    sibling_trade.log.append(TradeLogEntry(
                        time=self._time_provider.now(),
                        status='Cancelled',
                        message=f'OCA sibling {order_id} cancelled: {reason}',
                    ))
                    self._events.emit('cancel', sibling_trade)
                    self._events.emit('status', sibling_trade)
            self._oca_groups.pop(oca_group, None)

    def _cancel_oca_siblings(self, filled_trade: Trade) -> None:
        """Cancel all other orders in the same OCA group after a fill."""
        order = filled_trade.order
        if not order.ocaGroup:
            return
        siblings = self._oca_groups.get(order.ocaGroup, set())
        for sibling_id in list(siblings):
            if sibling_id != order.orderId and sibling_id in self._active_trades:
                sibling_trade = self._active_trades[sibling_id]
                self._cancel_trade(sibling_id, sibling_trade, f'OCO: order {order.orderId} filled')
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

    def _expire_day_orders(self, current_date: date) -> None:
        """Expire DAY orders submitted on a prior trading day.

        Orders submitted today (e.g. during execute() before exec bars run)
        are not expired — only orders left over from a previous day.
        """
        trades_to_expire = [
            (order_id, trade)
            for order_id, trade in self._active_trades.items()
            if trade.order.tif == 'DAY'
            and trade.log
            and trade.log[0].time.date() < current_date
        ]

        for order_id, trade in trades_to_expire:
            self._cancel_trade(order_id, trade, 'DAY order expired')

    def _expire_gtd_orders(self, current_date: date) -> None:
        """Expire GTD orders past their goodTillDate."""
        trades_to_expire: list[tuple[int, Trade]] = []

        for order_id, trade in self._active_trades.items():
            order = trade.order
            if order.tif == 'GTD' and order.goodTillDate:
                try:
                    gtd = datetime.strptime(order.goodTillDate[:8], '%Y%m%d').date()
                    if current_date > gtd:
                        trades_to_expire.append((order_id, trade))
                except ValueError:
                    pass

        for order_id, trade in trades_to_expire:
            self._cancel_trade(order_id, trade, 'GTD order expired')

    # endregion

    # region Callbacks

    def on_fill(self, callback: Callable[[Trade, Fill], None]) -> None:
        """Register a callback for fill events.

        Args:
            callback: Function called with (Trade, Fill) when order is filled
        """
        self._events.on('fill', callback)

    def on_cancel(self, callback: Callable[[Trade], None]) -> None:
        """Register a callback for cancel events.

        Args:
            callback: Function called with Trade when order is cancelled.
                      Cancel reason is in trade.log[-1].message.
        """
        self._events.on('cancel', callback)

    def on_status(self, callback: Callable[[Trade], None]) -> None:
        """Register a callback for any status change events.

        Args:
            callback: Function called with Trade on any status change
        """
        self._events.on('status', callback)

    def on_bar(self, callback: Callable[[BarData, list[Fill]], None]) -> None:
        """Register a callback for bar processing events.

        Called after each bar is processed, similar to ib_insync's updateEvent.

        Args:
            callback: Function called with (BarData, list[Fill]) after each bar
        """
        self._events.on('bar', callback)

    # endregion
