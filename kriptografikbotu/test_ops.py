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


if __name__ == "__main__":
    unittest.main()
