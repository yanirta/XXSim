from decimal import Decimal
import pytest
from models import Order, LimitOrder, MarketOrder, StopOrder, StopLimitOrder
from models.order import UNSET_DOUBLE

# region Base Order Tests
def test_base_order():
    """Test creating a base order with manual field population."""
    order = Order(
        action='BUY',
        totalQuantity=100,
        orderType='LMT',
        price=Decimal("150.25")
    )
    
    assert order.orderId > 0  # Auto-assigned
    assert order.action == 'BUY'
    assert order.totalQuantity == 100
    assert order.orderType == 'LMT'
    assert order.price == Decimal("150.25")
    assert hasattr(order, 'children')
    assert order.children == []

def test_order_id_auto_increment():
    """Test that orderId is automatically assigned and increments."""
    order1 = Order(action='BUY', totalQuantity=100, orderType='LMT')
    order2 = Order(action='SELL', totalQuantity=50, orderType='LMT')
    order3 = Order(action='BUY', totalQuantity=25, orderType='MKT')
    
    # Each order should have unique, incrementing IDs
    assert order1.orderId > 0
    assert order2.orderId > order1.orderId
    assert order3.orderId > order2.orderId
    assert order2.orderId == order1.orderId + 1
    assert order3.orderId == order2.orderId + 1

def test_base_order_children_not_shared():
    """Test that children lists are not shared between Order instances."""
    order1 = Order(action='BUY', totalQuantity=100, orderType='LMT')
    order2 = Order(action='SELL', totalQuantity=50, orderType='LMT')
    
    child1 = Order(action='BUY', totalQuantity=25, orderType='MKT')
    child2 = Order(action='SELL', totalQuantity=30, orderType='MKT')
    
    order1.add_child(child1)
    child1.add_child(child2)
    
    # Verify parent-child relationships
    assert child1.parentId == order1.orderId
    assert child2.parentId == child1.orderId
    
    # Each order should have only its own child
    assert len(order1.children) == 1
    assert len(child1.children) == 1
    assert len(order2.children) == 0
    assert order1.children[0] is child1
    assert child1.children[0] is child2
    # Lists should not be shared
    assert order1.children is not order2.children

# endregion

# region simple orders
def test_limit_order():
    """Test creating a limit order."""
    order = LimitOrder(
        action='BUY',
        totalQuantity=100,
        price=Decimal("150.25")
    )
    
    assert order.orderId > 0
    assert order.action == 'BUY'
    assert order.totalQuantity == 100
    assert order.price == Decimal("150.25")
    assert order.orderType == 'LMT'

def test_market_order():
    """Test creating a market order."""
    order = MarketOrder(
        action='SELL',
        totalQuantity=50
    )
    
    assert order.orderId > 0
    assert order.action == 'SELL'
    assert order.totalQuantity == 50
    assert order.orderType == 'MKT'

# endregion

#region composit orders
def test_stop_order():
    """Test creating a stop order - composite structure with Market child."""
    order = StopOrder(
        action='SELL',
        totalQuantity=100,
        stopPrice=Decimal("145.00")
    )
    
    assert order.orderId > 0
    assert order.action == 'SELL'
    assert order.price == Decimal("145.00")  # Stop price in parent
    assert order.orderType == 'STP'
    # Should have Market child
    assert len(order.children) == 1
    assert order.children[0].orderType == 'MKT'
    assert order.children[0].parentId == order.orderId

def test_stop_limit_order():
    """Test creating a stop limit order - backward compatibility test."""
    order = StopLimitOrder(
        action='BUY',
        totalQuantity=100,
        limitPrice=Decimal("150.50"),
        stopPrice=Decimal("150.00")
    )
    
    assert order.orderId > 0
    # Parent has stop price, child has limit price
    assert order.price == Decimal("150.00")  # Stop price in parent
    # Child has the limit price
    assert order.children[0].price == Decimal("150.50")
    assert order.orderType == 'STP LMT'
    assert order.children[0].orderType == 'LMT'
    assert order.children[0].parentId == order.orderId

# region Child Orders Tests
def test_order_add_multiple_children():
    """Test parent can have multiple children."""
    #TODO when adding children to StopOrder/StopLimitOrder, it should go to the child, not parent
    
    # Use base Order to avoid internal children from StopOrder/StopLimitOrder
    parent = Order(action='BUY', totalQuantity=100, orderType='LMT', price=Decimal("150.00"))
    child1 = LimitOrder('SELL', 100, Decimal("155.00"))
    child2 = LimitOrder('SELL', 100, Decimal("145.00"))
    
    parent.add_child(child1)
    parent.add_child(child2)
    
    assert child1.parentId == parent.orderId
    assert child2.parentId == parent.orderId
    assert len(parent.children) == 2
    assert parent.children[0] is child1
    assert parent.children[1] is child2
# endregion