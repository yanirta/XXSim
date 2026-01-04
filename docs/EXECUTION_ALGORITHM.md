# XSim Execution Algorithm

## Overview

XSim simulates order execution using OHLCV bar data. The core challenge: **reconstructing realistic fills from sparse price information** (Open, High, Low, Close, Volume).

**The Problem:** OHLCV bars reveal which prices were reached but not the exact sequence or timing of price movements. This creates execution ambiguity that must be resolved algorithmically.

---

## Development Phases

### Phase 1: Deterministic Single-Bar Execution ✅ **COMPLETE**

**Goal:** Implement all standard order types with deterministic, conservative fill logic.

**Achievements:**
- ✅ **Market Orders**: Fill at bar.open
- ✅ **Limit Orders**: Fill when bar touches limit price
  - BUY: fills if `bar.low <= limit`, at `min(bar.open, limit)`
  - SELL: fills if `bar.high >= limit`, at `max(bar.open, limit)`
- ✅ **Stop Orders**: Convert to market when stop triggers
  - BUY: triggers if `bar.high >= stop`
  - SELL: triggers if `bar.low <= stop`
- ✅ **Stop-Limit Orders**: Two-phase execution (stop trigger → limit evaluation)
  - **88 formation tests** covering all geometric relationships between bar OHLC and stop/limit prices
  - Normal scenarios: `Limit > Stop` (BUY), `Stop > Limit` (SELL)
  - Dipping/pullback scenarios: `Stop > Limit` (BUY), `Limit > Stop` (SELL)

**Design Principles:**
- **Conservative fills**: When uncertain, bias toward realistic execution (e.g., fill at trigger point for dipping scenarios)
- **Deterministic**: No randomness, reproducible results
- **Single-bar scope**: Each order evaluated independently per bar
- **Gap handling**: Detect when bar gaps past order prices (no gradual movement through trigger zone)

**Test Coverage:** 114 tests validating all order types and price formation scenarios.

---

### Phase 2: Recursive Order Transformation 🔄 **PLANNED**

**Goal:** Model order lifecycle transformations that mirror real-world exchange behavior.

#### 2.1 Recursive Execution Architecture

**Current Approach (Phase 1):**
```python
# Stop-Limit implemented as single monolithic function
def execute_stop_limit(order, bar):
    # Combined logic: trigger check + limit evaluation
    if stop_triggered:
        if limit_reachable:
            return fill
```

**Phase 2 Approach:**
```python
# Orders transform into other orders when triggered
def execute(order, bar, state=None):
    if isinstance(order, StopLimitOrder):
        # Check if stop triggers
        if stop_condition_met(order, bar):
            # Transform into LimitOrder
            limit_order = LimitOrder(
                action=order.action,
                lmtPrice=order.lmtPrice,
                totalQuantity=order.totalQuantity
            )
            # Recursively execute the transformed order
            return execute(limit_order, bar, state)
        return None, state
    
    elif isinstance(order, LimitOrder):
        # Execute limit logic
        ...
```

**Benefits:**
- Mirrors real exchange behavior (stop-limit → limit transition)
- Cleaner separation of concerns (each order type handles its own logic)
- Easier to add new order types (compose from existing primitives)
- Natural state propagation for multi-bar orders

#### 2.2 Execution Logging

**Goal:** Provide visibility into execution decisions for debugging and analysis.

**Implementation:**
```python
import logging

logger = logging.getLogger("xsim.execution")

def execute(order, bar, state=None):
    logger.debug(f"Evaluating {order.orderType} order {order.orderId} against bar {bar.date}")
    
    if isinstance(order, StopLimitOrder):
        if stop_condition_met(order, bar):
            logger.info(f"Stop triggered at {trigger_point} for order {order.orderId}")
            # Transform to limit order
            limit_order = LimitOrder(...)
            return execute(limit_order, bar, state)
        else:
            logger.debug(f"Stop not triggered (stop={order.stopPrice}, bar.high={bar.high})")
            return None, state
```

**Features:**
- **DEBUG level**: Every order evaluation, bar-by-bar details
- **INFO level**: Trigger events, fills, state transitions
- **WARNING level**: Gap scenarios, ambiguous situations
- **Structured output**: JSON-compatible for analysis tools
- **Performance impact**: Minimal overhead, opt-in via logging config

