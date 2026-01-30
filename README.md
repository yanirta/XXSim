# XXSim
Exchange Execution Simulator, development package.
This package simulates order(s) execution based on provided market OHLCV data.
This is not an independent package, but its the core logic required to implement backtesting when it comes on running on candlebar data.

**This is the first drop and wasn't tested out in the wild yet, more functionality and capabilities to come**

## disclaimer
**Own risk warning** - Execution prices are best estimations base on worst case scenarios and statistics, there will be price differences between simulations and real-world execution, using this package the user acknowledges his consent and takes full responsibility on the implications caused due to any error or misinterpetation of this package and it's results.

Trailing commands warning - Trailing commands are currently roughly estimated and carry high deviation from the real world

## The challenge
Core Problem: Reconstructing intra-bar price movement to determine order execution.

The golden standard of market data comes in chunks of Candle-bars providing Open, High, Low, Close and Volume of predefined time range
ie. 1-minute, 5-minutes, an hour, a day, a week, a month, etc...
Within each such data-unit there is a gap of the inner price motions, unless you work with tick-by-tick data which is expensive, noisy and resource intense.
On top of that, fill prices are results of a consiquent rules and formations that are hard to simulate.

## The solution
Output: Realistic execution fills within statistical uncertainty. or consiquent order either original or modified.

XSim relies on OHLC Data to simulate the inner motion of prices within single data-unit, and attempt to perform a set of decision to execute orders in the most authentic way.

## Supported order types
- MarketOrder
- LimitOrder
- StopOrder
- StopLimitOrder
- TrailingStopMarket

## Not supported order types (at the moment)
- Trailing Stop Limit Orders
- Market-on-Close (MOC) / Limit-on-Close (LOC)
- Bracket Orders (OCO - One-Cancels-Other)
- Market-if-Touched (MIT)
- Others...

## Current Execution algorithm assumptions
- No slippage
- No partial fills
- Aggressive approach - Order will be filled if there's a possible path between order's formation and the candlebar.
- Trail orders assume the following order of the candles:
On Bullish bar: prev_extremePrice [optional] -> open -> low -> high -> close
On Bearish bar: prev_extremePrice [optional] -> open -> high -> low -> close

## Installation

```bash
pip install XXSim
```

## Usage
Here is a minimal example of simulating a market order execution:
```python
from models import MarketOrder, BarData
from execution import ExecutionEngine
from decimal import Decimal
from datetime import datetime

engine = ExecutionEngine()
bar = BarData(
    date=datetime(2025, 1, 1, 9, 30),
    open=Decimal('100.00'),
    high=Decimal('105.00'),
    low=Decimal('95.00'),
    close=Decimal('102.00'),
    volume=1000000,
)
order = MarketOrder(action='BUY', totalQuantity=100)
result = engine.execute(order, bar)
print(result.fills)
```

## Development

## Running Tests

```bash
pytest tests/ -v
```

## Visualizations
Stop-limit and Trailing test cases can be visualized
For stop-limit visualization run:

```bash
python docs/stop-limit-chart-generator.py test-data/stop-limit/<filename.csv>
```

For trailing visualization run:

```bash
python docs/trailing-stop-chart-generator.py test-data/trailing-stop/<filename.csv>
```

TODO: Trailing cases are not organized systemactically enough

### Contributing
Contributions are welcome! Please see the documentation in the `docs` folder for more details and test specifications.