"""Tests for volatility-based slippage model in ExecutionEngine."""
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


def slippage_engine(seed=SEED, std_divider=10):
    """Engine with slippage enabled and low std_divider for visible effect."""
    return ExecutionEngine(ExecutionConfig(
        slippage_model="normal",
        std_divider=std_divider,
        random_seed=seed,
    ))


def expected_slipped_price(fill_price: float, bar: BarData, action: str,
                           seed=SEED, std_divider=10,
                           next_fragment_price=None) -> float:
    """Compute the expected slipped price for a given seed, matching _apply_slippage logic."""
    rng = np.random.default_rng(seed)
    bar_range = bar.high - bar.low
    std = bar_range / std_divider
    magnitude = abs(rng.normal(0, std))

    if next_fragment_price is not None:
        price_moving_up = next_fragment_price > fill_price
    else:
        price_moving_up = bar.close > bar.open

    adverse_scale = 1.0
    favorable_scale = 0.25

    if action in ("BUY", "BOT"):
        adverse = price_moving_up
        slippage = magnitude * (adverse_scale if adverse else favorable_scale)
        result = fill_price + slippage
    else:
        adverse = not price_moving_up
        slippage = magnitude * (adverse_scale if adverse else favorable_scale)
        result = fill_price - slippage

    return max(bar.low, min(bar.high, result))


# region Default (no slippage) behavior

class TestNoSlippage:

    def test_default_config_no_slippage(self):
        """Default ExecutionConfig (slippage_model='none') produces exact fills."""
        engine = ExecutionEngine()
        bar = make_bar(100.0, 110.0, 90.0, 105.0)
        order = MarketOrder(action="BUY", totalQuantity=100)
        fills = engine.execute(order, bar)

        assert fills[0].execution.price == 100.0

    def test_explicit_none_no_slippage(self):
        engine = ExecutionEngine(ExecutionConfig(slippage_model="none"))
        bar = make_bar(100.0, 110.0, 90.0, 105.0)
        order = MarketOrder(action="SELL", totalQuantity=50)
        fills = engine.execute(order, bar)

        assert fills[0].execution.price == 100.0

    def test_zero_range_bar_no_slippage(self):
        """Bar with zero range (high == low) should skip slippage."""
        engine = slippage_engine()
        bar = make_bar(100.0, 100.0, 100.0, 100.0)
        order = MarketOrder(action="BUY", totalQuantity=100)
        fills = engine.execute(order, bar)

        assert fills[0].execution.price == 100.0

# endregion


# region Market order slippage

class TestMarketSlippage:

    def test_buy_bullish_bar_slippage_up(self):
        """BUY on bullish bar: adverse direction (up) → full slippage → price > open."""
        engine = slippage_engine()
        bar = make_bar(100.0, 110.0, 90.0, 108.0)  # bullish
        order = MarketOrder(action="BUY", totalQuantity=100)
        fills = engine.execute(order, bar)

        expected = expected_slipped_price(100.0, bar, "BUY")
        assert fills[0].execution.price == pytest.approx(expected)
        assert fills[0].execution.price != 100.0  # not the exact base fill
        assert fills[0].execution.price > 100.0

    def test_buy_bearish_bar_slippage_reduced(self):
        """BUY on bearish bar: favorable direction → reduced slippage → still > open but less."""
        engine_bull = slippage_engine(seed=SEED)
        engine_bear = slippage_engine(seed=SEED)

        bullish_bar = make_bar(100.0, 110.0, 90.0, 108.0)
        bearish_bar = make_bar(100.0, 110.0, 90.0, 92.0)

        buy_bull = MarketOrder(action="BUY", totalQuantity=100)
        buy_bear = MarketOrder(action="BUY", totalQuantity=100)

        fill_bull = engine_bull.execute(buy_bull, bullish_bar)[0].execution.price
        fill_bear = engine_bear.execute(buy_bear, bearish_bar)[0].execution.price

        # Both should be above open (slippage always worsens)
        assert fill_bull > 100.0
        assert fill_bear > 100.0
        # Bullish bar should have larger slippage (adverse aligned)
        assert fill_bull > fill_bear

    def test_sell_bearish_bar_slippage_down(self):
        """SELL on bearish bar: adverse direction (down) → full slippage → price < open."""
        engine = slippage_engine()
        bar = make_bar(100.0, 110.0, 90.0, 92.0)  # bearish
        order = MarketOrder(action="SELL", totalQuantity=100)
        fills = engine.execute(order, bar)

        expected = expected_slipped_price(100.0, bar, "SELL")
        assert fills[0].execution.price == pytest.approx(expected)
        assert fills[0].execution.price != 100.0  # not the exact base fill
        assert fills[0].execution.price < 100.0

    def test_sell_bullish_bar_slippage_reduced(self):
        """SELL on bullish bar: favorable direction → reduced slippage."""
        engine_bull = slippage_engine(seed=SEED)
        engine_bear = slippage_engine(seed=SEED)

        bullish_bar = make_bar(100.0, 110.0, 90.0, 108.0)
        bearish_bar = make_bar(100.0, 110.0, 90.0, 92.0)

        sell_bull = MarketOrder(action="SELL", totalQuantity=100)
        sell_bear = MarketOrder(action="SELL", totalQuantity=100)

        fill_bull = engine_bull.execute(sell_bull, bullish_bar)[0].execution.price
        fill_bear = engine_bear.execute(sell_bear, bearish_bar)[0].execution.price

        # Both below open (slippage worsens SELL)
        assert fill_bull < 100.0
        assert fill_bear < 100.0
        # Bearish bar should have larger downward slippage (adverse aligned)
        assert fill_bear < fill_bull

