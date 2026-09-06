"""Bar sequence simulator for managing order lifecycle across multiple bars."""
import logging
from dataclasses import dataclass
from datetime import date, datetime, time as dtime, timedelta
from typing import Callable, Iterator, Literal, Optional

logger = logging.getLogger(__name__)

from xtrading_models import Order, Fill, BarData, Trade, OrderStatus, TradeLogEntry, TimeProvider, TradeStatus
from execEngine import ExecutionEngine, ExecutionConfig, order_active_at
from event_emitter import EventEmitter, SimulatorEvent

# IB rejects a market-on-close order that reaches it after the venue's cutoff
# (error 201). One cutoff is used for every symbol: NYSE and Nasdaq publish
# slightly different MOC/LOC deadlines and imbalance windows, and those
# differences are deliberately NOT modelled — a single conservative cutoff is
# enough to stop a late fill from silently acquiring an exit it could never have
# had. Revisit only if a strategy starts trading the 15:50-16:00 window.
MOC_CUTOFF = dtime(15, 50)


def gtd_expired(good_till_date: str, bar_time: datetime) -> bool:
    """Whether a GTD deadline has passed by `bar_time` (the bar's START).

    Two granularities, because IB accepts both and they mean different things:

    - ``'YYYYMMDD'`` — day granularity, the original behaviour. Valid through the
      whole of that day, expired on any later one. Unchanged so date-only callers
      (and daily-resolution backtests, where a bar IS a day) behave exactly as
      before.
    - ``'YYYYMMDD HH:MM:SS'``, optional timezone suffix — pinned to the instant.
      The first bar that *starts* at or after the deadline is refused, so an order
      good till 15:45 may still fill in the bar ending 15:45 and never after.
      This is what lets a strategy stop trading before the close rather than at
      it — the difference between an entry that can still be bracketed and one
      that fills at 15:59 with no exit that can reach the auction.

    The suffix is exchange-local, matching the bars, so it is dropped and the
    deadline read in `bar_time`'s own timezone — keeping both sides tz-aware, or
    both naive. Unparseable input never expires an order.
    """
    parts = good_till_date.split()
    clock = parts[1] if len(parts) > 1 and ':' in parts[1] else None
    try:
        if clock is None:
            return bar_time.date() > datetime.strptime(parts[0], '%Y%m%d').date()
        deadline = datetime.strptime(f'{parts[0]} {clock}', '%Y%m%d %H:%M:%S')
        return bar_time >= deadline.replace(tzinfo=bar_time.tzinfo)
    except ValueError:
        return False


@dataclass
class SimulatorConfig:
    """Configuration for Simulator behavior."""
    # Commission schedule — see ExecutionConfig for the formula and IB's tiers.
    # All zero means free trading, the behaviour every caller had before.
    commission_per_fill: float = 0.0
    commission_per_share: float = 0.0
    commission_minimum: float = 0.0
    commission_max_pct: float = 0.0
    fill_drift_model: Literal["none", "normal"] = "none"
    std_divider: int = 1000
    random_seed: Optional[int] = None
    # Span of one bar. Lets a goodAfterTime falling inside a bar activate on that
    # bar rather than the next one — which for the session's last bar means never.
    bar_duration: timedelta = timedelta(0)


