from decimal import Decimal
from datetime import datetime
import pytest
from models import Execution, CommissionReport, Fill, Order, LimitOrder


def test_create_execution():
    """Test creating an Execution record."""
    execution = Execution(
        execId='00012345.001',
        time=datetime(2026, 1, 2, 9, 30, 15),
        side='BUY',
        shares=100,
        price=Decimal("150.25"),
        orderId=1,
        cumQty=100,
        avgPrice=Decimal("150.25")
    )
    
    assert execution.execId == '00012345.001'
    assert execution.time == datetime(2026, 1, 2, 9, 30, 15)
    assert execution.side == 'BUY'
    assert execution.shares == 100
    assert execution.price == Decimal("150.25")
    assert execution.orderId == 1
    assert execution.cumQty == 100
    assert execution.avgPrice == Decimal("150.25")


def test_create_commission_report():
    """Test creating a CommissionReport."""
    report = CommissionReport(
        execId='00012345.001',
        commission=Decimal("1.00"),
        currency='USD',
        realizedPNL=Decimal("0")
    )
    
    assert report.execId == '00012345.001'
    assert report.commission == Decimal("1.00")
    assert report.currency == 'USD'
    assert report.realizedPNL == Decimal("0")


def test_create_fill():
    """Test creating a Fill (nested object)."""
    order = LimitOrder('BUY', 100, Decimal("150.00"))
    order.orderId = 1
    
    execution = Execution(
        execId='00012345.001',
        time=datetime(2026, 1, 2, 9, 30, 15),
        side='BUY',
        shares=100,
        price=Decimal("150.25"),
        orderId=1,
        cumQty=100,
        avgPrice=Decimal("150.25")
    )
    
    commission = CommissionReport(
        execId='00012345.001',
        commission=Decimal("1.00"),
        currency='USD'
    )
    
    fill = Fill(
        order=order,
        execution=execution,
        commissionReport=commission,
        time=datetime(2026, 1, 2, 9, 30, 15)
    )
    
    assert fill.order == order
    assert fill.execution.shares == 100
    assert fill.execution.price == Decimal("150.25")
    assert fill.commissionReport.commission == Decimal("1.00")
    assert fill.time == datetime(2026, 1, 2, 9, 30, 15)
