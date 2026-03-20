import unittest
from unittest.mock import patch

from app import app

TEST_ADDRESS = "0x1111111111111111111111111111111111111111"


class TestAppServiceParity(unittest.TestCase):
    def test_api_cli_account_validate(self):
        client = app.test_client()
        resp = client.get(f"/api/cli/account/validate?address={TEST_ADDRESS}")
        self.assertEqual(resp.status_code, 200)
        payload = resp.get_json()
        self.assertTrue(payload["success"])
        self.assertTrue(payload["ok"])

    @patch("app.get_positions_payload")
    def test_api_cli_positions_expiring_shape(self, mock_get_positions):
        mock_get_positions.return_value = {
            "account": TEST_ADDRESS,
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
            f"?address={TEST_ADDRESS}"
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
            "account": TEST_ADDRESS,
            "positions": {
                "open_positions": [{"symbol": "UBTC", "strategy": "covered_call"}],
                "asset_summary": [{"symbol": "UBTC", "current_price": 65000.0, "strikes": []}],
            },
        }
        client = app.test_client()
        open_resp = client.get(f"/api/cli/positions/open?address={TEST_ADDRESS}")
        strikes_resp = client.get(f"/api/cli/positions/strikes?address={TEST_ADDRESS}")
        self.assertEqual(open_resp.status_code, 200)
        self.assertEqual(strikes_resp.status_code, 200)
        self.assertEqual(open_resp.get_json()["count"], 1)
        self.assertEqual(strikes_resp.get_json()["assets"][0]["symbol"], "UBTC")

    @patch("app.get_history_payload")
    def test_api_cli_history_expiry_prices_shape(self, mock_get_history):
        mock_get_history.return_value = {
            "account": TEST_ADDRESS,
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
        resp = client.get(f"/api/cli/history/expiry-prices?address={TEST_ADDRESS}")
        self.assertEqual(resp.status_code, 200)
        payload = resp.get_json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["group_count"], 1)
        self.assertEqual(payload["groups"][0]["expiry"], 1773360000)
        self.assertEqual(payload["groups"][0]["expiry_price"], 68000.0)
        self.assertNotIn("unknown_count", payload["groups"][0])

    @patch("app.get_history_payload")
    def test_api_cli_history_summary_expired_and_deep_dive_shapes(self, mock_get_history):
        mock_get_history.return_value = {
            "account": TEST_ADDRESS,
            "history": {
                "summary": {"expired_count": 2, "unknown_count": 0},
                "expired_positions": [
                    {"symbol": "UBTC", "outcome": "Assigned", "premium": 100.0, "apr": 10.0},
                    {"symbol": "UBTC", "outcome": "Returned", "premium": 80.0, "apr": 8.0},
                ],
            },
        }
        client = app.test_client()
        summary_resp = client.get(f"/api/cli/history/summary?address={TEST_ADDRESS}")
        expired_resp = client.get(f"/api/cli/history/expired?address={TEST_ADDRESS}")
        deep_dive_resp = client.get(f"/api/cli/history/deep-dive?address={TEST_ADDRESS}")
        self.assertEqual(summary_resp.status_code, 200)
        self.assertEqual(expired_resp.status_code, 200)
        self.assertEqual(deep_dive_resp.status_code, 200)
        self.assertEqual(summary_resp.get_json()["summary"]["expired_count"], 2)
        self.assertNotIn("unknown_count", summary_resp.get_json()["summary"])
        self.assertEqual(expired_resp.get_json()["count"], 2)
        self.assertIn("deep_dive", deep_dive_resp.get_json())

    @patch("app.get_history_payload")
    @patch("app.get_positions_payload")
    def test_native_dashboard_endpoints_still_available(self, mock_get_positions, mock_get_history):
        mock_get_positions.return_value = {
            "account": TEST_ADDRESS,
            "positions": {"open_positions": [{"symbol": "UBTC"}], "summary": {"open_count": 1}},
        }
        mock_get_history.return_value = {
            "account": TEST_ADDRESS,
            "history": {"summary": {"expired_count": 4}, "expired_positions": []},
        }
        client = app.test_client()
        positions_resp = client.get(f"/api/positions?address={TEST_ADDRESS}")
        history_resp = client.get(f"/api/history?address={TEST_ADDRESS}")
        self.assertEqual(positions_resp.status_code, 200)
        self.assertEqual(history_resp.status_code, 200)

    @patch("app.backfill_outcomes")
    @patch("app.ADMIN_BACKFILL_TOKEN", "test-token")
    def test_admin_backfill_endpoint_requires_token_and_runs(self, mock_backfill):
        mock_backfill.return_value = {"groups_processed": 1, "rows_updated": 2, "rows_with_outcomes": 10}
        client = app.test_client()

        unauthorized = client.post("/api/admin/backfill-outcomes")
        self.assertEqual(unauthorized.status_code, 401)

        authorized = client.post(
            "/api/admin/backfill-outcomes",
            headers={"X-Admin-Token": "test-token"},
        )
        self.assertEqual(authorized.status_code, 200)
        payload = authorized.get_json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["rows_updated"], 2)


if __name__ == "__main__":
    unittest.main()
