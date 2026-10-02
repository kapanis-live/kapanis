"""Kripto Danışman V2 endpoints: admin only (decided on the server), nothing secret in a response, the run is stored,
macro and AI failures degrade instead of breaking. No network, no database.
Run: .venv\\Scripts\\python -m unittest tests.test_advisor_v2_api -v
"""
import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ["ADVISOR_DATA_ORIGIN"] = "TEST"
os.environ.setdefault("ADVISOR_PAPER_FILE", str(Path(tempfile.mkdtemp()) / "advisor_paper.jsonl"))
os.environ["DEEPSEEK_API_KEY"] = "TEST_API_KEY_VALUE_DEEPSEEK"
os.environ["NVIDIA_API_KEY"] = "TEST_API_KEY_VALUE_NVIDIA"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import httpx  # noqa: E402
from fastapi import FastAPI, HTTPException, Request  # noqa: E402

import advisor_v2_api as api  # noqa: E402
import limits  # noqa: E402
from test_advisor_api import NOW, candles  # noqa: E402

ADMIN = "admin@example.com"
OWNER = {"id": "u1", "email": ADMIN, "role": "owner", "clerk_id": "c1", "email_verified": True}
USERS = {"owner": OWNER,
         "user": {"id": "u2", "email": "someone@example.com", "role": "user", "clerk_id": "c2", "email_verified": True},
         "other-owner": {"id": "u3", "email": "second@example.com", "role": "owner", "clerk_id": "c3", "email_verified": True},
         "unverified": {"id": "u4", "email": ADMIN, "role": "owner", "clerk_id": "c4", "email_verified": False},
         "legacy-admin": {"id": "u5", "email": ADMIN, "role": "admin"}}
SECRETS = (os.environ["DEEPSEEK_API_KEY"], os.environ["NVIDIA_API_KEY"])
FILTERS = {"tick_size": 0.01, "step_size": 0.001, "min_qty": 0.001, "min_notional": 5.0}


async def current_user(request: Request) -> dict:
    """Stands in for the verified session: the token names an account, the document comes from the "database"."""
    who = request.headers.get("Authorization", "").removeprefix("Bearer ")
    if who not in USERS:
        raise HTTPException(status_code=401, detail="Oturum bulunamadı.")
    return dict(USERS[who])


class Cursor:
    def __init__(self, rows):
        self.rows = rows

    def sort(self, key, direction):
        self.rows = sorted(self.rows, key=lambda r: r.get(key) or "", reverse=direction < 0)
        return self

    async def to_list(self, n):
        return [dict(r) for r in self.rows[:n]]


class Collection:
    def __init__(self):
        self.rows = []

    def _match(self, q):
        return [r for r in self.rows if all(r.get(k) == v for k, v in q.items())]

    async def find_one(self, q, projection=None):
        hit = self._match(q)
        return dict(hit[0]) if hit else None

    async def insert_one(self, doc):
        self.rows.append(dict(doc))

    async def update_one(self, q, update, upsert=False):
        hit = self._match(q)
        if hit:
            hit[0].update(update["$set"])
        elif upsert:
            self.rows.append({**q, **update["$set"]})

    def find(self, q, projection=None):
        return Cursor(self._match(q))


class Db:
    def __init__(self):
        self.extras, self.advisor_consensus_runs, self.advisor_positions = Collection(), Collection(), Collection()
        self.advisor_plans = Collection()


def verdict(role, value):
    base = {"role": role, "verdict": value, "confidence": 0.8, "reason": "test", "setup": "BREAKOUT"}
    return json.dumps({**base, "evidence": [], "counter_evidence": [], "levels_to_watch": [], "risk_flags": [], "portfolio_flags": [],
                       "execution_flags": [], "macro_risks": [], "market_risks": [], "data_quality_flags": []})


