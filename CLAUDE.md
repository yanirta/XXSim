# CLAUDE.md — XXSim

OHLCV-based stock exchange execution simulator for backtesting trading strategies. Determines realistic order fills from sparse candlestick data. See `../CLAUDE.md` for workspace-wide conventions.

## Commands

```bash
pytest tests/ -v
pytest tests/test_file.py::test_function -v
```

## Architecture

### Core Components

- **`src/execEngine.py`**: `ExecutionEngine` - recursive order execution against bar data. Handles order type dispatch and parent-child relationships.
- **`src/simulator.py`**: `Simulator` - wraps ExecutionEngine to manage order lifecycle across multiple bars. `SimulatorConfig` controls fill drift (`fill_drift_model`, `std_divider`), commission, and `bar_duration` (see GAT below).

### Execution Flow

Orders follow a recursive parent-child pattern:
1. Stop orders create Market children (triggered when stop price hit)
2. Stop-Limit orders create Limit children (stop triggers limit evaluation)
3. Trailing orders track extreme prices and adjust stop dynamically

The engine is stateless per-bar; order state (e.g., trailing extreme prices) is mutated on the order object itself.

### Order Modification (`update_order`)

`update_order(order_id, **fields)` modifies an active order **in place** and
re-arms it as if it had been freshly submitted at that instant:

- Applies the given fields (`price`, `totalQuantity`, `trailingDistance`,
  `trailingPercent`).
- Resets any **derived** per-order execution state (`_reset_derived_state`): for
  a `TRAIL`/`TRAIL LIMIT` the high-water mark (`extremePrice`) and its derived
  `stopPrice` are cleared, so the trail re-anchors to the market on the next bar
  — matching IB's reset-on-modify. Non-trailing types carry no such state (no-op).
- Preserves `orderId`, `permId`, OCA membership, and prior fills; appends an
  `Order modified` log entry and emits a status event.

### Order Type Support

- **MKT**: Fills at bar.open (with optional drift)
- **LMT**: Fills when bar trades through limit price
- **STP**: Creates MKT child when stop price hit
- **STP LMT**: Creates LMT child when stop price hit
- **TRAIL**: Trailing stop; adjusts dynamically with price
- **MOC** (Market-on-Close): Only fills when `bar.is_close_bar=True`; fills at `bar.close`

### TIF Support

- **GTC**: Never expires
- **DAY**: Expires when the current bar's date is after the order's first `Submitted` log entry date. MOC orders start as `PreSubmitted` (see below), so their "submitted date" is stamped on the first `process_bar` call — allowing orders queued after close to survive until the next close bar. When combined with `goodAfterTime`, a DAY order is not expired until the `goodAfterTime` date has passed — it is dormant until that date, then active as a DAY order on that date, then expired if still unfilled the next day.
- **GTD**: Expires after goodTillDate
- **GAT**: goodAfterTime — order not active until specified time. Bars carry
  their START time, so `order_active_at(order, bar_time, bar_duration)` treats an
  order as active once the bar *covers* the activation: `bar_time >= gat` **or**
  `gat < bar_time + bar_duration`. Set `SimulatorConfig.bar_duration` to the fill
  resolution's span; the default `timedelta(0)` keeps the strict start-only
  comparison. Without it a mid-bar activation defers to the NEXT bar — and one
  falling inside the session's last bar (a 1-min NYSE session ends at 15:59:00,
  so 15:59:30) never activates at all, silently producing zero fills while
  filling normally against a live broker's clock. Covering the bar is
  deliberately optimistic: the fill is evaluated against the whole bar, including
  the part before the activation instant, which bar-level simulation cannot
  resolve.

### OCA (One-Cancels-Other)

Set `ocaGroup` on orders to link them. When one fills, siblings are cancelled. Order closest to `bar.open` fills first when multiple could fill.

### Bar Processing Algorithm

0. Activate `PreSubmitted` orders: transition to `Submitted`, stamping the bar's date as submission date (used for DAY expiry)
1. Expire GTD orders past goodTillDate
2. Sort active orders by distance to bar.open (OCO priority)
3. For each active order (skip if OCO-cancelled, skip if GAT not yet active):
   a. Execute via ExecutionEngine
   b. If filled: update Trade, cancel OCO siblings, submit bracket children
   c. If not filled: keep (state mutated in-place)
4. Expire unfilled DAY orders if date changed (compares bar date to first `Submitted` log entry)

**MOC PreSubmitted lifecycle:** MOC orders are submitted with status `PreSubmitted`. On the first `process_bar` call they activate to `Submitted` (dated that bar). This means a MOC order submitted after the day's last bar sees its first bar the next morning and fills at that day's close — matching IB's real behavior.

### Test Data

CSV-driven formation tests in `test-data/`.

## Code Conventions

- Use `# region` / `# endregion` for logical grouping in longer files
- File naming: singular nouns (`order.py` not `orders.py`)
- Core functions assume valid inputs; validation belongs in gateway/wrapper layer
- TDD approach: write tests before implementation
- Use `@pytest.mark.xfail` for planned but unimplemented features
