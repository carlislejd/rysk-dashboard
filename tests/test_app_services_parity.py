import unittest
from unittest.mock import patch

from app import app


class TestAppServiceParity(unittest.TestCase):
    def test_api_cli_account_validate(self):
        client = app.test_client()
        resp = client.get("/api/cli/account/validate?address=0xbE504fBfC1AD30708a79f5821ed5eA6Eef1A877B")
        self.assertEqual(resp.status_code, 200)
        payload = resp.get_json()
        self.assertTrue(payload["success"])
        self.assertTrue(payload["ok"])

    @patch("app.get_positions_payload")
    def test_api_positions_uses_service_payload_shape(self, mock_get_positions):
        mock_get_positions.return_value = {
            "account": "0xbE504fBfC1AD30708a79f5821ed5eA6Eef1A877B",
            "positions": {"open_positions": [{"symbol": "UBTC"}], "summary": {"open_count": 1}},
        }
        client = app.test_client()
        resp = client.get("/api/positions?address=0xbE504fBfC1AD30708a79f5821ed5eA6Eef1A877B")
        self.assertEqual(resp.status_code, 200)
        payload = resp.get_json()
        self.assertTrue(payload["success"])
        self.assertIn("positions", payload)
        self.assertEqual(payload["positions"]["summary"]["open_count"], 1)

    @patch("app.get_history_payload")
    def test_api_history_uses_service_payload_shape(self, mock_get_history):
        mock_get_history.return_value = {
            "account": "0xbE504fBfC1AD30708a79f5821ed5eA6Eef1A877B",
            "history": {"summary": {"expired_count": 4}, "expired_positions": []},
        }
        client = app.test_client()
        resp = client.get("/api/history?address=0xbE504fBfC1AD30708a79f5821ed5eA6Eef1A877B")
        self.assertEqual(resp.status_code, 200)
        payload = resp.get_json()
        self.assertTrue(payload["success"])
        self.assertIn("history", payload)
        self.assertEqual(payload["history"]["summary"]["expired_count"], 4)

    @patch("app.get_positions_payload")
    def test_api_cli_positions_expiring_shape(self, mock_get_positions):
        mock_get_positions.return_value = {
            "account": "0xbE504fBfC1AD30708a79f5821ed5eA6Eef1A877B",
            "positions": {
                "open_positions": [
                    {
                        "symbol": "UBTC",
                        "strategy": "covered_call",
                        "expiry_date": "2026-03-13",
                        "notional": 1000.0,
                        "premium": 20.0,
                    }
                ]
            },
        }
        client = app.test_client()
        resp = client.get(
            "/api/cli/positions/expiring"
            "?address=0xbE504fBfC1AD30708a79f5821ed5eA6Eef1A877B"
            "&expiry_date=2026-03-13"
        )
        self.assertEqual(resp.status_code, 200)
        payload = resp.get_json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["totals"]["notional"], 1000.0)

    @patch("app.get_positions_payload")
    def test_api_cli_positions_open_and_strikes_shapes(self, mock_get_positions):
        mock_get_positions.return_value = {
            "account": "0xbE504fBfC1AD30708a79f5821ed5eA6Eef1A877B",
            "positions": {
                "open_positions": [{"symbol": "UBTC", "strategy": "covered_call"}],
                "asset_summary": [{"symbol": "UBTC", "current_price": 65000.0, "strikes": []}],
            },
        }
        client = app.test_client()
        open_resp = client.get("/api/cli/positions/open?address=0xbE504fBfC1AD30708a79f5821ed5eA6Eef1A877B")
        strikes_resp = client.get("/api/cli/positions/strikes?address=0xbE504fBfC1AD30708a79f5821ed5eA6Eef1A877B")
        self.assertEqual(open_resp.status_code, 200)
        self.assertEqual(strikes_resp.status_code, 200)
        self.assertEqual(open_resp.get_json()["count"], 1)
        self.assertEqual(strikes_resp.get_json()["assets"][0]["symbol"], "UBTC")

    @patch("app.get_history_payload")
    def test_api_cli_history_expiry_prices_shape(self, mock_get_history):
        mock_get_history.return_value = {
            "account": "0xbE504fBfC1AD30708a79f5821ed5eA6Eef1A877B",
            "history": {
                "expired_positions": [
                    {
                        "symbol": "UBTC",
                        "expiry": 1773360000,
                        "expiry_date": "2026-03-13",
                        "expiry_price": 68000.0,
                        "outcome": "Returned",
                    }
                ]
            },
        }
        client = app.test_client()
        resp = client.get("/api/cli/history/expiry-prices?address=0xbE504fBfC1AD30708a79f5821ed5eA6Eef1A877B")
        self.assertEqual(resp.status_code, 200)
        payload = resp.get_json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["group_count"], 1)
        self.assertEqual(payload["groups"][0]["expiry"], 1773360000)

    @patch("app.get_history_payload")
    def test_api_cli_history_summary_expired_and_deep_dive_shapes(self, mock_get_history):
        mock_get_history.return_value = {
            "account": "0xbE504fBfC1AD30708a79f5821ed5eA6Eef1A877B",
            "history": {
                "summary": {"expired_count": 2},
                "expired_positions": [
                    {"symbol": "UBTC", "outcome": "Assigned", "premium": 100.0, "apr": 10.0},
                    {"symbol": "UBTC", "outcome": "Returned", "premium": 80.0, "apr": 8.0},
                ],
            },
        }
        client = app.test_client()
        summary_resp = client.get("/api/cli/history/summary?address=0xbE504fBfC1AD30708a79f5821ed5eA6Eef1A877B")
        expired_resp = client.get("/api/cli/history/expired?address=0xbE504fBfC1AD30708a79f5821ed5eA6Eef1A877B")
        deep_dive_resp = client.get("/api/cli/history/deep-dive?address=0xbE504fBfC1AD30708a79f5821ed5eA6Eef1A877B")
        self.assertEqual(summary_resp.status_code, 200)
        self.assertEqual(expired_resp.status_code, 200)
        self.assertEqual(deep_dive_resp.status_code, 200)
        self.assertEqual(summary_resp.get_json()["summary"]["expired_count"], 2)
        self.assertEqual(expired_resp.get_json()["count"], 2)
        self.assertIn("deep_dive", deep_dive_resp.get_json())


if __name__ == "__main__":
    unittest.main()
