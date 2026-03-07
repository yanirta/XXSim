"""Shared test fixtures for XXSim tests."""

from datetime import datetime, date

import pytest

from xtrading_models import TimeProvider


class StubTimeProvider(TimeProvider):
    """TimeProvider that returns a fixed time, adjustable via set_time()."""

    def __init__(self):
        self._current_time: datetime = datetime(2024, 1, 15, 9, 30)

    def set_time(self, dt: datetime):
        self._current_time = dt

    def now(self) -> datetime:
        return self._current_time

    def today(self) -> date:
        return self._current_time.date()


@pytest.fixture
def time_provider():
    return StubTimeProvider()