**Use Cases:**
- Debug why an order didn't fill as expected
- Analyze execution quality across backtests
- Generate execution reports for strategy validation
- Audit trail for regulatory compliance

#### 2.3 Trailing Stop Orders

**Implementation with caller-managed state:**
```python
class TrailingStopState:
    current_stop: Decimal
    extreme_price: Decimal  # Highest for SELL, lowest for BUY

def execute_trailing_stop(order, bar, prev_state=None):
    # Initialize or update state
    state = prev_state or initialize_state(order, bar)
    
    # Update trailing stop based on favorable price movement
    if favorable_movement(bar, state):
        state.current_stop = calculate_new_stop(bar, order.trailAmount)
    
    # Check if stop triggered
    if stop_triggered(bar, state.current_stop):
        # Transform to market order
        market_order = MarketOrder(action=order.action, ...)
        return execute(market_order, bar), None  # State=None (order complete)
    
    return None, state  # Continue to next bar

# Caller manages lifecycle
state = None
for bar in bars:
    fill, state = engine.execute(trailing_order, bar, state)
    if fill:
        break
```

**Features:**
- **Fixed amount trailing**: `stop = market_price ± trailAmount`
- **Percentage trailing**: `stop = market_price × (1 ± trailPercent/100)`
- **Conservative updates**: Trail only on confirmed bar extremes (high/low), check trigger before updating
- **Stateless engine**: Caller owns state, passes it each bar

**Signature:**
```python
def execute(order, bar, prev_state=None) -> Tuple[Optional[Fill], Optional[OrderState]]:
    """
    Returns:
        (fill, new_state) where:
        - fill=None, state=X: Order still active, continue next bar
        - fill=X, state=None: Order filled/cancelled, lifecycle complete
    """
```

---

### Phase 3: Advanced Execution Features 📋 **FUTURE**

#### Planning Items
- **Order orchestration**: Bracket orders (OCO), parent-child relationships
- **Time-in-force**: GTC (Good-Till-Cancelled), FOK (Fill-or-Kill), IOC (Immediate-or-Cancel)
- **Special execution**: Market-on-Close (MOC), Limit-on-Close (LOC)
- **Volume constraints**: Partial fills based on bar.volume
- **Multi-leg strategies**: Spread orders, ratio orders

#### Slippage Modeling

**Conservative approach (deterministic):**
```python
class SlippageModel:
    def apply(self, intended_price, bar, quantity):
        # Fixed percentage
        slippage = intended_price * 0.001  # 0.1% slippage
        return intended_price + slippage
```

**Statistical approach (realistic):**
```python
class StatisticalSlippage:
    def apply(self, intended_price, bar, quantity):
        spread = bar.high - bar.low
        std = spread / 1000
        # Normal distribution around intended price
        return random.normalvariate(intended_price, std)
```

**Volume-based approach:**
```python
class VolumeSlippage:
    def apply(self, intended_price, bar, quantity):
        # More slippage for larger orders relative to volume
        impact = (quantity / bar.volume) * spread
        return intended_price + impact
```

---

## Undecided

### Formalization & Release

**Questions:**
- What level of API stability to guarantee?
- Package structure: single package vs. modular components?
- Documentation scope: API reference, tutorials, research methodology?
- Release cadence: semantic versioning, breaking changes policy?
- Community engagement: open-source governance, contribution guidelines?

**Considerations:**
- XSim as **research tool** vs. **production library**
- Target audience: quantitative researchers, algo traders, students?
- Integration points: pandas, backtrader, zipline compatibility?
- Performance requirements: vectorized execution, JIT compilation?

---

## Design Philosophy

**Conservative over optimistic:** When uncertain about intra-bar price path, bias toward realistic (less favorable) fills rather than perfect execution.

**Deterministic by default:** Reproducibility is critical for backtesting. Statistical models are opt-in.

**Caller controls lifecycle:** Engine stays stateless (pure function per bar). Caller manages order state across bars.

**Test-driven precision:** Every execution scenario documented in formations.md and validated with comprehensive tests.

**Incremental complexity:** Phase 1 (simple deterministic) → Phase 2 (stateful multi-bar) → Phase 3 (advanced features). Each phase builds on proven foundation.
