"""Causality, next-open accounting, splits, and research isolation for lab v3."""
import json
import unittest
import numpy as np
import pandas as pd

from research import strategy_lab_v3 as lab


def bars(n=600, step=900_000, start="2023-01-01", seed=8):
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0004, 0.012, n)))
    opening = np.concatenate([[100.0], close[:-1]])
    return pd.DataFrame({"t": lab.ms(pd.Timestamp(start, tz="UTC")) + np.arange(n) * step,
                         "o": opening, "h": np.maximum(opening, close) * 1.01,
                         "l": np.minimum(opening, close) * 0.99, "c": close,
                         "v": rng.uniform(100, 1000, n)})


def labelled(d):
    d = d.copy()
    d["regime"], d["btc_regime"] = "RANGE", "TREND_UP"
    return d


class CausalityTest(unittest.TestCase):
    def test_holdout_and_unclosed_candles_removed_before_features(self):
        start = lab.LOCK - pd.Timedelta(hours=1)
        d = bars(12, start=str(start.date()))
        d["t"] = lab.ms(start) + np.arange(12) * lab.TF_MS["15m"]
        clipped = lab.closed_only(d, lab.TF_MS["15m"])
        self.assertEqual(len(clipped), 4)
        self.assertTrue((clipped.t + lab.TF_MS["15m"] <= lab.ms(lab.LOCK)).all())

    def test_resample_rejects_partial_hour(self):
        d = bars(7)
        result = lab.resample(d, "1h")
        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(result.c.iloc[0], d.c.iloc[3])

    def test_all_signals_and_indicators_are_prefix_invariant(self):
        d = bars(650)
        prefix = lab.features(d.iloc[:430].copy(), 900_000)
        full = lab.features(d, 900_000)
        for name in ("atr", "hi20", "lo20", "vwap", "atr_rank", "bbw_rank", "regime"):
            pd.testing.assert_series_equal(prefix[name], full[name].iloc[:430], check_names=False)
        for strategy in lab.STRATEGIES:
            if strategy == "relative_strength_rotation":
                continue
            a, b = lab.signals(prefix, strategy), lab.signals(full, strategy)
            for key in a:
                np.testing.assert_equal(a[key], b[key][:430])

    def test_btc_daily_bar_known_only_after_its_close(self):
        daily = pd.DataFrame({"t": [lab.ms(pd.Timestamp("2022-12-31", tz="UTC")),
                                    lab.ms(pd.Timestamp("2023-01-01", tz="UTC"))],
                              "regime": ["TREND_UP", "PANIC"]})
        d = lab.features(bars(97), 900_000, daily)
        self.assertEqual(d.btc_regime.iloc[0], "TREND_UP")
        self.assertEqual(d.btc_regime.iloc[94], "TREND_UP")
        self.assertEqual(d.btc_regime.iloc[95], "PANIC")
        self.assertTrue((d.btc_known_at_ms <= d.t + 900_000).all())


