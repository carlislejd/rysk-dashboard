import unittest

from risk_gate_services import build_strategy_clearance


class TestRiskGateServices(unittest.TestCase):
    def test_hype_covered_call_blocks_after_big_up_day(self):
        payload = {
            "latest": {
                "date": "2026-06-10",
                "close": 55.0,
                "rv_7d": 90.0,
                "abs_return_1d_pct": 4.0,
                "abs_return_3d_pct": 6.0,
                "return_1d_pct": 3.0,
            }
        }

        result = build_strategy_clearance("HYPE", "cc", volatility_payload=payload)

        self.assertEqual(result["overall"], "block")
        self.assertFalse(result["clear_to_sell"])
        self.assertIn("recommendation", result)
        self.assertIn("metrics", result)
        self.assertEqual(result["metrics"]["return_1d_pct"], 3.0)
        self.assertTrue(any(g["name"] == "covered-call upside chase" and g["status"] == "block" for g in result["gates"]))

    def test_btc_csp_can_be_clear(self):
        payload = {
            "latest": {
                "date": "2026-06-10",
                "close": 70000.0,
                "rv_7d": 35.0,
                "abs_return_1d_pct": 1.0,
                "abs_return_3d_pct": 2.0,
                "return_1d_pct": -0.5,
            }
        }

        result = build_strategy_clearance("BTC", "csp", target_dte=14, volatility_payload=payload)

        self.assertEqual(result["overall"], "clear")
        self.assertTrue(result["clear_to_sell"])


if __name__ == "__main__":
    unittest.main()
