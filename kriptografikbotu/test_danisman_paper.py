"""Advisor paper log (danisman_paper.py): setup ids, no duplicates, outcomes only when they are due and only from the
candles after the record, the record itself never rewritten, statistics per setup class."""
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
import danisman_paper as p
import test_danisman as t

M15, H1 = p.M15, 3_600_000
T0 = 1_760_000_400_000              # a 15m boundary


def candles(start_ms: int, rows: list[tuple]) -> pd.DataFrame:
    """15m candles (o, h, l, c) from start_ms on."""
    return pd.DataFrame({"t": [start_ms + k * M15 for k in range(len(rows))], "o": [r[0] for r in rows],
                         "h": [r[1] for r in rows], "l": [r[2] for r in rows], "c": [r[3] for r in rows]})


def flat(price: float, n: int) -> list[tuple]:
    return [(price, price + 0.05, price - 0.05, price)] * n


def record(**kw) -> dict:
    row = {"symbol": "TEST", "pair": "TESTUSDT", "setup_id": "s1", "setup_class": "WAIT_FOR_BREAKOUT", "close_ms": T0,
           "decision": "WAIT_FOR_BREAKOUT", "entry_type": "BREAKOUT", "price": 100.0, "level": 100.9,
           "plan_type": "STOP_LIMIT", "entry": 101.0, "trigger": 101.0, "limit": 101.2, "stop": 99.0, "invalidation": 99.2,
           "resistance_1": 104.0, "retest_zone": None, "retest_confirmation_price": None, "outcome": {}, "outcome_done": []}
    row.update(kw)
    return row


def mongo_collection():
    try:
        from pymongo import MongoClient
        client = MongoClient("mongodb://127.0.0.1:27017", serverSelectionTimeoutMS=800)
        client.admin.command("ping")
        return client, client["kapanis_test_advisor_paper"][p.COLLECTION]
    except Exception:
        return None, None


class SetupIdTest(unittest.TestCase):
    def test_same_setup_keeps_its_id_on_the_next_scan(self):
        first = t.analyze(t.data(t.BELOW))
        again = t.analyze(t.data(t.BELOW))
        next_candle = t.analyze(t.data(t.ending((99.0, 32), (99.05, 1))))       # fifteen minutes later, same resistance
        self.assertEqual(first["setup_id"], again["setup_id"])
        self.assertEqual(first["setup_id"], next_candle["setup_id"])
        self.assertNotEqual(first["as_of_ms"], next_candle["as_of_ms"])
        self.assertEqual(first["setup_key"].split("|")[:2], ["TEST", "BREAKOUT"])
        retest = t.analyze(t.data(t.BROKEN, volume=t.QUIET))
        path = t.ending((99.0, 32), (100.5, 12), (100.52, 1))
        later = t.analyze(t.data(path, volume=np.r_[np.full(len(path) - 14, 1000.0), np.full(13, 300.0)]))
        self.assertEqual((retest["decision"], later["decision"]), ("WAIT_FOR_RETEST",) * 2)
        self.assertEqual(retest["setup_id"], later["setup_id"])                  # same broken level, same breakout candle

    def test_new_level_or_new_breakout_is_a_new_setup(self):
        waiting = t.analyze(t.data(t.BELOW))
        higher = t.analyze(t.data(t.ending((100.0, 32), base=t.zigzag(t.N, 96.0, 101.0, drift=t.DRIFT))))
        self.assertEqual(higher["decision"], "WAIT_FOR_BREAKOUT")
        self.assertNotEqual(waiting["setup_id"], higher["setup_id"])            # another resistance
        retest = t.analyze(t.data(t.BROKEN, volume=t.QUIET))
        self.assertNotEqual(waiting["setup_id"], retest["setup_id"])            # the breakout happened: another setup
        self.assertEqual(len({waiting["setup_id"], higher["setup_id"], retest["setup_id"]}), 3)
        self.assertEqual(d.setup_identity("SOL", "WAIT_FOR_BREAKOUT", "BREAKOUT", None, 118.512, None, T0)["setup_id"],
                         d.setup_identity("SOL", "WAIT_FOR_BREAKOUT", "BREAKOUT", None, 118.5123, None, T0 + H1)["setup_id"])
        self.assertNotEqual(d.setup_identity("SOL", "WAIT_FOR_BREAKOUT", "BREAKOUT", None, 118.51, None, T0)["setup_id"],
                            d.setup_identity("SOL", "WAIT_FOR_BREAKOUT", "BREAKOUT", None, 119.80, None, T0)["setup_id"])

    def test_nothing_to_do_is_one_comparison_record_a_day(self):
        a = d.setup_identity("SOL", "NO_SETUP", "NO_TRADE", "NO_ROOM", None, None, T0)
        b = d.setup_identity("SOL", "NO_SETUP", "NO_TRADE", "NO_ROOM", None, None, T0 + H1)
        c = d.setup_identity("SOL", "NO_SETUP", "NO_TRADE", "NO_ROOM", None, None, T0 + 2 * p.DAY)
        self.assertEqual(a["setup_id"], b["setup_id"])
        self.assertNotEqual(a["setup_id"], c["setup_id"])
        self.assertEqual((a["setup_class"], d.setup_identity("SOL", "AVOID", "NO_TRADE", "DOWNTREND_1H", None, None, T0)["setup_class"]),
                         ("NO_SETUP", "AVOID"))


class StoreTest(unittest.TestCase):
    def stores(self):
        yield "jsonl", p.JsonlStore(pathlib.Path(tempfile.mkdtemp()) / "advisor_paper.jsonl")
        client, coll = mongo_collection()                  # the real unique index, when a local MongoDB is running
        if coll is not None:
            coll.drop()
            self.addCleanup(client.close)
            self.addCleanup(coll.drop)
            yield "mongo", p.MongoStore(coll)

    def test_same_setup_at_the_same_close_is_written_once(self):
        report = t.analyze(t.data(t.BELOW), portfolio_usdt=287)
        nxt = t.analyze(t.data(t.ending((99.0, 32), (99.05, 1))))               # same setup, the next 15m close
        for name, st in self.stores():
            with self.subTest(store=name):
                row = d.paper_row(report, "danis")
                self.assertEqual(p.log([row], st), 1)
                self.assertEqual(p.log([d.paper_row(report, "firsat")], st), 0)  # the scan saw it at the same close
                self.assertEqual(p.log([row, copy.deepcopy(row)], st), 0)
                self.assertEqual(p.log([d.paper_row(nxt, "danis")], st), 1)      # a new candle: a new record...
                rows = st.all()
                self.assertEqual(len(rows), 2)
                self.assertEqual(len({r["setup_id"] for r in rows}), 1)          # ...of the same setup
                self.assertNotIn("_id", rows[0])
        st = p.JsonlStore(pathlib.Path(tempfile.mkdtemp()) / "x.jsonl")
        p.log([d.paper_row(report, "danis")], st)
        self.assertEqual(p.log([d.paper_row(report, "danis")], p.JsonlStore(st.path)), 0)    # a restarted process

    def test_negative_examples_are_kept_once_per_candle(self):
        no_setup = t.analyze(t.data(t.FAILED, symbol="NOPE"))
        avoid = t.analyze(t.data(t.zigzag(t.N, 150, 153, drift=-0.006), symbol="DOWN"))
        self.assertEqual((no_setup["decision"], avoid["decision"]), ("NO_SETUP", "AVOID"))
        for name, st in self.stores():
            with self.subTest(store=name):
                rows = [d.paper_row(r, "firsat") for r in (no_setup, avoid, no_setup)]
                self.assertEqual(p.log(rows, st), 2)
                self.assertEqual(p.log(rows, st), 0)
                kept = {r["symbol"]: r for r in st.all()}
                self.assertEqual({k: v["setup_class"] for k, v in kept.items()}, {"NOPE": "NO_SETUP", "DOWN": "AVOID"})
                self.assertIsNone(kept["NOPE"]["plan_type"])
                self.assertEqual(kept["NOPE"]["outcome_due_ms"]["24h"], kept["NOPE"]["close_ms"] + p.DAY)

    def test_record_has_the_fields(self):
        row = d.paper_row(t.analyze(t.data(t.BELOW, btc_path=t.BROKEN), portfolio_usdt=287), "danis")
        for k in ("timestamp", "symbol", "setup_id", "decision", "entry_type", "price", "trend_1h", "trend_4h", "resistance",
                  "support", "trigger", "limit", "stop", "invalidation", "volume_ratio", "rsi_1h", "atr_1h", "btc_regime",
                  "warnings", "outcome", "outcome_done", "outcome_due_ms"):
            self.assertIn(k, row)
        self.assertEqual((row["decision"], row["entry_type"], row["plan_type"]), ("WAIT_FOR_BREAKOUT", "BREAKOUT", "STOP_LIMIT"))
        self.assertEqual(row["close_ms"], t.end_of(t.data(t.BELOW)))
        self.assertAlmostEqual(row["level"], row["resistance"][1])
        json.dumps(row, allow_nan=False)


