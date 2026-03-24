"""Tests for volatility-based fill drift model in ExecutionEngine."""
from datetime import datetime

import numpy as np
import pytest

from xtrading_models import BarData, MarketOrder, LimitOrder, StopOrder, StopLimitOrder
from xtrading_models.order import TrailingStopMarket
from execEngine import ExecutionEngine, ExecutionConfig


SEED = 42


def make_bar(open_, high, low, close, volume=1000000):
    return BarData(
        date=datetime(2025, 1, 1, 9, 30),
        open=open_, high=high, low=low, close=close, volume=volume,
    )


def drift_engine(seed=SEED, std_divider=10):
    """Engine with fill drift enabled and low std_divider for visible effect."""
    return ExecutionEngine(ExecutionConfig(
        fill_drift_model="normal",
        std_divider=std_divider,
        random_seed=seed,
    ))


def expected_drifted_price(fill_price: float, bar: BarData,
                           seed=SEED, std_divider=10,
                           next_fragment_price=None) -> float:
    """Compute the expected drifted price for a given seed, matching _apply_fill_drift logic."""
    rng = np.random.default_rng(seed)
    bar_range = bar.high - bar.low
    std = bar_range / std_divider
    magnitude = abs(rng.normal(0, std))

    if next_fragment_price is None:
        next_fragment_price = bar.close

    if fill_price < next_fragment_price:
        return min(fill_price + magnitude, bar.high)
    else:
        return max(fill_price - magnitude, bar.low)


# region Default (no drift) behavior

class TestNoDrift:

    def test_default_config_no_drift(self):
        """Default ExecutionConfig (fill_drift_model='none') produces exact fills."""
        engine = ExecutionEngine()
        bar = make_bar(100.0, 110.0, 90.0, 105.0)
        order = MarketOrder(action="BUY", totalQuantity=100)
        fills = engine.execute(order, bar)

        assert fills[0].execution.price == 100.0

    def test_explicit_none_no_drift(self):
        engine = ExecutionEngine(ExecutionConfig(fill_drift_model="none"))
        bar = make_bar(100.0, 110.0, 90.0, 105.0)
        order = MarketOrder(action="SELL", totalQuantity=50)
        fills = engine.execute(order, bar)

        assert fills[0].execution.price == 100.0

    def test_zero_range_bar_no_drift(self):
        """Bar with zero range (high == low) should skip drift."""
        engine = drift_engine()
        bar = make_bar(100.0, 100.0, 100.0, 100.0)
        order = MarketOrder(action="BUY", totalQuantity=100)
        fills = engine.execute(order, bar)

        assert fills[0].execution.price == 100.0

# endregion


# region Market order drift

