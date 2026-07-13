import unittest
from unittest.mock import patch

from app import app

TEST_ADDRESS = "0x1111111111111111111111111111111111111111"
TEST_ADDRESS_2 = "0x2222222222222222222222222222222222222222"


class TestAppServiceParity(unittest.TestCase):
    @patch("app.get_positions_payload_for_accounts")
    def test_native_positions_accepts_multiple_addresses(self, mock_get_positions):
        mock_get_positions.return_value = {
            "account": None,
            "accounts": [TEST_ADDRESS, TEST_ADDRESS_2],
            "positions": {"open_positions": [], "asset_summary": [], "summary": {}},
        }
        client = app.test_client()
        resp = client.get(f"/api/positions?address={TEST_ADDRESS},{TEST_ADDRESS_2}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["accounts"], [TEST_ADDRESS, TEST_ADDRESS_2])
        mock_get_positions.assert_called_once_with([TEST_ADDRESS, TEST_ADDRESS_2])

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
    def test_api_cli_history_assignment_backtest_shape(self, mock_get_history):
        mock_get_history.return_value = {
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
        client = app.test_client()
        resp = client.get(
            f"/api/cli/history/assignment-backtest?address={TEST_ADDRESS}&min_premium_retained=40"
        )
        self.assertEqual(resp.status_code, 200)
        payload = resp.get_json()
        self.assertTrue(payload["success"])
        self.assertIn("assignment_backtest", payload)
        self.assertEqual(payload["assignment_backtest"]["baseline"]["count"], 2)

    @patch("app.get_hype_volatility")
    def test_api_global_hype_volatility_shape(self, mock_vol):
        mock_vol.return_value = {
            "asset": "HYPE",
            "windows": [3, 7, 30],
            "days": 90,
            "point_count": 1,
            "latest": {"date": "2026-03-02", "close": 40.0, "rv_3d": 90.0, "rv_7d": 80.0, "rv_30d": 70.0},
            "series": [{"date": "2026-03-02", "close": 40.0, "rv_3d": 90.0, "rv_7d": 80.0, "rv_30d": 70.0}],
        }
        client = app.test_client()
        resp = client.get("/api/global/hype-volatility?days=90")
        self.assertEqual(resp.status_code, 200)
        payload = resp.get_json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["asset"], "HYPE")
        self.assertEqual(payload["latest"]["rv_7d"], 80.0)

    @patch("app.get_asset_volatility")
    def test_api_global_volatility_shape(self, mock_vol):
        mock_vol.return_value = {
            "asset": "BTC",
            "windows": [3, 7, 30],
            "days": 90,
            "point_count": 1,
            "latest": {"date": "2026-03-02", "close": 70000.0, "rv_7d": 40.0},
            "series": [{"date": "2026-03-02", "close": 70000.0, "rv_7d": 40.0}],
        }
        client = app.test_client()
        resp = client.get("/api/global/volatility?asset=BTC&days=90")
        self.assertEqual(resp.status_code, 200)
        payload = resp.get_json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["asset"], "BTC")

    @patch("app.build_clearance_board")
    def test_api_strategy_clearance_shape(self, mock_clearance):
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
        client = app.test_client()
        resp = client.get("/api/strategy/clearance?assets=HYPE,BTC")
        self.assertEqual(resp.status_code, 200)
        payload = resp.get_json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["entries"][0]["overall"], "block")

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
