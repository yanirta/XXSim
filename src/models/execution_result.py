"""Execution result model for order execution outcomes."""
from dataclasses import dataclass, field

from .order import Order
from .fill import Fill


@dataclass
class ExecutionResult:
    """Result of executing one or more orders against a bar."""
    fills: list[Fill] = field(default_factory=list)
    pending_orders: list[Order] = field(default_factory=list)
    
    @property
    def status(self) -> str:
        """Derive overall status from fills and pending.
        
        Returns:
            - 'PENDING': No fills yet (order not executed or pending)
            - 'FILLED': All orders filled, nothing pending
            - 'PARTIAL': Some fills with pending orders (e.g., stop triggered, limit pending)
        """
        has_fills = len(self.fills) > 0
        has_pending = len(self.pending_orders) > 0
        
        if not has_fills and not has_pending:
            # Should never happen - at minimum order should be pending
            raise ValueError("Invalid ExecutionResult state: empty result")
        if not has_fills and has_pending:
            return 'PENDING'      # Order(s) not executed yet
        if has_fills and not has_pending:
            return 'FILLED'       # All done
        if has_fills and has_pending:
            return 'PARTIAL'      # Parent filled, children pending
        
        raise ValueError("Unexpected ExecutionResult state")
