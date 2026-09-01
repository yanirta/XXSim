# B17 — Volume-aware partial fills in XXSim

**Status:** ⬜ pending · **Priority:** P2 · **Track:** Backtest
**Backlog row:** `implementation_plan.md` → B17
**Packages touched:** XXSim (version bump + PyPI publish), AlphaNexus. XTrading-models: **no change needed** — see §2.

---

## 1. Why

A fill today takes the whole order at one price regardless of the bar's volume. A
backtest that sizes into 50k shares of a name trading 30k in the bar reports an edge
the real book cannot trade, and the error scales with position size — so it is
precisely the strategies that look best at size that are most misreported.

XXSim's README states the assumption plainly: *"No partial fills — orders fill
entirely or not at all."* This item removes it.

## 2. What already works

Worth stating up front, because it is more than expected and it shapes the design:

- **`OrderStatus` already carries `filled` / `remaining` / `avgFillPrice`.** IB has no
  `PartiallyFilled` status — a partially filled order sits at `Submitted` with
  `filled`/`remaining` moving. **Do not add a status value.** Matching IB here is
  free and keeps the live/backtest trade records the same shape.
- **`Execution.cumQty` and `Execution.avgPrice` exist and are never populated.** They
  are the natural home for per-execution partial bookkeeping, and filling them in
  brings the sim closer to IB's own execution records rather than further away.
- **`BarData.volume` is present and populated**, so the cap has its input.
- **An order surviving a bar with mutated state is already a solved problem.**
  `_fill_stop_limit` returns `[]` (triggered, limit unfilled) rather than `None`, and
  `process_bar` carries it forward. Partials extend that path; they do not invent it.
- **`PortfolioTracker.process_fill` is fill-incremental** (`net_shares += shares`, cash
  delta per fill) so equity accounting is already partial-safe and needs no change.
- **`modify_order(order_id, **fields)` exists on the `OrderManager` ABC** (shipped with
  C9) and `Simulator.update_order` already accepts `totalQuantity`. This is the lever
  for resizing bracket children — see §4.4 for the one trap in it.

## 3. Blockers

### 3.1 Engine fills the whole order, unconditionally
`execEngine.py` — all six fill paths (`_fill_market`, `_fill_moc`, `_fill_limit`,
`_fill_stop`, `_fill_stop_limit`, `_fill_trail`) construct their `Execution` with
`shares=order.totalQuantity`. No remaining-quantity concept exists and bar volume
never reaches `_try_fill_order`.

### 3.2 Simulator books any fill as complete
`simulator.py::process_bar` does `self._active_trades.pop(order_id, None)` on any
non-empty fill list, then `_update_trade_filled`, which hardcodes
`status=TradeStatus.Filled` and `remaining=0.0`. A partial would be recorded as a
complete fill *and* dropped from the order book — the remainder silently ceases to
exist.

### 3.3 OCA cascades on a partial
`_cancel_oca_siblings(trade)` fires on any fill. A partially filled stop would cancel
its take-profit sibling while shares remain open — a silently unprotected position.
**This is the most dangerous of the blockers**, because it produces a plausible-looking
backtest rather than a crash.

### 3.4 Bracket children are sized at full entry quantity
`ExecutionEngine.execute` arms children on the parent's fill bar at their own
`totalQuantity`, and every strategy builds SL/TP at the same `quantity` as the entry
(`hourly_midpoint.py:112-124`, `nested_wick_intraday.py:352-367`,
`unilateral_pairs.py:330-343`, `dual_momentum.py:137-151`, `gtaa5.py:94-106`,
`rsi2_ibs_combined_mean_reversion.py:359-376`, `supply_demand_mean_reversion.py:170-182`).
A 40%-filled entry arms a 100% stop, which over-sells into a *short* position on exit.
Largest change in the item, and it lands in AlphaNexus, not XXSim.

