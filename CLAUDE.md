# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

XXSim (XSim) is an OHLCV-based stock exchange execution simulator for backtesting trading strategies. The core challenge is determining realistic order fills from sparse candlestick data (Open, High, Low, Close, Volume) with statistical accuracy. This is NOT a live exchange simulator.

## Commands

```bash
# Activate virtual environment (required before running/testing)
source ./.venv/bin/activate

# Run all tests
pytest tests/ -v

# Run a specific test file
pytest tests/test_stop_limit_orders_execution.py -v

# Run a single test
pytest tests/test_stop_limit_orders_execution.py::test_stop_limit_execution -v

# Visualize stop-limit formations
python docs/stop-limit-chart-generator.py test-data/stop-limit/<filename.csv>

# Visualize trailing stop formations
python docs/trailing-stop-chart-generator.py test-data/trailing-stop/<filename.csv>
```

## Architecture

### Core Components

- **`src/execution.py`**: `ExecutionEngine` - recursive order execution against bar data. Handles order type dispatch and parent-child order relationships.
- **`src/models/order.py`**: Order hierarchy using Pydantic. Base `Order` class with specialized subclasses (`MarketOrder`, `LimitOrder`, `StopOrder`, `StopLimitOrder`, `TrailingStopMarket`).
- **`src/models/bar.py`**: `BarData` - OHLCV candlestick representation.
- **`src/models/fill.py`**: `Fill`, `Execution`, `CommissionReport` - execution result models.
- **`src/models/execution_result.py`**: `ExecutionResult` - container for fills and pending orders.

### Execution Flow

Orders follow a recursive parent-child pattern:
1. Stop orders create Market children (triggered when stop price hit)
2. Stop-Limit orders create Limit children (stop triggers limit evaluation)
3. Trailing orders track extreme prices and adjust stop dynamically

The engine is stateless per-bar; order state (e.g., trailing extreme prices) is mutated on the order object itself.

### Simulator (Multi-Bar)

- **`src/simulator.py`**: `Simulator` - wraps `ExecutionEngine` to manage order lifecycle across multiple bars.

Key features:
- **Order Book**: Simple dict `{orderId: Order}` tracking active orders
- **TIF Support**: GTC (never expires), DAY (expires on date change), GTD (expires after goodTillDate)
- **Callbacks**: `on_fill`, `on_cancel`, `on_update`, `on_bar` for event notifications

API:
```python
sim = Simulator()
sim.on_fill(lambda fill: print(f"Filled: {fill.execution.price}"))
sim.on_cancel(lambda order, reason: print(f"Cancelled: {reason}"))

sim.submit_order(order)      # Returns order ID (uses order.ocaGroup if set)
sim.cancel_order(order_id)   # Returns True if found
sim.update_order(order_id, price=new_price)  # Modify active order
sim.get_order(order_id)      # Query single order
sim.get_active_orders()      # Query all active orders

fills = sim.process_bar(bar)  # Process bar, returns fills
```

**OCO (One-Cancels-Other) Orders:**
```python
# Set ocaGroup on orders to link them
take_profit = LimitOrder(action='SELL', totalQuantity=100, price=Decimal('110'), ocaGroup='exit_bracket')
stop_loss = StopOrder(action='SELL', totalQuantity=100, stopPrice=Decimal('90'), ocaGroup='exit_bracket')

sim.submit_order(take_profit)
sim.submit_order(stop_loss)

# When either fills, the other is automatically cancelled
# Order closest to bar.open fills first when multiple could fill
```

Bar processing algorithm:
1. Expire DAY orders if date changed
2. Expire GTD orders past goodTillDate
3. Execute each active order via ExecutionEngine
4. Handle FILLED (remove), PARTIAL (promote children), PENDING (keep)

ib_insync-style usage with `on_bar` and `run()`:
```python
def strategy(bar, fills):
    # React to bar, submit orders for next bar
    if should_buy(bar):
        sim.submit_order(MarketOrder(action='BUY', totalQuantity=100))

sim.on_bar(strategy)
sim.run(historical_bars)
```

### Test Data Structure

CSV-driven formation tests in `test-data/`:
- `test-data/stop-limit/` - 8 CSV files × 11 formations = 88 price scenarios
- `test-data/trailing-stop/` - trailing stop formation data

Each CSV defines OHLC values, stop/limit prices, and expected fill outcomes.

## Code Conventions

### Financial Values
Use `decimal.Decimal` or `int` for all financial values. Never use `float`.

### IB Compatibility
Models follow Interactive Brokers naming conventions (camelCase: `orderId`, `totalQuantity`, `lmtPrice`, `auxPrice`). Use `UNSET_DOUBLE` and `UNSET_INTEGER` sentinels for optional numeric fields.

### Code Organization
- Use `# region` and `# endregion` comments for logical grouping in longer files
- File naming: singular nouns (`order.py` not `orders.py`)
- Core functions assume valid inputs; validation belongs in gateway/wrapper layer

### Testing
- TDD approach: write tests before implementation
- Use `@pytest.mark.xfail` for planned but unimplemented features
- Tests should be simple and readable