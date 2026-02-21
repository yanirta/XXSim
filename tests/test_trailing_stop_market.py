"""Tests for TrailingStopMarket order execution.

These tests verify the trailing stop mechanism:
1. State initialization (extremePrice, currentStopPrice)
2. State updates as price moves favorably
3. Dual-trigger logic (bar crosses BOTH old_stop AND new_stop)
4. Child MarketOrder execution when triggered
5. Both fixed distance and percentage modes
"""
from datetime import datetime
import pytest
import csv
from pathlib import Path

from xtrading_models import TrailingStopMarket, BarData
from execEngine import ExecutionEngine


@pytest.fixture
def engine():
    """Execution engine instance."""
    return ExecutionEngine()


def load_formations(csv_file):
    """Load formation test cases from CSV file.
    
    Returns list of dicts with keys: Formation, Open, High, Low, Close,
    TrailingDistance, TrailingPercent, CarriedExtremePrice, StopFill, OrderFill
    """
    csv_path = Path(__file__).parent.parent / "test-data" / "trailing-stop" / csv_file
    formations = []
    
    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Strip whitespace from keys and values
            row = {k.strip(): v.strip() for k, v in row.items()}
            
            # Convert numeric fields
            formation = {
                'Formation': row['Formation'],
                'Open': float(row['Open']),
                'High': float(row['High']),
                'Low': float(row['Low']),
                'Close': float(row['Close']),
                'TrailingDistance': float(row['TrailingDistance']) if row['TrailingDistance'] else None,
                'TrailingPercent': float(row['TrailingPercent']) if row['TrailingPercent'] else None,
                'CarriedExtremePrice': float(row['CarriedExtremePrice']) if row['CarriedExtremePrice'] else None,
                'StopFill': row['StopFill'],
                'OrderFill': row['OrderFill'],
            }
            formations.append(formation)
    
    return formations



# Load all formations from CSV
buy_formations = load_formations('Buy-trailing-stop-market-Formations.csv')
sell_formations = load_formations('Sell-trailing-stop-market-Formations.csv')


@pytest.mark.parametrize("formation", buy_formations, ids=[f['Formation'] for f in buy_formations])
def test_buy_trailing_stop_market_execution(engine, formation):
    """Test BUY TrailingStopMarket execution for all formations."""
    bar = BarData(
        date=datetime(2025, 1, 1, 9, 30),
        open=formation['Open'],
        high=formation['High'],
        low=formation['Low'],
        close=formation['Close'],
        volume=1000000,
    )
    order = TrailingStopMarket(
        action='BUY',
        totalQuantity=100,
        trailingDistance=formation['TrailingDistance'],
        trailingPercent=formation['TrailingPercent'])
    if formation['CarriedExtremePrice']:
        order.extremePrice = formation['CarriedExtremePrice']
        if formation['TrailingDistance']:
            order.stopPrice = formation['CarriedExtremePrice'] + formation['TrailingDistance']
        else:
            order.stopPrice = formation['CarriedExtremePrice'] * (1.0 + formation['TrailingPercent'] / 100.0)
    fills = engine.execute(order, bar)
    expected_fill = formation['OrderFill']
    if expected_fill == 'No Fill':
        assert len(fills) == 0
        assert order.extremePrice is not None
        assert order.stopPrice is not None
    else:
        expected_price = float(expected_fill)
        assert len(fills) == 1
        fill = fills[0]
        assert fill.execution.price == pytest.approx(expected_price)
        assert fill.execution.shares == 100
        assert fill.order.orderType == 'TRAIL'


@pytest.mark.parametrize("formation", sell_formations, ids=[f['Formation'] for f in sell_formations])
def test_sell_trailing_stop_market_execution(engine, formation):
    """Test SELL TrailingStopMarket execution for all formations."""
    bar = BarData(
        date=datetime(2025, 1, 1, 9, 30),
        open=formation['Open'],
        high=formation['High'],
        low=formation['Low'],
        close=formation['Close'],
        volume=1000000,
    )
    order = TrailingStopMarket(
        action='SELL',
        totalQuantity=100,
        trailingDistance=formation['TrailingDistance'],
        trailingPercent=formation['TrailingPercent'])
    if formation['CarriedExtremePrice']:
        order.extremePrice = formation['CarriedExtremePrice']
        if formation['TrailingDistance']:
            order.stopPrice = formation['CarriedExtremePrice'] - formation['TrailingDistance']
        else:
            order.stopPrice = formation['CarriedExtremePrice'] * (1.0 - formation['TrailingPercent'] / 100.0)
    fills = engine.execute(order, bar)
    expected_fill = formation['OrderFill']
    if expected_fill == 'No Fill':
        assert len(fills) == 0
        assert order.extremePrice is not None
        assert order.stopPrice is not None
    else:
        expected_price = float(expected_fill)
        assert len(fills) == 1
        fill = fills[0]
        assert fill.execution.price == pytest.approx(expected_price)
        assert fill.execution.shares == 100
        assert fill.order.orderType == 'TRAIL'


# Add specific edge case tests if needed
def test_trailing_stop_market_state_initialization(engine):
    """Verify trailing stop initializes state on first bar."""
    order = TrailingStopMarket(
        action='BUY',
        totalQuantity=100,
        trailingDistance=10.0
    )
    
    bar = BarData(
        date=datetime(2025, 1, 1, 9, 30),
        open=100.0,
        high=105.0,
        low=95.0,
        close=102.0,
        volume=1000000,
    )
    
    # Before execution, state should be None
    assert order.extremePrice is None
    assert order.stopPrice is None
    
    fills = engine.execute(order, bar)

    # After execution, verify state initialization (mutated in-place)
    if not fills:
        assert order.extremePrice == 95.0  # bar.low for BUY
        assert order.stopPrice == 105.0  # extremePrice + distance