# endregion


# region Clamping

class TestSlippageClamping:

    def test_buy_clamped_to_bar_high(self):
        """BUY slippage should not exceed bar high."""
        # Very low std_divider for extreme slippage
        engine = slippage_engine(std_divider=2)
        bar = make_bar(100.0, 101.0, 99.0, 100.5)  # tight range
        order = MarketOrder(action="BUY", totalQuantity=100)

        # Run many times to ensure clamping
        for _ in range(50):
            engine_i = slippage_engine(seed=None, std_divider=2)
            fills = engine_i.execute(MarketOrder(action="BUY", totalQuantity=100), bar)
            assert fills[0].execution.price <= bar.high

    def test_sell_clamped_to_bar_low(self):
        """SELL slippage should not go below bar low."""
        bar = make_bar(100.0, 101.0, 99.0, 99.5)

        for _ in range(50):
            engine_i = slippage_engine(seed=None, std_divider=2)
            fills = engine_i.execute(MarketOrder(action="SELL", totalQuantity=100), bar)
            assert fills[0].execution.price >= bar.low

    def test_slippage_within_bar_range(self):
        """All slipped prices must be within [bar.low, bar.high]."""
        bar = make_bar(100.0, 105.0, 95.0, 102.0)

        for seed in range(100):
            engine = slippage_engine(seed=seed, std_divider=5)
            buy_fills = engine.execute(MarketOrder(action="BUY", totalQuantity=100), bar)
            assert bar.low <= buy_fills[0].execution.price <= bar.high

            engine2 = slippage_engine(seed=seed, std_divider=5)
            sell_fills = engine2.execute(MarketOrder(action="SELL", totalQuantity=100), bar)
            assert bar.low <= sell_fills[0].execution.price <= bar.high

# endregion


# region Limit order slippage

