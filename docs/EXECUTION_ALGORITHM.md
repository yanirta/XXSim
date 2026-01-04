# XSim Execution Algorithm Design

## Overview

This document outlines the design decisions and implementation strategy for XSim's order execution engine. The core challenge: **determining realistic order fills from OHLCV bar data**.

## The Fundamental Problem

Given a bar with Open, High, Low, Close, we know:
- Price moved from Open to some point during the period
- It reached High and Low at some point
- It ended at Close

**What we DON'T know:**
- The exact sequence of price movements (Did it go High→Low or Low→High?)
- The exact time within the bar when prices were reached
- Whether multiple orders at different prices should all fill

This creates **execution ambiguity** that must be resolved algorithmically.

---

## Industry Approaches Analysis

### 1. QuantConnect Lean (Conservative)

**Philosophy**: Simple threshold-based execution with optimistic fills.

**Execution Logic**:
```csharp
// Buy Limit Example
if (bar.Low < order.LimitPrice) {
    fill.Price = order.LimitPrice;  // Instant fill at limit
    fill.Quantity = order.Quantity;
}
```

**Characteristics**:
- ✅ Simple, fast, deterministic
- ✅ Production-grade validation (exchange hours, stale prices)
- ✅ Handles complex order types (StopLimit in 2 phases)
- ❌ Optimistic: assumes instant fill at exact limit price
- ❌ No slippage modeling
- ❌ No intra-bar price path reconstruction

**Key Insight**: Lean targets **institutional users** who want conservative estimates. If bar touched your price, you got filled at that price.

### 2. AlgoBee (Statistical)

**Philosophy**: Model execution uncertainty with statistical pricing.

**Execution Logic**:
```python
def _lbound_biased_price(self, lbound, ubound):
    d = ubound - lbound
    std = d / self.std_divider  # e.g., 1000
    # Normal distribution biased toward lower bound
    price = lbound + (random.normalvariate(lbound + std, std) - lbound) % d
    return price
```

**Characteristics**:
- ✅ Models slippage and realistic execution
- ✅ Configurable ambiguity resolution (skip/execute/postpone/randomize)
- ✅ Accounts for candle color (red/green) in price path
- ✅ Better for backtesting realistic P&L
- ❌ More complex
- ❌ Non-deterministic (requires seeding for reproducibility)

**Key Insight**: AlgoBee targets **retail backtesting** where realistic fills (including slippage) matter more than optimistic estimates.

---

## The Ambiguity Problem

### Example Scenario

Bar: `Open=150, High=152, Low=148, Close=149`

Pending Orders:
1. Buy Limit @ $151 (wants to buy if price drops to 151)
2. Sell Stop @ $149 (wants to sell if price drops to 149)

**Question**: Both prices were touched. Which order executes first?

### Possible Price Paths

**Path A**: 150 → 152 (high) → 148 (low) → 149  
- Buy limit fills at 151 on the way up
- Sell stop fills at 149 on the way down
- **Both fill**

**Path B**: 150 → 148 (low) → 152 (high) → 149  
- Sell stop fills at 149 on the way down
- Buy limit is now cancelled (parent-child relationship)
- **Only sell fills**

### Resolution Strategies

| Strategy | Lean | AlgoBee | XSim (Proposed) |
|----------|------|---------|-----------------|
| **Optimistic** | Fills both | - | ❌ Not realistic |
| **Skip** | - | Abort ambiguous orders | ✅ Phase 1 option |
| **Execute All** | ✅ Default | Optional | ❌ Too optimistic |
| **Postpone** | - | Defer to next bar | ✅ Phase 2 option |
| **Randomize** | - | Probabilistic split | ✅ Phase 3 (advanced) |

---

## XSim Implementation Phases

### Phase 1: MVP (Lean-style with explicit ambiguity handling)

**Goal**: Working execution engine with simple, deterministic logic.

**Approach**:
- Threshold-based fills (if bar touches price → fill)
- **Ambiguity**: Skip/abort orders when unclear
- Exact price fills (no slippage)
- Support: Market, Limit, Stop, StopLimit