class TestMarketDrift:

    def test_buy_bullish_bar_drift_up(self):
        """BUY on bullish bar: close > open → drift up from open."""
        engine = drift_engine()
        bar = make_bar(100.0, 110.0, 90.0, 108.0)  # bullish
        order = MarketOrder(action="BUY", totalQuantity=100)
        fills = engine.execute(order, bar)

        expected = expected_drifted_price(100.0, bar)
        assert fills[0].execution.price == pytest.approx(expected)
        assert fills[0].execution.price != 100.0
        assert fills[0].execution.price > 100.0

    def test_buy_bearish_bar_drift_down(self):
        """BUY on bearish bar: close < open → drift down from open."""
        engine = drift_engine()
        bar = make_bar(100.0, 110.0, 90.0, 92.0)  # bearish
        order = MarketOrder(action="BUY", totalQuantity=100)
        fills = engine.execute(order, bar)

        expected = expected_drifted_price(100.0, bar)
        assert fills[0].execution.price == pytest.approx(expected)
        assert fills[0].execution.price != 100.0
        assert fills[0].execution.price < 100.0

    def test_sell_bearish_bar_drift_down(self):
        """SELL on bearish bar: close < open → drift down from open."""
        engine = drift_engine()
        bar = make_bar(100.0, 110.0, 90.0, 92.0)  # bearish
        order = MarketOrder(action="SELL", totalQuantity=100)
        fills = engine.execute(order, bar)

        expected = expected_drifted_price(100.0, bar)
        assert fills[0].execution.price == pytest.approx(expected)
        assert fills[0].execution.price != 100.0
        assert fills[0].execution.price < 100.0

    def test_sell_bullish_bar_drift_up(self):
        """SELL on bullish bar: close > open → drift up from open."""
        engine = drift_engine()
        bar = make_bar(100.0, 110.0, 90.0, 108.0)  # bullish
        order = MarketOrder(action="SELL", totalQuantity=100)
        fills = engine.execute(order, bar)

        expected = expected_drifted_price(100.0, bar)
        assert fills[0].execution.price == pytest.approx(expected)
        assert fills[0].execution.price != 100.0
        assert fills[0].execution.price > 100.0

    def test_same_seed_same_drift_regardless_of_action(self):
        """Same bar, same seed → BUY and SELL get identical fill (drift is action-agnostic)."""
        bar = make_bar(100.0, 110.0, 90.0, 108.0)

        engine_buy = drift_engine(seed=SEED)
        engine_sell = drift_engine(seed=SEED)

        fill_buy = engine_buy.execute(MarketOrder(action="BUY", totalQuantity=100), bar)[0].execution.price
        fill_sell = engine_sell.execute(MarketOrder(action="SELL", totalQuantity=100), bar)[0].execution.price

        assert fill_buy == fill_sell

# endregion


# region Clamping

class TestDriftClamping:

    def test_drift_up_clamped_to_bar_high(self):
        """Upward drift should not exceed bar high."""
        bar = make_bar(100.0, 101.0, 99.0, 100.5)  # tight range, bullish

        for _ in range(50):
            engine_i = drift_engine(seed=None, std_divider=2)
            fills = engine_i.execute(MarketOrder(action="BUY", totalQuantity=100), bar)
            assert fills[0].execution.price <= bar.high

    def test_drift_down_clamped_to_bar_low(self):
        """Downward drift should not go below bar low."""
        bar = make_bar(100.0, 101.0, 99.0, 99.5)  # tight range, bearish

        for _ in range(50):
            engine_i = drift_engine(seed=None, std_divider=2)
            fills = engine_i.execute(MarketOrder(action="SELL", totalQuantity=100), bar)
            assert fills[0].execution.price >= bar.low

    def test_drift_within_bar_range(self):
        """All drifted prices must be within [bar.low, bar.high]."""
        bar = make_bar(100.0, 105.0, 95.0, 102.0)

        for seed in range(100):
            engine = drift_engine(seed=seed, std_divider=5)
            fills = engine.execute(MarketOrder(action="BUY", totalQuantity=100), bar)
            assert bar.low <= fills[0].execution.price <= bar.high

# endregion


# region Limit order drift