RUN = candles(T0, [(100.0, 100.6, 99.9, 100.5),                 # under the level
                   (100.5, 101.3, 100.4, 101.2),               # trigger 101 touched, closes above the level (100.9)
                   (101.2, 101.8, 101.1, 101.5),
                   (101.5, 101.6, 100.5, 100.6)]               # closes back under the level
              + flat(100.6, 92))


class OutcomeTimingTest(unittest.TestCase):
    def test_each_horizon_is_filled_only_once_it_has_passed(self):
        row = record()
        out, done = p.compute_outcome(row, RUN, T0 + H1 - 1)
        self.assertEqual((out, done), ({}, []))
        out, done = p.compute_outcome(row, RUN, T0 + H1)
        self.assertEqual(done, ["1h"])
        self.assertEqual(out, {"outcome_1h": 0.6, "max_favorable_excursion_1h": 1.8, "max_adverse_excursion_1h": -0.1})
        row.update(outcome=out, outcome_done=done)
        self.assertEqual(p.compute_outcome(row, RUN, T0 + 4 * H1 - 1)[1], ["1h"])            # not four hours yet
        out, done = p.compute_outcome(row, RUN, T0 + 4 * H1)
        self.assertEqual(done, ["1h", "4h"])
        self.assertEqual(out["outcome_4h"], 0.6)
        self.assertNotIn("outcome_24h", out)
        self.assertNotIn("triggered", out)                                                   # plan results wait for 24 h
        row.update(outcome=out, outcome_done=done)
        self.assertEqual(p.compute_outcome(row, RUN, T0 + 24 * H1 - 1)[1], ["1h", "4h"])     # not a day yet
        out, done = p.compute_outcome(row, RUN, T0 + 24 * H1)
        self.assertEqual(done, ["1h", "4h", "24h"])
        self.assertEqual((out["outcome_24h"], out["max_favorable_excursion_24h"]), (0.6, 1.8))

    def test_candles_after_a_horizon_and_before_the_record_do_not_count(self):
        want = p.compute_outcome(record(), RUN, T0 + H1)[0]
        spoiled = RUN.copy()
        spoiled.loc[4:, ["o", "h", "l", "c"]] = 999.0                                        # everything after the first hour
        before = candles(T0 - 4 * M15, flat(5.0, 4))                                         # and candles from before
        self.assertEqual(p.compute_outcome(record(), pd.concat([before, spoiled], ignore_index=True), T0 + H1)[0], want)

    def test_a_horizon_without_its_last_candle_waits(self):
        short = RUN.iloc[:3]                                                                 # the 4th candle is missing
        self.assertEqual(p.compute_outcome(record(), short, T0 + H1)[1], [])
        out, done = p.compute_outcome(record(), short, T0 + H1 + p.GIVE_UP_MS)               # the pair went silent
        self.assertEqual(done, ["1h"])
        self.assertEqual(out["outcome_1h"], 1.5)


