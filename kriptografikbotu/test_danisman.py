"""Kripto Danışman (danisman.py): closed candles only, confirmed swings, breakout states, decisions, sizing, and that
nothing after the report's moment can change it."""
import asyncio
import copy
import json
import os
import pathlib
import tempfile
import unittest
import unittest.mock

os.environ["ADVISOR_DATA_ORIGIN"] = "TEST"      # nothing a test logs may ever count as a live record

import numpy as np
import pandas as pd

import danisman as d

T0 = 1_700_006_400_000          # a UTC midnight
M15 = d.TFS["15m"]


def frames_from(path: np.ndarray, volume: np.ndarray | None = None) -> dict:
    """15m candles along a price path (bar k goes from path[k] to path[k+1]) and the 1h/4h/1d candles built from them."""
    o, c = path[:-1], path[1:]
    n = len(c)
    m = pd.DataFrame({"t": T0 + np.arange(n) * M15, "o": o, "h": np.maximum(o, c) + 0.03, "l": np.minimum(o, c) - 0.03,
                      "c": c, "v": np.full(n, 1000.0) if volume is None else volume})
    out = {"15m": m}
    for tf, step in list(d.TFS.items())[1:]:
        g = m.groupby(m.t // step * step)
        out[tf] = pd.DataFrame({"t": g.t.first().index.values, "o": g.o.first().values, "h": g.h.max().values,
                                "l": g.l.min().values, "c": g.c.last().values, "v": g.v.sum().values})
    return out


def zigzag(n: int, low: float, high: float, half: int = 40, drift: float = 0.0) -> np.ndarray:
    """A triangular wave from low to high and back, every `half` bars, drifting per bar."""
    k = np.arange(n + 1)
    phase = k % (2 * half)
    wave = np.where(phase <= half, phase, 2 * half - phase) / half
    return low + (high - low) * wave + drift * k


def data(path, btc_path=None, volume=None, symbol="TEST", others=None) -> dict:
    f = frames_from(np.asarray(path, dtype=float), volume)
    btc = f if btc_path is None else frames_from(np.asarray(btc_path, dtype=float))
    return {"symbol": symbol, "pair": symbol + "USDT", "quote": "USDT", "frames": f, "btc": btc, "others": others or {}}


def end_of(dt: dict) -> int:
    return int(dt["frames"]["15m"].t.iloc[-1]) + M15


def analyze(dt, **kw):
    return d.analyze(dt, asof_ms=kw.pop("asof", end_of(dt)), **kw)


N = 6400                         # 66 days of 15m candles: enough for every timeframe
DRIFT = 0.0000025                # peaks rise 0.0002 per cycle: higher highs and higher lows, one resistance cluster
BASE = zigzag(N, 95.0, 100.0, drift=DRIFT)          # ends at a trough
RES = 100.0


def ending(*legs, base=BASE) -> np.ndarray:
    """BASE, then straight legs: (target price, bars)."""
    p = list(base)
    for target, bars in legs:
        p += list(np.linspace(p[-1], target, bars + 1)[1:])
    return np.array(p)


BELOW = ending((99.0, 32))                           # rising, one point under the resistance
BROKEN = ending((99.0, 32), (100.5, 12))             # ...and through it, three candles closed above
FAILED = ending((99.0, 32), (100.5, 12), (99.6, 8))   # ...and back under it


class DataTest(unittest.TestCase):
    def test_open_candle_is_kept_out_of_the_closed_set(self):
        f = frames_from(BELOW)["15m"]
        asof = int(f.t.iloc[-1]) + M15 // 2            # the last candle is half way through
        closed, live = d.split(f, "15m", asof)
        self.assertEqual(len(closed), len(f) - 1)
        self.assertEqual(live["t"], float(f.t.iloc[-1]))
        self.assertEqual(d.split(f, "15m", asof + M15)[1], None)

    def test_quote_fallback_is_reported(self):
        f = frames_from(BELOW)
        rows = lambda tf: [[int(r.t), r.o, r.h, r.l, r.c, 0, 0, r.v] for r in f[tf].tail(400).itertuples()]

        class Resp:
            def __init__(self, code, body):
                self.status_code, self._b, self.text = code, body, ""

            def json(self):
                return self._b

        class Client:
            async def get(self, url, params, timeout):
                return Resp(400, None) if params["symbol"] == "XYZUSDT" else Resp(200, rows(params["interval"]))

        got = asyncio.run(d.fetch("xyz", client=Client()))
        self.assertEqual((got["pair"], got["quote"]), ("XYZUSDC", "USDC"))
        with unittest.mock.patch("danisman.time.time", return_value=(int(f["15m"].t.iloc[-1]) + M15) / 1000):
            self.assertIn("XYZUSDC", d.analyze(got)["quote_note"])


class IndicatorTest(unittest.TestCase):
    def setUp(self):
        self.f = frames_from(BELOW)

    def test_values_match_plain_arithmetic(self):
        m = self.f["15m"]
        s = d.snapshot(d.view(m, "15m"))
        self.assertAlmostEqual(s["sma20"], m.c.tail(20).mean())
        self.assertAlmostEqual(s["high20"], m.h.tail(20).max())
        self.assertAlmostEqual(s["donchian_high20"], m.h.iloc[-21:-1].max())   # the 20 candles BEFORE the last one
        self.assertAlmostEqual(s["volume_ratio"], 1.0)
        self.assertAlmostEqual(s["slope_sma20_pct"], (m.c.tail(20).mean() / m.c.iloc[-25:-5].mean() - 1) * 100, places=2)
        self.assertIsNone(d.snapshot(d.view(self.f["4h"], "4h"))["vwap"])     # VWAP only on intraday frames

    def test_vwap_restarts_each_utc_day(self):
        m = self.f["15m"]
        b = d.view(m, "15m")
        first = int(np.flatnonzero(m.t.values % 86_400_000 == 0)[-1])
        self.assertAlmostEqual(b.vwap[first], (m.h[first] + m.l[first] + m.c[first]) / 3)

    def test_a_swing_is_known_only_after_its_right_hand_candles(self):
        b = d.view(self.f["1h"], "1h")
        pts = d.swing_points(b)
        self.assertTrue(pts)
        for p in pts:
            self.assertGreaterEqual(p["known"], p["t"] + (d.sl.K + 1) * d.TFS["1h"])
            self.assertLessEqual(p["known"], int(b.t[-1]) + d.TFS["1h"])
        cut = d.view(self.f["1h"].iloc[:-40], "1h")      # forty hours earlier: nothing that was known changes
        early = {(p["kind"], p["t"]) for p in d.swing_points(cut)}
        self.assertTrue(early <= {(p["kind"], p["t"]) for p in pts} | {(p["kind"], p["t"]) for p in d.swing_points(cut)
                                                                         if p["t"] < int(b.t[-1]) - d.LOOKBACK * d.TFS["1h"]})
        self.assertFalse({(p["kind"], p["t"]) for p in pts if p["known"] <= int(cut.t[-1]) + d.TFS["1h"]
                          and p["t"] >= int(cut.t[-1]) - (d.LOOKBACK - 40) * d.TFS["1h"]} - early)


class TrendTest(unittest.TestCase):
    def test_states_and_reasons(self):
        up = d.trend_state(d.view(frames_from(zigzag(N + 30, 50, 53, drift=0.006))["1h"], "1h"))   # ends on an up-leg
        down = d.trend_state(d.view(frames_from(zigzag(N, 150, 153, drift=-0.006))["1h"], "1h"))
        flat = d.trend_state(d.view(frames_from(ending((97.5, 20)))["1h"], "1h"))
        self.assertIn(up["state"], ("UPTREND", "STRONG_UPTREND"))
        self.assertIn(down["state"], ("DOWNTREND", "STRONG_DOWNTREND"))
        self.assertIn(flat["state"], ("RANGE", "UPTREND"))
        self.assertTrue(all(isinstance(x, str) and x.startswith("1h") for x in up["reasons"]))
        self.assertTrue(any("swing" in x for x in up["reasons"]) and any("SMA200" in x for x in up["reasons"]))


class LevelTest(unittest.TestCase):
    def test_levels_carry_explainable_parts_not_a_score(self):
        r = analyze(data(BELOW))
        top = r["resistances"][0]
        self.assertAlmostEqual(top["price"], RES, delta=0.4)
        self.assertGreaterEqual(top["touch_count"], 2)
        self.assertEqual(set(top), {"price", "zone", "touch_count", "age_bars", "distance_pct", "strength"})
        self.assertEqual(set(top["strength"]), {"touch_count", "volume_on_reactions", "recency", "timeframe"})
        self.assertGreater(top["distance_pct"], 0)
        self.assertLess(r["supports"][0]["distance_pct"], 0)
        self.assertLess(r["supports"][0]["price"], r["price"])


class BreakoutTest(unittest.TestCase):
    def test_under_the_level_waits_with_a_stop_limit_plan(self):
        r = analyze(data(BELOW), portfolio_usdt=287)
        self.assertEqual((r["decision"], r["breakout"]["breakout_status"]), ("WAIT_FOR_BREAKOUT", "NONE"))
        p, top = r["plan"], r["resistances"][0]["zone"][1]
        self.assertEqual(p["type"], "STOP_LIMIT")
        self.assertAlmostEqual(p["trigger_price"], top * 1.0005)                # just above the level, no big buffer
        self.assertTrue(p["trigger_price"] < p["limit_price"] <= p["trigger_price"] * 1.004)
        self.assertLessEqual(p["initial_stop"], p["invalid_level"])
        self.assertLess(p["initial_stop"], p["entry"])
        self.assertAlmostEqual(p["risk_per_unit"], p["entry"] - p["initial_stop"])
        self.assertGreaterEqual(r["stop"]["distance_atr"], 1.0)                  # never inside normal movement
        self.assertIn("altında 15m kapanış", r["invalid_if"])
        self.assertIn("üzerinde 15m kapanış", r["recheck_if"])
        s = r["position_size"]
        self.assertAlmostEqual(s["risk_usdt"], 287 * 0.005, places=2)
        self.assertLessEqual(s["position_usdt"], 287 * 0.15 + 1e-9)             # altcoin cap

    def test_closed_candle_above_the_level_is_confirmed(self):
        vol = np.full(len(BROKEN) - 1, 1000.0)
        vol[-12:] = 2500.0                                                       # the breakout came with volume
        r = analyze(data(BROKEN, volume=vol))
        b = r["breakout"]
        self.assertEqual(b["breakout_status"], "CONFIRMED")
        self.assertTrue(b["fresh"] and b["quality_ok"])
        self.assertGreaterEqual(b["candle"]["volume_ratio"], 1.0)
        self.assertEqual((r["decision"], r["scenario"]), ("BUY_SETUP", "BREAKOUT"))
        self.assertLess(r["plan"]["initial_stop"], b["zone"][0])                 # under the broken zone
        self.assertIsNone(r["plan"]["trigger_price"])

    def test_breakout_without_volume_waits_for_the_retest(self):
        r = analyze(data(BROKEN, volume=np.r_[np.full(len(BROKEN) - 13, 1000.0), np.full(12, 300.0)]))
        self.assertEqual((r["breakout"]["breakout_status"], r["decision"]), ("CONFIRMED", "WAIT_FOR_RETEST"))
        self.assertEqual(r["plan"]["type"], "RETEST_WAIT")                       # a plan to wait with, not an entry
        self.assertIsNone(r["plan"]["trigger_price"])

    def test_pullback_to_the_broken_level_that_holds_is_a_retest(self):
        path = ending((99.0, 32), (100.9, 16), (100.12, 7), (100.3, 2))   # out, away, back to the level, a green candle
        r = analyze(data(path, volume=np.r_[np.full(len(path) - 26, 1000.0), np.full(25, 300.0)]))
        self.assertTrue(r["breakout"]["retested"])
        self.assertEqual((r["decision"], r["scenario"]), ("BUY_SETUP", "RETEST"))
        self.assertIn("altında 15m kapanış", r["invalid_if"])

    def test_fall_back_under_the_level_is_a_failed_breakout(self):
        r = analyze(data(FAILED))
        self.assertEqual(r["breakout"]["breakout_status"], "FAILED_BREAKOUT")
        self.assertEqual(r["decision"], "NO_SETUP")
        self.assertTrue(any("sahte kırılım" in x for x in r["evidence"]))

    def test_an_open_candle_never_confirms(self):
        path = ending((99.0, 32), (99.95, 8), (100.9, 1))      # the last candle jumps over the level and is still open
        dt = data(path)
        mid = (int(dt["frames"]["15m"].t.iloc[-1]) + M15 // 2) / 1000
        with unittest.mock.patch("danisman.time.time", return_value=mid):
            r = d.analyze(dt)
        self.assertGreater(r["price"], r["resistances"][0]["zone"][1])           # the live price IS above
        self.assertEqual(r["breakout"]["breakout_status"], "TESTING")
        self.assertTrue(r["breakout"]["open_candle_above"])
        self.assertNotEqual(r["decision"], "BUY_SETUP")
        self.assertIn("açık", r["price_source"])


class FilterTest(unittest.TestCase):
    def test_downtrend_is_avoided(self):
        r = analyze(data(zigzag(N, 150, 153, drift=-0.006)), portfolio_usdt=287)
        self.assertEqual(r["decision"], "AVOID")
        self.assertIsNone(r["plan"])

    def test_btc_falling_blocks_a_buy_and_warns(self):
        vol = np.full(len(BROKEN) - 1, 1000.0)
        vol[-12:] = 2500.0
        r = analyze(data(BROKEN, btc_path=zigzag(len(BROKEN) - 1, 400, 403, drift=-0.03), volume=vol))
        self.assertTrue(r["btc"]["market_risk"])
        self.assertIn("MARKET_RISK", [w["code"] for w in r["warnings"]])
        self.assertNotEqual(r["decision"], "BUY_SETUP")
        self.assertEqual((r["decision"], r["underlying_setup"], r["blocked_reason"]),
                         ("BLOCKED_SETUP", "READY_TO_WATCH", "BTC_MARKET_RISK"))

    def test_holdings_that_move_together_warn(self):
        one_hour = frames_from(BELOW)["1h"]
        r = analyze(data(BELOW, others={"AAA": one_hour, "BBB": one_hour}))
        self.assertEqual(r["correlation"], {"AAA": 1.0, "BBB": 1.0})
        self.assertIn("PORTFOLIO_CONCENTRATION", [w["code"] for w in r["warnings"]])
        self.assertNotIn("PORTFOLIO_CONCENTRATION", [w["code"] for w in analyze(data(BELOW))["warnings"]])

    def test_timeframes_without_enough_candles_take_no_part(self):
        dt = data(BELOW)                                                        # a pair listed a week ago
        dt["frames"] = {tf: f.tail(n).reset_index(drop=True) for (tf, f), n in zip(dt["frames"].items(), (700, 175, 44, 7))}
        r = analyze(dt)
        self.assertEqual(r["insufficient_history"], ["4h", "1d"])
        self.assertIn("INSUFFICIENT_HISTORY", [w["code"] for w in r["warnings"]])
        self.assertEqual((r["trend"]["4h"]["state"], r["trend"]["1d"]["state"]), ("INSUFFICIENT_HISTORY",) * 2)
        self.assertEqual(set(r["indicators"]), {"15m", "1h"})                   # no indicator from the short frames
        self.assertFalse([x for x in r["evidence"] if x.startswith(("4h", "1d", "Günlük"))])
        self.assertTrue(any(x.startswith("1h (ana yön)") for x in r["evidence"]))
        self.assertIn("4h veri yetersiz", d.format_report(r))
        dt["frames"]["1h"] = dt["frames"]["1h"].tail(80).reset_index(drop=True)  # not even the main timeframe: no report
        with self.assertRaises(ValueError):
            analyze(dt)


class PositionTest(unittest.TestCase):
    def test_loss_with_intact_structure_holds_with_an_exit_level(self):
        r = analyze(data(BELOW), portfolio_usdt=287, position_usdt=35, average_price=100.4)
        p = r["position"]
        self.assertEqual((r["decision"], p["action"]), ("HOLD", "EXIT_IF_INVALIDATED"))
        self.assertLess(p["unrealized_pnl_pct"], 0)
        self.assertAlmostEqual(p["break_even_level"], 100.4 * 1.002)
        self.assertLessEqual(p["technical_stop"], p["invalid_level"])
        self.assertLess(p["technical_stop"], r["price"])
        self.assertIsNone(r["plan"])                                             # no new-entry plan for a holder

    def test_profit_is_protected(self):
        r = analyze(data(BELOW), position_usdt=35, average_price=92.0)
        p = r["position"]
        self.assertEqual((r["decision"], p["action"]), ("PROTECT_PROFIT", "PROTECT_PROFIT"))
        self.assertGreaterEqual(p["protect_stop"], p["break_even_level"])

    def test_broken_structure_reduces(self):
        r = analyze(data(zigzag(N, 150, 153, drift=-0.006)), position_usdt=35, average_price=125.0)
        self.assertEqual((r["decision"], r["position"]["action"]), ("REDUCE_RISK", "REDUCE"))


class SizingTest(unittest.TestCase):
    def test_risk_based_size_and_class_caps(self):
        s = d.size_position(1000, 100.0, 95.0, "BTC", daily_atr_pct=0.03)
        self.assertAlmostEqual(s["position_usdt"], 100.0)                        # 5 risk / 5 % stop distance
        self.assertAlmostEqual(s["loss_at_stop_usdt"], 5.0)
        wide = lambda sym, vol: d.size_position(1000, 100.0, 99.5, sym, vol)["position_usdt"]
        self.assertEqual((wide("BTC", 0.03), wide("BTC", 0.07)), (200.0, 150.0))
        self.assertEqual((wide("HYPE", 0.03), wide("HYPE", 0.07)), (150.0, 100.0))
        self.assertEqual((wide("DOGE", 0.03), wide("DOGE", 0.07)), (100.0, 50.0))
        self.assertTrue(d.size_position(50, 100.0, 90.0, "BTC", 0.03)["below_exchange_minimum"])

    def test_stop_skips_levels_inside_the_noise(self):
        st = d.technical_stop(100.0, 2.0, [(99.2, "yakın destek"), (97.0, "swing dip"), (90.0, "uzak destek")])
        self.assertEqual(st["invalid_level"], 97.0)
        self.assertAlmostEqual(st["technical_stop"], 97.0 - 0.15 * 2.0)
        self.assertEqual(st["too_tight"]["level"], 99.2)
        self.assertEqual((st["distance_pct"], st["distance_atr"]), (3.3, 1.65))
        self.assertAlmostEqual(d.technical_stop(100.0, 2.0, [(99.2, "x")])["technical_stop"], 97.0)   # 1.5 ATR


class NoLookAheadTest(unittest.TestCase):
    def test_nothing_after_the_moment_changes_the_report(self):
        full = data(BROKEN)
        moment = int(full["frames"]["15m"].t.iloc[-300]) + 7 * 60_000            # in the middle of a candle
        want = json.dumps(analyze(full, asof=moment, portfolio_usdt=287), sort_keys=True)

        cut = data(BROKEN)
        cut["frames"] = {tf: f[f.t <= moment].reset_index(drop=True) for tf, f in cut["frames"].items()}
        cut["btc"] = cut["frames"]
        self.assertEqual(json.dumps(analyze(cut, asof=moment, portfolio_usdt=287), sort_keys=True), want)

        spoiled = data(BROKEN)                       # every candle that closes after the moment is replaced by garbage
        for tf, f in spoiled["frames"].items():
            later = f.t + d.TFS[tf] > moment
            f.loc[later, ["o", "h", "l", "c"]] = f.loc[later, ["o", "h", "l", "c"]] * 3.0
            f.loc[later, "v"] = 9e9
        self.assertEqual(json.dumps(analyze(spoiled, asof=moment, portfolio_usdt=287), sort_keys=True), want)

    def test_report_is_plain_json_and_readable_text(self):
        r = analyze(data(BELOW), portfolio_usdt=287)
        json.dumps(r, allow_nan=False)
        text = d.format_report(r)
        for part in ("TEST/USDT", "WAIT_FOR_BREAKOUT", "Stop-limit alış planı", "Tetik:", "Limit:", "Teknik stop:",
                     "İz süren stop: 3 ATR", "Pozisyon: portföy 287", "Neden:", "Tekrar kontrol:", "Emir gönderilmez"):
            self.assertIn(part, text)
        self.assertNotIn("confidence", json.dumps(r))


class StateMachineTest(unittest.TestCase):
    LO, TOP = 100.0, 100.2

    def state(self, closes, highs=None, live=None, start=0):
        c = np.array(closes, dtype=float)
        h = c + 0.05 if highs is None else np.array(highs, dtype=float)
        return d.level_state(c, h, self.LO, self.TOP, start, live)[0]

    def test_every_transition(self):
        steps = [(99.0, "NONE"), (99.97, "TESTING"), (99.0, "NONE"), (100.5, "CONFIRMED"), (100.6, "CONFIRMED"),
                 (100.1, "FAILED_BREAKOUT"),      # closed back under the top
                 (100.0, "FAILED_BREAKOUT"),      # still inside the zone: it never left, so this is not a new test
                 (99.5, "FAILED_BREAKOUT"),       # left the zone
                 (99.96, "RECLAIM_TESTING"),      # high 100.01 reaches the zone again
                 (99.4, "FAILED_BREAKOUT"),       # turned away again
                 (100.05, "RECLAIM_TESTING"), (100.4, "CONFIRMED")]
        for k in range(1, len(steps) + 1):
            self.assertEqual(self.state([p for p, _ in steps[:k]]), steps[k - 1][1], f"after {steps[k - 1][0]}")

    def test_an_open_candle_tests_but_never_confirms(self):
        above = {"h": 101.0, "c": 100.9}
        self.assertEqual(self.state([99.0, 99.2], live=above), "TESTING")
        self.assertEqual(self.state([99.0, 100.5, 100.1, 99.5], live=above), "RECLAIM_TESTING")
        self.assertEqual(self.state([99.0, 100.5, 100.1, 99.5], live={"h": 99.6, "c": 99.55}), "FAILED_BREAKOUT")

    def test_falling_from_above_is_not_a_failed_breakout(self):
        self.assertEqual(self.state([101.0, 100.8, 99.5]), "NONE")              # it was above when the window began
        self.assertEqual(d.level_state(np.array([99.0, 100.5, 99.5]), np.array([99.1, 100.6, 100.4]), 100.0, 100.2, 0)[1], 1)

    def test_failed_breakout_then_reclaim_in_a_report(self):
        failed = analyze(data(FAILED))
        lo, top = failed["breakout"]["zone"]
        self.assertEqual(failed["breakout"]["breakout_status"], "FAILED_BREAKOUT")
        self.assertEqual((failed["decision"], failed["reason_code"]), ("NO_SETUP", "FAILED_BREAKOUT"))

        back = ending((99.0, 32), (100.5, 12), (99.6, 8), (lo - 0.01, 3))        # away, then up to the zone again
        r = analyze(data(back))
        self.assertEqual(r["breakout"]["breakout_status"], "RECLAIM_TESTING")
        self.assertEqual(r["decision"], "WAIT_FOR_BREAKOUT")
        self.assertIn("FAILED_BEFORE", [w["code"] for w in r["warnings"]])
        self.assertAlmostEqual(r["plan"]["trigger_price"], top * 1.0005)

        dt = data(ending((99.0, 32), (100.5, 12), (99.6, 8), (lo - 0.01, 3), (top + 0.6, 1)))   # last candle still open
        with unittest.mock.patch("danisman.time.time", return_value=(int(dt["frames"]["15m"].t.iloc[-1]) + M15 // 2) / 1000):
            live = d.analyze(dt)
        self.assertEqual(live["breakout"]["breakout_status"], "RECLAIM_TESTING")
        self.assertTrue(live["breakout"]["open_candle_above"])
        self.assertNotEqual(live["decision"], "BUY_SETUP")
        self.assertEqual(analyze(dt)["breakout"]["breakout_status"], "CONFIRMED")   # ...and once that candle has closed


class SizingInputTest(unittest.TestCase):
    def test_unknown_portfolio_gives_no_size_and_says_why(self):
        r = analyze(data(BELOW))
        self.assertIsNotNone(r["plan"])
        self.assertIsNone(r["position_size"])
        self.assertEqual(r["position_size_note"], "Portföy büyüklüğü bilinmiyor.")
        self.assertIn("Pozisyon: Portföy büyüklüğü bilinmiyor.", d.format_report(r))
        self.assertNotIn("100 USDT", d.format_report(r))

    def test_btc_quote_is_analysed_but_never_sized_in_usdt(self):
        dt = data(BELOW)
        dt.update(pair="TESTBTC", quote="BTC")
        r = analyze(dt, portfolio_usdt=287)
        self.assertIn("QUOTE_BTC_WARNING", [w["code"] for w in r["warnings"]])
        self.assertIsNotNone(r["plan"])                                          # the analysis itself is there
        self.assertIsNone(r["position_size"])
        self.assertIn("BTC", r["position_size_note"])
        self.assertIn("TESTBTC", r["quote_note"])

    def test_fetch_falls_back_to_btc_only_after_the_stable_quotes(self):
        f = frames_from(BELOW)
        rows = lambda tf: [[int(r.t), r.o, r.h, r.l, r.c, 0, 0, r.v] for r in f[tf].tail(400).itertuples()]
        asked = []

        class Resp:
            def __init__(self, code, body):
                self.status_code, self._b, self.text = code, body, ""

            def json(self):
                return self._b

        class Client:
            async def get(self, url, params, timeout):
                asked.append(params["symbol"])
                ok = params["symbol"] in ("XYZBTC", "BTCUSDT")
                return Resp(200, rows(params["interval"])) if ok else Resp(400, None)

        got = asyncio.run(d.fetch("XYZ", client=Client()))
        self.assertEqual(got["quote"], "BTC")
        self.assertEqual(asked[:4], ["XYZUSDT", "XYZUSDC", "XYZFDUSD", "XYZBTC"])
        with self.assertRaises(d.NoPair):                                        # the scan never uses a BTC quote
            asyncio.run(d.fetch("XYZ", client=Client(), quotes=d.SCAN_QUOTES))


VOLUME = np.r_[np.full(len(BROKEN) - 13, 1000.0), np.full(12, 2500.0)]
OTHER = zigzag(N, 40.0, 42.0, half=50, drift=DRIFT)          # a different rhythm: does not move with BASE
THIRD = zigzag(N, 7.0, 7.4, half=32, drift=DRIFT)


def market() -> dict:
    """Twenty-four coins: every kind of report the scan has to sort, several of them moving together."""
    pad = lambda p: np.r_[p, np.full(len(FAILED) - len(p), p[-1])]            # same length, so the clocks agree
    falling = zigzag(len(FAILED) - 1, 150, 153, drift=-0.006)
    coins = {f"SAME{k}": data(pad(BELOW), symbol=f"SAME{k}") for k in range(7)}          # identical: correlation 1
    late = ending((99.0, 40), (100.5, 12))                                       # BROKEN, eight candles later
    coins |= {"BRK1": data(late, volume=np.r_[np.full(len(late) - 13, 1000.0), np.full(12, 2500.0)], symbol="BRK1"),
              "FAIL1": data(FAILED, symbol="FAIL1"), "FAIL2": data(FAILED * 3.0, symbol="FAIL2"),
              "OTH1": data(pad(ending((41.6, 32), base=OTHER)), symbol="OTH1"),
              "OTH2": data(pad(ending((41.2, 28), base=OTHER)), symbol="OTH2"),
              "THR1": data(pad(ending((7.32, 30), base=THIRD)), symbol="THR1"),
              "THR2": data(pad(ending((7.2, 20), base=THIRD)), symbol="THR2")}
    coins |= {f"DOWN{k}": data(falling * (k + 1), symbol=f"DOWN{k}") for k in range(5)}
    for k in range(3):                                                           # listed days ago: 4h and 1d too short
        dt = data(pad(BELOW), symbol=f"NEW{k}")
        dt["frames"] = {tf: f.tail(n).reset_index(drop=True) for (tf, f), n in zip(dt["frames"].items(), (700, 175, 44, 7))}
        coins[f"NEW{k}"] = dt
    tiny = data(pad(BELOW), symbol="TINY")
    tiny["frames"] = {tf: f.tail(50).reset_index(drop=True) for tf, f in tiny["frames"].items()}
    coins["TINY"] = tiny
    btc = frames_from(pad(BELOW))                                                # one BTC for everybody, as in a real scan
    for dt in coins.values():
        dt["btc"] = btc
    return coins


COLUMNS = {"symbol", "current_price", "decision", "entry_type", "1h_trend", "4h_trend", "main_resistance", "main_support",
           "trigger", "limit", "technical_stop", "stop_distance_pct", "trailing_atr", "trailing_pct", "volume_ratio", "RSI",
           "recheck_if", "invalid_if", "warnings"}


class ScanTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.coins = market()
        cls.asof = max(end_of(dt) for dt in cls.coins.values())

    def scan(self, coins=None, **kw):
        coins = coins or self.coins

        async def fetcher(coin):
            if coin == "GONE":
                raise d.NoPair(coin)
            return coins[coin]
        return asyncio.run(d.scan(symbols=list(coins) + ["GONE"], fetcher=fetcher, asof_ms=self.asof, **kw))

    def test_scan_over_more_than_twenty_symbols(self):
        s = self.scan()
        self.assertGreaterEqual(s["scanned"], 20)
        self.assertEqual(s["scanned"], len(self.coins) + 1)
        self.assertTrue(0 < len(s["results"]) <= d.SCAN_TOP)
        for row in s["results"]:
            self.assertTrue(COLUMNS <= set(row), COLUMNS - set(row))
            self.assertIn(row["group"], d.GROUPS[:4])
            self.assertFalse({"score", "confidence"} & set(row))                 # an order, never a made-up score
            self.assertEqual(row["rank_reasons"][0], d.TIERS[row["tier"]])
            self.assertTrue(row["summary"])
            self.assertIn(row["tier"], d.TIERS)
        self.assertEqual(set(s["groups"]), set(d.GROUPS))
        grouped = [x for g in s["groups"].values() for x in g]
        self.assertEqual(sorted(grouped), sorted(set(self.coins) - {"TINY"}))    # every analysed coin is in one group
        self.assertIn("BRK1", s["groups"]["READY_TO_WATCH"])
        self.assertTrue(set(s["groups"]["AVOID"]) >= {f"DOWN{k}" for k in range(5)})
        json.dumps(s, allow_nan=False)

    def test_order_is_lexicographic(self):
        s = self.scan()
        keys = [d.rank_key(row, 0)[0][:-2] for row in s["results"]]
        self.assertEqual(keys, sorted(keys))
        self.assertNotIn("MARKET_RISK", s["results"][0]["warnings"])
        short = [k for k, row in enumerate(s["results"]) if row["insufficient_history"]]
        full = [k for k, row in enumerate(s["results"]) if not row["insufficient_history"]]
        self.assertTrue(not short or not full or max(full) < min(short))         # enough history always comes first

    def test_rejected_coins_come_with_a_plain_reason(self):
        s = self.scan(holdings=["DOWN3"])
        self.assertTrue(0 < len(s["not_now"]) <= d.SCAN_REJECTED)
        self.assertGreater(s["not_now_total"], len(s["not_now"]))
        self.assertEqual(s["not_now"][0]["symbol"], "DOWN3")                     # a holding is reported first
        for x in s["not_now"]:
            if x["group"] == "BLOCKED_SETUP":                                   # a setup held back: says by what
                self.assertIn(d.BLOCK_TR[x["reason_code"]], x["reason"])
            else:
                self.assertEqual(x["reason"], d.REASON_TR[x["reason_code"]])
        reasons = {x["symbol"]: x["reason_code"] for x in self.scan()["not_now"] + d.build_scan([], [], {}, [], None)["not_now"]}
        every = {x["symbol"]: x["reason_code"] for x in asyncio.run(self._all_rejected())}
        self.assertEqual(every["DOWN0"], "DOWNTREND_1H")
        self.assertEqual(every["FAIL1"], "FAILED_BREAKOUT")
        self.assertEqual(every["TINY"], "INSUFFICIENT_HISTORY")
        self.assertEqual(every["GONE"], "NO_DATA")
        self.assertTrue(reasons)

    async def _all_rejected(self):
        with unittest.mock.patch.object(d, "SCAN_REJECTED", 999):
            async def fetcher(coin):
                if coin == "GONE":
                    raise d.NoPair(coin)
                return self.coins[coin]
            return (await d.scan(symbols=list(self.coins) + ["GONE"], fetcher=fetcher, asof_ms=self.asof))["not_now"]

    def test_coins_that_move_together_are_not_all_put_forward(self):
        s = self.scan()
        same = [row["symbol"] for row in s["results"] if row["symbol"].startswith(("SAME", "NEW", "BRK"))]
        self.assertLessEqual(len(same), d.MAX_CORRELATED)
        self.assertTrue(s["skipped_correlated"])
        self.assertTrue(all(len(x["moves_with"]) >= d.MAX_CORRELATED for x in s["skipped_correlated"]))
        held = self.scan(holdings=["SAME0", "SAME1", "SAME2"])                   # three of them are already held
        picked = [row["symbol"] for row in held["results"] if row["symbol"].startswith(("SAME", "NEW", "BRK"))]
        self.assertLessEqual(len(set(picked) - {"SAME0", "SAME1", "SAME2"}), d.MAX_CORRELATED - 3 + 3)
        pf = held["portfolio"]
        self.assertEqual(pf["holdings"], ["SAME0", "SAME1", "SAME2"])
        self.assertEqual(len(pf["high_correlation_pairs"]), 3)
        self.assertIn("birlikte hareket ediyor", pf["note"])
        self.assertTrue(all(row["held"] for row in held["results"] if row["symbol"] in pf["holdings"]))

    def test_portfolio_value_unknown_and_known(self):
        unknown, known = self.scan(), self.scan(portfolio_usdt=287)
        with_plan = [row for row in unknown["results"] if row["has_plan"]]
        self.assertTrue(with_plan)
        for row in with_plan:
            self.assertIsNone(row["position_size"])
            self.assertEqual(row["position_size_note"], "Portföy büyüklüğü bilinmiyor.")
        self.assertTrue(all(row["position_size"]["portfolio_usdt"] == 287 for row in known["results"] if row["has_plan"]))
        text = d.format_scan(unknown)
        for part in ("Kripto Danışman taraması", "Şu an işlem aranmayacaklar:", "Portföy büyüklüğü bilinmiyor.",
                     "Sıralama (sırayla, tek puan yok)", "Emir gönderilmez"):
            self.assertIn(part, text)

    def test_nothing_after_the_moment_changes_the_scan(self):
        moment = self.asof - 250 * M15 + 4 * 60_000
        want = json.dumps(asyncio.run(self._at(self.coins, moment)), sort_keys=True)
        spoiled = market()
        for dt in spoiled.values():
            for group in (dt["frames"], dt["btc"]):
                for tf, f in group.items():
                    later = f.t + d.TFS[tf] > moment
                    f.loc[later, ["o", "h", "l", "c"]] = f.loc[later, ["o", "h", "l", "c"]] * 5.0
                    f.loc[later, "v"] = 7e9
        self.assertEqual(json.dumps(asyncio.run(self._at(spoiled, moment)), sort_keys=True), want)

    async def _at(self, coins, moment):
        async def fetcher(coin):
            return coins[coin]
        return await d.scan(symbols=list(coins), fetcher=fetcher, asof_ms=moment, portfolio_usdt=287)

    def test_universe_prefers_usdt_and_skips_stables_and_thin_pairs(self):
        rows = [{"symbol": "SOLUSDT", "quoteVolume": "9e8"}, {"symbol": "SOLUSDC", "quoteVolume": "9e9"},
                {"symbol": "NEWUSDC", "quoteVolume": "8e7"}, {"symbol": "ODDFDUSD", "quoteVolume": "7e7"},
                {"symbol": "USDCUSDT", "quoteVolume": "9e9"}, {"symbol": "THINUSDT", "quoteVolume": "1000"},
                {"symbol": "ETHBTC", "quoteVolume": "9e9"}, {"symbol": "BTCUSDT", "quoteVolume": "5e9"}]

        class Resp:
            status_code, text = 200, ""

            def json(self):
                return rows

        class Client:
            async def get(self, url, timeout):
                if "exchangeInfo" in url:
                    raise d.httpx.ConnectError("no metadata")
                return Resp()

        d._meta.update(at=0.0, data=None)
        with self.assertLogs("danisman", level="WARNING"):
            self.assertEqual(asyncio.run(d.universe(Client())),
                             [("BTC", "USDT"), ("SOL", "USDT"), ("NEW", "USDC"), ("ODD", "FDUSD")])
            self.assertEqual(len(asyncio.run(d.universe(Client(), limit=2))), 2)


LATER = ending((99.0, 32), (100.5, 12), (102.4, 24), (100.9, 8), (101.9, 16))   # broke out, ran, made a higher low
QUIET = np.r_[np.full(len(BROKEN) - 13, 1000.0), np.full(12, 300.0)]          # the breakout candle had no volume


class RetestPlanTest(unittest.TestCase):
    def check(self, r):
        rt, plan = r["retest"], r["plan"]
        self.assertEqual(r["decision"], "WAIT_FOR_RETEST")
        self.assertEqual(set(rt), set(d.RETEST_FIELDS))
        self.assertTrue(all(v is not None for v in rt.values()))
        self.assertEqual(plan["type"], "RETEST_WAIT")
        self.assertTrue(r["actionable"])
        self.assertLess(rt["retest_invalidation"], rt["retest_zone_low"])       # never invalidated inside the zone
        self.assertLessEqual(rt["retest_stop"], rt["retest_invalidation"])
        self.assertGreaterEqual(rt["retest_confirmation_price"], rt["retest_zone_low"])
        self.assertLessEqual(rt["retest_zone_low"], rt["broken_resistance"])
        self.assertLess(rt["broken_resistance"], rt["retest_zone_high"])
        self.assertGreaterEqual(rt["retest_distance_pct"], 0)
        self.assertNotEqual(r["recheck_price"], rt["retest_invalidation"])       # "look again" and "it is over" differ
        self.assertGreater(r["recheck_price"], rt["retest_invalidation"])
        self.assertNotEqual(r["recheck_if"], r["invalid_if"])
        self.assertIn(d._p(rt["retest_invalidation"]), r["invalid_if"])
        self.assertNotIn(d._p(rt["retest_invalidation"]), r["recheck_if"])
        self.assertLess(rt["retest_invalidation"], r["main_support"][0])         # the shown support is not below the exit
        self.assertEqual(d.plan_missing(plan), [])
        return rt

    def test_wait_for_retest_carries_every_level(self):
        rt = self.check(analyze(data(BROKEN, volume=QUIET), portfolio_usdt=287))
        self.assertAlmostEqual(rt["retest_zone_high"] - rt["broken_resistance"], d.RETEST_ATR * analyze(
            data(BROKEN, volume=QUIET))["indicators"]["1h"]["atr14"])
        text = d.format_report(analyze(data(BROKEN, volume=QUIET), portfolio_usdt=287))
        for part in ("Geri test planı", "Kırılan direnç:", "Geri test bölgesi:", "Teyit:", "Teknik stop:", "Teknik geçersizlik:"):
            self.assertIn(part, text)

    def test_support_above_the_retest_zone_does_not_merge_the_two_levels(self):
        # the live STX case: a support formed ABOVE the broken resistance; "look again" and "invalid" were one price
        r = analyze(data(LATER))
        rt = self.check(r)
        self.assertGreater(r["main_support"][0], rt["retest_zone_high"])
        self.assertIn("desteği tutarsa geri test gelmeyebilir", r["recheck_if"])
        self.assertGreater(rt["retest_distance_pct"], 0.5)
        row = d.scan_row(r, False)
        self.assertEqual((row["group"], row["tier"]), ("WAIT_FOR_RETEST", "C"))
        self.assertTrue(all(row[k] is not None for k in d.RETEST_FIELDS))


class IntegrityTest(unittest.TestCase):
    def test_missing_or_contradicting_levels_make_a_plan_incomplete(self):
        good = analyze(data(BELOW))["plan"]
        self.assertEqual(d.plan_missing(good), [])
        self.assertEqual(d.plan_missing({**good, "limit_price": None}), ["limit_price"])
        self.assertEqual(d.plan_missing({**good, "initial_stop": float("nan")}), ["initial_stop"])
        self.assertTrue(d.plan_missing({**good, "initial_stop": good["entry"] + 1}))          # stop above the entry
        retest = analyze(data(BROKEN, volume=QUIET))["plan"]
        self.assertEqual(d.plan_missing({**retest, "retest_zone_low": None}), ["retest_zone_low"])
        self.assertTrue(d.plan_missing({**retest, "invalid_level": retest["retest_zone_low"]}))  # invalid inside the zone

    def test_incomplete_plan_is_not_actionable(self):
        real = d.sl.entry_order
        with unittest.mock.patch.object(d.sl, "entry_order", lambda res, atr, p: (real(res, atr, p)[0], float("nan"))):
            r = analyze(data(BELOW), portfolio_usdt=287)
        self.assertFalse(r["actionable"])
        self.assertIn("PLAN_INCOMPLETE", [w["code"] for w in r["warnings"]])
        row = d.scan_row(r, False)
        self.assertEqual((row["actionable"], row["tier"]), (False, "E"))
        ok = d.scan_row(analyze(data(BELOW), portfolio_usdt=287), False)
        self.assertEqual((ok["actionable"], ok["tier"]), (True, "B"))
        self.assertLess(d.rank_key(ok, 5)[0], d.rank_key(row, 0)[0])


WITH_CEILING = ending((99.0, 32), base=np.r_[zigzag(3200, 95.0, 100.6), zigzag(3200, 95.0, 100.0, drift=DRIFT)[1:]])


class RankingTest(unittest.TestCase):
    def test_actionable_setup_comes_before_an_aligned_one_without_a_plan(self):
        ready = analyze(data(BELOW, symbol="PLAN"))                              # full stop-limit plan, 1h flat
        watch = copy.deepcopy(ready)                                             # no plan, but 1h and 4h both rising
        watch.update(symbol="ALIGNED", pair="ALIGNEDUSDT", decision="WAIT_FOR_RETEST", scenario="RETEST", plan=None,
                     actionable=False, retest=None)
        for tf in ("1h", "4h"):
            watch["trend"][tf]["state"] = "STRONG_UPTREND"
        s = d.build_scan([watch, ready], [], {}, [], None)                       # the plan-less one is scanned first
        self.assertEqual([(row["symbol"], row["tier"]) for row in s["results"]], [("PLAN", "B"), ("ALIGNED", "E")])
        self.assertEqual(s["tiers"]["B"], ["PLAN"])
        aligned, flat = copy.deepcopy(ready), copy.deepcopy(ready)               # same tier: now the trend decides
        aligned.update(symbol="UP", pair="UPUSDT")
        for tf in ("1h", "4h"):
            aligned["trend"][tf]["state"], flat["trend"][tf]["state"] = "UPTREND", "RANGE"
        self.assertEqual([row["symbol"] for row in d.build_scan([flat, aligned], [], {}, [], None)["results"]], ["UP", "PLAN"])

    def test_low_rr_is_not_shown_as_a_ready_setup(self):
        path = ending((99.0, 40), (100.5, 12))
        ready = analyze(data(path, volume=np.r_[np.full(len(path) - 13, 1000.0), np.full(12, 2500.0)]))
        self.assertEqual(ready["decision"], "BUY_SETUP")
        row = d.scan_row(ready, False)
        self.assertEqual((row["group"], row["tier"]), ("READY_TO_WATCH", "A"))
        narrow = copy.deepcopy(ready)
        narrow["warnings"].append({"code": "LOW_RR", "text": "x"})
        low = d.scan_row(narrow, False)
        self.assertEqual((low["group"], low["tier"], low["low_rr_note"]), ("WAIT_FOR_BREAKOUT", "B_LOW_RR", d.LOW_RR_NOTE))
        self.assertEqual(narrow["decision"], "BUY_SETUP")                        # the advice itself is not filtered
        s = d.build_scan([narrow, ready], [], {}, [], None)
        self.assertEqual([r["tier"] for r in s["results"]], ["A", "B_LOW_RR"])
        self.assertIn("Plan mevcut fakat LOW_RR nedeniyle alt sırada.", d.format_scan(s))

    def test_low_rr_breakout_ranks_under_a_clean_retest(self):
        narrow = analyze(data(WITH_CEILING, symbol="TRXLIKE"), portfolio_usdt=287)   # stop-limit plan, resistance right above
        retest = analyze(data(LATER, symbol="STXLIKE"), portfolio_usdt=287)          # complete retest plan with room
        self.assertIn("LOW_RR", [w["code"] for w in narrow["warnings"]])
        self.assertNotIn("LOW_RR", [w["code"] for w in retest["warnings"]])
        self.assertTrue(narrow["actionable"] and retest["actionable"])
        s = d.build_scan([narrow, retest], [], {}, [], 287)                          # the narrow one is scanned first
        self.assertEqual([(r["symbol"], r["tier"]) for r in s["results"]], [("STXLIKE", "C"), ("TRXLIKE", "B_LOW_RR")])
        self.assertLess(d._distance(s["results"][1]), d._distance(s["results"][0]))  # ...and is nearer: still below
        self.assertEqual(s["results"][0]["summary"],
                         "Geri test planı hazır. R/R yeterli. Retest bölgesine yaklaşırsa yeniden kontrol.")
        self.assertEqual(narrow["decision"], "WAIT_FOR_BREAKOUT")                    # ranked lower, never refused
        self.assertIsNotNone(s["results"][1]["trigger"])
        clean = analyze(data(BELOW, symbol="CLEAN"))                                 # a breakout plan WITH room
        order = [r["tier"] for r in d.build_scan([narrow, clean, retest], [], {}, [], None)["results"]]
        self.assertEqual(order, ["C", "B", "B_LOW_RR"])
        self.assertEqual(d.TIER_ORDER, ["A", "C", "D", "B", "B_LOW_RR", "E"])

    def test_a_resistance_right_above_gives_the_low_rr_sentence(self):
        r = analyze(data(WITH_CEILING), portfolio_usdt=287)
        self.assertEqual(r["decision"], "WAIT_FOR_BREAKOUT")                     # still a plan: R/R is not a trade filter
        low = [w["text"] for w in r["warnings"] if w["code"] == "LOW_RR"]
        self.assertTrue(low and low[0].startswith("Kırılım seviyesi yakın ancak üst direnç nedeniyle hedef alanı dar"))
        self.assertLess(r["plan"]["RR_to_resistance_1"], d.LOW_RR)
        row = d.scan_row(r, False)
        self.assertTrue(row["low_rr"])
        self.assertEqual(row["tier"], "B_LOW_RR")
        self.assertEqual(row["summary"], "Kırılım seviyesi yakın ancak hedef alanı dar. Plan mevcut fakat LOW_RR nedeniyle alt sırada.")
        clear = d.scan_row(analyze(data(BELOW), portfolio_usdt=287), False)
        self.assertLess(d.rank_key(clear, 9)[0], d.rank_key(row, 0)[0])          # same tier: the narrow one comes after


def exchange(rows, symbols):
    """A client that serves a 24h ticker list and exchange metadata."""
    class Resp:
        status_code, text = 200, ""

        def __init__(self, body):
            self.body = body

        def json(self):
            return self.body

    class Client:
        async def get(self, url, timeout):
            return Resp({"symbols": symbols} if "exchangeInfo" in url else rows)
    return Client()


class UniverseTest(unittest.TestCase):
    def setUp(self):
        d._meta.update(at=0.0, data=None)
        self.addCleanup(lambda: d._meta.update(at=0.0, data=None))

    def test_metadata_decides_before_names(self):
        coin_set = [["SPOT", "MARGIN", "TRD_GRP_004", "TRD_GRP_005", "TRD_GRP_006"]]
        stock_set = [["SPOT", "MARGIN", "TRD_GRP_004", "TRD_GRP_006"]]           # what tokenized stocks share
        stocks = ["NVDA", "TSLA", "AAPL", "MSFT", "AMZN", "GOOGL", "META", "AMD", "INTC", "COIN", "MSTR", "ZZTOP"]
        meta = lambda sym, base, sets, status="TRADING", spot=True: {
            "symbol": sym, "baseAsset": base, "quoteAsset": "USDT", "status": status, "isSpotTradingAllowed": spot,
            "permissions": [], "permissionSets": sets}
        symbols = [meta(f"{c}USDT", c, coin_set) for c in ("BTC", "ETH", "ARB", "SHIB", "JUP", "TRB", "PAXG", "USDX", "EUR")]
        symbols += [meta(f"{s}BUSDT", f"{s}B", stock_set) for s in stocks]
        symbols += [meta("ODDUSDT", "ODD", stock_set),                           # in the stock group without a stock name
                    meta("BTCUPUSDT", "BTCUP", [["LEVERAGED"]]), meta("ETHBULLUSDT", "ETHBULL", [["LEVERAGED"]]),
                    meta("OLDUSDT", "OLD", coin_set, status="BREAK"), meta("HALTUSDT", "HALT", coin_set, spot=False)]
        tick = lambda sym, vol=9e7, last="25.0", hi="26.0", lo="24.0": {"symbol": sym, "quoteVolume": str(vol),
                                                                          "lastPrice": last, "highPrice": hi, "lowPrice": lo}
        rows = [tick(x["symbol"]) for x in symbols if x["symbol"] != "USDXUSDT"]
        rows += [tick("USDXUSDT", last="1.0001", hi="1.0004", lo="0.9998"), tick("THINUSDT", vol=1000)]
        pairs, out = asyncio.run(d.universe(exchange(rows, symbols), limit=0, with_excluded=True))
        why = {x["symbol"]: x["reason_code"] for x in out}
        self.assertEqual({c for c, _ in pairs}, {"BTC", "ETH", "ARB", "SHIB", "JUP", "TRB"})   # coins ending in B stay
        self.assertTrue(all(why[f"{s}B"] == "EQUITY_TOKEN" for s in stocks))     # stock tokens, known name or not
        self.assertEqual(why["ODD"], "EQUITY_TOKEN")                             # the metadata group, not the name
        self.assertEqual((why["BTCUP"], why["ETHBULL"]), ("LEVERAGED", "LEVERAGED"))
        self.assertEqual((why["OLD"], why["HALT"]), ("INACTIVE", "INACTIVE"))
        self.assertEqual((why["PAXG"], why["EUR"], why["USDX"]), ("COMMODITY", "FIAT", "STABLE"))
        self.assertTrue(all(x["reason"] == d.EXCLUDE_TR[x["reason_code"]] for x in out))

    def test_without_metadata_names_decide_carefully(self):
        bases = {"BTC", "JUP", "BTCUP", "SUPER", "NVDAB", "ARB"}
        t = {"quoteVolume": "9e7", "lastPrice": "25", "highPrice": "26", "lowPrice": "24"}
        self.assertEqual(d.exclusion("BTCUP", t, None, bases), "LEVERAGED")      # BTC + UP, and BTC is listed
        self.assertIsNone(d.exclusion("JUP", t, None, bases))                    # not "J" up
        self.assertIsNone(d.exclusion("SUPER", t, None, bases))
        self.assertEqual(d.exclusion("NVDAB", t, None, bases), "EQUITY_TOKEN")
        self.assertIsNone(d.exclusion("ARB", t, None, bases))
        self.assertEqual(d.exclusion("ARB", {**t, "quoteVolume": "10"}, None, bases), "LOW_VOLUME")

    def test_debug_scan_lists_what_was_left_out(self):
        s = d.build_scan([], [], {}, [], None)
        s["excluded"] = [{"symbol": "NVDAB", "pair": "NVDABUSDT", "reason_code": "EQUITY_TOKEN", "reason": d.EXCLUDE_TR["EQUITY_TOKEN"]},
                         {"symbol": "THIN", "pair": "THINUSDT", "reason_code": "LOW_VOLUME", "reason": d.EXCLUDE_TR["LOW_VOLUME"]}]
        text = d.format_scan(s)
        self.assertIn("Tarama dışı bırakılanlar (debug):", text)
        self.assertIn("hisse / ETF tokenı (1): NVDAB", text)
        self.assertNotIn("Tarama dışı", d.format_scan(d.build_scan([], [], {}, [], None)))


FALLING_BTC = zigzag(len(BROKEN) - 1, 400, 403, drift=-0.03)
LOUD = np.r_[np.full(len(BROKEN) - 13, 1000.0), np.full(12, 2500.0)]


class BlockedSetupTest(unittest.TestCase):
    def test_setup_plus_btc_risk_is_blocked_not_no_setup(self):
        free = analyze(data(BROKEN, volume=LOUD), portfolio_usdt=287)
        r = analyze(data(BROKEN, btc_path=FALLING_BTC, volume=LOUD), portfolio_usdt=287)
        self.assertEqual(free["decision"], "BUY_SETUP")
        self.assertEqual((r["decision"], r["setup_class"]), ("BLOCKED_SETUP", "BLOCKED_SETUP"))
        self.assertEqual((r["underlying_setup"], r["blocked_reason"]), ("READY_TO_WATCH", "BTC_MARKET_RISK"))
        self.assertEqual(d.group_of(r), "BLOCKED_SETUP")
        self.assertNotEqual(d.group_of(r), "NO_SETUP")
        self.assertIsNone(r["plan"])                                             # nothing to act on, no size
        self.assertFalse(r["actionable"])
        self.assertIsNone(r["position_size"])
        self.assertEqual(r["blocked_plan"]["initial_stop"], free["plan"]["initial_stop"])   # the setup itself is kept
        self.assertEqual(r["scenario"], free["scenario"])
        self.assertNotEqual(r["setup_id"], free["setup_id"])
        self.assertTrue(r["setup_key"].startswith(free["setup_key"] + "|BLOCKED|"))
        self.assertIn("BTC", r["recheck_if"])
        text = d.format_report(r)
        self.assertIn("ENGELLİ", text)
        self.assertIn("yalnız bilgi içindir, uygulanmaz", text)
        self.assertNotIn("Pozisyon: portföy", text)

    def test_underlying_setup_is_kept_for_every_kind(self):
        waiting = analyze(data(BELOW, btc_path=FALLING_BTC))
        self.assertEqual((waiting["decision"], waiting["underlying_setup"]), ("BLOCKED_SETUP", "WAIT_FOR_BREAKOUT"))
        self.assertEqual(waiting["blocked_plan"]["type"], "STOP_LIMIT")
        quiet = np.r_[np.full(len(BROKEN) - 13, 1000.0), np.full(12, 300.0)]
        retest = analyze(data(BROKEN, btc_path=FALLING_BTC, volume=quiet))
        self.assertEqual((retest["decision"], retest["underlying_setup"]), ("BLOCKED_SETUP", "WAIT_FOR_RETEST"))
        self.assertEqual(retest["blocked_plan"]["type"], "RETEST_WAIT")
        nothing = analyze(data(FAILED, btc_path=FALLING_BTC))                    # no setup: nothing to block
        self.assertEqual((nothing["decision"], nothing["underlying_setup"], nothing["blocked_reason"]),
                         ("NO_SETUP", None, None))
        held = analyze(data(BELOW, btc_path=FALLING_BTC), position_usdt=35, average_price=100.4)
        self.assertNotEqual(held["decision"], "BLOCKED_SETUP")                   # a holder is told what to do with it

    def test_other_filters(self):
        short = data(BELOW)
        short["frames"] = {tf: f.tail(n).reset_index(drop=True) for (tf, f), n in zip(short["frames"].items(), (700, 175, 44, 7))}
        self.assertEqual(analyze(short)["blocked_reason"], "INSUFFICIENT_HISTORY")          # no 4h filter
        one_hour = frames_from(BELOW)["1h"]
        crowded = analyze(data(BELOW, others={"AAA": one_hour, "BBB": one_hour}))
        self.assertEqual((crowded["decision"], crowded["blocked_reason"]), ("BLOCKED_SETUP", "PORTFOLIO_CONCENTRATION"))
        r = d.block(analyze(data(BELOW)), "SOMETHING_NEW")
        self.assertEqual((r["decision"], r["blocked_reason"]), ("BLOCKED_SETUP", "OTHER"))

    def test_scan_groups_and_logs_blocked_setups(self):
        coins = {f"SAME{k}": data(BELOW, symbol=f"SAME{k}") for k in range(7)}
        coins["RISK"] = data(BELOW, symbol="RISK")
        logged = []

        async def fetcher(coin):
            return coins[coin]
        with unittest.mock.patch.object(d, "paper_log", lambda reports, source: logged.extend(reports) or len(reports)):
            s = asyncio.run(d.scan(symbols=list(coins), fetcher=fetcher, asof_ms=end_of(coins["RISK"]), paper="firsat"))
        held_back = [x["symbol"] for x in s["skipped_correlated"]]
        self.assertTrue(held_back)
        self.assertEqual(sorted(s["groups"]["BLOCKED_SETUP"]), sorted(held_back))
        self.assertFalse(set(held_back) & set(s["groups"]["WAIT_FOR_BREAKOUT"]))
        self.assertFalse(set(held_back) & set(s["groups"]["NO_SETUP"]))
        rows = {r["symbol"]: d.paper_row(r, "firsat") for r in logged}
        for sym in held_back:
            self.assertEqual((rows[sym]["setup_class"], rows[sym]["underlying_setup"], rows[sym]["blocked_reason"]),
                             ("BLOCKED_SETUP", "WAIT_FOR_BREAKOUT", "PORTFOLIO_CONCENTRATION"))
            self.assertIsNotNone(rows[sym]["stop"])                              # the plan is on record for comparison
        self.assertEqual(rows[s["results"][0]["symbol"]]["setup_class"], "WAIT_FOR_BREAKOUT")
        self.assertIn("Engelli kurulum", d.format_scan(s))


if __name__ == "__main__":
    unittest.main()
