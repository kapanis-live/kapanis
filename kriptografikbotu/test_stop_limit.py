"""Order-planning layer (research/stop_limit.py) and its simulator: formulas, filters, fills, no look-ahead."""
import pathlib
import sys
import unittest
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "research"))
import stop_limit as sl  # noqa: E402
import stop_limit_bt as bt  # noqa: E402


def frame(n=400, seed=3, drift=0.0008, vol=0.02):
    """A random-walk OHLCV frame (daily, closed bars)."""
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(rng.normal(drift, vol, n)))
    o = np.concatenate([[100.0], c[:-1]]) * (1 + rng.normal(0, 0.003, n))
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.008, n)))
    l = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.008, n)))
    return pd.DataFrame({"t": 1_500_000_000_000 + np.arange(n) * 86_400_000, "o": o, "h": h, "l": l, "c": c,
                         "v": rng.uniform(800, 1200, n)})


class EntryOrderTest(unittest.TestCase):
    def test_worked_example(self):
        # resistance 84,250, ATR 650 (crypto defaults): buffer max(126.38, 65), limit buffer max(126.56, 52)
        trigger, limit = sl.entry_order(84250.0, 650.0, sl.DEFAULTS["KRIPTO"])
        self.assertAlmostEqual(trigger, 84376.375, places=3)
        self.assertAlmostEqual(limit, 84502.94, places=2)

    def test_atr_buffer_wins_when_volatile_and_limit_is_capped(self):
        p = sl.DEFAULTS["KRIPTO"]
        trigger, limit = sl.entry_order(100.0, 10.0, p)       # 0.10 * ATR = 1.0 > 0.15 % = 0.15
        self.assertAlmostEqual(trigger, 101.0)
        self.assertAlmostEqual(limit, 101.0 * 1.004)          # 0.08 * ATR = 0.8 would be 0.79 %: capped at 0.40 %

    def test_market_defaults(self):
        self.assertEqual((sl.DEFAULTS["BIST"].pct_buffer, sl.DEFAULTS["BIST"].atr_buffer, sl.DEFAULTS["BIST"].limit_cap),
                         (0.0010, 0.08, 0.0025))
        self.assertEqual(sl.DEFAULTS["ABD"], sl.DEFAULTS["BIST"])
        trigger, limit = sl.entry_order(200.0, 2.0, sl.DEFAULTS["BIST"])
        self.assertAlmostEqual(trigger, 200.2)                # max(0.20, 0.16)
        self.assertLessEqual(limit, trigger * 1.0025 + 1e-9)


