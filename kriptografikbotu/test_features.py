"""Pure-logic tests for the portfolio/discipline features. No network, temporary data folder.
Run with: python -m unittest test_features"""
import os
import pathlib
import tempfile
import unittest
import unittest.mock
from datetime import date, datetime, timedelta

_TMP = tempfile.mkdtemp()
os.environ["DATA_DIR"] = _TMP

import pandas as pd  # noqa: E402

import alerts_store  # noqa: E402
import bist  # noqa: E402
import config  # noqa: E402
import corporate  # noqa: E402
import dca  # noqa: E402
import discipline  # noqa: E402
import journal  # noqa: E402
import positions  # noqa: E402
import risk  # noqa: E402
import features  # noqa: E402
import tools  # noqa: E402


def _reset():
    for f in pathlib.Path(_TMP).glob("*.json"):
        f.unlink()


def _closed(pair, entry, exit_, qty, when, **extra):
    pos = positions.open_position(pair, entry, entry * qty, extra.pop("stop", None), extra.pop("hedef", None),
                                  market_name=extra.pop("piyasa", "KRIPTO"), symbol=extra.pop("symbol", None))
    positions.update(pos["id"], adet=qty, **extra)
    items = positions.load()
    for p in items:
        if p["id"] == pos["id"]:
            p.update(durum="kapali", kapanis_fiyat=exit_, kapanis_zamani=when.isoformat())
    positions.save(items)
    return pos["id"]


class PortfolioHistoryTest(unittest.IsolatedAsyncioTestCase):
    async def test_closed_bist_market_keeps_friday_close_on_crypto_weekend(self):
        _reset()

        def frame(prices):
            times = [int(datetime.fromisoformat(d).timestamp() * 1000) for d in prices]
            return pd.DataFrame({"open_time": times, "close": list(prices.values())})

        friday, saturday, sunday, monday = "2026-09-18", "2026-09-19", "2026-09-20", "2026-09-21"
        bist_rows = {
            "THYAO.IS": frame({friday: 100, monday: 110}),
            "USDTRY=X": frame({friday: 40, monday: 41}),
            "XU100.IS": frame({friday: 10000, monday: 10100}),
            "GC=F": frame({friday: 3000, monday: 3100}),
        }
        crypto = frame({friday: 10, saturday: 11, sunday: 12, monday: 13})

        async def fetch_bist(_client, symbol, _interval):
            return bist_rows[symbol]

        async def fetch_crypto(_client, _symbol, _interval, limit):
            return crypto

        held = [{"piyasa": "BIST", "symbol": "THYAO.IS", "adet": 1},
                {"piyasa": "KRIPTO", "symbol": "BTCUSDT", "adet": 1}]
        with unittest.mock.patch.object(features, "_today", return_value=monday), \
             unittest.mock.patch.object(positions, "open_positions", return_value=held), \
             unittest.mock.patch.object(bist, "fetch", side_effect=fetch_bist), \
             unittest.mock.patch.object(features.market, "fetch_klines", side_effect=fetch_crypto):
            rows = (await features.backfill_history(10))["satirlar"]

        by_day = {r["tarih"]: r for r in rows}
        self.assertEqual(by_day[saturday]["bist"], 100)
        self.assertEqual(by_day[sunday]["bist"], 100)
        self.assertEqual(by_day[sunday]["xu100"], 10000)
        self.assertEqual(by_day[sunday]["toplam_tl"], 580)
        self.assertAlmostEqual(by_day[sunday]["gram_altin"], round(3000 * 40 / features.assets.OUNCE_GRAMS, 2))


class PanelInputTest(unittest.TestCase):
    def setUp(self):
        _reset()

    def test_allocation_rejects_invalid_percentages(self):
        with self.assertRaises(ValueError):
            features.set_target({"BIST": -10, "KRIPTO": 110})
        with self.assertRaises(ValueError):
            features.set_target({"BIST": 100}, float("nan"))
        self.assertAlmostEqual(sum(features.set_target({"BIST": 1, "KRIPTO": 1, "ABD": 1}).get(k, 0)
                                   for k in features.TARGET_KEYS), 100)

    def test_paper_trade_rejects_zero_or_nonfinite_prices_and_quantity(self):
        for price, qty in ((0, 1), (1, -1), (float("nan"), 1)):
            with self.assertRaises(ValueError):
                features.paper_open("BIST", "THYAO", price, qty)
        with self.assertRaises(ValueError):
            features.paper_open("BIST", "THYAO", 100, 1.5)
        row = features.paper_open("BIST", "THYAO", 100, 1)
        with self.assertRaises(ValueError):
            features.paper_close(row["id"], 0)

    def test_watch_alert_uses_closed_price(self):
        features.set_watch_rules(destek_yakin=2, rsi_alti=0, rsi_ustu=0, hacim_kat=0)
        row = {"kod": "THYAO", "fiyat": 101, "destek": 100, "destek_yuzde": -1,
               "kapanis_fiyat": 110, "kapanis_destek": 100, "kapanis_destek_yuzde": -9,
               "rsi": 50, "hacim_kat": 1}
        self.assertIsNone(features.check_watch_rules({"BIST": [row]}))
        row.update(kapanis_fiyat=101, kapanis_destek_yuzde=-1)
        self.assertIn("son kapanış 101", features.check_watch_rules({"BIST": [row]}))


class SplitTest(unittest.TestCase):
    def test_split_rescales_quantity_and_levels(self):
        pos = {"adet": 10, "giris": 1000.0, "stop": 900.0, "stop_ilk": 880.0, "hedef": 1200.0,
               "son_cikis": {"stop_onerisi": 950.0}}
        ch = corporate.split_changes(pos, {"oran": 10.0})
        self.assertEqual(ch["adet"], 100)
        self.assertAlmostEqual(ch["giris"], 100.0)
        self.assertAlmostEqual(ch["stop"], 90.0)
        self.assertAlmostEqual(ch["hedef"], 120.0)
        self.assertAlmostEqual(ch["son_cikis"]["stop_onerisi"], 95.0)
        # position value is unchanged by a split
        self.assertAlmostEqual(ch["adet"] * ch["giris"], pos["adet"] * pos["giris"])


