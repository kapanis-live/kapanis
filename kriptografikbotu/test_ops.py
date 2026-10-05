"""Encrypted backup copy and the site watch. No network. Run: python -m unittest test_ops"""
import os
import pathlib
import tempfile
import types
import unittest
import unittest.mock

os.environ["DATA_DIR"] = tempfile.mkdtemp()

import config  # noqa: E402
import db_backup  # noqa: E402
import main  # noqa: E402

config.ALLOWED_CHAT_ID = 1000


class EncryptTest(unittest.TestCase):
    def test_roundtrip_and_wrong_password(self):
        d = pathlib.Path(tempfile.mkdtemp())
        f = d / "kapanis-20260928-0330.jsonl.gz"
        f.write_bytes(b"\x1f\x8bsecret portfolio data")
        enc = db_backup.encrypt(f, "dogru-sifre")
        self.assertNotIn(b"secret", enc.read_bytes())
        f.unlink()
        self.assertEqual(db_backup.decrypt(enc, "dogru-sifre").read_bytes(), b"\x1f\x8bsecret portfolio data")
        with self.assertRaises(ValueError):
            db_backup.decrypt(enc, "yanlis")


class SiteWatchTest(unittest.IsolatedAsyncioTestCase):
    async def test_alert_after_two_failures_then_recovery(self):
        sent, state = [], {"ok": False}

        class Bot:
            async def send_message(self, chat, text, **kw):
                sent.append(text)

        class Resp:
            def __init__(self):
                self.status_code = 200 if state["ok"] else 502

        class Client:
            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, url):
                return Resp()
        main._site_down.clear()
        ctx = types.SimpleNamespace(bot=Bot())
        with unittest.mock.patch.object(main.httpx, "AsyncClient", Client):
            await main.site_watch_job(ctx)
            self.assertEqual(sent, [])                      # one failure: could be a blip
            await main.site_watch_job(ctx)
            self.assertEqual(sum("cevap vermiyor" in s for s in sent), 2)
            await main.site_watch_job(ctx)
            self.assertEqual(sum("cevap vermiyor" in s for s in sent), 2)  # no repeat while still down
            state["ok"] = True
            await main.site_watch_job(ctx)
        self.assertEqual(sum("yeniden cevap" in s for s in sent), 2)


class RiskNewsTest(unittest.IsolatedAsyncioTestCase):
    async def test_only_verified_new_negative_events_are_sent(self):
        import time as _t
        import risk_news
        now = _t.time()
        items = [{"baslik": "Months After the Kelp Hack, Chainlink Adds Bridge Checks", "ts": now, "kaynaklar": ["Decrypt"], "link": "x"},
                 {"baslik": "Chainlink bridge exploited, $40M drained", "ts": now + 1, "kaynaklar": ["Decrypt"], "link": "y"},
                 {"baslik": "Chainlink lawsuit filed by SEC", "ts": now + 2, "kaynaklar": ["Decrypt"], "link": "z"}]
        verdicts = {"Months After the Kelp Hack, Chainlink Adds Bridge Checks": {"gonder": False, "ozet": "başka projenin hack'i"},
                    "Chainlink bridge exploited, $40M drained": {"gonder": True, "ozet": "LINK köprüsü exploit edildi"},
                    "Chainlink lawsuit filed by SEC": None}

        async def verify(asset, kw, item):
            return verdicts[item["baslik"]]

        async def binance(client):
            return [{"baslik": "Binance Will Delist LINK", "ts": now + 3, "kaynak": "Binance duyuru", "link": "b"}]
        with unittest.mock.patch.object(risk_news, "watched", return_value=({"LINK"}, set())),                 unittest.mock.patch.object(risk_news.news, "get_news", unittest.mock.AsyncMock(return_value=items)),                 unittest.mock.patch.object(risk_news, "_binance", binance),                 unittest.mock.patch.object(risk_news, "verify", verify):
            msgs = await risk_news.check()
        text = " ||| ".join(msgs)
        self.assertNotIn("Kelp", text)                          # read and dropped
        self.assertIn("Makale okundu: LINK köprüsü", text)      # verified
        self.assertIn("doğrulanamadı", text)                    # no model answered: sent, marked
        self.assertIn("Binance Will Delist LINK", text)          # official announcement, no check
        self.assertEqual(len(msgs), 3)


class PanelSettingsTest(unittest.TestCase):
    def test_save_validates_and_applies(self):
        import panel_settings
        done = panel_settings.save({"min_rr": "1,3", "brif": "7.45", "ai_mod": "kimi"})
        self.assertEqual(len(done), 3)
        self.assertEqual((config.MIN_RR, config.BRIEF_HOUR, config.BRIEF_MINUTE), (1.3, 7, 45))
        with self.assertRaises(ValueError):
            panel_settings.save({"bist_risk": "99"})
        with self.assertRaises(ValueError):
            panel_settings.save({"on_filtre": "rastgele"})
        self.assertNotIn("timezone", panel_settings.SPEC)


