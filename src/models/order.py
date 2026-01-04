from decimal import Decimal
from dataclasses import dataclass, field
from typing import Optional, ClassVar


UNSET_DOUBLE = Decimal('inf')
UNSET_INTEGER = 2**31 - 1


@dataclass
class Order:
    """Base order class for trading."""
    
    _next_order_id: ClassVar[int] = 1
    
    orderId: int = field(init=False)
    clientId: int = 0
    action: str = ''
    totalQuantity: float = 0.0
    orderType: str = ''
    price: Decimal = UNSET_DOUBLE
    tif: str = ''
    goodTillDate: str = ''
    goodAfterTime: str = ''
    ocaGroup: str = ''
    orderRef: str = ''
    parentId: int = UNSET_INTEGER
    transmit: bool = True
    children: list['Order'] = field(default_factory=list)
    
    def __post_init__(self):
        """Auto-assign orderId after initialization."""
        self.orderId = Order._next_order_id
        Order._next_order_id += 1
    
    def add_child(self, child: 'Order') -> None:
        """Add a child order and set its parentId."""
        child.parentId = self.orderId
        self.children.append(child)


class LimitOrder(Order):
    """Limit order."""
    
    def __init__(self, action: str, totalQuantity: float, price: Decimal, **kwargs):
        super().__init__(
            orderType='LMT',
            action=action,
            totalQuantity=totalQuantity,
            price=price,
            **kwargs
        )


class MarketOrder(Order):
    """Market order."""
    
    def __init__(self, action: str, totalQuantity: float, **kwargs):
        super().__init__(
            orderType='MKT',
            action=action,
            totalQuantity=totalQuantity,
            **kwargs
        )


class StopOrder(Order):
    """Stop order implemented as Stop with Market child."""
    
    def __init__(self, action: str, totalQuantity: float, stopPrice: Decimal, **kwargs):
        # Initialize as a Stop order (parent)
        super().__init__(
            orderType='STP',
            action=action,
            totalQuantity=totalQuantity,
            price=stopPrice,
            **kwargs
        )
        
        # Create Market child order (orderId auto-assigned)
        market_child = MarketOrder(
            action=action,
            totalQuantity=totalQuantity
        )
        self.add_child(market_child)


class StopLimitOrder(Order):
    """Stop limit order implemented as Stop with Limit child."""
    
    def __init__(self, action: str, totalQuantity: float, limitPrice: Decimal, 
                 stopPrice: Decimal, **kwargs):
        # Initialize as a Stop order (parent)
        super().__init__(
            orderType='STP LMT',  # Preserve backward compatibility
            action=action,
            totalQuantity=totalQuantity,
            price=stopPrice,
            **kwargs
        )
        
        # Create Limit child order (orderId auto-assigned)
        limit_child = LimitOrder(
            action=action,
            totalQuantity=totalQuantity,
            price=limitPrice
        )
        self.add_child(limit_child)
