"""Focused BIST signal and purchase checks. Run with: python -m unittest test_bist"""
import asyncio
import copy
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pandas as pd

import bist
import bist_signals
import alerts_store
import backtest
import config
import conversation_store
import gate
import llm
import main
import positions
import web_sync


def daily_frame(last_close=104.0, last_volume=150.0):
    closes = [100.0] * 60 + [last_close]
    df = pd.DataFrame({
        "close": closes, "high": [102.0] * 60 + [max(last_close + 1, 104.0)],
        "low": [99.8] * 60 + [101.0], "volume": [100.0] * 60 + [last_volume],
        "atr14": [2.0] * 61, "sma20": [100.0] * 60 + [101.0],
        "sma50": [99.0] * 61, "sma200": [98.0] * 61, "rsi14": [60.0] * 61,
        "vol_avg20": [100.0] * 61,
        "open_time": list(range(61)),
    })
    return df


def weekly_up():
    """30 weekly bars in an uptrend: close above the weekly SMA20."""
    return pd.DataFrame({"close": [90.0 + i for i in range(30)], "sma20": [85.0 + i for i in range(30)],
                         "open_time": list(range(30))})


class SetupTests(unittest.TestCase):
    def test_october_bist30_change(self):
        with patch.object(bist, "now_tr", return_value=datetime(2026, 9, 25, tzinfo=bist.TR)):
            self.assertIn("DSTKF", bist.watchlist())
        with patch.object(bist, "now_tr", return_value=datetime(2026, 10, 1, tzinfo=bist.TR)):
            self.assertIn("TRMET", bist.watchlist())
            self.assertNotIn("DSTKF", bist.watchlist())

    def test_holiday_and_half_day_close_entry_gate(self):
        self.assertFalse(bist.session_open(datetime(2026, 10, 29, 11, tzinfo=bist.TR)))
        self.assertTrue(bist.session_open(datetime(2026, 10, 28, 12, tzinfo=bist.TR)))
        self.assertFalse(bist.session_open(datetime(2026, 10, 28, 13, tzinfo=bist.TR)))
        self.assertFalse(bist.session_open(datetime(2027, 1, 4, 11, tzinfo=bist.TR)))

    def test_breakout_and_pullback_are_distinct(self):
        idx = pd.DataFrame({"close": [100.0] * 61})
        breakout_zones = {"direncler": [
            {"alt": 101.0, "ust": 102.0, "orta": 101.5, "dokunma": 3},
            {"alt": 110.0, "ust": 112.0, "orta": 111.0, "dokunma": 2}]}
        with patch.object(bist_signals.market, "sr_zones", return_value=breakout_zones):
            breakout = bist_signals._setup(daily_frame(), pd.DataFrame(), idx)
        self.assertEqual(breakout["strateji"], "Hacimli direnç kırılımı")
        # Medium-term target: the 111 resistance is closer than +8%, so the projection is used instead.
        self.assertAlmostEqual(breakout["hedef"],
                               max(104.0, breakout["tetik"]) * (1 + config.BIST_MIN_TARGET_PCT / 100), places=2)
        self.assertIn("projeksiyon", breakout["hedef_turu"])
        self.assertLessEqual(breakout["iptal"], 104.0 - 1.5 * 2.0)  # stop at least 1.5 ATR away

        pullback_zones = {"direncler": [
            {"alt": 109.0, "ust": 111.0, "orta": 110.0, "dokunma": 2}]}
        with patch.object(bist_signals.market, "sr_zones", return_value=pullback_zones):
            pullback = bist_signals._setup(daily_frame(103.0, 100.0), pd.DataFrame(), idx)
        self.assertEqual(pullback["strateji"], "Trend içi geri çekilme")
        self.assertEqual(pullback["tetik"], 104.0)
        self.assertLess(pullback["iptal"], 100)

    def test_weak_relative_strength_is_rejected(self):
        idx = pd.DataFrame({"close": [100.0] * 40 + [100.0 + i * 0.5 for i in range(21)]})  # index +10%, stock +4%
        self.assertIsNone(bist_signals._setup(daily_frame(), pd.DataFrame(), idx))


class FlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_bist_comment_cannot_rewrite_a_plan(self):
        reply = 'Kısa yorum<STATE>{"planlar":{"THYAO.IS":{"tetik":1,"iptal":0.5}}}</STATE>'
        response = SimpleNamespace(usage=None, choices=[SimpleNamespace(message=SimpleNamespace(content=reply))])
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
            create=AsyncMock(return_value=response))))
        apply_update = Mock()
        with (patch.object(llm, "_client", return_value=client),
              patch.object(llm.store, "load_state", return_value={"planlar": {}}),
              patch.object(llm.store, "load_history", return_value=[]),
              patch.object(llm.store, "apply_update", apply_update),
              patch.object(llm.store, "append_history"),
              patch.object(llm.positions, "open_positions", return_value=[]),
              patch.object(llm.macro, "summary", new=AsyncMock(return_value={})),
              patch.object(llm.news, "get_news", new=AsyncMock(return_value=[])),
              patch.object(llm.news, "for_model", return_value=[])):
            visible, warnings, plans = await llm.analyze("[BIST ŞİMDİ AL] THYAO", {}, allow_state_update=False)
        self.assertEqual(visible.split("\n\n🧠")[0], "Kısa yorum")  # model tag is appended below the reply
        self.assertEqual(warnings, [])
        self.assertEqual(plans, [])
        apply_update.assert_not_called()

    async def test_gate_accepts_same_calendar_day_with_different_vendor_timestamps(self):
        now = datetime(2026, 9, 25, 12, 0, tzinfo=bist.TR)
        stock = daily_frame()
        stock["open_time"] = [int((now - timedelta(days=60 - i)).timestamp() * 1000) for i in range(61)]
        index = stock.copy()
        index["close"] = 100.0
        index["open_time"] += 30 * 60 * 1000
        hour_bar = pd.Series({"open_time": int((now - timedelta(hours=1, minutes=30)).timestamp() * 1000),
                              "close_time": int((now - timedelta(minutes=30)).timestamp() * 1000),
                              "close": 104.0})
        with (patch.object(bist_signals.bist, "fetch", new=AsyncMock(side_effect=[stock, weekly_up(), index])),
              patch.object(bist_signals.market, "add_indicators", side_effect=lambda df: df),
              patch.object(bist_signals.bist, "session_open", return_value=True),
              patch.object(bist_signals.bist, "index_gate", new=AsyncMock(return_value={
                  "durum": "AÇIK", "xu100_kapanis": 100, "sma50": 99, "sma200": 98, "usdtry_baski": False})),
              patch.object(bist_signals.time, "time", return_value=now.timestamp()),
              patch.object(bist, "budget_tl", return_value=5000),
              patch.object(bist_signals.positions, "open_positions", return_value=[])):
            result = await bist_signals.evaluate(None, symbol="THYAO.IS", entry=104.0, iptal=100.0,
                                                 hedef=115.0, level=102.0, hour_bar=hour_bar, volume_ok=True)
        self.assertTrue(result["ok"], result["kalan"])
        with (patch.object(bist_signals.bist, "fetch", new=AsyncMock(side_effect=[stock, weekly_up(), index])),
              patch.object(bist_signals.market, "add_indicators", side_effect=lambda df: df),
              patch.object(bist_signals.bist, "session_open", return_value=True),
              patch.object(bist_signals.bist, "index_gate", new=AsyncMock(return_value={
                  "durum": "AÇIK", "xu100_kapanis": 100, "sma50": 99, "sma200": 98, "usdtry_baski": False})),
              patch.object(bist_signals.time, "time", return_value=now.timestamp()),
              patch.object(bist, "budget_tl", return_value=None),
              patch.object(bist_signals.positions, "open_positions", return_value=[])):
            blocked = await bist_signals.evaluate(None, symbol="THYAO.IS", entry=104.0, iptal=100.0,
                                                  hedef=115.0, level=102.0, hour_bar=hour_bar, volume_ok=True)
        self.assertFalse(blocked["ok"])
        self.assertIn("bütçe/adet", blocked["kalan"])

    async def test_yahoo_1800_price_only_row_is_not_an_hour(self):
        bist._cache.clear()
        day = datetime(2026, 9, 25, tzinfo=bist.TR)
        stamps = [int((day + timedelta(hours=17, minutes=30)).timestamp()),
                  int((day + timedelta(hours=18)).timestamp())]
        payload = {"chart": {"result": [{"timestamp": stamps, "indicators": {"quote": [{
            "open": [100, 101], "high": [101, 101], "low": [99, 101],
            "close": [100, 101], "volume": [1000, 0]}]}}]}}
        response = unittest.mock.Mock()
        response.json.return_value = payload
        client = unittest.mock.Mock()
        client.get = AsyncMock(return_value=response)
        with patch.object(bist, "now_tr", return_value=day + timedelta(hours=19)):
            df = await bist.fetch(client, "THYAO", "1h")
        self.assertEqual(len(df), 1)
        self.assertGreater(df.iloc[0].close_time, df.iloc[0].open_time)
        bist._cache.clear()

    async def test_weekly_downtrend_blocks_the_gate(self):
        now = datetime(2026, 9, 25, 18, 40, tzinfo=bist.TR)
        stock = daily_frame()
        stock["open_time"] = [int((now.replace(hour=10) - timedelta(days=60 - i)).timestamp() * 1000) for i in range(61)]
        weekly = weekly_up()
        weekly.loc[weekly.index[-1], "close"] = 90.0  # weekly close below weekly SMA20
        with (patch.object(bist_signals.bist, "fetch", new=AsyncMock(side_effect=[stock, weekly, stock])),
              patch.object(bist_signals.market, "add_indicators", side_effect=lambda df: df),
              patch.object(bist_signals.bist, "now_tr", return_value=now),
              patch.object(bist_signals.bist, "index_gate", new=AsyncMock(return_value={
                  "durum": "AÇIK", "xu100_kapanis": 100, "sma50": 99, "sma200": 98, "usdtry_baski": False})),
              patch.object(bist, "budget_tl", return_value=5000),
              patch.object(bist_signals.positions, "open_positions", return_value=[])):
            g = await bist_signals.evaluate(None, symbol="THYAO.IS", entry=104.0, iptal=99.0, hedef=115.0,
                                            level=102.0, hour_bar=stock.iloc[-1], volume_ok=True, bar_tf="1d")
        self.assertIn("haftalık trend", g["kalan"])
        self.assertNotIn("seans", [c["kural"] for c in g["kurallar"]])  # daily mode: decided after the close

    async def test_daily_mode_confirms_on_the_final_daily_close(self):
        now = datetime(2026, 9, 25, 18, 40, tzinfo=bist.TR)
        yesterday = (now - timedelta(days=1)).date().isoformat()
        holder = {"state": {"planlar": {"THYAO.IS": {
            "bist_aday": True, "aday_gunu": yesterday, "guncelleme": int(now.timestamp()) - 3600,
            "tetik": 100.0, "teyit": 100.0, "iptal": 95.0, "hedef": 115.0, "pozisyon": False, "son_saat": None}}}}
        day = lambda d, c: {"open_time": int(d.replace(hour=10).timestamp() * 1000),
                            "close_time": int(d.replace(hour=18, minute=10).timestamp() * 1000), "close": c}
        bars = pd.DataFrame([day(now - timedelta(days=1), 99), day(now, 101)])
        evaluate = AsyncMock(return_value={"ok": True})
        with (patch.object(bist_signals.config, "BIST_CONFIRM_TF", "1d"),
              patch.object(bist_signals.store, "load_state", side_effect=lambda: copy.deepcopy(holder["state"])),
              patch.object(bist_signals.store, "save_state", side_effect=lambda s: holder.__setitem__("state", copy.deepcopy(s))),
              patch.object(bist_signals.bist, "fetch", AsyncMock(return_value=bars)),
              patch.object(bist_signals.bist, "now_tr", return_value=now),
              patch.object(bist_signals.time, "time", return_value=now.timestamp()),  # else the candidate ages out on the real clock
              patch.object(bist_signals.market, "add_indicators", side_effect=lambda df: df),
              patch.object(bist_signals, "evaluate", evaluate)):
            self.assertEqual(await bist_signals.hourly_check(), [])  # no hourly triggers for BIST any more
            events = await bist_signals.daily_check()
            self.assertEqual([e["tur"] for e in events], ["kapi"])
            self.assertEqual(await bist_signals.daily_check(), [])   # same daily bar: nothing new
        self.assertEqual(evaluate.await_args.kwargs["bar_tf"], "1d")

    async def test_candidate_waits_for_next_session_and_emits_once(self):
        now = datetime(2026, 9, 25, 12, 0, tzinfo=bist.TR)
        yesterday = (now - timedelta(days=1)).date().isoformat()
        holder = {"state": {"planlar": {"THYAO.IS": {
            "bist_aday": True, "aday_gunu": yesterday, "guncelleme": int(now.timestamp()) - 3600,
            "tetik": 100.0, "teyit": 100.0, "iptal": 95.0, "hedef": 115.0,
            "pozisyon": False, "son_saat": None}}}}

        def bar(start, close):
            return {"open_time": int(start.timestamp() * 1000),
                    "close_time": int((start + timedelta(hours=1)).timestamp() * 1000),
                    "close": close}

        previous_day = now - timedelta(days=1)
        same_day = pd.DataFrame([bar(previous_day - timedelta(hours=2), 99),
                                 bar(previous_day - timedelta(hours=1), 101)])
        first = pd.DataFrame([bar(now - timedelta(hours=2, minutes=30), 99),
                              bar(now - timedelta(hours=1, minutes=30), 101)])
        later = pd.DataFrame([bar(now - timedelta(hours=1, minutes=30), 101),
                              bar(now - timedelta(minutes=30), 102)])
        fetch = AsyncMock(side_effect=[same_day, first, later])
        evaluate = AsyncMock(return_value={"ok": True})
        clock = [now.timestamp()]
        with (patch.object(bist_signals.config, "BIST_CONFIRM_TF", "1h"),  # the old short-term mode still works
              patch.object(bist_signals.store, "load_state", side_effect=lambda: copy.deepcopy(holder["state"])),
              patch.object(bist_signals.store, "save_state", side_effect=lambda s: holder.__setitem__("state", copy.deepcopy(s))),
              patch.object(bist_signals.bist, "fetch", fetch),
              patch.object(bist_signals.market, "add_indicators", side_effect=lambda df: df),
              patch.object(bist_signals.bist, "session_open", return_value=True),
              patch.object(bist_signals.time, "time", side_effect=lambda: clock[0]),
              patch.object(bist_signals, "evaluate", evaluate)):
            self.assertEqual(await bist_signals.hourly_check(), [])
            events = await bist_signals.hourly_check()
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["tur"], "kapi")
            clock[0] += 3600
            self.assertEqual(await bist_signals.hourly_check(), [])
        self.assertEqual(evaluate.await_count, 1)
        self.assertTrue(holder["state"]["planlar"]["THYAO.IS"]["sinyal_verildi"])

    async def test_bist_purchase_marks_plan_and_uses_tl_lots(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp:
            root = Path(tmp)
            with (patch.object(config, "POSITIONS_FILE", root / "positions.json"),
                  patch.object(config, "DECISIONS_FILE", root / "decisions.json"),
                  patch.object(config, "STATE_FILE", root / "state.json"),
                  patch.object(bist, "budget_tl", return_value=5000),
                  patch.object(bist, "last_price", new=AsyncMock(return_value=100.0))):
                conversation_store.save_state({"planlar": {"THYAO.IS": {"pozisyon": False, "iptal": 95.0}}})
                decision = positions.log_decision({
                    "piyasa": "BIST", "pair": "THYAO.IS", "symbol": "THYAO.IS", "lot": 7,
                    "iptal": 95.0, "hedef": 115.0, "kapi": {"risk_off": True, "hacim_ok": True}})
                pos, warning = await gate.record_purchase(decision)
                self.assertEqual(pos["piyasa"], "BIST")
                self.assertEqual(pos["para"], "TL")
                self.assertEqual(pos["adet"], 7)
                self.assertEqual(pos["miktar_usd"], 700.0)
                self.assertIsNone(warning)
                self.assertTrue(conversation_store.load_state()["planlar"]["THYAO.IS"]["pozisyon"])
                self.assertEqual(positions.get_decision(decision["id"])["aksiyon"], "aldi")

    async def test_report_uses_bist_hourly_history(self):
        candles = pd.DataFrame({"open_time": [1000, 2000, 3000], "close": [100.0, 111.0, 115.0]})
        with patch.object(bist, "fetch", new=AsyncMock(return_value=candles)):
            result = await backtest.evaluate_decision({"piyasa": "BIST", "symbol": "THYAO.IS", "timeframe": "1h",
                                                       "yon": "ABOVE", "mum_ms": 1000, "kapanis": 100.0,
                                                       "iptal": 95.0, "hedef": 110.0})
        self.assertEqual(result["sonuc"], "hedef")
        self.assertEqual(result["mum"], 1)

    async def test_bist_level_backtest_uses_bist_hourly_data_and_costs(self):
        stamp = int(time.time() * 1000) - 45 * 3_600_000
        candles = pd.DataFrame({
            "open_time": [stamp + i * 3_600_000 for i in range(40)],
            "close": [99.0] * 31 + [101.0, 110.0] + [110.0] * 7,
            "volume": [200.0] * 40, "vol_avg20": [100.0] * 40, "atr14": [2.0] * 40})
        fetch = AsyncMock(return_value=candles)
        with (patch.object(bist, "fetch", fetch),
              patch.object(backtest.market, "add_indicators", side_effect=lambda df: df),
              patch.object(backtest.market, "fetch_range", new=AsyncMock()) as crypto_fetch):
            result = await backtest.run("THYAO.IS", "ABOVE", 100.0, "1h", 90, 95.0, 108.0,
                                        fee_pct=config.BIST_FEE_PCT, slippage_pct=config.BIST_SLIPPAGE_PCT,
                                        market_name="BIST")
        crypto_fetch.assert_not_awaited()
        fetch.assert_awaited_once()
        self.assertEqual(result["tum"]["hedef"], 1)
        self.assertLess(result["islemler"][0]["R_net"], result["islemler"][0]["R"])

    async def test_telegram_budget_persists_and_resizes_lots(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp:
            reply = AsyncMock()
            update = SimpleNamespace(message=SimpleNamespace(reply_text=reply),
                                     effective_chat=SimpleNamespace(id=1))
            context = SimpleNamespace(args=["butce", "5.000"])
            with (patch.object(config, "SETTINGS_FILE", Path(tmp) / "settings.json"),
                  patch.object(bist_signals, "open_bist_tl", return_value=0)):
                await main.bist_cmd.__wrapped__(update, context)
                self.assertEqual(alerts_store.load_settings()["bist_budget_tl"], 5000)
                self.assertEqual(bist.tranche_tl(False, True, 0)[0], 1250)
                self.assertEqual(bist.tranche_tl(True, True, 0)[0], 750)
                context.args = ["butce", "8000"]
                await main.bist_cmd.__wrapped__(update, context)
                self.assertEqual(bist.tranche_tl(False, True, 0)[0], 2000)
                context.args = ["butce", "-100"]
                await main.bist_cmd.__wrapped__(update, context)
                self.assertEqual(bist.budget_tl(), 8000)

    async def test_unset_budget_skips_automatic_scan(self):
        bot = SimpleNamespace(send_message=AsyncMock())
        with (patch.object(bist, "budget_tl", return_value=None),
              patch.object(bist_signals, "daily_scan", new=AsyncMock()) as scan):
            await main.run_bist_scan(bot, announce_to=1)
        scan.assert_not_awaited()
        self.assertIn("/bist butce", bot.send_message.await_args.args[1])

    async def test_manual_bist_fill_and_whole_lot_correction(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp:
            root = Path(tmp)
            reply = AsyncMock()
            update = SimpleNamespace(message=SimpleNamespace(reply_text=reply))
            context = SimpleNamespace(args=["aldim", "THYAO", "100", "4", "stop=95", "hedef=115"])
            with (patch.object(config, "POSITIONS_FILE", root / "positions.json"),
                  patch.object(config, "STATE_FILE", root / "state.json"),
                  patch.object(config, "SETTINGS_FILE", root / "settings.json")):
                alerts_store.save_settings({"bist_budget_tl": 5000})
                conversation_store.save_state({"planlar": {"THYAO.IS": {"pozisyon": False}}})
                await main.bist_aldim(update, context)
                pos = positions.open_positions()[0]
                self.assertEqual(pos["adet"], 4)
                self.assertEqual(pos["miktar_usd"], 400)
                self.assertTrue(conversation_store.load_state()["planlar"]["THYAO.IS"]["pozisyon"])
                context.args = [str(pos["id"]), "giris=110", "lot=5"]
                await main.duzelt.__wrapped__(update, context)
                self.assertEqual(positions.get(pos["id"])["adet"], 5)
                self.assertEqual(positions.get(pos["id"])["miktar_usd"], 550)
                context.args = [str(pos["id"]), "miktar=555"]
                await main.duzelt.__wrapped__(update, context)
                self.assertEqual(positions.get(pos["id"])["adet"], 5)

    async def test_bist_analysis_uses_automatic_plan_follow_without_crypto_alarm_button(self):
        update = SimpleNamespace(message=SimpleNamespace(reply_text=AsyncMock()),
                                 effective_chat=SimpleNamespace(id=1))
        context = SimpleNamespace(args=["THYAO"], bot=Mock())
        with (patch.object(main, "bist_market_data", new=AsyncMock(return_value={"BIST_HISSE": {}})),
              patch.object(main, "run_analysis", new=AsyncMock()) as analyze):
            await main.bist_cmd.__wrapped__(update, context)
        self.assertIsNone(analyze.await_args.kwargs["buttons"])

    async def test_panel_close_uses_entered_tl_price(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp:
            with patch.object(config, "POSITIONS_FILE", Path(tmp) / "positions.json"):
                pos = positions.open_position("THYAO.IS", 100.0, 700.0, 95.0, 115.0,
                                              "1h", market_name="BIST", symbol="THYAO.IS")
                result = await web_sync._apply({"type": "position.close", "payload": {
                    "id": f"pos_{pos['id']}", "price": 110.0}}, lambda: None, AsyncMock())
                self.assertIn("70.00 TL", result)
                self.assertEqual(positions.get(pos["id"])["kapanis_fiyat"], 110.0)


class PanelTests(unittest.TestCase):
    def test_overview_keeps_usd_and_tl_apart(self):
        docs = [{"id": "pos_1", "status": "open", "currency": "USD", "pnl": 2.0,
                 "entry": 100.0, "size": 1, "current": 102.0},
                {"id": "pos_2", "status": "open", "currency": "TL", "pnl": 100.0,
                 "entry": 100.0, "size": 10, "current": 110.0}]
        with (patch.object(web_sync.positions, "get", return_value=None),
              patch.object(web_sync.positions, "load_decisions", return_value=[]),
              patch.object(web_sync.store, "load_state", return_value={"planlar": {}, "btc_not": None})):
            overview = web_sync.build_overview(docs, [], [], {}, [])
        self.assertEqual(overview["day_pnl"], 2.0)
        self.assertEqual(overview["bist_day_pnl"], 100.0)


if __name__ == "__main__":
    unittest.main()
