"""Multi-user acceptance tests against a real local MongoDB (separate test database, dropped after).

Clerk is simulated: tokens are signed with a throwaway RSA key and the Clerk profile lookup is patched,
so the backend code path (RS256 signature, expiry, issuer, azp, verified e-mail) is the real one.
Run: .venv\\Scripts\\python -m unittest tests.test_multiuser -v
"""
import os
import sys
import time
import unittest
from pathlib import Path

os.environ.update({
    "MONGO_URL": os.environ.get("TEST_MONGO_URL", "mongodb://127.0.0.1:27017"), "DB_NAME": "kapanis_test_multiuser",
    "JWT_SECRET": "test-secret-not-real", "BOT_API_KEY": "test-bot-key", "ADMIN_EMAIL": "owner@example.com",
    "ADMIN_PASSWORD": "owner-test-password", "OWNER_EMAIL": "owner@example.com", "AUTH_MODE": "both",
    "CLERK_JWKS_URL": "https://clerk.test.invalid/.well-known/jwks.json", "CLERK_SECRET_KEY": "sk_test_dummy",
    "CLERK_ISSUER": "https://clerk.test.invalid", "CLERK_AUTHORIZED_PARTIES": "https://kapanis.test",
    "CLERK_PUBLISHABLE_KEY": "pk_test_dummy", "USER_DAILY_ANALYSES": "3",
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


if __name__ == "__main__":
    unittest.main()