**Test Strategy**:
```python
def test_buy_limit_fills_when_low_touches():
    bar = BarData(low=Decimal("149"), high=Decimal("151"))
    order = LimitOrder('BUY', 100, Decimal("150"))
    
    fill = execute(order, bar)
    
    assert fill.execution.price == Decimal("150")  # Exact fill
    assert fill.execution.shares == 100
```

### Phase 2: Statistical Pricing

**Goal**: Add realistic slippage and execution modeling.

**Approach**:
- Implement `_biased_price(lbound, ubound, distribution)` 
- Normal distribution biased toward "worse" execution
- Configurable std deviation (volatility-based)

**Example**:
```python
# Buy limit at $150, bar goes to $148
# Instead of filling at exactly $150, model realistic fill:
fill_price = biased_price(
    lbound=Decimal("148"),  # Bar low
    ubound=Decimal("150"),  # Order limit
    bias="lower_bound",     # Favor worse price for buyer
    std_factor=1000
)
# Might fill at $149.23 instead of exactly $150
```

### Phase 3: Advanced Ambiguity Resolution

**Goal**: Handle complex scenarios with multiple orders.

**Approach**:
- Candle color analysis (red/green affects price path probability)
- Order sorting by price level
- Configurable ambiguity solver:
  - `postpone`: Move ambiguous orders to next bar
  - `randomize`: Probabilistic execution based on price proximity

**AlgoBee Pattern**:
```python
def split_children(order, bar):
    # After parent fills, determine which children can execute
    # in same bar vs. need to wait
    if parent_price_creates_ambiguity(order, bar):
        return curr_bar=[], next_bar=[child], ambiguous=[child]
```

---

## Data Constraints

### What We Have (Standard OHLCV)
- `BarData`: Open, High, Low, Close, Volume, Average (VWAP), BarCount
- Timestamp (bar period)

### What We DON'T Have
- Bid/Ask spread
- Individual tick data
- Exact price path within the bar

**Important**: Lean's bid/ask logic is for **QuoteBar** (premium data with separate bid/ask OHLCV). XSim works with standard **TradeBar** (single OHLCV) only.

---

## Design Decisions

### 1. Price Selection for Fills

**Decision**: Use bar range (High/Low) to determine if fill occurred, then model execution price statistically.

**Rationale**:
- No bid/ask data available in standard OHLCV
- More realistic than assuming instant fill at limit
- Configurable realism (Phase 1: exact, Phase 2: statistical)

### 2. Execution Timestamp

**Decision**: All fills within a bar get the bar's close timestamp.

**Rationale**:
- Cannot determine exact sub-bar timing
- Conservative approach (latest possible time)
- Matches data granularity

### 3. Partial Fills

**Decision**: Phase 1 - all or nothing. Phase 2+ - volume-based partial fills.

**Rationale**:
- Volume data available (`BarData.volume`)
- Can estimate if bar's volume sufficient for order size
- More realistic for large orders

---

## Stop-Limit Two-Phase Execution

### Core Concept

Stop-limit orders execute in **two distinct phases**:

**Phase 1 - Stop Trigger**: 
- Monitor if bar reaches stop price
- Once triggered, order converts to a limit order

**Phase 2 - Limit Execution**:
- Evaluate limit order against **remaining bar movement** after stop triggered
- Bar is "adjusted" - it has already moved from open to the stop trigger point

### BUY Stop-Limit Execution Logic

**Constraint**: `Limit > Stop`
**Bullish bar**: `Close > Open`

**Algorithm**:
```python
# PHASE 1: Check if stop triggers
if bar.high < stop_price:
    return None  # Stop never triggered

# Determine trigger point
if bar.open >= stop_price:
    trigger_point = bar.open  # Bar opened at/above stop
else:
    trigger_point = stop_price  # Bar rose to stop

# PHASE 2: Evaluate limit against remaining bar movement

# Can reach limit going DOWN from trigger?
if bar.low <= limit_price < trigger_point:
    return fill_at_price(order, bar, limit_price)

# Is limit at/above trigger? (already acceptable)
if limit_price >= trigger_point:
    return fill_at_price(order, bar, trigger_point)

# Limit below bar.low - unreachable
return None
```