class TestLimitSlippage:

    def test_limit_buy_fill_gets_slippage(self):
        """Limit BUY fill price should differ from exact limit when slippage enabled."""
        engine = slippage_engine()
        bar = make_bar(100.0, 110.0, 90.0, 105.0)  # bullish
        order = LimitOrder(action="BUY", totalQuantity=100, price=95.0)
        fills = engine.execute(order, bar)

        assert len(fills) == 1
        # Limit 95 < open 100 → fills at limit=95, then slippage applied
        expected = expected_slipped_price(95.0, bar, "BUY")
        assert fills[0].execution.price == pytest.approx(expected)
        assert fills[0].execution.price != 95.0  # not the exact limit price
        assert fills[0].execution.price > 95.0

    def test_limit_sell_fill_gets_slippage(self):
        """Limit SELL fill price should differ from exact limit when slippage enabled."""
        engine = slippage_engine()
        bar = make_bar(100.0, 110.0, 90.0, 105.0)  # bullish
        order = LimitOrder(action="SELL", totalQuantity=100, price=108.0)
        fills = engine.execute(order, bar)

        assert len(fills) == 1
        # Limit 108 > open 100 → fills at limit=108, then slippage applied
        expected = expected_slipped_price(108.0, bar, "SELL")
        assert fills[0].execution.price == pytest.approx(expected)
        assert fills[0].execution.price != 108.0  # not the exact limit price

    def test_limit_buy_no_fill_unchanged(self):
        """Limit BUY that doesn't fill should still return no fills."""
        engine = slippage_engine()
        bar = make_bar(100.0, 110.0, 90.0, 105.0)
        order = LimitOrder(action="BUY", totalQuantity=100, price=85.0)  # below low
        fills = engine.execute(order, bar)

        assert len(fills) == 0

    def test_limit_buy_at_open_gets_slippage(self):
        """Limit BUY where open is already at/below limit fills at open + slippage."""
        engine = slippage_engine()
        bar = make_bar(100.0, 110.0, 90.0, 105.0)  # bullish
        # Limit above open → fills at open=100, then slippage applied
        order = LimitOrder(action="BUY", totalQuantity=100, price=102.0)
        fills = engine.execute(order, bar)

        assert len(fills) == 1
        expected = expected_slipped_price(100.0, bar, "BUY")
        assert fills[0].execution.price == pytest.approx(expected)
        assert fills[0].execution.price != 100.0  # not the exact open price
        assert fills[0].execution.price > 100.0

# endregion


# region Stop order slippage

class TestStopSlippage:

    def test_stop_buy_fill_gets_slippage(self):
        """Stop BUY fill should have slippage applied."""
        engine = slippage_engine()
        bar = make_bar(100.0, 110.0, 90.0, 108.0)  # bullish
        order = StopOrder(action="BUY", totalQuantity=100, stopPrice=105.0)
        fills = engine.execute(order, bar)

        assert len(fills) == 1
        # Stop at 105, open < 105 → base fill at 105, then slippage
        expected = expected_slipped_price(105.0, bar, "BUY")
        assert fills[0].execution.price == pytest.approx(expected)
        assert fills[0].execution.price != 105.0  # not the exact stop price
        assert fills[0].execution.price > 105.0

    def test_stop_sell_fill_gets_slippage(self):
        """Stop SELL fill should have slippage applied."""
        engine = slippage_engine()
        bar = make_bar(100.0, 110.0, 90.0, 92.0)  # bearish
        order = StopOrder(action="SELL", totalQuantity=100, stopPrice=95.0)
        fills = engine.execute(order, bar)

        assert len(fills) == 1
        # Stop at 95, open > 95 → base fill at 95, then slippage
        expected = expected_slipped_price(95.0, bar, "SELL")
        assert fills[0].execution.price == pytest.approx(expected)
        assert fills[0].execution.price != 95.0  # not the exact stop price
        assert fills[0].execution.price < 95.0

    def test_stop_no_trigger_unchanged(self):
        """Stop that doesn't trigger should still return no fills."""
        engine = slippage_engine()
        bar = make_bar(100.0, 110.0, 90.0, 105.0)
        order = StopOrder(action="BUY", totalQuantity=100, stopPrice=115.0)
        fills = engine.execute(order, bar)

        assert len(fills) == 0

    def test_stop_buy_gap_up_fills_at_open_with_slippage(self):
        """Stop BUY where open is already above stop → fills at open + slippage."""
        engine = slippage_engine()
        bar = make_bar(106.0, 110.0, 100.0, 108.0)  # bullish
        order = StopOrder(action="BUY", totalQuantity=100, stopPrice=105.0)
        fills = engine.execute(order, bar)

        assert len(fills) == 1
        # Open 106 > stop 105 → base fill at open=106, then slippage
        expected = expected_slipped_price(106.0, bar, "BUY")
        assert fills[0].execution.price == pytest.approx(expected)
        assert fills[0].execution.price != 106.0  # not the exact open price
        assert fills[0].execution.price > 106.0

# endregion


# region Stop-limit order slippage

