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


class LanguageTest(Base):
    def setUp(self):
        super().setUp()
        st = alerts_store.load_settings()
        st.pop("dil", None)
        alerts_store.save_settings(st)
        self.addCleanup(lambda: alerts_store.save_settings({k: v for k, v in alerts_store.load_settings().items() if k != "dil"}))

    async def test_dil_switches_this_chat_and_its_menu(self):
        import lang
        update = types.SimpleNamespace(effective_chat=types.SimpleNamespace(id=OWNER, type="private"), message=types.SimpleNamespace(reply_text=AsyncMock()))
        bot = types.SimpleNamespace(set_my_commands=AsyncMock())
        ask = lambda *args: main.dil_cmd(update, types.SimpleNamespace(args=list(args), bot=bot, user_data={}))
        said = lambda: update.message.reply_text.await_args.args[0]
        self.assertEqual(lang.get(OWNER), "tr")                                        # Turkish until chosen otherwise
        await ask()
        self.assertIn("Dil: Türkçe", said())
        await ask("english")
        self.assertIn("Language: English", said())
        self.assertEqual((lang.get(OWNER), lang.get(999)), ("en", "tr"))               # per chat
        menu = {c.command: c.description for c in bot.set_my_commands.await_args.args[0]}
        self.assertEqual(menu["aylik"], "Monthly report: return, vs indexes, trades")
        self.assertEqual(bot.set_my_commands.await_args.kwargs["scope"].chat_id, OWNER)
        self.assertIn("Notification settings", np_.text(OWNER))
        self.assertIn("🪙 Crypto: OFF", np_.text(OWNER))
        await ask("xx")
        self.assertIn("❌", said())
        await ask("tr")
        self.assertIn("🪙 Kripto: KAPALI", np_.text(OWNER))
        self.assertEqual({c.command for c in main.menu_commands("en")}, {c for c, _ in main.BOT_MENU})
        self.assertEqual([c for c, _ in main.BOT_MENU if c not in lang.MENU_EN], [])   # every command has an English line

    async def test_translated_reports_keep_the_same_numbers(self):
        import monthly
        import stock_scan
        d = {"ay": "2026-09", "ad": "Eylül 2026", "bas_gun": "2026-08-31", "son_gun": "2026-09-30", "varlik": 2, "hesaplanamayan": [],
             "getiri": {"tl_yuzde": 3.5, "usd_yuzde": 2.2, "kazanc_tl": 5416.0, "kazanc_usd": 70.0, "izlenen_tl": 155000.0},
             "kiyas": {"BIST 100": -16.7, "BTC": 6.4}, "usdtry_yuzde": 1.6,
             "en_iyi": [{"ad": "ETH", "piyasa": "KRIPTO", "para": "USD", "kazanc_tl": 8000.0, "kazanc": 216.0, "yuzde": 17.5}], "en_kotu": [],
             "islemler": {"alim": 1, "satim": 1, "gerceklesen": {"USD": 200.0}, "alinan": ["SOL"], "satilan": ["ETH"]},
             "yogunlasma": {"ay_basi": {"ad": "ETH", "yuzde": 44.5, "toplam_tl": 1.0}, "ay_sonu": {"ad": "THYAO", "yuzde": 31.3, "toplam_tl": 1.0}}}
        tr, en = monthly.text(d), monthly.text(d, "en")
        self.assertIn("AYLIK RAPOR — Eylül 2026", tr)
        self.assertIn("MONTHLY REPORT — September 2026", en)
        self.assertIn("Return: TL %+3.5 (+5,416 TL) · USD %+2.2 (+70 USD)", en)
        self.assertIn("New money is not counted as return", en)
        import re
        nums = lambda t: sorted(re.findall(r"[+-]\d[\d,.]*", t))
        self.assertEqual(nums(tr), nums(en))                                           # only the words differ
        row = {"kod": "NVDA", "fiyat": 230.0, "gun_yuzde": 1.0, "hafta_yuzde": 1.0, "trend": "↗ güçlü", "guc": "GÜÇLÜ", "guc_6a": 11.5, "rsi": 54,
               "puan": 95, "puan_etiket": "x", "degerleme": "UCUZ", "sektor": "Technology", "revizyon": None, "bilanco_tarih": None,
               "bilanco_gun": 4, "bilanco_risk": "YÜKSEK"}
        doc = {"piyasa": "ABD", "zaman": "2026-10-09T18:00:00+03:00", "temeli_eksik": 0, "satirlar": [row]}
        self.assertIn("NVDA 230$ · puan 95 · ↗ güçlü · güç GÜÇLÜ · UCUZ · bilanço 4g ⚠️", stock_scan.text(doc))
        self.assertIn("NVDA 230$ · score 95 · ↗ strong · strength STRONG · CHEAP · earnings 4d ⚠️", stock_scan.text(doc, code="en"))
        self.assertIn("a ranking, not a suggestion", stock_scan.text(doc, code="en"))

    async def test_site_switch_reaches_the_right_chat(self):
        """The site's language choice arrives as a queued command: the owner's chat, or a user's own linked chat."""
        import lang
        import web_sync
        bot = types.SimpleNamespace(set_my_commands=AsyncMock())
        main.register_panel_actions(bot)
        run = web_sync.EXTRA_HANDLERS["language.set"]
        self.assertIn("language.set", web_sync.USER_COMMANDS)
        said = await run({"dil": "en", "_komut": {"role": "user", "telegram_chat_id": 555}})
        self.assertIn("Language: English", said)
        self.assertEqual((lang.get(555), lang.get(OWNER)), ("en", "tr"))               # only that user's chat
        bot.set_my_commands.assert_not_awaited()                                         # the owner's command menu is not theirs
        self.assertEqual(await run({"dil": "en", "_komut": {"role": "user", "telegram_chat_id": None}}), "")
        said = await run({"dil": "en", "_komut": {"role": "owner"}})
        self.assertIn("Language: English", said)
        self.assertEqual(lang.get(OWNER), "en")
        self.assertEqual(bot.set_my_commands.await_args.kwargs["scope"].chat_id, OWNER)
        self.assertIn("❌", await run({"dil": "de", "_komut": {"role": "owner"}}))


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


