from decimal import Decimal
import pytest
from models import (
    Order, LimitOrder, MarketOrder, StopOrder, StopLimitOrder,
    TrailingStopMarket, TrailingStopLimit
)
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

# region Trailing Stop Orders Tests
def test_trailing_stop_market_creation_with_amount():
    """Test creating a TrailingStopMarket order with absolute amount."""
    order = TrailingStopMarket(
        action='BUY',
        totalQuantity=100,
        trailingDistance=Decimal("2.00")
    )
    
    assert order.orderId > 0
    assert order.action == 'BUY'
    assert order.totalQuantity == 100
    assert order.orderType == 'TRAIL'
    assert order.trailingDistance == Decimal("2.00")
    assert order.trailingPercent is None
    # State should be uninitialized
    assert order.stopPrice is None
    assert order.extremePrice is None
    # Should have Market child
    assert len(order.children) == 1
    assert order.children[0].orderType == 'MKT'
    assert order.children[0].action == 'BUY'
    assert order.children[0].totalQuantity == 100
    assert order.children[0].parentId == order.orderId


def test_trailing_stop_market_creation_with_percent():
    """Test creating a TrailingStopMarket order with percentage."""
    order = TrailingStopMarket(
        action='SELL',
        totalQuantity=50,
        trailingPercent=Decimal("2.5")
    )
    
    assert order.orderId > 0
    assert order.action == 'SELL'
    assert order.totalQuantity == 50
    assert order.orderType == 'TRAIL'
    assert order.trailingDistance is None
    assert order.trailingPercent == Decimal("2.5")
    assert order.stopPrice is None
    assert order.extremePrice is None
    # Should have Market child
    assert len(order.children) == 1
    assert order.children[0].orderType == 'MKT'
    assert order.children[0].action == 'SELL'
    assert order.children[0].parentId == order.orderId


def test_trailing_stop_market_requires_one_parameter():
    """Test that TrailingStopMarket requires exactly one of trailingDistance or trailingPercent."""
    # Neither parameter - should raise
    with pytest.raises(ValueError, match="Exactly one"):
        TrailingStopMarket(action='BUY', totalQuantity=100)
    
    # Both parameters - should raise
    with pytest.raises(ValueError, match="Exactly one"):
        TrailingStopMarket(
            action='BUY',
            totalQuantity=100,
            trailingDistance=Decimal("2.00"),
            trailingPercent=Decimal("2.5")
        )


def test_trailing_stop_market_only_distance_allowed():
    """Test that TrailingStopMarket works with only trailingDistance."""
    order = TrailingStopMarket(
        action='BUY',
        totalQuantity=100,
        trailingDistance=Decimal("1.50")
    )
    assert order.trailingDistance == Decimal("1.50")
    assert order.trailingPercent is None


def test_trailing_stop_market_only_percent_allowed():
    """Test that TrailingStopMarket works with only trailingPercent."""
    order = TrailingStopMarket(
        action='SELL',
        totalQuantity=100,
        trailingPercent=Decimal("3.5")
    )
    assert order.trailingDistance is None
    assert order.trailingPercent == Decimal("3.5")


def test_trailing_stop_market_both_raises_error():
    """Test that providing both trailingDistance and trailingPercent raises ValueError."""
    with pytest.raises(ValueError, match="Exactly one of trailingDistance or trailingPercent"):
        TrailingStopMarket(
            action='BUY',
            totalQuantity=100,
            trailingDistance=Decimal("2.00"),
            trailingPercent=Decimal("2.0")
        )


def test_trailing_stop_market_neither_raises_error():
    """Test that providing neither trailingDistance nor trailingPercent raises ValueError."""
    with pytest.raises(ValueError, match="Exactly one of trailingDistance or trailingPercent"):
        TrailingStopMarket(action='BUY', totalQuantity=100)


def test_trailing_stop_market_state_mutability():
    """Test that trailing stop state can be mutated during execution."""
    order = TrailingStopMarket(
        action='SELL',
        totalQuantity=50,
        trailingDistance=Decimal("1.50")
    )
    
    # Simulate state initialization
    order.extremePrice = Decimal("100.00")
    order.stopPrice = Decimal("98.50")  # extremePrice - trailingDistance
    
    assert order.extremePrice == Decimal("100.00")
    assert order.stopPrice == Decimal("98.50")
    
    # Simulate state update (price moved higher)
    order.extremePrice = Decimal("101.00")
    order.stopPrice = Decimal("99.50")
    
    assert order.extremePrice == Decimal("101.00")
    assert order.stopPrice == Decimal("99.50")