class PlanOutcomeTest(unittest.TestCase):
    def test_breakout_that_fails_is_marked(self):
        out, _ = p.compute_outcome(record(outcome_done=["1h", "4h"]), RUN, T0 + 24 * H1)
        self.assertEqual((out["triggered"], out["fill_price"], out["trigger_time"]), (True, 101.0, p._iso(T0 + M15)))
        self.assertEqual((out["broke_resistance"], out["closed_above_resistance"], out["fell_back_below_resistance"]),
                         (True, True, True))
        self.assertEqual(out["time_to_failure"], 30)                                         # closed above 00:30, under 01:00
        self.assertAlmostEqual(out["max_gain_before_failure"], round((101.8 / 100.9 - 1) * 100, 3))
        self.assertEqual((out["mfe_r"], out["mae_r"]), (0.4, -0.3))                          # risk 2: +0.8 and -0.6
        self.assertEqual((out["stopped"], out["reached_1R"], out["reached_2R"], out["reached_next_resistance"]),
                         (False, False, False, False))
        self.assertFalse(out["broke_invalidation"])

    def test_breakout_that_holds_and_runs(self):
        run = candles(T0, [(100.0, 101.4, 99.9, 101.3), (101.3, 103.2, 101.2, 103.0), (103.0, 105.4, 102.9, 105.2)]
                      + flat(105.2, 93))
        out, _ = p.compute_outcome(record(), run, T0 + 24 * H1)
        self.assertEqual((out["closed_above_resistance"], out["fell_back_below_resistance"], out["time_to_failure"]),
                         (True, False, None))
        self.assertEqual((out["reached_1R"], out["reached_2R"], out["reached_next_resistance"], out["stopped"]),
                         (True, True, True, False))
        self.assertEqual(out["mfe_r"], 2.2)

    def test_untriggered_plan(self):
        out, _ = p.compute_outcome(record(), candles(T0, flat(100.2, 96)), T0 + 24 * H1)
        self.assertEqual((out["triggered"], out["fill_price"], out["mfe_r"], out["reached_1R"]), (False, None, None, None))
        self.assertEqual((out["broke_resistance"], out["closed_above_resistance"]), (False, False))

    def test_gap_over_the_limit_fills_only_if_the_price_comes_back(self):
        gone = candles(T0, [(101.5, 102.0, 101.4, 101.9)] + flat(101.9, 95))                 # opens over the limit, stays
        self.assertFalse(p.compute_outcome(record(), gone, T0 + 24 * H1)[0]["triggered"])
        back = candles(T0, [(101.5, 102.0, 101.4, 101.9), (101.9, 102.0, 101.1, 101.6)] + flat(101.6, 94))
        out = p.compute_outcome(record(), back, T0 + 24 * H1)[0]
        self.assertEqual((out["triggered"], out["fill_price"], out["trigger_time"]), (True, 101.2, p._iso(T0 + M15)))

    def test_stop_ends_the_trade_first(self):
        run = candles(T0, [(100.5, 101.3, 100.4, 101.2), (101.2, 104.5, 98.9, 104.0)] + flat(104.0, 94))
        out = p.compute_outcome(record(), run, T0 + 24 * H1)[0]
        self.assertEqual((out["stopped"], out["reached_1R"], out["mfe_r"]), (True, False, 0.15))   # the 104.5 does not count
        self.assertLessEqual(out["mae_r"], -1.0)
        self.assertTrue(out["intrabar_ambiguous"])                               # the same candle also held the target
        self.assertEqual((out["result_r_conservative"], out["result_r_optimistic"], out["result_r_resolved"]), (-1.0, 1.0, None))
        self.assertEqual((out["intrabar_resolution"], out["intrabar_candle_ms"]), ("STOP_FIRST_CONSERVATIVE", T0 + M15))

    def test_retest_outcome_fields(self):
        row = record(setup_class="WAIT_FOR_RETEST", decision="WAIT_FOR_RETEST", entry_type="RETEST", price=101.5,
                     plan_type="RETEST_WAIT", entry=100.1, trigger=None, limit=100.25, stop=99.0, invalidation=99.2,
                     resistance_1=103.0, level=100.1, retest_zone=[100.0, 100.3], retest_confirmation_price=100.1)
        good = candles(T0, [(101.5, 101.6, 100.8, 100.9),         # not in the zone yet
                            (100.9, 101.0, 100.2, 100.05),        # in the zone, closes under the level: no confirmation
                            (100.05, 100.7, 100.1, 100.6),        # in the zone and closes above it: confirmed, fill 100.6
                            (100.6, 102.3, 100.5, 102.2),         # 1R (risk 1.6 -> 102.2)
                            (102.2, 103.9, 102.1, 103.8)]         # 2R (103.8) and the next resistance (103.0)
                       + flat(103.8, 91))
        out = p.compute_outcome(row, good, T0 + 24 * H1)[0]
        self.assertEqual((out["entered_retest_zone"], out["confirmed_retest"], out["triggered"]), (True, True, True))
        self.assertEqual((out["fill_price"], out["trigger_time"]), (100.6, p._iso(T0 + 3 * M15)))
        self.assertEqual((out["reached_1R"], out["reached_2R"], out["reached_next_resistance"], out["broke_invalidation"]),
                         (True, True, True, False))
        self.assertNotIn("broke_resistance", out)                                            # breakout fields are for breakouts
        for k in ("immediate_false_breakout", "late_breakout_failure", "fell_back_below_resistance"):
            self.assertNotIn(k, out)                                                         # no false-breakout metric here
        self.assertEqual((out["result_r_conservative"], out["intrabar_ambiguous"], out["intrabar_resolution"]),
                         (1.0, False, "NOT_AMBIGUOUS"))

        lost = candles(T0, [(101.5, 101.6, 100.2, 100.05), (100.05, 100.1, 98.9, 99.0)] + flat(99.0, 94))
        out = p.compute_outcome(row, lost, T0 + 24 * H1)[0]
        self.assertEqual((out["entered_retest_zone"], out["confirmed_retest"], out["broke_invalidation"]), (True, False, True))
        self.assertEqual((out["triggered"], out["reached_1R"], out["reached_2R"]), (False, None, None))

        never = p.compute_outcome(row, candles(T0, flat(101.5, 96)), T0 + 24 * H1)[0]
        self.assertEqual((never["entered_retest_zone"], never["confirmed_retest"]), (False, False))

    def test_ready_setup_is_filled_at_the_record_and_negatives_have_no_plan_result(self):
        ready = record(setup_class="READY_TO_WATCH", decision="BUY_SETUP", plan_type="BREAKOUT", trigger=None, price=101.0,
                       entry=101.0, level=100.9)
        after = candles(T0, list(RUN[["o", "h", "l", "c"]].itertuples(index=False, name=None))[2:] + flat(100.6, 2))
        out = p.compute_outcome(ready, after, T0 + 24 * H1)[0]
        self.assertEqual((out["triggered"], out["fill_price"], out["trigger_time"]), (True, 101.0, p._iso(T0)))
        self.assertEqual((out["closed_above_resistance"], out["fell_back_below_resistance"], out["time_to_failure"]),
                         (True, True, 30))
        nothing = record(setup_class="NO_SETUP", decision="NO_SETUP", entry_type=None, plan_type=None, stop=None, level=None,
                         invalidation=None)
        out = p.compute_outcome(nothing, RUN, T0 + 24 * H1)[0]
        self.assertEqual((out["outcome_24h"], out["triggered"], out["broke_invalidation"]), (0.6, None, None))
        self.assertNotIn("broke_resistance", out)


class TrackerTest(unittest.TestCase):
    def setUp(self):
        self.st = p.JsonlStore(pathlib.Path(tempfile.mkdtemp()) / "advisor_paper.jsonl")
        self.report = t.analyze(t.data(t.BELOW), portfolio_usdt=287)
        self.row = d.paper_row(self.report, "danis")
        self.t0 = self.row["close_ms"]
        p.log([self.row], self.st)
        self.asked = []

    def run_at(self, now_ms):
        price = self.row["price"]

        trig = self.row["trigger"]

        async def fake(pair, start, end):
            self.asked.append((pair, start, end))                                # runs up through the trigger, never back
            return candles(self.t0, [(trig - 0.1, trig * 1.03, trig - 0.2, trig * 1.02)] * 96)

        async def no_minutes(pair, start, end):
            self.fail("no candle here holds both the stop and the target")
        got = asyncio.run(p.update_outcomes(self.st, now_ms, fake, no_minutes, origins=p.ORIGINS))
        self.assertEqual(got.pop("resolved_1m"), 0)
        return got

    def test_outcomes_arrive_on_time_and_never_touch_the_record(self):
        original = {k: v for k, v in json.loads(json.dumps(self.row)).items() if k not in ("outcome", "outcome_done")}
        self.assertEqual(self.run_at(self.t0 + H1 - 60_000), {"pending": 0, "updated": 0})
        self.assertEqual(self.asked, [])                                                     # nothing due: nothing fetched
        self.assertEqual(self.run_at(self.t0 + H1), {"pending": 1, "updated": 1})
        self.assertEqual(self.st.all()[0]["outcome_done"], ["1h"])
        self.assertEqual(self.run_at(self.t0 + 2 * H1), {"pending": 0, "updated": 0})        # 4h not due yet
        self.assertEqual(self.run_at(self.t0 + 4 * H1), {"pending": 1, "updated": 1})
        self.assertEqual(self.run_at(self.t0 + 23 * H1), {"pending": 0, "updated": 0})
        self.assertEqual(self.run_at(self.t0 + 24 * H1), {"pending": 1, "updated": 1})
        self.assertEqual(self.run_at(self.t0 + 30 * H1), {"pending": 0, "updated": 0})       # finished: never again
        stored = p.JsonlStore(self.st.path).all()[0]                                         # as a new process reads it
        self.assertEqual(stored["outcome_done"], ["1h", "4h", "24h"])
        self.assertEqual(stored["outcome"]["outcome_24h"], round((self.row["trigger"] * 1.02 / self.row["price"] - 1) * 100, 3))
        self.assertTrue(stored["outcome"]["triggered"])
        self.assertEqual((stored["outcome"]["result_r_conservative"], stored["outcome"]["intrabar_resolution"]),
                         (1.0, "NOT_AMBIGUOUS"))
        self.assertEqual({k: v for k, v in stored.items() if k not in ("outcome", "outcome_done")}, original)
        self.assertEqual((stored["decision"], stored["trigger"], stored["stop"]),
                         (self.report["decision"], self.report["plan"]["trigger_price"], self.report["plan"]["initial_stop"]))
        self.assertEqual(json.dumps(t.analyze(t.data(t.BELOW), portfolio_usdt=287), sort_keys=True),
                         json.dumps(self.report, sort_keys=True))                            # the advice itself is unchanged

    def test_a_failed_download_leaves_the_record_pending(self):
        async def broken(pair, start, end):
            raise RuntimeError("no network")
        with self.assertLogs("danisman_paper", level="WARNING"):
            self.assertEqual(asyncio.run(p.update_outcomes(self.st, self.t0 + H1, broken, broken, origins=p.ORIGINS)),
                             {"pending": 1, "updated": 0, "resolved_1m": 0})
        self.assertEqual(self.st.all()[0]["outcome_done"], [])


