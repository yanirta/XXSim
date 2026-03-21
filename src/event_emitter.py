"""Generic event emitter — observer pattern with fault-isolated dispatch."""

import logging
from enum import Enum
from typing import Callable

logger = logging.getLogger(__name__)


class SimulatorEvent(str, Enum):
    fill = 'fill'
    cancel = 'cancel'
    status = 'status'
    bar = 'bar'


class EventEmitter:
    """Register and emit named events with multiple subscribers.

    Each callback is invoked inside a try/except so a failing subscriber
    never blocks other subscribers or the emitter.
    """

    def __init__(self):
        self._callbacks: dict[str, list[Callable]] = {}

    def on(self, event: str, callback: Callable) -> None:
        """Register a callback for a named event."""
        if event not in self._callbacks:
            self._callbacks[event] = []
        self._callbacks[event].append(callback)

    def off(self, event: str, callback: Callable) -> None:
        """Remove a previously registered callback for a named event."""
        if event in self._callbacks:
            self._callbacks[event].remove(callback)

    def emit(self, event: str, *args) -> None:
        """Invoke all callbacks registered for the event."""
        for callback in self._callbacks.get(event, []):
            try:
                callback(*args)
            except Exception:
                logger.exception("Error in %s callback %s", event, getattr(callback, '__name__', repr(callback)))
