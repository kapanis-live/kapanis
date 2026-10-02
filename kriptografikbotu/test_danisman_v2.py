"""Kripto Danışman V2 (danisman_v2/): closed candles only, deterministic order prices, structural stops, the position
state machine, the consensus vetoes, macro degradation, the paper log and the whipsaw measurement. No network.
Run: python -m unittest test_danisman_v2 -v
"""
import asyncio
import copy
import json
import os
import pathlib
import tempfile
import unittest

os.environ["ADVISOR_DATA_ORIGIN"] = "TEST"      # nothing a test logs may ever count as a live record
os.environ.setdefault("ADVISOR_PAPER_FILE", str(pathlib.Path(tempfile.mkdtemp()) / "advisor_paper.jsonl"))

import numpy as np
import pandas as pd

import danisman as d
import danisman_paper as dp
import test_danisman as t
from danisman_v2 import agents, config as cfg, consensus, macro, planner, protection, research, service, snapshot

M15 = d.TFS["15m"]
FILTERS = {"tick_size": 0.01, "step_size": 0.001, "min_qty": 0.001, "min_notional": 5.0}
PORTFOLIO = {"value": 1000.0, "holdings": []}
FRESH = t.ending((99.0, 32), (100.12, 9))                                              # just closed above the resistance
RETEST = t.ending((99.0, 32), (100.5, 12), (101.0, 6), (100.15, 6), (100.22, 1))       # broke out, left, came back, held
RECLAIM = t.ending((99.0, 32), (100.3, 10), (99.9, 6), (100.5, 8), (100.55, 3))         # failed, then taken back and held


def data(path, **kw) -> dict:
    out = t.data(path, **kw)
    out["filters"] = dict(FILTERS)
    return out


def snap(path, portfolio=PORTFOLIO, **kw) -> dict:
    dt = data(path)
    return snapshot.build(dt, portfolio, asof_ms=t.end_of(dt), **kw).data()


