"""Multi-user safety on the bot side. No network, no real model, temporary data folder.
Run with: python -m unittest test_multiuser"""
import os
import pathlib
import tempfile
import types
import unittest
import unittest.mock

_TMP = tempfile.mkdtemp()
os.environ["DATA_DIR"] = _TMP

import config  # noqa: E402
import conversation_store as store  # noqa: E402
import llm  # noqa: E402
import main  # noqa: E402
import positions  # noqa: E402
import web_sync  # noqa: E402

OWNER_CHAT = 1000
config.ALLOWED_CHAT_ID = OWNER_CHAT


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat, text, **kw):
        self.sent.append((chat, text))
        return types.SimpleNamespace(delete=self._noop, edit_text=self._noop)

    async def _noop(self, *a, **k):
        pass


def fake_openai(captured):
    async def create(model, messages, max_tokens):
        captured.append(messages)
        msg = types.SimpleNamespace(content="Analiz metni.\n<STATE>{\"planlar\": {\"BTC\": {\"tetik\": 1, \"iptal\": 0.5}}}</STATE>")
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg)], usage=None)
    return types.SimpleNamespace(chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=create)))


class CommandPermissionTest(unittest.TestCase):
    def test_other_users_may_only_request_analysis(self):
        self.assertTrue(web_sync.allowed({"type": "position.close", "role": "owner"}))
        self.assertTrue(web_sync.allowed({"type": "position.close"}))  # queued before accounts existed
        self.assertTrue(web_sync.allowed({"type": "analysis.request", "role": "user"}))
        for t in ("position.close", "alert.create", "plan.add", "target.set", "paper.open", "check.request", "decision.action"):
            self.assertFalse(web_sync.allowed({"type": t, "role": "user"}), t)

    def test_command_meta_only_carries_identity(self):
        meta = web_sync.command_meta({"id": "c1", "type": "analysis.request", "payload": {"x": 1}, "user_id": "u1",
                                      "role": "user", "request_id": "r1", "telegram_chat_id": 42})
        self.assertEqual(meta, {"user_id": "u1", "role": "user", "request_id": "r1", "telegram_chat_id": 42, "own_keys": None, "dil": None})


class AccountUsBookTest(unittest.IsolatedAsyncioTestCase):
    """The US book analysis for a site account: its own holdings, its own result document."""

    def test_any_account_may_ask(self):
        self.assertTrue(web_sync.allowed({"type": "us.portfolio", "role": "user"}))

    def test_holdings_from_outside_are_cleaned(self):
        import us_portfolio
        raw = {"nvda": 2, "AAPL": "3.5", "MSFT": 0, "BAD TICKER": 1, "X" * 20: 1, "AMD": float("nan"), "TSLA": -1, "GOOG": "abc"}
        self.assertEqual(us_portfolio.clean_holdings(raw), {"NVDA": 2.0, "AAPL": 3.5})
        self.assertEqual(us_portfolio.clean_holdings(None), {})
        self.assertEqual(us_portfolio.clean_holdings(["NVDA"]), {})
        with self.assertRaises(ValueError):
            us_portfolio.clean_holdings({f"A{i}": 1 for i in range(us_portfolio.MAX_HOLDINGS + 1)})

    async def test_result_is_stored_under_the_account(self):
        import us_portfolio
        seen = []

        async def fake_report(holdings=None):
            seen.append(holdings)
            return {"toplam_usd": 1000.0, "agirlik_yuzde": {"NVDA": 100.0}}
        with unittest.mock.patch.object(us_portfolio, "report", fake_report):
            doc, reply = await us_portfolio.account_report({"NVDA": 2}, {"user_id": "u1", "role": "user"}, "2026-10-10T10:00:00+03:00", "https://x/app/saglik")
            self.assertEqual(seen, [{"NVDA": 2.0}])                       # the account's holdings, never the bot's own portfolio
            self.assertEqual((doc["id"], doc["user_id"], doc["bos"], doc["toplam_usd"]), ("abd_portfoy:u1", "u1", False, 1000.0))
            self.assertIn("hazır", reply)
            # English account
            self.assertIn("is ready", (await us_portfolio.account_report({"NVDA": 2}, {"user_id": "u1", "dil": "en"}, "t", "u"))[1])
            # nothing to analyse: an empty result, the bot's portfolio is not used instead
            doc, reply = await us_portfolio.account_report({}, {"user_id": "u2"}, "t", "u")
            self.assertEqual((doc["id"], doc["bos"]), ("abd_portfoy:u2", True))
            self.assertEqual(len(seen), 2)
            # no verified account: nothing is written
            self.assertIsNone((await us_portfolio.account_report({"NVDA": 1}, {}, "t", "u"))[0])

        async def boom(holdings=None):
            raise RuntimeError("endeks / faiz / VIX verisi alınamadı")
        with unittest.mock.patch.object(us_portfolio, "report", boom):
            doc, reply = await us_portfolio.account_report({"NVDA": 2}, {"user_id": "u1"}, "t", "u")
            self.assertEqual((doc["id"], doc["hata"]), ("abd_portfoy:u1", "endeks / faiz / VIX verisi alınamadı"))


