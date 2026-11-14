# CLAUDE.md — XXSim

OHLCV-based stock exchange execution simulator for backtesting trading strategies. Determines realistic order fills from sparse candlestick data. See `../CLAUDE.md` for workspace-wide conventions.

## Architecture

### Core Components

- **`src/execEngine.py`**: `ExecutionEngine` - recursive order execution against bar data. Handles order type dispatch and parent-child relationships.
- **`src/simulator.py`**: `Simulator` - wraps ExecutionEngine to manage order lifecycle across multiple bars. `SimulatorConfig` controls fill drift (`fill_drift_model`, `std_divider`), commission (see below), and `bar_duration` (see GAT below).

### Execution Flow

Each order type has its own fill method; an order's `children` (a bracket) are executed recursively on the bar their
parent fills on, against that bar re-opened at the parent's fill price:
1. Stop orders fill at the trigger point (the stop price, or the open after a gap)
2. Stop-Limit orders trigger, then evaluate their limit on the same bar and stay pending (triggered) if it is not reached
3. Trailing orders track extreme prices and adjust the stop dynamically

The engine is stateless per-bar; order state (e.g., trailing extreme prices) is mutated on the order object itself.

### Order Modification (`update_order`)

`update_order(order_id, **fields)` modifies an active order **in place** and
re-arms it as if it had been freshly submitted at that instant:

- Applies the given fields — and ONLY these, exported as `UPDATABLE_FIELDS`:
  `price`, `totalQuantity`, `trailingDistance`, `trailingPercent`,
  `goodAfterTime` (0.23.0). Any other
  field, or one the order type does not carry, **refuses the whole call**:
  nothing is applied and `False` is returned (0.22.0; before that an
  unsupported field was silently dropped and `True` returned). The strictness
  matters because a live order manager applies whatever field the order object
  carries and sends it to the broker — so a field this simulator does not model
  is a no-op in backtest and a real modification in production, and reporting
  success hides that divergence in the direction that flatters the backtest.
- `goodAfterTime` is validated **before** anything is applied: it must parse,
  and on an `MOC` it must fall before the auction cutoff. `_moc_is_too_late`
  guards submission only, so without that check a modification could move a live
  MOC to 15:55 — inert until it expired with the day, leaving the position it
  was meant to close with no exit. Unlike a trailing stop, `goodAfterTime` has
  no derived state to re-arm: `order_active_at` re-reads it every bar.
- Resets any **derived** per-order execution state (`_reset_derived_state`): for
  a `TRAIL`/`TRAIL LIMIT` the high-water mark (`extremePrice`) and its derived
  `stopPrice` are cleared, so the trail re-anchors to the market on the next bar
  — matching IB's reset-on-modify. Non-trailing types carry no such state (no-op).
- Preserves `orderId`, `permId`, OCA membership, and prior fills; appends an
  `Order modified` log entry and emits a status event.

### Order Type Support

- **MKT**: Fills at bar.open (with optional drift)
- **LMT**: Fills when the bar touches the limit price. Fill drift never moves the fill through the limit
- **STP**: Fills at the stop price when hit, or at the open after a gap through it
- **STP LMT**: Triggers at the stop price, then fills as a limit; stays pending (triggered) until the limit is reached
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

### Commission

Every fill is priced by one method, `ExecutionEngine._commission_for(shares, price)`:

```
commission = clamp(per_fill + per_share * shares, minimum, max_pct * notional)
```

Configured on `ExecutionConfig` / `SimulatorConfig` as `commission_per_fill`,
`commission_per_share`, `commission_minimum`, `commission_max_pct`. **All default
to zero, which is free trading** — the behaviour every caller had before the model
existed, and still the right default for a run asking about signal quality rather
than net P&L.

Interactive Brokers' US-equities schedules, as a caller would set them:

| Tier | `per_share` | `minimum` | `max_pct` |
|------|-------------|-----------|-----------|
| Fixed | 0.005 | 1.00 | 0.01 |
| Tiered | 0.0035 | 0.35 | 0.01 |

**The cap outranks the minimum**, and that ordering is why both exist: one share
of a $20 stock costs 1% of $20 = $0.20, not the $1.00 floor. A floor-then-return
implementation overcharges exactly the small trades a one-share config is made of.

All six fill paths (MOC, MKT, LMT, STP, STP LMT, TRAIL) call the one method. A
model that only some order types applied would be worse than none — the
difference would read as an edge belonging to the order shape.

### OCA (One-Cancels-Other)

Set `ocaGroup` on orders to link them. When one fills, siblings are cancelled. When several could fill on one bar, the order whose trigger is closest to `bar.open` fills first (`Simulator._trigger_distance`): a limit or stop by its price, a market order at the open, a MOC last, a TRAIL by its current stop (or the stop it would take at the open, before it has tracked a price). Ties keep submission order. Bar-level data cannot say which price came first; this rule is a stated convention, not a reconstruction (0.25.0; before it, a TRAIL's `price` of 0 put it first in every group).

### Bar Processing Algorithm

0. Activate `PreSubmitted` orders: transition to `Submitted`, stamping the bar's date as submission date (used for DAY expiry)
1. Expire GTD orders past goodTillDate
2. Expire DAY orders if the date changed (compares bar date to first `Submitted` log entry), before matching, so a DAY order
   never fills on a later day
3. Sort active orders by trigger distance to bar.open (OCA priority, above)
4. For each active order (skip if OCO-cancelled, skip if GAT not yet active):
   a. Execute via ExecutionEngine
   b. If filled: update Trade, cancel OCO siblings, submit bracket children. Of two OCA children that both fill on the
      parent's fill bar, the one whose trigger is closest to the parent's fill price wins; a tie goes to the one added first
   c. If not filled: keep (state mutated in-place)

**MOC PreSubmitted lifecycle:** MOC orders are submitted with status `PreSubmitted`. On the first `process_bar` call they activate to `Submitted` (dated that bar). This means a MOC order submitted after the day's last bar sees its first bar the next morning and fills at that day's close — matching IB's real behavior.

## Code Conventions

- Use `# region` / `# endregion` for logical grouping in longer files
- File naming: singular nouns (`order.py` not `orders.py`)
- Core functions assume valid inputs; validation belongs in gateway/wrapper layer
- TDD approach: write tests before implementation
- Use `@pytest.mark.xfail` for planned but unimplemented features