class RealReturnTest(unittest.TestCase):
    def test_dollar_and_inflation_return(self):
        fx = {"2026-01-05": 40.0, "2026-09-24": 48.0, "son": 48.0}
        cpi = {"2026-01": 100.0, "2026-08": 120.0}
        rows = [{"acilis": "2026-01-05T11:00:00+03:00", "maliyet": 1000.0, "deger": 1300.0, "para": "TL"}]
        r = corporate.real_returns(rows, fx, cpi)
        self.assertAlmostEqual(r["tl_yuzde"], 30.0)
        self.assertAlmostEqual(r["usd_yuzde"], round((1300 / 48) / (1000 / 40) * 100 - 100, 2))
        self.assertAlmostEqual(r["reel_yuzde"], round(1300 / 1200 * 100 - 100, 2))

    def test_no_cpi_means_no_real_column(self):
        r = corporate.real_returns([{"acilis": "2026-01-05", "maliyet": 10, "deger": 11, "para": "USD"}],
                                   {"2026-01-05": 40.0, "son": 48.0}, None)
        self.assertIsNone(r["reel_yuzde"])
        self.assertAlmostEqual(r["tl_yuzde"], round(11 * 48 / (10 * 40) * 100 - 100, 2))

    def test_dividend_outlook_uses_last_year(self):
        ev = {"temettuler": [{"tarih": "2025-11-10", "ms": 0, "tutar": 2.0},
                             {"tarih": "2026-03-01", "ms": 0, "tutar": 1.0}], "bolunmeler": []}
        info = corporate.dividend_outlook(ev, 100.0, today=date(2026, 9, 25))
        self.assertEqual(info["son12ay_toplam"], 3.0)
        self.assertEqual(info["verim_yuzde"], 3.0)
        self.assertEqual([d["tahmini"] for d in info["gecen_yil_ayni_donem"]], ["2026-11-10"])


class DisciplineTest(unittest.TestCase):
    def setUp(self):
        _reset()

    def test_two_losses_block_new_entries(self):
        now = alerts_store.now_tr()
        _closed("BTC/USDT", 100, 95, 0.2, now - timedelta(hours=5))
        _closed("ETH/USDT", 100, 97, 0.2, now - timedelta(hours=2))
        ok, detail = discipline.check("KRIPTO")
        self.assertFalse(ok)
        self.assertIn("üst üste 2 zarar", detail)
        ok_bist, _ = discipline.check("BIST")
        self.assertFalse(ok_bist)  # tilt is about the person, both markets
        discipline.forgive()
        self.assertTrue(discipline.check("KRIPTO")[0])

    def test_win_breaks_streak_and_fifo_parts_are_one_trade(self):
        now = alerts_store.now_tr()
        _closed("BTC/USDT", 100, 95, 0.1, now - timedelta(hours=6))
        _closed("ETH/USDT", 100, 110, 0.1, now - timedelta(hours=4))
        t = now - timedelta(hours=1)
        _closed("SOL/USDT", 100, 99, 0.05, t)
        _closed("SOL/USDT", 100, 99, 0.05, t)  # same minute, same asset: one trade
        self.assertEqual(discipline.status()["seri"], 1)

    def test_daily_loss_limit(self):
        now = alerts_store.now_tr().replace(hour=12)
        _closed("BTC/USDT", 100, 80, 0.2, now)  # -4 USD > 3% of 100 USD
        st = discipline.status(now=now)
        self.assertIsNotNone(st["piyasa"]["KRIPTO"]["engel"])
        self.assertIsNone(st["piyasa"]["BIST"]["engel"])

    def test_imported_holdings_do_not_count(self):
        now = alerts_store.now_tr()
        _closed("BTC/USDT", 100, 90, 0.1, now - timedelta(hours=3), kaynak="portföy")
        _closed("ETH/USDT", 100, 90, 0.1, now - timedelta(hours=2), birikim=1)
        self.assertEqual(discipline.status()["seri"], 0)

    def test_stop_down_attempt_is_logged(self):
        pos = positions.open_position("BTC/USDT", 100, 25, 95, 110)
        _, err = positions.update(pos["id"], stop=90)
        self.assertIn("goalpost", err)
        self.assertEqual(positions.get(pos["id"])["kural_ihlali"][0]["tur"], "stop_asagi")


class TrancheTest(unittest.TestCase):
    def setUp(self):
        _reset()

    def test_greed_shrinks_and_holdings_do_not_fill_cap(self):
        pos = positions.open_position("BTC/USDT", 100, 500, None, None, source="portföy")
        usd, notes = positions.tranche_usd("ETH/USDT", False, True)
        self.assertEqual(usd, config.DEFAULT_TRANCHE_USD)  # a 500 USD imported holding is not a first tranche
        usd, notes = positions.tranche_usd("ETH/USDT", False, True, greed="Korku & Açgözlülük 85")
        self.assertEqual(usd, config.REDUCED_TRANCHE_USD)
        self.assertTrue(any("85" in n for n in notes))
        self.assertTrue(pos)


class JournalTest(unittest.TestCase):
    def setUp(self):
        _reset()

    def test_reasons_adherence_and_top_mistake(self):
        now = alerts_store.now_tr()
        a = _closed("BTC/USDT", 100, 90, 0.1, now - timedelta(hours=3), stop=95)  # exit far below stop
        b = _closed("ETH/USDT", 100, 94.5, 0.1, now - timedelta(hours=2), stop=95)
        c = _closed("SOL/USDT", 100, 101, 0.1, now - timedelta(hours=1), stop=95, hedef=120)
        journal.set_reason(a, "al", "fomo")
        journal.set_reason(b, "al", "fomo")
        journal.set_reason(c, "sat", "korku")
        s = journal.summary((now - timedelta(days=1)).isoformat())
        self.assertEqual(s["islem"], 3)
        self.assertEqual(s["plan_uyumu"]["gec_stop"], 1)
        self.assertEqual(s["en_sik_hata"]["hata"], "FOMO ile alım")
        self.assertIn("FOMO", journal.text(s))


