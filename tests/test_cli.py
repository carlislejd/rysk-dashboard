import io
import json
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import rysk_cli


class TestCli(unittest.TestCase):
    def test_address_validate_json(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = rysk_cli.main(["account", "validate", "--address", "0xbE504fBfC1AD30708a79f5821ed5eA6Eef1A877B", "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(buf.getvalue())
        self.assertTrue(payload["ok"])

    @patch("rysk_cli.get_positions_payload")
    def test_positions_open_json_schema(self, mock_positions):
        mock_positions.return_value = {
            "account": "0xbE504fBfC1AD30708a79f5821ed5eA6Eef1A877B",
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
                    "0xbE504fBfC1AD30708a79f5821ed5eA6Eef1A877B",
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
            "account": "0xbE504fBfC1AD30708a79f5821ed5eA6Eef1A877B",
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
                    "0xbE504fBfC1AD30708a79f5821ed5eA6Eef1A877B",
                    "--json",
                ]
            )
        self.assertEqual(code, 0)
        payload = json.loads(buf.getvalue())
        self.assertIn("summary", payload)
        self.assertEqual(payload["summary"]["expired_count"], 10)


if __name__ == "__main__":
    unittest.main()
