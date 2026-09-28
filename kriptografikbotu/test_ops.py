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


if __name__ == "__main__":
    unittest.main()
