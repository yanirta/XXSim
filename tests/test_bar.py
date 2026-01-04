from decimal import Decimal
from datetime import datetime
import pytest
from pydantic import ValidationError
from models import BarData


def test_create_bardata():
    """Test creating a basic OHLCV bar."""
    bar = BarData(
        date=datetime(2026, 1, 2, 9, 30),
        open=Decimal("150.00"),
        high=Decimal("151.50"),
        low=Decimal("149.75"),
        close=Decimal("151.00"),
        volume=1000000
    )
    
    assert bar.date == datetime(2026, 1, 2, 9, 30)
    assert bar.open == Decimal("150.00")
    assert bar.high == Decimal("151.50")
    assert bar.low == Decimal("149.75")
    assert bar.close == Decimal("151.00")
    assert bar.volume == 1000000


def test_bardata_date_required():
    """Test that date is required (cannot be None)."""
    with pytest.raises(ValidationError, match="date cannot be null|Field required"):
        BarData(
            open=Decimal("150.00"),
            high=Decimal("151.50"),
            low=Decimal("149.75"),
            close=Decimal("151.00"),
            volume=1000000
        )


def test_bardata_date_explicitly_null():
    """Test that explicitly passing None for date is rejected."""
    with pytest.raises(ValidationError, match="Input should be a valid datetime"):
        BarData(
            date=None,
            open=Decimal("150.00"),
            high=Decimal("151.50"),
            low=Decimal("149.75"),
            close=Decimal("151.00"),
            volume=1000000
        )


def test_bardata_high_less_than_low():
    """Test that High < Low is rejected."""
    with pytest.raises(ValidationError, match="High.*must be >= Low"):
        BarData(
            date=datetime(2026, 1, 2, 9, 30),
            open=Decimal("150.00"),
            high=Decimal("149.00"),  # High < Low - invalid
            low=Decimal("149.75"),
            close=Decimal("150.50"),
            volume=1000000
        )


def test_bardata_high_less_than_open():
    """Test that High < Open is rejected."""
    with pytest.raises(ValidationError, match="High.*must be >= Open"):
        BarData(
            date=datetime(2026, 1, 2, 9, 30),
            open=Decimal("151.00"),
            high=Decimal("150.00"),  # High < Open - invalid
            low=Decimal("149.75"),
            close=Decimal("150.50"),
            volume=1000000
        )


def test_bardata_high_less_than_close():
    """Test that High < Close is rejected."""
    with pytest.raises(ValidationError, match="High.*must be >= Close"):
        BarData(
            date=datetime(2026, 1, 2, 9, 30),
            open=Decimal("150.00"),
            high=Decimal("150.50"),  # High < Close - invalid
            low=Decimal("149.75"),
            close=Decimal("151.00"),
            volume=1000000
        )


def test_bardata_low_greater_than_open():
    """Test that Low > Open is rejected."""
    with pytest.raises(ValidationError, match="Low.*must be <= Open"):
        BarData(
            date=datetime(2026, 1, 2, 9, 30),
            open=Decimal("149.00"),
            high=Decimal("151.50"),
            low=Decimal("150.00"),  # Low > Open - invalid
            close=Decimal("150.50"),
            volume=1000000
        )


def test_bardata_low_greater_than_close():
    """Test that Low > Close is rejected."""
    with pytest.raises(ValidationError, match="Low.*must be <= Close"):
        BarData(
            date=datetime(2026, 1, 2, 9, 30),
            open=Decimal("150.50"),
            high=Decimal("151.50"),
            low=Decimal("150.00"),  # Low > Close - invalid
            close=Decimal("149.75"),
            volume=1000000
        )


def test_bardata_valid_edge_case_all_equal():
    """Test that all prices equal is valid (e.g., no movement)."""
    bar = BarData(
        date=datetime(2026, 1, 2, 9, 30),
        open=Decimal("150.00"),
        high=Decimal("150.00"),
        low=Decimal("150.00"),
        close=Decimal("150.00"),
        volume=100
    )
    assert bar.high == bar.low == bar.open == bar.close


def test_bardata_valid_edge_case_high_equals_open():
    """Test that High == Open is valid."""
    bar = BarData(
        date=datetime(2026, 1, 2, 9, 30),
        open=Decimal("151.50"),
        high=Decimal("151.50"),
        low=Decimal("149.75"),
        close=Decimal("150.00"),
        volume=1000
    )
    assert bar.high == bar.open


def test_bardata_valid_edge_case_low_equals_close():
    """Test that Low == Close is valid."""
    bar = BarData(
        date=datetime(2026, 1, 2, 9, 30),
        open=Decimal("151.00"),
        high=Decimal("151.50"),
        low=Decimal("149.75"),
        close=Decimal("149.75"),
        volume=1000
    )
    assert bar.low == bar.close
