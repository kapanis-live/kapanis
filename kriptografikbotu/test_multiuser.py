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
        self.assertEqual(meta, {"user_id": "u1", "role": "user", "request_id": "r1", "telegram_chat_id": 42, "own_keys": None})


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
    """Any Telegram user can message the bot: voice needs a linked account and has an hourly budget."""

    def setUp(self):
        main._chat_hits.clear()
        self.replies = []

    def _update(self, chat_id):
        async def reply_text(text, **kw):
            self.replies.append(text)
        voice = types.SimpleNamespace(duration=5, file_size=1000)
        msg = types.SimpleNamespace(voice=voice, reply_text=reply_text, text="")
        return types.SimpleNamespace(effective_chat=types.SimpleNamespace(id=chat_id, type="private"), message=msg)

    async def test_unlinked_chat_is_refused_before_transcribing(self):
        with unittest.mock.patch.object(web_sync, "enabled", return_value=True),                 unittest.mock.patch.object(web_sync, "telegram_linked", unittest.mock.AsyncMock(return_value=False)),                 unittest.mock.patch.object(main.voice_quant, "transcribe") as tr:
            await main.quant_voice(self._update(555), types.SimpleNamespace(user_data={}))
        tr.assert_not_called()
        self.assertIn("bağla", self.replies[-1])

    async def test_linked_chat_gets_six_voice_messages_an_hour(self):
        with unittest.mock.patch.object(web_sync, "enabled", return_value=True),                 unittest.mock.patch.object(web_sync, "telegram_linked", unittest.mock.AsyncMock(return_value=True)):
            allowed = [main.chat_rate_ok(777, "voice", 6, 3600) for _ in range(6)]
            self.assertTrue(all(allowed))
            await main.quant_voice(self._update(777), types.SimpleNamespace(user_data={}))
        self.assertIn("Saatte en fazla 6", self.replies[-1])

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


if __name__ == "__main__":
    unittest.main()
