# Trade Lifecycle Alignment with IB

Align xtrading_models and XXSim objects with ib_insync's Trade lifecycle model, so both live and backtest modes share the same object semantics.

**Status: Complete** — all changes implemented, 287 tests passing (51 xtrading_models + 236 XXSim).

## Problem

XXSim callbacks emitted raw objects:
```python
on_fill(callback: (Fill) -> None)
on_cancel(callback: (Order, str) -> None)
```

In ib_insync, callbacks emit `Trade` objects that wrap the full lifecycle:
```python
ib.orderStatusEvent += callback   # receives Trade
ib.execDetailsEvent += callback   # receives Trade, Fill
ib.cancelOrderEvent += callback   # receives Trade
```

Without a common `Trade` object, the EventBus abstraction in ShadowTrader must translate between incompatible types. If xtrading_models and XXSim adopt the same lifecycle model, the EventBus becomes a thin passthrough rather than a translation layer.

## Before → After

### xtrading_models
| Model | Before | After |
|-------|--------|-------|
| `Order` (+ subtypes) | Had `status` field | Pure instruction, no status |
| `StopOrder` | Auto-created MarketOrder child on trigger | `triggered: bool` field, no auto-children |
| `StopLimitOrder` | Auto-created LimitOrder child on trigger | `triggered: bool` + `limitPrice` fields, no auto-children |
| `TrailingStopMarket` | Auto-created MarketOrder child | No auto-children |
| `TrailingStopLimit` | Auto-created LimitOrder child | No auto-children |
| `ExecutionResult` | PENDING / FILLED / PARTIAL statuses | **Deleted** — `execute()` returns `list[Fill]` directly |
| `Trade` | Did not exist | Lifecycle wrapper: order + orderStatus + fills + log |
| `OrderStatus` | Did not exist | Fill progress tracking with status constants |
| `TradeLogEntry` | Did not exist | Timestamped status + message entries |

### XXSim Simulator
| Aspect | Before | After |
|--------|--------|-------|
| Internal tracking | `_active_orders: dict[int, Order]` | `_active_trades: dict[int, Trade]` |
| `submit_order` return | `int` (orderId) | `Trade` |
| `on_fill` signature | `(Fill) -> None` | `(Trade, Fill) -> None` |
| `on_cancel` signature | `(Order, str) -> None` | `(Trade) -> None` |
| `on_update` | `(Order) -> None` | Removed, replaced by `on_status(Trade)` |
| `on_bar` signature | `(BarData, list[Fill]) -> None` | No change |
| `get_order` / `get_active_orders` | Returns Order | `get_trade` / `get_active_trades`, returns Trade |
| Cancel reason | Passed as string arg | In `trade.log[-1].message` |

### ExecutionEngine
| Aspect | Before | After |
|--------|--------|-------|
| Stop order dispatch | `startswith('STP')` matched both STP and STP LMT | Explicit `'STP'` and `'STP LMT'` cases |
| `_fill_stop` | Typed as `Order`, no triggered tracking | Typed as `StopOrder`, sets `order.triggered = True` |
| `_fill_stop_limit` | Did not exist (handled via child creation) | New method: trigger sets state, evaluates as limit |
| `_evaluate_limit_price` | Inline in `_fill_limit` | Extracted as shared helper for limit and stop-limit |
| Stop fill count | 2 fills (parent stop + child market) | 1 fill (original order) |
| Return type | `ExecutionResult` (fills + pending_orders + status) | `list[Fill]` — no wrapper needed |

## Implementation Details

### OrderStatus (`xtrading_models/trade.py`)

```python
@dataclass
class OrderStatus:
    orderId: int = 0
    status: str = 'PendingSubmit'
    filled: float = 0.0
    remaining: float = 0.0
    avgFillPrice: float = 0.0
    lastFillPrice: float = 0.0
    parentId: int = 0

    PendingSubmit = 'PendingSubmit'
    Submitted = 'Submitted'
    Filled = 'Filled'
    Cancelled = 'Cancelled'
    Inactive = 'Inactive'

    DoneStates = {'Filled', 'Cancelled'}
    ActiveStates = {'PendingSubmit', 'Submitted'}
```

### Trade (`xtrading_models/trade.py`)

```python
@dataclass
class Trade:
    order: Order
    orderStatus: OrderStatus
    fills: list[Fill] = field(default_factory=list)
    log: list[TradeLogEntry] = field(default_factory=list)

    @property
    def is_done(self) -> bool:
        return self.orderStatus.status in OrderStatus.DoneStates

    @property
    def is_active(self) -> bool:
        return self.orderStatus.status in OrderStatus.ActiveStates
```

