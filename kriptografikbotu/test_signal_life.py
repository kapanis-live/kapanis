"""Signal lifetime, stop cooldown, track record, broker stop, portfolio weight. Run: python -m unittest test_signal_life"""
import json
import os
import tempfile
import unittest
from datetime import timedelta

os.environ["DATA_DIR"] = tempfile.mkdtemp()

import alerts_store  # noqa: E402
import config  # noqa: E402
import gate  # noqa: E402
import positions  # noqa: E402
import signal_life as sl  # noqa: E402


class ClassifyTest(unittest.TestCase):
    def test_states_in_priority_order(self):
        self.assertEqual(sl.classify(10.87, 10.5, [10.9, 10.95], 10.9, "15m", "KRIPTO"), "aktif")
        self.assertEqual(sl.classify(10.87, 10.5, [10.9], 11.04, "15m", "KRIPTO"), "gec")  # +1.6% > 1%
        self.assertEqual(sl.classify(10.87, 10.5, [10.9] * 8, 10.9, "15m", "KRIPTO"), "suresi_doldu")
        # a close below the stop beats everything, even if the price came back
        self.assertEqual(sl.classify(10.87, 10.5, [10.4, 11.0], 10.9, "15m", "KRIPTO"), "gecersiz")
        self.assertIn("GEÇ KALDIN", sl.status_text({"etiket": sl.LABELS["gec"], "yas_dk": 130, "fiyat": 11.04,
                                                     "fark_yuzde": 1.56}))

    def test_midas_stop_sits_below_the_close_stop(self):
        lo, hi = sl.midas_stop(91.40, 0.8)
        self.assertAlmostEqual(lo, 90.60)
        self.assertAlmostEqual(hi, 91.00)
        self.assertIsNone(sl.midas_stop(None, 0.8))

    def test_stop_noise_is_measured_only_inside_the_tested_range(self):
        self.assertEqual(sl.stop_noise(1.0), (89, 82))
        self.assertEqual(sl.stop_noise(2.5), (72, 66))            # halfway between 2 and 3 ATR
        self.assertIsNone(sl.stop_noise(0.2))
        self.assertIsNone(sl.stop_noise(9))
        g = {"midas_stop": (98.0, 99.0), "atr": 1.0, "giris": 101.0, "mum": {"zaman_dilimi": "15m"}}
        self.assertIn("2.0 ATR", " ".join(gate.card_lines(g)))
        self.assertNotIn("Gürültü", " ".join(gate.card_lines({**g, "mum": {"zaman_dilimi": "1h"}})))   # only 15m was tested


class BookTest(unittest.TestCase):
    def setUp(self):
        for f in (config.POSITIONS_FILE, config.DECISIONS_FILE):
            if f.exists():
                f.unlink()

    def test_stop_cooldown_blocks_revenge_trades_for_a_few_hours(self):
        p = positions.open_position("HYPE/USDT", 92.15, 30, 91.40, 95.0, "15m", source="test")
        positions.close_position(p["id"], 91.30, "stop")
        self.assertIn("stop oldu", sl.stop_cooldown("HYPE/USDT"))
        self.assertIsNone(sl.stop_cooldown("BTC/USDT"))
        later = alerts_store.now_tr() + timedelta(hours=sl.STOP_COOLDOWN_HOURS + 1)
        self.assertIsNone(sl.stop_cooldown("HYPE/USDT", later))

    def test_track_record_needs_decided_gate_passed_signals(self):
        ds = [{"karar": "AL", "kapi": {"ok": True}, "sonuc": {"sonuc": "hedef", "R": 2.0}},
              {"karar": "AL", "kapi": {"ok": True}, "sonuc": {"sonuc": "stop", "R": -1.0}},
              {"karar": "AL", "kapi": {"ok": False}, "sonuc": {"sonuc": "hedef", "R": 2.0}},  # gate failed: not a signal
              {"karar": "AL", "kapi": {"ok": True}, "sonuc": {"sonuc": "açık", "R": 0.3}}]      # not decided yet
        t = sl.track_record(ds)
        self.assertEqual((t["n"], t["hedef"], t["isabet_yuzde"], t["ort_R"]), (2, 1, 50, 0.5))

    def test_one_heavy_coin_warns_on_every_new_signal(self):
        positions.open_position("ONDO/USDT", 1.0, 39, None, None, "4h", source="test")
        positions.open_position("AVAX/USDT", 10.0, 31, None, None, "4h", source="test")
        positions.open_position("SOL/USDT", 150.0, 30, None, None, "4h", source="test")
        self.assertIn("ONDO", gate.portfolio_weight_warning("BTC/USDT", 0))
        self.assertIn("bu alımla", gate.portfolio_weight_warning("BTC/USDT", 100))  # the new buy itself is the heavy one
        self.assertIsNone(gate.portfolio_weight_warning("BTC/USDT", 30))  # 39/130 = %30: at the limit, no warning