class AccountResultsTest(unittest.IsolatedAsyncioTestCase):
    """Stock card and monthly report for a site account: asked by any account, stored under that account only."""

    def test_any_account_may_ask_and_gets_its_own_document(self):
        for t in ("fundamentals.request", "monthly.request", "us.portfolio"):
            self.assertTrue(web_sync.allowed({"type": t, "role": "user"}), t)
        self.assertIsNone(web_sync.account_doc_id("temel", {"role": "owner", "user_id": "o1"}))        # the owner's plain document
        self.assertIsNone(web_sync.account_doc_id("temel", {}))                                         # commands from before accounts
        self.assertEqual(web_sync.account_doc_id("temel", {"role": "user", "user_id": "u1"}), "temel:u1")
        self.assertNotEqual(web_sync.account_doc_id("temel", {"role": "user"}), "temel")                # never the owner's document

    async def test_an_accounts_watchlist_rows_are_its_own(self):
        import watchlist
        self.assertTrue(web_sync.allowed({"type": "watch.request", "role": "user"}))
        raw = {"KRIPTO": ["btc", "BTC", "bad code", 7], "BIST": ["THYAO"], "ABD": "NVDA", "FX": ["EURUSD"]}
        self.assertEqual(watchlist.clean_lists(raw), {"KRIPTO": ["BTC", "7"], "BIST": ["THYAO"], "ABD": []})
        self.assertEqual(watchlist.clean_lists(None), {"KRIPTO": [], "BIST": [], "ABD": []})
        self.assertEqual(sum(len(v) for v in watchlist.clean_lists({"ABD": [f"A{i}" for i in range(100)]}).values()), watchlist.MAX_ACCOUNT_CODES)
        asked = []

        async def fake_rows(mkt, codes):
            asked.append((mkt, list(codes)))
            if mkt == "KRIPTO" and len(codes) > 1:      # one unknown code fails the bulk request
                raise RuntimeError("400")
            if codes == ["NOPE"]:
                raise RuntimeError("no such symbol")
            return [{"kod": c, "fiyat": 1.0} for c in codes]
        with unittest.mock.patch.object(watchlist, "rows", fake_rows):
            self.assertIsNone(await watchlist.account_rows({"BIST": ["THYAO"]}, {}))                # no account, no document
            doc = await watchlist.account_rows({"KRIPTO": ["BTC", "NOPE"], "BIST": ["THYAO"]}, {"user_id": "u1", "role": "user"})
        self.assertEqual((doc["id"], doc["tur"], doc["user_id"]), ("takip:u1", "takip", "u1"))
        self.assertEqual([(r["kod"], "hata" in r) for r in doc["piyasalar"]["KRIPTO"]], [("BTC", False), ("NOPE", True)])
        self.assertEqual((doc["piyasalar"]["BIST"][0]["kod"], doc["piyasalar"]["ABD"]), ("THYAO", []))
        self.assertNotIn(("ABD", []), asked)                                                        # an empty market asks nothing

    def test_account_positions_are_cleaned_and_shaped(self):
        import monthly
        raw = [{"piyasa": "BIST", "kod": "thyao", "adet": 10, "maliyet": 290, "acilis": "2026-08-20T10:00:00+03:00", "durum": "acik"},
               {"piyasa": "ABD", "kod": "NVDA", "adet": 2, "maliyet": 120, "acilis": "2026-09-05T10:00:00+03:00", "durum": "kapali",
                "kapanis_fiyat": 131, "kapanis": "2026-09-20T10:00:00+03:00"},
               {"piyasa": "KRIPTO", "kod": "BTC", "adet": 0.01, "maliyet": 84000, "acilis": "2026-09-01T10:00:00+03:00", "durum": "acik"},
               {"piyasa": "DIGER", "kod": "ALTIN", "adet": 1, "maliyet": 1, "durum": "acik"},            # not a market of the report
               {"piyasa": "BIST", "kod": "BAD CODE", "adet": 1, "maliyet": 1, "durum": "acik"},
               {"piyasa": "BIST", "kod": "ASELS", "adet": -1, "maliyet": 60, "durum": "acik"},
               {"piyasa": "BIST", "kod": "ASELS", "adet": "x", "maliyet": 60, "durum": "acik"}, "junk", None]
        items = monthly.account_items(raw)
        self.assertEqual([(p["symbol"], p["pair"], p["piyasa"], p["durum"], p["giris"]) for p in items],
                         [("THYAO.IS", "THYAO", "BIST", "acik", 290.0), ("NVDA.US", "NVDA", "ABD", "kapali", 120.0), ("BTCUSDT", "BTC/USDT", "KRIPTO", "acik", 84000.0)])
        self.assertEqual((items[1]["kapanis_fiyat"], items[1]["kapanis_zamani"][:10]), (131.0, "2026-09-20"))
        self.assertEqual(monthly.account_items({"not": "a list"}), [])
        self.assertEqual(len(monthly.account_items([raw[0]] * 1000)), monthly.MAX_ACCOUNT_POSITIONS)

    async def test_monthly_report_is_built_from_the_accounts_positions(self):
        import monthly
        seen = []

        async def fake_build(month=None, items=None):
            seen.append((month, items))
            return {"ay": month, "ad": "Eylül 2026", "varlik": len(items), "uretildi": "2026-10-10T10:00:00+03:00", "bas_gun": "2026-08-31", "son_gun": "2026-09-30",
                    "getiri": {"tl_yuzde": 4.2, "usd_yuzde": 1.1, "kazanc_tl": 120.0, "kazanc_usd": 3.0, "izlenen_tl": 2900.0},
                    "kiyas": {"BIST 100": 2.0}, "usdtry_yuzde": 3.0, "en_iyi": [], "en_kotu": [],
                    "islemler": {"alim": 0, "satim": 0, "gerceklesen": {}, "alinan": [], "satilan": []},
                    "yogunlasma": {"ay_basi": None, "ay_sonu": None}, "hesaplanamayan": [], "kaynaklar": []}
        raw = [{"piyasa": "BIST", "kod": "THYAO", "adet": 10, "maliyet": 290, "acilis": "2026-08-20T10:00:00+03:00", "durum": "acik"}]
        with unittest.mock.patch.object(monthly, "build", fake_build):
            doc, reply = await monthly.account_report(raw, {"user_id": "u1", "role": "user"}, "2026-09")
            self.assertEqual((doc["id"], doc["user_id"], doc["tur"], doc["ay"], doc["bos"]), ("aylik:u1:2026-09", "u1", "aylik", "2026-09", False))
            self.assertEqual(seen[0][0], "2026-09")
            self.assertEqual(seen[0][1][0]["symbol"], "THYAO.IS")                       # the account's positions, not the bot's record
            self.assertIn("Eylül 2026", reply)
            self.assertIn("September 2026", (await monthly.account_report(raw, {"user_id": "u1", "dil": "en"}, "2026-09"))[1])
            # a bad month falls back to the month that just ended; no positions = an empty document; no account = nothing written
            self.assertRegex((await monthly.account_report(raw, {"user_id": "u1"}, "../etc"))[0]["ay"], "^20[0-9][0-9]-[0-9][0-9]$")
            doc, _ = await monthly.account_report([], {"user_id": "u2"}, "2026-09")
            self.assertEqual((doc["id"], doc["bos"]), ("aylik:u2:2026-09", True))
            self.assertIsNone((await monthly.account_report(raw, {}, "2026-09"))[0])


class PersonalContextTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        store.save_state({"planlar": {"ETH": {"tetik": 3000, "iptal": 2900}}})
        store.clear_history()
        positions.open_position("ETH/USDT", 3000, 50, 2900, 3300)
        self.captured = []
        self.patches = [unittest.mock.patch.object(llm, "_client", lambda m: fake_openai(self.captured)),
                        unittest.mock.patch.object(llm, "pick_model", lambda *a: ["deepseek"]),
                        unittest.mock.patch.object(llm.macro, "summary", unittest.mock.AsyncMock(return_value={})),
                        unittest.mock.patch.object(llm.news, "get_news", unittest.mock.AsyncMock(return_value=[]))]
        for p in self.patches:
            p.start()

    async def asyncTearDown(self):
        for p in self.patches:
            p.stop()

    async def test_other_user_prompt_has_no_owner_data_and_writes_nothing(self):
        await llm.analyze("BTC analiz et.", {"BTC": {}}, personal=False)
        prompt = str(self.captured[-1])
        self.assertNotIn("ETH/USDT", prompt)       # owner's open position
        self.assertNotIn("3000", prompt)           # owner's plan level
        self.assertEqual(store.load_history(), [])   # owner's conversation untouched
        self.assertNotIn("BTC", store.load_state()["planlar"])  # the reply's STATE block was ignored

    async def test_owner_prompt_keeps_personal_context(self):
        await llm.analyze("BTC analiz et.", {"BTC": {}})
        prompt = str(self.captured[-1])
        self.assertIn("ETH/USDT", prompt)
        self.assertEqual(len(store.load_history()), 2)


class PanelAnalysisRoutingTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.calls, self.pushed = [], []

        async def run(bot, chat, text, coins, **kw):
            self.calls.append((chat, kw))
            return "cevap"

        async def push(col, docs, replace=False):
            self.pushed += docs
        self.patches = [unittest.mock.patch.object(main, "run_analysis", run),
                        unittest.mock.patch.object(web_sync, "push_docs", push),
                        unittest.mock.patch.object(web_sync, "enabled", lambda: True)]
        for p in self.patches:
            p.start()

    async def asyncTearDown(self):
        for p in self.patches:
            p.stop()

    async def test_linked_user_gets_telegram_unlinked_site_only_owner_personal(self):
        bot = FakeBot()
        await main.panel_analysis(bot, "KRIPTO", ["BTC"], {"user_id": "u1", "role": "user", "request_id": "r1", "telegram_chat_id": 55})
        await main.panel_analysis(bot, "KRIPTO", ["BTC"], {"user_id": "u2", "role": "user", "request_id": "r2", "telegram_chat_id": None})
        await main.panel_analysis(bot, "KRIPTO", ["BTC"], {"user_id": "o", "role": "owner", "request_id": "r3"})
        await main.panel_analysis(bot, "KRIPTO", ["BTC"])  # legacy call without a command
        chats = [c for c, _ in self.calls]
        self.assertEqual(chats, [55, None, OWNER_CHAT, OWNER_CHAT])
        self.assertEqual([kw.get("personal", True) for _, kw in self.calls], [False, False, True, True])
        # users get only a web link to their own analysis, never the owner's plan / "Aldım" buttons
        for _, kw in self.calls[:2]:
            markup = kw["buttons"]("cevap", ["BTC"]) if kw.get("buttons") else None
            buttons = [b for row in (markup.inline_keyboard if markup else []) for b in row]
            self.assertTrue(all(b.url and "/app/analizlerim?id=" in b.url and not b.callback_data for b in buttons))
        self.assertEqual([d.get("user_id") for d in self.pushed], ["u1", "u2", "o", None])
        self.assertEqual(len({d["id"] for d in self.pushed}), 4)

    async def test_site_language_travels_with_the_request(self):
        """An account that chose English on the site: the analysis is asked for in English, linked chat or not."""
        bot = FakeBot()
        await main.panel_analysis(bot, "KRIPTO", ["BTC"], {"user_id": "u1", "role": "user", "request_id": "r1", "telegram_chat_id": None, "dil": "en"})
        await main.panel_analysis(bot, "KRIPTO", ["BTC"], {"user_id": "u2", "role": "user", "request_id": "r2", "telegram_chat_id": 55, "dil": None})
        self.assertEqual([kw.get("language") for _, kw in self.calls], ["en", None])
        self.assertEqual(web_sync.command_meta({"dil": "en", "role": "user"})["dil"], "en")

    async def test_notify_goes_to_the_right_chat(self):
        bot = FakeBot()
        ctx = types.SimpleNamespace(bot=bot)
        captured = {}

        async def process(refresh, notify):
            await notify("owner msg", {"role": "owner"})
            await notify("user linked", {"role": "user", "telegram_chat_id": 77})
            await notify("user unlinked", {"role": "user", "telegram_chat_id": None})
            captured["done"] = True
            return 0
        with unittest.mock.patch.object(web_sync, "process_commands", process), \
                unittest.mock.patch.object(main, "engine", types.SimpleNamespace(refresh=lambda: None), create=True):
            await main.web_command_job(ctx)
        self.assertTrue(captured["done"])
        self.assertEqual(bot.sent, [(OWNER_CHAT, "owner msg"), (77, "user linked")])