class TestLimitDrift:

    def test_limit_buy_fill_gets_drift(self):
        """Limit BUY fill price should differ from exact limit when drift enabled."""
        engine = drift_engine()
        bar = make_bar(100.0, 110.0, 90.0, 105.0)  # bullish
        order = LimitOrder(action="BUY", totalQuantity=100, price=95.0)
        fills = engine.execute(order, bar)

        assert len(fills) == 1
        # Limit 95 < open 100 → fills at limit=95, then drift applied
        # close(105) > fill(95) → drift up
        expected = expected_drifted_price(95.0, bar)
        assert fills[0].execution.price == pytest.approx(expected)
        assert fills[0].execution.price != 95.0
        assert fills[0].execution.price > 95.0

    def test_limit_sell_fill_gets_drift(self):
        """Limit SELL fill price should differ from exact limit when drift enabled."""
        engine = drift_engine()
        bar = make_bar(100.0, 110.0, 90.0, 105.0)  # bullish
        order = LimitOrder(action="SELL", totalQuantity=100, price=108.0)
        fills = engine.execute(order, bar)

        assert len(fills) == 1
        # Limit 108 > open 100 → fills at limit=108
        # close(105) < fill(108) → drift down
        expected = expected_drifted_price(108.0, bar)
        assert fills[0].execution.price == pytest.approx(expected)
        assert fills[0].execution.price != 108.0
        assert fills[0].execution.price < 108.0

    def test_limit_buy_no_fill_unchanged(self):
        """Limit BUY that doesn't fill should still return no fills."""
        engine = drift_engine()
        bar = make_bar(100.0, 110.0, 90.0, 105.0)
        order = LimitOrder(action="BUY", totalQuantity=100, price=85.0)  # below low
        fills = engine.execute(order, bar)

        assert len(fills) == 0

    def test_limit_buy_at_open_gets_drift(self):
        """Limit BUY where open is already at/below limit fills at open + drift."""
        engine = drift_engine()
        bar = make_bar(100.0, 110.0, 90.0, 105.0)  # bullish
        # Limit above open → fills at open=100, then drift applied
        order = LimitOrder(action="BUY", totalQuantity=100, price=102.0)
        fills = engine.execute(order, bar)

        assert len(fills) == 1
        expected = expected_drifted_price(100.0, bar)
        assert fills[0].execution.price == pytest.approx(expected)
        assert fills[0].execution.price != 100.0
        assert fills[0].execution.price > 100.0

# endregion


# region Stop order drift

class TestStopDrift:

    def test_stop_buy_fill_gets_drift(self):
        """Stop BUY fill should have drift applied."""
        engine = drift_engine()
        bar = make_bar(100.0, 110.0, 90.0, 108.0)  # bullish
        order = StopOrder(action="BUY", totalQuantity=100, stopPrice=105.0)
        fills = engine.execute(order, bar)

        assert len(fills) == 1
        # Stop at 105, open < 105 → base fill at 105
        # close(108) > fill(105) → drift up
        expected = expected_drifted_price(105.0, bar)
        assert fills[0].execution.price == pytest.approx(expected)
        assert fills[0].execution.price != 105.0
        assert fills[0].execution.price > 105.0

    def test_stop_sell_fill_gets_drift(self):
        """Stop SELL fill should have drift applied."""
        engine = drift_engine()
        bar = make_bar(100.0, 110.0, 90.0, 92.0)  # bearish
        order = StopOrder(action="SELL", totalQuantity=100, stopPrice=95.0)
        fills = engine.execute(order, bar)

        assert len(fills) == 1
        # Stop at 95, open > 95 → base fill at 95
        # close(92) < fill(95) → drift down
        expected = expected_drifted_price(95.0, bar)
        assert fills[0].execution.price == pytest.approx(expected)
        assert fills[0].execution.price != 95.0
        assert fills[0].execution.price < 95.0

    def test_stop_no_trigger_unchanged(self):
        """Stop that doesn't trigger should still return no fills."""
        engine = drift_engine()
        bar = make_bar(100.0, 110.0, 90.0, 105.0)
        order = StopOrder(action="BUY", totalQuantity=100, stopPrice=115.0)
        fills = engine.execute(order, bar)

        assert len(fills) == 0

    def test_stop_buy_gap_up_fills_at_open_with_drift(self):
        """Stop BUY where open is already above stop → fills at open + drift."""
        engine = drift_engine()
        bar = make_bar(106.0, 110.0, 100.0, 108.0)  # bullish
        order = StopOrder(action="BUY", totalQuantity=100, stopPrice=105.0)
        fills = engine.execute(order, bar)

        assert len(fills) == 1
        # Open 106 > stop 105 → base fill at open=106
        # close(108) > fill(106) → drift up
        expected = expected_drifted_price(106.0, bar)
        assert fills[0].execution.price == pytest.approx(expected)
        assert fills[0].execution.price != 106.0
        assert fills[0].execution.price > 106.0

# endregion


# region Stop-limit order drift

