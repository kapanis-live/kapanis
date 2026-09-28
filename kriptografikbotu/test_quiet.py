"""/sessizlik, /sessiz and the send gate. No network. Run: python -m unittest test_quiet"""
import os
import tempfile
import types
import unittest
from datetime import datetime, timedelta

os.environ["DATA_DIR"] = tempfile.mkdtemp()

import alerts_store  # noqa: E402
import config  # noqa: E402
import main  # noqa: E402
import quiet  # noqa: E402

OWNER = 1000
config.ALLOWED_CHAT_ID = OWNER


def at(day: int, hhmm: str) -> datetime:
    """2026-09-28 is a Monday; day 0..6 = Mon..Sun."""
    h, m = map(int, hhmm.split(":"))
    return datetime(2026, 9, 28, h, m, tzinfo=alerts_store.TR) + timedelta(days=day)


class ParseTest(unittest.TestCase):
    def test_spoken_weekday_window(self):
        w = quiet.parse_window("her hafta içi bana 12.00 14.30 arası bildirim atma")
        self.assertEqual(w, {"gunler": quiet.DAYS[:5], "bas": "12:00", "bit": "14:30"})
        self.assertEqual(quiet.describe(w), "hafta içi 12:00–14:30")

    def test_forms(self):
        self.assertEqual(quiet.parse_window("09.00-12.00")["gunler"], quiet.DAYS)
        self.assertEqual(quiet.parse_window("hafta sonu 10-13 arası")["bas"], "10:00")
        self.assertEqual(quiet.parse_window("cumartesi ve pazartesi 9:30 11:00")["gunler"], ["Mon", "Sat"])
        self.assertEqual(quiet.parse_window("pazar 23:00-07:00")["gunler"], ["Sun"])
        self.assertIsNone(quiet.parse_window("bildirim atma"))
        self.assertIsNone(quiet.parse_window("12.00 12.00"))

    def test_window_membership_and_midnight(self):
        weekday = {"gunler": quiet.DAYS[:5], "bas": "12:00", "bit": "14:30"}
        self.assertTrue(quiet.in_window(weekday, at(0, "12:00")))
        self.assertFalse(quiet.in_window(weekday, at(0, "14:30")))
        self.assertFalse(quiet.in_window(weekday, at(5, "13:00")))  # Saturday
        night = {"gunler": ["Fri"], "bas": "23:00", "bit": "07:00"}
        self.assertTrue(quiet.in_window(night, at(4, "23:30")))
        self.assertTrue(quiet.in_window(night, at(5, "06:00")))  # Saturday morning = Friday's night
        self.assertFalse(quiet.in_window(night, at(0, "06:00")))


class GateTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        s = alerts_store.load_settings()
        s.update(sessizlik=[], sessiz=False, bekleyen_bildirimler=[])
        alerts_store.save_settings(s)
        self.sent = []

    async def _send(self, chat, text):
        async def fake_retry(send, *args, **kwargs):
            self.sent.append((args, kwargs))
        orig = main._retry_send
        main._retry_send = fake_retry
        try:
            return await main.RetryBot(token="123:TEST").send_message(chat, text)
        finally:
            main._retry_send = orig

    async def test_mute_holds_background_messages_only_for_the_owner(self):
        quiet.set_muted_all(True)
        msg = await self._send(OWNER, "🟢 ŞİMDİ AL — AVAX/USDT\nayrıntı")
        self.assertIsInstance(msg, main.HeldMessage)
        await msg.delete()  # callers may still delete/edit a held message
        self.assertEqual(self.sent, [])
        await self._send(555, "başka kullanıcının analizi")  # other chats are never held
        self.assertEqual(len(self.sent), 1)
        token = main.USER_TURN.set(True)  # the owner's own command: the reply arrives
        try:
            await self._send(OWNER, "cevap")
        finally:
            main.USER_TURN.reset(token)
        self.assertEqual(len(self.sent), 2)
        held = quiet.take_held()
        self.assertEqual(len(held), 1)
        self.assertIn("AVAX", quiet.digest(held))

    async def test_plan_turns_mute_off_and_delivers_the_digest(self):
        quiet.set_muted_all(True)
        quiet.hold("⏰ BTC tetik 60000")
        replies, bot_msgs = [], []

        async def reply_text(text, **kw):
            replies.append(text)

        class Bot:
            async def send_message(self, chat, text, **kw):
                bot_msgs.append(text)

        update = types.SimpleNamespace(effective_chat=types.SimpleNamespace(id=OWNER),
                                       message=types.SimpleNamespace(reply_text=reply_text))
        context = types.SimpleNamespace(args=["45dk"], bot=Bot(), application=types.SimpleNamespace(
            job_queue=types.SimpleNamespace(get_jobs_by_name=lambda n: [], run_repeating=lambda *a, **k: None)))
        await main.plan(update, context)
        self.assertFalse(quiet.is_muted_all())
        self.assertIn("45 dk", replies[-1])
        self.assertEqual(main.plan_follow_minutes(), 45)
        self.assertTrue(any("BTC tetik" in m for m in bot_msgs))


class SellWhenTest(unittest.TestCase):
    def test_parse_when(self):
        now = alerts_store.now_tr()
        self.assertEqual(main.parse_when("dün")[:10], (now - main.timedelta(days=1)).date().isoformat())
        self.assertTrue(main.parse_when("25.09 14:30").endswith("14:30:00+03:00"))
        self.assertIsNone(main.parse_when("yarın"))
        self.assertIsNone(main.parse_when("31.02"))


if __name__ == "__main__":
    unittest.main()