class OwnKeysBotTest(unittest.IsolatedAsyncioTestCase):
    async def test_user_key_is_used_and_not_billed_to_owner(self):
        used_keys, recorded = [], []

        def user_client(model, keys):
            used_keys.append((model, keys.get("deepseek")))
            return fake_openai([])
        with unittest.mock.patch.object(llm, "_user_client", user_client), \
                unittest.mock.patch.object(llm, "_client", lambda m: self.fail("owner client used")), \
                unittest.mock.patch.object(llm, "mode", lambda: "deepseek"), \
                unittest.mock.patch.object(llm.costs, "record", lambda *a, **k: recorded.append(a)), \
                unittest.mock.patch.object(llm.macro, "summary", unittest.mock.AsyncMock(return_value={})), \
                unittest.mock.patch.object(llm.news, "get_news", unittest.mock.AsyncMock(return_value=[])):
            reply, _, _ = await llm.analyze("BTC analiz et.", {"BTC": {}}, personal=False, keys={"deepseek": "sk-user"})
        self.assertEqual(used_keys, [("deepseek", "sk-user")])
        self.assertEqual(recorded, [])
        self.assertIn("senin anahtarınla", reply)

    async def test_missing_user_key_leaves_a_note_in_the_panel(self):
        pushed, ran = [], []

        async def push(col, docs, replace=False):
            pushed.extend(docs)

        async def run(*a, **k):
            ran.append(k)
            return "cevap"
        with unittest.mock.patch.object(web_sync, "user_keys", unittest.mock.AsyncMock(return_value=None)), \
                unittest.mock.patch.object(web_sync, "push_docs", push), \
                unittest.mock.patch.object(web_sync, "enabled", lambda: True), \
                unittest.mock.patch.object(main, "run_analysis", run):
            await main.panel_analysis(FakeBot(), "KRIPTO", ["BTC"], {"user_id": "u9", "role": "user", "request_id": "r9",
                                                                     "own_keys": True})
            self.assertEqual(ran, [])  # never falls back to the owner's paid keys
            self.assertIn("API anahtarın", pushed[0]["metin"])
            with unittest.mock.patch.object(web_sync, "user_keys", unittest.mock.AsyncMock(return_value={"nvidia": "nv"})):
                await main.panel_analysis(FakeBot(), "KRIPTO", ["BTC"], {"user_id": "u9", "role": "user", "request_id": "r10",
                                                                         "own_keys": True})
            self.assertEqual(ran[0]["keys"], {"nvidia": "nv"})


class StrategyExplainTest(unittest.TestCase):
    def test_eliminated_counts_each_rule_and_missing_fk_fails(self):
        import quant_scan
        data = {"excluded": 7, "rows": [
            {"kod": "A", "fk": 5, "kalite": 80, "momentum_goreli": 3},
            {"kod": "B", "fk": None, "kalite": 90, "momentum_goreli": -5},
            {"kod": "C", "fk": 15, "kalite": 60, "momentum_goreli": 10}]}
        rules = {"fk_max": 10, "momentum_min": 0, "quality_min": 70}
        self.assertEqual(quant_scan.eliminated(data, rules), {"veri_eksik": 7, "fk": 2, "momentum": 1, "kalite": 1})
        self.assertEqual([r["kod"] for r in quant_scan.rank(data, rules)], ["A"])