class PanelHoldingTest(unittest.IsolatedAsyncioTestCase):
    async def test_add_edit_delete_from_the_panel(self):
        import positions
        import web_sync
        main.register_panel_actions(None)
        h = web_sync.EXTRA_HANDLERS

        async def levels(pos_like):
            return 80000.0, 95000.0, "test"

        async def review(pos):
            return None
        with unittest.mock.patch.object(main, "_suggest_levels", levels),                 unittest.mock.patch.object(main.exits, "review", review):
            said = await h["holding.add"]({"kod": "btc", "piyasa": "KRIPTO", "adet": 0.05, "maliyet": 84000})
            self.assertIn("Portföye eklendi", said)
            await h["holding.add"]({"kod": "THYAO", "piyasa": "BIST", "adet": 10, "maliyet": 300})
            self.assertIn("tam sayı", await h["holding.add"]({"kod": "THYAO", "piyasa": "BIST", "adet": 1.5, "maliyet": 300}))
        btc, thy = positions.open_positions()
        self.assertEqual((btc["piyasa"], btc["adet"], btc["giris"], btc["kaynak"]), ("KRIPTO", 0.05, 84000, "portföy"))
        self.assertIn("düzeltildi", await h["holding.edit"]({"id": btc["id"], "adet": 0.1, "maliyet": 80000}))
        self.assertEqual((positions.get(btc["id"])["adet"], positions.get(btc["id"])["giris"]), (0.1, 80000))
        self.assertIn("tam sayı", await h["holding.edit"]({"id": thy["id"], "adet": 2.5, "maliyet": 300}))
        self.assertIn("pozitif", await h["holding.edit"]({"id": thy["id"], "adet": 0, "maliyet": 300}))
        self.assertIn("silindi", await h["holding.delete"]({"id": thy["id"]}))
        self.assertIn("yok", await h["holding.delete"]({"id": thy["id"]}))
        self.assertEqual([p["id"] for p in positions.open_positions()], [btc["id"]])
        # a new portfolio from the panel: the open records go (kept in a backup file), the new rows come in
        with unittest.mock.patch.object(main, "_suggest_levels", levels), \
                unittest.mock.patch.object(main.exits, "review", review):
            said = await h["holding.bulk"]({"temizle": True, "satirlar": [
                {"kod": "eth", "piyasa": "KRIPTO", "adet": 2, "maliyet": 3000},
                {"kod": "NVDA", "piyasa": "ABD", "adet": 3, "maliyet": 120},
                {"kod": "THYAO", "piyasa": "BIST", "adet": 1.5, "maliyet": 300}]})
        self.assertIn("1 açık kayıt", said)
        self.assertEqual(said.count("✅"), 2)
        self.assertIn("❌ THYAO", said)
        self.assertEqual([(p["piyasa"], p["adet"]) for p in positions.open_positions()], [("KRIPTO", 2), ("ABD", 3)])
        self.assertTrue((config.DATA_DIR / "positions_silinen.json").exists())
        self.assertIn("2 açık kayıt", await h["holding.bulk"]({"temizle": True}))
        self.assertEqual(positions.open_positions(), [])


    async def test_cash_plans_alarms_watchlist_and_sale_from_the_panel(self):
        import balance
        import dca
        import pf_alarm
        import positions
        import watchlist
        import web_sync
        main.register_panel_actions(None)
        h = web_sync.EXTRA_HANDLERS
        positions.save([])
        self.assertIn("5,000.00 TL", await h["cash.set"]({"piyasa": "BIST", "tutar": 5000}))
        self.assertEqual(balance.cash()["BIST"], 5000)
        self.assertIn("❌", await h["cash.set"]({"piyasa": "BIST", "tutar": -1}))
        with unittest.mock.patch.object(main.bist, "watchlist", return_value=["THYAO"]):
            self.assertIn("Birikim planı kuruldu", await h["dca.add"]({"kod": "THYAO", "tutar": 1000, "gun": 15}))
        plan = dca.plans()[-1]
        self.assertEqual((plan["piyasa"], plan["tutar"], plan["gun"]), ("BIST", 1000, 15))
        self.assertIn("silindi", await h["dca.delete"]({"id": plan["id"]}))
        self.assertIn("Kuruldu", await h["palarm.add"]({"piyasa": "BIST", "tur": "yuzde", "deger": -10}))
        alarm = pf_alarm.load()[-1]
        self.assertEqual((alarm["esik"], alarm["yon"]), (4500, "ALTINA"))
        self.assertIn("Silindi", await h["palarm.delete"]({"id": alarm["id"]}))
        self.assertIn("❌", await h["palarm.add"]({"piyasa": "BIST", "tur": "yuzde", "deger": 0}))
        self.assertIn("Eklendi", await h["watch.add"]({"kodlar": ["zzztest"], "piyasa": "KRIPTO"}))
        self.assertIn("ZZZTEST", watchlist.load()["KRIPTO"])
        self.assertIn("Çıkarıldı", await h["watch.remove"]({"kodlar": ["ZZZTEST"]}))
        self.assertNotIn("ZZZTEST", watchlist.load()["KRIPTO"])
        self.assertIn("KAPATILDI", await h["discipline.set"]({"islem": "kapat"}))
        self.assertIn("açıldı", await h["discipline.set"]({"islem": "ac"}))
        pos = positions.open_position("SOL/USDT", 100, 1000, 90, 130, "4h", source="portföy")
        self.assertIn("kalan 6", await h["holding.sell"]({"id": pos["id"], "adet": 4, "fiyat": 120}))
        self.assertIn("elde 6", await h["holding.sell"]({"id": pos["id"], "adet": 7, "fiyat": 120}))
        said = await h["holding.edit"]({"id": pos["id"], "adet": 6, "maliyet": 100, "stop": 95, "tarih": "2026-03-01"})
        self.assertIn("düzeltildi", said)
        now = positions.get(pos["id"])
        self.assertEqual((now["stop"], now["acilis"][:10], now["tarih_girildi"]), (95, "2026-03-01", True))
        self.assertIn("goalpost", await h["holding.edit"]({"id": pos["id"], "adet": 6, "maliyet": 100, "stop": 80}))
        self.assertIn("pozisyon kapandı", await h["holding.sell"]({"id": pos["id"], "fiyat": 110}))
        self.assertEqual(positions.open_positions(), [])