class RiskTest(unittest.TestCase):
    def test_stop_uses_nearest_structure_between_1_and_3_atr(self):
        p = sl.DEFAULTS["KRIPTO"]
        stop, invalid, _ = sl.stop_level(100.0, 2.0, swing_low=97.0, sma20=99.5, sma50=93.0, p=p)
        self.assertEqual(invalid, 97.0)                       # SMA20 is inside the noise (0.25 ATR), SMA50 is 3.5 ATR away
        self.assertAlmostEqual(stop, 97.0 - 0.15 * 2.0)

    def test_stop_falls_back_to_atr_when_no_level_fits(self):
        stop, invalid, text = sl.stop_level(100.0, 2.0, float("nan"), 99.5, 80.0, sl.DEFAULTS["KRIPTO"])
        self.assertAlmostEqual(stop, 97.0)
        self.assertIn("ATR", text)

    def test_stop_modes(self):
        p = sl.DEFAULTS["KRIPTO"]
        self.assertAlmostEqual(sl.stop_level(100, 2, 95, 0, 0, replace(p, stop_mode="atr2"))[0], 96.0)
        self.assertAlmostEqual(sl.stop_level(100, 2, 95, 0, 0, replace(p, stop_mode="swing"))[0], 95.0)
        self.assertAlmostEqual(sl.stop_level(100, 2, 95, 0, 0, replace(p, stop_mode="swing_tampon"))[0], 94.7)
        self.assertIsNone(sl.stop_level(100, 2, float("nan"), 0, 0, replace(p, stop_mode="swing")))

    def test_targets_prefer_strong_resistance_and_fall_back_to_r_multiples(self):
        clusters = [(100.0, 2, 5), (103.0, 1, 9), (106.0, 2, 20), (112.0, 3, 30)]
        tp1, tp2, rr1, rr2, technical = sl.targets(101.0, 99.0, clusters, above=101.2)
        self.assertEqual((tp1, tp2, technical), (106.0, 112.0, True))
        self.assertAlmostEqual(rr1, 2.5)
        tp1, tp2, rr1, rr2, technical = sl.targets(101.0, 99.0, [(100.0, 2, 5)], above=101.2)
        self.assertEqual((tp1, tp2, rr1, technical), (105.0, 107.0, None, False))

    def test_position_size_risk_and_caps(self):
        s = sl.position_size(10_000, 100.0, 95.0, "KRIPTO", "BTC", atr_pct=0.03)
        self.assertAlmostEqual(s["tutar"], 1000.0)            # 0.5 % of 10,000 = 50 risk / 5 % stop distance
        self.assertAlmostEqual(s["risk_tutari"], 50.0)
        s = sl.position_size(10_000, 100.0, 99.0, "KRIPTO", "BTC", atr_pct=0.03)
        self.assertEqual((s["tutar"], s["sinira_takildi"]), (2000.0, True))    # 5,000 wanted, 20 % cap
        s = sl.position_size(10_000, 100.0, 99.0, "KRIPTO", "DOGE", atr_pct=0.07)
        self.assertEqual(s["tutar"], 1000.0)                  # volatile altcoin: 10 % cap
        s = sl.position_size(10_000, 33.0, 31.0, "BIST", "THYAO", atr_pct=0.02)
        self.assertEqual(s["adet"], int(s["adet"]))           # whole lots


class TrailingTest(unittest.TestCase):
    def test_regime_bands(self):
        p = sl.DEFAULTS["KRIPTO"]
        mult, pct = sl.trailing("TREND_UP", atr=1.2, price=100.0, p=p)
        self.assertEqual(mult, 2.25)
        self.assertAlmostEqual(pct, 2.7)
        self.assertEqual(sl.trailing("YATAY", 1, 100, p)[0], 1.55)
        self.assertEqual(sl.trailing("YUKSEK_VOL", 1, 100, p)[0], 2.75)
        self.assertEqual(sl.trailing("TREND_UP", 1, 100, replace(p, trail=3.0))[0], 3.0)


class PlanTest(unittest.TestCase):
    def test_plan_is_consistent(self):
        df = frame()
        t = sl.build_plan(df, "KRIPTO", "TEST", strategy_position=1)
        self.assertEqual(t.strategy_position, 1)              # shown, never changed
        self.assertGreaterEqual(t.resistance, df.c.iloc[-1])
        self.assertGreater(t.stop_trigger, t.resistance)
        self.assertGreater(t.limit_price, t.stop_trigger)
        self.assertLessEqual(t.limit_price, t.stop_trigger * 1.004 + 1e-9)
        self.assertLess(t.initial_stop, t.stop_trigger)
        self.assertGreater(t.tp1, t.limit_price)
        self.assertIn("TEST", sl.format_plan(t))
        self.assertIsInstance(t.to_dict()["reasons"], list)

    def test_low_score_and_bad_rr_block_the_order(self):
        df = frame(drift=-0.004)                               # a downtrend: below every average
        t = sl.build_plan(df, "KRIPTO", "TEST")
        self.assertLessEqual(t.breakout_score, 3)
        self.assertTrue(t.decision.startswith("EMİR VERME"))
        self.assertIsNone(t.position)

    def test_panic_regime_blocks_new_positions(self):
        df = frame()
        bench = pd.DataFrame({"day": pd.to_datetime(df.t, unit="ms").dt.normalize(), "c": 1.0, "sma50": 2.0,
                              "ret63": 0.0, "regime": "PANIK"})
        self.assertTrue(sl.build_plan(df, "KRIPTO", "TEST", bench).decision.startswith("YENİ POZİSYON AÇMA"))