class Simulator:
    """Manages order lifecycle across multiple bars using Trade objects.

    Wraps ExecutionEngine to provide:
    - Trade lifecycle management (submit, cancel, update)
    - TIF expiration (GTC, DAY, GTD)
    - Callback notifications (on_fill, on_cancel, on_status)

    Example:
        Simulator.static_init(time_provider, SimulatorConfig())
        sim = Simulator()
        sim.on_fill(lambda trade, fill: print(f"Filled: {fill.execution.price}"))
        trade = sim.submit_order(MarketOrder(action='BUY', totalQuantity=100))
        fills = sim.process_bar(bar)
    """

    _time_provider: TimeProvider
    _config: SimulatorConfig

    @classmethod
    def static_init(cls, time_provider: TimeProvider, config: SimulatorConfig) -> None:
        cls._time_provider = time_provider
        cls._config = config

    def __init__(self):
        self._engine = ExecutionEngine(
            ExecutionConfig(
                commission_per_fill=self._config.commission_per_fill,
                commission_per_share=self._config.commission_per_share,
                commission_minimum=self._config.commission_minimum,
                commission_max_pct=self._config.commission_max_pct,
                fill_drift_model=self._config.fill_drift_model,
                std_divider=self._config.std_divider,
                random_seed=self._config.random_seed,
                bar_duration=self._config.bar_duration)
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

        # An MOC that reaches the auction desk after the cutoff never reaches the
        # auction. What matters is when the order goes LIVE, not when it was
        # written down: an immediately-live MOC is judged by the clock now, and a
        # deferred one by the time of day its goodAfterTime names — a deferral to
        # 15:55 is just as late as a submission at 15:55, on whatever day it
        # lands. The case that prompted this is a bracket child created at the
        # instant its parent fills late in the session, which otherwise sits
        # inertly and expires with the day, leaving the position it was meant to
        # close with no exit at all.
        if self._moc_is_too_late(order, self._time_provider.now()):
            return self._reject_late_moc(order, self._time_provider.now())

        # MOC orders start as PreSubmitted: they can only fill at the next close bar,
        # so they must not be treated as a same-day DAY order until first processed.
        initial_status = TradeStatus.PreSubmitted if order.orderType == 'MOC' else TradeStatus.Submitted
        trade = Trade(
            order=order,
            orderStatus=OrderStatus(
                orderId=order.orderId,
                status=initial_status,
                remaining=order.totalQuantity,
            ),
            log=[TradeLogEntry(
                time=self._time_provider.now(),
                status=initial_status,
                message='Order submitted',
            )],
        )

        if order.ocaGroup:
            if order.ocaGroup not in self._oca_groups:
                self._oca_groups[order.ocaGroup] = set()
            self._oca_groups[order.ocaGroup].add(order.orderId)

        self._active_trades[order.orderId] = trade
        self._events.emit(SimulatorEvent.status, trade)
        return trade

    def _moc_activation_time(self, order: Order, becomes_live: datetime) -> dtime:
        """Time of day at which this MOC becomes live.

        Its goodAfterTime when it has one, otherwise `becomes_live` — the clock
        for a directly submitted order, and the bar's own timestamp for a bracket
        child (a child goes live on the bar its parent fills on, not when the
        parent was written).

        Only a time of day is returned, and for a goodAfterTime the target date
        is discarded on purpose: every session has the same cutoff, so an
        activation past it is late on whichever day it lands. Deferring to
        15:55 next Tuesday is refused for the same reason as 15:55 today — there
        is no date on which 15:55 reaches the auction. Carrying the date would
        only invite a comparison ("is it late *today*?") that has no bearing on
        the answer.

        Same parse as `order_active_at`: '%Y%m%d %H:%M:%S' with an optional
        timezone suffix, which is exchange-local and dropped.
        """
        if not order.goodAfterTime:
            return becomes_live.time()
        gat_str = order.goodAfterTime.rsplit(' ', 1)[0]
        return datetime.strptime(gat_str, '%Y%m%d %H:%M:%S').time()

    def _moc_is_too_late(self, order: Order, becomes_live: datetime) -> bool:
        return order.orderType == 'MOC' and self._moc_activation_time(order, becomes_live) >= MOC_CUTOFF

    def _reject_late_moc(self, order: Order, becomes_live: datetime) -> Trade:
        """Return a Cancelled trade for an MOC that would go live past MOC_CUTOFF.

        It never becomes active and — the part that matters — never joins its
        OCA group. A rejected order that registered there would be free to
        cancel the sibling exit that is still legitimately working.
        """
        activates = self._moc_activation_time(order, becomes_live)
        trade = Trade(
            order=order,
            orderStatus=OrderStatus(
                orderId=order.orderId,
                status=TradeStatus.Cancelled,
                remaining=order.totalQuantity,
            ),
            log=[TradeLogEntry(
                time=becomes_live,
                status=TradeStatus.Cancelled,
                message=f'MOC rejected: goes live {activates:%H:%M}, '
                        f'after the {MOC_CUTOFF:%H:%M} cutoff',
            )],
        )
        self._events.emit(SimulatorEvent.status, trade)
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
        """Modify an active order in place, re-arming it as if newly submitted.

        Supports updating: price, totalQuantity, trailingDistance, trailingPercent.
        After applying the fields, any *derived* per-order execution state is
        reset (see _reset_derived_state) so the order re-evaluates from the next
        bar — for a trailing stop this re-anchors the high-water mark to the
        current market, matching IB's reset-on-modify. The orderId, permId, OCA
        membership, and fills so far are preserved. A 'Order modified' log entry
        is appended so the change is auditable.

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

        self._reset_derived_state(order)
        trade.log.append(TradeLogEntry(
            time=self._time_provider.now(),
            status=trade.orderStatus.status,
            message='Order modified',
        ))
        self._events.emit(SimulatorEvent.status, trade)
        return True

    @staticmethod
    def _reset_derived_state(order: Order) -> None:
        """Clear order-type-specific accumulated execution state so a modified
        order re-evaluates from the next bar as if freshly submitted. Trailing
        stops track a high-water mark (extremePrice) and its derived stopPrice;
        clearing them forces _fill_trail to re-initialise from the current
        market. Non-trailing order types carry no such state, so this is a
        no-op for them."""
        if order.orderType in ('TRAIL', 'TRAIL LIMIT'):
            setattr(order, 'extremePrice', None)
            setattr(order, 'stopPrice', None)

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
        0. Activate PreSubmitted orders → Submitted (MOC orders queued after last bar)
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

        # 0. Activate PreSubmitted orders: transition to Submitted on first bar they see.
        #    This gives MOC orders a submission date of the bar day they first encounter,
        #    so DAY expiry is measured from that day rather than the evening they were queued.
        for trade in list(self._active_trades.values()):
            if trade.orderStatus.status == TradeStatus.PreSubmitted:
                trade.orderStatus.status = TradeStatus.Submitted
                trade.log.append(TradeLogEntry(
                    time=bar.date,
                    status=TradeStatus.Submitted,
                    message='Order submitted',
                ))
                self._events.emit(SimulatorEvent.status, trade)

        # 1. Expire GTD orders past goodTillDate
        self._expire_gtd_orders(bar.date)

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
            if not order_active_at(trade.order, bar.date, self._config.bar_duration):
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
                    self._events.emit(SimulatorEvent.fill, trade, fill)
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
                                status=TradeStatus.Cancelled,
                                remaining=0.0,
                            ),
                            log=[TradeLogEntry(
                                time=bar.date,
                                status=TradeStatus.Cancelled,
                                message=f'OCO: sibling filled on same bar',
                            )],
                        )
                        self._events.emit(SimulatorEvent.cancel, child_trade)
                        self._events.emit(SimulatorEvent.status, child_trade)
                        continue

                    cf = child_fills_by_id.get(child.orderId)
                    if cf:
                        child_trade = Trade(
                            order=child,
                            orderStatus=OrderStatus(
                                orderId=child.orderId,
                                status=TradeStatus.Filled,
                                remaining=0.0,
                            ),
                            log=[TradeLogEntry(
                                time=bar.date,
                                status=TradeStatus.Submitted,
                                message=f'Child of order {order_id}',
                            )],
                        )
                        self._update_trade_filled(child_trade, cf, bar.date)
                        all_fills.extend(cf)
                        for fill in cf:
                            self._events.emit(SimulatorEvent.fill, child_trade, fill)
                    else:
                        # Unfilled child — but if OCA sibling already filled, cancel
                        if child.ocaGroup and child.ocaGroup in oca_winner:
                            child_trade = Trade(
                                order=child,
                                orderStatus=OrderStatus(
                                    orderId=child.orderId,
                                    status=TradeStatus.Cancelled,
                                    remaining=0.0,
                                ),
                                log=[TradeLogEntry(
                                    time=bar.date,
                                    status=TradeStatus.Cancelled,
                                    message=f'OCO: sibling filled on same bar',
                                )],
                            )
                            self._events.emit(SimulatorEvent.cancel, child_trade)
                            self._events.emit(SimulatorEvent.status, child_trade)
                        elif self._moc_is_too_late(child, bar.date):
                            # A bracket child goes live on the bar its parent
                            # fills on. An MOC born after the cutoff missed the
                            # auction it exists for, so it is refused here rather
                            # than added — otherwise it lingers unfillable until
                            # DAY expiry and the position it was meant to close
                            # is left with no working exit and no trace of why.
                            child_trade = self._reject_late_moc(child, bar.date)
                            self._events.emit(SimulatorEvent.cancel, child_trade)
                        else:
                            child_trade = Trade(
                                order=child,
                                orderStatus=OrderStatus(
                                    orderId=child.orderId,
                                    status=TradeStatus.Submitted,
                                    remaining=child.totalQuantity,
                                ),
                                log=[TradeLogEntry(
                                    time=bar.date,
                                    status=TradeStatus.Submitted,
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
        self._events.emit(SimulatorEvent.bar, bar, all_fills)

        return all_fills

    def _update_trade_filled(self, trade: Trade, fills: list[Fill], time: datetime) -> None:
        """Update trade status to Filled with fill details."""
        total_filled = sum(f.execution.shares for f in fills)
        avg_price = sum(f.execution.shares * f.execution.price for f in fills) / total_filled if total_filled > 0 else 0.0

        trade.orderStatus.status = TradeStatus.Filled
        trade.orderStatus.filled = total_filled
        trade.orderStatus.remaining = 0.0
        trade.orderStatus.avgFillPrice = avg_price
        trade.orderStatus.lastFillPrice = fills[-1].execution.price if fills else 0.0
        trade.fills.extend(fills)
        trade.log.append(TradeLogEntry(
            time=time,
            status=TradeStatus.Filled,
            message=f'Filled {total_filled} @ {avg_price:.3f}',
        ))
        self._events.emit(SimulatorEvent.status, trade)

    def _distance_to_open(self, order: Order, bar: BarData) -> float:
        """Calculate distance from order's trigger price to bar.open.

        Used to determine OCO priority - order closest to open fills first.
        """
        if order.orderType == 'MKT':
            return 0.0
        price = order.price or bar.open
        return abs(price - bar.open)

    def _collect_cancel_subtree(self, order_id: int, trade: Trade, reason: str) -> list[Trade]:
        """Cancel a trade and all its children (state only, no events).

        Removes each trade from _active_trades, updates status and log, then
        recurses into children. Returns all affected Trade objects so the caller
        can emit events after the full cancel tree is resolved.
        """
        self._active_trades.pop(order_id, None)
        trade.orderStatus.status = TradeStatus.Cancelled
        trade.log.append(TradeLogEntry(
            time=self._time_provider.now(),
            status=TradeStatus.Cancelled,
            message=reason,
        ))
        result = [trade]
        for child in trade.order.children:
            if child.permId == 0:
                child.permId = child.orderId
            child_trade = self._active_trades.get(child.orderId)
            if child_trade is None:
                child_trade = Trade(
                    order=child,
                    orderStatus=OrderStatus(
                        orderId=child.orderId,
                        status=TradeStatus.Submitted,
                        remaining=child.totalQuantity,
                    ),
                    log=[],
                )
            result.extend(self._collect_cancel_subtree(
                child.orderId, child_trade, f'Parent order {order_id} cancelled - {reason}'
            ))
        return result

    def _cancel_trade(self, order_id: int, trade: Trade, reason: str) -> None:
        """Cancel a trade, its children, and all OCA siblings.

        This is the single cancellation path used by all cancel scenarios:
        user cancel, OCA sibling fill, DAY expiry, GTD expiry.

        OCA siblings are cancelled in two passes: all state mutations first,
        then all events. This ensures callbacks see a fully resolved group —
        new orders submitted into the same OCA group from within a callback
        are not caught by the already-completed cancellation loop.

        Args:
            order_id: ID of the order to cancel
            trade: The Trade object to cancel
            reason: Human-readable cancellation reason for log
        """
        cancelled = self._collect_cancel_subtree(order_id, trade, reason)
        for t in cancelled:
            self._events.emit(SimulatorEvent.cancel, t)
            self._events.emit(SimulatorEvent.status, t)

        # Cancel OCA siblings — two-pass so callbacks see a resolved group
        oca_group = trade.order.ocaGroup
        if oca_group:
            siblings = self._oca_groups.pop(oca_group, set())
            oca_cancelled: list[Trade] = []
            for sibling_id in list(siblings):
                if sibling_id != order_id and sibling_id in self._active_trades:
                    sibling_trade = self._active_trades[sibling_id]
                    oca_cancelled.extend(self._collect_cancel_subtree(
                        sibling_id, sibling_trade, f'OCA sibling {order_id} cancelled: {reason}'
                    ))
            for t in oca_cancelled:
                self._events.emit(SimulatorEvent.cancel, t)
                self._events.emit(SimulatorEvent.status, t)

    def _cancel_oca_siblings(self, filled_trade: Trade) -> None:
        """Cancel all other orders in the same OCA group after a fill.

        Two-pass: all state mutations first, then all events. This ensures
        callbacks see a fully resolved group — new orders submitted into the
        same OCA group from within a callback are not caught by the
        already-completed cancellation loop.
        """
        order = filled_trade.order
        if not order.ocaGroup:
            return
        siblings = self._oca_groups.pop(order.ocaGroup, set())
        oca_cancelled: list[Trade] = []
        for sibling_id in list(siblings):
            if sibling_id != order.orderId and sibling_id in self._active_trades:
                sibling_trade = self._active_trades[sibling_id]
                oca_cancelled.extend(self._collect_cancel_subtree(
                    sibling_id, sibling_trade, f'OCO: order {order.orderId} filled'
                ))
        for t in oca_cancelled:
            self._events.emit(SimulatorEvent.cancel, t)
            self._events.emit(SimulatorEvent.status, t)

    def process_bars(
        self,
        bars: list[BarData],
        yield_predicate: Callable[[BarData], bool] = lambda bar: True,
    ) -> Iterator[list[Fill]]:
        """Process a sequence of bars, accumulating fills and yielding when predicate fires.

        Args:
            bars: Iterable of BarData objects
            yield_predicate: Called after each bar; yields accumulated fills when True.
                             Defaults to firing every bar.

        Yields:
            Accumulated fills since the last yield
        """
        accumulated: list[Fill] = []
        for bar in bars:
            self._time_provider.set_time(bar.date)
            accumulated.extend(self.process_bar(bar))
            if yield_predicate(bar):
                yield accumulated
                accumulated = []

    def _expire_day_orders(self, current_date: date) -> None:
        """Expire DAY orders whose first Submitted log entry is from a prior day.

        Uses the first Submitted entry (not log[0]) so that MOC orders, which start
        as PreSubmitted and transition to Submitted on their first bar, are judged
        by the day they entered the market rather than the evening they were queued.

        Orders with goodAfterTime are not expired until that date has passed —
        they are dormant until then and only become a "live DAY order" on the
        goodAfterTime date.
        """
        trades_to_expire = []
        for order_id, trade in self._active_trades.items():
            order = trade.order
            if order.tif != 'DAY':
                continue
            if not any(
                e.status == TradeStatus.Submitted and e.time.date() < current_date
                for e in trade.log
            ):
                continue
            if order.goodAfterTime:
                gat_str = order.goodAfterTime.rsplit(' ', 1)[0]
                gat_date = datetime.strptime(gat_str, '%Y%m%d %H:%M:%S').date()
                if gat_date >= current_date:
                    continue
            trades_to_expire.append((order_id, trade))

        for order_id, trade in trades_to_expire:
            self._cancel_trade(order_id, trade, 'DAY order expired')

    def _expire_gtd_orders(self, bar_time: datetime) -> None:
        """Expire GTD orders whose goodTillDate has passed — see `gtd_expired`.

        Runs before matching, so an order that has just expired cannot fill on
        the bar that expired it.
        """
        trades_to_expire: list[tuple[int, Trade]] = []

        for order_id, trade in self._active_trades.items():
            order = trade.order
            if order.tif == 'GTD' and order.goodTillDate and gtd_expired(order.goodTillDate, bar_time):
                trades_to_expire.append((order_id, trade))

        for order_id, trade in trades_to_expire:
            self._cancel_trade(order_id, trade, 'GTD order expired')

    # endregion

    # region Callbacks

    def on_fill(self, callback: Callable[[Trade, Fill], None]) -> None:
        """Register a callback for fill events.

        Args:
            callback: Function called with (Trade, Fill) when order is filled
        """
        self._events.on(SimulatorEvent.fill, callback)

    def on_cancel(self, callback: Callable[[Trade], None]) -> None:
        """Register a callback for cancel events.

        Args:
            callback: Function called with Trade when order is cancelled.
                      Cancel reason is in trade.log[-1].message.
        """
        self._events.on(SimulatorEvent.cancel, callback)

    def on_status(self, callback: Callable[[Trade], None]) -> None:
        """Register a callback for any status change events.

        Args:
            callback: Function called with Trade on any status change
        """
        self._events.on(SimulatorEvent.status, callback)

    def on_bar(self, callback: Callable[[BarData, list[Fill]], None]) -> None:
        """Register a callback for bar processing events.

        Called after each bar is processed, similar to ib_insync's updateEvent.

        Args:
            callback: Function called with (BarData, list[Fill]) after each bar
        """
        self._events.on(SimulatorEvent.bar, callback)

    def off_bar(self, callback: Callable[[BarData, list[Fill]], None]) -> None:
        """Remove a previously registered bar callback."""
        self._events.off(SimulatorEvent.bar, callback)

    # endregion