class DcaTest(unittest.TestCase):
    def setUp(self):
        _reset()

    def test_due_once_a_month_and_bist_waits_for_trading_day(self):
        p = {"piyasa": "BIST", "gun": 15, "son_hatirlatma": None}
        self.assertFalse(dca.due(p, date(2026, 9, 14), True))
        self.assertTrue(dca.due(p, date(2026, 9, 15), True))
        self.assertFalse(dca.due(p, date(2026, 9, 15), False))  # holiday: wait
        self.assertTrue(dca.due(p, date(2026, 9, 16), True))   # first trading day after
        p["son_hatirlatma"] = "2026-09-16"
        self.assertFalse(dca.due(p, date(2026, 9, 20), True))
        self.assertTrue(dca.due(p, date(2026, 10, 15), True))

    def test_quantity_and_dip(self):
        plan = dca.add_plan("THYAO", "BIST", "THYAO.IS", "THYAO.IS", 1000, 15)
        self.assertEqual(dca.quantity(plan, 300), 3)
        dca.record_buy(plan, 300, 3)
        self.assertEqual(dca.holdings(plan)["ortalama"], 300)
        self.assertIsNotNone(dca.dip_reason(plan, 260, None))    # 13% under average cost
        self.assertIsNone(dca.dip_reason(plan, 290, 300))
        self.assertIsNotNone(dca.dip_reason(plan, 290, 350))     # 17% under the 30-day high
        # accumulation buys stay out of the short-term BIST cap
        import bist_signals
        self.assertEqual(bist_signals.open_bist_tl(), 0)


class RiskTest(unittest.TestCase):
    def test_concentration_warnings(self):
        groups = [{"piyasa": "BIST", "symbol": "AKBNK.IS", "pair": "AKBNK.IS", "deger": 5000},
                  {"piyasa": "BIST", "symbol": "GARAN.IS", "pair": "GARAN.IS", "deger": 3000},
                  {"piyasa": "KRIPTO", "symbol": "BTCUSDT", "pair": "BTC/USDT", "deger": 20}]
        c = risk.concentration(groups, 50.0)
        self.assertEqual(c["toplam_tl"], 9000)
        self.assertEqual(c["varliklar"][0]["ad"], "AKBNK")
        self.assertTrue(any("AKBNK" in w for w in c["uyarilar"]))
        self.assertTrue(any("Banka" in w for w in c["uyarilar"]))

    def test_correlation_flags_moving_together(self):
        idx = [f"2026-08-{d:02d}" for d in range(1, 31)]
        base = pd.Series([100 + i + (i % 3) for i in range(30)], index=idx, dtype=float)
        noise = pd.Series([100 + ((i * 7) % 5) for i in range(30)], index=idx, dtype=float)
        corr = risk.correlations({"BTC": base, "ETH": base * 2, "THYAO": noise})
        warns = risk.correlation_warnings(corr, {"BTC", "ETH"})
        self.assertTrue(any("TEK pozisyon" in w for w in warns))


class Round3Test(unittest.TestCase):
    def setUp(self):
        _reset()

    def test_natural_alarm_parsing(self):
        import main
        a = main.parse_natural_alarm("THYAO 300 üstünde kapanırsa haber ver")
        self.assertEqual((a["kod"], a["fiyat"], a["yon"], a["tf"]), ("THYAO", 300.0, "ABOVE", None))
        a = main.parse_natural_alarm("btc 80000 altına düşerse günlük bazda uyar")
        self.assertEqual((a["kod"], a["yon"], a["tf"]), ("BTC", "BELOW", "1d"))
        a = main.parse_natural_alarm("SOL 4 saatlik 150,5 üstü kapanış olursa bildir")
        self.assertEqual((a["kod"], a["fiyat"], a["tf"]), ("SOL", 150.5, "4h"))
        self.assertIsNone(main.parse_natural_alarm("BTC 90000 olur mu sence"))       # no alarm word
        self.assertIsNone(main.parse_natural_alarm("BTC hakkında 90000 ne söylersin"))  # no direction
        self.assertIsNone(main.parse_natural_alarm("THYAO ne durumda"))

    def test_benchmark_compare(self):
        idx = ["2026-09-01", "2026-09-10"]
        series = {"XU100": pd.Series([100.0, 110.0], index=idx), "BTC": pd.Series([100.0, 90.0], index=idx),
                  "_son": {"XU100": 110.0, "BTC": 90.0}}
        rows = [{"acilis": "2026-09-01T10:00:00+03:00", "maliyet_tl": 1000.0, "deger_tl": 1050.0}]
        r = benchmark_mod().compare(rows, series, 36.5, today="2026-09-11")
        by = {b["ad"]: b for b in r["kiyas"]}
        self.assertEqual(r["portfoy_yuzde"], 5.0)
        self.assertEqual(by["BIST 100"]["yuzde"], 10.0)
        self.assertLess(by["BIST 100"]["fark"], 0)
        self.assertEqual(by["BTC"]["yuzde"], -10.0)
        self.assertGreater(by["BTC"]["fark"], 0)
        self.assertAlmostEqual(by["Mevduat %36.5"]["yuzde"], round(((1 + 0.365 / 365) ** 10 - 1) * 100, 2))
        self.assertIsNone(by["Gram altın"]["yuzde"])

    def test_after_sale_verdict(self):
        b = benchmark_mod()
        self.assertEqual(b.verdict(5.0), "erken satış")
        self.assertEqual(b.verdict(-4.0), "iyi çıkış")
        self.assertEqual(b.verdict(1.0), "nötr")

    def test_shadow_trade_net_of_costs(self):
        import shadow
        d = {"id": 1, "pair": "BTC/USDT", "kapanis": 100.0, "kademe_usd": 25, "karar": "AL",
             "sonuc": {"sonuc": "hedef", "cikis": 110.0}}
        t = shadow.trade(d)
        cost = 0.25 * (100 + 110) * (config.BACKTEST_FEE_PCT + config.BACKTEST_SLIPPAGE_PCT) / 100
        self.assertAlmostEqual(t["net"], round(0.25 * 10 - cost, 2))
        d2 = {**d, "piyasa": "BIST", "lot": 3, "kademe_usd": 300, "sonuc": {"sonuc": "stop", "cikis": 95.0}}
        self.assertLess(shadow.trade(d2)["net"], -15)

    def test_risk_news_matching(self):
        import risk_news
        c, s = {"SOL", "NEAR", "BTC"}, {"SASA"}
        self.assertEqual(risk_news.match("Solana network outage", c, s), ("SOL", "outage"))
        self.assertIsNone(risk_news.match("Bitcoin near record as hackers drain exchange", c, s))
        self.assertIsNone(risk_news.match("Drug case mentions SOL", c, s))
        self.assertEqual(risk_news.match("SASA için SPK soruşturma", c, s), ("SASA", "spk"))

    def test_rule_advice(self):
        import gate
        stats = [{"kural": "hacim", "gectiginde": {"n": 12, "isabet_yuzde": 70}, "kaldiginda": {"n": 10, "isabet_yuzde": 30}},
                 {"kural": "BTC kapı", "gectiginde": {"n": 12, "isabet_yuzde": 50}, "kaldiginda": {"n": 10, "isabet_yuzde": 52}},
                 {"kural": "R/R", "gectiginde": {"n": 5, "isabet_yuzde": 50}, "kaldiginda": {"n": 3, "isabet_yuzde": 10}}]
        adv = gate.rule_advice(stats)
        self.assertTrue(any(a.startswith("✅ hacim") for a in adv))
        self.assertTrue(any(a.startswith("🤔 BTC kapı") for a in adv))
        self.assertFalse(any("R/R" in a for a in adv))  # too few decisions

    def test_gold_fx_are_other_market(self):
        import assets
        self.assertEqual(assets.normalize("altın"), "GRAM_ALTIN")
        self.assertEqual(assets.normalize("dolar"), "USD")
        self.assertIsNone(assets.normalize("THYAO"))
        c = risk.concentration([{"piyasa": "DIGER", "symbol": "GRAM_ALTIN", "pair": "GRAM_ALTIN", "deger": 6000},
                                {"piyasa": "BIST", "symbol": "THYAO.IS", "pair": "THYAO.IS", "deger": 4000}], 48.0)
        self.assertEqual(c["varliklar"][0]["ad"], "Gram altın")
        self.assertEqual(c["varliklar"][0]["sektor"], "Altın")


