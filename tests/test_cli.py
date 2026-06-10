import io
import json
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import rysk_cli

TEST_ADDRESS = "0x1111111111111111111111111111111111111111"


class TestCli(unittest.TestCase):
    def test_address_validate_json(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = rysk_cli.main(["account", "validate", "--address", TEST_ADDRESS, "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(buf.getvalue())
        self.assertTrue(payload["ok"])

    @patch("rysk_cli.get_positions_payload")
    def test_positions_open_json_schema(self, mock_positions):
        mock_positions.return_value = {
            "account": TEST_ADDRESS,
            "positions": {
                "open_positions": [
                    {
                        "symbol": "UBTC",
                        "strategy": "cash_secured_put",
                        "type": "Put",
                        "side": "Sell",
                        "quantity": 0.5,
                        "strike": 62000.0,
                        "premium": 1200.0,
                        "apr": 24.5,
                        "expiry_date": "2026-03-31",
                    }
                ]
            },
        }
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = rysk_cli.main(
                [
                    "positions",
                    "open",
                    "--address",
                    TEST_ADDRESS,
                    "--json",
                ]
            )
        self.assertEqual(code, 0)
        payload = json.loads(buf.getvalue())
        self.assertIn("open_positions", payload)
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["open_positions"][0]["strategy"], "cash_secured_put")

    @patch("rysk_cli.get_history_payload")
    def test_history_summary_json_schema(self, mock_history):
        mock_history.return_value = {
            "account": TEST_ADDRESS,
            "history": {
                "summary": {
                    "expired_count": 10,
                    "net_premium": 1000.0,
                    "assigned_count": 4,
                    "returned_count": 6,
                    "unknown_count": 0,
                    "total_notional": 90000.0,
                },
                "expired_positions": [],
            },
        }
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = rysk_cli.main(
                [
                    "history",
                    "summary",
                    "--address",
                    TEST_ADDRESS,
                    "--json",
                ]
            )
        self.assertEqual(code, 0)
        payload = json.loads(buf.getvalue())
        self.assertIn("summary", payload)
        self.assertEqual(payload["summary"]["expired_count"], 10)

    @patch("rysk_cli.get_positions_payload")
    def test_positions_expiring_totals(self, mock_positions):
        mock_positions.return_value = {
            "account": TEST_ADDRESS,
            "positions": {
                "open_positions": [
                    {
                        "symbol": "UBTC",
                        "strategy": "covered_call",
                        "type": "Call",
                        "side": "Sell",
                        "quantity": 0.5,
                        "strike": 67000.0,
                        "notional": 33500.0,
                        "premium": 500.0,
                        "expiry_date": "2026-03-13",
                    },
                    {
                        "symbol": "WHYPE",
                        "strategy": "cash_secured_put",
                        "type": "Put",
                        "side": "Sell",
                        "quantity": 1000.0,
                        "strike": 29.0,
                        "notional": 29000.0,
                        "premium": 350.0,
                        "expiry_date": "2026-03-13",
                    },
                    {
                        "symbol": "WHYPE",
                        "strategy": "cash_secured_put",
                        "type": "Put",
                        "side": "Sell",
                        "quantity": 500.0,
                        "strike": 28.0,
                        "notional": 14000.0,
                        "premium": 100.0,
                        "expiry_date": "2026-03-27",
                    },
                ]
            },
        }
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = rysk_cli.main(
                [
                    "positions",
                    "expiring",
                    "--address",
                    TEST_ADDRESS,
                    "--expiry-date",
                    "2026-03-13",
                    "--json",
                ]
            )
        self.assertEqual(code, 0)
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["count"], 2)
        self.assertEqual(payload["totals"]["notional"], 62500.0)
        self.assertEqual(payload["totals"]["premium"], 850.0)

    @patch("rysk_cli.get_history_payload")
    def test_history_expiry_prices_grouping(self, mock_history):
        mock_history.return_value = {
            "account": TEST_ADDRESS,
            "history": {
                "expired_positions": [
                    {
                        "symbol": "UBTC",
                        "expiry": 1773360000,
                        "expiry_date": "2026-03-13",
                        "expiry_price": 67000.0,
                        "outcome": "Assigned",
                    },
                    {
                        "symbol": "UBTC",
                        "expiry": 1773360000,
                        "expiry_date": "2026-03-13",
                        "expiry_price": 69000.0,
                        "outcome": "Returned",
                    },
                    {
                        "symbol": "WHYPE",
                        "expiry": 1773360000,
                        "expiry_date": "2026-03-13",
                        "expiry_price": 28.5,
                        "outcome": "Assigned",
                    },
                    {
                        "symbol": "WHYPE",
                        "expiry": 1773964800,
                        "expiry_date": "2026-03-20",
                        "expiry_price": None,
                        "outcome": "Unknown",
                    },
                ]
            },
        }
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = rysk_cli.main(
                [
                    "history",
                    "expiry-prices",
                    "--address",
                    TEST_ADDRESS,
                    "--json",
                ]
            )
        self.assertEqual(code, 0)
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["group_count"], 3)
        ubtc = [g for g in payload["groups"] if g["symbol"] == "UBTC" and g["expiry_date"] == "2026-03-13"][0]
        self.assertEqual(ubtc["expiry"], 1773360000)
        self.assertEqual(ubtc["positions_total"], 2)
        self.assertEqual(ubtc["positions_with_price"], 2)
        self.assertEqual(ubtc["expiry_price"], 67000.0)

    @patch("rysk_cli.get_history_payload")
    def test_history_assignment_backtest_json_schema(self, mock_history):
        mock_history.return_value = {
            "account": TEST_ADDRESS,
            "history": {
                "expired_positions": [
                    {
                        "symbol": "kHYPE",
                        "strategy": "covered_call",
                        "outcome": "Assigned",
                        "premium": 500.0,
                        "notional": 20000.0,
                        "apr": 42.0,
                        "created_at_iso": "2026-03-01T00:00:00+00:00",
                        "expiry": 1773388800,
                        "type": "Call",
                        "strike": 40.0,
                        "expiry_price": 45.0,
                    },
                    {
                        "symbol": "UBTC",
                        "strategy": "cash_secured_put",
                        "outcome": "Returned",
                        "premium": 700.0,
                        "notional": 70000.0,
                        "apr": 30.0,
                        "created_at_iso": "2026-03-05T00:00:00+00:00",
                        "expiry": 1773388800,
                        "type": "Put",
                        "strike": 70000.0,
                        "expiry_price": 72000.0,
                    },
                ],
            },
        }
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = rysk_cli.main(
                [
                    "history",
                    "assignment-backtest",
                    "--address",
                    TEST_ADDRESS,
                    "--min-premium-retained",
                    "40",
                    "--json",
                ]
            )
        self.assertEqual(code, 0)
        payload = json.loads(buf.getvalue())
        self.assertIn("assignment_backtest", payload)
        self.assertEqual(payload["assignment_backtest"]["baseline"]["count"], 2)
        self.assertIn("recommended_rules", payload["assignment_backtest"])

    @patch("rysk_cli.get_hype_volatility")
    @patch("rysk_cli.get_history_payload")
    def test_history_assignment_backtest_can_include_hype_vol(self, mock_history, mock_vol):
        mock_history.return_value = {
            "account": TEST_ADDRESS,
            "history": {
                "expired_positions": [
                    {
                        "symbol": "kHYPE",
                        "strategy": "covered_call",
                        "outcome": "Assigned",
                        "premium": 500.0,
                        "notional": 20000.0,
                        "apr": 42.0,
                        "created_at_iso": "2026-03-02T00:00:00+00:00",
                        "expiry": 1773388800,
                        "type": "Call",
                        "strike": 40.0,
                        "expiry_price": 45.0,
                    },
                    {
                        "symbol": "UBTC",
                        "strategy": "cash_secured_put",
                        "outcome": "Returned",
                        "premium": 700.0,
                        "notional": 70000.0,
                        "apr": 30.0,
                        "created_at_iso": "2026-03-03T00:00:00+00:00",
                        "expiry": 1773388800,
                        "type": "Put",
                        "strike": 70000.0,
                        "expiry_price": 72000.0,
                    },
                ],
            },
        }
        mock_vol.return_value = {
            "series": [
                {"date": "2026-03-02", "rv_3d": 150.0, "rv_7d": 160.0, "rv_30d": 170.0},
            ]
        }
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = rysk_cli.main(
                [
                    "history",
                    "assignment-backtest",
                    "--address",
                    TEST_ADDRESS,
                    "--include-hype-vol",
                    "--min-premium-retained",
                    "40",
                    "--json",
                ]
            )
        self.assertEqual(code, 0)
        payload = json.loads(buf.getvalue())
        rule_ids = [r["rule_id"] for r in payload["assignment_backtest"]["top_rules"]]
        self.assertTrue(any(rule_id.startswith("max_hype_rv_") for rule_id in rule_ids))

    @patch("rysk_cli.build_clearance_board")
    def test_market_clearance_json_schema(self, mock_clearance):
        mock_clearance.return_value = {
            "assets": ["HYPE", "BTC"],
            "strategies": ["covered_call", "cash_secured_put"],
            "target_dte": None,
            "entries": [
                {
                    "asset": "HYPE",
                    "strategy": "covered_call",
                    "strategy_label": "Covered Call",
                    "overall": "block",
                    "clear_to_sell": False,
                    "as_of_date": "2026-06-10",
                    "close": 55.0,
                    "gates": [],
                    "latest": {},
                }
            ],
        }
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = rysk_cli.main(["market", "clearance", "--assets", "HYPE,BTC", "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(buf.getvalue())
        self.assertIn("entries", payload)
        self.assertEqual(payload["entries"][0]["overall"], "block")

    @patch("rysk_cli.build_clearance_board")
    def test_market_check_json_schema(self, mock_clearance):
        mock_clearance.return_value = {
            "assets": ["HYPE"],
            "strategies": ["cc"],
            "target_dte": 21.0,
            "entries": [
                {
                    "asset": "HYPE",
                    "strategy": "covered_call",
                    "strategy_label": "Covered Call",
                    "overall": "block",
                    "clear_to_sell": False,
                    "recommendation": "Do not sell this HYPE Covered Call today.",
                    "as_of_date": "2026-06-10",
                    "close": 55.0,
                    "metrics": {"return_1d_pct": 3.0, "rv_7d": 120.0},
                    "gates": [],
                    "latest": {},
                }
            ],
        }
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = rysk_cli.main([
                "market",
                "check",
                "--asset",
                "HYPE",
                "--strategy",
                "cc",
                "--target-dte",
                "21",
                "--json",
            ])
        self.assertEqual(code, 0)
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["assets"], ["HYPE"])
        self.assertEqual(payload["entries"][0]["metrics"]["rv_7d"], 120.0)


if __name__ == "__main__":
    unittest.main()