### SELL Stop-Limit Execution Logic

**Constraint**: `Stop > Limit`
**Bearish bar**: `Open > Close`

**Algorithm**:
```python
# PHASE 1: Check if stop triggers
if bar.low > stop_price:
    return None  # Stop never triggered

# Determine trigger point
if bar.open <= stop_price:
    trigger_point = bar.open  # Bar opened at/below stop
else:
    trigger_point = stop_price  # Bar fell to stop

# PHASE 2: Evaluate limit against remaining bar movement
# For SELL: limit is FLOOR (minimum acceptable price)

# Can reach limit going UP from trigger?
if bar.high >= limit_price > trigger_point:
    return fill_at_price(order, bar, limit_price)

# Is limit at/below trigger? (already acceptable)
if limit_price <= trigger_point:
    return fill_at_price(order, bar, trigger_point)

# Limit above bar.high - unreachable
return None
```

**Key Insights**:
- After stop triggers, order becomes limit order evaluated against **remaining bar movement**
- **BUY**: Limit is ceiling (max price), evaluated going DOWN from trigger
- **SELL**: Limit is floor (min price), evaluated going UP from trigger
- When limit already acceptable at trigger → fill at trigger (market behavior)
- When limit reachable in remaining range → fill at limit
- When limit unreachable → no fill

### BUY Stop-Limit Formations (Two-Phase Analysis)

**Reference bar (bullish)**: `open=148, high=152, low=146, close=150, volume=1M`
**Constraint**: `Limit > Stop`

| # | Formation | Stop | Limit | Fill | Explanation |
|---|-----------|------|-------|------|-------------|
| **F1** | Limit > Stop > High > Close > Open > Low | 153 | 154 | **None** | Stop > high → never triggers |
| **F2** | Limit > High > Stop > Close > Open > Low | 151 | 152 | **151** | Triggers at stop, limit ≥ trigger → fill at trigger |
| **F3** | Limit > High > Close > Stop > Open > Low | 149 | 150 | **149** | Triggers at stop, limit ≥ trigger → fill at trigger |
| **F4** | Limit > High > Close > Open > Stop > Low | 148 | 150 | **148** | Opens at stop, limit ≥ trigger → fill at trigger |
| **F5** | Limit > High > Close > Open > Low > Stop | 148 | 149 | **148** | Opens above stop, limit ≥ trigger → fill at trigger |
| **F6** | High > Limit > Close > Open > Low > Stop | 147 | 148 | **148** | Opens above stop, limit = trigger → fill at trigger |
| **F7** | High > Close > Limit > Open > Low > Stop | 146 | 148 | **148** | Opens at stop, limit = trigger → fill at trigger |
| **F8** | High > Close > Open > Limit > Low > Stop | 146 | 147 | **147** | Opens above stop, limit reachable on pullback → fill at limit |
| **F9** | High > Close > Open > Low > Limit > Stop | 145 | 145.5 | **None** | Limit < bar.low → unreachable |
| **F10** | High > Limit > Close > Open > Stop > Low | 148 | 148.5 | **148** | Opens at stop, limit ≥ trigger → fill at trigger |
| **F11** | High > Close > Limit > Stop > Open > Low | 148.5 | 149 | **148.5** | Triggers at stop, limit ≥ trigger → fill at trigger |

**Pattern Summary**:
- **No trigger** (F1): `stop > bar.high`
- **Fill at trigger** (F2-F7, F10-F11): `limit ≥ trigger` → immediate fill (market behavior)
- **Fill at limit** (F8): `bar.low ≤ limit < trigger` → reachable on pullback
- **No fill** (F9): `limit < bar.low` → unreachable

### SELL Stop-Limit Formations (Two-Phase Analysis)

**Reference bar (bearish)**: `open=150, high=152, low=146, close=148, volume=1M`
**Constraint**: `Stop > Limit`