class CloudStateTest(unittest.TestCase):
    """data/ survives a wiped disk: needs a local MongoDB, skipped without one."""

    def test_sync_then_restore_on_empty_disk(self):
        import importlib
        import cloud_store
        try:
            from pymongo import MongoClient
            MongoClient("mongodb://127.0.0.1:27017", serverSelectionTimeoutMS=1500).admin.command("ping")
        except Exception:
            self.skipTest("no local MongoDB")
        os.environ["STATE_MONGO_URL"], os.environ["STATE_DB_NAME"] = "mongodb://127.0.0.1:27017", "kapanis_test_cloudstate"
        cs = importlib.reload(cloud_store)
        try:
            cs._collection().delete_many({})
            (config.DATA_DIR / "bulut_test.json").write_text('[{"id": 1, "pair": "THYAO.IS"}]', encoding="utf-8")
            (config.DATA_DIR / "bulut_test.jsonl").write_text('{"a": 1}\n', encoding="utf-8")
            (config.DATA_DIR / "ornek.log").write_text("token-like secret line", encoding="utf-8")
            self.assertGreaterEqual(cs.sync(), 2)
            self.assertEqual(cs.sync(), 0)  # nothing changed
            names = {d["name"] for d in cs._collection().find({}, {"name": 1})}
            self.assertNotIn("ornek.log", names)  # logs never leave the machine
            for f in ("bulut_test.json", "bulut_test.jsonl"):
                (config.DATA_DIR / f).unlink()
            self.assertGreaterEqual(cs.restore(), 2)
            self.assertIn("THYAO.IS", (config.DATA_DIR / "bulut_test.json").read_text(encoding="utf-8"))
            cs._collection().insert_one({"name": "../evil.json", "content": "x"})
            cs.restore()
            self.assertFalse((config.DATA_DIR.parent / "evil.json").exists())  # no path escape
        finally:
            for f in ("bulut_test.json", "bulut_test.jsonl", "ornek.log"):
                (config.DATA_DIR / f).unlink(missing_ok=True)
            cs._collection().database.client.drop_database("kapanis_test_cloudstate")
            cs._collection().database.client.close()
            os.environ.pop("STATE_MONGO_URL", None)
            importlib.reload(cloud_store)


class PublicChatLimitTest(unittest.IsolatedAsyncioTestCase):
    """Any Telegram user can message the bot: public commands have a per-chat budget."""

    def setUp(self):
        main._chat_hits.clear()
        self.replies = []

    def _update(self, chat_id):
        async def reply_text(text, **kw):
            self.replies.append(text)
        voice = types.SimpleNamespace(duration=5, file_size=1000)
        msg = types.SimpleNamespace(voice=voice, reply_text=reply_text, text="")
        return types.SimpleNamespace(effective_chat=types.SimpleNamespace(id=chat_id, type="private"), message=msg)

    def test_owner_chat_is_never_limited(self):
        self.assertTrue(all(main.chat_rate_ok(OWNER_CHAT, "public", 1, 600) for _ in range(5)))
        self.assertTrue(main.chat_rate_ok(888, "public", 1, 600))
        self.assertFalse(main.chat_rate_ok(888, "public", 1, 600))


