"""Observation dates must describe the selected dataset, not browser refresh time."""
import sqlite3
import unittest
from unittest.mock import patch
from db import init_db
from global_services import get_market_pulse


class ObservationMetadataTest(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        init_db(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_empty_chain_has_no_observation_date(self):
        self.assertEqual(get_market_pulse(self.conn, chain_id=1)['observation'],
                         {'last_trade_at': None, 'trade_count': 0})

    def test_observation_includes_old_trades_and_respects_chain(self):
        for chain, created in [(999, 100), (999, 200), (1, 300)]:
            self.conn.execute('''INSERT INTO trades
                (tx_hash,address,chain_id,created_at,expiry,is_buy,is_put,symbol,
                 quantity,strike,price,premium,quantity_f,strike_f,premium_f,notional_f)
                VALUES (?, '', ?, ?, 400, 0, 0, 'ETH', '1','1','1','1',1,1,1,1)''',
                (str(created), chain, created))
        with patch('global_services.time.time', return_value=2_000_000):
            all_data = get_market_pulse(self.conn)
            filtered = get_market_pulse(self.conn, chain_id=999)
        self.assertEqual(all_data['observation'], {'last_trade_at': 300, 'trade_count': 3})
        self.assertEqual(filtered['observation'], {'last_trade_at': 200, 'trade_count': 2})
        self.assertEqual(filtered['activity']['trades_24h'], 0)
        self.assertEqual(filtered['active_positions']['count'], 0)
