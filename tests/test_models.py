from decimal import Decimal
import pytest
from models import Order, LimitOrder, MarketOrder, StopOrder, StopLimitOrder


def test_base_order():
    """Test creating a base order with manual field population."""
    order = Order(
        orderId=1,
        action='BUY',
        totalQuantity=100,
        orderType='LMT',
        lmtPrice=Decimal("150.25")
    )
    
    assert order.orderId == 1
    assert order.action == 'BUY'
    assert order.totalQuantity == 100
    assert order.orderType == 'LMT'
    assert order.lmtPrice == Decimal("150.25")


def test_limit_order():
    """Test creating a limit order."""
    order = LimitOrder(
        action='BUY',
        totalQuantity=100,
        lmtPrice=Decimal("150.25"),
        orderId=1
    )
    
    assert order.orderId == 1
    assert order.action == 'BUY'
    assert order.totalQuantity == 100
    assert order.lmtPrice == Decimal("150.25")
    assert order.orderType == 'LMT'


def test_market_order():
    """Test creating a market order."""
    order = MarketOrder(
        action='SELL',
        totalQuantity=50,
        orderId=2
    )
    
    assert order.orderId == 2
    assert order.action == 'SELL'
    assert order.totalQuantity == 50
    assert order.orderType == 'MKT'


def test_stop_order():
    """Test creating a stop order."""
    order = StopOrder(
        action='SELL',
        totalQuantity=100,
        stopPrice=Decimal("145.00"),
        orderId=3
    )
    
    assert order.orderId == 3
    assert order.action == 'SELL'
    assert order.auxPrice == Decimal("145.00")
    assert order.orderType == 'STP'


def test_stop_limit_order():
    """Test creating a stop limit order."""
    order = StopLimitOrder(
        action='BUY',
        totalQuantity=100,
        lmtPrice=Decimal("150.50"),
        stopPrice=Decimal("150.00"),
        orderId=4
    )
    
    assert order.orderId == 4
    assert order.lmtPrice == Decimal("150.50")
    assert order.auxPrice == Decimal("150.00")
    assert order.orderType == 'STP LMT'


@pytest.mark.xfail(reason="Order relationships not implemented yet")
def test_bracket_order_with_parent_child():
    """Test parent-child order relationships (bracket order)."""
    entry = StopLimitOrder('BUY', 100, Decimal("150.50"), Decimal("150.00"), orderId=1)
    
    take_profit = LimitOrder('SELL', 100, Decimal("155.00"), parentId=1, orderId=2)
    stop_loss = StopOrder('SELL', 100, Decimal("148.00"), parentId=1, orderId=3)
    
    assert take_profit.parentId == 1
    assert stop_loss.parentId == 1


@pytest.mark.xfail(reason="OCA groups not implemented yet")
def test_oca_group():
    """Test OCA (One-Cancels-All) group."""
    order1 = LimitOrder('SELL', 100, Decimal("155.00"), orderId=1, ocaGroup="EXIT_GROUP")
    order2 = StopOrder('SELL', 100, Decimal("148.00"), orderId=2, ocaGroup="EXIT_GROUP")
    
    assert order1.ocaGroup == "EXIT_GROUP"
    assert order2.ocaGroup == "EXIT_GROUP"


@pytest.mark.xfail(reason="Time-based orders not implemented yet")
def test_time_based_order():
    """Test order with time constraints."""
    order = LimitOrder(
        action='BUY',
        totalQuantity=100,
        lmtPrice=Decimal("150.00"),
        orderId=1,
        tif='GTD',
        goodTillDate='20260115 16:00:00 US/Eastern'
    )
    
    assert order.tif == 'GTD'
    assert order.goodTillDate == '20260115 16:00:00 US/Eastern'


@pytest.mark.xfail(reason="OrderRef metadata not implemented yet")
def test_order_reference():
    """Test order reference for tagging."""
    order = LimitOrder(
        action='SELL',
        totalQuantity=100,
        lmtPrice=Decimal("155.00"),
        orderId=1,
        orderRef="Take Profit"
    )
    
    assert order.orderRef == "Take Profit"
