import unittest
from unittest.mock import patch

import tradeable_assets as listings


class TestTradeableAssets(unittest.TestCase):
    def setUp(self):
        self.snapshot = listings._snapshot
        self.retry_after = listings._retry_after
        listings._snapshot = None
        listings._retry_after = 0

    def tearDown(self):
        listings._snapshot = self.snapshot
        listings._retry_after = self.retry_after

    def test_inventory_filters_empty_listings_and_normalizes_wrappers(self):
        inventory = {'assets': [{'asset': 'UETH', 'options': [{}]},
                                {'asset': 'ETH', 'options': [{}]},
                                {'asset': 'XRP', 'options': []}]}
        with patch.object(listings, 'fetch_inventory', return_value=inventory) as fetch:
            with patch.object(listings.time, 'time', return_value=1000):
                self.assertEqual(listings.get_tradeable_assets()['assets'], ['ETH'])
                listings.get_tradeable_assets()
        self.assertEqual(fetch.call_count, 1)

    def test_temporary_failure_preserves_last_success_and_labels_it(self):
        listings._snapshot = {'assets': ['BTC'], 'source': 'live_inventory', 'checked_at': 10}
        with patch.object(listings, 'fetch_inventory', side_effect=RuntimeError('offline')):
            result = listings.get_tradeable_assets()
        self.assertEqual(result['assets'], ['BTC'])
        self.assertEqual(result['source'], 'cached_inventory')
        self.assertEqual(result['checked_at'], 10)

    def test_cold_start_failure_does_not_restore_retired_assets(self):
        with patch.object(listings, 'fetch_inventory', side_effect=RuntimeError('offline')):
            result = listings.get_tradeable_assets()
        self.assertNotIn('XRP', result['assets'])
        self.assertNotIn('ZEC', result['assets'])
        self.assertEqual(result['source'], 'last_known_listing')

    def test_valid_empty_inventory_remains_empty(self):
        with patch.object(listings, 'fetch_inventory', return_value={'assets': []}):
            self.assertEqual(listings.get_tradeable_assets()['assets'], [])