class SellDateTest(unittest.TestCase):
    def test_close_keeps_the_real_sale_time(self):
        p = positions.open_position("AVAX/USDT", 10.81, 30, None, None, "4h", source="test")
        when = (alerts_store.now_tr() - timedelta(days=2)).isoformat()
        part, rest = positions.partial_close(p["id"], p["adet"] / 2, 11.04, "elle", when=when)
        self.assertEqual(part["kapanis_zamani"], when)
        closed = positions.close_position(rest["id"], 11.2, "elle", when=when)
        self.assertEqual(closed["kapanis_zamani"], when)
        self.assertEqual(json.loads(config.POSITIONS_FILE.read_text(encoding="utf-8"))[0]["durum"], "kapali")


class AdvisorTest(unittest.TestCase):
    def setUp(self):
        if config.POSITIONS_FILE.exists():
            config.POSITIONS_FILE.unlink()

    def test_holdings_are_combined_and_plan_has_whole_lots(self):
        import advisor
        a1 = positions.open_position("ASTOR.IS", 80.0, 800, None, None, "1d", source="test")
        positions.update(a1["id"], piyasa="BIST", adet=10)
        a2 = positions.open_position("ASTOR.IS", 100.0, 500, None, None, "1d", source="test")
        positions.update(a2["id"], piyasa="BIST", adet=5)
        items = advisor.holdings("astor")
        self.assertEqual(len(items), 2)
        pos = advisor.combine(items)
        self.assertEqual(pos["adet"], 15)
        self.assertAlmostEqual(pos["giris"], (800 + 500) / 15)
        a = {"karar": "KISMİ SAT", "kar_yuzde": 45.0, "fiyat": 125.0, "olasi_tepe": "128–131 (3 dokunma, %+3.0)",
             "stop_onerisi": {"seviye": 110.0, "neden": "iz süren stop"}, "trend_cikis": 115.0}
        steps = advisor.plan(pos, a)
        self.assertIn("yarısını sat (7 adet)", steps[0])  # BIST: whole lots
        self.assertIn("10 günün dibi", steps[1])  # the tested exit, not the resistance zone
        self.assertNotIn("128", " ".join(steps))  # the zone level is no longer a sell step
        self.assertIn("110", steps[2])
        big = advisor.plan(pos, {**a, "karar": "TUT"})
        self.assertIn("üçte birini sat (5 adet)", big[0])
        self.assertIn("hepsini sat (15 adet)", advisor.plan(pos, {**a, "karar": "SAT"})[0])


class SellDialogTest(unittest.IsolatedAsyncioTestCase):
    """SHIB-sized numbers: 'Hepsi' must close everything (a text round trip once sold 1.2 SHIB at 6 USD)."""

    async def test_sell_all_with_huge_quantity_and_tiny_price(self):
        import types
        import main
        if config.POSITIONS_FILE.exists():
            config.POSITIONS_FILE.unlink()
        a = positions.open_position("SHIB/USDT", 0.00001234, 15.0, None, None, "4h", source="test")
        b = positions.open_position("SHIB/USDT", 0.00001300, 16.0, None, None, "4h", source="test")
        total = a["adet"] + b["adet"]
        self.assertGreater(total, 1e6)
        replies = []

        async def reply_text(text, **kw):
            replies.append(text)
        update = types.SimpleNamespace(message=types.SimpleNamespace(reply_text=reply_text))
        context = types.SimpleNamespace(user_data={})
        await main.sell_holding(update, context, "KRIPTO", "SHIBUSDT", qty=float(repr(total)), price=0.0000125)
        self.assertEqual([p for p in positions.open_positions() if p["pair"] == "SHIB/USDT"], [])
        closed = [p for p in positions.load() if p["pair"] == "SHIB/USDT"]
        self.assertTrue(all(p["kapanis_fiyat"] == 0.0000125 for p in closed))
        sold = next(r for r in replies if "satıldı" in r)
        self.assertIn("Kalan 0", sold)
        self.assertNotIn("e-05", sold)


if __name__ == "__main__":
    unittest.main()
