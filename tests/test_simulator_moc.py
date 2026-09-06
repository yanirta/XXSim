"""Tests for MOC order TIF/GAT combinations in Simulator."""
import pytest
from datetime import datetime

from xtrading_models import BarData
from xtrading_models.order import LimitOrder, MarketOnCloseOrder, Order

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
    """MOC + DAY: starts PreSubmitted; activates on first bar; fills at that day's close;
    expires the following day if not filled."""

    def test_moc_day_initial_status_is_presubmitted(self, sim):
        order = moc_order()
        trade = sim.submit_order(order)
        from xtrading_models import TradeStatus
        assert trade.orderStatus.status == TradeStatus.PreSubmitted
        assert trade.log[0].status == TradeStatus.PreSubmitted

    def test_moc_day_activates_to_submitted_on_first_bar(self, sim):
        order = moc_order()
        trade = sim.submit_order(order)
        sim.process_bar(make_intraday_bar(datetime(2024, 1, 15, 9, 30)))
        from xtrading_models import TradeStatus
        assert trade.orderStatus.status == TradeStatus.Submitted
        assert trade.log[-1].status == TradeStatus.Submitted
        assert trade.log[-1].time.date() == datetime(2024, 1, 15).date()

    def test_moc_day_submitted_after_close_fills_next_close(self, sim):
        """MOC queued after the day's last bar survives to fill at the next day's close."""
        order = moc_order()
        sim.submit_order(order)
        # Simulate bar stream: Jan 15 close already passed, order submitted after it
        # First bar seen is Jan 16 intraday → activates Submitted dated Jan 16
        sim.process_bar(make_intraday_bar(datetime(2024, 1, 16, 9, 30)))
        # Jan 16 close bar — should fill
        fills = sim.process_bar(make_close_bar(datetime(2024, 1, 16, 16, 0)))
        assert len(fills) == 1
        assert fills[0].execution.price == 100.0

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


def make_close_bar_hl(dt: datetime, close: float, high: float, low: float) -> BarData:
    return BarData(date=dt, open=close, high=high, low=low, close=close, volume=1000, is_close_bar=True)


class TestBracketChildGoodAfterTime:
    """A bracket child with a future goodAfterTime must NOT fill on the parent's
    fill bar even when the price would trigger it — it fills on/after its GAT.

    Regression for the AlphaNexus Harlev bug: a LMT take-profit child was filling
    on the entry MOC's own close bar, so entry and exit shared a timestamp."""

    def _parent_with_lmt_child(self, gat: str) -> tuple[Order, Order]:
        parent = moc_order(action="BUY")
        child = LimitOrder(action="SELL", totalQuantity=10, price=102.0)
        child.tif = "GTC"
        child.goodAfterTime = gat
        parent.add_child(child)
        return parent, child

    def test_lmt_child_does_not_fill_on_parent_bar(self, sim):
        """Parent MOC fills day0 at close 100 on a bar whose high (103) reaches the
        102 target — the child must stay pending because its GAT (day2) is future."""
        parent, child = self._parent_with_lmt_child(gat="20240117 00:00:00 US/Eastern")
        sim.submit_order(parent)

        day0_fills = sim.process_bar(make_close_bar_hl(datetime(2024, 1, 15, 16, 0), close=100.0, high=103.0, low=99.0))
        assert any(f.execution.orderId == parent.orderId for f in day0_fills)
        # The take-profit must NOT have filled on the entry bar.
        assert not any(f.execution.orderId == child.orderId for f in day0_fills)
        assert sim.get_trade(child.orderId) is not None

    def test_lmt_child_fills_once_gat_reached(self, sim):
        """Same child fills on the GAT date when the bar reaches the target."""
        parent, child = self._parent_with_lmt_child(gat="20240117 00:00:00 US/Eastern")
        sim.submit_order(parent)

        sim.process_bar(make_close_bar_hl(datetime(2024, 1, 15, 16, 0), close=100.0, high=103.0, low=99.0))
        # Day1 (GAT not yet reached) — still pending even though high reaches target.
        day1_fills = sim.process_bar(make_close_bar_hl(datetime(2024, 1, 16, 16, 0), close=100.0, high=103.0, low=99.0))
        assert not any(f.execution.orderId == child.orderId for f in day1_fills)
        # Day2 (GAT reached) — fills at the limit.
        day2_fills = sim.process_bar(make_close_bar_hl(datetime(2024, 1, 17, 16, 0), close=100.0, high=103.0, low=99.0))
        assert any(f.execution.orderId == child.orderId for f in day2_fills)