### ExecutionEngine return type

`ExecutionResult` was deleted. `execute()` now returns `list[Fill]` directly:
- Non-empty list = order filled
- Empty list = order not filled (stays pending)
- Bracket children: Simulator derives unfilled children from `order.children` minus those that appear in fills

### Stop execution model

**StopOrder** — trigger and fill in one step:
```python
def _fill_stop(self, order: StopOrder, bar: BarData, parent_id: int = 0) -> Optional[ExecutionResult]:
    # Check trigger, calculate fill price
    order.triggered = True
    # Return single fill referencing the original StopOrder
    return [fill]
```

**StopLimitOrder** — trigger changes state, then evaluate as limit:
```python
def _fill_stop_limit(self, order: StopLimitOrder, bar: BarData, parent_id: int = 0) -> Optional[ExecutionResult]:
    if not order.triggered:
        # Check stop trigger
        if not triggered: return None
        order.triggered = True
        eval_bar = _create_modified_bar(bar, trigger_price)
    else:
        eval_bar = bar  # already triggered on prior bar

    fill_price = _evaluate_limit_price(action, limitPrice, eval_bar)
    if fill_price is None:
        return []  # triggered but limit not reached; stays pending
    return [fill]
```

### Simulator process_bar

```python
fills = self._engine.execute(trade.order, bar)

if fills:
    # Update trade status, invoke callbacks, cancel OCA siblings
    # Submit unfilled bracket children as new trades
    filled_order_ids = {f.execution.orderId for f in fills}
    for child in trade.order.children:
        if child.orderId not in filled_order_ids:
            child_trade = Trade(order=child, ...)
            # Added to _active_trades

# else: PENDING — keep trade (state already mutated in-place by engine)
```

### Simulator callbacks

```python
on_fill(callback: (Trade, Fill) -> None)
on_cancel(callback: (Trade) -> None)       # reason in trade.log[-1].message
on_status(callback: (Trade) -> None)       # any status change
on_bar(callback: (BarData, list[Fill]) -> None)  # unchanged
```

---

## Impact on ShadowTrader Backtest Infrastructure

With these changes, the EventBus becomes a thin passthrough:

```python
class IBEventBus(EventBus):
    def on_fill(self, callback: Callable[[Trade, Fill], None]):
        self.ib.execDetailsEvent += callback  # already passes (Trade, Fill)

class SimEventBus(EventBus):
    def on_fill(self, callback: Callable[[Trade, Fill], None]):
        self.simulator.on_fill(callback)  # now also passes (Trade, Fill)
```

No wrapping, no translation — both sides emit the same types.

## Files Changed

| File | Changes |
|------|---------|
| `XTrading-models/src/xtrading_models/trade.py` | **New** — OrderStatus, Trade, TradeLogEntry |
| `XTrading-models/src/xtrading_models/order.py` | Removed `status` field, removed auto-children from stop types, added `triggered` to StopOrder/StopLimitOrder, added `limitPrice` to StopLimitOrder |
| `XTrading-models/src/xtrading_models/execution_result.py` | **Deleted** — `execute()` returns `list[Fill]` directly |
| `XTrading-models/src/xtrading_models/__init__.py` | Added Trade, OrderStatus, TradeLogEntry exports; removed ExecutionResult |
| `XTrading-models/pyproject.toml` | Version 0.6.0 → 0.7.0 |
| `XTrading-models/tests/test_models.py` | Updated stop/trailing assertions (0 children), added Trade/OrderStatus tests |
| `XXSim/src/execEngine.py` | **Renamed** from `execution.py`. Returns `list[Fill]`. Split STP/STP LMT dispatch, added `_fill_stop_limit`, extracted `_evaluate_limit_price` |
| `XXSim/src/simulator.py` | Trade lifecycle management, updated callback signatures, bracket children from `order.children` |
| `XXSim/src/__init__.py` | Added Trade, OrderStatus, TradeLogEntry exports; updated import path |
| `XXSim/tests/test_simple_orders_execution.py` | Stop fills: 2 → 1, `result.fills` → `fills` |
| `XXSim/tests/test_stop_limit_orders_execution.py` | Rewritten: triggered state model, `pending_orders` → `order.triggered` checks |
| `XXSim/tests/test_trailing_stop_market.py` | Fills: 2 → 1, `pending_orders` → order state checks |
| `XXSim/tests/test_exec_engine.py` | **Renamed** from `test_execution_result.py`. Removed ExecutionResult tests |
| `XXSim/tests/test_simulator.py` | Trade objects, updated callback signatures, status values |
