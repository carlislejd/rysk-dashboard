import unittest

from volatility_services import compute_rolling_volatility


class TestVolatilityServices(unittest.TestCase):
    def test_compute_rolling_volatility_from_daily_candles(self):
        candles = [
            {"t": 1704067200000, "c": "100"},
            {"t": 1704153600000, "c": "105"},
            {"t": 1704240000000, "c": "102"},
            {"t": 1704326400000, "c": "110"},
            {"t": 1704412800000, "c": "108"},
        ]

        series = compute_rolling_volatility(candles, windows=(3,))

        self.assertEqual(len(series), 5)
        self.assertEqual(series[0]["date"], "2024-01-01")
        self.assertIsNone(series[0]["rv_3d"])
        self.assertIsNotNone(series[-1]["rv_3d"])
        self.assertGreater(series[-1]["rv_3d"], 0)
        self.assertIsNotNone(series[-1]["return_1d_pct"])
        self.assertIsNotNone(series[-1]["return_3d_pct"])
        self.assertGreater(series[-1]["abs_return_1d_pct"], 0)


if __name__ == "__main__":
    unittest.main()