class ModelRotationTest(unittest.IsolatedAsyncioTestCase):
    def test_slots_rotate_kimi_deepseek_glm(self):
        import llm
        from macro import TR
        from datetime import datetime as dt
        with unittest.mock.patch.object(config, "KIMI_API_KEY", "x"), \
                unittest.mock.patch.object(config, "GLM_API_KEY", "x"), \
                unittest.mock.patch.object(config, "DEEPSEEK_API_KEY", "y"):
            self.assertEqual(llm.slot_model(dt(2026, 9, 26, 11, 20, tzinfo=TR)), "kimi")
            self.assertEqual(llm.slot_model(dt(2026, 9, 26, 11, 35, tzinfo=TR)), "deepseek")
            self.assertEqual(llm.slot_model(dt(2026, 9, 26, 11, 50, tzinfo=TR)), "glm")
            self.assertEqual(llm.slot_model(dt(2026, 9, 26, 12, 5, tzinfo=TR)), "kimi")
            self.assertEqual(llm.pick_model(dt(2026, 9, 26, 11, 50, tzinfo=TR)), ["glm", "kimi", "deepseek"])
        with unittest.mock.patch.object(config, "KIMI_API_KEY", ""), \
                unittest.mock.patch.object(config, "GLM_API_KEY", ""), \
                unittest.mock.patch.object(config, "DEEPSEEK_API_KEY", "y"):
            self.assertEqual(llm.pick_model(dt(2026, 9, 26, 11, 20, tzinfo=TR)), ["deepseek"])  # no NVIDIA key

    async def test_failed_model_falls_back_to_the_next(self):
        import llm
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, patch
        ok = SimpleNamespace(usage=None, choices=[SimpleNamespace(message=SimpleNamespace(content="<think>x</think>Cevap"))])
        calls = []

        def client(model):
            async def create(**kw):
                calls.append(kw["model"])
                if model == "kimi":
                    raise TimeoutError("yavaş")
                return ok
            return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

        with (patch.object(llm, "_client", side_effect=client),
              patch.object(llm, "pick_model", return_value=["kimi", "deepseek", "glm"]),
              patch.object(llm.store, "load_state", return_value={"planlar": {}}),
              patch.object(llm.store, "load_history", return_value=[]),
              patch.object(llm.store, "append_history"),
              patch.object(llm.positions, "open_positions", return_value=[]),
              patch.object(llm.macro, "summary", new=AsyncMock(return_value={})),
              patch.object(llm.news, "get_news", new=AsyncMock(return_value=[])),
              patch.object(llm.news, "for_model", return_value=[])):
            reply, _, _ = await llm.analyze("BTC", {}, allow_state_update=False)
        self.assertEqual(calls, [config.KIMI_MODEL, config.DEEPSEEK_MODEL])
        self.assertTrue(reply.startswith("Cevap"))  # <think> removed
        self.assertIn(f"{llm.MODEL_NAMES['deepseek']} (yedek: Kimi K3 hata verdi)", reply)


