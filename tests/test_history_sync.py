import json
import os
import tempfile
import unittest
from unittest.mock import patch

from db import get_db, init_db, insert_trades, get_last_sync_ts
from scripts import sync as history


class TestHistorySync(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.directory.name, 'test.db')
        self.conn = get_db(self.path)
        init_db(self.conn)
        self.row = {'txHash': '0xone', 'chainId': 1, 'createdAt': history.START_TS + 100,
                    'symbol': 'WETH', 'address': 'asset', 'expiry': history.START_TS + 1000,
                    'quantity': '1000000000000000000', 'strike': '1000000000000000000',
                    'premium': '10000000000000000'}

    def tearDown(self):
        self.conn.close()
        self.directory.cleanup()

    def test_replay_does_not_duplicate_hashed_or_hashless_rows(self):
        hashless = {**self.row, 'txHash': None}
        self.assertEqual(insert_trades(self.conn, [self.row, hashless]), 2)
        self.assertEqual(insert_trades(self.conn, [self.row, hashless]), 0)
        self.assertEqual(self.conn.execute('select count(*) from trades').fetchone()[0], 2)

    def test_failed_window_does_not_advance_past_gap_and_retry_resumes(self):
        end = history.START_TS + 2 * history.WINDOW
        with patch.object(history, 'get_db', side_effect=lambda: get_db(self.path)), \
             patch.object(history.time, 'time', return_value=end), \
             patch.object(history, 'fetch_window', side_effect=[[self.row], ValueError('upstream failure')]):
            with self.assertRaises(ValueError):
                history.sync(from_ts=history.START_TS)
        self.assertEqual(get_last_sync_ts(self.conn), history.START_TS + history.WINDOW)
        saved = json.loads(self.conn.execute("select value from sync_meta where key='last_trade_audit_json'").fetchone()[0])
        self.assertFalse(saved['complete'])
        with patch.object(history, 'get_db', side_effect=lambda: get_db(self.path)), \
             patch.object(history.time, 'time', return_value=end), \
             patch.object(history, 'fetch_window', return_value=[]) as fetch:
            result = history.sync()
        self.assertEqual(fetch.call_args_list[0].args[1], history.START_TS + history.WINDOW - history.OVERLAP)
        self.assertTrue(result['complete'])

    def test_reconciliation_reports_old_extras_without_deleting_them(self):
        insert_trades(self.conn, [{**self.row, 'txHash': '0xold', 'chainId': 999}])
        with patch.object(history, 'get_db', side_effect=lambda: get_db(self.path)), \
             patch.object(history.time, 'time', return_value=history.START_TS + 500), \
             patch.object(history, 'fetch_window', return_value=[self.row, self.row]):
            result = history.sync(from_ts=history.START_TS)
        self.assertEqual(result['source_unique_hashes'], 1)
        self.assertEqual(result['new_trades'], 1)
        self.assertEqual(result['missing_from_database'], 0)
        self.assertEqual(result['stored_not_in_source'], 1)
        self.assertEqual(result['database_by_chain'], {1: 1, 999: 1})

    def test_cursor_is_monotonic_under_concurrent_refreshes(self):
        from db import set_last_sync_ts
        set_last_sync_ts(self.conn, 200)
        set_last_sync_ts(self.conn, 100)
        self.assertEqual(get_last_sync_ts(self.conn), 200)
