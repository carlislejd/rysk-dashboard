import unittest

from backtest_services import build_assignment_backtest


def row(symbol, strategy, outcome, premium, notional, apr, created, expiry, option_type="Call", strike=40, expiry_price=45):
    return {
        "symbol": symbol,
        "strategy": strategy,
        "outcome": outcome,
        "premium": premium,
        "notional": notional,
        "apr": apr,
        "created_at_iso": created,
        "expiry": expiry,
        "type": option_type,
        "strike": strike,
        "expiry_price": expiry_price,
    }


class TestBacktestServices(unittest.TestCase):
    def test_assignment_backtest_scores_rule_frontier(self):
        history = {
            "expired_positions": [
                row("kHYPE", "covered_call", "Assigned", 500, 20000, 42, "2026-03-01T00:00:00+00:00", 1773388800),
                row("kHYPE", "covered_call", "Assigned", 450, 18000, 38, "2026-03-02T00:00:00+00:00", 1773388800),
                row("kHYPE", "covered_call", "Returned", 250, 17000, 22, "2026-03-05T00:00:00+00:00", 1773388800),
                row("UBTC", "cash_secured_put", "Returned", 700, 70000, 30, "2026-03-05T00:00:00+00:00", 1773388800, "Put", 70000, 72000),
                row("UBTC", "cash_secured_put", "Assigned", 1000, 68000, 45, "2026-03-01T00:00:00+00:00", 1773388800, "Put", 68000, 66000),
            ]
        }

        result = build_assignment_backtest(history, min_premium_retained_pct=40)

        self.assertEqual(result["baseline"]["count"], 5)
        self.assertEqual(result["baseline"]["assigned_count"], 3)
        self.assertGreater(result["rule_count"], 0)
        self.assertTrue(result["recommended_rules"])
        self.assertIn("data_notes", result)
        self.assertIn("by_symbol_strategy", result["diagnostics"])

        top = result["recommended_rules"][0]
        self.assertIn("premium_retained_pct", top)
        self.assertIn("assigned_notional_avoided_pct", top)
        self.assertGreaterEqual(top["premium_retained_pct"], 40)

    def test_assignment_backtest_filters_symbol_and_strategy(self):
        history = {
            "expired_positions": [
                row("kHYPE", "covered_call", "Assigned", 500, 20000, 42, "2026-03-01T00:00:00+00:00", 1773388800),
                row("UBTC", "cash_secured_put", "Returned", 700, 70000, 30, "2026-03-05T00:00:00+00:00", 1773388800, "Put", 70000, 72000),
            ]
        }

        result = build_assignment_backtest(history, symbol="UBTC", strategy="csp")

        self.assertEqual(result["baseline"]["count"], 1)
        self.assertEqual(result["baseline"]["returned_count"], 1)
        self.assertEqual(result["filters"]["strategy"], "csp")

    def test_assignment_backtest_can_score_hype_volatility_rules(self):
        history = {
            "expired_positions": [
                row("kHYPE", "covered_call", "Assigned", 500, 20000, 42, "2026-03-02T00:00:00+00:00", 1773388800),
                row("kHYPE", "covered_call", "Returned", 250, 17000, 22, "2026-03-03T00:00:00+00:00", 1773388800),
                row("UBTC", "cash_secured_put", "Returned", 700, 70000, 30, "2026-03-03T00:00:00+00:00", 1773388800, "Put", 70000, 72000),
            ]
        }
        vol_points = [
            {"date": "2026-03-01", "rv_3d": 60.0, "rv_7d": 70.0, "rv_30d": 80.0},
            {"date": "2026-03-02", "rv_3d": 160.0, "rv_7d": 170.0, "rv_30d": 180.0},
            {"date": "2026-03-03", "rv_3d": 65.0, "rv_7d": 75.0, "rv_30d": 85.0},
        ]

        result = build_assignment_backtest(history, min_premium_retained_pct=40, volatility_points=vol_points)
        rule_ids = [r["rule_id"] for r in result["top_rules"]]

        self.assertTrue(any(rule_id.startswith("max_hype_rv_7d") for rule_id in rule_ids))

    def test_assignment_backtest_can_score_hype_daily_move_rules(self):
        history = {
            "expired_positions": [
                row("kHYPE", "covered_call", "Assigned", 500, 20000, 42, "2026-03-02T00:00:00+00:00", 1773388800),
                row("kHYPE", "covered_call", "Returned", 250, 17000, 22, "2026-03-03T00:00:00+00:00", 1773388800),
                row("WHYPE", "cash_secured_put", "Assigned", 300, 15000, 35, "2026-03-04T00:00:00+00:00", 1773388800, "Put", 30, 28),
            ]
        }
        vol_points = [
            {
                "date": "2026-03-02",
                "rv_3d": 90.0,
                "rv_7d": 90.0,
                "rv_30d": 90.0,
                "return_1d_pct": 8.0,
                "abs_return_1d_pct": 8.0,
                "return_3d_pct": 12.0,
                "abs_return_3d_pct": 12.0,
            },
            {
                "date": "2026-03-03",
                "rv_3d": 90.0,
                "rv_7d": 90.0,
                "rv_30d": 90.0,
                "return_1d_pct": 1.0,
                "abs_return_1d_pct": 1.0,
                "return_3d_pct": 3.0,
                "abs_return_3d_pct": 3.0,
            },
            {
                "date": "2026-03-04",
                "rv_3d": 90.0,
                "rv_7d": 90.0,
                "rv_30d": 90.0,
                "return_1d_pct": -8.0,
                "abs_return_1d_pct": 8.0,
                "return_3d_pct": -12.0,
                "abs_return_3d_pct": 12.0,
            },
        ]

        result = build_assignment_backtest(history, min_premium_retained_pct=20, volatility_points=vol_points)
        rule_ids = [r["rule_id"] for r in result["top_rules"]]

        self.assertTrue(any(rule_id.startswith("directional_hype_return_1d_pct") for rule_id in rule_ids))


if __name__ == "__main__":
    unittest.main()
