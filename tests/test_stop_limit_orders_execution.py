"""Data-driven tests for stop-limit order execution using CSV formation data."""
from decimal import Decimal
from datetime import datetime
from pathlib import Path
import csv
import pytest

from xtrading_models import StopLimitOrder, BarData
from execution import ExecutionEngine


# region CSV Data Loading

def load_formation_data():
    """Load all formation data from CSV files in test-data/stop-limit/."""
    test_data_dir = Path(__file__).parent.parent / "test-data" / "stop-limit"
    
    csv_files = [
        "Buy-Bullish-Bar-Formations.csv",
        "Buy-Bearish-Bar-Formations.csv",
        "Buy-Bullish-Bar-Dipping-Formations.csv",
        "Buy-Bearish-Bar-Dipping-Formations.csv",
        "Sell-Bullish-Bar-Formations.csv",
        "Sell-Bearish-Bar-Formations.csv",
        "Sell-Bullish-Bar-Dipping-Formations.csv",
        "Sell-Bearish-Bar-Dipping-Formations.csv",
    ]
    
    test_cases = []
    
    for csv_file in csv_files:
        file_path = test_data_dir / csv_file
        
        # Parse scenario info from filename
        parts = csv_file.replace(".csv", "").split("-")
        action = parts[0].upper()  # BUY or SELL
        bar_type = parts[1].lower()  # bullish or bearish
        is_dipping = "Dipping" in csv_file
        
        scenario_name = f"{action}_{bar_type}{'_dipping' if is_dipping else ''}"
        
        with open(file_path, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                formation = row['Formation']
                
                # Create test case tuple
                test_case = (
                    scenario_name,
                    formation,
                    action,
                    bar_type,
                    Decimal(row['Open']),
                    Decimal(row['High']),
                    Decimal(row['Low']),
                    Decimal(row['Close']),
                    Decimal(row['Stop']),
                    Decimal(row['Limit']),
                    row['Stop Fill'],
                    row['Limit Fill'],
                )
                
                test_cases.append(test_case)
    
    return test_cases


def parse_fill(fill_str):
    """Parse fill string like 'Stop (100)', 'Open (105)', 'Limit (200)', or 'No fill'.
    
    Returns:
        tuple: (fill_type, fill_price) where fill_type is 'Stop', 'Open', 'Limit', or None
               and fill_price is Decimal or None
    """
    if fill_str == "No fill":
        return None, None
    
    # Extract type and price from "Type (Price)" format
    parts = fill_str.split('(')
    fill_type = parts[0].strip()
    price_str = parts[1].rstrip(')')
    fill_price = Decimal(price_str)
    
    return fill_type, fill_price


# endregion

# region Parameterized Tests

@pytest.mark.parametrize(
    "scenario,formation,action,bar_type,open_price,high,low,close,stop,limit,stop_fill_str,limit_fill_str",
    load_formation_data(),
    ids=lambda params: f"{params[0]}_{params[1]}" if isinstance(params, tuple) else str(params)
)
def test_stop_limit_formation(
    scenario, formation, action, bar_type, 
    open_price, high, low, close, stop, limit,
    stop_fill_str, limit_fill_str
):
    """Test stop-limit order execution for a specific formation.
    
    Each formation from the CSV files is tested to ensure:
    1. Correct number of fills (0, 1, or 2)
    2. Correct fill prices for stop trigger and limit execution
    3. Proper parent-child relationship (parentId)
    4. Correct pending orders for partial fills
    """
    # Setup
    bar = BarData(
        date=datetime(2025, 1, 1, 9, 30),
        open=open_price,
        high=high,
        low=low,
        close=close,
        volume=1000000,
    )
    
    order = StopLimitOrder(
        action=action,
        totalQuantity=100,
        limitPrice=limit,
        stopPrice=stop,
    )
    
    engine = ExecutionEngine()
    
    # Execute
    result = engine.execute(order, bar)
    
    # Parse expected fills
    stop_fill_type, stop_fill_price = parse_fill(stop_fill_str)
    limit_fill_type, limit_fill_price = parse_fill(limit_fill_str)
    
    # Determine expected outcomes
    if stop_fill_type is None and limit_fill_type is None:
        # No fill - order should remain pending
        assert len(result.fills) == 0, (
            f"{scenario} {formation}: Expected no fills, got {len(result.fills)}"
        )
        assert len(result.pending_orders) == 1, (
            f"{scenario} {formation}: Expected 1 pending order (parent STP LMT)"
        )
        assert result.pending_orders[0].orderType == "STP LMT"
        
    elif stop_fill_type is not None and limit_fill_type is None:
        # Partial fill - stop triggered but limit not reached
        assert len(result.fills) == 1, (
            f"{scenario} {formation}: Expected 1 fill (stop trigger), got {len(result.fills)}"
        )
        assert len(result.pending_orders) == 1, (
            f"{scenario} {formation}: Expected 1 pending order (child limit)"
        )
        
        # Validate stop trigger fill
        stop_fill = result.fills[0]
        assert stop_fill.execution.price == stop_fill_price, (
            f"{scenario} {formation}: Stop fill price mismatch. "
            f"Expected {stop_fill_price}, got {stop_fill.execution.price}"
        )
        assert stop_fill.parentId == 0, (
            f"{scenario} {formation}: Stop trigger should have parentId=0"
        )
        
        # Validate pending child order
        child_order = result.pending_orders[0]
        assert child_order.orderType == "LMT", (
            f"{scenario} {formation}: Child order should be LMT type"
        )
        assert child_order.price == limit, (
            f"{scenario} {formation}: Child limit price should be {limit}"
        )
        
    else:
        # Complete fill - both stop and limit executed
        assert len(result.fills) == 2, (
            f"{scenario} {formation}: Expected 2 fills (stop + limit), got {len(result.fills)}"
        )
        assert len(result.pending_orders) == 0, (
            f"{scenario} {formation}: Expected no pending orders after complete fill"
        )
        
        # Validate stop trigger fill (first fill)
        stop_fill = result.fills[0]
        assert stop_fill.execution.price == stop_fill_price, (
            f"{scenario} {formation}: Stop fill price mismatch. "
            f"Expected {stop_fill_price}, got {stop_fill.execution.price}"
        )
        assert stop_fill.parentId == 0, (
            f"{scenario} {formation}: Stop trigger should have parentId=0"
        )
        
        # Validate limit execution fill (second fill)
        limit_fill = result.fills[1]
        assert limit_fill.execution.price == limit_fill_price, (
            f"{scenario} {formation}: Limit fill price mismatch. "
            f"Expected {limit_fill_price}, got {limit_fill.execution.price}"
        )
        assert limit_fill.parentId == stop_fill.order.orderId, (
            f"{scenario} {formation}: Limit fill should have parentId={stop_fill.order.orderId}"
        )
        
        # Validate fill times
        assert stop_fill.time == bar.date, (
            f"{scenario} {formation}: Stop fill time should match bar date"
        )
        assert limit_fill.time == bar.date, (
            f"{scenario} {formation}: Limit fill time should match bar date"
        )


# endregion
