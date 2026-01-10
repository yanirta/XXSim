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

### Phase 2: Recursive Order Transformation 🔄 **IN PROGRESS**

**Goal:** Model order lifecycle transformations that mirror real-world exchange behavior.

#### 2.1 Recursive Execution Architecture ✅ **COMPLETE**

**Status:** Implemented and tested with comprehensive data-driven test suite.

**Implementation Approach:**
```python
class ExecutionEngine:
    def execute(self, order: Order, bar: BarData, parent_id: int = 0) -> ExecutionResult:
        """Recursively execute order and its children.
        
        Returns:
            ExecutionResult with:
            - fills: List of Fill objects (parent + children)
            - pending_orders: List of untriggered/unfilled orders
        """
        fill = self._execute_order(order, bar)
        
        if fill:
            # Propagate parent_id to fill
            fill.parentId = parent_id
            
            # Recursively execute children
            child_fills = []
            child_pending = []
            for child in order.children:
                child_result = self.execute(child, bar, parent_id=order.orderId)
                child_fills.extend(child_result.fills)
                child_pending.extend(child_result.pending_orders)
            
            return ExecutionResult(
                fills=[fill] + child_fills,
                pending_orders=child_pending
            )
        else:
            # Parent didn't trigger, return as pending
            return ExecutionResult(fills=[], pending_orders=[order])
```

**Key Changes from Phase 1:**
- **ExecutionResult** dataclass replaces single Fill return
- **parentId tracking**: Each fill knows its parent order
- **Automatic child execution**: Stop orders create and execute Market children, Stop-Limit creates Limit children
- **Pending order tracking**: Untriggered/unfilled orders returned separately

**Test Coverage:**
- ✅ **88 CSV-driven formation tests** in [`test_stop_limit.py`](test_stop_limit.py)
- ✅ Data loaded from [`test-data/stop-limit/`](test-data/stop-limit/) (8 CSV files × 11 formations)
- ✅ Each CSV documents expected "Stop Fill" and "Limit Fill" outcomes
- ✅ Tests validate: fill counts, prices, parentId relationships, pending orders
- ✅ Current status: **148/148 passing (100%)**

**Architecture Benefits:**
- ✅ **Composability**: Stop orders reuse Market logic, Stop-Limit reuses both
- ✅ **Real-world fidelity**: Mirrors exchange behavior (order transformation via children)
- ✅ **Debuggability**: parentId chain shows order lifecycle
- ✅ **Extensibility**: Easy to add bracket orders, OCO, etc.

**Data-Driven Testing Infrastructure:**
- CSV files define all 88 price formations exhaustively
- Charts visualize formations with TradingView-style candlesticks
- Test framework: `pytest` with parameterization
- Single master test function + CSV parsing = comprehensive coverage

---

#### 2.2 Trailing Stop Orders ⏳ **PLANNED**

**Design:** Stateless engine returns updated order state in `pending_orders` if not filled.

**Order Types:**
1. **TrailingStopMarket**: Trails market price, triggers Market order when stop hit
2. **TrailingStopLimit**: Trails market price, triggers Limit order at offset when stop hit

**Core Algorithm (Conservative Dual-Trigger Evaluation):**