class Round5Test(unittest.TestCase):
    def setUp(self):
        _reset()

    def test_portfolio_alarm_parse_and_fire(self):
        import pf_alarm
        self.assertEqual(pf_alarm.parse("kripto %-10"), {"piyasa": "KRIPTO", "tur": "yuzde", "deger": -10.0})
        self.assertEqual(pf_alarm.parse("kripto portföyüm %10 düşerse haber ver")["deger"], -10.0)
        self.assertEqual(pf_alarm.parse("bist 20000"), {"piyasa": "BIST", "tur": "seviye", "deger": 20000.0})
        self.assertIsNone(pf_alarm.parse("portföyüm nasıl"))
        down = pf_alarm.add({"piyasa": "KRIPTO", "tur": "yuzde", "deger": -10.0}, 200.0)
        up = pf_alarm.add({"piyasa": "BIST", "tur": "seviye", "deger": 20000.0}, 15000.0)
        self.assertEqual((down["esik"], down["yon"], up["yon"]), (180.0, "ALTINA", "USTUNE"))
        self.assertEqual(pf_alarm.check({"KRIPTO": 185.0, "BIST": 19000.0}), [])
        msgs = pf_alarm.check({"KRIPTO": 179.0, "BIST": 20500.0})
        self.assertEqual(len(msgs), 2)
        self.assertEqual(pf_alarm.check({"KRIPTO": 100.0, "BIST": 30000.0}), [])  # each fires once

    def test_model_scorecard(self):
        import model_score
        ds = [{"sonuc": {"sonuc": "hedef"}, "konsey": {"kimi": {"karar": "AL"}, "glm": {"karar": "PAS"}}},
              {"sonuc": {"sonuc": "stop"}, "konsey": {"kimi": {"karar": "AL"}, "glm": {"karar": "BEKLE"}}},
              {"sonuc": {"sonuc": "stop"}, "model": "deepseek", "karar": "PAS"},
              {"sonuc": {"sonuc": "açık"}, "konsey": {"kimi": {"karar": "AL"}}}]
        t = model_score.scorecard(ds)
        self.assertEqual((t["kimi"]["n"], t["kimi"]["isabet"], t["kimi"]["al_isabet"]), (2, 50, 50))
        self.assertEqual((t["glm"]["n"], t["glm"]["isabet"]), (2, 50))
        self.assertEqual(t["deepseek"]["isabet"], 100)
        self.assertIn("Kimi K3", model_score.text(ds))

    def test_strength_ranking(self):
        import strength
        weeks = 40
        idx = pd.DataFrame({"close": [100.0] * weeks})
        def frame(slope, vol=100.0):
            closes = [100.0 + slope * i for i in range(weeks)]
            return pd.DataFrame({"close": closes, "volume": [vol] * weeks,
                                 "sma20": [c - abs(slope) * 5 for c in closes], "sma50": [c - abs(slope) * 10 for c in closes]})
        rows = {"GUCLU": strength.metrics(frame(1.0), idx), "ORTA": strength.metrics(frame(0.3), idx),
                "ZAYIF": strength.metrics(frame(-0.5), idx)}
        ranked = strength.rank(rows)
        self.assertEqual([r["hisse"] for r in ranked], ["GUCLU", "ORTA", "ZAYIF"])
        self.assertGreater(ranked[0]["rs13"], 0)

    def test_vote_json_extraction(self):
        import llm
        self.assertEqual(llm._json_obj('<think>..</think>Sonuç: {"karar": "AL", "neden": "hacimli kırılım"}'),
                         {"karar": "AL", "neden": "hacimli kırılım"})
        self.assertEqual(llm.model_of("yorum\n\n🧠 GLM 5.3"), "glm")
        self.assertEqual(llm.model_of("yorum\n\n🧠 DeepSeek V4 Pro (yedek: Kimi K3 hata verdi)"), "deepseek")


class EngineTest(unittest.TestCase):
    @staticmethod
    def frame(closes, spread=1.0, vol=100.0):
        import market
        df = pd.DataFrame({"open": closes, "close": closes, "high": [c + spread for c in closes],
                           "low": [c - spread for c in closes], "volume": [vol] * len(closes),
                           "open_time": [i * 3_600_000 for i in range(len(closes))]})
        return market.add_indicators(df)

    def test_uptrend_structure_and_bos(self):
        import structure
        # zig-zag climbing: each swing high and low higher than the last
        closes = []
        base = 100.0
        for k in range(8):
            closes += [base + i for i in range(6)] + [base + 5 - i for i in range(1, 4)]
            base += 4
        closes += [base + 6]  # close above the last swing high
        st = structure.structure(self.frame(closes), left=2, right=2)
        self.assertEqual(st["trend"], "yükseliş")
        self.assertIn("BOS", st["bos"])

    def test_liquidity_sweep_and_reclaim(self):
        import structure
        closes = [100.0] * 30
        df = self.frame(closes)
        daily = pd.DataFrame({"high": [101.0, 102.0], "low": [98.0, 99.0]})
        df.loc[df.index[-1], ["low", "close"]] = [98.5, 100.0]  # wick below yesterday's low 99, close back above
        liq = structure.liquidity(df, daily, None)
        self.assertTrue(any("alttan süpürüldü" in s for s in liq["supurme"]))

    def test_volume_profile_poc(self):
        import structure
        closes = [100.0] * 40 + [110.0] * 5
        vp = structure.volume_profile(self.frame(closes, spread=0.5))
        self.assertAlmostEqual(vp["poc"], 100.0, delta=1.0)
        self.assertEqual(vp["fiyat_konumu"], "değer alanının üstünde")

    def test_confluence_is_scaled_without_a_plan(self):
        import structure
        c = structure.confluence(htf=["yükseliş", "yükseliş"], level_ok=None, sweep_bull=True, sweep_bear=False,
                                 volume_ratio=2.0, mom={"rsi": 60, "macd": "MACD pozitif, histogram artıyor", "uyumsuzluk": None},
                                 deriv=None, trigger=None, rr=None)
        self.assertEqual(c["skor"], round((20 + 15 + 10 + 7) / 55 * 100))
        self.assertIn("olasılığı DEĞİL", c["not"])

    def test_stage_two_and_four(self):
        import structure
        up = pd.DataFrame({"close": [100 + i for i in range(60)], "high": [101 + i for i in range(60)],
                           "low": [99 + i for i in range(60)], "volume": [1.0] * 60})
        down = up.iloc[::-1].reset_index(drop=True)
        self.assertEqual(structure.stage(up)["stage"], 2)
        self.assertEqual(structure.stage(down)["stage"], 4)