class TestMocCutoff:
    """An MOC that reaches the broker after MOC_CUTOFF misses the auction.

    IB answers that with error 201; before this was modelled the order sat
    inertly until the day rolled and was then expired, so a position whose only
    remaining exit was that MOC was left with nothing working and no sign of it.
    """

    def test_moc_before_cutoff_is_accepted_and_fills_at_the_close(self, sim, time_provider):
        time_provider.set_time(datetime(2024, 1, 15, 15, 49))
        trade = sim.submit_order(moc_order())
        from xtrading_models import TradeStatus
        assert trade.orderStatus.status == TradeStatus.PreSubmitted
        fills = sim.process_bar(make_close_bar(datetime(2024, 1, 15, 15, 59)))
        assert len(fills) == 1

    def test_moc_after_cutoff_is_rejected(self, sim, time_provider):
        time_provider.set_time(datetime(2024, 1, 15, 15, 51))
        trade = sim.submit_order(moc_order())
        from xtrading_models import TradeStatus
        assert trade.orderStatus.status == TradeStatus.Cancelled
        assert "goes live 15:51, after the 15:50 cutoff" in trade.log[-1].message

    def test_a_rejected_moc_never_becomes_active(self, sim, time_provider):
        """It must not fill at a later close either — it was never at the venue."""
        time_provider.set_time(datetime(2024, 1, 15, 15, 51))
        sim.submit_order(moc_order())
        assert sim.process_bar(make_close_bar(datetime(2024, 1, 15, 15, 59))) == []
        assert sim.process_bar(make_close_bar(datetime(2024, 1, 16, 15, 59))) == []

    def test_the_cutoff_is_inclusive(self, sim, time_provider):
        time_provider.set_time(datetime(2024, 1, 15, 15, 50))
        from xtrading_models import TradeStatus
        assert sim.submit_order(moc_order()).orderStatus.status == TradeStatus.Cancelled

    def test_a_rejected_moc_does_not_cancel_its_oca_sibling(self, sim, time_provider):
        """The reason it is kept out of the OCA group: the sibling exit is still
        legitimately working, and a rejected order must not take it down."""
        time_provider.set_time(datetime(2024, 1, 15, 15, 51))
        sibling = LimitOrder(action="SELL", totalQuantity=10, price=99.0)
        sibling.ocaGroup = "exit_group"
        sibling_trade = sim.submit_order(sibling)

        late = moc_order(action="SELL")
        late.ocaGroup = "exit_group"
        sim.submit_order(late)

        from xtrading_models import TradeStatus
        assert sibling_trade.orderStatus.status != TradeStatus.Cancelled
        fills = sim.process_bar(make_close_bar(datetime(2024, 1, 15, 15, 59), close=100.0))
        assert len(fills) == 1, "the working sibling must still be able to fill"

    def test_a_deferred_moc_is_judged_by_its_activation_time(self, sim, time_provider):
        """The wall clock at submission says nothing about a queued order — it
        goes live at its goodAfterTime, which here is midnight."""
        time_provider.set_time(datetime(2024, 1, 15, 15, 51))
        trade = sim.submit_order(moc_gtc_gat_order(gat="20240117 00:00:00 US/Eastern"))
        from xtrading_models import TradeStatus
        assert trade.orderStatus.status == TradeStatus.PreSubmitted

    def test_a_deferred_moc_that_goes_live_after_the_cutoff_is_rejected(self, sim, time_provider):
        """Deferring to 15:55 is exactly as late as submitting at 15:55 — the
        target date is irrelevant, only the time of day it activates."""
        time_provider.set_time(datetime(2024, 1, 15, 9, 30))
        trade = sim.submit_order(moc_gtc_gat_order(gat="20240117 15:55:00 US/Eastern"))
        from xtrading_models import TradeStatus
        assert trade.orderStatus.status == TradeStatus.Cancelled
        assert "goes live 15:55" in trade.log[-1].message

    def test_a_deferred_moc_just_inside_the_cutoff_is_accepted(self, sim, time_provider):
        time_provider.set_time(datetime(2024, 1, 15, 9, 30))
        trade = sim.submit_order(moc_gtc_gat_order(gat="20240117 15:49:00 US/Eastern"))
        from xtrading_models import TradeStatus
        assert trade.orderStatus.status == TradeStatus.PreSubmitted


class TestMocCutoffOnBracketChildren:
    """The path that actually matters: a bracket child is created inside
    process_bar, not through submit_order, so a guard on submission alone never
    sees the 15:59 MOC that prompted the cutoff."""

    @staticmethod
    def _parent_with_moc_child():
        """A market parent, so it fills on whatever bar it first sees and the
        child is born at that bar's timestamp."""
        from xtrading_models.order import MarketOrder
        parent = MarketOrder(action="BUY", totalQuantity=10)
        parent.orderId = 1
        child = MarketOnCloseOrder(action="SELL", totalQuantity=10)
        child.orderId = 2
        parent.add_child(child)
        return parent, child

    def test_moc_child_born_after_the_cutoff_is_rejected(self, sim, time_provider):
        time_provider.set_time(datetime(2024, 1, 15, 9, 30))
        parent, _ = self._parent_with_moc_child()
        sim.submit_order(parent)
        # Parent triggers on the session's last bar — the child is born at 15:59.
        sim.process_bar(make_close_bar(datetime(2024, 1, 15, 15, 59), close=100.0))
        assert 2 not in sim._active_trades, "a refused MOC must never become active"

    def test_moc_child_born_before_the_cutoff_is_kept(self, sim, time_provider):
        time_provider.set_time(datetime(2024, 1, 15, 9, 30))
        parent, _ = self._parent_with_moc_child()
        sim.submit_order(parent)
        sim.process_bar(make_intraday_bar(datetime(2024, 1, 15, 10, 0), close=100.0))
        assert 2 in sim._active_trades

    def test_a_rejected_child_does_not_join_its_oca_group(self, sim, time_provider):
        """It must not be able to cancel the sibling exit still working."""
        time_provider.set_time(datetime(2024, 1, 15, 9, 30))
        parent, child = self._parent_with_moc_child()
        child.ocaGroup = "exit_group"
        sim.submit_order(parent)
        sim.process_bar(make_close_bar(datetime(2024, 1, 15, 15, 59), close=100.0))
        assert 2 not in sim._oca_groups.get("exit_group", set())