class TestStopLimitSlippage:

    def test_stop_limit_buy_fill_gets_slippage(self):
        """Stop-limit BUY: slippage applied via _evaluate_limit_price."""
        engine = slippage_engine()
        bar = make_bar(100.0, 110.0, 90.0, 108.0)  # bullish
        order = StopLimitOrder(
            action="BUY", totalQuantity=100,
            stopPrice=105.0, limitPrice=107.0,
        )
        fills = engine.execute(order, bar)

        assert len(fills) == 1
        # Stop triggers at 105 (open<105), modified bar open=105
        # Limit 107 > modified open 105 → fills at modified open=105
        # Slippage applied to 105 on modified bar (bullish: close 108 > open 105)
        modified_bar = make_bar(105.0, 110.0, 90.0, 108.0)
        expected = expected_slipped_price(105.0, modified_bar, "BUY")
        assert fills[0].execution.price == pytest.approx(expected)
        assert fills[0].execution.price != 105.0  # not the exact trigger price

    def test_stop_limit_no_trigger_unchanged(self):
        """Stop-limit that doesn't trigger should still return no fills."""
        engine = slippage_engine()
        bar = make_bar(100.0, 110.0, 90.0, 105.0)
        order = StopLimitOrder(
            action="BUY", totalQuantity=100,
            stopPrice=115.0, limitPrice=116.0,
        )
        fills = engine.execute(order, bar)

        assert len(fills) == 0

# endregion


# region Trailing stop slippage

class TestTrailingStopSlippage:

    def test_trail_sell_uses_next_fragment_direction(self):
        """Trail SELL on bearish bar: triggered at high→low transition.
        Next fragment is lower → adverse for SELL → full slippage down."""
        engine = slippage_engine()
        # Bearish bar: fragments = [open=100, high=105, low=90, close=92]
        bar = make_bar(100.0, 105.0, 90.0, 92.0)
        order = TrailingStopMarket(action="SELL", totalQuantity=100, trailingDistance=3.0)
        fills = engine.execute(order, bar)

        assert len(fills) == 1
        # SELL trail: extreme tracks up to 105, stop=102
        # Fragment[2]=90 <= 102 → triggered, prev=105 > 102 → fill at stop=102
        # Next fragment after index 2 is close=92 (down) → adverse for SELL
        expected = expected_slipped_price(102.0, bar, "SELL", next_fragment_price=92.0)
        assert fills[0].execution.price == pytest.approx(expected)
        assert fills[0].execution.price != 102.0  # not the exact stop price

    def test_trail_buy_uses_next_fragment_direction(self):
        """Trail BUY on bullish bar: triggered at low→high transition.
        Next fragment is higher → adverse for BUY → full slippage up."""
        engine = slippage_engine()
        # Bullish bar: fragments = [open=100, low=90, high=110, close=108]
        bar = make_bar(100.0, 110.0, 90.0, 108.0)
        order = TrailingStopMarket(action="BUY", totalQuantity=100, trailingDistance=5.0)
        fills = engine.execute(order, bar)

        assert len(fills) == 1
        # BUY trail: extreme tracks down to 90, stop=95
        # Fragment[2]=110 >= 95 → triggered, prev=90 < 95 → fill at stop=95
        # Next fragment after index 2 is close=108 (up) → adverse for BUY
        expected = expected_slipped_price(95.0, bar, "BUY", next_fragment_price=108.0)
        assert fills[0].execution.price == pytest.approx(expected)
        assert fills[0].execution.price != 95.0  # not the exact stop price

    def test_trail_no_trigger_unchanged(self):
        """Trail that doesn't trigger should return no fills."""
        engine = slippage_engine()
        bar = make_bar(100.0, 101.0, 99.0, 100.5)  # very tight range
        order = TrailingStopMarket(action="BUY", totalQuantity=100, trailingDistance=50.0)
        fills = engine.execute(order, bar)

        assert fills is None or len(fills) == 0

    def test_trail_slippage_worsens_sell(self):
        """Trail SELL with slippage should fill worse than without."""
        bar = make_bar(100.0, 105.0, 90.0, 92.0)  # bearish

        # Without slippage
        engine_none = ExecutionEngine(ExecutionConfig(slippage_model="none"))
        order_none = TrailingStopMarket(action="SELL", totalQuantity=100, trailingDistance=3.0)
        fills_none = engine_none.execute(order_none, bar)
        price_none = fills_none[0].execution.price

        assert price_none == pytest.approx(102.0)  # extreme=105, stop=102

        # With slippage
        engine_slip = slippage_engine()
        order_slip = TrailingStopMarket(action="SELL", totalQuantity=100, trailingDistance=3.0)
        fills_slip = engine_slip.execute(order_slip, bar)
        price_slip = fills_slip[0].execution.price

        expected = expected_slipped_price(102.0, bar, "SELL", next_fragment_price=92.0)
        assert price_slip == pytest.approx(expected)
        assert price_slip <= price_none

    def test_trail_slippage_worsens_buy(self):
        """Trail BUY with slippage should fill worse than without."""
        bar = make_bar(100.0, 110.0, 90.0, 108.0)  # bullish

        engine_none = ExecutionEngine(ExecutionConfig(slippage_model="none"))
        order_none = TrailingStopMarket(action="BUY", totalQuantity=100, trailingDistance=5.0)
        fills_none = engine_none.execute(order_none, bar)
        price_none = fills_none[0].execution.price

        assert price_none == pytest.approx(95.0)  # extreme=90, stop=95

        engine_slip = slippage_engine()
        order_slip = TrailingStopMarket(action="BUY", totalQuantity=100, trailingDistance=5.0)
        fills_slip = engine_slip.execute(order_slip, bar)
        price_slip = fills_slip[0].execution.price

        expected = expected_slipped_price(95.0, bar, "BUY", next_fragment_price=108.0)
        assert price_slip == pytest.approx(expected)
        assert price_slip >= price_none

