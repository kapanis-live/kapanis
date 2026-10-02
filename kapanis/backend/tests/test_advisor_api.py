"""Kripto Danışman endpoints: owner only, validated input, rate limited, exchange errors mapped; no database needed.
Run: .venv\\Scripts\\python -m unittest tests.test_advisor_api -v
"""
import asyncio
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

# whatever these tests make the advisor record is a TEST record in a throw-away file, never the live paper log
os.environ["ADVISOR_DATA_ORIGIN"] = "TEST"
os.environ["ADVISOR_PAPER_FILE"] = str(Path(tempfile.mkdtemp()) / "advisor_paper.jsonl")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from fastapi import FastAPI, HTTPException  # noqa: E402

import advisor_api  # noqa: E402
import limits  # noqa: E402

USER = {"id": "u1", "owner": True}
# The engine takes "now" from time.time, and the 1h / 4h / 1d candles are cut on UTC boundaries: the same 15m candles give
# another 4h picture at another time of day. In the last hour of every 4h block the last closed 4h candle of this path
# closes under its SMA20, the advisor rightly blocks (HTF_DOWNTREND), and the tests that expect a sized plan fail.
# So the candles end at one fixed moment and the tests run at that moment, never at the wall clock.
NOW = datetime(2026, 1, 15, 10, 7, 30, tzinfo=timezone.utc).timestamp()


async def current_user():
    return USER


async def require_owner():
    if not USER["owner"]:
        raise HTTPException(status_code=403, detail="Bu bölüm yalnız sistem sahibine açık.")
    return USER


