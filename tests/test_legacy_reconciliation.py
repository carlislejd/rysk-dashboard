import json
import sqlite3
import unittest

from db import init_db, insert_trades
from scripts.reconcile_legacy_trades import reconcile


class TestLegacyReconciliation(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        init_db(self.conn)
        self.row = {'txHash': 'current', 'chainId': 999, 'createdAt': 10, 'expiry': 20,
                    'symbol': 'HYPE', 'address': 'asset', 'quantity': '100', 'premium': '5', 'strike': '20'}
        insert_trades(self.conn, [self.row, {**self.row, 'txHash': 'old'}])
        self.conn.execute("INSERT INTO trade_source_observations VALUES (999,'current',100)")
        self.conn.executemany('INSERT INTO trade_wallets VALUES (?,?,?,?,?,?)', [
            (999, 'current', 'owner', 'verified_short_owner', '{}', 100),
            (999, 'old', None, 'receipt_unavailable', None, 100)])
        self.conn.execute('INSERT INTO sync_meta VALUES (?,?)', ('full_trade_audit_json',
                          json.dumps({'complete': True, 'presence_recorded': True, 'started_at': 100})))
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_exact_match_is_archived_and_outcome_preserved(self):
        self.conn.execute("UPDATE trades SET outcome='Returned',expiry_price_f=4 WHERE tx_hash='old'")
        self.assertEqual(reconcile(self.conn)['archived'], 1)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM trades').fetchone()[0], 1)
        self.assertEqual(self.conn.execute('SELECT outcome FROM trades').fetchone()[0], 'Returned')
        archived = json.loads(self.conn.execute('SELECT original_json FROM reconciled_trade_records').fetchone()[0])
        self.assertEqual(archived['tx_hash'], 'old')
        self.assertEqual(reconcile(self.conn)['archived'], 0)

    def test_ambiguous_or_different_trade_is_not_merged(self):
        self.conn.execute("UPDATE trades SET price='different' WHERE tx_hash='old'")
        self.assertEqual(reconcile(self.conn)['archived'], 0)
        self.conn.execute("UPDATE trades SET price='0' WHERE tx_hash='old'")
        insert_trades(self.conn, [{**self.row, 'txHash': 'another-current'}])
        self.conn.execute("INSERT INTO trade_source_observations VALUES (999,'another-current',100)")
        self.assertEqual(reconcile(self.conn)['archived'], 0)

    def test_verified_old_transaction_is_never_assumed_duplicate(self):
        self.conn.execute("UPDATE trade_wallets SET status='verified_short_owner',wallet='other' WHERE tx_hash='old'")
        self.assertEqual(reconcile(self.conn)['archived'], 0)

    def test_audit_counts_legacy_identity_once_across_snapshot_versions(self):
        from cohort_services import get_retention_audit
        reconcile(self.conn)
        row = self.conn.execute('SELECT * FROM reconciled_trade_records').fetchone()
        original = json.loads(row['original_json'])
        original['inserted_at'] += 1
        self.conn.execute('INSERT INTO reconciled_trade_records VALUES (?,?,?,?,?,?)',
                          ('another-snapshot',row['chain_id'],row['canonical_tx_hash'],
                           json.dumps(original),row['reason'],row['reconciled_at']))
        self.assertEqual(get_retention_audit(self.conn)['reconciled_legacy_rows'], 1)