def live_snap(path, portfolio=PORTFOLIO) -> dict:
    """The last candle of the path is still open (half way through)."""
    dt = data(path)
    return snapshot.build(dt, portfolio, now_ms=int(dt["frames"]["15m"].t.iloc[-1]) + M15 // 2).data()


def held(entry, stop=None, qty=1.0):
    return {"value": 1000.0, "holdings": [{"symbol": "TEST", "quantity": qty, "entry_price": entry, "initial_stop": stop, "value": None}]}


def answer(role, verdict, **extra) -> str:
    base = {"role": role, "verdict": verdict, "confidence": 0.7, "reason": "test"}
    base.update({k: [] for k in agents.LISTS[role]})
    if role == "TECHNICAL":
        base["setup"] = "BREAKOUT"
    base.update(extra)
    return json.dumps(base)


def clients(technical="BUY", risk="APPROVE", regime="ALLOW", raw=None) -> dict:
    """Three analysts whose model answers what the test says. raw: {role: text or Exception} overrides one."""
    out = {}
    for role, verdict in (("TECHNICAL", technical), ("RISK", risk), ("REGIME", regime)):
        text = (raw or {}).get(role, answer(role, verdict))

        async def post(url, headers, body, timeout, text=text):
            if isinstance(text, Exception):
                raise text
            return {"choices": [{"message": {"content": text}}], "usage": {"prompt_tokens": 10, "completion_tokens": 5}}
        out[role] = agents.AdvisorAIClient("test", "model-x", "SECRET-KEY-123", "http://ai.test", post=post)
    return out


def run(path=t.BELOW, **kw):
    kw.setdefault("clients", clients())
    dt = data(path)
    return asyncio.run(service.analyze("TEST", kw.pop("portfolio", PORTFOLIO), data=dt, asof_ms=t.end_of(dt), log_paper=False, **kw))


class TickTest(unittest.TestCase):
    def test_trigger_is_the_first_tick_above_the_level(self):
        self.assertEqual(snapshot.next_tick(100.0, 0.01), 100.01)
        self.assertEqual(snapshot.next_tick(100.0459, 0.01), 100.05)
        self.assertEqual(snapshot.next_tick(0.04857, 0.00001), 0.04858)
        self.assertEqual(snapshot.floor_tick(94.8961, 0.01), 94.89)

    def test_limit_is_above_the_trigger_and_inside_the_cap(self):
        trigger, limit, band = planner.order_prices(100.0459, atr15=0.2, tick=0.01)
        self.assertEqual((trigger, limit), (100.05, 100.07))            # max(2 ticks, 0.10 ATR15) = 0.02
        trigger, limit, _ = planner.order_prices(100.0, atr15=10.0, tick=0.01)   # a wild ATR: the 0.25 % cap decides
        self.assertLessEqual(limit - trigger, trigger * cfg.MAX_EXECUTION_BUFFER_PCT / 100 + 1e-9)
        trigger, limit, _ = planner.order_prices(1.0, atr15=0.0001, tick=0.01)   # a coarse tick: still one tick above
        self.assertGreaterEqual(limit, trigger + 0.01 - 1e-12)


class SnapshotTest(unittest.TestCase):
    def test_the_snapshot_is_immutable_and_the_same_candles_give_the_same_hash(self):
        dt = data(t.BELOW)
        a = snapshot.build(dt, PORTFOLIO, asof_ms=t.end_of(dt))
        b = snapshot.build(copy.deepcopy(dt), PORTFOLIO, asof_ms=t.end_of(dt))
        self.assertEqual(a.hash, b.hash)
        with self.assertRaises(Exception):
            a.hash = "x"
        one = a.data()
        one["current_price"] = 1.0                      # a copy: the snapshot itself cannot be changed through it
        self.assertEqual(a.data()["current_price"], b.data()["current_price"])
        self.assertNotEqual(snapshot.build(data(FRESH), PORTFOLIO, asof_ms=t.end_of(data(FRESH))).hash, a.hash)

    def test_it_carries_every_timeframe_the_zones_the_btc_regime_and_the_order_rules(self):
        s = snap(t.BELOW)
        for tf in ("15m", "1h", "4h", "1d"):
            ind = s["timeframes"][tf]["indicators"]
            for key in ("sma20", "sma50", "ema20", "rsi14", "atr14", "volume_ma20", "volume_ratio"):
                self.assertIn(key, ind)
            self.assertTrue(s["timeframes"][tf]["candles"])
        self.assertIsNotNone(s["timeframes"]["15m"]["indicators"]["vwap"])
        zone = s["structure"]["nearest_resistance"]
        self.assertEqual(set(zone) >= {"low", "high", "touch_count", "last_touch_timestamp", "timeframe", "strength", "source"}, True)
        self.assertIn("1h", zone["timeframe"])                                   # 15m swings never make a main zone
        self.assertEqual(s["execution"]["tick_size"], 0.01)
        self.assertEqual(s["btc"]["regime"], "RISK_ON")
        self.assertEqual((s["market_timestamp_ms"], s["live"], s["stale"]), (t.end_of(data(t.BELOW)), False, False))

    def test_an_open_candle_gives_the_price_and_confirms_nothing(self):
        above = t.ending((100.6, 1), base=t.BELOW)        # the candle that is still open has jumped over the resistance
        s = live_snap(above)
        self.assertEqual(s["current_price"], 100.6)
        self.assertLess(s["last_closed_15m"], 100.0)
        st = s["structure"]
        self.assertFalse(st["confirmed_breakout"])
        self.assertTrue(st["open_candle_above"])
        e = planner.build_buy_plan(s)
        self.assertEqual((e["status"], e["plan"]), ("WAIT_FOR_BREAKOUT", None))  # far above the trigger: nothing to chase
        self.assertIn("NO_CHASE", [w["code"] for w in e["waits"]])
        closed = snap(above)                               # the same candle, closed: now it is a breakout
        self.assertTrue(closed["structure"]["confirmed_breakout"])

    def test_stale_data_gives_no_buy_plan(self):
        dt = data(t.BELOW)
        s = snapshot.build(dt, PORTFOLIO, now_ms=t.end_of(dt) + (cfg.MAX_DATA_AGE_SECONDS + 600) * 1000).data()
        self.assertTrue(s["stale"])
        e = planner.build_buy_plan(s)
        self.assertEqual((e["plan"], e["status"]), (None, "BLOCKED_SETUP"))
        self.assertIn("DATA_STALE", [b["code"] for b in e["blocks"]])

    def test_btc_falling_is_a_caution_or_a_block_for_an_altcoin(self):
        falling = t.zigzag(t.N, 100.0, 95.0, drift=-0.0045)
        dt = t.data(t.BELOW, btc_path=falling)
        regime = snapshot.btc_regime(dt, t.end_of(dt))
        self.assertIn(regime["regime"], ("CAUTION", "RISK_OFF"))
        self.assertIn(regime["trend_4h"], snapshot.DOWNS)


class BuyPlanTest(unittest.TestCase):
    def test_a_pending_breakout_is_a_stop_limit_one_tick_above_the_resistance(self):
        s = snap(t.BELOW)
        e = planner.build_buy_plan(s)
        plan, res = e["plan"], s["structure"]["nearest_resistance"]
        self.assertEqual((e["status"], e["setup"], e["result"], plan["kind"]), ("WAIT_FOR_BREAKOUT", "BREAKOUT", "BUY_SETUP", "BREAKOUT_PENDING"))
        self.assertGreater(plan["trigger"], res["high"])
        self.assertAlmostEqual(plan["trigger"], snapshot.next_tick(res["high"], 0.01))
        self.assertGreaterEqual(plan["limit"], plan["trigger"])
        self.assertEqual(e["evidence_status"], "RESEARCH_UNPROVEN")              # never sold as a proven edge
        self.assertFalse(plan["order_sent"])

    def test_the_initial_stop_sits_under_a_support_and_is_not_a_fixed_percentage(self):
        plan = planner.build_buy_plan(snap(t.BELOW))["plan"]
        sup = snap(t.BELOW)["structure"]["nearest_support"]
        self.assertLess(plan["technical_stop"], sup["low"])
        self.assertLess(plan["technical_stop"], plan["technical_invalidation"])   # the stop has a buffer under the level
        self.assertLess(plan["technical_invalidation"], plan["trigger"])
        other = planner.build_buy_plan(snap(RETEST))["plan"]
        self.assertNotAlmostEqual(plan["stop_distance_pct"], other["stop_distance_pct"], places=1)
        self.assertIsNone(planner.technical_stop(100.0, [], 0.2, 0.5, 0.01))      # no level: no stop, never "minus 2 %"
        self.assertIsNone(planner.technical_stop(100.0, [(101.0, "above the entry")], 0.2, 0.5, 0.01))

    def test_a_stop_inside_normal_movement_is_skipped_or_flagged(self):
        near, far = 99.9, 99.0                           # ATR15 0.2: the room wanted is 0.3
        st = planner.technical_stop(100.0, [(near, "yakın"), (far, "uzak")], atr15=0.2, atr1h=0.4, tick=0.01)
        self.assertEqual((st["technical_invalidation"], st["too_tight"]), (99.0, False))
        self.assertEqual(st["skipped"]["name"], "yakın")
        only = planner.technical_stop(100.0, [(near, "yakın")], atr15=0.2, atr1h=0.4, tick=0.01)
        self.assertTrue(only["too_tight"])                # nothing lower exists: used, and said
        self.assertIn("STOP_TOO_TIGHT", [w["code"] for w in planner.build_buy_plan(snap(RETEST))["warnings"]])

    def test_no_chase_and_no_buy_before_the_retest_zone_is_reached(self):
        s = snap(t.BROKEN)
        e = planner.build_buy_plan(s)
        self.assertEqual((e["status"], e["result"], e["plan"]), ("WAIT_FOR_RETEST", "WAIT", None))
        self.assertEqual({w["code"] for w in e["waits"]}, {"NO_CHASE", "RETEST_NOT_REACHED"})
        wait = e["withheld_plan"]
        self.assertEqual(wait["type"], "RETEST_WAIT")
        self.assertEqual(wait["broken_resistance"], s["structure"]["broken_resistance"])
        self.assertLess(wait["retest_zone"][0], wait["retest_zone"][1])
        self.assertGreater(e["retest"]["current_distance_atr15"], cfg.NO_CHASE_ATR15)
        self.assertTrue(e["why_not"])

    def test_a_fresh_close_just_above_the_level_is_a_breakout_setup(self):
        e = planner.build_buy_plan(snap(FRESH))
        self.assertEqual((e["status"], e["setup"], e["plan"]["kind"]), ("BUY_SETUP", "BREAKOUT", "BREAKOUT_CONFIRMED"))
        self.assertTrue(e["plan"]["already_above_trigger"])
        self.assertLessEqual(e["plan"]["distance_to_trigger_atr15"], cfg.NO_CHASE_ATR15)

    def test_a_retest_needs_a_closed_15m_candle_that_held_the_level(self):
        s = snap(RETEST)
        rt = s["structure"]["retest"]
        self.assertTrue(rt["entered_zone"])
        conf = rt["confirmation"]
        self.assertGreater(conf["close"], rt["broken_resistance"])
        self.assertLessEqual(conf["low"], rt["zone_high"])
        e = planner.build_buy_plan(s)
        self.assertEqual((e["status"], e["setup"], e["plan"]["kind"]), ("BUY_SETUP", "RETEST", "RETEST_CONFIRMED"))
        self.assertAlmostEqual(e["plan"]["trigger"], snapshot.next_tick(conf["high"], 0.01))
        self.assertLess(e["plan"]["technical_stop"], rt["zone_low"])
        # the candle that comes back to the zone is still open: no confirmation, no order
        returning = t.ending((99.0, 32), (100.5, 12), (101.0, 6), (100.4, 4), (100.15, 1))
        live = live_snap(returning)
        self.assertIsNone(live["structure"]["retest"]["confirmation"])
        self.assertFalse(live["structure"]["retest"]["entered_zone"])
        self.assertEqual(planner.build_buy_plan(live)["plan"], None)
        self.assertIsNotNone(snap(returning)["structure"]["retest"]["confirmation"])   # once it has closed, it counts

    def test_a_failed_breakout_gives_no_buy_until_it_is_reclaimed_and_a_reclaim_is_watch_only(self):
        e = planner.build_buy_plan(snap(t.FAILED))
        self.assertEqual((e["status"], e["result"], e["plan"]), ("RECLAIM_WATCH", "WAIT", None))
        self.assertIn("FAILED_BREAKOUT_NOT_RECLAIMED", [w["code"] for w in e["waits"]])
        s = snap(RECLAIM)
        rc = s["structure"]["reclaim"]
        self.assertTrue(rc and rc["confirmed"] and rc["held_bars"] >= cfg.RECLAIM_HOLD_BARS)
        e = planner.build_buy_plan(s)
        self.assertEqual((e["status"], e["setup"], e["plan"], e["actionable"]), ("RECLAIM_WATCH", "RECLAIM", None, False))
        self.assertEqual(e["withheld_plan"]["kind"], "RECLAIM_HELD")            # kept for the paper log only
        s1 = snap(t.ending((99.0, 32), (100.25, 6), (99.95, 4), (100.2, 1)))    # a single candle back above: not held yet
        self.assertEqual((s1["structure"]["reclaim"]["confirmed"], s1["structure"]["reclaim"]["held_bars"]), (False, 0))
        e1 = planner.build_buy_plan(s1)
        self.assertEqual((e1["status"], e1["plan"], e1["withheld_plan"]), ("RECLAIM_WATCH", None, None))
        self.assertIn("RECLAIM_NOT_HELD", [w["code"] for w in e1["waits"]])

    def test_outside_filters_block_the_setup_and_keep_its_levels_on_record(self):
        base = snap(t.BELOW)
        for change, code in ((("structure", "trend_4h", "STRONG_DOWN"), "4H_STRONG_DOWN"),
                             (("structure", "trend_1h", "DOWN"), "TREND_1H_DOWN"),
                             (("structure", "trend_1d", "STRONG_DOWN"), "HTF_STRONG_DOWNTREND"),
                             (("btc", "regime", "RISK_OFF"), "BTC_MARKET_RISK")):
            s = copy.deepcopy(base)
            s[change[0]][change[1]] = change[2]
            e = planner.build_buy_plan(s)
            self.assertEqual((e["status"], e["result"], e["plan"], e["actionable"]), ("BLOCKED_SETUP", "BLOCKED_SETUP", None, False), code)
            self.assertIn(code, [b["code"] for b in e["blocks"]])
            self.assertEqual(e["underlying_status"], "WAIT_FOR_BREAKOUT")
            self.assertEqual(e["withheld_plan"]["trigger"], planner.build_buy_plan(base)["plan"]["trigger"])
        s = copy.deepcopy(base)
        s["btc"]["regime"] = "CAUTION"                    # a falling BTC that is not a rout: a warning, not a block
        e = planner.build_buy_plan(s)
        self.assertTrue(e["plan"])
        self.assertIn("BTC_CAUTION", [w["code"] for w in e["warnings"]])
        s = copy.deepcopy(base)
        s["execution"] = None                             # the exchange's order rules are unknown: no price is made up
        self.assertIn("DATA_ERROR", [b["code"] for b in planner.build_buy_plan(s)["blocks"]])
        s = copy.deepcopy(base)
        s["insufficient_history"] = ["4h"]
        self.assertIn("INSUFFICIENT_HISTORY", [b["code"] for b in planner.build_buy_plan(s)["blocks"]])

    def test_rsi_alone_never_makes_a_buy(self):
        s = snap(t.BASE)
        self.assertEqual(planner.build_buy_plan(s)["result"], "NO_SETUP")
        for tf in ("15m", "1h", "4h"):
            s["timeframes"][tf]["indicators"]["rsi14"] = 12.0
        e = planner.build_buy_plan(s)
        self.assertEqual((e["result"], e["plan"]), ("NO_SETUP", None))

    def test_structural_target_first_and_the_r_fallback_only_without_one(self):
        zones = [{"low": 100.2, "high": 100.3}, {"low": 103.0, "high": 103.4}]
        tp = planner.take_profit(100.0, 1.0, zones, atr1h=1.0, above=100.05)      # 100.2 is inside noise: skipped
        self.assertEqual((tp["price"], tp["source"], tp["research_fallback"]), (103.0, "STRUCTURAL_RESISTANCE", False))
        tp = planner.take_profit(100.0, 1.0, [], atr1h=1.0, above=100.05)
        self.assertEqual((tp["price"], tp["source"], tp["research_fallback"]), (102.5, "FALLBACK_2_5R", True))
        plan = planner.build_buy_plan(snap(t.BELOW))["plan"]                     # nothing above the broken level here
        self.assertEqual((plan["take_profit_source"], plan["take_profit_is_research_fallback"]), ("FALLBACK_2_5R", True))


class SizingTest(unittest.TestCase):
    def test_size_comes_from_the_risk_budget_and_is_cut_by_the_caps(self):
        s = snap(t.BELOW)
        plan = planner.build_buy_plan(s)["plan"]
        pos = plan["position"]
        risk_frac = (plan["trigger"] - plan["technical_stop"]) / plan["trigger"]
        self.assertAlmostEqual(pos["risk_budget"], 1000 * cfg.RISK_PER_TRADE_PCT / 100)
        self.assertAlmostEqual(pos["risk_based_notional"], pos["risk_budget"] / risk_frac, places=1)
        self.assertLessEqual(pos["suggested_notional"], 1000 * cfg.MAX_NEW_POSITION_PCT / 100 + 1e-9)
        self.assertEqual(pos["limited_by"], "MAX_NEW_POSITION")
        self.assertAlmostEqual(pos["loss_at_stop"], pos["quantity"] * (plan["trigger"] - plan["technical_stop"]), places=2)

    def test_without_a_portfolio_there_is_no_size(self):
        plan = planner.build_buy_plan(snap(t.BELOW, portfolio=None))["plan"]
        self.assertEqual((plan["position"], plan["position_note"]), (None, "PORTFOLIO_REQUIRED_FOR_SIZING"))

    def test_exchange_minimum_and_exposure_limits(self):
        tiny = planner.build_buy_plan(snap(t.BELOW, portfolio={"value": 100.0, "holdings": []}))["plan"]
        self.assertEqual((tiny["position"], tiny["position_note"]), (None, "BELOW_EXCHANGE_MINIMUM"))   # 3 % of 100 < 5
        full = {"value": 1000.0, "holdings": [{"symbol": "AAA", "value": 400.0}]}                    # 40 % in altcoins already
        e = planner.build_buy_plan(snap(t.BELOW, portfolio=full))
        self.assertEqual((e["status"], e["plan"]), ("BLOCKED_SETUP", None))
        self.assertIn("MAX_EXPOSURE_REACHED", [b["code"] for b in e["blocks"]])
        near = {"value": 1000.0, "holdings": [{"symbol": "AAA", "value": 290.0}]}                    # 10 left under the limit
        pos = planner.build_buy_plan(snap(t.BELOW, portfolio=near))["plan"]["position"]
        self.assertEqual(pos["limited_by"], "MAX_ALT_EXPOSURE")
        self.assertLessEqual(pos["suggested_notional"], 10.0)
        self.assertIn("HIGH_ALT_EXPOSURE", [w["code"] for w in planner.build_buy_plan(snap(t.BELOW, portfolio=near))["warnings"]])
        self.assertEqual(pos["limit_basis"], "CONFIGURED_POLICY")             # an exposure limit is the admin's policy...
        free = planner.build_buy_plan(snap(t.BELOW))["plan"]["position"]
        self.assertIsNone(free["limit_basis"])                                # ...the position cap and the risk budget are not
        pol = cfg.policy()
        self.assertEqual((pol["basis"], set(pol["limits"])), ("CONFIGURED_POLICY", set(cfg.POLICY_LIMITS)))


class ProtectionTest(unittest.TestCase):
    def test_sell_means_a_protection_plan_with_r(self):
        p = protection.build_protection_plan(snap(t.BELOW, portfolio=held(98.5, stop=97.5)))
        self.assertEqual((p["action"], p["state"], p["order_sent"]), ("HOLD", "INITIAL", False))
        self.assertAlmostEqual(p["current_R"], 0.5)
        self.assertEqual((p["stop_loss"], p["stop_source"]), (97.5, "INITIAL_STRUCTURAL_STOP"))   # below +1R: not moved to break-even
        self.assertFalse(p["initial_stop_assumed"])
        self.assertIsNotNone(p["technical_invalidation"])
        self.assertIsNone(protection.build_protection_plan(snap(t.BELOW))["action"])               # no position: nothing to protect

    def test_break_even_only_from_1r_and_only_with_room(self):
        p = protection.build_protection_plan(snap(t.BELOW, portfolio=held(98.0, stop=97.5)))       # +2R
        self.assertGreaterEqual(p["current_R"], 2.0)
        self.assertEqual(p["stop_source"], "BREAK_EVEN_PLUS_FEES")
        self.assertGreater(p["stop_loss"], 98.0)
        self.assertGreaterEqual(p["breathing_room_atr15"], cfg.MIN_STOP_ATR15)
        tight = protection.build_protection_plan(snap(t.BELOW, portfolio=held(98.9, stop=98.82)))  # +1R but 0.1 above the cost
        self.assertEqual(tight["stop_source"], "INITIAL_STRUCTURAL_STOP")
        self.assertIn("BREAK_EVEN_SKIPPED", [w["code"] for w in tight["warnings"]])

    def test_the_stop_never_moves_down(self):
        s = snap(t.BELOW, portfolio=held(98.0, stop=97.5))
        first = protection.build_protection_plan(s)
        state = dict(first["new_state"], last_stop=98.6, last_stop_source="CONFIRMED_HIGHER_LOW")
        again = protection.build_protection_plan(s, state)
        self.assertEqual((again["stop_loss"], again["stop_source"]), (98.6, "CONFIRMED_HIGHER_LOW"))
        self.assertGreaterEqual(again["new_state"]["last_stop"], state["last_stop"])
        manual = protection.build_protection_plan(s, state, manual_stop=97.9)                      # only the user may lower it
        self.assertEqual((manual["stop_loss"], manual["stop_source"]), (97.9, "MANUAL_OVERRIDE"))

    def test_an_unknown_first_stop_is_said_and_then_kept(self):
        s = snap(t.BELOW, portfolio=held(98.0))
        p = protection.build_protection_plan(s)
        self.assertTrue(p["initial_stop_assumed"])
        self.assertIn("ESTIMATED_R", [w["code"] for w in p["warnings"]])
        self.assertEqual((p["current_R_estimated"], p["r_basis"], p["initial_stop_source"]), (True, "ESTIMATED_R", "ASSUMED_ATR"))
        again = protection.build_protection_plan(s, p["new_state"])
        self.assertEqual(again["initial_stop"], p["initial_stop"])                                 # R keeps its unit
        self.assertTrue(again["current_R_estimated"])                                             # and stays an estimate
        real = protection.build_protection_plan(snap(t.BELOW, portfolio=held(98.0, stop=97.5)))
        self.assertEqual((real["current_R_estimated"], real["r_basis"]), (False, "RECORDED_INITIAL_STOP"))
        # the real first stop is given later: it replaces the stored assumption, and R stops being an estimate
        later = protection.build_protection_plan(snap(t.BELOW, portfolio=held(98.0, stop=97.5)), p["new_state"])
        self.assertEqual((later["initial_stop"], later["current_R_estimated"], later["new_state"]["initial_stop_assumed"]), (97.5, False, False))
        kept = protection.build_protection_plan(snap(t.BELOW, portfolio=held(98.0, stop=97.0)), later["new_state"])
        self.assertEqual(kept["initial_stop"], 97.5)                                              # a recorded first stop is not rewritten
        text = run(portfolio=held(98.0))["text"]
        self.assertIn("(tahmini", text)                                                           # never shown as a real R
        self.assertNotIn("(tahmini", run(portfolio=held(98.0, stop=97.5))["text"])

    def test_rsi_alone_never_sells_and_structure_does(self):
        s = snap(t.BELOW, portfolio=held(98.5, stop=97.5))
        for tf in ("15m", "1h", "4h"):
            s["timeframes"][tf]["indicators"]["rsi14"] = 91.0
        self.assertEqual(protection.build_protection_plan(s)["action"], "HOLD")
        s["structure"]["trend_4h"] = "STRONG_DOWN"
        p = protection.build_protection_plan(s)
        self.assertEqual(p["action"], "EXIT")
        self.assertEqual([x["code"] for x in p["exit_reasons"]], ["HTF_REVERSAL"])
        s = snap(t.BELOW, portfolio=held(98.5, stop=97.5))
        state = dict(protection.build_protection_plan(s)["new_state"], last_stop=99.5, market_timestamp="2000-01-01T00:00:00Z")
        p = protection.build_protection_plan(s, state)                                            # a closed candle traded under the stop
        self.assertEqual((p["action"], p["state"]), ("EXITED", "EXITED"))

    def test_target_is_the_resistance_above_or_the_fallback(self):
        p = protection.build_protection_plan(snap(t.BELOW, portfolio=held(98.5, stop=97.5)))
        self.assertEqual(p["take_profit_source"], "STRUCTURAL_RESISTANCE")
        self.assertGreater(p["take_profit"], p["current_price"])
        s = snap(t.BELOW, portfolio=held(98.5, stop=97.5))
        s["structure"]["resistances"] = []
        q = protection.build_protection_plan(s)
        self.assertEqual((q["take_profit_source"], q["take_profit"]), ("FALLBACK_2_5R", 98.5 + 2.5 * 1.0))
        self.assertLess(q["trailing_reference_3atr"], q["current_price"])

    def test_an_underwater_position_without_a_recorded_stop_gets_todays_structure(self):
        s = snap(t.BELOW, portfolio=held(103.0))                # bought higher, never told the advisor a stop
        p = protection.build_protection_plan(s)
        self.assertTrue(p["initial_stop_assumed"])
        self.assertEqual(p["stop_source"], "CURRENT_STRUCTURE")
        self.assertLess(p["stop_loss"], p["current_price"])     # a stop above the price would be no stop at all
        self.assertGreater(p["breathing_room_atr15"], 0)
        self.assertNotIn("STOP_BREACHED", [x["code"] for x in p["exit_reasons"]])
        self.assertLess(p["current_R"], 0)
        again = protection.build_protection_plan(s, p["new_state"])
        self.assertEqual(again["stop_loss"], p["stop_loss"])    # and from then on it only moves up
        known = protection.build_protection_plan(snap(t.BELOW, portfolio=held(103.0, stop=101.0)))
        self.assertEqual((known["action"], known["stop_loss"]), ("EXIT", 101.0))      # a recorded stop the price is under
        self.assertIn("STOP_BREACHED", [x["code"] for x in known["exit_reasons"]])
        s = snap(t.FAILED, portfolio=held(103.0, stop=90.0))    # bought long before, far above the failed level
        self.assertNotIn("FAILED_BREAKOUT_NO_RECLAIM", [x["code"] for x in protection.build_protection_plan(s)["exit_reasons"]])
        s = snap(t.FAILED, portfolio=held(100.2, stop=90.0))    # bought on that breakout
        self.assertIn("FAILED_BREAKOUT_NO_RECLAIM", [x["code"] for x in protection.build_protection_plan(s)["exit_reasons"]])

    def test_a_lost_major_support_ends_the_trade(self):
        s = snap(t.BELOW, portfolio=held(98.5, stop=97.5))
        s["structure"]["lost_support"] = {"low": 99.4, "high": 99.5, "bars_ago": 1, "touch_count": 3}
        p = protection.build_protection_plan(s)
        self.assertEqual((p["action"], [x["code"] for x in p["exit_reasons"]]), ("EXIT", ["MAJOR_SUPPORT_LOST"]))
        self.assertIsNone(snap(t.BELOW)["structure"]["lost_support"])


class ConsensusTest(unittest.TestCase):
    def setUp(self):
        self.engine = planner.build_buy_plan(snap(t.BELOW))

    def verdicts(self, technical="BUY", risk="APPROVE", regime="ALLOW", failed=()):
        out = {r: {"role": r, "status": "OK", "verdict": v} for r, v in (("TECHNICAL", technical), ("RISK", risk), ("REGIME", regime))}
        for r in failed:
            out[r] = {"role": r, "status": "FAILED", "verdict": None, "error": "TIMEOUT"}
        return out

    def test_the_only_way_to_a_released_plan(self):
        c = consensus.decide(self.verdicts(), self.engine)
        self.assertEqual((c["consensus"], c["plan_released"], c["final"]), ("BUY", True, "WAIT_FOR_BREAKOUT"))
        c = consensus.decide(self.verdicts(regime="CAUTION"), self.engine)                 # caution is not a veto
        self.assertTrue(c["plan_released"])

    def test_vetoes_and_missing_analysts(self):
        for kw, outcome in (({"risk": "REJECT"}, "NO_TRADE"), ({"regime": "BLOCK"}, "BLOCKED_SETUP"),
                            ({"technical": "WAIT"}, "WAIT"), ({"risk": "WAIT"}, "WAIT"),
                            ({"risk": "REDUCE_RISK"}, "CONSENSUS_DISAGREEMENT"),
                            ({"technical": "AVOID"}, "CONSENSUS_DISAGREEMENT"),
                            ({"failed": ("REGIME",)}, "DEGRADED_CONSENSUS")):
            c = consensus.decide(self.verdicts(**kw), self.engine)
            self.assertEqual((c["consensus"], c["plan_released"]), (outcome, False), kw)
        self.assertEqual(consensus.decide(None, self.engine)["consensus"], "DEGRADED_CONSENSUS")   # nobody was asked: no buy
        # two "yes" never outvote the risk veto
        self.assertFalse(consensus.decide(self.verdicts(technical="BUY", risk="REJECT", regime="ALLOW"), self.engine)["plan_released"])

    def test_the_analysts_cannot_create_a_setup_the_engine_does_not_have(self):
        blocked = planner.build_buy_plan(snap(t.FAILED))
        c = consensus.decide(self.verdicts(), blocked)
        self.assertEqual((c["consensus"], c["plan_released"], c["final"]), ("BUY", False, "RECLAIM_WATCH"))


class AgentTest(unittest.TestCase):
    def test_a_valid_answer_is_parsed_and_an_invalid_one_fails_after_one_retry(self):
        v = agents.parse_verdict("RISK", "<think>hmm</think> " + answer("RISK", "approve", risk_flags=["stop geniş"]))
        self.assertEqual((v["verdict"], v["confidence"], v["risk_flags"]), ("APPROVE", 0.7, ["stop geniş"]))
        for bad in ("al gitsin", '{"role": "RISK", "verdict": "MAYBE", "confidence": 0.5}',
                    '{"role": "RISK", "verdict": "APPROVE", "confidence": 7}', '{"role": "REGIME", "verdict": "ALLOW", "confidence": 0.5}'):
            with self.assertRaises(ValueError):
                agents.parse_verdict("RISK", bad)
        calls = []

        async def post(url, headers, body, timeout):
            calls.append(len(body["messages"]))
            return {"choices": [{"message": {"content": "üzgünüm, JSON yazamadım"}}]}
        c = agents.AdvisorAIClient("test", "m", "SECRET-KEY-123", "http://ai.test", post=post)
        out = asyncio.run(c.analyze("TECHNICAL", snap(t.BELOW)))
        self.assertEqual((out["status"], out["verdict"], out["attempts"], len(calls)), ("FAILED", None, 2, 2))
        self.assertTrue(out["error"].startswith("INVALID_JSON"))
        self.assertEqual(calls, [2, 3])                    # the retry reminds the model of the format

    def test_a_timeout_and_a_provider_error_fail_without_leaking_the_key(self):
        async def slow(url, headers, body, timeout):
            await asyncio.sleep(1)
        c = agents.AdvisorAIClient("test", "m", "SECRET-KEY-123", "http://ai.test", timeout=0.01, post=slow)
        out = asyncio.run(c.analyze("RISK", snap(t.BELOW)))
        self.assertEqual((out["status"], out["error"]), ("FAILED", "TIMEOUT"))

        async def broken(url, headers, body, timeout):
            raise RuntimeError(f"401 for key {headers['Authorization']}")
        out = asyncio.run(agents.AdvisorAIClient("test", "m", "SECRET-KEY-123", "http://ai.test", post=broken).analyze("RISK", snap(t.BELOW)))
        self.assertEqual(out["status"], "FAILED")
        self.assertNotIn("SECRET-KEY-123", json.dumps(out)[:200] + json.dumps(agents.describe(clients())))

    def test_roles_without_a_key_are_not_configured_and_the_three_see_the_same_snapshot(self):
        self.assertEqual(set(agents.build_clients({}).values()), {None})                 # no key: nobody is configured
        built = agents.build_clients({"DEEPSEEK_API_KEY": "k1"})
        self.assertEqual({r: c.provider for r, c in built.items()}, dict.fromkeys(agents.ROLES, "deepseek"))
        built = agents.build_clients({"KIMI_API_KEY": "k2", "RISK_AI_PROVIDER": "nvidia", "RISK_AI_MODEL": "moonshotai/kimi-k3"})
        self.assertEqual((built["RISK"].provider, built["RISK"].model, built["TECHNICAL"]), ("nvidia", "moonshotai/kimi-k3", None))
        self.assertIsNone(agents.build_clients({"RISK_AI_PROVIDER": "nvidia", "NVIDIA_API_KEY": "k"})["RISK"])   # a provider without a model
        seen = {}

        def client(role):
            async def post(url, headers, body, timeout):
                seen[role] = body["messages"][1]["content"]
                return {"choices": [{"message": {"content": answer(role, agents.VERDICTS[role][0])}}]}
            return agents.AdvisorAIClient("test", "m", "k", "http://ai.test", post=post)
        s = snap(t.BELOW)
        out = asyncio.run(agents.run_agents({r: client(r) for r in agents.ROLES}, s, planner.build_buy_plan(s), None))
        self.assertEqual(len(set(seen.values())), 1)       # one payload, three independent readers
        self.assertEqual({v["status"] for v in out.values()}, {"OK"})
        for role in agents.ROLES:
            self.assertIn("-0.21R", agents.system_prompt(role))                # the research facts go to every analyst
            self.assertIn("You do not set order prices", agents.system_prompt(role))
        missing = asyncio.run(agents.run_agents({"TECHNICAL": client("TECHNICAL")}, s, planner.build_buy_plan(s), None))
        self.assertEqual(missing["RISK"]["error"], "NOT_CONFIGURED")

    def test_the_three_analysts_together_have_a_hard_time_limit(self):
        async def never(url, headers, body, timeout):
            await asyncio.sleep(30)
        cs = clients()
        cs["REGIME"] = agents.AdvisorAIClient("test", "slow-model", "k", "http://ai.test", timeout=30, post=never)
        old = cfg.AI_TOTAL_TIMEOUT_SECONDS
        cfg.AI_TOTAL_TIMEOUT_SECONDS = 0.3
        try:
            s = snap(t.BELOW)
            engine = planner.build_buy_plan(s)
            out = asyncio.run(agents.run_agents(cs, s, engine, None))
        finally:
            cfg.AI_TOTAL_TIMEOUT_SECONDS = old
        self.assertEqual((out["TECHNICAL"]["status"], out["RISK"]["status"]), ("OK", "OK"))     # the fast ones are kept
        self.assertEqual((out["REGIME"]["status"], out["REGIME"]["error"], out["REGIME"]["model"]), ("FAILED", "TIMEOUT_TOTAL", "slow-model"))
        c = consensus.decide(out, engine)
        self.assertEqual((c["consensus"], c["plan_released"]), ("DEGRADED_CONSENSUS", False))    # one missing analyst: no buy

    def test_three_roles_on_one_model_are_not_called_three_models(self):
        same = agents.diversity(agents.build_clients({"DEEPSEEK_API_KEY": "k"}))
        self.assertEqual((same["configured_roles"], same["distinct_models"], same["model_diversity"]), (3, 1, False))
        mixed = agents.diversity(agents.build_clients({"DEEPSEEK_API_KEY": "k", "KIMI_API_KEY": "k2", "REGIME_AI_PROVIDER": "nvidia",
                                                       "REGIME_AI_MODEL": "moonshotai/kimi-k3"}))
        self.assertEqual((mixed["distinct_models"], mixed["model_diversity"]), (2, True))
        self.assertEqual(agents.diversity(agents.build_clients({}))["configured_roles"], 0)


class ServiceTest(unittest.TestCase):
    def test_a_full_run_releases_the_plan_only_when_everyone_agrees(self):
        r = run()
        self.assertEqual((r["final"], r["consensus"]["consensus"], r["mode"]), ("WAIT_FOR_BREAKOUT", "BUY", "NEW"))
        self.assertTrue(r["buy_plan"] and r["unreleased_plan"] is None)
        self.assertEqual((r["order_sent"], r["auto_trading"]), (False, False))
        self.assertIn("Emir gönderilmedi", r["text"])
        self.assertEqual(r["advisor_version"], cfg.ADVISOR_VERSION)
        self.assertEqual(len(r["ruleset_hash"]), 12)
        for kw in ({"clients": clients(risk="REJECT")}, {"clients": clients(regime="BLOCK")},
                   {"clients": clients(raw={"TECHNICAL": "json değil"})},
                   {"clients": clients(raw={"REGIME": RuntimeError("down")})},
                   {"clients": {"TECHNICAL": clients()["TECHNICAL"]}}, {"with_ai": False}):
            r = run(**kw)
            self.assertIsNone(r["buy_plan"], kw)
            self.assertTrue(r["unreleased_plan"]["trigger"])               # the engine's levels are shown as not released
            self.assertTrue(r["why_not_trade"])

    def test_the_same_snapshot_gives_the_same_order_plan_whatever_the_models_write(self):
        a = run(clients=clients())
        b = run(clients=clients(raw={"TECHNICAL": answer("TECHNICAL", "BUY", reason="bambaşka bir yorum", confidence=0.31,
                                                         levels_to_watch=["123456"])}))
        self.assertEqual(a["snapshot_hash"], b["snapshot_hash"])
        self.assertEqual(a["buy_plan"], b["buy_plan"])                       # prices come from code, not from the prose
        self.assertNotIn("123456", json.dumps(b["buy_plan"]))

    def test_openbb_down_does_not_take_the_technical_report_down(self):
        async def dead(section):
            raise RuntimeError("openbb yok")
        r = run(macro=macro.OpenBBService(runner=dead))
        self.assertEqual(r["snapshot"]["macro"]["macro_status"], "UNAVAILABLE")
        self.assertTrue(r["snapshot"]["macro"]["unavailable_fields"])
        self.assertEqual(r["engine"]["status"], "WAIT_FOR_BREAKOUT")
        self.assertTrue(r["buy_plan"])
        self.assertEqual(macro.OpenBBService(python="", url="").mode() in ("not_installed", "in_process"), True)
        self.assertEqual(macro.OpenBBService(python="", url="http://openbb:8010").mode(), "http")   # a separate worker service

    def test_a_slow_macro_read_is_not_waited_for(self):
        async def slow(section):
            await asyncio.sleep(5)
            return {"data": {}, "sources": [], "unavailable": []}
        old = cfg.MACRO_WAIT_SECONDS
        cfg.MACRO_WAIT_SECONDS = 0.2
        try:
            r = run(macro=macro.OpenBBService(runner=slow))
        finally:
            cfg.MACRO_WAIT_SECONDS = old
        self.assertEqual(r["snapshot"]["macro"]["macro_status"], "UNAVAILABLE")
        self.assertIn("arka planda", r["snapshot"]["macro"]["unavailable_fields"][0]["reason"])
        self.assertTrue(r["buy_plan"])                                        # the technical side did not wait

    def test_a_held_coin_gets_the_protection_plan_and_its_state(self):
        r = run(portfolio=held(98.5, stop=97.5))
        self.assertEqual((r["mode"], r["final"]), ("POSITION", "HOLD"))
        self.assertEqual(r["sell_plan"]["stop_loss"], 97.5)
        self.assertEqual(r["sell_plan"]["new_state"]["initial_risk"], 1.0)
        typed = run(position={"entry_price": 98.0, "quantity": 2.0, "initial_stop": 97.5})   # typed in by the admin
        self.assertEqual((typed["mode"], typed["sell_plan"]["entry_price"]), ("POSITION", 98.0))
        doc = service.audit_doc(r, "abc123")
        self.assertEqual((doc["admin_user_hash"], doc["order_sent"]), ("abc123", False))
        self.assertNotIn("snapshot", doc)
        for key in ("snapshot_hash", "technical_verdict", "risk_verdict", "regime_verdict", "final_consensus", "ruleset_hash",
                    "advisor_version", "git_commit", "working_tree_dirty", "models", "latency", "macro_snapshot_hash"):
            self.assertIn(key, doc)

    def test_scan_groups_and_orders_without_calling_a_model(self):
        paths = {"AAA": t.BELOW, "BBB": RETEST, "CCC": t.FAILED, "DDD": t.BASE, "EEE": t.BROKEN}

        async def fetcher(coin):
            if coin == "ZZZ":
                raise RuntimeError("no data")
            return data(paths[coin], symbol=coin)
        out = asyncio.run(service.scan(PORTFOLIO, symbols=[*paths, "ZZZ"], fetcher=fetcher, asof_ms=t.end_of(data(RETEST))))
        self.assertEqual(set(out["groups"]), set(planner.GROUPS))
        order = [r["symbol"] for r in out["results"]]
        self.assertEqual(order[0], "BBB")                                     # the complete, ready setup first
        self.assertLess(order.index("AAA"), order.index("DDD"))               # a pending breakout before "no setup"
        self.assertEqual({r["consensus"] for r in out["results"]}, {"NOT_REQUESTED"})
        self.assertEqual([f["symbol"] for f in out["failed"]], ["ZZZ"])
        self.assertTrue(all(r["rank_reasons"] for r in out["results"]))
        self.assertFalse(out["order_sent"])


class MacroTest(unittest.TestCase):
    NOW = macro.datetime(2026, 10, 2, 12, 0, tzinfo=macro.timezone.utc)

    def rows(self):
        return [{"time": "2026-10-02 08:30:00", "timezone": "America/New_York", "country": "United States", "event": "Nonfarm Payrolls",
                 "importance": None, "source": "x"},                              # 12:30 UTC: 30 minutes away
                {"time": "2026-10-02 10:00:00", "timezone": "America/New_York", "country": "United States", "event": "Factory Orders",
                 "importance": None, "source": "x"},
                {"time": "2026-10-02 09:00:00", "timezone": "America/New_York", "country": "India", "event": "PMI", "importance": None},
                {"time": "2026-10-02", "timezone": "America/New_York", "country": "United States", "event": "date only"}]

    def test_impact_is_never_guessed(self):
        events = macro.classify_events(self.rows(), self.NOW)
        self.assertEqual([e["event"] for e in events], ["Nonfarm Payrolls", "Factory Orders"])   # own countries, timed, upcoming
        self.assertEqual(events[0]["minutes_from_now"], 30)
        self.assertEqual({e["high_impact"] for e in events}, {None})          # no provider rating, no keyword list: unknown

    def test_the_admins_keyword_list_marks_events_and_drives_the_windows(self):
        old = cfg.MACRO_HIGH_IMPACT_KEYWORDS
        cfg.MACRO_HIGH_IMPACT_KEYWORDS = ("nonfarm", "cpi")
        try:
            async def runner(section):
                return {"data": {"economic_calendar": self.rows()} if section == "calendar" else {}, "sources": [], "unavailable": []}
            m = asyncio.run(macro.OpenBBService(runner=runner).get_macro_snapshot(self.NOW))
            self.assertEqual((m["caution"], m["block_new_entry"], m["high_impact_event_within_2h"]), (True, False, True))
            self.assertEqual(m["minutes_to_next_high_impact"], 30)
            near = asyncio.run(macro.OpenBBService(runner=runner).get_macro_snapshot(self.NOW + macro.timedelta(minutes=20)))
            self.assertTrue(near["block_new_entry"])                          # 10 minutes away
            s = snap(t.BELOW, macro=near)
            e = planner.build_buy_plan(s)
            self.assertEqual(e["status"], "BLOCKED_SETUP")
            self.assertIn("MACRO_EVENT_BLOCK", [b["code"] for b in e["blocks"]])
            self.assertIn("HIGH_IMPACT_EVENT_WINDOW", [w["code"] for w in planner.build_buy_plan(snap(t.BELOW, macro=m))["warnings"]])
        finally:
            cfg.MACRO_HIGH_IMPACT_KEYWORDS = old

    def test_reads_are_cached_and_a_failed_refresh_keeps_the_last_value_marked_stale(self):
        calls, fail = [], {"on": False}

        async def runner(section):
            calls.append(section)
            if fail["on"]:
                raise RuntimeError("provider down")
            return {"data": {"vix": {"last": 16.4, "change_1d_pct": 1.0}}, "sources": [{"field": "vix", "source": "OpenBB · Cboe"}],
                    "unavailable": []}
        svc = macro.OpenBBService(runner=runner)
        first = asyncio.run(svc.get_cross_asset_snapshot())
        asyncio.run(svc.get_cross_asset_snapshot())
        self.assertEqual(calls, ["cross_asset"])                              # the second read used the cache
        self.assertFalse(first["stale"])
        fail["on"] = True
        svc._cache["cross_asset"] = (0.0, svc._cache["cross_asset"][1])       # the cache is old now
        kept = asyncio.run(svc.get_cross_asset_snapshot())
        self.assertEqual((kept["stale"], kept["data"]["vix"]["last"]), (True, 16.4))
        m = asyncio.run(svc.get_macro_snapshot(self.NOW))
        self.assertEqual(m["macro_status"], "DEGRADED")
        self.assertIn("cross_asset", m["stale_fields"])
        self.assertTrue(all(u["reason"] for u in m["unavailable_fields"]))


class PaperTest(unittest.TestCase):
    def test_a_run_is_logged_once_under_its_own_ruleset_and_never_as_live_in_a_test(self):
        s = snap(t.BELOW)
        e = planner.build_buy_plan(s)
        row = research.paper_row(s, e, consensus.decide(None, e), "test")
        self.assertEqual((row["data_origin"], row["advisor_version"], row["engine"]), ("TEST", "2.0.0", "v2"))
        self.assertEqual(row["ruleset_hash"], research.ruleset_hash())
        self.assertNotEqual(row["ruleset_hash"], d.ruleset_hash())             # the first advisor's statistics stay apart
        self.assertEqual((row["plan_type"], row["trigger"], row["stop"]), ("STOP_LIMIT", e["plan"]["trigger"], e["plan"]["technical_stop"]))
        store = dp.JsonlStore(pathlib.Path(tempfile.mkdtemp()) / "p.jsonl")
        self.assertEqual((dp.log([row], store), dp.log([dict(row)], store)), (1, 0))   # the duplicate is refused
        later = research.paper_row(snap(FRESH), planner.build_buy_plan(snap(FRESH)), None, "test")
        self.assertNotEqual(later["setup_id"], row["setup_id"])
        self.assertEqual(dp.log([later], store), 1)
        blocked = snap(t.BELOW)
        blocked["btc"]["regime"] = "RISK_OFF"
        b = research.paper_row(blocked, planner.build_buy_plan(blocked), None, "test")
        self.assertEqual((b["setup_class"], b["blocked_reason"], b["stop"] is not None), ("BLOCKED_SETUP", "BTC_MARKET_RISK", True))
        self.assertNotEqual(b["setup_id"], row["setup_id"])

    def test_the_first_trackers_outcome_works_on_a_v2_record(self):
        s = snap(t.BELOW)
        row = research.paper_row(s, planner.build_buy_plan(s), None, "test")
        n = 100
        after = pd.DataFrame({"t": row["close_ms"] + np.arange(n) * M15, "o": 99.0, "h": 99.2, "l": 98.8, "c": 99.0})
        after.loc[3, ["h", "c"]] = [100.3, 100.2]                             # the trigger trades on the fourth candle
        after.loc[4:, ["o", "h", "l", "c"]] = [100.2, 100.4, 100.0, 100.2]
        out, done = dp.compute_outcome(row, after, row["close_ms"] + 25 * 3_600_000)
        self.assertEqual(done, ["1h", "4h", "24h"])
        self.assertTrue(out["triggered"])
        self.assertAlmostEqual(out["fill_price"], row["trigger"])


class WhipsawTest(unittest.TestCase):
    ROW = {"engine": "v2", "symbol": "T", "pair": "TUSDT", "close_ms": 0, "price": 99.5, "plan_type": "STOP_LIMIT",
           "trigger": 100.0, "limit": 100.2, "stop": 99.0, "invalidation": 98.8, "take_profit": 103.0,
           "take_profit_source": "STRUCTURAL_RESISTANCE", "atr_15m": 0.4, "atr_1h": 0.8, "stop_source": "destek − 0.15 ATR(1h)",
           "setup_class": "WAIT_FOR_BREAKOUT", "actionable": True, "setup_id": "s1", "data_origin": "LIVE", "decision": "WAIT_FOR_BREAKOUT"}

    def bars(self, after: list[tuple]) -> pd.DataFrame:
        """Flat candles before the record (ATR history), then (open, high, low, close) rows after it."""
        warm = [(99.5, 99.7, 99.3, 99.5)] * 80
        rows = warm + after
        times = (np.arange(len(rows)) - len(warm)) * M15
        return pd.DataFrame(rows, columns=["o", "h", "l", "c"]).assign(t=times)

    def test_a_stop_that_is_taken_back_at_once_is_a_whipsaw(self):
        after = [(99.6, 100.1, 99.5, 100.05), (100.05, 100.1, 98.95, 99.1), (99.1, 99.5, 99.05, 99.4)] + [(99.4, 99.6, 99.3, 99.5)] * 10
        out = research.simulate(self.ROW, self.bars(after))
        self.assertEqual((out["triggered"], out["fill_price"]), (True, 100.0))
        b = out["variants"]["B"]
        self.assertEqual((b["exit"], b["result_r"]), ("STOP", -1.0))
        w = b["whipsaw"]
        self.assertEqual((w["whipsaw_exit"], w["time_to_reclaim"], w["technical_invalidation_broken"]), (True, 15, False))
        self.assertEqual((w["stop_price"], w["initial_entry"], w["R_at_stop"]), (99.0, 100.0, -1.0))
        self.assertGreater(w["ATR15_at_stop"], 0)
        self.assertAlmostEqual(w["max_price_1h_after_stop"], 99.6)

    def test_a_stop_followed_by_a_real_breakdown_is_not(self):
        after = [(99.6, 100.1, 99.5, 100.05), (100.05, 100.1, 98.5, 98.6)] + [(98.6, 98.7, 98.2, 98.4)] * 10
        w = research.simulate(self.ROW, self.bars(after))["variants"]["B"]["whipsaw"]
        self.assertEqual((w["whipsaw_exit"], w["technical_invalidation_broken"], w["time_to_reclaim"]), (False, True, None))

    def test_the_four_exit_styles_differ_only_in_the_exit(self):
        up = [(99.6, 100.1, 99.5, 100.05)] + [(100.0 + k * 0.25, 100.3 + k * 0.25, 99.95 + k * 0.25, 100.25 + k * 0.25) for k in range(14)] \
            + [(103.4, 103.5, 100.5, 100.6)] + [(100.6, 100.7, 100.4, 100.5)] * 6
        out = research.simulate(self.ROW, self.bars(up))
        v = out["variants"]
        self.assertEqual((v["B"]["exit"], v["B"]["result_r"]), ("TP", 2.5))           # 102.5 comes before 103
        self.assertEqual((v["A"]["exit"], v["A"]["result_r"]), ("TP", 3.0))
        self.assertEqual(v["C"]["exit"], "TRAIL")                                     # 3 ATR(1h) under the top
        self.assertGreater(v["C"]["result_r"], 0)
        self.assertGreaterEqual(v["A"]["left_on_table_r"], 0)
        no_tp = dict(self.ROW, take_profit=102.5, take_profit_source="FALLBACK_2_5R")
        self.assertIsNone(research.simulate(no_tp, self.bars(up))["variants"]["A"])    # no structural target: style A does not apply
        never = research.simulate(self.ROW, self.bars([(99.5, 99.8, 99.3, 99.6)] * 12))
        self.assertEqual(never["triggered"], False)

    def test_statistics_are_inconclusive_below_the_sample_size(self):
        after = [(99.6, 100.1, 99.5, 100.05), (100.05, 100.1, 98.95, 99.1), (99.1, 99.5, 99.05, 99.4)] + [(99.4, 99.6, 99.3, 99.5)] * 10
        sim = research.simulate(self.ROW, self.bars(after))
        rows = [dict(self.ROW, setup_id=f"s{k}", close_ms=k, ruleset_hash="h", outcome={"v2": sim}, stop_distance_atr15=2.5) for k in range(5)]
        st = research.stats(rows, "LIVE")
        self.assertEqual((st["entered"], st["variants"]["B"]["sample_size"], st["variants"]["B"]["verdict"]), (5, 5, "INCONCLUSIVE"))
        b = st["variants"]["B"]
        self.assertEqual((b["expectancy_R"], b["stop_rate"], b["whipsaw_rate"]), (-1.0, 100.0, 100.0))
        self.assertEqual(st["variants"]["B"]["max_drawdown_R"], 5.0)
        self.assertEqual(st["whipsaw"]["all"], {"stops": 5, "whipsaw_rate": 100.0, "verdict": "INCONCLUSIVE"})
        self.assertEqual(research.stats(rows, "REPLAY")["entered"], 0)                 # origins are never mixed silently
        many = [dict(r, setup_id=f"m{k}") for k, r in enumerate(rows * 6)]
        self.assertEqual(research.stats(many, "LIVE")["variants"]["B"]["verdict"], "MEASURED")

    def test_update_outcomes_fills_only_v2_records_past_the_horizon(self):
        store = dp.JsonlStore(pathlib.Path(tempfile.mkdtemp()) / "p.jsonl")
        base = dict(self.ROW, ruleset_hash="h", outcome={}, outcome_done=[])
        dp.log([dict(base, setup_id="old"), dict(base, setup_id="young", close_ms=10**13), dict(base, setup_id="v1", engine=None),
                dict(base, setup_id="test", data_origin="TEST")], store)
        after = [(99.6, 100.1, 99.5, 100.05), (100.05, 100.1, 98.95, 99.1)] + [(99.2, 99.5, 99.1, 99.4)] * 300

        async def candles(pair, start, end):
            return self.bars(after)
        horizon = cfg.RESEARCH_HORIZON_HOURS * 3_600_000
        done = asyncio.run(research.update_outcomes(store, now_ms=horizon + 2 * M15, candles=candles))
        self.assertEqual(done, {"pending": 1, "updated": 1})
        by = {r["setup_id"]: r for r in store.all()}
        self.assertIn("v2", by["old"]["outcome"])
        self.assertTrue(all("v2" not in by[k]["outcome"] for k in ("young", "v1", "test")))


class RulesetTest(unittest.TestCase):
    def test_a_threshold_change_changes_the_hash_and_a_cache_time_does_not(self):
        before = research.ruleset_hash()
        old = cfg.MIN_STOP_ATR15
        cfg.MIN_STOP_ATR15 = 1.75
        try:
            self.assertNotEqual(research.ruleset_hash(), before)
        finally:
            cfg.MIN_STOP_ATR15 = old
        old = cfg.MACRO_CACHE_SECONDS
        cfg.MACRO_CACHE_SECONDS = 5
        try:
            self.assertEqual(research.ruleset_hash(), before)
        finally:
            cfg.MACRO_CACHE_SECONDS = old
        self.assertNotIn("KEY", json.dumps(cfg.public()).upper().replace("KEYWORDS", ""))   # no secret lives in the config


if __name__ == "__main__":
    unittest.main()