class FalseBreakoutTest(unittest.TestCase):
    def test_back_under_the_resistance_before_1r_is_an_immediate_false_breakout(self):
        out = p.compute_outcome(record(), RUN, T0 + 24 * H1)[0]                              # entered 00:15, under 01:00
        self.assertEqual((out["immediate_false_breakout"], out["late_breakout_failure"]), (True, False))
        self.assertTrue(out["fell_back_below_resistance"])                                   # the old field is still there

    def test_failure_after_1r_is_a_late_failure(self):
        run = candles(T0, [(100.5, 101.3, 100.4, 101.2),          # entry at 101 (risk 2), closes above the level
                           (101.2, 103.4, 101.1, 103.0),          # 1R (103) seen
                           (103.0, 103.1, 100.4, 100.5)]          # ...then back under the resistance
                      + flat(100.5, 93))
        out = p.compute_outcome(record(), run, T0 + 24 * H1)[0]
        self.assertEqual((out["immediate_false_breakout"], out["late_breakout_failure"]), (False, True))
        self.assertEqual((out["reached_1R"], out["result_r_conservative"]), (True, 1.0))

    def test_failure_after_holding_is_late_and_no_failure_is_neither(self):
        held = candles(T0, [(100.5, 101.3, 100.4, 101.2)] + flat(101.4, 5) + [(101.4, 101.5, 100.3, 100.4)] + flat(100.4, 89))
        out = p.compute_outcome(record(), held, T0 + 24 * H1)[0]                             # five candles above, no 1R
        self.assertEqual((out["immediate_false_breakout"], out["late_breakout_failure"], out["reached_1R"]),
                         (False, True, False))
        runs = candles(T0, [(100.0, 101.4, 99.9, 101.3), (101.3, 103.2, 101.2, 103.0)] + flat(103.0, 94))
        out = p.compute_outcome(record(), runs, T0 + 24 * H1)[0]
        self.assertEqual((out["immediate_false_breakout"], out["late_breakout_failure"]), (False, False))
        idle = p.compute_outcome(record(), candles(T0, flat(100.2, 96)), T0 + 24 * H1)[0]    # never entered
        self.assertEqual((idle["immediate_false_breakout"], idle["late_breakout_failure"]), (None, None))


AMBIGUOUS = candles(T0, [(100.5, 101.3, 100.4, 101.2),            # entry at 101, stop 99, target 103
                         (101.2, 104.5, 98.9, 104.0)]             # this candle holds the stop AND the target
                    + flat(104.0, 94))


def one_minute(start_ms: int, rows: list[tuple]) -> pd.DataFrame:
    return pd.DataFrame({"t": [start_ms + k * 60_000 for k in range(len(rows))], "o": [r[0] for r in rows],
                         "h": [r[1] for r in rows], "l": [r[2] for r in rows], "c": [r[3] for r in rows]})


class IntrabarTest(unittest.TestCase):
    def setUp(self):
        self.row = record()
        self.outcome = p.compute_outcome(self.row, AMBIGUOUS, T0 + 24 * H1)[0]

    def test_stop_and_target_in_one_candle_is_ambiguous(self):
        o = self.outcome
        self.assertTrue(o["intrabar_ambiguous"])
        self.assertEqual(o["intrabar_resolution"], "STOP_FIRST_CONSERVATIVE")
        self.assertEqual((o["result_r_conservative"], o["result_r_optimistic"], o["result_r_resolved"]), (-1.0, 1.0, None))
        self.assertEqual((o["stopped"], o["reached_1R"]), (True, False))                     # the main numbers stay conservative
        clean = p.compute_outcome(self.row, RUN, T0 + 24 * H1)[0]
        self.assertEqual((clean["intrabar_ambiguous"], clean["intrabar_resolution"]), (False, "NOT_AMBIGUOUS"))
        self.assertEqual(clean["result_r_resolved"], clean["result_r_conservative"])

    def test_one_minute_candles_show_the_stop_first(self):
        m1 = one_minute(T0 + M15, [(101.2, 101.5, 100.8, 101.0), (101.0, 101.1, 98.9, 99.2), (99.2, 104.5, 99.1, 104.0)]
                        + [(104.0, 104.1, 103.9, 104.0)] * 12)
        o = p.resolve_intrabar(self.row, self.outcome, m1)
        self.assertEqual((o["intrabar_resolution"], o["result_r_resolved"]), ("RESOLVED_1M", -1.0))
        self.assertEqual((o["result_r_conservative"], o["result_r_optimistic"]), (-1.0, 1.0))  # both kept

    def test_one_minute_candles_show_the_target_first(self):
        m1 = one_minute(T0 + M15, [(101.2, 101.9, 101.1, 101.8), (101.8, 104.5, 101.7, 104.2), (104.2, 104.3, 98.9, 99.5)]
                        + [(99.5, 104.0, 99.4, 104.0)] + [(104.0, 104.1, 103.9, 104.0)] * 11)
        o = p.resolve_intrabar(self.row, self.outcome, m1)
        self.assertEqual((o["intrabar_resolution"], o["result_r_resolved"]), ("RESOLVED_1M", 1.0))
        self.assertEqual(o["result_r_conservative"], -1.0)                                   # the main number is unchanged

    def test_without_one_minute_data_resolved_stays_empty(self):
        for m1 in (None, one_minute(T0 + M15, []), one_minute(T0 + M15, [(101.2, 104.5, 98.9, 104.0)] * 15)):
            o = p.resolve_intrabar(self.row, self.outcome, m1)                               # missing, empty, both in a minute
            self.assertEqual((o["intrabar_resolution"], o["result_r_resolved"]), ("STOP_FIRST_CONSERVATIVE", None))
            self.assertTrue(o["intrabar_checked"])

    def test_minutes_before_the_fill_do_not_count(self):
        both = candles(T0, [(100.5, 103.5, 98.8, 103.0)] + flat(103.0, 95))                  # the entry candle holds both
        o = p.compute_outcome(self.row, both, T0 + 24 * H1)[0]
        self.assertTrue(o["intrabar_ambiguous"] and o["intrabar_fill_inside"])
        # 98.8 came BEFORE the order filled at 101; after the fill the price went straight to the target
        m1 = one_minute(T0, [(100.5, 100.6, 98.8, 100.0), (100.0, 101.2, 99.9, 101.1), (101.1, 103.5, 101.0, 103.2)]
                        + [(103.2, 103.3, 103.0, 103.0)] * 12)
        self.assertEqual(p.resolve_intrabar(self.row, o, m1)["result_r_resolved"], 1.0)

    def test_tracker_resolves_with_one_minute_data_and_leaves_the_record_alone(self):
        st = p.JsonlStore(pathlib.Path(tempfile.mkdtemp()) / "advisor_paper.jsonl")
        report = t.analyze(t.data(t.BELOW), portfolio_usdt=287)
        row = d.paper_row(report, "danis")
        p.log([row], st)
        original = {k: v for k, v in json.loads(json.dumps(row)).items() if k not in ("outcome", "outcome_done")}
        t0, trig, stop = row["close_ms"], row["trigger"], row["stop"]
        target = trig + (trig - stop)
        asked = []

        async def fifteen(pair, start, end):
            return candles(t0, [(trig - 0.2, trig + 0.1, trig - 0.3, trig + 0.05),           # entry
                                (trig, target + 0.5, stop - 0.2, target)]                    # stop and target together
                           + flat(target, 94))

        async def minutes(pair, start, end):
            asked.append((pair, start, end))
            return one_minute(start, [(trig, target + 0.5, trig - 0.1, target), (target, target, stop - 0.2, stop)]
                              + [(stop, stop + 0.1, stop - 0.1, stop)] * 13)                 # the target came first
        got = asyncio.run(p.update_outcomes(st, t0 + 24 * H1, fifteen, minutes, origins=p.ORIGINS))
        self.assertEqual(got, {"pending": 1, "updated": 1, "resolved_1m": 1})
        self.assertEqual(asked, [("TESTUSDT", t0 + M15, t0 + 2 * M15)])                      # only the ambiguous candle
        stored = p.JsonlStore(st.path).all()[0]
        oc = stored["outcome"]
        self.assertEqual((oc["result_r_conservative"], oc["result_r_optimistic"], oc["result_r_resolved"]), (-1.0, 1.0, 1.0))
        self.assertEqual(oc["intrabar_resolution"], "RESOLVED_1M")
        self.assertEqual({k: v for k, v in stored.items() if k not in ("outcome", "outcome_done")}, original)
        self.assertEqual(json.dumps(t.analyze(t.data(t.BELOW), portfolio_usdt=287), sort_keys=True),
                         json.dumps(report, sort_keys=True))                                 # the advice is what it was
        again = asyncio.run(p.update_outcomes(st, t0 + 30 * H1, fifteen, minutes, origins=p.ORIGINS))
        self.assertEqual((again, len(asked)), ({"pending": 0, "updated": 0, "resolved_1m": 0}, 1))


