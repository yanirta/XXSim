"""Order execution engine for OHLCV-based backtesting."""
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Literal
import random

from xtrading_models import Order, Fill, Execution, CommissionReport, BarData, ExecutionResult
from xtrading_models.order import TrailingStopMarket


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

# region Phase 2.1: Recursive Execution with ExecutionResult

class ExecutionEngine:
    """Executes orders against OHLCV bar data with recursive parent-child support."""
    
    def execute(self, order: Order, bar: BarData, parent_id: int = 0) -> ExecutionResult:
        """Recursively execute order and its children.
        
        Args:
            order: Order to execute (may have children)
            bar: Bar data to execute against
            
        Returns:
            ExecutionResult with fills and pending orders
        """
        # 1. Try to fill immediate order
        execResult = self._try_fill_order(order, bar, parent_id)
        
        execResult = execResult if execResult is not None else ExecutionResult()
        
        # 2. If filled and has children, execute them with modified bar
        if len(execResult.fills) > 0 and order.children:
            # Create modified bar starting from fill price
            modified_bar = self._create_modified_bar(bar, execResult.fills[0].execution.price)
            
            for child in order.children:
                child_result = self.execute(child, modified_bar, parent_id=order.orderId)    
                execResult.fills.extend(child_result.fills)
                execResult.pending_orders.extend(child_result.pending_orders)
        
        # 3. If not filled, parent order becomes pending (children stay dormant)
        elif len(execResult.fills) == 0:
            execResult.pending_orders.append(order)
        
        return execResult
    
    def _try_fill_order(self, order: Order, bar: BarData, parent_id: int = 0) -> Optional[ExecutionResult]:
        """Fill single order based on type.
        
        Args:
            order: Order to fill
            bar: Bar data to execute against
            parent_id: Parent order ID (0 for parent orders)
            
        Returns:
            Fill if order executes, None otherwise
        """
        if order.orderType == 'MKT':
            return self._fill_market(order, bar, parent_id)
        elif order.orderType == 'LMT':
            return self._fill_limit(order, bar, parent_id)
        elif order.orderType.startswith('STP'):
            # Handles both 'STP' and 'STP LMT'
            return self._fill_stop(order, bar, parent_id)
        elif order.orderType == 'TRAIL':
            return self._fill_trail(order, bar, parent_id)
        elif order.orderType == 'TRAIL LMT':
            # Not implemented
            raise NotImplementedError("Trailing Stop Limit execution not implemented")
        return None
    
    def _create_modified_bar(self, original: BarData, new_open: Decimal) -> BarData:
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
    
    def _fill_market(self, order: Order, bar: BarData, parent_id: int = 0) -> Optional[ExecutionResult]:
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
            commission=Decimal("0.00"),
            currency="USD",
        )
        
        fill = Fill(
                order=order,
                execution=execution,
                commissionReport=commission,
                time=bar.date,
                parentId=parent_id)
            
        return ExecutionResult(fills=[fill])
    
    def _fill_limit(self, order: Order, bar: BarData, parent_id: int = 0) -> Optional[ExecutionResult]:
        """Fill limit order if price is reached."""
        limit_price = order.price
        
        if order.action == "BUY":
            # BUY limit: fill if bar goes at/below limit
            if bar.low <= limit_price:
                # Fill at limit if reached, or at open if open is better
                fill_price = limit_price if bar.open > limit_price else bar.open
            else:
                return None
        else:  # SELL
            # SELL limit: fill if bar goes at/above limit
            if bar.high >= limit_price:
                # Fill at limit if reached, or at open if open is better
                fill_price = limit_price if bar.open < limit_price else bar.open
            else:
                return None
        
        execution = Execution(
            orderId=order.orderId,
            time=bar.date,
            shares=order.totalQuantity,
            price=fill_price,
            side=order.action,
        )
        
        commission = CommissionReport(
            commission=Decimal("0.00"),
            currency="USD",
        )
        
        fill = Fill(
            order=order,
            execution=execution,
            commissionReport=commission,
            time=bar.date,
            parentId=parent_id,
        )

        return ExecutionResult(fills=[fill])
    
    def _fill_stop(self, order: Order, bar: BarData, parent_id: int = 0) -> Optional[ExecutionResult]:
        """Fill stop order if triggered - converts to market at trigger point."""
        stop_price = order.price
        
        if order.action == "BUY":
            # BUY stop: triggers when price goes at/above stop
            if bar.high >= stop_price:
                # Fill at stop if triggered after open, else at open
                fill_price = stop_price if bar.open < stop_price else bar.open
            else:
                return None
        else:  # SELL
            # SELL stop: triggers when price goes at/below stop
            if bar.low <= stop_price:
                # Fill at stop if triggered after open, else at open
                fill_price = stop_price if bar.open > stop_price else bar.open
            else:
                return None
        
        execution = Execution(
            orderId=order.orderId,
            time=bar.date,
            shares=order.totalQuantity,
            price=fill_price,
            side=order.action,
        )
        
        commission = CommissionReport(
            commission=Decimal("0.00"),
            currency="USD",
        )
        
        fill = Fill(
            order=order,
            execution=execution,
            commissionReport=commission,
            time=bar.date,
            parentId=parent_id,
        )

        return ExecutionResult(fills=[fill])
    
    def _fill_trail(self, order: TrailingStopMarket, bar: BarData, parent_id: int = 0) -> Optional[ExecutionResult]:
        """
        Stateless execution for TrailingStopMarket (BUY only).
        - Updates order.extremePrice and order.currentStopPrice in-place.
        - Returns (fills, pending_orders, updated_order)
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
                # Initialize on first fragment
                if order.stopPrice is None:
                    order.extremePrice = price
                    order.stopPrice = order.extremePrice + order.trailingDistance if order.trailingDistance is not None else \
                        order.extremePrice * (1 + order.trailingPercent / 100)  # type: ignore
                
                # Update extreme and stop prices on motion down
                if price <= order.extremePrice:  # type: ignore
                    order.extremePrice = price
                    order.stopPrice = order.extremePrice + order.trailingDistance if order.trailingDistance is not None else \
                        order.extremePrice * (1 + order.trailingPercent / 100)  # type: ignore
                # Check for trigger on motion up
                elif price >= order.stopPrice:
                    # Triggered
                    fill_price = order.stopPrice if prev_price is not None and prev_price < order.stopPrice else price
                    break

            elif order.action == 'SELL':
                # Initialize on first fragment
                if order.stopPrice is None:
                    order.extremePrice = price
                    order.stopPrice = order.extremePrice - order.trailingDistance if order.trailingDistance is not None else \
                        order.extremePrice * (1 - order.trailingPercent / 100)  # type: ignore
                # Update extreme and stop prices on motion up
                if price >= order.extremePrice:  # type: ignore
                    order.extremePrice = price
                    order.stopPrice = order.extremePrice - order.trailingDistance if order.trailingDistance is not None else \
                        order.extremePrice * (1 - order.trailingPercent / 100)  # type: ignore
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
                commission=Decimal("0.00"),
                currency="USD",
            )
            
            fill = Fill(
                order=order,
                execution=execution,
                commissionReport=commission,
                time=bar.date,
                parentId=parent_id,
            )
                
            return ExecutionResult(fills=[fill])  # No pending, no updated order
       
        # ---  Not triggered empty result, original order will be attached as pending in the caller ---
        return ExecutionResult()

# endregion
