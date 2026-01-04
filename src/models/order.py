from decimal import Decimal
from dataclasses import dataclass, field
from typing import Optional


UNSET_DOUBLE = Decimal('inf')
UNSET_INTEGER = 2**31 - 1


@dataclass
class Order:
    """Base order class for trading."""
    
    orderId: int = 0
    clientId: int = 0
    action: str = ''
    totalQuantity: float = 0.0
    orderType: str = ''
    lmtPrice: Decimal = UNSET_DOUBLE
    auxPrice: Decimal = UNSET_DOUBLE
    tif: str = ''
    goodTillDate: str = ''
    goodAfterTime: str = ''
    ocaGroup: str = ''
    orderRef: str = ''
    parentId: int = 0
    transmit: bool = True


class LimitOrder(Order):
    """Limit order."""
    
    def __init__(self, action: str, totalQuantity: float, lmtPrice: Decimal, **kwargs):
        super().__init__(
            orderType='LMT',
            action=action,
            totalQuantity=totalQuantity,
            lmtPrice=lmtPrice,
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
    """Stop order."""
    
    def __init__(self, action: str, totalQuantity: float, stopPrice: Decimal, **kwargs):
        super().__init__(
            orderType='STP',
            action=action,
            totalQuantity=totalQuantity,
            auxPrice=stopPrice,
            **kwargs
        )


class StopLimitOrder(Order):
    """Stop limit order."""
    
    def __init__(self, action: str, totalQuantity: float, lmtPrice: Decimal, 
                 stopPrice: Decimal, **kwargs):
        super().__init__(
            orderType='STP LMT',
            action=action,
            totalQuantity=totalQuantity,
            lmtPrice=lmtPrice,
            auxPrice=stopPrice,
            **kwargs
        )