class OpportunityOrderTest(unittest.TestCase):
    def test_usdt_and_usd_rows_lead_and_tl_rows_are_capped(self):
        import opportunities
        rows = [{"piyasa": "BIST", "kod": f"TL{i}", "durum": "yaklasiyor", "fiyat": 10.0, "uzaklik_yuzde": 1.0} for i in range(6)]
        rows += [{"piyasa": "ABD", "kod": "NVDA", "durum": "yaklasiyor", "fiyat": 120.0, "uzaklik_yuzde": 1.0},
                 {"piyasa": "KRIPTO", "kod": "SOL", "durum": "yaklasiyor", "fiyat": 150.0, "uzaklik_yuzde": 1.0}]
        shown, hidden = opportunities._front(rows, 8)
        self.assertEqual([i["kod"] for i in shown], ["SOL", "NVDA", "TL0", "TL1", "TL2"])
        self.assertEqual(hidden, 3)
        blockers = {"btc_kapi": "AÇIK", "makro": "0", "duygu": "50", "kademe": 25.0, "kademe_not": ""}
        bist = {"seans": "açık", "endeks": "AÇIK", "butce": 0, "kademe_tl": 0.0, "kademe_not": ""}
        text = opportunities.text({"zaman": "2026-10-02T10:00:00+03:00", "sure_sn": 1.0, "alinabilir": [], "kalemler": rows,
                                   "kripto_engeller": blockers, "bist_engeller": bist})
        self.assertLess(text.index("SOL"), text.index("NVDA"))
        self.assertLess(text.index("NVDA"), text.index("TL0"))
        self.assertNotIn("TL3", text)
        self.assertIn("+3 BIST (TL) kalemi daha", text)