class BlockedOutcomeTest(unittest.TestCase):
    def test_blocked_setup_is_never_counted_as_a_fill(self):
        blocked = record(setup_class="BLOCKED_SETUP", decision="BLOCKED_SETUP", underlying_setup="WAIT_FOR_BREAKOUT",
                         blocked_reason="BTC_MARKET_RISK")
        run = candles(T0, [(100.0, 101.4, 99.9, 101.3), (101.3, 103.2, 101.2, 103.0), (103.0, 105.4, 102.9, 105.2)]
                      + flat(105.2, 93))
        out = p.compute_outcome(blocked, run, T0 + 24 * H1)[0]
        self.assertEqual((out["triggered"], out["fill_price"], out["trigger_time"]), (None, None, None))
        self.assertEqual((out["would_trigger"], out["would_hit_1R"], out["would_hit_2R"]), (True, True, True))
        self.assertEqual((out["virtual_mfe_r"], out["virtual_result_r"]), (2.2, 1.0))
        self.assertEqual(out["outcome_24h"], 5.2)
        for k in ("reached_1R", "mfe_r", "result_r_conservative", "immediate_false_breakout", "broke_resistance"):
            self.assertNotIn(k, out)                                                         # real-trade fields: absent

    def test_paper_record_of_a_blocked_report(self):
        falling = t.zigzag(len(t.BROKEN) - 1, 400, 403, drift=-0.03)
        report = t.analyze(t.data(t.BELOW, btc_path=falling), portfolio_usdt=287)
        row = d.paper_row(report, "firsat")
        self.assertEqual((row["decision"], row["setup_class"], row["underlying_setup"], row["blocked_reason"]),
                         ("BLOCKED_SETUP", "BLOCKED_SETUP", "WAIT_FOR_BREAKOUT", "BTC_MARKET_RISK"))
        self.assertEqual((row["plan_type"], row["actionable"]), ("STOP_LIMIT", False))       # the plan, for the comparison
        self.assertIsNotNone(row["trigger"])
        self.assertTrue(row["btc_regime"]["market_risk"])


