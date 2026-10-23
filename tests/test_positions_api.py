import os
import unittest
from unittest.mock import patch

import positions_api
import requests


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


class WalletSnapshotReliabilityTests(unittest.TestCase):
    address = '0x' + '1' * 40

    def setUp(self):
        for cache in (positions_api._positions_cache, positions_api._history_cache,
                      positions_api._expired_positions_store):
            cache.clear()

    def tearDown(self):
        self.setUp()

    @patch('positions_api._fetch_json')
    def test_positions_failure_is_not_cached_as_an_empty_success(self, fetch):
        fetch.side_effect = [requests.Timeout('upstream URL includes ' + self.address), []]
        with self.assertRaises(positions_api.WalletDataUnavailable) as raised:
            positions_api.fetch_positions(self.address)
        self.assertNotIn(self.address, str(raised.exception))
        self.assertEqual(positions_api._positions_cache, {})
        self.assertEqual(positions_api._expired_positions_store, {})
        # A successful empty response is real data and may be cached.
        result = positions_api.fetch_positions(self.address)
        self.assertEqual(result['open_positions'], [])
        self.assertEqual(result['summary']['open_count'], 0)
        self.assertEqual(positions_api.fetch_positions(self.address), result)
        self.assertEqual(fetch.call_count, 2)

    @patch('positions_api.time.time', return_value=100_000)
    @patch('positions_api._fetch_json')
    def test_failed_refresh_preserves_both_last_good_caches(self, fetch, clock):
        old_positions = {'timestamp': 1, 'data': {'open_positions': [{'symbol': 'ETH'}]}}
        old_history = {'timestamp': 1, 'data': {'trades': [{'symbol': 'ETH'}]}}
        old_expired = {'timestamp': 1, 'positions': [{'symbol': 'ETH'}]}
        positions_api._positions_cache[self.address] = old_positions
        positions_api._history_cache[self.address + '::0'] = old_history
        positions_api._expired_positions_store[self.address] = old_expired
        fetch.side_effect = requests.HTTPError('upstream unavailable')
        for call in (positions_api.fetch_positions, positions_api.fetch_history):
            with self.assertRaises(positions_api.WalletDataUnavailable):
                call(self.address)
        self.assertIs(positions_api._positions_cache[self.address], old_positions)
        self.assertIs(positions_api._history_cache[self.address + '::0'], old_history)
        self.assertIs(positions_api._expired_positions_store[self.address], old_expired)

    @patch('positions_api._fetch_json')
    def test_invalid_json_or_payload_is_not_an_empty_snapshot(self, fetch):
        for call in (positions_api.fetch_positions, positions_api.fetch_history):
            for payload in (None, {}, {'error': 'upstream error'}, [None], ['invalid']):
                with self.subTest(call=call.__name__, payload=payload):
                    fetch.return_value = payload
                    with self.assertRaises(positions_api.WalletDataUnavailable):
                        call(self.address)
            fetch.side_effect = ValueError('Invalid JSON')
            with self.assertRaises(positions_api.WalletDataUnavailable):
                call(self.address)
            fetch.side_effect = None
        self.assertEqual(positions_api._positions_cache, {})
        self.assertEqual(positions_api._history_cache, {})

    @patch('positions_api._fetch_json', return_value=[])
    def test_successful_empty_history_is_cached(self, fetch):
        result = positions_api.fetch_history(self.address)
        self.assertEqual(result['trades'], [])
        self.assertEqual(result['expired_positions'], [])
        self.assertEqual(result['summary']['expired_count'], 0)
        self.assertEqual(positions_api.fetch_history(self.address), result)
        self.assertEqual(fetch.call_count, 2)  # history + positions, once each

    @patch('positions_api._fetch_json')
    def test_position_dependency_failure_does_not_cache_partial_history(self, fetch):
        fetch.side_effect = [[], requests.ConnectionError('positions unavailable')]
        with self.assertRaises(positions_api.WalletDataUnavailable):
            positions_api.fetch_history(self.address)
        self.assertEqual(positions_api._history_cache, {})

    @patch.dict(os.environ, {'RYSK_HISTORY_LIMIT': '0'})
    @patch('positions_api._fetch_json')
    def test_unverified_execution_history_stays_suppressed(self, fetch):
        common = {'symbol': 'ETH', 'chainId': 1, 'expiry': 2_000_000_000,
                  'quantity': str(10**18), 'strike': str(3000 * 10**18),
                  'premium': str(20 * 10**18), 'price': '0', 'isBuy': True}
        fetch.side_effect = [
            [{**common, 'txHash': 'older', 'createdAt': 1_700_000_000},
             {**common, 'txHash': 'newer', 'createdAt': 1_700_000_100}],
            [],
        ]
        result = positions_api.fetch_history(self.address)
        self.assertEqual(result['trades'], [])
        self.assertEqual(result['expired_positions'], [])
        self.assertEqual(result['summary']['net_premium'], 0)

    @patch.dict(os.environ, {'RYSK_HISTORY_LIMIT': '1'})
    @patch('positions_api._annotate_expired_position')
    @patch('positions_api._fetch_json')
    def test_expiry_history_limit_preserves_full_account_summary(self, fetch, annotate):
        annotate.side_effect = lambda position: position.update(
            outcome='Returned', expiry_price=2000, expiry_price_finalized=True)
        common = {'symbol': 'ETH', 'chainId': 1, 'quantity': str(10**18),
                  'strike': str(3000 * 10**18), 'premium': str(20 * 10**18),
                  'price': '0', 'isBuy': True, 'createdAt': 1_600_000_000}
        fetch.side_effect = [
            [{'createdAt': 100, 'txHash': 'unverified-execution'}],
            [{**common, 'expiry': 1_700_000_000, 'txHash': 'older'},
             {**common, 'expiry': 1_700_000_100, 'txHash': 'newer'}],
        ]
        result = positions_api.fetch_history(self.address)
        self.assertEqual(result['trades'], [])
        self.assertEqual([row['tx_hash'] for row in result['expired_positions']], ['newer'])
        self.assertEqual(result['summary']['expired_count'], 2)
        self.assertEqual(result['summary']['returned_count'], 2)
        self.assertEqual(result['summary']['net_premium'], 40)


if __name__ == "__main__":
    unittest.main()