def test_trailing_stop_limit_creation_with_amount():
    """Test creating a TrailingStopLimit order with absolute amount."""
    order = TrailingStopLimit(
        action='BUY',
        totalQuantity=100,
        trailingDistance=Decimal("2.00"),
        limitOffset=Decimal("0.50")
    )
    
    assert order.orderId > 0
    assert order.action == 'BUY'
    assert order.totalQuantity == 100
    assert order.orderType == 'TRAIL LIMIT'
    assert order.trailingDistance == Decimal("2.00")
    assert order.trailingPercent is None
    assert order.limitOffset == Decimal("0.50")
    # State should be uninitialized
    assert order.stopPrice is None
    assert order.extremePrice is None
    # Should have Limit child (price unset until triggered)
    assert len(order.children) == 1
    assert order.children[0].orderType == 'LMT'
    assert order.children[0].action == 'BUY'
    assert order.children[0].totalQuantity == 100
    assert order.children[0].parentId == order.orderId


def test_trailing_stop_limit_creation_with_percent():
    """Test creating a TrailingStopLimit order with percentage."""
    order = TrailingStopLimit(
        action='SELL',
        totalQuantity=50,
        trailingPercent=Decimal("1.5"),
        limitOffset=Decimal("0.25")
    )
    
    assert order.orderId > 0
    assert order.action == 'SELL'
    assert order.totalQuantity == 50
    assert order.orderType == 'TRAIL LIMIT'
    assert order.trailingDistance is None
    assert order.trailingPercent == Decimal("1.5")
    assert order.limitOffset == Decimal("0.25")
    assert order.stopPrice is None
    assert order.extremePrice is None
    # Should have Limit child
    assert len(order.children) == 1
    assert order.children[0].orderType == 'LMT'
    assert order.children[0].action == 'SELL'
    assert order.children[0].parentId == order.orderId


def test_trailing_stop_limit_requires_one_parameter():
    """Test that TrailingStopLimit requires exactly one of trailingDistance or trailingPercent."""
    # Neither parameter - should raise
    with pytest.raises(ValueError, match="Exactly one"):
        TrailingStopLimit(
            action='BUY',
            totalQuantity=100,
            limitOffset=Decimal("0.50")
        )
    
    # Both parameters - should raise
    with pytest.raises(ValueError, match="Exactly one"):
        TrailingStopLimit(
            action='BUY',
            totalQuantity=100,
            limitOffset=Decimal("0.50"),
            trailingDistance=Decimal("2.00"),
            trailingPercent=Decimal("2.5")
        )


def test_trailing_stop_limit_only_distance_allowed():
    """Test that TrailingStopLimit works with only trailingDistance."""
    order = TrailingStopLimit(
        action='BUY',
        totalQuantity=100,
        trailingDistance=Decimal("1.50"),
        limitOffset=Decimal("0.25")
    )
    assert order.trailingDistance == Decimal("1.50")
    assert order.trailingPercent is None
    assert order.limitOffset == Decimal("0.25")


def test_trailing_stop_limit_only_percent_allowed():
    """Test that TrailingStopLimit works with only trailingPercent."""
    order = TrailingStopLimit(
        action='SELL',
        totalQuantity=100,
        trailingPercent=Decimal("3.5"),
        limitOffset=Decimal("0.50")
    )
    assert order.trailingDistance is None
    assert order.trailingPercent == Decimal("3.5")
    assert order.limitOffset == Decimal("0.50")


def test_trailing_stop_limit_both_raises_error():
    """Test that providing both trailingDistance and trailingPercent raises ValueError."""
    with pytest.raises(ValueError, match="Exactly one of trailingDistance or trailingPercent"):
        TrailingStopLimit(
            action='BUY',
            totalQuantity=100,
            limitOffset=Decimal("0.50"),
            trailingDistance=Decimal("2.00"),
            trailingPercent=Decimal("2.0")
        )


def test_trailing_stop_limit_neither_raises_error():
    """Test that providing neither trailingDistance nor trailingPercent raises ValueError."""
    with pytest.raises(ValueError, match="Exactly one of trailingDistance or trailingPercent"):
        TrailingStopLimit(
            action='BUY',
            totalQuantity=100,
            limitOffset=Decimal("0.50")
        )


def test_trailing_stop_limit_state_mutability():
    """Test that trailing stop limit state can be mutated during execution."""
    order = TrailingStopLimit(
        action='SELL',
        totalQuantity=50,
        trailingDistance=Decimal("1.50"),
        limitOffset=Decimal("0.25")
    )
    
    # Simulate state initialization
    order.extremePrice = Decimal("100.00")
    order.stopPrice = Decimal("98.50")  # extremePrice - trailingDistance
    
    assert order.extremePrice == Decimal("100.00")
    assert order.stopPrice == Decimal("98.50")
    
    # Simulate state update
    order.extremePrice = Decimal("102.00")
    order.stopPrice = Decimal("100.50")
    
    assert order.extremePrice == Decimal("102.00")
    assert order.stopPrice == Decimal("100.50")


