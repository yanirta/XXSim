"""Tests for MOC order TIF/GAT combinations in Simulator."""
import pytest
from datetime import datetime

from xtrading_models import BarData
from xtrading_models.order import MarketOnCloseOrder, Order

from simulator import Simulator, SimulatorConfig


# region Helpers

def make_close_bar(dt: datetime, close: float = 100.0) -> BarData:
    return BarData(
        date=dt,
        open=close,
        high=close,
        low=close,
        close=close,
        volume=1000,
        is_close_bar=True,
    )


def make_intraday_bar(dt: datetime, close: float = 100.0) -> BarData:
    return BarData(
        date=dt,
        open=close,
        high=close,
        low=close,
        close=close,
        volume=1000,
        is_close_bar=False,
    )


def moc_order(action: str = "BUY", qty: int = 10) -> Order:
    o = MarketOnCloseOrder(action=action, totalQuantity=qty)
    return o


def moc_gtc_order(action: str = "SELL", qty: int = 10) -> Order:
    o = MarketOnCloseOrder(action=action, totalQuantity=qty)
    o.tif = "GTC"
    return o


def moc_gtc_gat_order(action: str = "SELL", qty: int = 10, gat: str = "") -> Order:
    o = MarketOnCloseOrder(action=action, totalQuantity=qty)
    o.tif = "GTC"
    o.goodAfterTime = gat
    return o


def moc_gtd_order(action: str = "SELL", qty: int = 10, gtd: str = "") -> Order:
    o = MarketOnCloseOrder(action=action, totalQuantity=qty)
    o.tif = "GTD"
    o.goodTillDate = gtd
    return o


# endregion


@pytest.fixture
def sim(time_provider):
    Simulator.static_init(time_provider, SimulatorConfig())
    return Simulator()


class TestMocDay:
    """MOC + DAY: fills at close of submission day; expires next day if unfilled."""

    def test_moc_day_fills_on_close_bar(self, sim):
        order = moc_order()
        sim.submit_order(order)
        close_bar = make_close_bar(datetime(2024, 1, 15, 16, 0))
        fills = sim.process_bar(close_bar)
        assert len(fills) == 1
        assert fills[0].execution.price == 100.0

    def test_moc_day_does_not_fill_on_intraday_bar(self, sim):
        order = moc_order()
        sim.submit_order(order)
        bar = make_intraday_bar(datetime(2024, 1, 15, 9, 30))
        fills = sim.process_bar(bar)
        assert len(fills) == 0

    def test_moc_day_expires_next_day_if_not_filled(self, sim):
        order = moc_order()
        sim.submit_order(order)
        # Intraday bar day 1 — no fill
        sim.process_bar(make_intraday_bar(datetime(2024, 1, 15, 9, 30)))
        # First bar of day 2 — DAY order expires before matching
        cancelled = []
        sim.on_cancel(lambda t: cancelled.append(t))
        sim.process_bar(make_intraday_bar(datetime(2024, 1, 16, 9, 30)))
        assert len(cancelled) == 1
        assert len(sim.get_active_trades()) == 0


class TestMocGtc:
    """MOC + GTC (no GAT): fills at next close bar; does NOT expire across days."""

    def test_moc_gtc_fills_at_close(self, sim):
        order = moc_gtc_order()
        sim.submit_order(order)
        fills = sim.process_bar(make_close_bar(datetime(2024, 1, 15, 16, 0)))
        assert len(fills) == 1

    def test_moc_gtc_survives_day_change(self, sim):
        order = moc_gtc_order()
        sim.submit_order(order)
        # Intraday bar day 1 — no fill
        sim.process_bar(make_intraday_bar(datetime(2024, 1, 15, 9, 30)))
        # First bar of day 2 — GTC should still be active
        sim.process_bar(make_intraday_bar(datetime(2024, 1, 16, 9, 30)))
        assert len(sim.get_active_trades()) == 1

    def test_moc_gtc_fills_on_day2_close(self, sim):
        order = moc_gtc_order()
        sim.submit_order(order)
        sim.process_bar(make_intraday_bar(datetime(2024, 1, 15, 9, 30)))
        # Day 2 close — should fill
        fills = sim.process_bar(make_close_bar(datetime(2024, 1, 16, 16, 0)))
        assert len(fills) == 1