# endregion


# region Reproducibility

class TestSlippageReproducibility:

    def test_same_seed_same_results(self):
        """Same seed should produce identical fill prices."""
        bar = make_bar(100.0, 110.0, 90.0, 105.0)

        engine1 = slippage_engine(seed=123)
        engine2 = slippage_engine(seed=123)

        order1 = MarketOrder(action="BUY", totalQuantity=100)
        order2 = MarketOrder(action="BUY", totalQuantity=100)

        fill1 = engine1.execute(order1, bar)[0].execution.price
        fill2 = engine2.execute(order2, bar)[0].execution.price

        assert fill1 == fill2

    def test_different_seeds_different_results(self):
        """Different seeds should produce different fill prices."""
        bar = make_bar(100.0, 110.0, 90.0, 105.0)

        engine1 = slippage_engine(seed=100)
        engine2 = slippage_engine(seed=200)

        order1 = MarketOrder(action="BUY", totalQuantity=100)
        order2 = MarketOrder(action="BUY", totalQuantity=100)

        fill1 = engine1.execute(order1, bar)[0].execution.price
        fill2 = engine2.execute(order2, bar)[0].execution.price

        assert fill1 != fill2

    def test_sequential_fills_vary(self):
        """Multiple fills from same engine should vary (not all identical)."""
        engine = slippage_engine()
        bar = make_bar(100.0, 110.0, 90.0, 105.0)

        prices = []
        for _ in range(10):
            order = MarketOrder(action="BUY", totalQuantity=100)
            fills = engine.execute(order, bar)
            prices.append(fills[0].execution.price)

        # Not all prices should be the same
        assert len(set(prices)) > 1

# endregion


# region Direction logic unit tests

