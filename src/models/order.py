from decimal import Decimal
from typing import Optional, ClassVar
from pydantic import BaseModel, Field, model_validator, field_validator


UNSET_DOUBLE = Decimal('inf')
UNSET_INTEGER = 2**31 - 1


class Order(BaseModel):
    """Base order class for trading."""
    
    model_config = {
        'arbitrary_types_allowed': True,
        'validate_assignment': True,  # Validate on mutation
    }
    
    _next_order_id: ClassVar[int] = 1
    
    orderId: int = Field(default=0)
    clientId: int = 0
    action: str = ''
    totalQuantity: float = 0.0
    orderType: str = ''
    price: Decimal = Field(default=UNSET_DOUBLE, allow_inf_nan=True)
    tif: str = ''
    goodTillDate: str = ''
    goodAfterTime: str = ''
    ocaGroup: str = ''
    orderRef: str = ''
    parentId: int = UNSET_INTEGER
    transmit: bool = True
    children: list['Order'] = Field(default_factory=list)
    
    @field_validator('price', mode='before')
    @classmethod
    def allow_unset_price(cls, v):
        """Allow UNSET_DOUBLE sentinel value."""
        return v
    
    def model_post_init(self, __context) -> None:
        """Auto-assign orderId after initialization."""
        if self.orderId == 0:
            self.orderId = Order._next_order_id
            Order._next_order_id += 1
    
    def add_child(self, child: 'Order') -> None:
        """Add a child order and set its parentId."""
        child.parentId = self.orderId
        self.children.append(child)

class LimitOrder(Order):
    """Limit order."""
    
    @field_validator('price', mode='before')
    @classmethod
    def allow_unset_price(cls, v):
        """Allow UNSET_DOUBLE sentinel value."""
        return v
    
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
    
    def __init__(self, action: str, totalQuantity: float, limitPrice: Decimal, stopPrice: Decimal, **kwargs):
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

class TrailingOrder(Order):
    """Base class for trailing orders."""
    
    trailingDistance: Optional[Decimal] = None
    trailingPercent: Optional[Decimal] = None
    stopPrice: Optional[Decimal] = None
    extremePrice: Optional[Decimal] = None

    @model_validator(mode='after')
    def validate_trailing_params(self):
        """Validate exactly one of trailingDistance or trailingPercent is set."""
        if (self.trailingDistance is None and self.trailingPercent is None) or \
           (self.trailingDistance is not None and self.trailingPercent is not None):
            raise ValueError("Exactly one of trailingDistance or trailingPercent must be specified")
        return self
    

    def __init__(self, orderType: str, action: str, totalQuantity: float, trailingDistance: Optional[Decimal] = None, trailingPercent: Optional[Decimal] = None, **kwargs):
        super().__init__(
            orderType=orderType,
            action=action,
            totalQuantity=totalQuantity,
            trailingDistance=trailingDistance, # type: ignore
            trailingPercent=trailingPercent, # type: ignore
            **kwargs
        )

class TrailingStopMarket(TrailingOrder):
    """Trailing stop market order with mutable state tracking.
    
    Tracks the extreme price and adjusts stop price as market moves favorably.
    When stop is hit, the child Market order is executed.
    
    Supports two modes (exactly one must be specified):
    - trailingDistance: Absolute trailing amount (e.g., trail by $2.00)
    - trailingPercent: Percentage trailing (e.g., trail by 2%)
    
    Attributes:
        trailingDistance: Absolute distance from extreme to stop (optional)
        trailingPercent: Percentage distance from extreme to stop (optional)
        currentStopPrice: Current stop trigger price (mutable)
        extremePrice: Best price seen so far (mutable)
        children: Contains one MarketOrder child
    """
    def __init__(self, action: str, totalQuantity: float, trailingDistance: Optional[Decimal] = None, trailingPercent: Optional[Decimal] = None, **kwargs):
        super().__init__(
            orderType='TRAIL',
            action=action,
            totalQuantity=totalQuantity,
            trailingDistance=trailingDistance,
            trailingPercent=trailingPercent,
            **kwargs
        )
        
        # Create Market child order (will be executed when stop triggers)
        market_child = MarketOrder(
            action=action,
            totalQuantity=totalQuantity
        )
        self.add_child(market_child)


class TrailingStopLimit(TrailingOrder):
    """Trailing stop limit order with mutable state tracking.
    
    Similar to TrailingStopMarket but the child is a Limit order.
    
    Supports two modes (exactly one must be specified):
    - trailingDistance: Absolute trailing amount (e.g., trail by $2.00)
    - trailingPercent: Percentage trailing (e.g., trail by 2%)
    
    Attributes:
        trailingDistance: Absolute distance from extreme to stop (optional)
        trailingPercent: Percentage distance from extreme to stop (optional)
        limitOffset: Distance from stop to limit price (always positive)
        currentStopPrice: Current stop trigger price (mutable)
        extremePrice: Best price seen so far (mutable)
        children: Contains one LimitOrder child (price set when triggered)
    """
    
    limitOffset: Decimal = Decimal('0')

    def __init__(self, action: str, totalQuantity: float,
                 limitOffset: Decimal,
                 trailingDistance: Optional[Decimal] = None,
                 trailingPercent: Optional[Decimal] = None,
                 **kwargs):
        super().__init__(
            orderType='TRAIL LIMIT',
            action=action,
            totalQuantity=totalQuantity,
            trailingDistance=trailingDistance,
            trailingPercent=trailingPercent,
            limitOffset=limitOffset,
            **kwargs
        )
        
        # Create Limit child order (price will be set when stop triggers)
        limit_child = LimitOrder(
            action=action,
            totalQuantity=totalQuantity,
            price=Decimal('0')  # Placeholder, set when stop triggers
        )
        self.add_child(limit_child)