class ExecutionTest(unittest.TestCase):
    def fixture(self):
        step = 900_000
        d = labelled(bars(8))
        d[["o", "c"]] = 100.0
        d["h"], d["l"] = 102.0, 99.0
        d.loc[2, "o"] = 110.0  # distinct from signal close: reveals same-close fills
        d.loc[2, ["c", "h", "l"]] = [111.0, 112.0, 109.0]
        d.loc[3, ["o", "c", "h", "l"]] = [111.0, 89.0, 112.0, 88.0]
        d.loc[4, ["o", "c", "h", "l"]] = [85.0, 85.0, 86.0, 84.0]
        plan = {"enter": np.array([False, True, False, False, False, False, False, False]),
                "stop": np.full(8, 90.0), "level": np.full(8, 100.0)}
        start = pd.Timestamp("2023-01-01", tz="UTC")
        return d, plan, step, start, start + pd.Timedelta(hours=2)

    def test_next_open_gap_costs_R_and_excursions(self):
        d, plan, step, start, end = self.fixture()
        path = lab.simulate_asset(d, plan, "TEST", step, start, end)
        trade = path["trades"][0]
        entry, exit_price = 110 * (1 + lab.SLIPPAGE), 85 * (1 - lab.SLIPPAGE)
        expected = exit_price * (1 - lab.FEE) / (entry * (1 + lab.FEE)) - 1
        self.assertAlmostEqual(trade["entry_fill"], entry)
        self.assertEqual(trade["entry_ms"], d.t.iloc[2])
        self.assertEqual(trade["exit_ms"], d.t.iloc[4])
        self.assertEqual(trade["exit_reason"], "close_stop")
        self.assertAlmostEqual(trade["net_R"], (exit_price * (1 - lab.FEE) - entry * (1 + lab.FEE)) / (entry - 90))
        self.assertAlmostEqual(path["equity"][-1] - 1, expected)
        self.assertGreater(trade["MAE_R"], 1.0)
        self.assertTrue(trade["false_breakout"])
        self.assertAlmostEqual(trade["hold_hours"], 0.5)
        report = lab.summarize(path, step)
        self.assertEqual(report["execution_audit"]["entry_not_at_next_open"], 0)
        json.dumps(report, allow_nan=False)

    def test_future_prices_cannot_change_first_fill(self):
        d, plan, step, start, end = self.fixture()
        first = lab.simulate_asset(d, plan, "TEST", step, start, end)["trades"][0]
        d.loc[2:, ["h", "l", "c"]] *= 10
        changed = lab.simulate_asset(d, plan, "TEST", step, start, end)["trades"][0]
        self.assertEqual(first["entry_fill"], changed["entry_fill"])
        self.assertEqual(first["initial_stop"], changed["initial_stop"])

    def test_gap_below_stop_skips_entry(self):
        d, plan, step, start, end = self.fixture()
        d.loc[2, "o"] = 80.0
        self.assertEqual(lab.simulate_asset(d, plan, "TEST", step, start, end)["trades"], [])

    def test_period_exit_on_reserved_final_open(self):
        d, plan, step, start, end = self.fixture()
        plan["stop"][:] = 50.0
        path = lab.simulate_asset(d, plan, "TEST", step, start, end)
        self.assertEqual(path["trades"][0]["exit_ms"], d.t.iloc[-1])
        self.assertEqual(path["trades"][0]["exit_reason"], "period_end")
        self.assertEqual(path["exposure"][-1], 0)

    def test_independent_periods_do_not_carry_positions(self):
        d, plan, step, start, end = self.fixture()
        cut = start + pd.Timedelta(hours=1)
        dev = lab.simulate_asset(d, plan, "TEST", step, start, cut)
        val = lab.simulate_asset(d, plan, "TEST", step, cut, end)
        self.assertEqual(len(dev["trades"]), 1)
        self.assertEqual(len(val["trades"]), 0)
        self.assertEqual(val["equity"][0], 1)

    def test_regime_zero_cells_and_json_have_no_nan(self):
        grid = np.arange(0, 8 * 900_000, 900_000)
        report = lab.summarize(lab.empty_path(grid), 900_000)
        self.assertEqual(report["metrics"]["trade_count"], 0)
        self.assertIsNone(report["metrics"]["profit_factor"])
        self.assertEqual(report["metrics"]["CAGR"], 0)
        for regime in lab.REGIMES:
            self.assertEqual(report["by_regime"][regime]["trade_count"], 0)
            self.assertIn(regime, report["by_btc_regime"])
        json.dumps(report, allow_nan=False)

    def test_rotation_next_open_and_pnl_reconcile(self):
        # Synthetic rankings make A outrun BTC. Execution price jumps after the signal.
        start = pd.Timestamp("2023-01-01", tz="UTC")
        frames = {coin: labelled(bars(72, seed=seed)) for coin, seed in (("BTC", 4), ("A", 5), ("B", 6))}
        for coin, d in frames.items():
            d["sma200"], d["atr"], d["ret63"] = 50.0, 5.0, (0.01 if coin == "BTC" else 0.2)
        step = 900_000
        path = lab.simulate_rotation(frames, step, start, start + pd.Timedelta(hours=18))
        self.assertTrue(path["trades"])
        for trade in path["trades"]:
            k = frames[trade["symbol"].removesuffix("USDT")]
            opening = k.loc[k.t == trade["entry_ms"], "o"].iloc[0]
            self.assertAlmostEqual(trade["entry_fill"], opening * (1 + lab.SLIPPAGE))
            self.assertEqual(trade["entry_ms"], trade["signal_close_ms"])
        lab.summarize(path, step)
        self.assertAlmostEqual(sum(t["net_profit"] for t in path["trades"]), path["equity"][-1] - 1)
        self.assertTrue((path["exposure"] <= 1.0 + 1e-9).all())

    def test_cash_sleeves_include_unavailable_assets(self):
        d, plan, step, start, end = self.fixture()
        path = lab.simulate_asset(d, plan, "TEST", step, start, end)
        pooled = lab.combine_sleeves([path], 2, path["grid"])
        self.assertAlmostEqual(pooled["equity"][-1] - 1, (path["equity"][-1] - 1) / 2)
        lab.summarize(pooled, step)

    def test_rotation_rank_and_entry_ignore_future_prices(self):
        start = pd.Timestamp("2023-01-01", tz="UTC")
        frames = {coin: labelled(bars(96, seed=seed)) for coin, seed in (("BTC", 1), ("A", 2), ("B", 3), ("C", 4), ("D", 5))}
        for coin, d in frames.items():
            d["sma200"], d["atr"] = 50.0, 8.0
            d["ret63"] = {"BTC": 0.01, "A": 0.4, "B": 0.3, "C": 0.2, "D": 0.1}[coin]
        end = start + pd.Timedelta(days=1)
        original = lab.simulate_rotation(frames, 900_000, start, end)
        first_ms = min(t["entry_ms"] for t in original["trades"])
        first = sorted((t["symbol"], t["entry_fill"]) for t in original["trades"] if t["entry_ms"] == first_ms)
        self.assertEqual([symbol for symbol, _ in first], ["AUSDT", "BUSDT", "CUSDT"])
        for d in frames.values():
            d.loc[d.t > first_ms, ["c", "h", "l", "ret63", "sma200"]] *= 5
        changed = lab.simulate_rotation(frames, 900_000, start, end)
        other = sorted((t["symbol"], t["entry_fill"]) for t in changed["trades"] if t["entry_ms"] == first_ms)
        self.assertEqual(first, other)

    def test_profit_factor_uses_money_not_sum_R(self):
        grid = np.arange(0, 8 * 900_000, 900_000)
        ts = [{"net_R": 2.0, "net_profit": 0.1, "MFE_R": 3.0, "MAE_R": 0.5,
               "false_breakout_observed": False, "hold_hours": 1, "exit_reason": "close_target"},
              {"net_R": -1.0, "net_profit": -0.2, "MFE_R": 0.5, "MAE_R": 1.5,
               "false_breakout_observed": False, "hold_hours": 2, "exit_reason": "close_stop"}]
        result = lab.metrics(ts, np.ones(len(grid)), grid, np.zeros(len(grid)), 900_000)
        self.assertEqual(result["profit_factor"], 0.5)
        self.assertEqual(result["mean_R"], 0.5)


if __name__ == "__main__":
    unittest.main()
