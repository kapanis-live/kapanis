"""Multi-user acceptance tests against a real local MongoDB (separate test database, dropped after).

Clerk is simulated: tokens are signed with a throwaway RSA key and the Clerk profile lookup is patched,
so the backend code path (RS256 signature, expiry, issuer, azp, verified e-mail) is the real one.
Run: .venv\\Scripts\\python -m unittest tests.test_multiuser -v
"""
import os
import sys
import time
import unittest
import unittest.mock
from pathlib import Path

os.environ.update({
    "MONGO_URL": os.environ.get("TEST_MONGO_URL", "mongodb://127.0.0.1:27017"), "DB_NAME": "kapanis_test_multiuser",
    "JWT_SECRET": "test-secret-not-real", "BOT_API_KEY": "test-bot-key", "ADMIN_EMAIL": "owner@example.com",
    "ADMIN_PASSWORD": "owner-test-password", "OWNER_EMAIL": "owner@example.com", "AUTH_MODE": "both", "ALARM_LOOP": "0",
    "CLERK_JWKS_URL": "https://clerk.test.invalid/.well-known/jwks.json", "CLERK_SECRET_KEY": "sk_test_dummy",
    "CLERK_ISSUER": "https://clerk.test.invalid", "CLERK_AUTHORIZED_PARTIES": "https://kapanis.test",
    "CLERK_PUBLISHABLE_KEY": "pk_test_dummy", "USER_DAILY_ANALYSES": "3", "USER_KEY_DAILY_ANALYSES": "4",
    "GLOBAL_DAILY_ANALYSES": "5", "RATE_IP_PER_MINUTE": "100000", "KEY_ENCRYPTION_KEY": "kA9mS0Bq3QzvT8Xyq1dN0VYQe6o1c3pY3w5VYyC0x5g=",
})
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402
import jwt  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402

import identity  # noqa: E402
import server  # noqa: E402

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PROFILES = {
    "user_a": {"email": "a@example.com", "verified": True, "name": "A"},        # e.g. Google sign-in
    "user_b": {"email": "b@example.com", "verified": True, "name": "B"},        # e-mail + code, code entered
    "user_c": {"email": "c@example.com", "verified": True, "name": "C"},
    "user_d": {"email": "d@example.com", "verified": True, "name": "D"},
    "user_x": {"email": "x@example.com", "verified": False, "name": "X"},       # e-mail sign-up, code not entered
    "owner_clerk": {"email": "owner@example.com", "verified": True, "name": "Owner"},
}


class _Key:
    key = KEY.public_key()


class _Jwks:
    def get_signing_key_from_jwt(self, token):
        return _Key()


async def _profile(clerk_id):
    if clerk_id not in PROFILES:
        raise identity.AuthError("yok")
    return PROFILES[clerk_id]


identity._jwks = lambda: _Jwks()
identity.fetch_clerk_profile = _profile


def token(sub, exp_in=300, azp="https://kapanis.test", iss="https://clerk.test.invalid"):
    now = int(time.time())
    return jwt.encode({"sub": sub, "iat": now, "exp": now + exp_in, "azp": azp, "iss": iss}, KEY, algorithm="RS256")


def auth(sub, **kw):
    return {"Authorization": f"Bearer {token(sub, **kw)}"}


BOT = {"X-Bot-Key": "test-bot-key"}


class MultiUserTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # a fresh Motor client per test: each test runs in its own event loop
        server.client = server.AsyncIOMotorClient(os.environ["MONGO_URL"])
        server.db = server.client["kapanis_test_multiuser"]
        await server.client.drop_database("kapanis_test_multiuser")
        await server.startup()
        server.limits._hits.clear()
        server.limits._streams.clear()
        self.c = httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="https://kapanis.test")

    async def asyncTearDown(self):
        await self.c.aclose()
        await server.client.drop_database("kapanis_test_multiuser")

    async def test_verified_user_signs_in_unverified_does_not(self):
        r = await self.c.get("/api/auth/me", headers=auth("user_a"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual((r.json()["email"], r.json()["role"]), ("a@example.com", "user"))
        r = await self.c.get("/api/auth/me", headers=auth("user_x"))
        self.assertEqual(r.status_code, 401)
        self.assertIn("doğrulanmadı", r.json()["detail"])

    async def test_bad_tokens_rejected(self):
        self.assertEqual((await self.c.get("/api/auth/me", headers=auth("user_a", exp_in=-60))).status_code, 401)
        self.assertEqual((await self.c.get("/api/auth/me", headers=auth("user_a", azp="https://evil.test"))).status_code, 401)
        self.assertEqual((await self.c.get("/api/auth/me", headers=auth("user_a", iss="https://other.test"))).status_code, 401)
        other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        forged = jwt.encode({"sub": "user_a", "exp": int(time.time()) + 300, "iss": "https://clerk.test.invalid"}, other, algorithm="RS256")
        self.assertEqual((await self.c.get("/api/auth/me", headers={"Authorization": f"Bearer {forged}"})).status_code, 401)
        self.assertEqual((await self.c.get("/api/auth/me")).status_code, 401)

    async def test_users_cannot_see_each_others_portfolio(self):
        r = await self.c.post("/api/portfolio/positions", headers=auth("user_a"),
                              json={"piyasa": "BIST", "kod": "THYAO", "adet": 10, "maliyet": 290, "stop": 280})
        self.assertEqual(r.status_code, 200, r.text)
        pid = r.json()["id"]
        await self.c.put("/api/portfolio/cash", headers=auth("user_a"), json={"para": "TL", "tutar": 5000})
        a = (await self.c.get("/api/portfolio", headers=auth("user_a"))).json()
        b = (await self.c.get("/api/portfolio", headers=auth("user_b"))).json()
        self.assertEqual(len(a["positions"]), 1)
        self.assertEqual(a["cash_balance"]["TL"], 5000)
        self.assertEqual((b["positions"], b["transactions"], b["cash_balance"]["TL"]), ([], [], 0.0))
        # B cannot touch A's position even knowing its id
        self.assertEqual((await self.c.post(f"/api/portfolio/positions/{pid}/sell", headers=auth("user_b"), json={"fiyat": 300})).status_code, 404)
        self.assertEqual((await self.c.patch(f"/api/portfolio/positions/{pid}/stop", headers=auth("user_b"), json={"stop": 285})).status_code, 404)
        # and the bot owner's personal data stays closed to users
        for path in ("/api/positions", "/api/extras", "/api/decisions", "/api/signals", "/api/alerts", "/api/overview",
                     "/api/settings", "/api/report", "/api/usage", "/api/firsat", "/api/sonuclar/kontrol"):
            self.assertEqual((await self.c.get(path, headers=auth("user_a"))).status_code, 403, path)

    async def test_goalpost_and_trade_rules_on_user_portfolio(self):
        h = auth("user_a")
        pid = (await self.c.post("/api/portfolio/positions", headers=h,
                                 json={"piyasa": "BIST", "kod": "EREGL", "adet": 20, "maliyet": 40, "stop": 38})).json()["id"]
        self.assertEqual((await self.c.patch(f"/api/portfolio/positions/{pid}/stop", headers=h, json={"stop": 37})).status_code, 409)
        self.assertEqual((await self.c.patch(f"/api/portfolio/positions/{pid}/stop", headers=h, json={"stop": 39})).status_code, 200)
        bad = [{"piyasa": "BIST", "kod": "EREGL", "adet": 1.5, "maliyet": 40},  # BIST whole shares
               {"piyasa": "KRIPTO", "kod": "BTC", "adet": 1, "maliyet": 100, "stop": 120},  # spot: stop below cost
               {"piyasa": "KRIPTO", "kod": "BTC", "adet": -1, "maliyet": 100},
               {"piyasa": "FX", "kod": "EURUSD", "adet": 1, "maliyet": 1}]
        for body in bad:
            self.assertEqual((await self.c.post("/api/portfolio/positions", headers=h, json=body)).status_code, 400, body)
        r = await self.c.post(f"/api/portfolio/positions/{pid}/sell", headers=h, json={"fiyat": 45, "adet": 5})
        self.assertEqual((r.status_code, r.json()["kar"]), (200, 25.0))
        r = await self.c.post(f"/api/portfolio/positions/{pid}/sell", headers=h, json={"fiyat": 45, "adet": 99})
        self.assertEqual(r.status_code, 400)
        # deleting is not a sale: the record goes, no profit is booked, and only its owner may do it
        self.assertEqual((await self.c.delete(f"/api/portfolio/positions/{pid}", headers=auth("user_b"))).status_code, 404)
        self.assertEqual((await self.c.delete(f"/api/portfolio/positions/{pid}", headers=h)).status_code, 200)
        doc = (await self.c.get("/api/portfolio", headers=h)).json()
        self.assertEqual([p for p in doc["positions"] if p["id"] == pid], [])
        self.assertEqual((doc["transactions"][-1]["tur"], doc["transactions"][-1].get("kar")), ("silme", None))
        self.assertEqual((await self.c.delete(f"/api/portfolio/positions/{pid}", headers=h)).status_code, 404)

    async def test_advisor_v2_is_admin_only_through_the_real_session_path(self):
        """The whole server: an RS256 session token, the verified e-mail from the Clerk profile, the role from the
        database. ADMIN_EMAILS is checked against that e-mail, never against anything the request carries."""
        url = "/api/admin/advisor/health"
        spoof = {"X-Admin-Email": "owner@example.com", "X-User-Role": "owner", "X-Is-Admin": "true"}
        body = {"symbol": "BTC", "email": "owner@example.com", "role": "owner", "isAdmin": True}
        with unittest.mock.patch.dict(os.environ, {"ADMIN_EMAILS": "owner@example.com"}):
            self.assertEqual((await self.c.get(url)).status_code, 401)                                    # no session
            self.assertEqual((await self.c.get(url, headers=spoof)).status_code, 401)                     # headers are not a session
            self.assertEqual((await self.c.get(url, headers=auth("user_x"))).status_code, 401)            # e-mail not verified
            self.assertEqual((await self.c.get(url, headers=auth("user_a", exp_in=-60))).status_code, 401)  # expired token
            self.assertEqual((await self.c.get(url, headers=auth("user_a"))).status_code, 403)            # a signed-in user
            self.assertEqual((await self.c.get(f"{url}?email=owner@example.com&isAdmin=true",
                                               headers={**auth("user_a"), **spoof})).status_code, 403)    # forged e-mail / role
            r = await self.c.post("/api/admin/advisor/analyze", headers={**auth("user_a"), **spoof}, json=body)
            self.assertEqual(r.status_code, 403)
            r = await self.c.get(url, headers=auth("owner_clerk"))                                        # the admin
            self.assertEqual(r.status_code, 200, r.text)
            h = r.json()
            self.assertEqual(h["session"], {"role": "admin", "email_verified": True, "on_admin_list": True, "auth": "clerk"})
            self.assertEqual((h["auto_trading"], h["admin_list_set"]), (False, True))
            self.assertNotIn("owner@example.com", r.text)                                                 # no e-mail comes back
            self.assertNotIn("sk_test_dummy", r.text)
        with unittest.mock.patch.dict(os.environ, {"ADMIN_EMAILS": "someone-else@example.com"}):
            self.assertEqual((await self.c.get(url, headers=auth("owner_clerk"))).status_code, 403)       # owner, not on the list
        self.assertEqual(await server.db.advisor_consensus_runs.count_documents({}), 0)                   # nobody ran anything

    async def test_owner_keeps_bot_data_via_clerk_and_legacy(self):
        await self.c.post("/api/ingest/positions", headers=BOT, json=[{"id": "pos_1", "symbol": "BTC/USDT"}])
        r = await self.c.get("/api/positions", headers=auth("owner_clerk"))
        self.assertEqual((r.status_code, len(r.json())), (200, 1))
        me = (await self.c.get("/api/auth/me", headers=auth("owner_clerk"))).json()
        self.assertEqual(me["role"], "admin")  # the legacy admin account, now also reachable with Clerk
        r = await self.c.post("/api/auth/login", json={"email": "owner@example.com", "password": "owner-test-password"})
        self.assertEqual(r.status_code, 200)
        r = await self.c.get("/api/positions", cookies={"access_token": r.json()["access_token"]})
        self.assertEqual(r.status_code, 200)

    async def test_actions_and_analysis_isolation(self):
        ha, hb = auth("user_a"), auth("user_b")
        self.assertEqual((await self.c.post("/api/actions", headers=ha, json={"type": "plan.add", "payload": {"kod": "BTC"}})).status_code, 403)
        for _ in range(3):
            r = await self.c.post("/api/actions", headers=ha, json={"type": "analysis.request", "payload": {"kodlar": ["BTC"], "piyasa": "KRIPTO"}})
            self.assertEqual(r.status_code, 200)
        r = await self.c.post("/api/actions", headers=ha, json={"type": "analysis.request", "payload": {"kodlar": ["BTC"], "piyasa": "KRIPTO"}})
        self.assertEqual(r.status_code, 429)  # daily limit (3 in this test)
        pending = (await self.c.get("/api/commands/pending", headers=BOT)).json()
        me_a = (await self.c.get("/api/auth/me", headers=ha)).json()
        self.assertTrue(all(c["user_id"] == me_a["id"] and c["role"] == "user" and c["request_id"].startswith("req_") for c in pending))
        # the bot writes each analysis with the asking user's id
        me_b = (await self.c.get("/api/auth/me", headers=hb)).json()
        await self.c.post("/api/ingest/analyses", headers=BOT, json=[
            {"id": "an_a", "user_id": me_a["id"], "kodlar": ["BTC"], "zaman": "2026-09-27T10:00:00", "metin": "A"},
            {"id": "an_b", "user_id": me_b["id"], "kodlar": ["BTC"], "zaman": "2026-09-27T10:01:00", "metin": "B"},
            {"id": "an_old", "kodlar": ["BTC"], "zaman": "2026-09-20T10:00:00", "metin": "owner, before accounts"}])
        self.assertEqual([x["metin"] for x in (await self.c.get("/api/analyses?kod=BTC", headers=ha)).json()], ["A"])
        self.assertEqual([x["metin"] for x in (await self.c.get("/api/analyses?kod=BTC", headers=hb)).json()], ["B"])
        owner = [x["metin"] for x in (await self.c.get("/api/analyses?kod=BTC", headers=auth("owner_clerk"))).json()]
        self.assertEqual(owner, ["owner, before accounts"])
        # B's command list does not show A's requests
        self.assertEqual((await self.c.get("/api/commands", headers=hb)).json(), [])

    async def test_language_follows_the_account(self):
        """The site's switch: stored on the account; the bot is told only when there is a chat to switch."""
        h = auth("user_a")
        self.assertEqual((await self.c.put("/api/account/language", headers=h, json={"dil": "de"})).status_code, 400)
        r = (await self.c.put("/api/account/language", headers=h, json={"dil": "en"})).json()
        self.assertEqual(r, {"dil": "en", "telegram": False})                 # no linked chat: nothing queued for the bot
        self.assertEqual((await self.c.get("/api/commands/pending", headers=BOT)).json(), [])
        self.assertEqual((await self.c.get("/api/auth/me", headers=h)).json()["dil"], "en")
        # linking Telegram afterwards hands the bot the chosen language
        code = (await self.c.post("/api/telegram/link-code", headers=h)).json()["kod"]
        link = (await self.c.post("/api/bot/telegram/link", headers=BOT, json={"code": code, "chat_id": 111, "username": "a_tg"})).json()
        self.assertEqual(link["dil"], "en")
        # with a linked chat a change is queued for that chat only
        self.assertTrue((await self.c.put("/api/account/language", headers=h, json={"dil": "tr"})).json()["telegram"])
        cmds = (await self.c.get("/api/commands/pending", headers=BOT)).json()
        self.assertEqual([(c["type"], c["payload"], c["telegram_chat_id"], c["role"]) for c in cmds], [("language.set", {"dil": "tr"}, 111, "user")])
        # the owner's choice goes to the owner's chat (role owner)
        await self.c.put("/api/account/language", headers=auth("owner_clerk"), json={"dil": "en"})
        roles = sorted(c["role"] for c in (await self.c.get("/api/commands/pending", headers=BOT)).json())
        self.assertEqual(roles, ["owner", "user"])

    async def test_telegram_link_one_time_code(self):
        h = auth("user_a")
        code = (await self.c.post("/api/telegram/link-code", headers=h)).json()["kod"]
        self.assertEqual((await self.c.post("/api/bot/telegram/link", json={"code": code, "chat_id": 111})).status_code, 401)
        r = await self.c.post("/api/bot/telegram/link", headers=BOT, json={"code": code.lower(), "chat_id": 111, "username": "a_tg"})
        self.assertEqual(r.status_code, 200)
        self.assertTrue((await self.c.get("/api/telegram/status", headers=h)).json()["bagli"])
        self.assertEqual((await self.c.post("/api/bot/telegram/link", headers=BOT, json={"code": code, "chat_id": 222})).status_code, 404)
        # the next analysis request carries the chat id for the bot; B's does not
        await self.c.post("/api/actions", headers=h, json={"type": "analysis.request", "payload": {"kodlar": ["ETH"], "piyasa": "KRIPTO"}})
        await self.c.post("/api/actions", headers=auth("user_b"), json={"type": "analysis.request", "payload": {"kodlar": ["ETH"], "piyasa": "KRIPTO"}})
        chats = sorted(str(c.get("telegram_chat_id")) for c in (await self.c.get("/api/commands/pending", headers=BOT)).json())
        self.assertEqual(chats, ["111", "None"])
        # expired code
        await server.db.telegram_links.insert_one({"code_hash": server.user_api.hash_code("KP-OLDOLD11"), "user_id": "x",
                                                   "used": False, "created_at": server.datetime.now(server.timezone.utc),
                                                   "expires_at": server.datetime.now(server.timezone.utc) - server.timedelta(minutes=1)})
        self.assertEqual((await self.c.post("/api/bot/telegram/link", headers=BOT, json={"code": "KP-OLDOLD11", "chat_id": 333})).status_code, 404)
        await self.c.delete("/api/telegram/link", headers=h)
        self.assertFalse((await self.c.get("/api/telegram/status", headers=h)).json()["bagli"])

    async def test_clerk_only_mode_disables_password_login(self):
        old = identity.AUTH_MODE
        identity.AUTH_MODE = "clerk"
        try:
            r = await self.c.post("/api/auth/login", json={"email": "owner@example.com", "password": "owner-test-password"})
            self.assertEqual(r.status_code, 404)
            cfg = (await self.c.get("/api/auth/config")).json()
            self.assertEqual((cfg["clerk"], cfg["legacy"], cfg["clerk_publishable_key"]), (True, False, "pk_test_dummy"))
        finally:
            identity.AUTH_MODE = old

    async def test_telegram_portfolio_and_crisis_plan_stay_in_linked_account(self):
        ha, hb = auth("user_a"), auth("user_b")
        code = (await self.c.post("/api/telegram/link-code", headers=ha)).json()["kod"]
        await self.c.post("/api/bot/telegram/link", headers=BOT, json={"code": code, "chat_id": 111})
        r = await self.c.post("/api/bot/telegram/position", headers=BOT,
                              json={"chat_id": 111, "piyasa": "BIST", "kod": "THYAO", "adet": 2, "maliyet": 100})
        self.assertEqual(r.status_code, 200, r.text)
        pid = r.json()["id"]
        self.assertEqual((await self.c.get("/api/portfolio", headers=hb)).json()["positions"], [])

        day = 86400
        base = (int(time.time()) // day - 3) * day + 7 * 3600  # 07:00 UTC, three closed BIST sessions

        async def chart(*args):
            return {"candles": [{"t": base, "c": 110}, {"t": base + day, "c": 120}, {"t": base + 2 * day, "c": 121}]}
        original = server.user_api.chart_data.chart
        server.user_api.chart_data.chart = chart
        try:
            proposal = (await self.c.post("/api/bot/telegram/risk-proposal", headers=BOT,
                                          json={"chat_id": 111})).json()
        finally:
            server.user_api.chart_data.chart = original
        self.assertEqual(proposal["suggestions"][0]["id"], pid)
        # every open position is listed with its risk now and after; stops cannot be undone (goalpost)
        self.assertEqual(proposal["affected"][0]["fiyat"], 121)
        self.assertEqual((proposal["affected"][0]["risk_sonra"], proposal["geri_alinabilir"]), (round(2 * (121 - 114.95), 2), {"risk_hedefi": True, "stoplar": False}))
        url = f"/api/risk/proposals/{proposal['id']}/apply"
        self.assertEqual((await self.c.post(url, headers=hb, json={"position_ids": [pid]})).status_code, 404)
        self.assertEqual((await self.c.get("/api/portfolio", headers=ha)).json()["risk_target_pct"], 1)
        self.assertEqual((await self.c.post(url, headers=ha, json={"position_ids": [pid]})).status_code, 200)
        portfolio = (await self.c.get("/api/portfolio", headers=ha)).json()
        self.assertEqual((portfolio["risk_target_pct"], portfolio["risk_mode"]), (0.5, "defansif"))
        self.assertEqual(portfolio["positions"][0]["stop"], 114.95)
        await self.c.post("/api/risk/restore-target", headers=ha)
        restored = (await self.c.get("/api/portfolio", headers=ha)).json()
        self.assertEqual(restored["risk_target_pct"], 1)
        self.assertEqual(restored["positions"][0]["stop"], 114.95)

    async def test_telegram_add_is_confirmed_marked_and_refused_when_ambiguous(self):
        ha = auth("user_a")
        code = (await self.c.post("/api/telegram/link-code", headers=ha)).json()["kod"]
        await self.c.post("/api/bot/telegram/link", headers=BOT, json={"code": code, "chat_id": 555})
        r = (await self.c.post("/api/bot/telegram/position", headers=BOT,
                               json={"chat_id": 555, "piyasa": "BIST", "kod": "EREGL", "adet": 3, "maliyet": 40})).json()
        self.assertEqual((r["kaynak"], r["hesap"]), ("telegram", "a***@example.com"))
        pos = (await self.c.get("/api/portfolio", headers=ha)).json()["positions"][0]
        self.assertEqual(pos["kaynak"], "telegram")
        # a chat that somehow maps to two accounts never gets a purchase written anywhere
        await server.db.users.update_one({"email": "b@example.com"}, {"$set": {"telegram_chat_id": 555}}, upsert=False)
        await self.c.get("/api/auth/me", headers=auth("user_b"))
        await server.db.users.update_one({"email": "b@example.com"}, {"$set": {"telegram_chat_id": 555}})
        r = await self.c.post("/api/bot/telegram/position", headers=BOT,
                              json={"chat_id": 555, "piyasa": "BIST", "kod": "EREGL", "adet": 1, "maliyet": 40})
        self.assertEqual(r.status_code, 409)

    async def test_portfolio_stream_sends_only_revision_numbers(self):
        h = auth("user_a")
        await self.c.post("/api/portfolio/positions", headers=h, json={"piyasa": "BIST", "kod": "THYAO", "adet": 1, "maliyet": 290})
        server.user_api.STREAM_SECONDS = 1  # the test client buffers the whole stream
        async with self.c.stream("GET", "/api/portfolio/stream", headers=h) as resp:
            self.assertEqual(resp.headers["content-type"].split(";")[0], "text/event-stream")
            first = ""
            async for chunk in resp.aiter_text():
                first += chunk
                if "\n\n" in first:
                    break
        self.assertTrue(first.startswith("event: rev\ndata: "), first)
        self.assertNotIn("THYAO", first)
        self.assertEqual((await self.c.get("/api/portfolio/stream")).status_code, 401)

    async def test_bot_endpoints_refuse_internet_traffic_even_with_the_key(self):
        public = {**BOT, "X-Kapanis-Public": "1"}  # what the site's reverse proxy adds to every outside request
        for method, path in (("GET", "/api/commands/pending"), ("GET", "/api/bot/user-keys/x"),
                             ("GET", "/api/bot/telegram/linked/1"), ("POST", "/api/ingest/positions")):
            self.assertEqual((await self.c.request(method, path, headers=public, json=[])).status_code, 404, path)
        self.assertEqual((await self.c.get("/api/commands/pending", headers=BOT)).status_code, 200)  # internal worker
        self.assertFalse((await self.c.get("/api/bot/telegram/linked/111", headers=BOT)).json()["bagli"])
        code = (await self.c.post("/api/telegram/link-code", headers=auth("user_a"))).json()["kod"]
        await self.c.post("/api/bot/telegram/link", headers=BOT, json={"code": code, "chat_id": 111})
        self.assertTrue((await self.c.get("/api/bot/telegram/linked/111", headers=BOT)).json()["bagli"])

    async def test_rate_limits_per_ip_per_user_and_open_streams(self):
        old = server.limits.IP_PER_MINUTE, server.limits.CHART_PER_MINUTE, server.limits.MAX_STREAMS
        server.limits.IP_PER_MINUTE, server.limits.CHART_PER_MINUTE, server.limits.MAX_STREAMS = 5, 2, 1
        try:
            codes = [(await self.c.get("/api/auth/config")).status_code for _ in range(6)]
            self.assertEqual(codes, [200] * 5 + [429])
            server.limits._hits.clear()
            server.limits.IP_PER_MINUTE = 1000
            h = auth("user_a")

            async def fake_chart(symbol, tf, market):
                return {"symbol": symbol}
            with unittest.mock.patch.object(server.chart_data, "chart", fake_chart):
                chart = [(await self.c.get("/api/chart/THYAO?market=BIST", headers=h)).status_code for _ in range(3)]
                self.assertEqual(chart, [200, 200, 429])
                self.assertEqual((await self.c.get("/api/chart/THYAO?market=BIST", headers=auth("user_b"))).status_code, 200)
            with server.limits.StreamSlot("u1"):
                with self.assertRaises(server.HTTPException):
                    server.limits.StreamSlot("u1").__enter__()  # a second tab of the same user
                with server.limits.StreamSlot("u2"):
                    pass  # other users are not affected
            with server.limits.StreamSlot("u1"):
                pass  # the slot is free again after the first connection closed
        finally:
            server.limits.IP_PER_MINUTE, server.limits.CHART_PER_MINUTE, server.limits.MAX_STREAMS = old

    async def test_strategy_and_quant_scan_are_scoped_and_queued(self):
        ha, hb = auth("user_a"), auth("user_b")
        strategy = (await self.c.post("/api/strategies", headers=ha, json={"name": "Altın Vuruş",
                    "rules": {"fk_max": 10, "momentum_min": 0, "quality_min": 70}})).json()
        self.assertEqual((await self.c.post(f"/api/strategies/{strategy['id']}/run", headers=hb)).status_code, 404)
        self.assertEqual((await self.c.post(f"/api/strategies/{strategy['id']}/run", headers=ha)).status_code, 200)
        code = (await self.c.post("/api/telegram/link-code", headers=ha)).json()["kod"]
        await self.c.post("/api/bot/telegram/link", headers=BOT, json={"code": code, "chat_id": 111})
        self.assertEqual((await self.c.post("/api/bot/telegram/quant-run", headers=BOT,
                                       json={"chat_id": 222, "top_n": 3})).status_code, 404)
        # A second scan waits until the first completes, so the worker cannot mix two requests.
        self.assertEqual((await self.c.post("/api/bot/telegram/quant-run", headers=BOT,
                                       json={"chat_id": 111, "top_n": 3})).status_code, 409)
        pending = (await self.c.get("/api/commands/pending", headers=BOT)).json()
        self.assertEqual((len(pending), pending[0]["payload"]["strategy_id"]), (1, strategy["id"]))


class _FakeProvider:
    """Stands in for the AI provider's key check: keys starting with 'bad' are refused."""
    calls = []

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def request(self, method, url, headers=None, json=None):
        _FakeProvider.calls.append(url)
        bad = headers["Authorization"].split()[-1].startswith("bad")
        return httpx.Response(401 if bad else 200, request=httpx.Request(method, url))


class OwnKeysAndAccountTest(MultiUserTest.__bases__[0]):
    async def asyncSetUp(self):
        await MultiUserTest.asyncSetUp(self)
        self._orig = server.user_api.httpx.AsyncClient
        server.user_api.httpx.AsyncClient = _FakeProvider

    async def asyncTearDown(self):
        server.user_api.httpx.AsyncClient = self._orig
        await MultiUserTest.asyncTearDown(self)

    async def test_own_key_is_encrypted_masked_and_only_for_a_waiting_analysis(self):
        h = auth("user_a")
        key = "sk-" + "x" * 30 + "WXYZ"
        self.assertEqual((await self.c.put("/api/ai-keys", headers=h, json={"saglayici": "deepseek", "anahtar": "bad" + "y" * 30})).status_code, 400)
        r = await self.c.put("/api/ai-keys", headers=h, json={"saglayici": "deepseek", "anahtar": key})
        self.assertEqual((r.status_code, r.json()["maske"]), (200, "••••WXYZ"))
        raw = await server.db.users.find_one({"email": "a@example.com"})
        self.assertNotIn(key, str(raw))                        # stored encrypted
        for path in ("/api/auth/me", "/api/ai-keys", "/api/account/export"):
            body = (await self.c.get(path, headers=h)).text
            self.assertNotIn(key, body, path)
            self.assertNotIn(raw["ai_keys"]["deepseek"]["enc"], body, path)
        me = (await self.c.get("/api/auth/me", headers=h)).json()
        self.assertEqual(me["kendi_anahtari"], ["deepseek"])
        # the bot gets the key only while this user has an analysis waiting, and only with the bot key
        self.assertEqual((await self.c.get(f"/api/bot/user-keys/{me['id']}", headers=BOT)).status_code, 404)
        await self.c.post("/api/actions", headers=h, json={"type": "analysis.request", "payload": {"kodlar": ["BTC"], "piyasa": "KRIPTO"}})
        self.assertEqual((await self.c.get(f"/api/bot/user-keys/{me['id']}")).status_code, 401)
        self.assertEqual((await self.c.get(f"/api/bot/user-keys/{me['id']}", headers=BOT)).json(), {"deepseek": key})
        cmd = (await self.c.get("/api/commands/pending", headers=BOT)).json()[0]
        self.assertTrue(cmd["own_keys"])
        self.assertNotIn(key, str(cmd))
        # own key: the higher limit (4 in this test) instead of 3, outside the shared capacity
        for _ in range(3):
            await self.c.post("/api/actions", headers=h, json={"type": "analysis.request", "payload": {"kodlar": ["BTC"], "piyasa": "KRIPTO"}})
        r = await self.c.post("/api/actions", headers=h, json={"type": "analysis.request", "payload": {"kodlar": ["BTC"], "piyasa": "KRIPTO"}})
        self.assertEqual(r.status_code, 429)
        await self.c.delete("/api/ai-keys/deepseek", headers=h)
        self.assertEqual((await self.c.get("/api/auth/me", headers=h)).json()["kendi_anahtari"], [])

    async def test_shared_capacity_caps_all_users_together(self):
        ok = 0
        for sub in ("user_a", "user_b", "user_c"):
            for _ in range(2):
                r = await self.c.post("/api/actions", headers=auth(sub), json={"type": "analysis.request", "payload": {"kodlar": ["ETH"], "piyasa": "KRIPTO"}})
                ok += r.status_code == 200
        self.assertEqual(ok, 5)  # GLOBAL_DAILY_ANALYSES = 5 even though each user may do 3

    async def test_account_export_and_delete(self):
        h = auth("user_d")
        await self.c.post("/api/portfolio/positions", headers=h, json={"piyasa": "BIST", "kod": "THYAO", "adet": 1, "maliyet": 290})
        exp = (await self.c.get("/api/account/export", headers=h)).json()
        self.assertEqual(exp["hesap"]["email"], "d@example.com")
        self.assertEqual(len(exp["portfoy"]["positions"]), 1)
        deleted = []

        async def fake_delete(cid):
            deleted.append(cid)
            return True
        orig = identity.delete_clerk_user
        identity.delete_clerk_user = fake_delete
        try:
            self.assertEqual((await self.c.delete("/api/account", headers=h)).status_code, 200)
        finally:
            identity.delete_clerk_user = orig
        self.assertEqual(deleted, ["user_d"])
        self.assertIsNone(await server.db.users.find_one({"email": "d@example.com"}))
        self.assertEqual(await server.db.portfolios.count_documents({}), 0)
        # the owner's account cannot be deleted from the panel (the bot depends on it)
        self.assertEqual((await self.c.delete("/api/account", headers=auth("owner_clerk"))).status_code, 403)

    async def test_admin_user_list_is_owner_only(self):
        await self.c.get("/api/auth/me", headers=auth("user_a"))
        self.assertEqual((await self.c.get("/api/admin/users", headers=auth("user_a"))).status_code, 403)
        r = (await self.c.get("/api/admin/users", headers=auth("owner_clerk"))).json()
        self.assertIn("a@example.com", [u["email"] for u in r["kullanicilar"]])
        self.assertNotIn("positions", str(r))  # counts only, no portfolio contents


class UserAlarmTest(MultiUserTest.__bases__[0]):
    """Close-based user alarms: checked by the web service, delivered by the bot."""
    asyncSetUp = MultiUserTest.asyncSetUp
    asyncTearDown = MultiUserTest.asyncTearDown

    def _fake_chart(self, closes, start, step=3600):
        async def chart(symbol, tf="1d", market=None):
            if symbol == "YOKBOYLE":
                raise server.chart_data.ChartError("yok")
            return {"candles": [{"t": start + i * step, "c": c} for i, c in enumerate(closes)],
                    "rsi": [50.0] * (len(closes) - 1) + [25.0]}
        return chart

    async def test_price_alarm_fires_once_on_a_new_close_and_is_delivered(self):
        import unittest.mock as um
        h = auth("user_a")
        code = (await self.c.post("/api/telegram/link-code", headers=h)).json()["kod"]
        await self.c.post("/api/bot/telegram/link", headers=BOT, json={"code": code, "chat_id": 4242})
        start = int(time.time()) - 5 * 3600 - 60  # 5 closed 1h candles + one forming
        closes = [100, 101, 102, 103, 104, 110]
        with um.patch.object(server.user_alerts.chart_data, "chart", self._fake_chart(closes, start)):
            bad = await self.c.post("/api/alarms", headers=h, json={"piyasa": "BIST", "kod": "THYAO", "tur": "fiyat",
                                                                   "yon": "ustu", "seviye": 105, "tf": "1h"})
            self.assertEqual(bad.status_code, 400)  # BIST: daily only
            self.assertEqual((await self.c.post("/api/alarms", headers=h, json={
                "piyasa": "KRIPTO", "kod": "YOKBOYLE", "seviye": 1, "tf": "1h"})).status_code, 404)
            a = (await self.c.post("/api/alarms", headers=h, json={"piyasa": "KRIPTO", "kod": "btc", "tur": "fiyat",
                                                                  "yon": "ustu", "seviye": 105, "tf": "1h"})).json()
            self.assertEqual((a["kod"], a["son_kapanis"]), ("BTC", 104))
            # the forming candle (110) never counts, and the old closes were before the alarm existed
            self.assertEqual(await server.user_alerts.run_once(server.db), 0)
            # an hour later the 110 candle has closed after the alarm was created: fires once
            later = time.time() + 3600
            self.assertEqual(await server.user_alerts.run_once(server.db, now=later), 1)
            self.assertEqual(await server.user_alerts.run_once(server.db, now=later), 0)
        mine = (await self.c.get("/api/alarms", headers=h)).json()
        self.assertEqual(mine["alarmlar"][0]["durum"], "tetiklendi")
        self.assertIn("BTC", mine["olaylar"][0]["metin"])
        self.assertEqual((await self.c.get("/api/alarms", headers=auth("user_b"))).json()["alarmlar"], [])
        self.assertEqual((await self.c.delete(f"/api/alarms/{a['id']}", headers=auth("user_b"))).status_code, 404)
        events = (await self.c.get("/api/bot/alarm-events", headers=BOT)).json()
        self.assertEqual([(e["chat_id"], e["kod"]) for e in events], [(4242, "BTC")])
        self.assertEqual((await self.c.get("/api/bot/alarm-events", headers={**BOT, "X-Kapanis-Public": "1"})).status_code, 404)
        await self.c.post(f"/api/bot/alarm-events/{events[0]['id']}/sent", headers=BOT)
        self.assertEqual((await self.c.get("/api/bot/alarm-events", headers=BOT)).json(), [])

    async def test_weekly_summary_once_on_sunday_evening_and_owner_events_reach_the_bot(self):
        import datetime as dt
        import unittest.mock as um
        ua = server.user_alerts
        h = auth("user_a")
        code = (await self.c.post("/api/telegram/link-code", headers=h)).json()["kod"]
        await self.c.post("/api/bot/telegram/link", headers=BOT, json={"code": code, "chat_id": 5151})
        await self.c.post("/api/portfolio/positions", headers=h,
                          json={"piyasa": "KRIPTO", "kod": "SOL", "adet": 2, "maliyet": 100, "stop": 97})
        # a Sunday 20:30 in Turkey; positions were opened "now", so the week's base is the cost (100)
        sunday = dt.datetime(2026, 10, 4, 20, 30, tzinfo=ua.TR).timestamp()
        start = int(sunday) - 10 * 86400
        closes = [90, 92, 95, 96, 98, 99, 100, 99, 98, 99, 99.5]
        with um.patch.object(ua.chart_data, "chart", self._fake_chart(closes, start, step=86400)):
            self.assertEqual(await ua.weekly_once(server.db, now=sunday - 86400), 0)  # Saturday: nothing
            self.assertEqual(await ua.weekly_once(server.db, now=sunday), 1)
            self.assertEqual(await ua.weekly_once(server.db, now=sunday + 600), 0)   # once per week
        ev = [e for e in (await self.c.get("/api/bot/alarm-events", headers=BOT)).json() if e["id"].startswith("ozet_")]
        self.assertEqual(len(ev), 1)
        self.assertIn("Haftalık özet", ev[0]["metin"])
        self.assertIn("Stopa yakın", ev[0]["metin"])  # 99 vs stop 97: 2.1% above
        # the owner has no Telegram id on the account: their events are marked for the bot's own chat
        owner = await server.db.users.find_one({"email": "owner@example.com"})
        await ua._event(server.db, owner, "BTC", "KRIPTO", "1d", "🔔 test")
        owner_ev = [e for e in (await self.c.get("/api/bot/alarm-events", headers=BOT)).json() if e.get("sahip")]
        self.assertEqual(len(owner_ev), 1)

    async def test_trend_alarm_fires_on_each_state_change(self):
        import unittest.mock as um
        ua = server.user_alerts
        h = auth("user_a")
        closes = {"v": [100.0] * 240}
        start = int(time.time()) - 240 * 86400 - 60

        async def chart(symbol, tf="1d", market=None):
            cs = closes["v"]
            return {"candles": [{"t": start + i * 86400, "c": c, "h": c * 1.01, "l": c * 0.99} for i, c in enumerate(cs)],
                    "sma200": [100.0] * len(cs), "rsi": [50.0] * len(cs)}
        with um.patch.object(ua.chart_data, "chart", chart):
            self.assertEqual((await self.c.post("/api/alarms", headers=h, json={"piyasa": "BIST", "kod": "THYAO",
                                                                             "tur": "trend", "tf": "1d"})).status_code, 400)
            a = (await self.c.post("/api/alarms", headers=h, json={"piyasa": "KRIPTO", "kod": "BTC", "tur": "trend", "tf": "1d"})).json()
            self.assertFalse(a["trendde"])
            board = (await self.c.get("/api/strategies/trend", headers=h)).json()
            self.assertIn("satirlar", board["kanit"])
            closes["v"] = [100.0] * 237 + [104, 108, 112]    # breakout: entry
            later = time.time() + 86400 * 3
            self.assertEqual(await ua.run_once(server.db, now=later), 1)
            self.assertEqual(await ua.run_once(server.db, now=later), 0)
            closes["v"] = [100.0] * 237 + [104, 108, 90]     # close below the 10-day low: exit
            self.assertEqual(await ua.run_once(server.db, now=later), 1)
        texts = [e["metin"] for e in (await self.c.get("/api/alarms", headers=h)).json()["olaylar"]]
        self.assertTrue(any("GİRİŞ" in t for t in texts) and any("ÇIKIŞ" in t for t in texts))

    async def test_portfolio_health_and_trend_live_record(self):
        import unittest.mock as um
        ua, ins = server.user_alerts, server.insights
        h = auth("user_c")
        for kod, adet, cost in (("ETH", 1, 100), ("SOL", 10, 10)):
            await self.c.post("/api/portfolio/positions", headers=h, json={"piyasa": "KRIPTO", "kod": kod, "adet": adet, "maliyet": cost})
        start = int(time.time()) - 130 * 86400

        async def chart(symbol, tf="1d", market=None):
            if symbol == "USDTRY=X":
                return {"candles": [{"t": start + i * 86400, "c": 40.0} for i in range(130)]}
            cs = [100 + (i % 9) * 2 + i * 0.3 for i in range(130)]   # SOL moves exactly like ETH
            k = 1.0 if symbol == "ETH" else 0.1
            return {"candles": [{"t": start + i * 86400, "c": c * k, "h": c * k * 1.01, "l": c * k * 0.99} for i, c in enumerate(cs)],
                    "sma200": [50.0 * k] * 130}
        with um.patch.object(ins.chart_data, "chart", chart), um.patch.object(ua.chart_data, "chart", chart):
            hl = (await self.c.get("/api/portfolio/health", headers=h)).json()
        self.assertEqual(len(hl["pozisyonlar"]), 2)
        self.assertEqual(sum(p["agirlik_yuzde"] for p in hl["pozisyonlar"]), 100.0)
        self.assertEqual(hl["korelasyon"][0]["r"], 1.0)
        self.assertTrue(any("birlikte hareket" in w for w in hl["uyarilar"]))
        self.assertTrue(any("stop yok" in w for w in hl["uyarilar"]))
        self.assertEqual((await self.c.get("/api/karne", headers=h)).json()["islem"], 0)
        # live record: an entry that happened before the record began is not back-filled
        states = [{"kod": "BTC", "trendde": True, "degisim": time.time() - 10 * 86400, "degisim_kapanis": 90.0,
                   "kapanis": 100.0, "giris_bugun": False, "mum": 0}]
        with um.patch.object(ins.trend_rule, "universe_states", um.AsyncMock(return_value=states)):
            self.assertEqual(await ins.record_trend(server.db), 0)
            t0 = time.time()
            states[0].update(trendde=False, degisim=t0 - 3600, degisim_kapanis=95.0)
            await ins.record_trend(server.db)
            states[0].update(trendde=True, degisim=t0 + 86400, degisim_kapanis=100.0, kapanis=100.0)
            self.assertEqual(await ins.record_trend(server.db, now=t0 + 2 * 86400), 1)   # new entry after the start
            states[0].update(trendde=False, degisim=t0 + 5 * 86400, degisim_kapanis=110.0, kapanis=110.0)
            self.assertEqual(await ins.record_trend(server.db, now=t0 + 6 * 86400), 1)   # exit: closed with the result
            rec = await ins.trend_record(server.db)
        self.assertEqual((rec["kapali"], rec["acik"]), (1, 0))
        self.assertAlmostEqual(rec["ort_getiri_yuzde"], 9.78, places=1)                  # +10 % minus 0.1 % per side

    async def test_risk_size_is_arithmetic_with_reasons(self):
        import unittest.mock as um
        h = auth("user_d")
        await self.c.put("/api/portfolio/cash", headers=h, json={"para": "TL", "tutar": 100000})
        start = int(time.time()) - 400 * 86400

        async def chart(symbol, tf="1d", market=None):
            if symbol == "USDTRY=X":
                return {"candles": [{"t": start + i * 86400, "c": 40.0, "h": 40.0, "l": 40.0} for i in range(400)]}
            cs = [100 + (i % 10) for i in range(400)]
            return {"candles": [{"t": start + i * 86400, "c": c, "h": c + 2, "l": c - 2} for i, c in enumerate(cs)],
                    "sma50": [104.0] * 400, "sma200": [104.0] * 400}
        with um.patch.object(server.risk_budget.chart_data, "chart", chart), um.patch.object(server.insights.chart_data, "chart", chart):
            r = (await self.c.post("/api/risk/size", headers=h, json={"piyasa": "BIST", "kod": "THYAO", "stop": 95})).json()
            self.assertEqual(r["adet"], float(int(r["adet"])))                 # whole lots on BIST
            self.assertLessEqual(r["risk_tl"], 1000 + 1e-6)                    # 1 % of 100,000 TL at most
            self.assertTrue(any("Oynaklık" in x for x in r["satirlar"]))
            self.assertEqual((await self.c.post("/api/risk/size", headers=h, json={"piyasa": "BIST", "kod": "THYAO",
                                                                                "stop": 500})).status_code, 400)
            reg = (await self.c.get("/api/market/regime", headers=h)).json()
            self.assertEqual(len(reg["rejimler"]), 3)

    async def test_turn_of_month_notifies_entry_and_exit_days(self):
        import datetime as dt
        import unittest.mock as um
        ua = server.user_alerts
        h = auth("user_a")

        async def chart(symbol, tf="1d", market=None):
            return {"candles": [{"t": 1, "c": 100.0, "h": 101, "l": 99}], "rsi": [50.0]}
        with um.patch.object(ua.chart_data, "chart", chart):
            r = await self.c.post("/api/alarms", headers=h, json={"piyasa": "BIST", "kod": "-", "tur": "ay_donumu"})
            self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual((await self.c.post("/api/alarms", headers=h, json={"piyasa": "BIST", "kod": "-", "tur": "ay_donumu"})).status_code, 400)
            noon = lambda d: dt.datetime.fromisoformat(d + "T13:00:00+03:00").timestamp()  # noqa: E731
            self.assertEqual(await ua.run_once(server.db, now=noon("2026-09-29")), 1)   # first day of the window
            self.assertEqual(await ua.run_once(server.db, now=noon("2026-09-29")), 0)   # once
            self.assertEqual(await ua.run_once(server.db, now=noon("2026-10-01")), 0)   # middle
            self.assertEqual(await ua.run_once(server.db, now=noon("2026-10-05")), 1)   # last day
        ev = [e["metin"] for e in (await self.c.get("/api/alarms", headers=h)).json()["olaylar"]]
        self.assertTrue(any("başlıyor" in e for e in ev) and any("bitiyor" in e for e in ev))
        w = (await self.c.get("/api/strategies/tom", headers=h)).json()["pencereler"]
        self.assertEqual([x["piyasa"] for x in w], ["BIST", "KRIPTO"])

    def test_tom_skips_bist_holidays(self):
        import datetime as dt
        import tom
        self.assertEqual(tom.window("BIST", dt.date(2026, 10, 27))["gunler"][:2], ["2026-10-28", "2026-10-30"])  # 29 Ekim closed
        self.assertEqual(tom.window("BIST", dt.date(2026, 5, 20))["gunler"][2], "2026-06-01")                    # Kurban Bayramı

    async def test_stress_and_decision_capsule(self):
        import unittest.mock as um
        ua, ins = server.user_alerts, server.insights
        h = auth("user_b")
        r = await self.c.post("/api/portfolio/positions", headers=h, json={
            "piyasa": "KRIPTO", "kod": "ETH", "adet": 1, "maliyet": 100, "tez": "ETF onayı gelecek", "cikis_sarti": "90 altı kapanış"})
        self.assertEqual(r.status_code, 200, r.text)
        start = int(time.time()) - 300 * 86400

        async def chart(symbol, tf="1d", market=None):
            if symbol == "USDTRY=X":
                return {"candles": [{"t": start + i * 86400, "c": 40.0} for i in range(300)]}
            k = 2.0 if symbol == "ETH" else 1.0   # ETH moves twice as much as BTC
            cs = [100 * (1 + k * 0.01 * ((i % 7) - 3)) for i in range(300)]
            return {"candles": [{"t": start + i * 86400, "c": c, "h": c, "l": c} for i, c in enumerate(cs)], "rsi": [50.0] * 300}
        with um.patch.object(ins.chart_data, "chart", chart), um.patch.object(ua.chart_data, "chart", chart):
            st = (await self.c.get("/api/portfolio/stress", headers=h)).json()
            btc = next(x for x in st["senaryolar"] if x["senaryo"].startswith("BTC"))
            self.assertAlmostEqual(btc["kalemler"][0]["beta"], 2.0, delta=0.1)
            self.assertAlmostEqual(btc["portfoy_yuzde"], -40.0, delta=2)
            self.assertEqual(await ua.run_once(server.db), 0)                          # too early
            self.assertEqual(await ua.run_once(server.db, now=time.time() + 31 * 86400), 1)
        ev = (await self.c.get("/api/alarms", headers=h)).json()["olaylar"]
        self.assertIn("ETF onayı gelecek", ev[0]["metin"])

    async def test_position_stop_warning_once_per_level_and_limit(self):
        import unittest.mock as um
        h = auth("user_b")
        await self.c.post("/api/portfolio/positions", headers=h,
                          json={"piyasa": "KRIPTO", "kod": "ETH", "adet": 1, "maliyet": 100, "stop": 95})
        start = int(time.time()) - 2 * 86400 - 60
        # daily crypto candles: yesterday closed at 90 (< stop 95); today's is still forming
        with um.patch.object(server.user_alerts.chart_data, "chart", self._fake_chart([99, 90, 91], start, step=86400)):
            later = time.time() + 86400  # the 90 candle closed after the position was opened
            self.assertEqual(await server.user_alerts.run_once(server.db, now=later), 1)
            self.assertEqual(await server.user_alerts.run_once(server.db, now=later), 0)
            ev = (await self.c.get("/api/alarms", headers=h)).json()["olaylar"]
            self.assertIn("stopun", ev[0]["metin"])
            self.assertTrue(ev[0]["gonderildi"])  # no Telegram linked: shown in the panel only
            for i in range(server.user_alerts.MAX_ACTIVE):
                r = await self.c.post("/api/alarms", headers=h, json={"piyasa": "KRIPTO", "kod": "ETH", "seviye": 200 + i})
                self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual((await self.c.post("/api/alarms", headers=h, json={
                "piyasa": "KRIPTO", "kod": "ETH", "seviye": 999})).status_code, 400)


class TrendRuleTest(unittest.TestCase):
    """Donchian 20/10 with a 200-day filter, on closed daily candles only."""

    def _candles(self, closes, start=0):
        return [{"t": start + i * 86400, "c": c, "h": c * 1.01, "l": c * 0.99} for i, c in enumerate(closes)]

    def test_entry_hold_and_exit(self):
        import trend_rule
        base = [100.0] * 230
        up = base + [103, 106, 110]          # breaks the 20-day high and stays above the 200-day average
        sma = [100.0] * len(up)
        now = len(up) * 86400 + 60           # every candle closed
        st = trend_rule.state(self._candles(up), sma, now)
        self.assertTrue(st["trendde"])
        self.assertFalse(st["giris_bugun"])  # the entry was on the 103 candle
        down = up + [108, 104, 95]           # 95 < lowest low of the previous 10 days
        st2 = trend_rule.state(self._candles(down), [100.0] * len(down), len(down) * 86400 + 60)
        self.assertFalse(st2["trendde"])
        self.assertTrue(st2["cikis_bugun"])
        # the forming candle never counts: with "now" inside the last candle, 95 is ignored
        st3 = trend_rule.state(self._candles(down), [100.0] * len(down), (len(down) - 1) * 86400 + 60)
        self.assertTrue(st3["trendde"])
        # below the 200-day average a breakout is not an entry
        st4 = trend_rule.state(self._candles(up), [120.0] * len(up), now)
        self.assertFalse(st4["trendde"])


class InsightsTest(unittest.TestCase):
    def test_report_card_from_own_trades(self):
        import insights
        doc = {"positions": [
            {"id": "p1", "kod": "THYAO", "maliyet": 100, "acilis": "2026-09-01T10:00:00+00:00", "stop": 95},
            {"id": "p2", "kod": "BTC", "maliyet": 50000, "acilis": "2026-09-10T10:00:00+00:00", "stop": 48000}],
            "transactions": [
            {"tur": "satis", "pozisyon_id": "p1", "kod": "THYAO", "piyasa": "BIST", "para": "TL", "fiyat": 120, "kar": 200,
             "zaman": "2026-09-11T10:00:00+00:00"},
            {"tur": "satis", "pozisyon_id": "p2", "kod": "BTC", "piyasa": "KRIPTO", "para": "USD", "fiyat": 47000, "kar": -300,
             "zaman": "2026-09-12T10:00:00+00:00"}]}
        after_sale = 1790000000.0  # a close after both sales
        r = insights.report(doc, {"BIST:THYAO": (after_sale, 140.0)})
        self.assertIsNone(insights.report(doc, {"BIST:THYAO": (1757000000.0, 140.0)})["islemler"][1]["sonra_yuzde"])
        self.assertEqual((r["islem"], r["kazanan"], r["isabet_yuzde"]), (2, 1, 50))
        self.assertEqual(r["gerceklesen"], {"TL": 200.0, "USD": -300.0})
        self.assertEqual(r["stop_alti_satis"], 1)            # BTC sold below its stop
        self.assertEqual(r["erken_satis"], 1)                # THYAO went 16.7 % higher after the sale
        self.assertEqual(r["ort_gun_kazanan"], 10.0)

    def test_correlation(self):
        import insights
        day = 86400
        a = [(i * day, 100 + (i % 7) * 3 + i * 0.1) for i in range(120)]
        b = [(t, c * 2) for t, c in a]
        c = [(i * day, 100 + ((i * 5) % 11)) for i in range(120)]
        self.assertEqual(insights.correlation(a, b), 1.0)
        self.assertLess(abs(insights.correlation(a, c)), 0.8)
        self.assertIsNone(insights.correlation(a[:10], b[:10]))


class LastClosedTest(unittest.TestCase):
    def test_todays_forming_candle_never_counts(self):
        import chart_data
        day = 86400
        today = (int(time.time()) // day) * day
        bist = [{"t": today - day + 7 * 3600, "c": 1}, {"t": today + 7 * 3600, "c": 2}]
        # 12:00 UTC today: BIST session still open -> yesterday; 16:00 UTC -> today's close counts
        self.assertEqual(chart_data.last_closed(bist, "BIST", now=today + 12 * 3600)["c"], 1)
        self.assertEqual(chart_data.last_closed(bist, "BIST", now=today + 16 * 3600)["c"], 2)
        crypto = [{"t": today - day, "c": 1}, {"t": today, "c": 2}]
        self.assertEqual(chart_data.last_closed(crypto, "KRIPTO", now=today + 60)["c"], 1)
        self.assertIsNone(chart_data.last_closed([], "BIST"))


class ClerkAddressTest(unittest.TestCase):
    def test_issuer_and_jwks_come_from_the_publishable_key(self):
        pk = "pk_test_" + __import__("base64").b64encode(b"driven-panther-5032.clerk.accounts.dev$").decode()
        self.assertEqual(identity.frontend_api(pk), "https://driven-panther-5032.clerk.accounts.dev")
        for bad in ("", "pk_test_", "pk_test_!!!", "sk_test_" + __import__("base64").b64encode(b"evil.com/x$").decode()):
            self.assertEqual(identity.frontend_api(bad), "", bad)


if __name__ == "__main__":
    unittest.main()
