import unittest
from unittest.mock import patch

from app import app


class TestAppServiceParity(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