class BackupTest(unittest.TestCase):
    """Daily dump of every collection and its restore: needs a local MongoDB, skipped without one."""

    def test_dump_prune_and_restore_into_new_database(self):
        import importlib
        import sys
        import cloud_store
        import db_backup
        try:
            from pymongo import MongoClient
            client = MongoClient("mongodb://127.0.0.1:27017", serverSelectionTimeoutMS=1500)
            client.admin.command("ping")
        except Exception:
            self.skipTest("no local MongoDB")
        src, dst = "kapanis_test_backup", "kapanis_test_backup_geri"
        os.environ["STATE_MONGO_URL"], os.environ["STATE_DB_NAME"] = "mongodb://127.0.0.1:27017", src
        folder = tempfile.mkdtemp()
        os.environ["BACKUP_DIR"], os.environ["BACKUP_KEEP"] = folder, "2"
        importlib.reload(cloud_store)
        bk = importlib.reload(db_backup)
        try:
            from datetime import datetime, timezone
            client[src].users.insert_many([{"id": "u1", "email": "a@example.com", "created": datetime(2026, 1, 2, tzinfo=timezone.utc)},
                                           {"id": "u2", "email": "b@example.com"}])
            client[src].portfolios.insert_one({"user_id": "u1", "rev": 3, "positions": [{"kod": "THYAO", "adet": 10.5}]})
            for day in (1, 2, 3):
                path, counts = bk.run(datetime(2026, 9, day, 3, 30, tzinfo=timezone.utc))
            self.assertEqual(counts, {"portfolios": 1, "users": 2})
            self.assertEqual(len(list(pathlib.Path(folder).glob("kapanis-*.jsonl.gz"))), 2)  # BACKUP_KEEP
            rows = list(bk.read(path))
            self.assertIsInstance(next(d for c, d in rows if c == "users" and d["id"] == "u1")["created"], datetime)

            sys.path.insert(0, str(pathlib.Path(__file__).parent / "scripts"))
            import restore_backup
            with unittest.mock.patch.object(sys, "argv", ["x", str(path)]):
                self.assertEqual(restore_backup.main(), 0)  # dry run
            self.assertEqual(client[dst].users.count_documents({}), 0)
            with unittest.mock.patch.object(sys, "argv", ["x", str(path), "--yes", "--db", dst]):
                restore_backup.main()
            self.assertEqual(client[dst].users.count_documents({}), 2)
            self.assertEqual(client[dst].portfolios.find_one()["positions"][0]["adet"], 10.5)
            client[dst].users.delete_one({"id": "u2"})
            with unittest.mock.patch.object(sys, "argv", ["x", str(path), "--yes", "--db", dst]):
                restore_backup.main()  # non-empty collection: skipped, never mixed
            self.assertEqual(client[dst].users.count_documents({}), 1)
        finally:
            client.drop_database(src)
            client.drop_database(dst)
            client.close()
            for k in ("STATE_MONGO_URL", "BACKUP_DIR", "BACKUP_KEEP"):
                os.environ.pop(k, None)
            importlib.reload(cloud_store)
            importlib.reload(db_backup)


class UserAlarmDeliveryTest(unittest.IsolatedAsyncioTestCase):
    async def test_events_go_to_their_own_chat_with_a_chart_link_and_are_marked_sent(self):
        sent, marked = [], []

        class Bot:
            async def send_message(self, chat, text, **kw):
                if chat == 999:
                    raise main.BadRequest("Chat not found")
                sent.append((chat, text, kw["reply_markup"].inline_keyboard[0][0].url))

        events = [{"id": "e1", "chat_id": 4242, "kod": "BTC", "piyasa": "KRIPTO", "metin": "🔔 Alarmın: BTC"},
                  {"id": "e2", "chat_id": 999, "kod": "THYAO", "piyasa": "BIST", "metin": "🔴 THYAO stop"},
                  {"id": "e3", "chat_id": None, "sahip": True, "kod": "", "piyasa": "", "metin": "📅 Haftalık özet"}]

        async def mark(eid):
            marked.append(eid)
        with unittest.mock.patch.object(web_sync, "alarm_events", unittest.mock.AsyncMock(return_value=events)),                 unittest.mock.patch.object(web_sync, "alarm_event_sent", mark):
            await main.user_alarm_job(types.SimpleNamespace(bot=Bot()))
        self.assertEqual([(c, u.endswith("kod=BTC&piyasa=KRIPTO")) for c, _, u in sent][0], (4242, True))
        self.assertEqual((sent[1][0], sent[1][2].endswith("/app/portfoyum")), (OWNER_CHAT, True))  # owner: bot's own chat
        self.assertEqual(marked, ["e1", "e2", "e3"])  # a chat that is gone is not retried forever


class AnalysisLanguageTest(unittest.IsolatedAsyncioTestCase):
    async def test_english_reader_gets_an_english_request(self):
        """run_analysis adds the language note for an English reader and leaves a Turkish request untouched."""
        asked = []

        async def analyze(user_text, data, **kw):
            asked.append(user_text)
            return "answer", [], []
        with unittest.mock.patch.object(main.llm, "analyze", analyze):
            self.assertEqual(await main.run_analysis(FakeBot(), None, "BTC analiz et.", [], data={}, language="en"), "answer")
            await main.run_analysis(FakeBot(), None, "BTC analiz et.", [], data={})
        self.assertTrue(asked[0].endswith(main.ENGLISH_NOTE))
        self.assertEqual(asked[1], "BTC analiz et.")


if __name__ == "__main__":
    unittest.main()