class FundamentalsTest(unittest.TestCase):
    def data(self):
        # year-to-date income items, point-in-time balance items
        return {
            "2023/6": {"3C": 380.0, "3D": 95.0, "3DF": 38.0, "4CAB": 9.0, "3Z": 28.0, "4CB": 18.0, "3HC": -9.0, "3I": 33.0, "3HA": 2.0},
            "2023/12": {"3C": 800.0, "3D": 200.0, "3DF": 80.0, "4CAB": 18.0, "3Z": 60.0, "4CB": 45.0, "3HC": -18.0, "3I": 70.0, "3HA": 4.0},
            "2024/6": {"3C": 400.0, "3D": 100.0, "3DF": 40.0, "4CAB": 10.0, "3Z": 30.0, "4CB": 20.0, "3HC": -10.0, "3I": 35.0, "3HA": 2.0,
                       "2AA": 100.0, "2BA": 100.0, "1AA": 50.0, "2O": 300.0, "2OA": 10.0, "1AC": 80.0, "1AF": 60.0},
            "2024/12": {"3C": 900.0, "3D": 220.0, "3DF": 90.0, "4CAB": 20.0, "3Z": 70.0, "4CB": 50.0, "3HC": -20.0, "3I": 80.0, "3HA": 5.0},
            "2025/6": {"3C": 500.0, "3D": 130.0, "3DF": 55.0, "4CAB": 12.0, "3Z": 40.0, "4CB": 30.0, "3HC": -12.0, "3I": 45.0, "3HA": 3.0,
                       "2AA": 110.0, "2BA": 100.0, "1AA": 60.0, "2O": 340.0, "2OA": 10.0, "1AC": 90.0, "1AF": 66.0},
        }

    def test_ttm_and_metrics(self):
        import fundamentals
        d = self.data()
        self.assertEqual(fundamentals.ttm(d, "3C", "2025/6"), 900 + 500 - 400)
        f = fundamentals.compute("XI_29", d, 20.0, {"2025/6": 40.0, "2024/6": 32.0})
        self.assertEqual(f["son_donem"], "2025/6")
        self.assertEqual(f["ciro_ttm"], 1000.0)
        self.assertEqual(f["ciro_buyume_tl_yuzde"], round((1000 / (800 + 400 - 380) - 1) * 100, 1))  # vs TTM a year earlier
        self.assertEqual(f["ciro_buyume_usd_yuzde"], round((1000 / 40 / (820 / 32) - 1) * 100, 1))
        self.assertEqual(f["piyasa_degeri_tl"], 200)
        self.assertEqual(f["fk"], round(200 / 80, 1))  # NI TTM = 70 + 40 - 30
        self.assertEqual(f["net_borc"], 150)
        self.assertEqual(f["kirmizi_bayraklar"], [])

    def test_red_flags(self):
        import fundamentals
        d = self.data()
        d["2025/6"]["4CB"] = -40.0          # cash burn while profitable
        d["2025/6"]["1AF"] = 200.0          # inventory explodes
        f = fundamentals.compute("XI_29", d, 20.0)
        joined = " ".join(f["kirmizi_bayraklar"])
        self.assertIn("serbest nakit akımı negatif", joined)
        self.assertIn("stoklar", joined)
        s = fundamentals.score(f, {"stage": 4})
        self.assertIn("Stage 4", s["etiket"])
        self.assertIn("olasılığı DEĞİL", s["not"])