class TestSlippageDirection:

    def test_apply_slippage_buy_bullish_full_scale(self):
        """_apply_slippage BUY on bullish bar uses ADVERSE_SCALE (1.0)."""
        engine = slippage_engine(seed=SEED)
        bar = make_bar(100.0, 110.0, 90.0, 108.0)  # bullish
        result = engine._apply_slippage(100.0, bar, "BUY")
        expected = expected_slipped_price(100.0, bar, "BUY")
        assert result == pytest.approx(expected)

    def test_apply_slippage_buy_bearish_reduced_scale(self):
        """_apply_slippage BUY on bearish bar uses FAVORABLE_SCALE (0.25)."""
        engine = slippage_engine(seed=SEED)
        bar = make_bar(100.0, 110.0, 90.0, 92.0)  # bearish
        result = engine._apply_slippage(100.0, bar, "BUY")
        expected = expected_slipped_price(100.0, bar, "BUY")
        assert result == pytest.approx(expected)

    def test_apply_slippage_sell_bearish_full_scale(self):
        """_apply_slippage SELL on bearish bar uses ADVERSE_SCALE (1.0)."""
        engine = slippage_engine(seed=SEED)
        bar = make_bar(100.0, 110.0, 90.0, 92.0)  # bearish
        result = engine._apply_slippage(100.0, bar, "SELL")
        expected = expected_slipped_price(100.0, bar, "SELL")
        assert result == pytest.approx(expected)

    def test_apply_slippage_sell_bullish_reduced_scale(self):
        """_apply_slippage SELL on bullish bar uses FAVORABLE_SCALE (0.25)."""
        engine = slippage_engine(seed=SEED)
        bar = make_bar(100.0, 110.0, 90.0, 108.0)  # bullish
        result = engine._apply_slippage(100.0, bar, "SELL")
        expected = expected_slipped_price(100.0, bar, "SELL")
        assert result == pytest.approx(expected)

    def test_apply_slippage_with_next_fragment_up(self):
        """next_fragment_price > fill_price → price_moving_up=True → BUY adverse."""
        engine = slippage_engine(seed=SEED)
        bar = make_bar(100.0, 110.0, 90.0, 105.0)
        result = engine._apply_slippage(95.0, bar, "BUY", next_fragment_price=105.0)
        expected = expected_slipped_price(95.0, bar, "BUY", next_fragment_price=105.0)
        assert result == pytest.approx(expected)

    def test_apply_slippage_with_next_fragment_down(self):
        """next_fragment_price < fill_price → price_moving_up=False → BUY favorable."""
        engine = slippage_engine(seed=SEED)
        bar = make_bar(100.0, 110.0, 90.0, 105.0)
        result = engine._apply_slippage(105.0, bar, "BUY", next_fragment_price=95.0)
        expected = expected_slipped_price(105.0, bar, "BUY", next_fragment_price=95.0)
        assert result == pytest.approx(expected)

    def test_doji_bar_no_direction_bias(self):
        """Doji bar (open == close): price_moving_up=False → SELL adverse, BUY favorable."""
        engine = slippage_engine(seed=SEED)
        bar = make_bar(100.0, 110.0, 90.0, 100.0)  # doji
        result = engine._apply_slippage(100.0, bar, "BUY")
        expected = expected_slipped_price(100.0, bar, "BUY")
        assert result == pytest.approx(expected)

# endregion


# region Simulator integration

class TestSimulatorSlippageConfig:

    def test_simulator_passes_slippage_config(self):
        """SimulatorConfig slippage fields are passed to ExecutionEngine."""
        from simulator import Simulator, SimulatorConfig

        config = SimulatorConfig(
            slippage_model="normal",
            std_divider=50,
            random_seed=999,
        )
        sim = Simulator(config)

        assert sim._engine._config.slippage_model == "normal"
        assert sim._engine._config.std_divider == 50
        assert sim._engine._config.random_seed == 999

    def test_simulator_default_no_slippage(self):
        """Default SimulatorConfig should have no slippage."""
        from simulator import Simulator, SimulatorConfig

        sim = Simulator()

        assert sim._engine._config.slippage_model == "none"

# endregion


# region Std divider effect

class TestStdDividerEffect:

    def test_higher_divider_less_slippage(self):
        """Higher std_divider → smaller std → less slippage on average."""
        bar = make_bar(100.0, 110.0, 90.0, 108.0)

        total_slip_low_div = 0.0
        total_slip_high_div = 0.0

        for seed in range(100):
            engine_low = ExecutionEngine(ExecutionConfig(
                slippage_model="normal", std_divider=5, random_seed=seed,
            ))
            engine_high = ExecutionEngine(ExecutionConfig(
                slippage_model="normal", std_divider=100, random_seed=seed,
            ))

            fill_low = engine_low.execute(MarketOrder(action="BUY", totalQuantity=100), bar)[0].execution.price
            fill_high = engine_high.execute(MarketOrder(action="BUY", totalQuantity=100), bar)[0].execution.price

            total_slip_low_div += abs(fill_low - 100.0)
            total_slip_high_div += abs(fill_high - 100.0)

        assert total_slip_low_div > total_slip_high_div

# endregion