| # | Formation | Stop | Limit | Fill | Explanation |
|---|-----------|------|-------|------|-------------|
| **F1** | High > Open > Close > Low > Stop > Limit | 145 | 144 | **None** | Stop < low → never triggers |
| **F2** | High > Open > Close > Stop > Low > Limit | 147 | 145 | **147** | Triggers at stop, limit ≤ trigger → fill at trigger |
| **F3** | High > Open > Stop > Close > Low > Limit | 149 | 145 | **149** | Triggers at stop, limit ≤ trigger → fill at trigger |
| **F4** | High > Stop > Open > Close > Low > Limit | 151 | 145 | **150** | Opens below stop, limit ≤ trigger → fill at trigger (open) |
| **F5** | Stop > High > Open > Close > Low > Limit | 153 | 145 | **150** | Opens below stop, limit ≤ trigger → fill at trigger (open) |
| **F6** | Stop > High > Open > Close > Limit > Low | 153 | 147 | **150** | Opens below stop, limit ≤ trigger → fill at trigger (open) |
| **F7** | Stop > High > Open > Limit > Close > Low | 153 | 149 | **150** | Opens below stop, limit ≤ trigger → fill at trigger (open) |
| **F8** | Stop > High > Limit > Open > Close > Low | 153 | 151 | **151** | Opens below stop, limit reachable on bounce → fill at limit |
| **F9** | Stop > Limit > High > Open > Close > Low | 154 | 153 | **None** | Limit > bar.high → unreachable |
| **F10** | High > Stop > Open > Close > Limit > Low | 151 | 147 | **150** | Opens below stop, limit ≤ trigger → fill at trigger (open) |
| **F11** | High > Open > Stop > Limit > Close > Low | 149.5 | 149 | **149.5** | Triggers at stop, limit ≤ trigger → fill at trigger |

**Pattern Summary**:
- **No trigger** (F1): `stop < bar.low`
- **Fill at trigger** (F2-F7, F10-F11): `limit ≤ trigger` → immediate fill (market behavior)
- **Fill at limit** (F8): `trigger < limit ≤ bar.high` → reachable on bounce
- **No fill** (F9): `limit > bar.high` → unreachable

**Key Insight**: SELL stop-limit mirrors BUY logic with inverted price relationships. Stop triggers downward, limit is floor price. When limit ≤ trigger, fills at trigger (market behavior). When limit reachable above trigger, fills at limit.

---

## Order Type Implementation Summary

### Market Orders
- **Always fills** at `bar.open`
- No conditions, no slippage in Phase 1

### Limit Orders

**BUY Limit**:
- Triggers: `bar.low <= limit_price`
- Fill price: `min(bar.open, limit_price)` (best available)
- No fill: `bar.low > limit_price`

**SELL Limit**:
- Triggers: `bar.high >= limit_price`
- Fill price: `max(bar.open, limit_price)` (best available)
- No fill: `bar.high < limit_price`

### Stop Orders

**BUY Stop**:
- Triggers: `bar.high >= stop_price`
- Fill price:
  - Normal: `stop_price` (if `bar.low <= stop_price`)
  - Gap up: `bar.open` (if `bar.low > stop_price`)

**SELL Stop**:
- Triggers: `bar.low <= stop_price`
- Fill price:
  - Normal: `stop_price` (if `bar.high >= stop_price`)
  - Gap down: `bar.open` (if `bar.high < stop_price`)

### Stop-Limit Orders - Two-Phase Execution

**BUY Stop-Limit** (`Limit > Stop`):

**Phase 1 - Stop Trigger**:
- Triggers: `bar.high >= stop_price`
- Trigger point: `bar.open` if opened at/above stop, else `stop_price`

**Phase 2 - Limit Evaluation**:
```python
if bar.low <= limit < trigger:
    fill at limit  # Reachable on pullback
elif limit >= trigger:
    fill at trigger  # Already acceptable (market behavior)
else:
    no fill  # limit < bar.low, unreachable
```

**SELL Stop-Limit** (`Stop > Limit`):

**Phase 1 - Stop Trigger**:
- Triggers: `bar.low <= stop_price`
- Trigger point: `bar.open` if opened at/below stop, else `stop_price`

**Phase 2 - Limit Evaluation**:
```python
if bar.high >= limit > trigger:
    fill at limit  # Reachable on bounce
elif limit <= trigger:
    fill at trigger  # Already acceptable (market behavior)
else:
    no fill  # limit > bar.high, unreachable
```