def candles() -> dict:
    """A range between 95 and 100 that ends one point under the resistance, with the last 15m candle still open."""
    d = advisor_api.engine()
    n, half = 6400, 40
    k = np.arange(n + 34)
    phase = k % (2 * half)
    path = 95 + 5 * np.where(phase <= half, phase, 2 * half - phase) / half
    path[n:] = np.linspace(path[n], 99.0, 34)
    o, c = path[:-1], path[1:]
    step = d.TFS["15m"]
    start = int(NOW * 1000) // step * step - (len(c) - 1) * step
    m = pd.DataFrame({"t": start + np.arange(len(c)) * step, "o": o, "h": np.maximum(o, c) + 0.03,
                      "l": np.minimum(o, c) - 0.03, "c": c, "v": 1000.0})
    frames = {"15m": m}
    for tf, s in list(d.TFS.items())[1:]:
        g = m.groupby(m.t // s * s)
        frames[tf] = pd.DataFrame({"t": g.t.first().index.values, "o": g.o.first().values, "h": g.h.max().values,
                                   "l": g.l.min().values, "c": g.c.last().values, "v": g.v.sum().values})
    return frames


class AdvisorApiTest(unittest.TestCase):
    def setUp(self):
        clock = mock.patch("time.time", return_value=NOW)
        clock.start()
        self.addCleanup(clock.stop)
        self.d = advisor_api.engine()
        self.calls = []
        frames = candles()

        async def fetch(symbol, holdings=None, client=None):
            self.calls.append((symbol, tuple(holdings or [])))
            if symbol == "NOPE":
                raise self.d.NoPair(symbol)
            return {"symbol": symbol, "pair": symbol + "USDT", "quote": "USDT", "frames": frames, "btc": frames, "others": {}}

        self.scans = []
        real_scan = self.d.scan

        async def scan(portfolio_usdt=None, holdings=None, limit=None, paper=None):
            self.scans.append((portfolio_usdt, tuple(holdings or []), limit))
            if portfolio_usdt == 13:
                raise RuntimeError("borsa yok")

            async def fetcher(coin):
                return await fetch(coin)
            return await real_scan(portfolio_usdt, holdings, symbols=["AAA", "BBB", "CCC", "NOPE"], fetcher=fetcher, paper=paper)

        self._fetch, self.d.fetch = self.d.fetch, fetch
        self._scan, self.d.scan = real_scan, scan
        advisor_api._scans.clear()
        advisor_api._cache.clear()
        limits._hits.clear()
        USER["owner"] = True
        self.app = FastAPI()
        self.app.include_router(advisor_api.build_router(current_user, require_owner))

    def tearDown(self):
        self.d.fetch, self.d.scan = self._fetch, self._scan

    def test_opportunities_scan(self):
        r = self.call("GET", "/api/advisor/opportunities?portfolio_usdt=287&holdings=sol,eth")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        s = body["scan"]
        self.assertEqual(self.scans, [(287.0, ("ETH", "SOL"), self.d.SCAN_LIMIT)])
        self.assertNotIn("OPPORTUNITIES", [c[0] for c in self.calls])            # not mistaken for a coin
        self.assertEqual(set(s["groups"]), set(self.d.GROUPS))
        self.assertLessEqual(len(s["results"]), self.d.SCAN_TOP)
        self.assertTrue(all(x["reason"] for x in s["not_now"]))
        self.assertIn("NOPE", [x["symbol"] for x in s["not_now"]])
        self.assertEqual(s["portfolio"]["holdings"], ["ETH", "SOL"])
        self.assertIn("Kripto Danışman taraması", body["text"])
        self.assertNotIn("score", r.text)
        self.call("GET", "/api/advisor/opportunities?portfolio_usdt=287&holdings=sol,eth")
        self.assertEqual(len(self.scans), 1)                                     # the second call used the kept result

    def test_opportunities_without_a_portfolio_size_gives_no_position_size(self):
        s = self.call("GET", "/api/advisor/opportunities").json()["scan"]
        self.assertIsNone(s["portfolio_usdt"])
        self.assertTrue(all(row["position_size"] is None for row in s["results"]))
        self.assertTrue(any(row["position_size_note"] == "Portföy büyüklüğü bilinmiyor." for row in s["results"]))

    def test_opportunities_guards(self):
        self.assertEqual(self.call("GET", "/api/advisor/opportunities?limit=2").status_code, 400)
        self.assertEqual(self.call("GET", "/api/advisor/opportunities?portfolio_usdt=0").status_code, 400)
        self.assertEqual(self.call("GET", "/api/advisor/opportunities?portfolio_usdt=13").status_code, 502)
        USER["owner"] = False
        self.assertEqual(self.call("GET", "/api/advisor/opportunities").status_code, 403)
        USER["owner"] = True
        codes = [self.call("GET", f"/api/advisor/opportunities?portfolio_usdt={100 + k}").status_code for k in range(4)]
        self.assertEqual(codes[-1], 429)                                         # each new scan counts; the 502 above too

    def call(self, method, url, **kw):
        async def go():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://t") as c:
                return await c.request(method, url, **kw)
        return asyncio.run(go())

    def paper(self):
        path = Path(os.environ["ADVISOR_PAPER_FILE"])
        return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []

    def test_reports_are_recorded_once_and_a_test_never_writes_a_live_record(self):
        before = len(self.paper())
        self.call("GET", "/api/advisor/LOGME?portfolio_usdt=287")
        self.call("GET", "/api/advisor/LOGME")                                   # the same candle again: no second record
        rows = [r for r in self.paper() if r["symbol"] == "LOGME"]
        self.assertEqual((len(rows), len(self.paper()) - before), (1, 1))
        self.assertEqual((rows[0]["data_origin"], rows[0]["source"]), ("TEST", "api"))
        self.assertEqual((rows[0]["advisor_version"], rows[0]["ruleset_hash"]), ("1.0.0", self.d.ruleset_hash()))
        self.assertNotEqual(rows[0]["generated_at"][:10], "")
        self.call("GET", "/api/advisor/opportunities")
        scanned = {r["symbol"]: r for r in self.paper() if r["source"] == "api-tara"}
        self.assertTrue({"AAA", "BBB", "CCC"} <= set(scanned))               # other tests in this file scan too
        self.assertEqual({r["data_origin"] for r in self.paper()}, {"TEST"})
        os.environ.pop("ADVISOR_DATA_ORIGIN")                                    # what production does: a real call is LIVE
        try:
            report = self.call("GET", "/api/advisor/LOGME").json()["report"]
            self.assertTrue(report["live"])
            self.assertEqual(self.d.data_origin(report), "LIVE")
        finally:
            os.environ["ADVISOR_DATA_ORIGIN"] = "TEST"
        self.assertIn("LIVE", {r["data_origin"] for r in self.paper() if r["symbol"] == "LOGME"})

    def test_get_returns_report_and_text(self):
        r = self.call("GET", "/api/advisor/hype?portfolio_usdt=287")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        rep = body["report"]
        self.assertEqual((rep["symbol"], rep["pair"]), ("HYPE", "HYPEUSDT"))
        self.assertIn(rep["decision"], self.d.DECISION_TR)
        self.assertIn("evidence", rep)
        self.assertNotIn("confidence", r.text)
        self.assertEqual(rep["position_size"]["portfolio_usdt"], 287)
        self.assertIn("HYPE/USDT — Kripto Danışman", body["text"])
        self.assertIn("Emir gönderilmez", body["text"])

    def test_post_with_a_position_answers_what_to_do_with_it(self):
        r = self.call("POST", "/api/advisor/analyze", json={"symbol": "HYPE", "portfolio_usdt": 287, "position_usdt": 35,
                                                           "average_price": 101.05, "holdings": ["btc", "ETH"]})
        self.assertEqual(r.status_code, 200)
        p = r.json()["report"]["position"]
        self.assertIn(p["action"], ("HOLD", "PROTECT_PROFIT", "REDUCE", "EXIT_IF_INVALIDATED"))
        self.assertLess(p["unrealized_pnl_pct"], 0)
        self.assertEqual(self.calls[-1], ("HYPE", ("BTC", "ETH")))

    def test_only_the_owner_for_now(self):
        USER["owner"] = False
        self.assertEqual(self.call("GET", "/api/advisor/BTC").status_code, 403)
        self.assertEqual(self.call("POST", "/api/advisor/analyze", json={"symbol": "BTC"}).status_code, 403)
        self.assertEqual(self.calls, [])

    def test_bad_input_is_refused_before_the_exchange_is_called(self):
        self.assertEqual(self.call("GET", "/api/advisor/BT$C").status_code, 400)
        self.assertEqual(self.call("GET", "/api/advisor/BTC?portfolio_usdt=-5").status_code, 400)
        r = self.call("POST", "/api/advisor/analyze", json={"symbol": "BTC", "position_usdt": 35})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.calls, [])

    def test_unknown_coin_is_404_and_candles_are_shared_for_a_moment(self):
        self.assertEqual(self.call("GET", "/api/advisor/NOPE").status_code, 404)
        self.call("GET", "/api/advisor/SOL")
        self.call("GET", "/api/advisor/SOL?portfolio_usdt=100")
        self.assertEqual([c[0] for c in self.calls], ["NOPE", "SOL"])           # the second SOL call used the cache

    def test_rate_limit_per_user(self):
        codes = [self.call("GET", "/api/advisor/SOL").status_code for _ in range(advisor_api.ADVISOR_PER_MINUTE + 1)]
        self.assertEqual(codes[:-1], [200] * advisor_api.ADVISOR_PER_MINUTE)
        self.assertEqual(codes[-1], 429)


if __name__ == "__main__":
    unittest.main()
