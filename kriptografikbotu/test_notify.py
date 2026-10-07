"""Per-market notification switches. Run: python -m unittest test_notify"""
import os
import tempfile
import types
import unittest
import unittest.mock
from unittest.mock import AsyncMock

os.environ["DATA_DIR"] = tempfile.mkdtemp()

import alerts_store  # noqa: E402
import config  # noqa: E402
import main  # noqa: E402
import notify_prefs as np_  # noqa: E402

OWNER = 111


class Base(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        s = alerts_store.load_settings()
        s.pop(np_.KEY, None)
        alerts_store.save_settings(s)
        np_.suppressed_log.clear()
        self.sent = []
        self.owner = unittest.mock.patch.object(config, "ALLOWED_CHAT_ID", OWNER)
        self.owner.start()
        self.addCleanup(self.owner.stop)
        self.quiet = unittest.mock.patch.object(main.quiet, "muted", return_value=False)
        self.quiet.start()
        self.addCleanup(self.quiet.stop)

        async def fake_send(method, *args, **kwargs):          # what would have reached Telegram
            self.sent.append(kwargs.get("text", args[1] if len(args) > 1 else kwargs.get("caption")))
            return types.SimpleNamespace(message_id=1)
        self.wire = unittest.mock.patch.object(main, "_retry_send", fake_send)
        self.wire.start()
        self.addCleanup(self.wire.stop)
        self.bot = main.RetryBot("123:TEST")

    async def proactive(self, market, text="x"):
        """A scheduled job of one market sending one message."""
        @np_.scoped(market)
        async def job():
            return await self.bot.send_message(OWNER, text)
        return await job()


class GateTest(Base):
    async def test_defaults_and_independent_switches(self):
        self.assertEqual(np_.prefs(OWNER), {"KRIPTO": False, "BIST": True, "ABD": True})          # the owner's defaults
        self.assertEqual(np_.prefs(999), {"KRIPTO": True, "BIST": True, "ABD": True})             # a site user's chat
        np_.set_enabled(OWNER, "ABD", False)
        self.assertEqual(np_.prefs(OWNER), {"KRIPTO": False, "BIST": True, "ABD": False})         # 11: BIST untouched
        np_.set_enabled(OWNER, "KRIPTO", True)
        self.assertEqual(np_.prefs(OWNER), {"KRIPTO": True, "BIST": True, "ABD": False})
        self.assertEqual(np_.prefs(999)["ABD"], True)                                             # per chat

    async def test_scheduled_messages_follow_the_switch_of_their_market(self):
        held = await self.proactive("KRIPTO", "BTC alarmı")                                       # 1: crypto off
        self.assertIsInstance(held, main.HeldMessage)
        await self.proactive("BIST", "THYAO")                                                     # 3
        await self.proactive("ABD", "NVDA")                                                       # 4
        self.assertEqual(self.sent, ["THYAO", "NVDA"])
        self.assertEqual(np_.suppressed_log[-1]["market"], "KRIPTO")
        self.assertEqual(np_.suppressed_log[-1]["reason"], "user_preference")
        await self.bot.send_message(OWNER, "makro brif")                                          # no market: always passes
        self.assertEqual(self.sent[-1], "makro brif")

    async def test_manual_commands_are_answered_while_the_market_is_off(self):
        token = main.USER_TURN.set(True)                                                          # 2: the user typed /danis BTC
        try:
            with np_.scope("KRIPTO"):
                await self.bot.send_message(OWNER, "BTC raporu")
        finally:
            main.USER_TURN.reset(token)
        self.assertEqual(self.sent, ["BTC raporu"])

    async def test_tagged_text_and_photo_are_gated_too(self):
        await self.bot.send_message(OWNER, np_.tag("RSI alarmı SOL", "KRIPTO"))
        await self.bot.send_message(OWNER, np_.tag("RSI alarmı NVDA", "ABD"))
        with np_.scope("KRIPTO"):
            await self.bot.send_photo(OWNER, b"png", caption="BTC grafiği")
        self.assertEqual(self.sent, ["RSI alarmı NVDA"])

    async def test_nothing_suppressed_is_sent_after_switching_back_on(self):
        await self.proactive("KRIPTO", "eski")                                                    # 10
        np_.set_enabled(OWNER, "KRIPTO", True)
        with unittest.mock.patch.object(main.quiet, "take_held", return_value=[]):
            await main.send_held(self.bot)                                                        # the quiet-mode queue stays empty
        await self.proactive("KRIPTO", "yeni")
        self.assertEqual(self.sent, ["yeni"])

    async def test_preferences_survive_a_restart(self):
        np_.set_enabled(OWNER, "BIST", False)                                                     # 8: stored in settings.json,
        raw = config.SETTINGS_FILE.read_text(encoding="utf-8")                                    # which cloud_store keeps in MongoDB
        self.assertIn(np_.KEY, raw)
        import importlib
        fresh = importlib.reload(np_)
        self.assertEqual(fresh.prefs(OWNER), {"KRIPTO": False, "BIST": False, "ABD": True})

    async def test_alarms_of_a_closed_market_are_kept(self):
        import tools                                                                              # 9
        rows = [{"id": 1, "piyasa": "KRIPTO", "kod": "BTC", "tf": "1h", "durum": "aktif", "gosterge": "rsi", "yon": "alti", "deger": 30}]
        alerts_store._save(tools.IND_ALERTS, rows)
        await self.proactive("KRIPTO", "tetik")
        self.assertEqual(self.sent, [])
        self.assertEqual(tools.ind_alerts(), rows)                                                # still saved, still active


class CommandTest(Base):
    def update(self):
        return types.SimpleNamespace(effective_chat=types.SimpleNamespace(id=OWNER, type="private"),
                                     message=types.SimpleNamespace(reply_text=AsyncMock()))

    async def run_cmd(self, handler, *args):
        u = self.update()
        await handler(u, types.SimpleNamespace(args=list(args), bot=self.bot, user_data={}))
        return u.message.reply_text

    async def test_the_flow_from_the_request(self):
        said = lambda mock: mock.await_args.args[0]
        self.assertIn("🪙 Kripto: KAPALI\n🇹🇷 BIST: AÇIK\n🇺🇸 ABD: AÇIK", said(await self.run_cmd(main.bildirimler_cmd)))
        self.assertIn("🪙 Kripto: AÇIK", said(await self.run_cmd(main.kripto_cmd, "aç")))            # 5 (with and without ç)
        self.assertIn("🪙 Kripto: KAPALI", said(await self.run_cmd(main.kripto_cmd, "kapat")))       # 6
        self.assertIn("🇺🇸 ABD: KAPALI", said(await self.run_cmd(main.abd, "kapat")))
        self.assertIn("🇺🇸 ABD: AÇIK", said(await self.run_cmd(main.abd, "ac")))
        self.assertIn("🇹🇷 BIST: KAPALI", said(await self.run_cmd(main.bist_cmd, "kapa")))
        self.assertIn("🇹🇷 BIST: AÇIK", said(await self.run_cmd(main.bist_cmd, "ac")))
        self.assertEqual(np_.prefs(OWNER), {"KRIPTO": False, "BIST": True, "ABD": True})

    async def test_other_abd_and_bist_forms_still_reach_their_own_code(self):
        with unittest.mock.patch.object(main, "us_card_cmd", AsyncMock()) as card, \
             unittest.mock.patch.object(main, "us_portfolio_cmd", AsyncMock()) as pf, \
             unittest.mock.patch.object(main, "us_ranking", AsyncMock()) as rank:
            await self.run_cmd(main.abd, "kart", "NVDA")                                          # 7
            await self.run_cmd(main.abd, "portfoy")
            await self.run_cmd(main.abd, "guc")
        self.assertEqual(card.await_args.args[2], "NVDA")
        self.assertTrue(pf.await_count == 1 and rank.await_count == 1)
        self.assertIn("ABD bütçesi 1,000 USD", (await self.run_cmd(main.abd, "butce", "1000")).await_args.args[0])
        self.assertEqual(np_.prefs(OWNER)["ABD"], True)                                           # none of these touched the switch
        self.assertIsNone(np_.command(OWNER, "ABD", ["ac", "NVDA"]))                              # two words: not a switch

    async def test_panel_switch_uses_the_same_store(self):
        import web_sync
        row = lambda: {r["piyasa"]: r["acik"] for r in web_sync.build_settings()["bildirimler"]}
        self.assertEqual(row(), {"KRIPTO": False, "BIST": True, "ABD": True})
        np_.set_enabled(OWNER, "KRIPTO", True)                                                    # what settings.set {bildirim} does
        self.assertEqual(row()["KRIPTO"], True)
        self.assertIn("🪙 Kripto: AÇIK", np_.text(OWNER))                                         # and Telegram shows the same


class DigestTest(Base):
    async def test_level_digest_lists_only_open_markets(self):
        ev = lambda mkt, kod: {"piyasa": mkt, "kod": kod, "tf": "1s", "mum": 1, "kapanis": 10.0, "tur": "KIRILIM", "alt": 9.0,
                               "ust": 9.5, "dokunma": 2, "hacim": True, "sonraki": None, "atr": None, "atr_mum": None}
        res = {"olaylar": [ev("KRIPTO", "SOL"), ev("ABD", "NVDA")], "taranan": {"KRIPTO": 60, "ABD": 100}, "hata": 0}
        with unittest.mock.patch.object(main.levels_scan, "scan", AsyncMock(return_value=res)), \
             unittest.mock.patch.object(main.levels_scan, "record", return_value=[]), \
             unittest.mock.patch.object(main.levels_scan, "enabled", return_value=True):
            await main.levels_job(types.SimpleNamespace(bot=self.bot))
        self.assertEqual(len(self.sent), 1)
        self.assertIn("NVDA", self.sent[0])
        self.assertNotIn("SOL", self.sent[0])


if __name__ == "__main__":
    unittest.main()