class LookAheadTest(unittest.TestCase):
    def test_levels_do_not_change_when_the_future_is_cut_off(self):
        df = frame(n=520, seed=7)
        b = sl.prepare(df)
        P = bt.precompute(b)
        for i in (bt.START, 300, 377, 450, 519):
            bc = sl.prepare(df.iloc[:i + 1])
            cl = sl.clusters_at(bc, i)
            m = sl.main_resistance(cl)
            self.assertAlmostEqual(cl[m][0], P.res[i])
            self.assertEqual(cl[m][1], P.tch[i])
            self.assertEqual(sl.score_at(bc, i, cl[m][0], cl[m][2], detail=False)[0], P.score[i])
            low = sl.swing_low_at(bc, i)
            self.assertTrue((low != low and P.swing[i] != P.swing[i]) or low == P.swing[i])

    def test_swing_is_only_used_after_it_is_confirmed(self):
        df = frame(n=300, seed=5)
        b = sl.prepare(df)
        i = 280
        used = [src for _, _, src in sl.clusters_at(b, i)]
        self.assertTrue(all(src <= i for src in used))
        self.assertTrue(all(j <= i - sl.K or j == i - 19 + int(np.argmax(b.h[i - 19:i + 1]))
                            for j in used if j >= 0))


def bars(o, h, l, c, res_at=None):
    """Hand-made bars for the simulator: flat history, then the listed bars; the order level is given directly."""
    n0 = bt.START + 1
    pad = lambda first, xs: np.concatenate([np.full(n0, float(first)), np.array(xs, dtype=float)])
    n = n0 + len(c)
    b = SimpleNamespace(n=n, o=pad(100, o), h=pad(100, h), l=pad(100, l), c=pad(100, c), atr=np.full(n, 2.0),
                        sma20=np.full(n, np.nan), sma50=np.full(n, np.nan), regime=np.full(n, "YATAY", dtype=object),
                        day=np.arange(n).astype("datetime64[D]"))
    P = SimpleNamespace(res=np.full(n, np.nan), tch=np.full(n, 2), swing=np.full(n, np.nan), score=np.full(n, 6),
                        cl_lvl=np.full((n, sl.MAX_CLUSTERS), np.nan), cl_tch=np.zeros((n, sl.MAX_CLUSTERS), dtype=int),
                        trail_regime=np.full(n, 1.55))
    P.res[n0 - 1] = 101.0 if res_at is None else res_at       # the order is placed at the close of the last flat bar
    return b, P, n0