### 3.5 Journal marks the order terminal on the first partial
`AlphaNexus/src/backtest/engine.py:35` `_trade_from_fill` hardcodes
`status=TradeStatus.Filled, remaining=0` per fill. `Filled` is in the journal's
`TERMINAL_STATUSES` (`trade_journal.py:54`), so the first partial closes the row and
subsequent fills for the same order are reconciled against a terminal entry.

### 3.6 Position tracker records intended, not filled, quantity
`arbiter_base.py:120` calls `open_position(quantity=order.totalQuantity)` at submit
time. With partials, `position.quantity` diverges from what is actually held — and
exit builders read `position.quantity` (`gtaa5.py:106`, `dual_momentum.py:151`,
`hourly_midpoint.py:137`, and others) to size the closing order.

## 4. Design

### 4.1 The cap
Add to `ExecutionConfig` / `SimulatorConfig`:

```python
max_volume_participation_p: float = 0.0   # fraction of bar volume one order may take
```

Fraction in `[0, 1]` with the `_p` suffix, per CLAUDE.md. **`0.0` disables the cap
entirely**, reproducing today's behaviour exactly — the same convention the commission
model uses, and it means every existing backtest stays byte-identical until a config
opts in. Fillable quantity for a bar is
`min(remaining, max_volume_participation_p * bar.volume)`, floored to whole shares,
and a cap that rounds to zero fills nothing (the order rests, it is not cancelled).

Open question for review: **the cap is per order, not per bar across orders.** Two
orders on the same symbol and bar can each take the full participation slice. Making
it a shared per-bar budget requires the Simulator to meter across orders, which is a
larger change and interacts with the existing distance-to-open sort order. Recommend
shipping per-order first and recording the limitation.

### 4.2 Where remaining quantity lives
The Simulator owns the `Trade`/`OrderStatus`, which is the authoritative record.
**Pass remaining into the engine** — `execute(order, bar, parent_id, remaining)` —
rather than adding mutable fill state to `Order`. The engine stays a function of
`(order, bar, remaining)` and there is one source of truth for how much is left.
(Contrast with `triggered` / `extremePrice`, which are genuinely per-order *execution*
state and correctly live on the order.)

### 4.3 Simulator partial branch
When the returned fills sum to less than `remaining`:
- **do not** pop from `_active_trades`
- **do not** call `_cancel_oca_siblings`
- update `filled` / `remaining` / `avgFillPrice` cumulatively across all fills so far;
  status stays `Submitted`
- append a `TradeLogEntry` (`Partially filled N @ P, M remaining`)
- emit `fill` and `status` events as usual — downstream is incremental and copes

Split `_update_trade_filled` into `_apply_fills` (cumulative accounting, always) and a
terminal transition that only runs when `remaining` reaches zero.

### 4.4 Bracket children on a partially filled parent
Children must be armed for **what the parent has actually filled**, and resized upward
as more fills arrive — leaving them unarmed until the parent completes would leave the
position unprotected across bars, which is worse than mis-sizing.

Reuse `modify_order(child_id, totalQuantity=...)`, which already exists.

> **Trap:** `Simulator._reset_derived_state` clears `extremePrice`/`stopPrice` on *any*
> `update_order` call, to reproduce IB's reset-on-modify for trailing stops. Resizing a
> trailing child would therefore re-anchor its high-water mark to the current market —
> silently loosening a stop that has been ratcheting. Either give quantity-only updates
> a path that skips the derived-state reset, or forbid partial-parent brackets with
> trailing children. **Decide this before implementing**; it is the kind of thing that
> produces a better-looking backtest and no error.

### 4.5 Commission must stay per-order
`_commission_for` applies `commission_minimum` per fill. Splitting one order into N
partials would multiply IB's $1 minimum by N, but **IB applies the minimum (and the
`max_pct` cap) per order, not per execution**. Naive partials therefore fabricate
commission drag that does not exist — the exact class of error the commission model
was added to prevent.

