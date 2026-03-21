# XXSim
Exchange Execution Simulator — simulates order execution against OHLCV candlebar data.

## Disclaimer
**Own risk warning** — Execution prices are best estimations based on worst-case scenarios and statistics. There will be price differences between simulations and real-world execution. By using this package the user acknowledges consent and takes full responsibility for any implications caused by errors or misinterpretation of results.

## The challenge
The golden standard of market data comes in OHLCV candlebars (1-min, 5-min, daily, etc.). Within each bar, the intra-bar price path is unknown. Fill prices depend on rules and order formations that are hard to simulate exactly.

## The solution
XXSim reconstructs a plausible intra-bar price path from OHLC data and evaluates orders against it, producing realistic fill prices within statistical uncertainty.

## Supported order types
- `MarketOrder`
- `LimitOrder`
- `StopOrder`
- `StopLimitOrder`
- `TrailingStopMarket`
- `TrailingStopLimit`
- `MarketOnCloseOrder` (MOC) — fills at `bar.close` only on bars where `BarData.is_close_bar=True`

## Not supported
- Limit-on-Close (LOC)
- Market-if-Touched (MIT)

## Execution algorithm assumptions
- **No partial fills** — orders fill entirely or not at all
- **Aggressive approach** — order fills if there is any plausible price path through the bar that would trigger it
- **Intra-bar price path** for trailing stops:
  - Bullish bar (`close > open`): `open → low → high → close`
  - Bearish bar (`close ≤ open`): `open → high → low → close`
- **Optional fill drift** — volatility-based normal distribution drift, configurable via `SimulatorConfig`:
  - `fill_drift_model="none"` (default): deterministic fills at exact price
  - `fill_drift_model="normal"`: drift drawn from `N(0, bar_range / std_divider)`
  - Result always clamped to `[bar.low, bar.high]`
  - Use `random_seed` for reproducible backtests
- **`goodAfterTime` format**: `'%Y%m%d %H:%M:%S'` with optional timezone suffix, e.g. `'20260115 09:30:00 US/Eastern'`

## Installation

```bash
pip install XXSim
```

## Usage

### Single-Bar Execution
```python
from XXSim import ExecutionEngine
from xtrading_models import MarketOrder, BarData
from datetime import datetime

engine = ExecutionEngine()
bar = BarData(
    date=datetime(2025, 1, 1, 9, 30),
    open=100.00, high=105.00, low=95.00, close=102.00, volume=1000000,
)
order = MarketOrder(action='BUY', totalQuantity=100)
fills = engine.execute(order, bar)
print(fills)
```

### Multi-Bar Simulation
```python
from XXSim import Simulator, SimulatorConfig
from xtrading_models import MarketOrder, LimitOrder

sim = Simulator()

# Register callbacks
sim.on_fill(lambda trade, fill: print(f"Filled: {fill.execution.price}"))
sim.on_cancel(lambda trade: print(f"Cancelled: {trade.log[-1].message}"))

# Submit orders
sim.submit_order(MarketOrder(action='BUY', totalQuantity=100))
sim.submit_order(LimitOrder(action='SELL', totalQuantity=100, price=110.0))

# Process bars
for bar in historical_bars:
    fills = sim.process_bar(bar)
```

### Bracket Orders
```python
from xtrading_models import MarketOrder, StopOrder, LimitOrder

entry = MarketOrder(action='BUY', totalQuantity=100)
stop_loss = StopOrder(action='SELL', totalQuantity=100, price=95.0)
take_profit = LimitOrder(action='SELL', totalQuantity=100, price=110.0)

entry.add_child(stop_loss)
entry.add_child(take_profit)

trade = sim.submit_order(entry)
```

The Simulator supports:
- **TIF**: `GTC`, `DAY` (expires on date change), `GTD` (expires after date)
- **GAT**: `goodAfterTime` — order inactive until the specified datetime
- **OCO**: `ocaGroup` — when one order fills, linked siblings are cancelled
- **Bracket orders**: child orders activate when parent fills
- **Callbacks**: `on_fill`, `on_cancel`, `on_status`, `on_bar`
- **`SimulatorEvent`**: enum of all event names (`fill`, `cancel`, `status`, `bar`) — use instead of raw strings when subscribing via `EventEmitter` directly

## Development

### Running Tests

```bash
pytest tests/ -v
```

### Visualizations
Stop-limit and trailing test cases can be visualized:

```bash
python docs/stop-limit-chart-generator.py test-data/stop-limit/<filename.csv>
python docs/trailing-stop-chart-generator.py test-data/trailing-stop/<filename.csv>
```

### Contributing
Contributions are welcome! Please see the documentation in the `docs` folder for algorithm details and test specifications.