class TestStopLimitDrift:

    def test_stop_limit_buy_fill_gets_drift(self):
        """Stop-limit BUY: drift applied via _evaluate_limit_price."""
        engine = drift_engine()
        bar = make_bar(100.0, 110.0, 90.0, 108.0)  # bullish
        order = StopLimitOrder(
            action="BUY", totalQuantity=100,
            stopPrice=105.0, limitPrice=107.0,
        )
        fills = engine.execute(order, bar)

        assert len(fills) == 1
        # Stop triggers at 105 (open<105), modified bar open=105
        # Limit 107 > modified open 105 → fills at modified open=105
        # close(108) > fill(105) → drift up
        modified_bar = make_bar(105.0, 110.0, 90.0, 108.0)
        expected = expected_drifted_price(105.0, modified_bar)
        assert fills[0].execution.price == pytest.approx(expected)
        assert fills[0].execution.price != 105.0

    def test_stop_limit_no_trigger_unchanged(self):
        """Stop-limit that doesn't trigger should still return no fills."""
        engine = drift_engine()
        bar = make_bar(100.0, 110.0, 90.0, 105.0)
        order = StopLimitOrder(
            action="BUY", totalQuantity=100,
            stopPrice=115.0, limitPrice=116.0,
        )
        fills = engine.execute(order, bar)

        assert len(fills) == 0

# endregion


# region Trailing stop drift

class TestTrailingStopDrift:

    def test_trail_sell_uses_next_fragment_direction(self):
        """Trail SELL on bearish bar: triggered at high→low transition.
        Next fragment is lower → drift down."""
        engine = drift_engine()
        # Bearish bar: fragments = [open=100, high=105, low=90, close=92]
        bar = make_bar(100.0, 105.0, 90.0, 92.0)
        order = TrailingStopMarket(action="SELL", totalQuantity=100, trailingDistance=3.0)
        fills = engine.execute(order, bar)

        assert len(fills) == 1
        # SELL trail: extreme tracks up to 105, stop=102
        # Fragment[2]=90 <= 102 → triggered, prev=105 > 102 → fill at stop=102
        # Next fragment after index 2 is close=92, 92 < 102 → drift down
        expected = expected_drifted_price(102.0, bar, next_fragment_price=92.0)
        assert fills[0].execution.price == pytest.approx(expected)
        assert fills[0].execution.price != 102.0

    def test_trail_buy_uses_next_fragment_direction(self):
        """Trail BUY on bullish bar: triggered at low→high transition.
        Next fragment is higher → drift up."""
        engine = drift_engine()
        # Bullish bar: fragments = [open=100, low=90, high=110, close=108]
        bar = make_bar(100.0, 110.0, 90.0, 108.0)
        order = TrailingStopMarket(action="BUY", totalQuantity=100, trailingDistance=5.0)
        fills = engine.execute(order, bar)

        assert len(fills) == 1
        # BUY trail: extreme tracks down to 90, stop=95
        # Fragment[2]=110 >= 95 → triggered, prev=90 < 95 → fill at stop=95
        # Next fragment after index 2 is close=108, 108 > 95 → drift up
        expected = expected_drifted_price(95.0, bar, next_fragment_price=108.0)
        assert fills[0].execution.price == pytest.approx(expected)
        assert fills[0].execution.price != 95.0

    def test_trail_no_trigger_unchanged(self):
        """Trail that doesn't trigger should return no fills."""
        engine = drift_engine()
        bar = make_bar(100.0, 101.0, 99.0, 100.5)  # very tight range
        order = TrailingStopMarket(action="BUY", totalQuantity=100, trailingDistance=50.0)
        fills = engine.execute(order, bar)

        assert fills is None or len(fills) == 0

    def test_trail_sell_drift_vs_no_drift(self):
        """Trail SELL with drift should differ from without."""
        bar = make_bar(100.0, 105.0, 90.0, 92.0)  # bearish

        # Without drift
        engine_none = ExecutionEngine(ExecutionConfig(fill_drift_model="none"))
        order_none = TrailingStopMarket(action="SELL", totalQuantity=100, trailingDistance=3.0)
        fills_none = engine_none.execute(order_none, bar)
        price_none = fills_none[0].execution.price

        assert price_none == pytest.approx(102.0)  # extreme=105, stop=102

        # With drift
        engine_drift = drift_engine()
        order_drift = TrailingStopMarket(action="SELL", totalQuantity=100, trailingDistance=3.0)
        fills_drift = engine_drift.execute(order_drift, bar)
        price_drift = fills_drift[0].execution.price

        # Next fragment is 92 (down from 102) → drift down
        expected = expected_drifted_price(102.0, bar, next_fragment_price=92.0)
        assert price_drift == pytest.approx(expected)
        assert price_drift != price_none

    def test_trail_buy_drift_vs_no_drift(self):
        """Trail BUY with drift should differ from without."""
        bar = make_bar(100.0, 110.0, 90.0, 108.0)  # bullish

        engine_none = ExecutionEngine(ExecutionConfig(fill_drift_model="none"))
        order_none = TrailingStopMarket(action="BUY", totalQuantity=100, trailingDistance=5.0)
        fills_none = engine_none.execute(order_none, bar)
        price_none = fills_none[0].execution.price

        assert price_none == pytest.approx(95.0)  # extreme=90, stop=95

        engine_drift = drift_engine()
        order_drift = TrailingStopMarket(action="BUY", totalQuantity=100, trailingDistance=5.0)
        fills_drift = engine_drift.execute(order_drift, bar)
        price_drift = fills_drift[0].execution.price

        # Next fragment is 108 (up from 95) → drift up
        expected = expected_drifted_price(95.0, bar, next_fragment_price=108.0)
        assert price_drift == pytest.approx(expected)
        assert price_drift != price_none

