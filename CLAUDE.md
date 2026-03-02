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
- **`src/simulator.py`**: `Simulator` - wraps ExecutionEngine to manage order lifecycle across multiple bars.

### Execution Flow

Orders follow a recursive parent-child pattern:
1. Stop orders create Market children (triggered when stop price hit)
2. Stop-Limit orders create Limit children (stop triggers limit evaluation)
3. Trailing orders track extreme prices and adjust stop dynamically

The engine is stateless per-bar; order state (e.g., trailing extreme prices) is mutated on the order object itself.

### Simulator API

```python
sim = Simulator()
sim.on_fill(lambda trade, fill: print(f"Filled: {fill.execution.price}"))
sim.on_cancel(lambda trade: print(f"Cancelled: {trade.log[-1].message}"))

trade = sim.submit_order(order)
sim.cancel_order(order_id)
sim.update_order(order_id, price=new_price)
sim.get_trade(order_id)
sim.get_active_trades()
fills = sim.process_bar(bar)
```

### TIF Support

- **GTC**: Never expires
- **DAY**: Expires on date change (after matching, so orders get one bar attempt)
- **GTD**: Expires after goodTillDate
- **GAT**: goodAfterTime — order not active until specified time

### OCA (One-Cancels-Other)

Set `ocaGroup` on orders to link them. When one fills, siblings are cancelled. Order closest to `bar.open` fills first when multiple could fill.

### Bar Processing Algorithm

1. Expire GTD orders past goodTillDate
2. Sort active orders by distance to bar.open (OCO priority)
3. For each active order (skip if OCO-cancelled, skip if GAT not yet active):
   a. Execute via ExecutionEngine
   b. If filled: update Trade, cancel OCO siblings, submit bracket children
   c. If not filled: keep (state mutated in-place)
4. Expire unfilled DAY orders if date changed

### Test Data

CSV-driven formation tests in `test-data/`:
- `test-data/stop-limit/` - 8 CSV files x 11 formations = 88 price scenarios
- `test-data/trailing-stop/` - trailing stop formation data

## Code Conventions

- Use `# region` / `# endregion` for logical grouping in longer files
- File naming: singular nouns (`order.py` not `orders.py`)
- Core functions assume valid inputs; validation belongs in gateway/wrapper layer
- TDD approach: write tests before implementation
- Use `@pytest.mark.xfail` for planned but unimplemented features