class StatsTest(unittest.TestCase):
    def rows(self):
        day = p.DAY
        done = ["1h", "4h", "24h"]
        hit = {"outcome_24h": 4.0, "triggered": True, "reached_1R": True, "reached_2R": False, "mfe_r": 1.6, "mae_r": -0.2,
               "result_r_conservative": 1.0, "result_r_optimistic": 1.0, "result_r_resolved": 1.0, "intrabar_ambiguous": False,
               "immediate_false_breakout": False, "late_breakout_failure": True}
        fail = {"outcome_24h": -2.0, "triggered": True, "reached_1R": False, "reached_2R": False, "mfe_r": 0.2, "mae_r": -1.0,
                "result_r_conservative": -1.0, "result_r_optimistic": 1.0, "result_r_resolved": 1.0, "intrabar_ambiguous": True,
                "intrabar_resolution": "RESOLVED_1M", "immediate_false_breakout": True, "late_breakout_failure": False}
        idle = {"outcome_24h": 0.5, "triggered": False, "immediate_false_breakout": None, "late_breakout_failure": None}
        retest = {"outcome_24h": 3.0, "triggered": True, "reached_1R": True, "reached_2R": True, "mfe_r": 2.4, "mae_r": -0.1,
                  "result_r_conservative": -1.0, "result_r_optimistic": 1.0, "result_r_resolved": None, "intrabar_ambiguous": True,
                  "intrabar_resolution": "STOP_FIRST_CONSERVATIVE"}
        virtual = lambda r24, one, two: {"outcome_24h": r24, "triggered": None, "would_trigger": True, "would_hit_1R": one,
                                         "would_hit_2R": two, "virtual_mfe_r": 1.5 if one else 0.3, "virtual_mae_r": -0.5}
        now = T0 + 40 * day
        mk = lambda sid, cls, age_days, oc, d_=done, **kw: {"setup_id": sid, "setup_class": cls, "close_ms": now - age_days * day,
                                                            "outcome": oc, "outcome_done": d_, "data_origin": "LIVE",
                                                            "ruleset_hash": "r1", **kw}
        btc = dict(blocked_reason="BTC_MARKET_RISK", underlying_setup="WAIT_FOR_BREAKOUT")
        return now, [mk("a", "WAIT_FOR_BREAKOUT", 2, hit), mk("a", "WAIT_FOR_BREAKOUT", 1, fail),      # same setup twice
                     mk("b", "WAIT_FOR_BREAKOUT", 3, fail), mk("c", "WAIT_FOR_BREAKOUT", 20, idle),
                     mk("d", "WAIT_FOR_BREAKOUT", 0.2, {}, []),                                        # not measured yet
                     mk("e", "WAIT_FOR_RETEST", 5, retest), mk("f", "NO_SETUP", 4, {"outcome_24h": -1.0}),
                     mk("g", "NO_SETUP", 35, {"outcome_24h": 3.0}), mk("h", "AVOID", 6, {"outcome_24h": -5.0}),
                     mk("i", "PULLBACK_SETUP", 6, {"outcome_24h": 1.0}),
                     mk("j", "BLOCKED_SETUP", 2, virtual(6.0, True, True), **btc),
                     mk("k", "BLOCKED_SETUP", 3, virtual(-2.0, False, False), **btc),
                     mk("l", "BLOCKED_SETUP", 4, virtual(1.0, True, False), blocked_reason="HTF_DOWNTREND",
                        underlying_setup="WAIT_FOR_RETEST")]

    def test_counts_per_class_and_period(self):
        now, rows = self.rows()
        s = p.stats(rows, now)
        self.assertEqual((s["records"], s["setups"]), (13, 12))
        self.assertEqual(list(s["periods"]), ["son 7 gün", "son 30 gün", "tüm dönem"])
        week = s["periods"]["son 7 gün"]["classes"]
        self.assertEqual(set(week), set(p.CLASSES))
        b = week["WAIT_FOR_BREAKOUT"]
        self.assertEqual((b["count"], b["measured"]), (3, 2))                    # a (first record only), b, d; c is older
        self.assertEqual((b["trigger_rate_%"], b["hit_1R_%"], b["hit_2R_%"]), (100.0, 50.0, 0.0))
        self.assertEqual((b["mean_mfe_r"], b["mean_mae_r"], b["mean_result_r"], b["median_24h_return_%"]), (0.9, -0.6, 0.0, 1.0))
        month = s["periods"]["son 30 gün"]["classes"]["WAIT_FOR_BREAKOUT"]
        self.assertEqual((month["count"], month["measured"], month["trigger_rate_%"]), (4, 3, 66.7))
        self.assertEqual(week["WAIT_FOR_RETEST"]["hit_2R_%"], 100.0)
        self.assertNotIn("false_breakout_%", week["WAIT_FOR_RETEST"])            # only breakouts have that
        self.assertEqual((week["NO_SETUP"]["count"], week["NO_SETUP"]["trigger_rate_%"], week["NO_SETUP"]["median_24h_return_%"]),
                         (1, None, -1.0))                                        # blocked setups are not in here
        self.assertEqual(s["periods"]["tüm dönem"]["classes"]["NO_SETUP"]["count"], 2)
        self.assertEqual((week["AVOID"]["median_24h_return_%"], week["PULLBACK_SETUP"]["count"], week["READY_TO_WATCH"]["count"]),
                         (-5.0, 1, 0))

    def test_blocked_setups_are_reported_apart_and_virtually(self):
        now, rows = self.rows()
        week = p.stats(rows, now)["periods"]["son 7 gün"]
        self.assertEqual((week["classes"]["BLOCKED_SETUP"]["count"], week["classes"]["BLOCKED_SETUP"]["trigger_rate_%"]), (3, None))
        b = week["blocked"]
        self.assertEqual({k: v["count"] for k, v in b.items()},
                         {"ALL": 3, "BTC_MARKET_RISK": 2, "HTF_DOWNTREND": 1, "PORTFOLIO_CONCENTRATION": 0,
                          "INSUFFICIENT_HISTORY": 0, "OTHER": 0})
        btc = b["BTC_MARKET_RISK"]
        self.assertEqual((btc["median_24h_return_%"], btc["would_hit_1R_%"], btc["would_hit_2R_%"]), (2.0, 50.0, 50.0))
        self.assertEqual((btc["mean_virtual_mfe_r"], btc["mean_virtual_mae_r"]), (0.9, -0.5))
        self.assertEqual((b["ALL"]["median_24h_return_%"], b["ALL"]["would_hit_1R_%"]), (1.0, 66.7))
        self.assertEqual(week["intrabar"]["trades"], 3)                          # a, b, e: blocked ones are not trades

    def test_breakout_and_intrabar_sections(self):
        now, rows = self.rows()
        week = p.stats(rows, now)["periods"]["son 7 gün"]
        self.assertEqual(week["breakout"], {"entered": 2, "immediate_false_breakout_%": 50.0, "late_breakout_failure_%": 50.0})
        i = week["intrabar"]
        self.assertEqual((i["trades"], i["ambiguous"], i["ambiguous_%"], i["resolved_1m"], i["resolved_1m_%"]),
                         (3, 2, 66.7, 1, 50.0))
        self.assertEqual((i["mean_result_r_conservative"], i["mean_result_r_optimistic"], i["optimistic_minus_conservative_r"]),
                         (-0.33, 1.0, 1.33))

    def test_text(self):
        now, rows = self.rows()
        text = p.format_stats(p.stats(rows, now), {"pending": 3, "updated": 2, "resolved_1m": 1})
        for part in ("Canlı paper veri", "SON 7 GÜN", "SON 30 GÜN", "TÜM DÖNEM", "[WAIT_FOR_BREAKOUT]", "[WAIT_FOR_RETEST]", "[PULLBACK_SETUP]",
                     "[NO_SETUP]", "[AVOID]", "tetiklenme 100%", "Engelli kurulumlar [BLOCKED_SETUP]: 3 kurulum",
                     "BTC riski nedeniyle: 2", "4H düşüş nedeniyle: 1", "1R'ye giderdi 50%", "hemen sahte kırılım 50%",
                     "geç bozulma 50%", "belirsiz 66.7%", "1m ile çözülen 50%", "fark 1.33R", "hiçbir eşik",
                     "1 belirsiz mum 1m veriyle çözüldü"):
            self.assertIn(part, text)
        self.assertNotIn("Portföy yoğunluğu nedeniyle", text)                    # no such record: no line
        self.assertIn("0 kurulum", p.format_stats(p.stats([], now)))


def no_forced_origin():
    """Inside this block the origin comes from the report itself, as in production (the suites force TEST)."""
    env = unittest.mock.patch.dict(os.environ)
    env.start()
    os.environ.pop("ADVISOR_DATA_ORIGIN", None)
    return env