# endregion


# region Reproducibility

class TestDriftReproducibility:

    def test_same_seed_same_results(self):
        """Same seed should produce identical fill prices."""
        bar = make_bar(100.0, 110.0, 90.0, 105.0)

        engine1 = drift_engine(seed=123)
        engine2 = drift_engine(seed=123)

        fill1 = engine1.execute(MarketOrder(action="BUY", totalQuantity=100), bar)[0].execution.price
        fill2 = engine2.execute(MarketOrder(action="BUY", totalQuantity=100), bar)[0].execution.price

        assert fill1 == fill2

    def test_different_seeds_different_results(self):
        """Different seeds should produce different fill prices."""
        bar = make_bar(100.0, 110.0, 90.0, 105.0)

        engine1 = drift_engine(seed=100)
        engine2 = drift_engine(seed=200)

        fill1 = engine1.execute(MarketOrder(action="BUY", totalQuantity=100), bar)[0].execution.price
        fill2 = engine2.execute(MarketOrder(action="BUY", totalQuantity=100), bar)[0].execution.price

        assert fill1 != fill2

    def test_sequential_fills_vary(self):
        """Multiple fills from same engine should vary (not all identical)."""
        engine = drift_engine()
        bar = make_bar(100.0, 110.0, 90.0, 105.0)

        prices = []
        for _ in range(10):
            order = MarketOrder(action="BUY", totalQuantity=100)
            fills = engine.execute(order, bar)
            prices.append(fills[0].execution.price)

        assert len(set(prices)) > 1

# endregion


# region Direction logic unit tests

