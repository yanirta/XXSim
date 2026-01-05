from decimal import Decimal
from dataclasses import dataclass
from datetime import datetime
from typing import NamedTuple, Optional

from .order import Order


@dataclass
class Execution:
    """Record of an order execution."""
    
    execId: str = ''
    time: Optional[datetime] = None
    acctNumber: str = ''
    exchange: str = ''
    side: str = ''
    shares: float = 0.0
    price: Decimal = Decimal('0')
    permId: int = 0
    clientId: int = 0
    orderId: int = 0
    liquidation: int = 0
    cumQty: float = 0.0
    avgPrice: Decimal = Decimal('0')
    orderRef: str = ''
    evRule: str = ''
    evMultiplier: float = 0.0
    modelCode: str = ''
    lastLiquidity: int = 0


@dataclass
class CommissionReport:
    """Commission and P&L information for an execution."""
    
    execId: str = ''
    commission: Decimal = Decimal('0')
    currency: str = ''
    realizedPNL: Decimal = Decimal('0')
    yield_: float = 0.0
    yieldRedemptionDate: int = 0


class Fill(NamedTuple):
    """
    Combines order, execution, and commission into a single record.
    IB-compatible nested object.
    """
    
    order: Order
    execution: Execution
    commissionReport: CommissionReport
    time: datetime
    parentId: int = 0
