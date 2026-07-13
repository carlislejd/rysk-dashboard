import unittest
from unittest.mock import patch

from dashboard_services import (
    get_history_payload_for_accounts,
    get_positions_payload_for_accounts,
)


ADDRESS_A = "0x1111111111111111111111111111111111111111"
ADDRESS_B = "0x2222222222222222222222222222222222222222"


class TestMultiAccountServices(unittest.TestCase):
    @patch("dashboard_services.fetch_positions")
    def test_positions_are_tagged_and_aggregated(self, mock_fetch):
        mock_fetch.side_effect = [
            {
                "open_positions": [{"symbol": "UBTC", "expiry": 2}],
                "asset_summary": [],
                "summary": {"open_count": 1, "open_notional_total": 100, "open_premium_total": 4, "open_weighted_apr": 20},
            },
            {
                "open_positions": [{"symbol": "WHYPE", "expiry": 1}],
                "asset_summary": [],
                "summary": {"open_count": 1, "open_notional_total": 300, "open_premium_total": 6, "open_weighted_apr": 40},
            },
        ]

        payload = get_positions_payload_for_accounts([ADDRESS_A, ADDRESS_B])

        self.assertEqual(payload["accounts"], [ADDRESS_A, ADDRESS_B])
        self.assertEqual([row["wallet_address"] for row in payload["positions"]["open_positions"]], [ADDRESS_B, ADDRESS_A])
        self.assertEqual(payload["positions"]["summary"]["open_count"], 2)
        self.assertEqual(payload["positions"]["summary"]["open_notional_total"], 400)
        self.assertEqual(payload["positions"]["summary"]["open_weighted_apr"], 35)

    @patch("dashboard_services.fetch_history")
    def test_histories_and_outcomes_are_aggregated(self, mock_fetch):
        mock_fetch.side_effect = [
            {
                "trades": [],
                "expired_positions": [{"symbol": "UBTC", "expiry": 1}],
                "summary": {"expired_count": 1, "net_premium": 5, "assigned_count": 1, "asset_outcomes": []},
            },
            {
                "trades": [],
                "expired_positions": [{"symbol": "WHYPE", "expiry": 2}],
                "summary": {"expired_count": 1, "net_premium": 7, "returned_count": 1, "asset_outcomes": []},
            },
        ]

        payload = get_history_payload_for_accounts([ADDRESS_A, ADDRESS_B])

        self.assertEqual(payload["history"]["summary"]["expired_count"], 2)
        self.assertEqual(payload["history"]["summary"]["net_premium"], 12)
        self.assertEqual(payload["history"]["summary"]["assigned_count"], 1)
        self.assertEqual(payload["history"]["summary"]["returned_count"], 1)
        self.assertEqual(payload["history"]["expired_positions"][0]["wallet_address"], ADDRESS_B)


if __name__ == "__main__":
    unittest.main()