class EnglishTextTest(unittest.TestCase):
    """Cards, the US portfolio report and the level digest have an English text; the Turkish one is unchanged by default."""
    CARD = {"hisse": "NVDA", "fiyat": 131.2, "sektor": "Technology", "endustri": "Semiconductors", "temel": {"skor": 82, "durum": "GÜÇLÜ"},
            "bilanco": {"gun": 4, "risk": "YÜKSEK", "tarih": "2026-10-13", "kaynak": "Yahoo"},
            "degerleme": {"etiket": "PAHALI", "ileri_fk": 38.1, "peg": None, "fcf_verimi_yuzde": 2.1},
            "guc": {"spy_6a": 14.2, "spy": "GÜÇLÜ", "qqq_6a": None, "qqq": "BİLİNMİYOR"},
            "trend": {"günlük": "↗ güçlü", "haftalık": "→ karışık", "hizalama": "fiyat > SMA50", "zirveye_uzaklik_yuzde": 6.4},
            "revizyon": {"etiket": "YUKARI", "eps_30g_yuzde": 2.4, "eps_90g_yuzde": None, "yukari_30g": 12, "asagi_30g": None},
            "son_bilanco": {"surpriz_yuzde": None, "not": "", "tepki": None}, "dikkat": [], "kaynaklar": [], "uretildi": "2026-10-09T19:00:00"}
    SCAN = {"taranan": {"KRIPTO": 40, "BIST": 30, "ABD": 100}, "hata": 0,
            "olaylar": [{"piyasa": "ABD", "tur": "KIRILIM", "hacim": True, "dokunma": 3, "kod": "NVDA", "kapanis": 131.2, "alt": 128, "ust": 130, "sonraki": 140}]}

    def test_us_card(self):
        import us_card
        en, tr = us_card.text(self.CARD, "en"), us_card.text(self.CARD)
        self.assertIn("Strength (6 months, points): SPY +14.2 STRONG · QQQ — UNKNOWN", en)
        self.assertIn("risk HIGH", en)
        self.assertIn("not a BUY/SELL suggestion", en)
        self.assertIn("Güç (6 ay, puan farkı): SPY +14.2 GÜÇLÜ", tr)
        self.assertEqual(tr, us_card.text(self.CARD, "tr"))

    def test_level_digest(self):
        import levels_scan
        en = levels_scan.text(self.SCAN, code="en")
        self.assertIn("NVDA 131.2 — 🟢 resistance broken 128–130 (3 touches, with volume) · next level 140", en)
        self.assertIn("not a BUY/SELL suggestion", en)
        self.assertIsNone(levels_scan.text({**self.SCAN, "olaylar": []}, code="en"))
        self.assertIn("No new level event.", levels_scan.text({**self.SCAN, "olaylar": []}, empty=True, code="en"))
        self.assertIn("direnç kırıldı", levels_scan.text(self.SCAN))

    def test_us_portfolio(self):
        import us_portfolio
        r = {"toplam_usd": 12000, "agirlik_yuzde": {"NVDA": 60, "MSFT": 40}, "sektor_yuzde": {"Technology": 100},
             "tema": {"Mega teknoloji": {"agirlik_yuzde": 100, "hisseler": ["NVDA", "MSFT"]}},
             "korelasyon": {"ortalama": None, "en_bagli": [], "en_bagimsiz": []}, "beta": {"SPY": 1.4, "QQQ": 1.2}, "vix": 17.2, "tnx": 4.21,
             "senaryolar": [{"senaryo": "S&P 500 %10 düşerse", "portfoy_yuzde": -14.0, "tutar_usd": -1680, "en_cok_etkilenen": [[-16.2, "NVDA"]]}],
             "dikkat": [], "kapsam_yuzde": 100, "kaynaklar": []}
        en = us_portfolio.text(r, "en")
        self.assertIn("· Mega tech: 100% (NVDA, MSFT)", en)
        self.assertIn("· If the S&P 500 falls 10%: portfolio -14% (-1,680 USD) · most affected: NVDA -16.2%", en)
        self.assertIn("S&P 500 %10 düşerse: portföy %-14", us_portfolio.text(r))