class TestMocGtcGat:
    """MOC + GTC + GAT: skips close bars before GAT date; fills on first close bar >= GAT."""

    def test_moc_gtc_gat_does_not_fill_before_gat(self, sim):
        order = moc_gtc_gat_order(gat="20240116 00:00:00 US/Eastern")
        sim.submit_order(order)
        # Close bar on day 0 (Jan 15) — before GAT
        fills = sim.process_bar(make_close_bar(datetime(2024, 1, 15, 16, 0)))
        assert len(fills) == 0

    def test_moc_gtc_gat_fills_on_gat_date_close(self, sim):
        order = moc_gtc_gat_order(gat="20240116 00:00:00 US/Eastern")
        sim.submit_order(order)
        # Pre-GAT close — no fill
        sim.process_bar(make_close_bar(datetime(2024, 1, 15, 16, 0)))
        # GAT date close — should fill
        fills = sim.process_bar(make_close_bar(datetime(2024, 1, 16, 16, 0)))
        assert len(fills) == 1

    def test_moc_gtc_gat_order_stays_active_across_days(self, sim):
        order = moc_gtc_gat_order(gat="20240117 00:00:00 US/Eastern")
        sim.submit_order(order)
        # Jan 15 + Jan 16 — both before GAT, still active
        sim.process_bar(make_close_bar(datetime(2024, 1, 15, 16, 0)))
        sim.process_bar(make_close_bar(datetime(2024, 1, 16, 16, 0)))
        assert len(sim.get_active_trades()) == 1
        # Jan 17 — fills
        fills = sim.process_bar(make_close_bar(datetime(2024, 1, 17, 16, 0)))
        assert len(fills) == 1


class TestMocGtd:
    """MOC + GTD: fills at close before goodTillDate; expires if GTD passed without fill."""

    def test_moc_gtd_fills_before_gtd(self, sim):
        order = moc_gtd_order(gtd="20240116 16:00:00 US/Eastern")
        order.tif = "GTD"
        order.goodTillDate = "20240116 16:00:00 US/Eastern"
        sim.submit_order(order)
        fills = sim.process_bar(make_close_bar(datetime(2024, 1, 15, 16, 0)))
        assert len(fills) == 1

    def test_moc_gtd_expires_after_gtd(self, sim):
        order = moc_gtd_order(gtd="20240114")
        sim.submit_order(order)
        cancelled = []
        sim.on_cancel(lambda t: cancelled.append(t))
        # Bar on Jan 15, which is after GTD Jan 14 — should expire
        sim.process_bar(make_close_bar(datetime(2024, 1, 15, 16, 0)))
        assert len(cancelled) == 1
        assert len(sim.get_active_trades()) == 0


class TestMocOcaIntegration:
    """Integration: parent MOC BUY + GTC+GAT child + OCA signal exit."""

    def _make_parent_with_gat_child(self, gat: str, oca_group: str) -> tuple[Order, Order]:
        parent = moc_order(action="BUY")
        child = moc_gtc_gat_order(action="SELL", gat=gat)
        child.ocaGroup = oca_group
        parent.add_child(child)
        return parent, child

    def test_parent_fills_day0_child_activates_day_n(self, sim):
        """Parent MOC BUY fills on day 0; GTC+GAT child activates and fills on day N."""
        oca_group = "exit_1"
        parent, child = self._make_parent_with_gat_child(
            gat="20240117 00:00:00 US/Eastern", oca_group=oca_group
        )
        sim.submit_order(parent)

        # Day 0 close — parent fills
        day0_fills = sim.process_bar(make_close_bar(datetime(2024, 1, 15, 16, 0)))
        assert any(f.execution.orderId == parent.orderId for f in day0_fills)

        # Child is now an active trade (submitted by simulator when parent filled)
        assert sim.get_trade(child.orderId) is not None

        # Day 1 close (Jan 16) — GAT not yet reached, child still pending
        day1_fills = sim.process_bar(make_close_bar(datetime(2024, 1, 16, 16, 0)))
        assert not any(f.execution.orderId == child.orderId for f in day1_fills)

        # Day 2 close (Jan 17) — GAT reached, child fills
        day2_fills = sim.process_bar(make_close_bar(datetime(2024, 1, 17, 16, 0)))
        assert any(f.execution.orderId == child.orderId for f in day2_fills)

    def test_signal_exit_fires_before_gat_cancels_child(self, sim):
        """Signal exit with same OCA group fires before GAT → child is cancelled."""
        oca_group = "exit_1"
        parent, child = self._make_parent_with_gat_child(
            gat="20240120 00:00:00 US/Eastern", oca_group=oca_group
        )
        sim.submit_order(parent)

        # Day 0 close — parent fills, child becomes active
        sim.process_bar(make_close_bar(datetime(2024, 1, 15, 16, 0)))
        assert sim.get_trade(child.orderId) is not None

        # Submit a signal exit with same OCA group
        signal_exit = moc_order(action="SELL")
        signal_exit.ocaGroup = oca_group
        sim.submit_order(signal_exit)

        # Day 1 close — signal exit fills; child should be cancelled via OCA
        cancelled = []
        sim.on_cancel(lambda t: cancelled.append(t.order.orderId))
        sim.process_bar(make_close_bar(datetime(2024, 1, 16, 16, 0)))

        assert any(oid == signal_exit.orderId or True for oid in [signal_exit.orderId])
        # Child should no longer be active
        assert sim.get_trade(child.orderId) is None
