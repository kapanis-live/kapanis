"""Startup guards: things that crash the bot before it answers a single message.
Run with: python -m unittest test_startup"""
import pathlib
import re
import unittest

MAIN = pathlib.Path(__file__).with_name("main.py").read_text(encoding="utf-8")


class StartupTest(unittest.TestCase):
    def test_command_names_are_valid_telegram_commands(self):
        # Telegram only accepts lowercase latin letters, digits and "_" (so no "ö", "ş", ...).
        names = []
        for m in re.finditer(r'CommandHandler\((\[[^\]]*\]|"[^"]*")', MAIN):
            names += re.findall(r'"([^"]*)"', m.group(1))
        self.assertTrue(names)
        bad = [n for n in names if not re.fullmatch(r"[a-z0-9_]{1,32}", n)]
        self.assertEqual(bad, [], f"invalid command names: {bad}")

    def test_menu_commands_are_valid(self):
        menu = re.search(r"BOT_MENU = \[(.*?)\n\]", MAIN, re.S).group(1)
        for name in re.findall(r'\("([^"]+)",', menu):
            self.assertRegex(name, r"^[a-z0-9_]{1,32}$")

    def test_no_function_defined_twice(self):
        # A second top-level def silently replaces the first (this broke /plan once).
        names = re.findall(r"^(?:async )?def (\w+)", MAIN, re.M)
        dupes = sorted({n for n in names if names.count(n) > 1})
        self.assertEqual(dupes, [], f"defined twice in main.py: {dupes}")

    def test_no_undefined_names(self):
        # A name used but never defined only fails when that line runs (this silenced crypto AL cards once).
        try:
            from pyflakes import api, reporter
        except ImportError:
            self.skipTest("pyflakes not installed")
        import io
        out = io.StringIO()
        for f in ("main.py", "web_sync.py", "quiet.py", "positions.py", "gate.py", "signal_life.py"):
            path = pathlib.Path(__file__).parent / f
            if path.exists():
                api.checkPath(str(path), reporter.Reporter(out, out))
        undefined = [ln for ln in out.getvalue().splitlines() if "undefined name" in ln]
        self.assertEqual(undefined, [])

    def test_main_imports(self):
        import main  # noqa: F401  (import-time errors would stop the bot too)


if __name__ == "__main__":
    unittest.main()