class SimulatorTest(unittest.TestCase):
    P0 = replace(sl.DEFAULTS["KRIPTO"], pct_buffer=0.0, atr_buffer=0.0, stop_mode="atr1.5", trail=2.0, min_rr=0.0)
    # resistance 101, ATR 2: trigger 101, limit 101.16 (0.08 ATR), stop 98

    def test_fill_at_trigger_then_trailing_stop(self):
        b, P, e = bars(o=[100, 103, 106, 104], h=[102, 106, 107, 104], l=[99.5, 102.5, 104, 100], c=[101.8, 105.5, 104.5, 101])
        r = bt.simulate(b, P, self.P0, "KRIPTO", cost=0.0, slip=0.0)
        t = r["trades"][0]
        self.assertEqual((t["e"], t["x"]), (e, e + 3))
        # trail = high - 2 ATR (4): highs 102, 106, 107 -> stop 98, 102, 103; the last bar's low 100 touches 103
        self.assertAlmostEqual(t["r"], 103 / 101 - 1)
        self.assertAlmostEqual(t["R"], (103 - 101) / 3)
        self.assertEqual(r["held"][e:e + 4].tolist(), [1, 1, 1, 0])

    def test_gap_above_the_limit_is_not_chased(self):
        b, P, _ = bars(o=[102], h=[104], l=[101.5], c=[103])   # opens above 101.16 and never comes back
        r = bt.simulate(b, P, self.P0, "KRIPTO", cost=0.0, slip=0.0)
        self.assertEqual((len(r["trades"]), r["st"]["bosluk_kacti"]), (0, 1))

    def test_gap_that_comes_back_fills_at_the_limit(self):
        b, P, e = bars(o=[102, 103], h=[104, 104], l=[101, 102.5], c=[103, 103.5])
        r = bt.simulate(b, P, self.P0, "KRIPTO", cost=0.0, slip=0.0)
        self.assertEqual(r["st"]["bosluk_limitten_doldu"], 1)
        self.assertAlmostEqual(r["dret"][e], 103 / 101.16 - 1)

    def test_stop_on_the_entry_day_is_assumed(self):
        b, P, e = bars(o=[100], h=[101.5], l=[97], c=[100])   # touched 101, and the low is under the stop (98)
        r = bt.simulate(b, P, self.P0, "KRIPTO", cost=0.0, slip=0.0)
        t = r["trades"][0]
        self.assertTrue(t["ayni_gun_stop"])
        self.assertAlmostEqual(t["R"], -1.0)

    def test_gap_through_the_stop_exits_at_the_open(self):
        b, P, e = bars(o=[100, 95], h=[102, 96], l=[99.5, 94], c=[101.5, 95])
        t = bt.simulate(b, P, self.P0, "KRIPTO", cost=0.0, slip=0.0)["trades"][0]
        self.assertAlmostEqual(t["r"], 95 / 101 - 1)          # stop was 98; the open below it is the fill

    def test_costs_and_slippage_reduce_the_result(self):
        o, h, l, c = [100, 103, 106, 104], [102, 106, 107, 104], [99.5, 102.5, 104, 100], [101.8, 105.5, 104.5, 101]
        free = bt.simulate(*bars(o, h, l, c)[:2], self.P0, "KRIPTO", cost=0.0, slip=0.0)["trades"][0]["r"]
        paid = bt.simulate(*bars(o, h, l, c)[:2], self.P0, "KRIPTO")["trades"][0]["r"]
        buy, sell = 101 * 1.0005 * 1.001, 103 * 0.9995 * 0.999  # slipped fills, then 0.1 % commission each side
        self.assertAlmostEqual(paid, sell / buy - 1)
        self.assertLess(paid, free)

    def test_filters_keep_orders_out(self):
        b, P, _ = bars(o=[100, 103], h=[102, 106], l=[99.5, 102.5], c=[101.8, 105.5])
        P.score[:] = 3
        self.assertEqual(len(bt.simulate(b, P, replace(self.P0, min_score=4), "KRIPTO")["trades"]), 0)
        P.score[:] = 6
        b.regime[:] = "PANIK"
        self.assertEqual(len(bt.simulate(b, P, self.P0, "KRIPTO")["trades"]), 0)
        b.regime[:] = "YATAY"
        P.cl_lvl[:, 0], P.cl_tch[:, 0] = 103.0, 2            # next resistance 2 above the entry, risk 3: R/R 0.67
        r = bt.simulate(b, P, replace(self.P0, min_rr=1.5), "KRIPTO")
        self.assertEqual((len(r["trades"]), r["st"]["rr_yetersiz"]), (0, 1))

    def test_half_out_at_tp1(self):
        b, P, e = bars(o=[100, 103, 106, 104], h=[102, 106, 107, 104], l=[99.5, 102.5, 104, 100], c=[101.8, 105.5, 104.5, 101])
        P.cl_lvl[:, 0], P.cl_tch[:, 0] = 105.0, 2
        t = bt.simulate(b, P, replace(self.P0, tp_mode="yarim"), "KRIPTO", cost=0.0, slip=0.0)["trades"][0]
        self.assertAlmostEqual(t["r"], 0.5 * (105 / 101 - 1) + 0.5 * (103 / 101 - 1))


if __name__ == "__main__":
    unittest.main()