Fix: compute the schedule against *cumulative* filled quantity and charge the
difference from what has already been billed for that order.

```
this_fill = clamp(f(cum_shares), minimum, max_pct * cum_notional) - already_charged
```

This is exact for both the floor and the cap, and needs cumulative shares/commission
threaded alongside remaining quantity (§4.2).

### 4.6 A triggered stop's remainder must not re-test its trigger
`_fill_stop` re-evaluates the stop condition on every bar and never consults
`order.triggered` (unlike `_fill_stop_limit`, which short-circuits on it). Today that
is harmless, because a triggered stop always fills completely and leaves the book. With
partials, a stop that triggered and filled half must fill its remainder **as a market
order on the next bar** — it must not re-test the stop price, which may no longer be
reachable. Add the same `triggered` short-circuit `_fill_stop_limit` has.

Same question applies per type and should be settled explicitly:
- **MKT** — remainder fills at the *next* bar's open. Realistic.
- **LMT** — remainder re-evaluates the limit each bar. Correct as-is.
- **STP** — see above: remainder becomes market.
- **STP LMT** — remainder re-evaluates the limit; `triggered` already handles it.
- **TRAIL** — remainder keeps trailing. Verify the high-water mark is not disturbed by
  the partial (interacts with §4.4).
- **MOC** — fills only on `is_close_bar`; a capped remainder has no later close bar
  that day. Recommend: MOC remainder is **cancelled**, not carried, and logged as such.

## 5. Work items

**XXSim** (→ 0.21.0, republish to PyPI)
1. `ExecutionConfig` / `SimulatorConfig`: `max_volume_participation_p`.
2. `execute()` / `_try_fill_order` / six fill paths: thread remaining, apply cap, set
   `cumQty` / `avgPrice` on `Execution`.
3. `_commission_for`: cumulative-difference model (§4.5).
4. `_fill_stop`: `triggered` short-circuit (§4.6).
5. `simulator.py`: partial branch — no pop, no OCA cascade, cumulative status (§4.3).
6. Docs: `README.md` (drop the "No partial fills" line), `EXECUTION_ALGORITHM.md`
   (move *Volume constraints* out of Phase 3 Future).

**AlphaNexus**
7. `backtest/engine.py::_trade_from_fill` — derive status from `trade.orderStatus`
   instead of hardcoding `Filled`.
8. Arbiter — resize bracket children on partial parent fill (§4.4).
9. `PositionTracker` — track filled quantity, not intended (§3.6); exit builders that
   read `position.quantity` then size correctly with no per-strategy change.

**Strategies:** none, provided the arbiter resizes children centrally. That is the
main argument for doing §4.4 in the arbiter rather than in `build_exit_order`.

## 6. Test plan

XXSim:
- cap disabled (`0.0`) → existing suite passes unchanged, byte-identical fills
- order larger than the cap fills across N bars; sum of partials == `totalQuantity`
- `avgFillPrice` is the share-weighted mean of the partials
- partial fill does **not** cancel an OCA sibling; completion does
- commission across N partials == commission of one equivalent full fill (§4.5)
- triggered stop's remainder fills at market next bar even when the stop price is no
  longer touched (§4.6)
- DAY/GTD expiry cancels a partially filled order and reports the partial, not zero
- MOC remainder is cancelled at the close bar, not carried

AlphaNexus:
- journal row stays non-terminal across partials, terminal on completion, and reports
  the share-weighted price
- bracket children are sized to filled quantity and resized as the parent completes
- a trailing child is not re-anchored by a quantity-only resize (§4.4 trap)
- `PortfolioTracker` net shares match the sum of partials (regression — expected to
  pass already)

## 7. Rollout

Default `0.0` keeps every existing backtest identical, so this can land without
invalidating prior results. Enabling it is a config change per strategy, and the first
strategy to turn it on should be re-run against its archived results with the
difference recorded — the *point* of the item is that some edges will shrink.