class USEngineTest(unittest.TestCase):
    def test_quarters_from_ytd_and_tag_switch(self):
        import us_fund
        old_tag = [{"start": "2024-01-01", "end": "2024-03-31", "val": 100, "filed": "2024-05-01"},
                   {"start": "2024-01-01", "end": "2024-06-30", "val": 210, "filed": "2024-08-01"}]
        new_tag = [{"start": "2024-01-01", "end": "2024-09-30", "val": 330, "filed": "2024-11-01"},
                   {"start": "2024-10-01", "end": "2024-12-31", "val": 130, "filed": "2025-02-01"},
                   {"start": "2025-01-01", "end": "2025-03-31", "val": 140, "filed": "2025-05-01"}]
        facts = {"us-gaap": {"Revenues": {"units": {"USD": old_tag}},
                             "RevenueFromContractWithCustomerExcludingAssessedTax": {"units": {"USD": new_tag}}}}
        rows = us_fund._entries(facts, ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues"])
        q = us_fund.quarters(rows)
        self.assertEqual(q, {"2024-03-31": 100.0, "2024-06-30": 110.0, "2024-09-30": 120.0,
                             "2024-12-31": 130.0, "2025-03-31": 140.0})
        self.assertEqual(us_fund.ttm(q), 110 + 120 + 130 + 140)

    def test_flags_and_score_are_not_probabilities(self):
        import us_fund
        f = {"ceyreklik_ciro_buyume_yuzde": [30, 20, 10], "ivme": "YAVAŞLIYOR", "faaliyet_marj_yuzde": 10,
             "faaliyet_marj_gecen_yil_yuzde": 15, "sbc_ciro_yuzde": 20, "hisse_sayisi_yillik_degisim_yuzde": 5,
             "analist": {"tahminler": {"+1y": {"revizyon_30g_yuzde": -4}},
                         "surprizler": [{"surpriz_yuzde": -3.0}]}}
        fl = us_fund.flags(f)
        self.assertGreaterEqual(len(fl["uyarilar"]), 5)
        f.update(fl, brut_marj_yuzde=70, ciro_buyume_yuzde=10)
        sc = us_fund.score(f, {"rs_spy": {"6a": -5}, "stage": {"stage": 4}})
        self.assertEqual(sc["durum"], "TEZ ZAYIFLIYOR")
        self.assertIn("olasılığı DEĞİL", sc["not"])

    def test_us_plan_key_and_calendar(self):
        import us
        from datetime import date
        self.assertEqual(us.key("aapl"), "AAPL.US")
        self.assertEqual(us.ticker("AAPL.US"), "AAPL")
        self.assertFalse(us.trading_day(date(2026, 11, 26)))  # Thanksgiving
        self.assertTrue(us.trading_day(date(2026, 11, 27)))   # half day, still open

    def test_us_card_labels_sources_and_earnings_context(self):
        import pandas as pd
        import us
        import us_card
        import us_events
        self.assertEqual(str(us_events.ny_time("2025-08-01T00:30:25")), "2025-07-31 16:30:25")      # summer: 8 hours ahead
        self.assertEqual(str(us_events.ny_time("2026-01-13T16:41:09")), "2026-01-13 06:41:09")      # winter: 10 hours ahead
        ms = lambda day: int(datetime.fromisoformat(day + "T09:30").replace(tzinfo=us.NY).timestamp() * 1000)
        days = ["2025-07-30", "2025-07-31", "2025-08-01", "2025-08-04"]
        d = pd.DataFrame({"open_time": [ms(x) for x in days], "close": [100.0, 100.0, 106.0, 108.12]})
        spy = pd.DataFrame({"open_time": [ms(x) for x in days], "close": [500.0, 500.0, 505.0, 505.0]})
        r = us_events.last_reaction(d, spy, ["2025-08-01T00:30:25"])     # released after the close of 31 July
        self.assertEqual((r["tepki_gunu"], r["tepki_yuzde"], r["spy_gore_yuzde"], r["o_gunden_beri_yuzde"], r["seans_once"]),
                         ("2025-08-01", 6.0, 5.0, 2.0, 1))
        self.assertEqual(us_events.last_reaction(d, spy, ["2025-07-31T14:30:00"])["tepki_gunu"], "2025-07-31")   # before the open
        today = date(2026, 10, 7)
        self.assertEqual(us_card.earnings("2026-10-09", None, today)["risk"], "YÜKSEK")
        self.assertEqual(us_card.earnings("2026-10-19", None, today)["risk"], "ORTA")
        self.assertEqual(us_card.earnings("2026-11-17", "2026-11-20", today)["kaynak"], "şirket takvimi (Yahoo)")
        est = us_card.earnings(None, "2026-11-20", today)
        self.assertEqual((est["risk"], est["kaynak"][:6]), ("DÜŞÜK", "tahmin"))
        self.assertEqual(us_card.earnings(None, None, today)["risk"], "BİLİNMİYOR")
        rev = lambda **k: us_card.revisions({"tahminler": {"+1y": k}})["etiket"]
        self.assertEqual([rev(revizyon_30g_yuzde=2.5, yukari_30g=46, asagi_30g=0), rev(revizyon_30g_yuzde=-3.0), rev(revizyon_30g_yuzde=0.2, yukari_30g=3, asagi_30g=3), rev()],
                         ["YUKARI", "AŞAĞI", "YATAY", "BİLİNMİYOR"])
        val = lambda **k: us_card.valuation(k)["etiket"]
        self.assertEqual([val(ileri_fk=48.0, peg=1.2), val(ileri_fk=12.0, peg=0.9), val(ileri_fk=22.0, peg=1.8), val()],
                         ["PAHALI", "UCUZ", "MAKUL", "BİLİNMİYOR"])
        f = {"hisse": "NVDA", "fiyat": 237.13, "son_ceyrek": "2026-07-26", "ileri_fk": 48.0, "peg": 1.2, "fcf_verimi_yuzde": 2.2,
             "puan": {"skor": 95, "durum": "BİRİKTİRME BÖLGESİ"},
             "analist": {"sektor": "Technology", "endustri": "Semiconductors", "sonraki_bilanco": "2026-10-09",
                         "tahminler": {"+1y": {"revizyon_30g_yuzde": -2.0}}, "surprizler": [{"ceyrek": "2Q2026", "surpriz_yuzde": 6.2}]},
             "teknik": {"trend": {"günlük": "yükseliş", "haftalık": "karışık/yatay"}, "hizalama": "fiyat > 50G > 200G (güçlü)",
                        "zirveye_uzaklik_yuzde": -1.0, "rs_spy": {"6a": 16.5}, "rs_qqq_6a": 5.6, "rs_sektor_6a": -34.9, "sektor_etf": "SOXX"}}
        now = datetime(2026, 10, 7, 19, 0, tzinfo=us_card.alerts_store.TR)
        c = us_card.build(f, r, None, "2026-10-06", None, now)
        self.assertEqual((c["guc"]["spy"], c["guc"]["qqq"], c["guc"]["sektor"], c["bilanco"]["risk"]), ("GÜÇLÜ", "NÖTR", "ZAYIF", "YÜKSEK"))
        self.assertEqual(len(c["kaynaklar"]), 4)
        said = us_card.text(c)
        self.assertIn("Bilanço 2 gün sonra", said)
        self.assertIn("SEC EDGAR (8-K madde 2.02, resmi) — 2025-07-31 16:30 New York", said)
        self.assertIn("AL/SAT önerisi değildir", said)
        self.assertNotIn("🟢", said)

    def test_us_portfolio_sees_one_theme_behind_several_names(self):
        import numpy as np
        import pandas as pd
        import us_portfolio
        idx = pd.date_range("2025-10-01", periods=260, freq="B")
        rng = np.random.default_rng(3)
        mkt, own = rng.normal(0, 0.01, 260), lambda: rng.normal(0, 0.004, 260)
        price = lambda r: pd.Series(100 * np.cumprod(1 + r), index=idx)
        closes = {"NVDA": price(2 * mkt + own()), "AMD": price(2 * mkt + own()), "COST": price(0.5 * mkt + own())}
        factors = {"SPY": price(mkt), "QQQ": price(1.3 * mkt), "^TNX": pd.Series(4.5 + np.cumsum(-10 * mkt), index=idx),
                   "^VIX": pd.Series(18 * np.exp(np.cumsum(-5 * mkt + rng.normal(0, 0.001, 260))), index=idx).clip(9, 80)}
        r = us_portfolio.analyze({"NVDA": 5000.0, "AMD": 3000.0, "COST": 2000.0}, closes,
                                 {"NVDA": "Technology", "AMD": "Technology", "COST": "Consumer Defensive"}, factors)
        self.assertEqual(r["sektor_yuzde"]["Technology"], 80.0)
        self.assertEqual(r["tema"]["Yarı iletken"], {"agirlik_yuzde": 80.0, "hisseler": ["AMD", "NVDA"]})
        self.assertEqual(r["korelasyon"]["en_bagli"][0]["cift"], "AMD–NVDA")
        self.assertAlmostEqual(r["beta"]["SPY"], 1.7, delta=0.1)                     # 0.8 x 2 + 0.2 x 0.5
        spy = r["senaryolar"][0]
        self.assertAlmostEqual(spy["portfoy_yuzde"], -17.0, delta=1.0)
        self.assertAlmostEqual(spy["tutar_usd"], -1700.0, delta=100.0)
        self.assertLess(r["senaryolar"][2]["portfoy_yuzde"], 0)                      # yields up: these fell with them
        self.assertTrue(any("Yarı iletken" in n for n in r["dikkat"]) and any("NVDA portföyün %50" in n for n in r["dikkat"]))
        self.assertIn("Öneri içermez", us_portfolio.text({**r, "kaynaklar": [], "uretildi": "x"}))

    def test_us_calendar_is_computed_for_any_year(self):
        import us
        self.assertEqual(sorted(us.holidays(2026)), ["2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25",
                                                     "2026-06-19", "2026-07-03", "2026-09-07", "2026-11-26", "2026-12-25"])
        self.assertIn("2027-12-24", us.holidays(2027))            # Christmas on a Saturday: observed on Friday
        self.assertIn("2027-07-05", us.holidays(2027))            # 4 July on a Sunday: observed on Monday
        self.assertNotIn("2021-12-31", us.holidays(2021))         # New Year's Day on a Saturday is not observed
        self.assertNotIn("2022-01-01", us.holidays(2022))
        self.assertTrue(us.half_day(date(2025, 7, 3)) and us.half_day(date(2026, 12, 24)))
        self.assertFalse(us.half_day(date(2027, 12, 24)))         # closed that day, so not a half day
        ny = lambda s: datetime.fromisoformat(s).replace(tzinfo=us.NY)
        self.assertEqual([us.phase(ny(t)) for t in ("2026-10-07T03:59", "2026-10-07T08:00", "2026-10-07T09:30", "2026-10-07T16:00",
                                                    "2026-10-07T20:00", "2026-11-27T13:00", "2026-11-26T10:00", "2026-10-10T10:00")],
                         ["CLOSED", "PREMARKET", "REGULAR_OPEN", "AFTER_HOURS", "CLOSED", "AFTER_HOURS", "CLOSED", "CLOSED"])
        # Turkey has no DST, New York has: the same session is 16:30 in October and 17:30 after the US clocks go back
        self.assertIn("bugün 16:30–23:00 (Türkiye)", us.session_text(ny("2026-10-07T10:00")))
        self.assertIn("bugün 17:30–00:00 (Türkiye)", us.session_text(ny("2026-11-03T10:00")))
        self.assertIn("27.11 17:30–21:00 (Türkiye) · yarım gün", us.session_text(ny("2026-11-25T17:00")))   # skips Thanksgiving


class WatchlistTest(unittest.TestCase):
    def setUp(self):
        _reset()

    def test_defaults_and_edit(self):
        import watchlist
        lists = watchlist.load()
        self.assertEqual((len(lists["KRIPTO"]), len(lists["BIST"]), len(lists["ABD"])), (16, 35, 53))
        self.assertEqual(watchlist.add("KRIPTO", ["BTC", "TAO"]), ["TAO"])
        self.assertEqual(watchlist.remove(["TAO", "THYAO"]), ["TAO", "THYAO"])
        self.assertNotIn("THYAO", watchlist.load()["BIST"])

    def test_row_and_text(self):
        import market
        import watchlist
        n = 260
        close = pd.Series([100 + i * 0.5 for i in range(n)], dtype=float)
        d = market.add_indicators(pd.DataFrame({"open_time": range(n), "open": close, "high": close + 1, "low": close - 1,
                                                "close": close, "volume": 1000.0}))
        r = watchlist._row("THYAO", 230.0, 225.0, d)
        self.assertAlmostEqual(r["gun_yuzde"], 2.22, places=2)
        self.assertEqual(r["trend"], "↗ güçlü")
        txt = watchlist.text("BIST", [r, {"kod": "XYZ", "hata": "yok"},
                                      {**r, "kod": "NEW", "gun_yuzde": None, "hafta_yuzde": None, "rsi": None}])
        self.assertIn("🟢 THYAO 230₺ %+2.22", txt)
        self.assertIn("XYZ: veri alınamadı", txt)
        self.assertIn("NEW 230₺ %—", txt)

    def test_code_and_picker(self):
        import main
        self.assertEqual([main._takip_code(a) for a in ("btc/usdt", "PEPEUSDT", "thyao.is", "AAPL.US", "USDT")],
                         ["BTC", "PEPE", "THYAO", "AAPL", "USDT"])
        w = {"piyasa": "ABD", "secili": ["NVDA"], "sayfa": 0}
        kb = main.takip_picker(w).inline_keyboard
        texts = [b.text for row in kb for b in row]
        self.assertIn("✅NVDA", texts)
        self.assertIn("1/3", texts)  # 53 US codes, 24 per page
        self.assertIn("📊 Durum (1)", texts)


def benchmark_mod():
    import benchmark
    return benchmark


class ToolsTest(unittest.TestCase):
    def setUp(self):
        _reset()

    @staticmethod
    def bar(close, sma50=100.0, rsi=50.0, volume=100.0, avg=100.0):
        return pd.Series({"close": close, "sma20": sma50, "sma50": sma50, "sma200": sma50, "rsi14": rsi,
                          "volume": volume, "vol_avg20": avg})

    def test_sma_cross_only_on_crossing(self):
        a = {"gosterge": "sma50", "yon": "ustu", "deger": None}
        self.assertTrue(tools.crossed(a, self.bar(99), self.bar(101))[0])
        self.assertFalse(tools.crossed(a, self.bar(101), self.bar(102))[0])  # already above: no repeat
        self.assertTrue(tools.crossed({**a, "yon": "alti"}, self.bar(101), self.bar(99))[0])

    def test_rsi_and_volume_cross(self):
        rsi = {"gosterge": "rsi", "yon": "alti", "deger": 30}
        self.assertTrue(tools.crossed(rsi, self.bar(1, rsi=33), self.bar(1, rsi=28))[0])
        self.assertFalse(tools.crossed(rsi, self.bar(1, rsi=28), self.bar(1, rsi=25))[0])
        vol = {"gosterge": "hacim", "yon": "ustu", "deger": 2}
        self.assertTrue(tools.crossed(vol, self.bar(1, volume=150), self.bar(1, volume=250))[0])
        self.assertFalse(tools.crossed(vol, self.bar(1, volume=250), self.bar(1, volume=300))[0])

    def test_indicator_alarm_validation(self):
        with self.assertRaises(ValueError):
            tools.ind_create("BIST", "THYAO", "sma50", "ustu", "4h")  # BIST is daily/weekly only
        with self.assertRaises(ValueError):
            tools.ind_create("KRIPTO", "BTC", "rsi", "alti", "4h", 150)
        a = tools.ind_create("KRIPTO", "btc", "hacim", "alti", "1d", 2)
        self.assertEqual((a["kod"], a["yon"], a["son_mum"]), ("BTC", "ustu", None))
        self.assertEqual(tools.ind_delete(a["id"])["id"], a["id"])
        self.assertEqual(tools.ind_alerts(), [])

    def test_dividend_projection(self):
        divs = [{"tarih": "2024-10-01", "tutar": 1.0}, {"tarih": "2025-05-10", "tutar": 2.0},
                {"tarih": "2025-11-20", "tutar": 0.5}]
        pr = tools.project(divs, 10, date(2025, 12, 1))
        self.assertEqual(pr["son12"], 25.0)
        self.assertEqual(pr["onceki12"], 10.0)
        self.assertEqual(pr["aylar"], {"2026-05": 20.0, "2026-11": 5.0})

    def test_best_of(self):
        rows = [{"kod": "A", "skor": 60, "fk": -3, "borc": 2.0}, {"kod": "B", "skor": 70, "fk": 9, "borc": 0.5},
                {"kod": "C", "skor": 50, "fk": 12, "borc": None}]
        best = tools.best_of(rows)
        self.assertEqual((best["skor"], best["fk"], best["borc"]), ("B", "B", "B"))


if __name__ == "__main__":
    unittest.main()
