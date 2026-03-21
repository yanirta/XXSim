"""XSim - Stock Exchange Execution Simulator."""
from xtrading_models import (
    Order,
    LimitOrder,
    MarketOrder,
    StopOrder,
    StopLimitOrder,
    BarData,
    Execution,
    CommissionReport,
    Fill,
    Trade,
    OrderStatus,
    TradeLogEntry,
)
from .execEngine import ExecutionEngine, ExecutionConfig
from .simulator import Simulator, SimulatorConfig
from .event_emitter import SimulatorEvent

from importlib.metadata import version
__version__ = version("xxsim")

__all__ = [
    "Order",
    "LimitOrder",
    "MarketOrder",
    "StopOrder",
    "StopLimitOrder",
    "BarData",
    "Execution",
    "CommissionReport",
    "Fill",
    "Trade",
    "OrderStatus",
    "TradeLogEntry",
    "ExecutionEngine",
    "ExecutionConfig",
    "Simulator",
    "SimulatorConfig",
    "SimulatorEvent",
]