class AdvisorV2ApiTest(unittest.TestCase):
    def setUp(self):
        clock = mock.patch("time.time", return_value=NOW)      # the candles end at NOW; the snapshot's "now" is the same moment
        clock.start()
        self.addCleanup(clock.stop)
        self.svc = api.engine()
        self.agents = sys.modules["danisman_v2.agents"]
        self.macro = sys.modules["danisman_v2.macro"]
        frames = candles()
        self.fetched = []

        async def fetch(symbol, holdings=None, client=None, btc=None, quotes=None):
            self.fetched.append(symbol)
            if symbol == "NOPE":
                raise self.svc.d.NoPair(symbol)
            return {"symbol": symbol, "pair": symbol + "USDT", "quote": "USDT", "frames": frames, "btc": frames, "others": {}}

        async def filters(client, pairs):
            return {p: dict(FILTERS) for p in pairs}

        async def universe(client, limit):
            return [("AAA", "USDT"), ("BBB", "USDT")]

        async def klines(client, pair, tf, limit=500):
            return frames[tf]

        async def dead(section):
            raise RuntimeError("openbb yok")
        d = self.svc.d
        self._saved = (d.fetch, d.universe, d._klines, self.svc.exchange_filters, api.ai_clients, api._openbb)
        d.fetch, d.universe, d._klines, self.svc.exchange_filters = fetch, universe, klines, filters
        api._openbb = self.macro.OpenBBService(runner=dead)
        self.ai = {"TECHNICAL": "BUY", "RISK": "APPROVE", "REGIME": "ALLOW"}
        api.ai_clients = self.clients
        os.environ["ADMIN_EMAILS"] = ADMIN
        limits._hits.clear()
        self.db = Db()
        self.app = FastAPI()
        self.app.include_router(api.build_router(lambda: self.db, current_user))

    def tearDown(self):
        d = self.svc.d
        d.fetch, d.universe, d._klines, self.svc.exchange_filters, api.ai_clients, api._openbb = self._saved

    def clients(self):
        out = {}
        for role, value in self.ai.items():
            async def post(url, headers, body, timeout, role=role, value=value):
                if value is None:
                    raise RuntimeError("model down")
                return {"choices": [{"message": {"content": verdict(role, value)}}]}
            out[role] = self.agents.AdvisorAIClient("deepseek", "model-x", SECRETS[0], "http://ai.test", post=post)
        return out

    def call(self, method, path, who="owner", **kw):
        async def go():
            headers = {**({"Authorization": f"Bearer {who}"} if who else {}), **kw.pop("headers", {})}
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://t") as c:
                return await c.request(method, "/api/admin/advisor" + path, headers=headers, **kw)
        return asyncio.run(go())

    ROUTES = (("GET", "/health", None), ("POST", "/analyze", {"symbol": "BTC"}), ("POST", "/buy-plan", {"symbol": "BTC"}),
              ("POST", "/sell-plan", {"symbol": "BTC", "entry_price": 98.0}), ("POST", "/scan", {}), ("GET", "/macro", None),
              ("GET", "/paper-stats", None), ("GET", "/consensus-history", None), ("GET", "/portfolio", None))

    def test_every_endpoint_is_admin_only(self):
        for method, path, body in self.ROUTES:
            kw = {"json": body} if body is not None else {}
            self.assertEqual(self.call(method, path, who=None, **kw).status_code, 401, path)             # no session
            self.assertEqual(self.call(method, path, who="user", **kw).status_code, 403, path)           # a signed-in user
            self.assertEqual(self.call(method, path, who="other-owner", **kw).status_code, 403, path)    # owner, not on the list
            self.assertEqual(self.call(method, path, who="unverified", **kw).status_code, 403, path)     # e-mail not verified
        self.assertEqual(self.fetched, [])                                         # nobody reached the exchange
        self.assertEqual(self.db.advisor_consensus_runs.rows, [])
        for method, path, body in self.ROUTES:
            limits._hits.clear()
            self.assertEqual(self.call(method, path, **({"json": body} if body is not None else {})).status_code, 200, path)
        self.assertEqual(self.call("GET", "/health", who="legacy-admin").status_code, 200)   # this PC's single admin login

    def test_what_the_browser_claims_about_itself_is_ignored(self):
        spoof = {"symbol": "BTC", "email": ADMIN, "role": "owner", "isAdmin": True, "admin": True, "user": {"role": "owner", "email": ADMIN}}
        headers = {"X-Admin-Email": ADMIN, "X-User-Role": "owner", "X-Is-Admin": "true", "X-Forwarded-Email": ADMIN}
        r = self.call("POST", "/analyze", who="user", json=spoof, headers=headers)
        self.assertEqual(r.status_code, 403)
        r = self.call("GET", f"/health?email={ADMIN}&role=owner&isAdmin=true", who="user", headers=headers)
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.fetched, [])

    def test_without_an_admin_list_the_owner_alone_may_call(self):
        os.environ["ADMIN_EMAILS"] = ""
        self.assertEqual(self.call("GET", "/health", who="other-owner").status_code, 200)
        self.assertEqual(self.call("GET", "/health", who="user").status_code, 403)
        self.assertFalse(self.call("GET", "/health").json()["admin_list_set"])

    def test_no_response_carries_a_key(self):
        for method, path, body in self.ROUTES:
            limits._hits.clear()
            text = self.call(method, path, **({"json": body} if body is not None else {})).text
            for secret in SECRETS:
                self.assertNotIn(secret, text, path)
        health = self.call("GET", "/health?deep=true").json()
        self.assertEqual(health["analysts"]["RISK"], {"provider": "deepseek", "model": "model-x"})
        configured = health["providers_configured"]                                # set or not, never the value
        self.assertEqual((configured["deepseek"], configured["openai"]), (True, False))
        self.assertEqual((health["analysts_configured"], health["model_diversity"]["distinct_models"],
                          health["model_diversity"]["model_diversity"]), (True, 1, False))     # three roles, one model: said as such
        self.assertEqual(health["policy"]["basis"], "CONFIGURED_POLICY")
        self.assertEqual(health["session"], {"role": "owner", "email_verified": True, "on_admin_list": True, "auth": "clerk"})
        self.assertIn("AI_TOTAL_TIMEOUT_SECONDS", health["timeouts"])
        self.assertEqual((health["auto_trading"], health["orders_sent"]), (False, 0))
        self.assertNotIn("api_key", json.dumps(health).lower())
        stored = json.dumps(self.db.advisor_consensus_runs.rows)
        self.assertNotIn(ADMIN, stored)                                            # the audit log keeps a hash, not the e-mail
        self.assertTrue(all(s not in stored for s in SECRETS))

    def test_analyze_releases_a_plan_only_through_the_consensus_and_stores_the_run(self):
        r = self.call("POST", "/analyze", json={"symbol": "sol/usdt", "portfolio_usdt": 1000})
        self.assertEqual(r.status_code, 200, r.text)
        run = r.json()
        self.assertEqual((run["symbol"], run["consensus"]["consensus"], run["order_sent"], run["auto_trading"]), ("SOL", "BUY", False, False))
        plan = run["buy_plan"]
        self.assertGreater(plan["trigger"], plan["resistance"][1])
        self.assertGreaterEqual(plan["limit"], plan["trigger"])
        self.assertLess(plan["technical_stop"], plan["technical_invalidation"])
        self.assertTrue(plan["position"]["suggested_notional"] <= 30.0)            # 3 % of the typed 1000
        self.assertNotIn("candles", run["snapshot"]["timeframes"]["15m"])
        self.assertEqual(run["snapshot"]["macro"]["macro_status"], "UNAVAILABLE")  # OpenBB is down: the report is still there
        doc = self.db.advisor_consensus_runs.rows[-1]
        self.assertEqual((doc["symbol"], doc["final_consensus"], doc["plan_released"]), ("SOL", "BUY", True))
        self.assertEqual((doc["technical_verdict"], doc["risk_verdict"], doc["regime_verdict"]), ("BUY", "APPROVE", "ALLOW"))
        for key in ("snapshot_hash", "ruleset_hash", "advisor_version", "git_commit", "working_tree_dirty", "models", "latency",
                    "admin_user_hash", "market_timestamp", "generated_at", "macro_snapshot_hash"):
            self.assertIn(key, doc)
        self.assertEqual(len(doc["admin_user_hash"]), 16)
        for change, outcome in (({"RISK": "REJECT"}, "NO_TRADE"), ({"REGIME": "BLOCK"}, "BLOCKED_SETUP"),
                                ({"TECHNICAL": None}, "DEGRADED_CONSENSUS")):
            self.ai = {"TECHNICAL": "BUY", "RISK": "APPROVE", "REGIME": "ALLOW", **change}
            run = self.call("POST", "/analyze", json={"symbol": "SOL", "portfolio_usdt": 1000}).json()
            self.assertEqual((run["consensus"]["consensus"], run["buy_plan"]), (outcome, None))
            self.assertTrue(run["why_not_trade"])
        run = self.call("POST", "/buy-plan", json={"symbol": "SOL", "with_ai": False}).json()
        self.assertEqual((run["buy_plan"], run["consensus"]["consensus"]), (None, "DEGRADED_CONSENSUS"))
        self.assertEqual(run["unreleased_plan"]["position_note"], "PORTFOLIO_REQUIRED_FOR_SIZING")

    def test_sell_plan_needs_a_position_and_keeps_the_stop_from_moving_down(self):
        self.assertEqual(self.call("POST", "/sell-plan", json={"symbol": "SOL"}).status_code, 400)
        r = self.call("POST", "/sell-plan", json={"symbol": "SOL", "entry_price": 98.0, "quantity": 2, "initial_stop": 97.5})
        self.assertEqual(r.status_code, 200, r.text)
        plan = r.json()["sell_plan"]
        self.assertEqual((plan["entry_price"], plan["initial_stop"], plan["order_sent"]), (98.0, 97.5, False))
        self.assertGreaterEqual(plan["current_R"], 1.0)
        state = self.db.advisor_positions.rows[0]
        self.assertEqual((state["symbol"], state["initial_risk"]), ("SOL", 0.5))
        self.db.advisor_positions.rows[0]["last_stop"] = plan["stop_loss"] + 0.2      # an earlier run had it higher
        again = self.call("POST", "/sell-plan", json={"symbol": "SOL", "entry_price": 98.0, "quantity": 2, "initial_stop": 97.5}).json()["sell_plan"]
        self.assertAlmostEqual(again["stop_loss"], plan["stop_loss"] + 0.2)
        self.assertEqual(self.call("POST", "/sell-plan", json={"symbol": "SOL", "entry_price": 98.0, "initial_stop": 99.0}).status_code, 400)

    def test_r_is_real_for_a_position_bought_on_a_released_plan_and_an_estimate_otherwise(self):
        run = self.call("POST", "/analyze", json={"symbol": "AVAX", "portfolio_usdt": 1000}).json()
        plan = run["buy_plan"]
        stored = self.db.advisor_plans.rows[0]
        self.assertEqual((stored["symbol"], stored["technical_stop"], stored["trigger"]), ("AVAX", plan["technical_stop"], plan["trigger"]))
        sell = self.call("POST", "/sell-plan", json={"symbol": "AVAX", "entry_price": plan["trigger"]}).json()["sell_plan"]   # filled at the trigger
        self.assertEqual((sell["initial_stop"], sell["initial_stop_source"], sell["current_R_estimated"], sell["r_basis"]),
                         (plan["technical_stop"], "V2_PLAN", False, "RECORDED_INITIAL_STOP"))
        old = self.call("POST", "/sell-plan", json={"symbol": "ARB", "entry_price": 97.0}).json()["sell_plan"]          # no plan, no stop on record
        self.assertEqual((old["current_R_estimated"], old["r_basis"], old["initial_stop_source"]), (True, "ESTIMATED_R", "ASSUMED_ATR"))
        self.call("POST", "/analyze", json={"symbol": "OP", "portfolio_usdt": 1000})
        far = self.call("POST", "/sell-plan", json={"symbol": "OP", "entry_price": 90.0}).json()["sell_plan"]           # not that plan's fill
        self.assertTrue(far["current_R_estimated"])

    def test_the_owners_portfolio_is_read_on_the_server(self):
        self.db.extras.rows.append({"id": "extras", "usdtry": 40.0, "nakit": {"KRIPTO": 100.0, "BIST": 4000.0}, "portfoy": [
            {"ad": "SOL", "piyasa": "KRIPTO", "para": "USD", "adet": 2.0, "maliyet": 196.0, "deger": 198.0,
             "pozlar": [{"id": 7, "adet": 2.0, "giris": 98.0, "stop": 97.6, "stop_ilk": 97.5, "acilis": "2026-09-01T10:00:00+03:00"}]},
            {"ad": "THYAO", "piyasa": "BIST", "para": "TL", "adet": 10, "maliyet": 3000.0, "deger": 4000.0, "pozlar": []}]})
        run = self.call("POST", "/analyze", json={"symbol": "SOL"}).json()
        p = run["snapshot"]["portfolio"]
        self.assertEqual((run["mode"], p["holding_exists"], p["entry_price"], p["initial_stop"]), ("POSITION", True, 98.0, 97.5))
        self.assertAlmostEqual(p["portfolio_value"], 198.0 + 100.0 + 8000.0 / 40.0)   # crypto + cash + the TL side in dollars
        self.assertTrue(p["total_known"])
        self.assertEqual(run["sell_plan"]["initial_stop"], 97.5)
        view = self.call("GET", "/portfolio").json()
        self.assertEqual(view["policy"]["basis"], "CONFIGURED_POLICY")
        self.assertEqual(view["portfolio"]["holdings"][0]["symbol"], "SOL")
        self.assertEqual(view["position_states"][0]["symbol"], "SOL")

    def test_scan_macro_history_stats_and_guards(self):
        s = self.call("POST", "/scan", json={"portfolio_usdt": 1000}).json()
        self.assertEqual({r["symbol"] for r in s["results"]}, {"AAA", "BBB"})
        self.assertEqual({r["consensus"] for r in s["results"]}, {"NOT_REQUESTED"})
        self.assertFalse(s["order_sent"])
        m = self.call("GET", "/macro").json()
        self.assertEqual((m["macro_status"], m["economic_events"]), ("UNAVAILABLE", []))
        self.call("POST", "/analyze", json={"symbol": "ETH"})
        rows = self.call("GET", "/consensus-history?symbol=eth").json()
        self.assertEqual([r["symbol"] for r in rows], ["ETH"])
        st = self.call("GET", "/paper-stats?origin=test").json()
        self.assertEqual(set(st["exit_styles"]["variants"]), {"A", "B", "C", "D"})
        self.assertEqual(st["exit_styles"]["variants"]["B"]["verdict"], "INCONCLUSIVE")
        self.assertEqual(self.call("GET", "/paper-stats?origin=x").status_code, 400)
        self.assertEqual(self.call("POST", "/analyze", json={"symbol": "BT$C"}).status_code, 400)
        self.assertEqual(self.call("POST", "/analyze", json={"symbol": "NOPE"}).status_code, 404)
        self.assertEqual(self.call("POST", "/analyze", json={"symbol": "BTC", "portfolio_usdt": -1}).status_code, 400)
        self.assertEqual(self.call("POST", "/scan", json={"limit": 2}).status_code, 400)
        limits._hits.clear()
        codes = [self.call("POST", "/analyze", json={"symbol": "BTC", "with_ai": False}).status_code for _ in range(api.ANALYZE_PER_MINUTE + 1)]
        self.assertEqual((codes[0], codes[-1]), (200, 429))

    def test_there_is_no_endpoint_that_could_send_an_order(self):
        paths = [r.path for r in self.app.routes]
        self.assertTrue(all(not any(w in p for w in ("order", "trade", "execute", "buy/", "sell/")) for p in paths), paths)
        source = Path(api.__file__).read_text(encoding="utf-8") + "".join(
            p.read_text(encoding="utf-8") for p in (api.advisor_api.BOT_DIR / "danisman_v2").glob("*.py"))
        for forbidden in ("/api/v3/order", "/sapi/", "X-MBX-APIKEY", "create_order", "new_order", "signature="):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