class OriginTest(unittest.TestCase):
    def test_a_normal_run_is_live_and_a_replayed_moment_is_replay(self):
        dt = t.data(t.BELOW)
        moment = t.end_of(dt)
        env = no_forced_origin()
        self.addCleanup(env.stop)
        with unittest.mock.patch("danisman.time.time", return_value=(moment + 60_000) / 1000):
            live = d.analyze(dt)                                                 # what /danis and /firsat do: no asof
        replay = d.analyze(dt, asof_ms=moment)                                   # the same moment, asked for afterwards
        self.assertEqual((live["live"], replay["live"]), (True, False))
        a, b = d.paper_row(live, "danis"), d.paper_row(replay, "replay")
        self.assertEqual((a["data_origin"], b["data_origin"]), ("LIVE", "REPLAY"))
        self.assertEqual(a["market_timestamp_ms"], b["market_timestamp_ms"])     # the same candle...
        self.assertEqual((a["market_timestamp"], a["market_timestamp_ms"]), (live["as_of"], moment))
        self.assertNotEqual(a["generated_at"][:16], a["market_timestamp"][:16])  # ...written now, not then
        self.assertNotEqual(p.key(a), p.key(b))                                  # so a replay never collides with it
        self.assertEqual(d.paper_row(replay, "x", origin="LIVE")["data_origin"], "LIVE")   # an explicit origin wins

    def test_a_record_written_by_a_test_is_test(self):
        report = t.analyze(t.data(t.BELOW))
        self.assertEqual(os.environ["ADVISOR_DATA_ORIGIN"], "TEST")              # set by this file and test_danisman
        self.assertEqual(d.paper_row(report, "danis")["data_origin"], "TEST")
        with unittest.mock.patch("danisman.time.time", return_value=t.end_of(t.data(t.BELOW)) / 1000 + 60):
            self.assertEqual(d.paper_row(d.analyze(t.data(t.BELOW)), "danis")["data_origin"], "TEST")   # even a live-mode run
        with unittest.mock.patch.dict(os.environ, {"ADVISOR_DATA_ORIGIN": "nonsense"}):
            self.assertEqual(d.paper_row(report, "danis")["data_origin"], "REPLAY")

    def test_code_version_is_on_the_record(self):
        row = d.paper_row(t.analyze(t.data(t.BELOW)), "danis")
        self.assertEqual((row["advisor_version"], row["ruleset_hash"]), ("1.0.0", d.ruleset_hash()))
        self.assertRegex(row["git_commit"], r"^[0-9a-f]{40}$")
        self.assertIsInstance(row["working_tree_dirty"], bool)
        with unittest.mock.patch.object(d, "_code", None), unittest.mock.patch.dict(os.environ, {"ADVISOR_GIT_COMMIT": "abc123"}):
            self.assertEqual(d.code_version(), {"git_commit": "abc123", "working_tree_dirty": None})

    def test_deploy_file_gives_the_commit_where_there_is_no_git(self):
        folder = pathlib.Path(tempfile.mkdtemp())
        (folder / "danisman.py").write_text("", encoding="utf-8")
        no_git = unittest.mock.patch.object(d.subprocess, "run", side_effect=FileNotFoundError("git"))   # as in the image
        for text, want in (("a1b2c3d4\n", ("a1b2c3d4", False)), ("a1b2c3d4\ndirty\n", ("a1b2c3d4", True))):
            (folder / ".git_commit").write_text(text, encoding="utf-8")
            with unittest.mock.patch.object(d, "_code", None), no_git, \
                    unittest.mock.patch.object(d, "__file__", str(folder / "danisman.py")):
                got = d.code_version()
            self.assertEqual((got["git_commit"], got["working_tree_dirty"]), want)


class RulesetTest(unittest.TestCase):
    def test_same_config_same_hash(self):
        self.assertEqual(d.ruleset_hash(), d.ruleset_hash())
        self.assertRegex(d.ruleset_hash(), r"^[0-9a-f]{12}$")
        rules = d.ruleset()
        self.assertEqual(d.ruleset_hash(dict(reversed(list(rules.items())))), d.ruleset_hash(rules))   # key order is fixed
        json.dumps(rules, sort_keys=True)

    def test_a_technical_threshold_changes_the_hash(self):
        base = d.ruleset_hash()
        for name, value in (("REACTION_ATR", 1.5), ("TREND_BARS", 80), ("BREAKOUT_WINDOW", 12), ("RETEST_ATR", 0.5),
                            ("LOW_RR", 2.0), ("TRAIL_ATR", 2.0), ("HIGH_CORR", 0.9), ("MAX_CORRELATED", 2),
                            ("RULESET_REVISION", 99), ("PARAMS", d.sl.Params(pct_buffer=0.002, atr_buffer=0.0,
                                                                              limit_cap=0.004, max_risk_pct=0.12))):
            with self.subTest(setting=name), unittest.mock.patch.object(d, name, value):
                self.assertNotEqual(d.ruleset_hash(), base)
        with unittest.mock.patch.object(d.sl, "MIN_STRUCT_ATR", 2.0):
            self.assertNotEqual(d.ruleset_hash(), base)                          # the stop engine's limits too
        self.assertEqual(d.ruleset_hash(), base)

    def test_texts_and_cache_times_do_not(self):
        base = d.ruleset_hash()
        changes = {"RESEARCH_NOTE": "başka bir not 🙂", "DECISION_TR": {k: v + "!" for k, v in d.DECISION_TR.items()},
                   "GROUP_TR": {k: "x" for k in d.GROUP_TR}, "BLOCK_TR": {k: "y" for k in d.BLOCK_TR},
                   "TIERS": {k: "z" for k in d.TIERS}, "REASON_TR": {}, "META_SECONDS": 1, "SCAN_PARALLEL": 99,
                   "SCAN_LIMIT": 5, "ADVISOR_VERSION": "9.9.9"}
        for name, value in changes.items():
            with self.subTest(setting=name), unittest.mock.patch.object(d, name, value):
                self.assertEqual(d.ruleset_hash(), base)