class TestDriftDirection:

    def test_fill_below_close_drifts_up(self):
        """fill_price < close → drift up."""
        engine = drift_engine(seed=SEED)
        bar = make_bar(100.0, 110.0, 90.0, 108.0)
        result = engine._apply_fill_drift(100.0, bar)
        expected = expected_drifted_price(100.0, bar)
        assert result == pytest.approx(expected)
        assert result > 100.0

    def test_fill_above_close_drifts_down(self):
        """fill_price > close → drift down."""
        engine = drift_engine(seed=SEED)
        bar = make_bar(100.0, 110.0, 90.0, 92.0)
        result = engine._apply_fill_drift(100.0, bar)
        expected = expected_drifted_price(100.0, bar)
        assert result == pytest.approx(expected)
        assert result < 100.0

    def test_next_fragment_up_drifts_up(self):
        """next_fragment_price > fill_price → drift up."""
        engine = drift_engine(seed=SEED)
        bar = make_bar(100.0, 110.0, 90.0, 105.0)
        result = engine._apply_fill_drift(95.0, bar, next_fragment_price=105.0)
        expected = expected_drifted_price(95.0, bar, next_fragment_price=105.0)
        assert result == pytest.approx(expected)
        assert result > 95.0

    def test_next_fragment_down_drifts_down(self):
        """next_fragment_price < fill_price → drift down."""
        engine = drift_engine(seed=SEED)
        bar = make_bar(100.0, 110.0, 90.0, 105.0)
        result = engine._apply_fill_drift(105.0, bar, next_fragment_price=95.0)
        expected = expected_drifted_price(105.0, bar, next_fragment_price=95.0)
        assert result == pytest.approx(expected)
        assert result < 105.0

    def test_doji_fill_at_close_drifts_down(self):
        """Doji bar (open == close), fill at same level → fill >= close so drift down."""
        engine = drift_engine(seed=SEED)
        bar = make_bar(100.0, 110.0, 90.0, 100.0)  # doji
        result = engine._apply_fill_drift(100.0, bar)
        expected = expected_drifted_price(100.0, bar)
        assert result == pytest.approx(expected)
        assert result < 100.0

    def test_drift_is_action_agnostic(self):
        """Same fill_price, same bar → same drift regardless of action string."""
        bar = make_bar(100.0, 110.0, 90.0, 108.0)
        engine1 = drift_engine(seed=SEED)
        engine2 = drift_engine(seed=SEED)
        result_buy = engine1._apply_fill_drift(100.0, bar)
        result_sell = engine2._apply_fill_drift(100.0, bar)
        assert result_buy == result_sell

# endregion


# region Simulator integration

class TestSimulatorDriftConfig:

    def test_simulator_passes_drift_config(self, time_provider):
        """SimulatorConfig drift fields are passed to ExecutionEngine."""
        from simulator import Simulator, SimulatorConfig

        config = SimulatorConfig(
            fill_drift_model="normal",
            std_divider=50,
            random_seed=999,
        )
        Simulator.static_init(time_provider, config)
        sim = Simulator()

        assert sim._engine._config.fill_drift_model == "normal"
        assert sim._engine._config.std_divider == 50
        assert sim._engine._config.random_seed == 999

    def test_simulator_default_no_drift(self, time_provider):
        """Default SimulatorConfig should have no drift."""
        from simulator import Simulator, SimulatorConfig

        Simulator.static_init(time_provider, SimulatorConfig())
        sim = Simulator()

        assert sim._engine._config.fill_drift_model == "none"

# endregion


# region Std divider effect

class TestStdDividerEffect:

    def test_higher_divider_less_drift(self):
        """Higher std_divider → smaller std → less drift on average."""
        bar = make_bar(100.0, 110.0, 90.0, 108.0)

        total_drift_low_div = 0.0
        total_drift_high_div = 0.0

        for seed in range(100):
            engine_low = ExecutionEngine(ExecutionConfig(
                fill_drift_model="normal", std_divider=5, random_seed=seed,
            ))
            engine_high = ExecutionEngine(ExecutionConfig(
                fill_drift_model="normal", std_divider=100, random_seed=seed,
            ))

            fill_low = engine_low.execute(MarketOrder(action="BUY", totalQuantity=100), bar)[0].execution.price
            fill_high = engine_high.execute(MarketOrder(action="BUY", totalQuantity=100), bar)[0].execution.price

            total_drift_low_div += abs(fill_low - 100.0)
            total_drift_high_div += abs(fill_high - 100.0)

        assert total_drift_low_div > total_drift_high_div

# endregion