class LevelScanTest(unittest.TestCase):
    def test_events_come_from_closes_and_carry_the_untested_note(self):
        import levels_scan
        bar = lambda o, h, l, c, v=100.0: types.SimpleNamespace(open=o, high=h, low=l, close=c, volume=v, vol_avg20=80.0)
        zone = lambda lo, hi, n=3: {"alt": lo, "ust": hi, "orta": (lo + hi) / 2, "dokunma": n}
        zones = {"direncler": [zone(104, 105), zone(110, 111)], "destekler": [zone(95, 96), zone(90, 91)]}
        up = levels_scan.detect(bar(100, 103, 99, 102), bar(102, 107, 102, 106), zones)
        self.assertEqual((up["tur"], up["ust"], up["sonraki"], up["hacim"]), ("KIRILIM", 105, 110.5, True))
        wick = levels_scan.detect(bar(100, 103, 99, 102), bar(102, 107, 102, 104.5), zones)     # high above, close inside
        self.assertEqual(wick["tur"], "DIRENCTE")
        down = levels_scan.detect(bar(100, 101, 97, 98), bar(98, 98, 93, 94), zones)
        self.assertEqual((down["tur"], down["alt"], down["sonraki"]), ("DESTEK_KIRILDI", 95, 90.5))
        hold = levels_scan.detect(bar(100, 101, 97, 98), bar(98, 99, 95.5, 97), zones)
        self.assertEqual(hold["tur"], "DESTEKTE")
        self.assertIsNone(levels_scan.detect(bar(100, 101, 99, 100), bar(100, 101, 99, 100.5), zones))
        weak = {"direncler": [zone(104, 105, 1)], "destekler": []}                               # one touch: not a level
        self.assertIsNone(levels_scan.detect(bar(100, 103, 99, 102), bar(102, 107, 102, 106), weak))
        res = {"olaylar": [{"piyasa": "KRIPTO", "kod": "SOL", "tf": "1s", "mum": 1, "kapanis": 106.0, **up}],
               "taranan": {"KRIPTO": 60}, "hata": 0}
        said = levels_scan.text(res)
        self.assertIn("SOL 106 — 🟢 direnç kırıldı 104–105 (3 dokunma, hacimli)", said)
        self.assertIn("AL/SAT önerisi değil", said)
        self.assertIsNone(levels_scan.text({**res, "olaylar": []}))
        self.assertIn("Yeni seviye olayı yok", levels_scan.text({**res, "olaylar": []}, empty=True))


class DeleteButtonTest(unittest.TestCase):
    def test_sil_removes_every_lot_of_one_asset_without_a_sale(self):
        import positions
        lot = lambda i, sym, qty: {"id": i, "pair": sym[:-4] + "/USDT", "symbol": sym, "piyasa": "KRIPTO", "adet": qty,
                                   "giris": 1.0, "durum": "acik", "miktar_usd": qty}
        positions.save([lot(1, "SHIBUSDT", 5e6), lot(2, "SHIBUSDT", 47971), lot(3, "BTCUSDT", 0.01)])
        self.addCleanup(positions.save, [])                                     # the data folder is shared by this file
        said = main.delete_holding("KRIPTO", "SHIBUSDT")
        self.assertIn("5,047,971 adet, 2 kayıt", said)
        self.assertEqual([p["id"] for p in positions.load()], [3])              # nothing closed, nothing realized
        self.assertEqual(len(alerts_store_backup()), 3)                         # the way back
        self.assertIn("kalmamış", main.delete_holding("KRIPTO", "SHIBUSDT"))


def alerts_store_backup():
    import json
    return json.loads((config.DATA_DIR / "positions_silinen.json").read_text(encoding="utf-8"))


class ResearchGapTest(unittest.TestCase):
    def test_relisted_ticker_is_two_assets(self):
        # LUNA: last old candle 0.00005, relaunch 18 days later at 6.38; one frame would book +12,700,000 % as a trade
        import sys
        sys.path.insert(0, str(pathlib.Path(__file__).parent / "research"))
        import pandas as pd
        import engine
        day = 86_400_000
        df = pd.DataFrame({"t": [0, day, 2 * day, 20 * day, 21 * day], "c": [80.0, 1.0, 0.00005, 6.38, 6.0]})
        parts = engine.split_gaps(df)
        self.assertEqual([len(p) for p in parts], [3, 2])
        self.assertEqual(parts[1].c.iloc[0], 6.38)
        self.assertEqual(len(engine.split_gaps(df.iloc[:3])), 1)

    def test_impossible_result_is_flagged(self):
        import sys
        sys.path.insert(0, str(pathlib.Path(__file__).parent / "research"))
        import numpy as np
        import engine
        self.assertIn("METRIC_ANOMALY", engine.anomaly(np.array([0.02, -0.01, 127354.0]))["anomali"])
        self.assertEqual(engine.anomaly(np.array([0.05, -0.03, 0.4, -0.1])), {})


class BrokerFilterTest(unittest.TestCase):
    def test_blocked_coins_never_reach_a_scan(self):
        import broker
        import danisman
        self.assertIn("STX", broker.blocked())                                   # the user's reported defaults
        self.assertEqual(broker.change(["sol", "STXUSDT", "sol"], block=True), ["SOL"])
        self.assertEqual(broker.change(["STX"], block=False), ["STX"])
        self.assertEqual(broker.blocked(), {"JASMY", "INJ", "TAO", "SOL"})
        t = {"lastPrice": "150", "highPrice": "155", "lowPrice": "140", "quoteVolume": "9e9"}
        self.assertEqual(danisman.exclusion("SOL", t, None, {"SOL"}, broker.blocked()), "NOT_ON_BROKER")
        self.assertIsNone(danisman.exclusion("STX", t, None, {"STX"}, broker.blocked()))
        self.assertIn("NOT_ON_BROKER", danisman.EXCLUDE_TR)
        broker.change(["SOL"], block=False)


if __name__ == "__main__":
    unittest.main()
