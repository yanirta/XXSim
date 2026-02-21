"""Order execution engine for OHLCV-based backtesting."""
from dataclasses import dataclass
from typing import Optional, Literal

from xtrading_models import Order, Fill, Execution, CommissionReport, BarData
from xtrading_models.order import StopOrder, StopLimitOrder, TrailingStopMarket


@dataclass
class ExecutionConfig:
    """Configuration for execution engine behavior."""

    # Resolution strategy for ambiguous orders (multiple orders in same bar)
    ambiguity_strategy: Literal["skip", "execute_all", "postpone", "randomize"] = "skip"

    # Slippage model: deterministic (exact fill at limit) or statistical (normal distribution)
    slippage_model: Literal["none", "normal"] = "none"

    # Standard deviation divider for normal distribution slippage
    # Price range / std_divider = std for normal distribution
    # Higher values = less slippage variance
    std_divider: int = 1000

    # Random seed for reproducible statistical slippage
    random_seed: Optional[int] = None


class ExecutionEngine:
    """Executes orders against OHLCV bar data with recursive parent-child support."""

    def execute(self, order: Order, bar: BarData, parent_id: int = 0) -> list[Fill]:
        """Recursively execute order and its children.

        Args:
            order: Order to execute (may have children)
            bar: Bar data to execute against
            parent_id: Parent order ID (0 for top-level orders)

        Returns:
            List of fills (empty if order didn't execute)
        """
        fills = self._try_fill_order(order, bar, parent_id) or []

        if fills and order.children:
            modified_bar = self._create_modified_bar(bar, fills[0].execution.price)
            for child in order.children:
                child_fills = self.execute(child, modified_bar, parent_id=order.orderId)
                fills.extend(child_fills)

        return fills

    def _try_fill_order(self, order: Order, bar: BarData, parent_id: int = 0) -> Optional[list[Fill]]:
        """Fill single order based on type.

        Args:
            order: Order to fill
            bar: Bar data to execute against
            parent_id: Parent order ID (0 for parent orders)

        Returns:
            List of fills if order executes, None otherwise
        """
        if order.orderType == 'MKT':
            return self._fill_market(order, bar, parent_id)
        elif order.orderType == 'LMT':
            return self._fill_limit(order, bar, parent_id)
        elif order.orderType == 'STP':
            return self._fill_stop(order, bar, parent_id)  # type: ignore[arg-type]
        elif order.orderType == 'STP LMT':
            return self._fill_stop_limit(order, bar, parent_id)  # type: ignore[arg-type]
        elif order.orderType == 'TRAIL':
            return self._fill_trail(order, bar, parent_id)  # type: ignore[arg-type]
        elif order.orderType == 'TRAIL LIMIT':
            raise NotImplementedError("Trailing Stop Limit execution not implemented")
        return None

    def _create_modified_bar(self, original: BarData, new_open: float) -> BarData:
        """Create modified bar with adjusted open price (aggressive approach).

        Only open is modified - we don't know if bar extremes happened before/after trigger.

        Args:
            original: Original bar data
            new_open: New open price (typically the fill price)

        Returns:
            New BarData with modified open
        """
        return BarData(
            date=original.date,
            open=new_open,
            high=max(new_open, original.high),
            low=min(new_open, original.low),
            close=original.close,
            volume=original.volume
        )

    def _fill_market(self, order: Order, bar: BarData, parent_id: int = 0) -> Optional[list[Fill]]:
        """Fill market order at open price."""
        fill_price = bar.open

        execution = Execution(
            orderId=order.orderId,
            time=bar.date,
            shares=order.totalQuantity,
            price=fill_price,
            side=order.action,
        )

        commission = CommissionReport(
            commission=0.0,
            currency="USD",
        )

        fill = Fill(
                order=order,
                execution=execution,
                commissionReport=commission,
                time=bar.date,
                parentId=parent_id)

        return [fill]

    def _evaluate_limit_price(self, action: str, limit_price: float, bar: BarData) -> Optional[float]:
        """Evaluate if a limit price would fill against a bar.

        Returns fill price if limit is reached, None otherwise.
        """
        if action == "BUY":
            if bar.low <= limit_price:
                return limit_price if bar.open > limit_price else bar.open
            return None
        else:  # SELL
            if bar.high >= limit_price:
                return limit_price if bar.open < limit_price else bar.open
            return None

    def _fill_limit(self, order: Order, bar: BarData, parent_id: int = 0) -> Optional[list[Fill]]:
        """Fill limit order if price is reached."""
        fill_price = self._evaluate_limit_price(order.action, order.price, bar)
        if fill_price is None:
            return None

        execution = Execution(
            orderId=order.orderId,
            time=bar.date,
            shares=order.totalQuantity,
            price=fill_price,
            side=order.action,
        )

        commission = CommissionReport(
            commission=0.0,
            currency="USD",
        )

        fill = Fill(
            order=order,
            execution=execution,
            commissionReport=commission,
            time=bar.date,
            parentId=parent_id,
        )

        return [fill]

    def _fill_stop(self, order: StopOrder, bar: BarData, parent_id: int = 0) -> Optional[list[Fill]]:
        """Fill stop order if triggered - fills at trigger point."""
        stop_price = order.price

        if order.action == "BUY":
            # BUY stop: triggers when price goes at/above stop
            if bar.high >= stop_price:
                fill_price = stop_price if bar.open < stop_price else bar.open
            else:
                return None
        else:  # SELL
            # SELL stop: triggers when price goes at/below stop
            if bar.low <= stop_price:
                fill_price = stop_price if bar.open > stop_price else bar.open
            else:
                return None

        order.triggered = True
        order.triggerPrice = fill_price

        execution = Execution(
            orderId=order.orderId,
            time=bar.date,
            shares=order.totalQuantity,
            price=fill_price,
            side=order.action,
        )

        commission = CommissionReport(
            commission=0.0,
            currency="USD",
        )

        fill = Fill(
            order=order,
            execution=execution,
            commissionReport=commission,
            time=bar.date,
            parentId=parent_id,
        )

        return [fill]

    def _fill_stop_limit(self, order: StopLimitOrder, bar: BarData, parent_id: int = 0) -> Optional[list[Fill]]:
        """Fill stop-limit order: stop triggers internally, then evaluates as limit.

        When stop is not yet triggered:
        - Check if stop price is hit
        - If hit: set triggered=True, create modified bar, evaluate limit
        - If limit fills: return 1 fill at limit price
        - If limit doesn't fill: return empty list (order stays pending with triggered=True)

        When already triggered (from a previous bar):
        - Evaluate limit against full bar
        """
        if not order.triggered:
            # Check stop trigger
            stop_price = order.price
            if order.action == "BUY":
                if bar.high < stop_price:
                    return None  # Stop not triggered
                trigger_price = stop_price if bar.open < stop_price else bar.open
            else:  # SELL
                if bar.low > stop_price:
                    return None  # Stop not triggered
                trigger_price = stop_price if bar.open > stop_price else bar.open

            order.triggered = True
            order.triggerPrice = trigger_price
            eval_bar = self._create_modified_bar(bar, trigger_price)
        else:
            eval_bar = bar

        # Evaluate limit price
        fill_price = self._evaluate_limit_price(order.action, order.limitPrice, eval_bar)
        if fill_price is None:
            return []  # Triggered but limit not filled; order stays pending

        execution = Execution(
            orderId=order.orderId,
            time=bar.date,
            shares=order.totalQuantity,
            price=fill_price,
            side=order.action,
        )

        commission = CommissionReport(
            commission=0.0,
            currency="USD",
        )

        fill = Fill(
            order=order,
            execution=execution,
            commissionReport=commission,
            time=bar.date,
            parentId=parent_id,
        )

        return [fill]

    def _fill_trail(self, order: TrailingStopMarket, bar: BarData, parent_id: int = 0) -> Optional[list[Fill]]:
        """
        Stateless execution for TrailingStopMarket (BUY only).
        - Updates order.extremePrice and order.currentStopPrice in-place.
        """
        # Note: Bullish bar flow assumption: prev_extremePrice [optional] -> open -> low -> high -> close
        #       Bearish bar flow assumption: prev_extremePrice [optional] -> open -> high -> low -> close

        fragments = []
        if bar.close > bar.open:
            fragments = [bar.open, bar.low, bar.high, bar.close]
        else:
            fragments = [bar.open, bar.high, bar.low, bar.close]

        fill_price = None
        prev_price = None
        # Evaluate each fragment in order for trigger
        for price in fragments:
            if order.action == 'BUY':
                # Update extreme and stop prices on motion down or initialization
                if order.stopPrice is None or price <= order.extremePrice:  # type: ignore
                    order.extremePrice = price
                    order.stopPrice = order.extremePrice + order.trailingDistance if order.trailingDistance is not None else \
                        order.extremePrice + order.trailingPercent / 100  # type: ignore
                # Check for trigger on motion up
                elif price >= order.stopPrice:
                    # Triggered
                    fill_price = order.stopPrice if prev_price is not None and prev_price < order.stopPrice else price
                    break

            elif order.action == 'SELL':
                # Update extreme and stop prices on motion up or initialization
                if order.stopPrice is None or price >= order.extremePrice:  # type: ignore
                    order.extremePrice = price
                    order.stopPrice = order.extremePrice - order.trailingDistance if order.trailingDistance is not None else \
                        order.extremePrice - order.trailingPercent / 100  # type: ignore
                # Check for trigger on motion down
                elif price <= order.stopPrice:
                    # Triggered
                    fill_price = order.stopPrice if prev_price is not None and prev_price > order.stopPrice else price
                    break

            else:
                raise ValueError(f"Unsupported action for TrailingStopMarket: {order.action}")

            prev_price = price

        if fill_price is not None:
            execution = Execution(
                orderId=order.orderId,
                time=bar.date,
                shares=order.totalQuantity,
                price=fill_price,
                side=order.action,
            )

            commission = CommissionReport(
                commission=0.0,
                currency="USD",
            )

            fill = Fill(
                order=order,
                execution=execution,
                commissionReport=commission,
                time=bar.date,
                parentId=parent_id,
            )

            return [fill]

        return None
