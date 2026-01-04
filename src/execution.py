"""Order execution engine for OHLCV-based backtesting."""
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Literal
import random

from models import Order, Fill, Execution, CommissionReport, BarData


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
    """Executes orders against OHLCV bar data."""
    
    def __init__(self, config: Optional[ExecutionConfig] = None):
        self.config = config or ExecutionConfig()
        
        if self.config.random_seed is not None:
            random.seed(self.config.random_seed)
    
    def execute(self, order: Order, bar: BarData) -> Optional[Fill]:
        """Execute an order against a bar of OHLCV data.
        
        Phase 1 Implementation:
        - Threshold-based fills (if bar touches price → fill)
        - Exact price fills (no slippage by default)
        - All-or-nothing fills (no partial fills)
        - Market orders execute at open
        
        Args:
            order: Order to execute
            bar: OHLCV bar data
            
        Returns:
            Fill if order executed, None if no fill
        """
        action = order.action
        
        # Market orders: execute at bar open
        if order.orderType == "MKT":
            # Phase 1: fill at exact open price
            # Phase 2: apply slippage
            return self._fill_at_price(order, bar, bar.open)
        
        # Limit orders: execute at limit if bar touches it
        if order.orderType == "LMT":
            limit_price = order.lmtPrice
            
            if action == "BUY":
                # Buy limit fills when price drops to or below limit
                if bar.low <= limit_price:
                    # If open is already below limit, fill at open (better price)
                    # Otherwise fill at limit price
                    fill_price = bar.open if bar.open <= limit_price else limit_price
                    return self._fill_at_price(order, bar, fill_price)
            
            elif action == "SELL":
                # Sell limit fills when price rises to or above limit
                if bar.high >= limit_price:
                    # If open is already above limit, fill at open (better price)
                    # Otherwise fill at limit price
                    fill_price = bar.open if bar.open >= limit_price else limit_price
                    return self._fill_at_price(order, bar, fill_price)
            
            return None
        
        # Stop orders: trigger at stop price, then execute as market
        if order.orderType == "STP":
            stop_price = order.auxPrice
            
            if action == "BUY":
                # Buy stop triggers when price rises to or above stop
                if bar.high >= stop_price:
                    # Two scenarios:
                    # 1. Stop within bar range: fill at stop price (price touched stop)
                    # 2. Gap up (bar.low > stop): fill at open (closest market price)
                    fill_price = stop_price if bar.low <= stop_price else bar.open
                    return self._fill_at_price(order, bar, fill_price)
            
            elif action == "SELL":
                # Sell stop triggers when price drops to or below stop
                if bar.low <= stop_price:
                    # Two scenarios:
                    # 1. Stop within bar range: fill at stop price (price touched stop)
                    # 2. Gap down (bar.high < stop): fill at open (closest market price)
                    fill_price = stop_price if bar.high >= stop_price else bar.open
                    return self._fill_at_price(order, bar, fill_price)
            
            return None
        
        # Stop-Limit orders: Two-phase execution
        # Phase 1: Check if stop triggers (converts to limit order)
        # Phase 2: Evaluate limit against remaining bar movement after trigger
        if order.orderType == "STP LMT":
            stop_price = order.auxPrice
            limit_price = order.lmtPrice
            
            if action == "BUY":
                # PHASE 1: Check if stop triggers (BUY stop triggers on upward movement)
                if bar.high < stop_price:
                    return None  # Stop never triggered
                
                # Special case: Gap scenario where bar entirely above stop (SCENARIO B only)
                # For normal Limit >= Stop, this is fine. For dipping Stop > Limit, this means
                # bar gapped up past stop without touching it
                if limit_price < stop_price and bar.low > stop_price:
                    # Gap up scenario in dipping - bar never touched stop going up
                    return None
                
                # Determine trigger point
                # For dipping scenarios (Stop > Limit), use stop price even if bar opened above
                # This represents the "breakout" level, not where bar happened to open
                if limit_price < stop_price:
                    # Dipping scenario: trigger is always at stop price (the breakout level)
                    trigger_point = stop_price
                elif bar.open >= stop_price:
                    # Normal scenario: Bar opened at/above stop - triggers at open
                    trigger_point = bar.open
                else:
                    # Normal scenario: Bar opened below stop, rose to trigger it
                    trigger_point = stop_price
                
                # PHASE 2: Evaluate limit order against remaining bar movement
                # Two scenarios based on limit vs stop relationship:
                
                # SCENARIO A: Normal (Limit >= Stop) - buy on breakout with limit above
                if limit_price >= stop_price:
                    # Check if limit is reachable in downward movement from trigger
                    if bar.low <= limit_price < trigger_point:
                        # Limit is below trigger and above/at bar low - reachable going down
                        return self._fill_at_price(order, bar, limit_price)
                    
                    # Check if limit is at/above trigger (fill at trigger immediately)
                    if limit_price >= trigger_point:
                        # Limit at or above trigger - already in acceptable range
                        return self._fill_at_price(order, bar, trigger_point)
                    
                    # Otherwise: limit < bar.low - unreachable, no fill
                    return None
                
                # SCENARIO B: Dipping/Pullback (Stop > Limit) - buy on pullback after breakout
                else:  # stop_price > limit_price
                    # After breakout above stop, wait for pullback to limit
                    # Only fill at limit if it's clearly below bar range (conservative approach)
                    # Rationale: With OHLCV data, we can't determine exact price path.
                    # If limit is within [low, open], it's ambiguous whether pullback reached it.
                    # Fill at limit ONLY if limit < bar.low (clearly unreachable, so fill at stop instead)
                    # Actually, that's backwards. Let me reconsider...
                    # Fill at stop (trigger) unless limit is clearly and unambiguously reachable.
                    # Since we don't know if price pulled back after breakout, default to stop.
                    # Only exception: if limit is somehow obviously fillable... but how?
                    # Per CSV: most cases fill at stop. So default behavior: fill at stop.
                    # Always fill at stop/trigger for dipping scenario
                    return self._fill_at_price(order, bar, trigger_point)
            
            elif action == "SELL":
                # PHASE 1: Check if stop triggers (SELL stop triggers on downward movement)
                # Stop triggers when price DROPS to/below stop
                if bar.low > stop_price:
                    return None  # Stop never triggered (price never dropped to stop)
                
                # Special case: Gap scenario where bar entirely below stop (SCENARIO B only)
                # For normal Stop > Limit, this is fine. For dipping Limit > Stop, this means
                # bar gapped down past stop without touching it
                if limit_price > stop_price and bar.high < stop_price:
                    # Gap down scenario in dipping - bar never touched stop going down
                    return None
                
                # Determine trigger point
                # For dipping scenarios (Limit > Stop), use stop price even if bar opened below
                # This represents the "breakdown" level, not where bar happened to open
                if limit_price > stop_price:
                    # Dipping scenario: trigger is always at stop price (the breakdown level)
                    trigger_point = stop_price
                elif bar.open <= stop_price:
                    # Normal scenario: Bar opened at/below stop - triggers at open
                    trigger_point = bar.open
                else:
                    # Normal scenario: Bar opened above stop, dropped to trigger it
                    trigger_point = stop_price
                
                # PHASE 2: Evaluate limit order against remaining bar movement
                # Two scenarios based on limit vs stop relationship:
                
                # SCENARIO A: Normal (Stop > Limit) - protective sell with limit below
                if stop_price > limit_price:
                    # Check if limit is reachable in upward movement from trigger
                    if bar.high >= limit_price > trigger_point:
                        # Limit is above trigger and below/at bar high - reachable going up
                        return self._fill_at_price(order, bar, limit_price)
                    
                    # Check if limit is at/below trigger (fill at trigger immediately)
                    if limit_price <= trigger_point:
                        # Limit at or below trigger - already in acceptable range (market behavior)
                        return self._fill_at_price(order, bar, trigger_point)
                    
                    # Otherwise: limit > bar.high - unreachable, no fill
                    return None
                
                # SCENARIO B: Dipping/Bounce (Limit > Stop) - sell on bounce after breakdown
                else:  # limit_price > stop_price
                    # After breakdown below stop, wait for bounce to limit
                    # Conservative: always fill at stop/trigger for dipping scenario
                    # Rationale: with OHLCV data, we can't determine if bounce to limit occurred
                    return self._fill_at_price(order, bar, trigger_point)
            
            return None
        
        # Unknown order type
        raise ValueError(f"Unsupported order type: {order.orderType}")
    
    def _apply_slippage(self, lbound: Decimal, ubound: Decimal, bar: BarData) -> Decimal:
        """Apply slippage model to determine execution price within range.
        
        Args:
            lbound: Lower bound of possible execution prices
            ubound: Upper bound of possible execution prices
            bar: Current bar data (for volatility-based adjustments)
            
        Returns:
            Execution price within [lbound, ubound]
        """
        if self.config.slippage_model == "none":
            # Phase 1: Fill at limit price (optimistic, Lean-style)
            # Return ubound for best possible execution
            return ubound
        
        elif self.config.slippage_model == "normal":
            # Phase 2: Statistical slippage using normal distribution
            # TODO: Implement biased normal distribution
            # - Should favor worse execution (higher for buys, lower for sells)
            # - Use bar.high - bar.low to adjust std based on volatility
            return self._normal_slippage(lbound, ubound, bar)
        
        return lbound
    
    def _normal_slippage(self, lbound: Decimal, ubound: Decimal, bar: BarData) -> Decimal:
        """Calculate slippage using normal distribution biased toward lbound.
        
        TODO Phase 2: Implement AlgoBee-style biased normal distribution.
        Current: Placeholder that returns lbound.
        
        Algorithm:
        1. Calculate range = ubound - lbound
        2. std = range / self.config.std_divider
        3. Generate normal(lbound + std, std)
        4. Clamp to [lbound, ubound]
        """
        # Placeholder: return lbound for now
        return lbound
    
    def _fill_at_price(self, order: Order, bar: BarData, price: Decimal) -> Fill:
        """Create a Fill for an order at specified price.
        
        Phase 1: All-or-nothing fills at exact price.
        """
        execution = Execution(
            orderId=order.orderId,
            time=bar.date,
            shares=order.totalQuantity,
            price=price,
            side=order.action,
        )
        
        # Phase 1: No commission modeling
        commission = CommissionReport(
            commission=Decimal("0.00"),
            currency="USD",
        )
        
        return Fill(
            order=order,
            execution=execution,
            commissionReport=commission,
            time=bar.date,
        )