def test_trailing_stop_market_buy_vs_sell():
    """Test TrailingStopMarket for both BUY and SELL actions."""
    buy_order = TrailingStopMarket(
        action='BUY',
        totalQuantity=100,
        trailingDistance=Decimal("1.00")
    )
    
    sell_order = TrailingStopMarket(
        action='SELL',
        totalQuantity=100,
        trailingDistance=Decimal("1.00")
    )
    
    assert buy_order.action == 'BUY'
    assert sell_order.action == 'SELL'
    assert buy_order.trailingDistance == sell_order.trailingDistance
    assert buy_order.orderType == sell_order.orderType == 'TRAIL'


def test_trailing_stop_limit_buy_vs_sell():
    """Test TrailingStopLimit for both BUY and SELL actions."""
    buy_order = TrailingStopLimit(
        action='BUY',
        totalQuantity=100,
        trailingDistance=Decimal("1.00"),
        limitOffset=Decimal("0.25")
    )
    
    sell_order = TrailingStopLimit(
        action='SELL',
        totalQuantity=100,
        trailingDistance=Decimal("1.00"),
        limitOffset=Decimal("0.25")
    )
    
    assert buy_order.action == 'BUY'
    assert sell_order.action == 'SELL'
    assert buy_order.trailingDistance == sell_order.trailingDistance
    assert buy_order.limitOffset == sell_order.limitOffset
    assert buy_order.orderType == sell_order.orderType == 'TRAIL LIMIT'


def test_trailing_stop_orders_unique_ids():
    """Test that trailing stop orders get unique auto-incremented IDs."""
    order1 = TrailingStopMarket('BUY', 100, trailingDistance=Decimal("1.00"))
    order2 = TrailingStopLimit('SELL', 50, trailingDistance=Decimal("2.00"), limitOffset=Decimal("0.50"))
    order3 = TrailingStopMarket('SELL', 75, trailingPercent=Decimal("1.50"))
    
    # All orders should have unique IDs
    assert order1.orderId > 0
    assert order2.orderId > order1.orderId
    assert order3.orderId > order2.orderId
    
    # All should have one child with unique ID
    assert len(order1.children) == 1
    assert len(order2.children) == 1
    assert len(order3.children) == 1
    assert order1.children[0].orderId > 0
    assert order2.children[0].orderId > 0
    assert order3.children[0].orderId > 0


def test_trailing_stop_fields_are_instance_vars():
    """Test that trailingDistance, trailingPercent, etc. are instance variables, not class variables."""
    order1 = TrailingStopMarket('BUY', 100, trailingDistance=Decimal("1.00"))
    order2 = TrailingStopMarket('BUY', 100, trailingDistance=Decimal("2.00"))
    
    # Each instance should have its own trailingDistance
    assert order1.trailingDistance == Decimal("1.00")
    assert order2.trailingDistance == Decimal("2.00")
    assert order1.trailingPercent is None
    assert order2.trailingPercent is None
    
    # Mutate state on order1
    order1.stopPrice = Decimal("100.00")
    order1.extremePrice = Decimal("101.00")
    
    # order2 should not be affected
    assert order2.stopPrice is None
    assert order2.extremePrice is None
    
    # Mutate state on order2
    order2.stopPrice = Decimal("200.00")
    order2.extremePrice = Decimal("202.00")
    
    # order1 should retain its own values
    assert order1.stopPrice == Decimal("100.00")
    assert order1.extremePrice == Decimal("101.00")


def test_trailing_stop_limit_fields_are_instance_vars():
    """Test that TrailingStopLimit fields are instance variables."""
    order1 = TrailingStopLimit('SELL', 50, trailingDistance=Decimal("1.50"), limitOffset=Decimal("0.25"))
    order2 = TrailingStopLimit('SELL', 50, trailingPercent=Decimal("2.5"), limitOffset=Decimal("0.50"))
    
    # Each instance should have its own parameters
    assert order1.trailingDistance == Decimal("1.50")
    assert order1.trailingPercent is None
    assert order1.limitOffset == Decimal("0.25")
    
    assert order2.trailingDistance is None
    assert order2.trailingPercent == Decimal("2.5")
    assert order2.limitOffset == Decimal("0.50")
    
    # Mutate state independently
    order1.stopPrice = Decimal("98.50")
    order1.extremePrice = Decimal("100.00")
    
    order2.stopPrice = Decimal("195.00")
    order2.extremePrice = Decimal("200.00")
    
    # Verify no cross-contamination
    assert order1.stopPrice == Decimal("98.50")
    assert order1.extremePrice == Decimal("100.00")
    assert order2.stopPrice == Decimal("195.00")
    assert order2.extremePrice == Decimal("200.00")
# endregion