**Three Outcomes**:
1. **Fill at limit**: Limit reachable in remaining bar movement
2. **Fill at trigger**: Limit already acceptable at trigger (market behavior)
3. **No fill**: Limit unreachable in bar's range

---

## Open Research Questions

1. **Volatility Adjustment**: Should `std_divider` scale with bar volatility (High-Low range)?
   
2. **Volume Impact**: How to model price impact for large orders relative to bar volume?

3. **Gap Handling**: When Open != previous Close, how to handle orders triggered by gap?

4. **Trailing Stops**: How to update stop price during the bar when we don't know intra-bar movement?

5. **Multi-Bar Orders**: For low-liquidity, should large orders fill across multiple bars?

---

## Implementation Roadmap

### Immediate (Week 1-2)
- [x] Order models (completed)
- [x] BarData model with Pydantic validation (completed)
- [x] Fill/Execution models (completed)
- [x] Basic execution engine Phase 1 (completed)
- [x] Test suite for Market/Limit/Stop orders (17 tests passing)
- [x] BUY Stop-Limit two-phase execution logic (completed)
- [x] BUY Stop-Limit 11 formations tested and passing (F1-F11)
- [x] SELL Stop-Limit two-phase execution logic (completed)
- [x] SELL Stop-Limit 11 formations tested and passing (F1-F11)
- [x] BarData model with Pydantic validation (completed)
- [x] Fill/Execution models (completed)
- [x] Basic execution engine Phase 1 (completed)
- [x] Test suite for Market/Limit/Stop orders (17 tests passing)
- [x] BUY Stop-Limit two-phase execution logic (completed)
- [x] SELL Stop-Limit two-phase execution logic (completed)
- [x] SELL Stop-Limit 11 formations tested and passing (F1-F11)

### Short-term (Month 1)
- [ ] Statistical pricing model (Phase 2)
- [ ] Configurable ambiguity handling
- [ ] OCA group execution
- [ ] Parent-child order relationships

### Medium-term (Quarter 1)
- [ ] Trailing stop updates
- [ ] Volume-based partial fills
- [ ] Time-based order constraints (TIF, goodTillDate)
- [ ] Performance optimization for large backtests

---

## Test Coverage

**Current Status**: 70 tests passing, 2 xfailed (Phase 2/3 features)

- Market orders: 3 tests (2 bullish + 1 bearish)
- Limit orders: 13 tests (6 BUY + 7 SELL, covering both bullish and bearish bars)
- Stop orders: 10 tests (5 BUY + 5 SELL, covering both bullish and bearish bars)
- Stop-Limit orders: 44 tests
  - BUY: 22 tests (11 formations F1-F11 on bullish bar + 11 formations F1-F11 on bearish bar)
  - SELL: 22 tests (11 formations F1-F11 on bearish bar + 11 formations F1-F11 on bullish bar)
- Edge cases: 3 tests (UNSET values, pending status)
- Future: 2 xfailed tests (partial fills, time constraints)

**Test fixtures**:
- `bullish_bar`: open=148, high=152, low=146, close=150 (Close > Open)
- `bearish_bar`: open=150, high=152, low=146, close=148 (Open > Close)

**Coverage notes**:
- All order types tested on both bullish and bearish bars
- BUY stop-limit: Full F1-F11 formation coverage on BOTH bullish and bearish bars
- SELL stop-limit: Full F1-F11 formation coverage on BOTH bullish and bearish bars
- Two-phase execution logic validated across different bar types and formations
- Comprehensive coverage ensures algorithm works correctly regardless of bar direction
- Complete symmetrical coverage: BUY and SELL both have 22 tests (2 bar types × 11 formations)

---

## References

- **QuantConnect Lean**: [GitHub - FillModel.cs](https://github.com/QuantConnect/Lean)
- **AlgoBee**: Internal implementation (simexchange.py)
- **Industry Practice**: Most platforms use threshold-based fills (Lean approach) for simplicity
- **Interactive Brokers API**: Order types and parameter naming conventions