```python
class TrailingStopMarket(Order):
    orderType: str = "TRAIL"
    trailAmount: Decimal  # Fixed dollar amount to trail
    currentStopPrice: Decimal = UNSET_DECIMAL  # Mutable state
    extremePrice: Decimal = UNSET_DECIMAL  # Tracks high (SELL) or low (BUY)

def _execute_order(order: TrailingStopMarket, bar: BarData) -> Optional[Fill]:
    # 1. Initialize on first bar
    if order.currentStopPrice == UNSET_DECIMAL:
        order.currentStopPrice = bar.open - order.trailAmount if order.action == "BUY" \
                                  else bar.open + order.trailAmount
        order.extremePrice = bar.open
    
    # Store old stop price before updating
    old_stop = order.currentStopPrice
    
    # 2. Calculate new extreme price from this bar
    new_extreme = bar.low if order.action == "BUY" else bar.high
    
    # 3. Update stop if extreme improved
    if order.action == "BUY":
        if new_extreme < order.extremePrice:  # Lower low = more favorable for BUY
            order.extremePrice = new_extreme
            new_stop = new_extreme - order.trailAmount
        else:
            new_stop = old_stop  # No change
    else:  # SELL
        if new_extreme > order.extremePrice:  # Higher high = more favorable for SELL
            order.extremePrice = new_extreme
            new_stop = new_extreme + order.trailAmount
        else:
            new_stop = old_stop  # No change
    
    # 4. Conservative trigger check: Did bar cross EITHER old_stop OR new_stop?
    # This handles intra-bar scenarios where:
    # - Price improves (new extreme) AND THEN reverses to hit new stop
    # - Price hits old stop BEFORE improving
    if order.action == "BUY":
        # Trigger if bar went high enough to hit either stop
        if bar.high >= old_stop or bar.high >= new_stop:
            trigger_price = min(old_stop, new_stop)  # Most conservative
            order.children = [MarketOrder(action=order.action, totalQuantity=order.totalQuantity)]
            # Recursive execution fills the Market child
            return _fill_at_price(order, bar, trigger_price)
    else:  # SELL
        # Trigger if bar went low enough to hit either stop
        if bar.low <= old_stop or bar.low <= new_stop:
            trigger_price = max(old_stop, new_stop)  # Most conservative
            order.children = [MarketOrder(action=order.action, totalQuantity=order.totalQuantity)]
            return _fill_at_price(order, bar, trigger_price)
    
    # 5. Not triggered - update state for next bar
    order.currentStopPrice = new_stop
    return None  # Returned in pending_orders by ExecutionResult

# Caller usage
trailing = TrailingStopMarket(action="SELL", totalQuantity=100, trailAmount=Decimal("5"))

for bar in bars:
    result = engine.execute(trailing, bar)
    
    if result.fills:
        print(f"Triggered at {result.fills[0].execution.price}")
        break
    
    # Order auto-updated, continue with same object
    # (pending_orders[0] contains updated state)
    trailing = result.pending_orders[0]
```

**TrailingStopLimit** (similar but creates Limit child):

```python
class TrailingStopLimit(Order):
    orderType: str = "TRAIL LMT"
    trailAmount: Decimal
    limitOffset: Decimal  # Distance from trigger to limit price
    currentStopPrice: Decimal = UNSET_DECIMAL
    extremePrice: Decimal = UNSET_DECIMAL

# When triggered, creates LimitOrder child:
if triggered:
    limit_price = trigger_price - order.limitOffset if order.action == "BUY" \
                  else trigger_price + order.limitOffset
    order.children = [LimitOrder(
        action=order.action,
        totalQuantity=order.totalQuantity,
        price=limit_price
    )]
    return _fill_at_price(order, bar, trigger_price)
```

**Key Design Decisions:**

1. **Stateless Engine**: Order carries mutable state (`currentStopPrice`, `extremePrice`), but engine remains pure function
2. **Dual-Trigger Check**: Evaluates both old and new stop prices conservatively
   - Handles edge case: extreme improves mid-bar, then reverses to hit new stop
   - Conservative: triggers if EITHER stop was hit
3. **Updated Orders in pending_orders**: Caller gets updated order back, continues loop
4. **Recursive Child Execution**: Leverages Phase 2.1 architecture (children array)
5. **Separate Order Types**: `TrailingStopMarket` vs `TrailingStopLimit` (not parent-child inheritance initially)

**Test Strategy:**
- Formation-based CSV tests (similar to stop-limit)
- Scenarios: trailing up (SELL), trailing down (BUY), reversal cases
- Dual-trigger validation: old_stop hit vs new_stop hit vs both
- Gap scenarios: bar gaps past both stops

---

#### 2.3 Execution Logging ⏳ **PLANNED**

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