class ProvenanceStoreTest(unittest.TestCase):
    def stores(self):
        yield "jsonl", p.JsonlStore(pathlib.Path(tempfile.mkdtemp()) / "advisor_paper.jsonl")
        client, coll = mongo_collection()
        if coll is not None:
            coll.drop()
            self.addCleanup(client.close)
            self.addCleanup(coll.drop)
            yield "mongo", p.MongoStore(coll)

    def test_another_ruleset_or_origin_is_not_a_duplicate(self):
        report = t.analyze(t.data(t.BELOW), portfolio_usdt=287)
        for name, st in self.stores():
            with self.subTest(store=name):
                self.assertEqual(p.log([d.paper_row(report, "danis")], st), 1)
                self.assertEqual(p.log([d.paper_row(report, "danis")], st), 0)   # same setup, same ruleset: once
                with unittest.mock.patch.object(d, "REACTION_ATR", 1.5):         # the same market setup, newer logic
                    newer = d.paper_row(report, "danis")
                self.assertEqual(newer["setup_id"], d.paper_row(report, "danis")["setup_id"])
                self.assertNotEqual(newer["ruleset_hash"], d.ruleset_hash())
                self.assertEqual(p.log([newer], st), 1)
                self.assertEqual(p.log([newer], st), 0)
                self.assertEqual(p.log([d.paper_row(report, "replay", origin="REPLAY")], st), 1)   # replayed later
                rows = st.all()
                self.assertEqual(len(rows), 3)
                self.assertEqual(len({r["setup_id"] for r in rows}), 1)
                self.assertEqual(sorted(r["data_origin"] for r in rows), ["REPLAY", "TEST", "TEST"])

    def test_outcome_never_changes_the_origin_and_tests_are_left_alone(self):
        report = t.analyze(t.data(t.BELOW), portfolio_usdt=287)
        st = p.JsonlStore(pathlib.Path(tempfile.mkdtemp()) / "advisor_paper.jsonl")
        rows = [d.paper_row(report, "danis", origin=o) for o in p.ORIGINS]
        p.log(rows, st)
        t0, trig = rows[0]["close_ms"], rows[0]["trigger"]

        async def fake(pair, start, end):
            return candles(t0, [(trig - 0.1, trig * 1.03, trig - 0.2, trig * 1.02)] * 96)
        got = asyncio.run(p.update_outcomes(st, t0 + 24 * H1, fake, fake))        # as the bot's scheduler calls it
        self.assertEqual((got["pending"], got["updated"]), (2, 2))               # LIVE and REPLAY; the TEST record waits
        stored = {r["data_origin"]: r for r in p.JsonlStore(st.path).all()}
        self.assertEqual(set(stored), {"LIVE", "REPLAY", "TEST"})                # no origin was rewritten
        self.assertEqual(stored["LIVE"]["outcome_done"], ["1h", "4h", "24h"])
        self.assertEqual(stored["REPLAY"]["outcome_done"], ["1h", "4h", "24h"])
        self.assertEqual((stored["TEST"]["outcome"], stored["TEST"]["outcome_done"]), ({}, []))
        for o in p.ORIGINS:
            want = next(r for r in rows if r["data_origin"] == o)
            for k in ("data_origin", "generated_at", "market_timestamp", "ruleset_hash", "advisor_version", "git_commit",
                      "setup_id", "decision"):
                self.assertEqual(stored[o][k], want[k])

    def test_old_records_are_kept_and_marked_replay(self):
        path = pathlib.Path(tempfile.mkdtemp()) / "advisor_paper.jsonl"
        old = {"symbol": "WLD", "pair": "WLDUSDT", "setup_id": "f295186cba5e2903", "setup_class": "WAIT_FOR_RETEST",
               "close_ms": T0, "timestamp": "2026-09-30 18:00 UTC", "logged_at": "2026-10-01 20:02:52 UTC", "source": "replay",
               "price": 0.5335, "plan_type": None, "outcome": {"outcome_24h": -6.9}, "outcome_done": ["1h", "4h", "24h"]}
        path.write_text(json.dumps(old) + "\n", encoding="utf-8")
        st = p.JsonlStore(path)
        row = st.all()[0]
        self.assertEqual((row["data_origin"], row["ruleset_hash"], row["advisor_version"]), ("REPLAY", "legacy", "0.0.0"))
        self.assertEqual((row["market_timestamp"], row["generated_at"]), (old["timestamp"], old["logged_at"]))
        self.assertEqual(row["outcome"], old["outcome"])                         # nothing lost
        self.assertEqual(d.paper_stats(st.all())["records"], 0)                  # ...and not in the live statistics
        self.assertEqual(p.stats(st.all(), origin="REPLAY")["records"], 1)
        client, coll = mongo_collection()
        if coll is not None:
            self.addCleanup(client.close)
            self.addCleanup(coll.drop)
            coll.drop()
            coll.create_index([("symbol", 1), ("setup_id", 1), ("close_ms", 1)], unique=True, name="setup_at_close")
            coll.insert_one(dict(old))
            moved = p.MongoStore(coll).all()[0]
            self.assertEqual((moved["data_origin"], moved["ruleset_hash"], moved["market_timestamp_ms"]), ("REPLAY", "legacy", T0))
            self.assertNotIn("setup_at_close", coll.index_information())
            self.assertIn("setup_at_close_by_ruleset_and_origin", coll.index_information())


class StatsOriginTest(unittest.TestCase):
    def rows(self):
        now = T0 + 3 * p.DAY
        cur = d.ruleset_hash()
        mk = lambda sid, origin, rules=cur, version="1.0.0": {
            "setup_id": sid, "setup_class": "WAIT_FOR_BREAKOUT", "close_ms": now - p.DAY, "data_origin": origin,
            "ruleset_hash": rules, "advisor_version": version, "git_commit": "a" * 40, "working_tree_dirty": False,
            "outcome": {"outcome_24h": 1.0, "triggered": True, "reached_1R": True, "reached_2R": False},
            "outcome_done": ["1h", "4h", "24h"]}
        return now, [mk("l1", "LIVE"), mk("l2", "LIVE"), mk("r1", "REPLAY"), mk("r2", "REPLAY"), mk("r3", "REPLAY"),
                     mk("t1", "TEST"), mk("old", "LIVE", "0ldru1e5e700", "0.9.0")]

    def count(self, s):
        return s["periods"]["tüm dönem"]["classes"]["WAIT_FOR_BREAKOUT"]["count"]

    def test_default_is_live_only_and_the_current_ruleset(self):
        now, rows = self.rows()
        s = d.paper_stats(rows, now_ms=now)
        self.assertEqual((s["origin"], s["ruleset_hash"], s["records"], self.count(s)), ("LIVE", d.ruleset_hash(), 2, 2))
        self.assertEqual((s["excluded_other_origins"], s["excluded_other_versions"]), (4, 1))   # 3 replay + 1 test; 1 old live
        text = p.format_stats(s)
        self.assertTrue(text.startswith("📒 Canlı paper veri — 2 kayıt"))
        self.assertIn("Başka danışman sürümlerinden 1 kayıt hariç tutuldu.", text)
        self.assertIn("(güncel)", text)
        self.assertNotIn("Replay araştırma verisi", text)

    def test_replay_and_all_have_to_be_asked_for_and_say_so(self):
        now, rows = self.rows()
        replay = d.paper_stats(rows, "REPLAY", now_ms=now)
        self.assertEqual((replay["records"], self.count(replay)), (3, 3))
        self.assertTrue(p.format_stats(replay).startswith("📒 Replay araştırma verisi — 3 kayıt"))
        everything = d.paper_stats(rows, "ALL", now_ms=now)
        self.assertEqual((everything["records"], everything["excluded_other_origins"]), (6, 0))   # current ruleset, every origin
        self.assertIn("canlı + replay + test birlikte", p.format_stats(everything))
        self.assertEqual(d.paper_stats(rows, "ALL", all_rulesets=True, now_ms=now)["records"], 7)
        self.assertEqual(d.paper_stats(rows, "TEST", now_ms=now)["records"], 1)
        self.assertEqual(d.paper_stats(rows, all_rulesets=True, now_ms=now)["records"], 3)        # live, every ruleset
        self.assertIn("bütün sürümler birlikte", p.format_stats(d.paper_stats(rows, all_rulesets=True, now_ms=now)))

    def test_versions(self):
        now, rows = self.rows()
        vs = p.versions(rows)
        self.assertEqual([(v["advisor_version"], v["ruleset_hash"], v["LIVE"], v["REPLAY"], v["TEST"]) for v in vs],
                         [("1.0.0", d.ruleset_hash(), 2, 3, 1), ("0.9.0", "0ldru1e5e700", 1, 0, 0)])
        self.assertEqual((vs[0]["first"], vs[0]["last"]), (p._iso(now - p.DAY),) * 2)
        text = p.format_versions(vs, d.ruleset_hash())
        self.assertIn(f"1.0.0 · kural seti {d.ruleset_hash()} (güncel): canlı 2 kayıt", text)
        self.assertIn("0.9.0 · kural seti 0ldru1e5e700: canlı 1 kayıt", text)
        self.assertIn("Henüz kayıt yok.", p.format_versions([]))


if __name__ == "__main__":
    unittest.main()