class PortfolioTextTest(unittest.IsolatedAsyncioTestCase):
    """/portfoy: the frame and the labels follow the chat's language; the numbers are the same."""
    PF = {"gruplar": [{"piyasa": "ABD", "para": "USD", "symbol": "NVDA.US", "kod": "NVDA", "adet": 2, "maliyet": 400.0, "deger": 440.0, "fiyat": 220.0,
                       "gun_etiket": "Son seans (08.10)", "gun_yuzde": 1.0, "gun_tutar": 4.4, "karar": "TUT", "poz": [{}], "ids": [7], "reel": {},
                       "temettu": 0.0, "temettu_bilgi": None}],
          "hatalar": [], "toplam": {"ABD": {"deger": 440.0, "maliyet": 400.0, "gun": 4.4, "para": "USD", "temettu": 0, "reel": {}}},
          "yogunlasma": {"uyarilar": []}, "tufe": True}

    async def summary(self, code):
        sent = []

        async def fake_long(bot, chat_id, text, **kwargs):
            sent.append(text)
        status = types.SimpleNamespace(delete=AsyncMock())
        update = types.SimpleNamespace(effective_chat=types.SimpleNamespace(id=OWNER), message=types.SimpleNamespace(reply_text=AsyncMock(return_value=status)))
        with unittest.mock.patch.object(main.positions, "open_positions", return_value=[{"piyasa": "ABD"}]),                 unittest.mock.patch.object(main, "collect_portfolio", AsyncMock(return_value=self.PF)),                 unittest.mock.patch.object(main, "send_long", fake_long),                 unittest.mock.patch.object(main.lang, "get", return_value=code),                 unittest.mock.patch.object(main.risk, "name", return_value="NVDA"):
            await main.portfolio_summary(update, types.SimpleNamespace(bot=None))
        return sent[0]

    async def test_english_and_turkish(self):
        en, tr = await self.summary("en"), await self.summary("tr")
        self.assertIn("💼 PORTFOLIO", en)
        self.assertIn("2 shares · avg. cost 200 → 220", en)
        self.assertIn("Value 440.00 USD · Last session (08.10)", en)
        self.assertIn("🟢 HOLD · #7", en)
        self.assertIn("── Total 440.00 USD", en)
        self.assertIn("💼 PORTFÖY", tr)
        self.assertIn("2 hisse · ort. maliyet 200 → 220", tr)
        self.assertIn("🟢 TUT · #7", tr)


if __name__ == "__main__":
    unittest.main()
