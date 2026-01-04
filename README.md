# XSim
Stock Exchange Order Execution Simulator core.
This project simulates order(s) execution based on provided market OHLCV data.

# The challange
Core Problem: Reconstructing intra-bar price movement to determine order execution.

The golden standard of market data comes in chunks of Candle-bars providing Open, High, Low, Close and Volume of predefined time range
ie. 1-minute, 5-minutes, an hour, a day, a week, a month, etc...
Within each such data-unit there is a gap of the inner price motions, unless you work with tick-by-tick data which is expensive, noisy and resource intense.

# The solution
Output: Realistic execution fills with statistical uncertainty.

XSim relies on OHLC Data to simulate the inner motion of prices within single data-unit, and attempt to perform a set of decision to execute orders in the most authentic way.

# Use cases
1. Market order - Market order executes immidiently on submission time (close to open)
1. Limit order - The algorithm will determine whether the price motion goes through the limit defined in the order, if so it will execute the order with some statistical error depends on the volatility of the candle-bar.
1. Additional types of orders: Trailing stop, StopLimitOrder, StopOrder, 
1. Supporting buy/sell(long/short) directions
1. Supporting Time In Force (Tif), goodAfterTime, goodTillDate
1. Supporting ocaGroup
1. Supporting parent/child relationships

* Working with fractional time of submission is Unsupported yet

## Installation

```bash
pip install -e .
```

## Running Tests

```bash
pytest tests/ -v
```
