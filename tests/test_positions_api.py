import unittest
from unittest.mock import patch

import positions_api


class ExpiredPositionAnnotationTests(unittest.TestCase):
    @patch("positions_api.get_expiry_price", return_value=(0.008, True))
    @patch("positions_api.get_underlying_address", return_value="0xpump")
    def test_prefers_canonical_symbol_address_over_payload_address(
        self, get_underlying_address, get_expiry_price
    ):
        position = {
            "status": "Expired",
            "symbol": "UPUMP",
            "chain_id": 999,
            "expiry": 1_756_454_400,
            "strike": 0.007,
            "type": "Call",
            # The API has returned WHYPE's generic address for UPUMP rows.
            "underlying_address": "0x5555555555555555555555555555555555555555",
        }

        positions_api._annotate_expired_position(position)

        get_underlying_address.assert_called_once_with("UPUMP", chain_id=999)
        get_expiry_price.assert_called_once_with("0xpump", position["expiry"], chain_id=999)
        self.assertEqual(position["expiry_price"], 0.008)
        self.assertEqual(position["outcome"], "Assigned")


if __name__ == "__main__":
    unittest.main()
