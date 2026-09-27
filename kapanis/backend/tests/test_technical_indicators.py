import math
import unittest

from technical_indicators import calculate


class IndicatorsTest(unittest.TestCase):
    def test_short_history_has_aligned_warmup(self):
        rows = [{"o": 10, "h": 11, "l": 9, "c": 10, "v": 100},
                {"o": 10, "h": 12, "l": 9, "c": 11, "v": 120}]
        result = calculate(rows)
        self.assertTrue(all(len(values) == 2 for values in result.values()))
        self.assertIsNone(result["adx"][-1])
        self.assertIsNone(result["stoch_rsi"][-1])
        self.assertEqual(result["obv"][-1], 120)

    def test_indicators_use_no_future_candles(self):
        rows = [{"o": 100 + i / 8, "h": 102 + i / 8, "l": 99 + i / 8,
                 "c": 100.5 + i / 8 + (i % 7 - 3) / 5, "v": 1000 + i * 3} for i in range(220)]
        before = calculate(rows)
        changed = [*rows, {"o": 200, "h": 250, "l": 170, "c": 230, "v": 50000}]
        after = calculate(changed)
        self.assertTrue(all(len(values) == len(rows) for values in before.values()))
        for key, values in before.items():
            self.assertEqual(values, after[key][:-1], key)
            self.assertTrue(all(math.isfinite(v) for v in values if v is not None), key)


if __name__ == "__main__":
    unittest.main()
