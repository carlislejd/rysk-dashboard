import unittest
from unittest.mock import Mock, patch

import hyperliquid_client


class TestHyperliquidClient(unittest.TestCase):
    def setUp(self):
        hyperliquid_client._api_instance = None
        hyperliquid_client._mids_cache = {"data": None, "timestamp": 0}

    def test_get_hyperliquid_api_falls_back_when_sdk_init_raises_index_error(self):
        with patch("hyperliquid_client.Info", side_effect=IndexError("list index out of range")):
            api = hyperliquid_client.get_hyperliquid_api()

        self.assertIsInstance(api, hyperliquid_client.MinimalPerpInfo)

    @patch("hyperliquid_client.requests.post")
    def test_minimal_perp_info_fetches_all_mids(self, mock_post):
        response = Mock()
        response.json.return_value = {"BTC": "63500.0", "HYPE": "60.1"}
        mock_post.return_value = response

        mids = hyperliquid_client.MinimalPerpInfo().all_mids()

        mock_post.assert_called_once_with(
            "https://api.hyperliquid.xyz/info",
            json={"type": "allMids"},
            timeout=10,
        )
        response.raise_for_status.assert_called_once()
        self.assertEqual(mids["BTC"], "63500.0")

    @patch("hyperliquid_client.time.time", return_value=1000)
    def test_get_current_price_uses_cached_all_mids(self, mock_time):
        api = Mock()
        api.all_mids.return_value = {"BTC": "63500.0"}
        hyperliquid_client._api_instance = api

        first_price = hyperliquid_client.get_current_price("UBTC")
        second_price = hyperliquid_client.get_current_price("BTC")

        self.assertEqual(first_price, 63500.0)
        self.assertEqual(second_price, 63500.0)
        api.all_mids.assert_called_once()


if __name__ == "__main__":
    unittest.main()
