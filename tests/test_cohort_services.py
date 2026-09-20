import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import unittest

from cohort_services import (
    get_retention_cohorts,
    get_retention_audit,
    public_retention_audit,
    public_retention_cohorts,
)
from db import init_db
from wallet_attribution import recover_wallet, receipt_proof


def ts(date):
    return int(datetime.fromisoformat(date).replace(tzinfo=timezone.utc).timestamp())


class TestRetention(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        init_db(self.conn)

    def tearDown(self):
        self.conn.close()

    def trade(self, date, wallet, chain=999):
        key = str(self.conn.execute('select count(*) from trades').fetchone()[0])
        self.conn.execute('''INSERT INTO trades
            (tx_hash,address,chain_id,created_at,is_buy,is_put,symbol,quantity,strike,
             price,premium,quantity_f,strike_f,premium_f,notional_f)
            VALUES (?,'asset',?,?,1,0,'HYPE','1','1','1','1',1,1,1,1)''', (key, chain, ts(date)))
        if wallet:
            self.conn.execute('INSERT INTO trade_wallets VALUES (?,?,?,?,?,?)',
                              (chain, key, wallet, 'verified_short_owner', None, 0))

    def test_retention_deduplicates_wallets_and_allows_reactivation(self):
        self.trade('2025-12-01', '0xABC')
        self.trade('2025-12-02', '0xabc')
        self.trade('2025-12-31T23:59:59', '0xdef')
        self.trade('2026-01-01', '0xabc')
        self.trade('2026-01-15', '0xabc')
        self.trade('2026-01-20', '0xnew')
        self.trade('2026-02-02', '0xdef')
        self.trade('2026-03-16', '0xabc')
        result = get_retention_cohorts(self.conn)
        december, january = result['cohorts']
        self.assertEqual(december['wallets'], 2)
        self.assertEqual([c['retention_pct'] for c in december['cells']], [100, 50, 50, 50])
        self.assertEqual(december['cells'][1]['trades_per_active_wallet'], 2)
        self.assertEqual(december['cells'][2]['active_wallets'], 1)
        self.assertTrue(december['cells'][3]['partial'])
        self.assertIsNone(january['cells'][3])
        self.assertEqual(january['cells'][1]['retention_pct'], 0)
        self.assertEqual(result['summary'][1]['eligible_wallets'], 3)
        self.assertAlmostEqual(result['summary'][1]['retention_pct'], 100 / 3)
        self.assertIsNone(result['summary'][3]['retention_pct'])

    def test_missing_attribution_is_in_coverage_not_cohort_denominator(self):
        self.trade('2026-01-01', '0xone')
        self.trade('2026-01-10', None)
        self.trade('2026-02-01', '0xtwo', chain=1)
        result = get_retention_cohorts(self.conn, chain_id=999)
        self.assertEqual(result['coverage_pct'], 50)
        self.assertEqual(result['wallet_count'], 1)
        self.assertFalse(result['cohorts'][0]['cells'][0]['attribution_complete'])
        self.assertEqual(result['observed_through'][:10], '2026-01-10')
        self.assertEqual(get_retention_cohorts(self.conn, chain_id=42)['cohorts'], [])

    def test_global_feed_and_owner_audit_preserve_unattributed_trades(self):
        from global_services import get_global_trades
        self.trade('2026-01-01', '0xone')
        self.trade('2026-01-02', None)
        feed = get_global_trades(self.conn)
        audit = get_retention_audit(self.conn)
        self.assertEqual(feed['total'], audit['global_trade_count'])
        self.assertEqual(feed['total'], 2)
        self.assertNotIn('seller_wallet', feed['trades'][0])
        self.assertEqual(feed['trades'][0]['owner_status'], 'pending')
        self.assertNotIn('seller_wallet', feed['trades'][1])
        self.assertEqual(audit['by_chain'][0]['attributed_trades'], 1)
        self.assertEqual(audit['by_chain'][0]['pending_trades'], 1)

    def test_pending_recovery_does_not_report_zero_retention(self):
        self.trade('2026-01-01', '0xone')
        self.trade('2026-02-01', None)
        self.trade('2026-03-01', '0xone')
        result = get_retention_cohorts(self.conn)
        self.assertEqual(result['pending_trades'], 1)
        self.assertTrue(result['cohorts'][0]['cells'][1]['pending'])
        self.assertIsNone(result['cohorts'][0]['cells'][1]['retention_pct'])
        self.assertIsNone(result['summary'][1]['retention_pct'])

    def test_no_data(self):
        result = get_retention_cohorts(self.conn)
        self.assertEqual(result['cohorts'], [])
        self.assertEqual(result['coverage_pct'], 0)
        self.assertIsNone(result['observed_through'])

    def test_public_projection_removes_participant_counts_and_suppresses_small_cohorts(self):
        self.trade('2026-01-01', '0xone')
        self.trade('2026-02-01', '0xone')
        internal = get_retention_cohorts(self.conn)
        public = public_retention_cohorts(internal, min_participants=20)

        self.assertNotIn('wallet_count', public)
        self.assertNotIn('wallets', public['cohorts'][0])
        self.assertTrue(public['cohorts'][0]['limited_history'])
        cell = public['cohorts'][0]['cells'][1]
        self.assertTrue(cell['limited_history'])
        self.assertIsNone(cell['retention_pct'])
        self.assertNotIn('active_wallets', cell)
        self.assertNotIn('trades_per_active_wallet', cell)
        self.assertTrue(public['summary'][1]['limited_history'])
        self.assertNotIn('eligible_wallets', public['summary'][1])
        self.assertNotIn('active_wallets', public['summary'][1])

    def test_public_projection_threshold_zero_pending_partial_and_future_invariants(self):
        for number in range(19):
            self.trade('2026-01-01', f'0x{number:040x}')
        internal = get_retention_cohorts(self.conn)
        public = public_retention_cohorts(internal, min_participants=20)
        self.assertTrue(public['cohorts'][0]['limited_history'])

        # The twentieth trader makes the original January cohort reportable.
        self.trade('2026-01-02', f'0x{19:040x}')
        # Advance the observation period without a January return, then add a
        # pending March receipt. February's zero must remain a valid result.
        self.trade('2026-02-01', '0xfebruary')
        self.trade('2026-03-01', None)
        internal = get_retention_cohorts(self.conn)
        public = public_retention_cohorts(internal, min_participants=20)
        january, february = public['cohorts']
        self.assertFalse(january['limited_history'])
        self.assertTrue(february['limited_history'])
        self.assertEqual(january['cells'][1]['retention_pct'], 0)
        self.assertFalse(january['cells'][1]['partial'])
        self.assertTrue(january['cells'][2]['pending'])
        self.assertTrue(january['cells'][2]['partial'])
        self.assertIsNone(january['cells'][2]['retention_pct'])
        self.assertIsNone(february['cells'][2])

        cell = public['cohorts'][0]['cells'][0]
        self.assertFalse(cell['limited_history'])
        self.assertEqual(cell['retention_pct'], 100)

    def test_public_audit_allowlists_trade_metrics(self):
        audit = public_retention_audit({
            'by_chain': [{'chain_id': 1, 'chain_name': 'Ethereum', 'wallets': 20,
                          'total_trades': 25, 'attributed_trades': 24}],
            'statuses': [{'chain_id': 1, 'status': 'verified_short_owner', 'trades': 24}],
            'reconciled_legacy_rows': 3,
            'global_trade_count': 25,
            'source_reconciliation': {'source_unique_hashes': 25,
                                      'missing_examples': ['0xowner'],
                                      'database_by_chain': {'1': 25,
                                                            'owner_address': '0xowner',
                                                            'nested': {'wallets': 20}},
                                      'source_by_chain': {'999': 24,
                                                          'wallet': {'count': 1}},
                                      'extra_by_chain': {'not-a-chain': 1}},
            'latest_refresh': {'state': 'complete', 'started_at': 1,
                               'by_chain': [{'wallets': 20}], 'error': '0xowner'},
        })
        self.assertNotIn('wallets', audit['by_chain'][0])
        self.assertNotIn('missing_examples', audit['source_reconciliation'])
        self.assertNotIn('by_chain', audit['latest_refresh'])
        self.assertNotIn('owner_address', audit['source_reconciliation']['database_by_chain'])
        self.assertNotIn('nested', audit['source_reconciliation']['database_by_chain'])
        self.assertEqual(audit['source_reconciliation']['database_by_chain'], {'1': 25})
        self.assertEqual(audit['source_reconciliation']['source_by_chain'], {'999': 24})
        self.assertEqual(audit['source_reconciliation']['extra_by_chain'], {})
        self.assertNotIn('0xowner', str(audit))
        self.assertEqual(audit['by_chain'][0]['attributed_trades'], 24)


class TestWalletAttribution(unittest.TestCase):
    def setUp(self):
        self.receipt = json.loads((Path(__file__).parent / 'fixtures/short_mint_receipt.json').read_text())
        self.trade = {'chain_id': 999, 'tx_hash': self.receipt['transactionHash'],
                      'quantity': '1000000000000000000000',
                      'collateral': '0x5555555555555555555555555555555555555555'}

    def test_real_receipt_uses_position_owner_not_relayer(self):
        wallet, status = recover_wallet(self.trade, self.receipt)
        self.assertEqual(status, 'verified_short_owner')
        self.assertEqual(wallet, '0x7c6db5dcfab3be735ac65e019b1ffb2bda214ff9')
        self.assertNotEqual(wallet, self.receipt['from'])

    def test_compact_proof_retains_attribution_and_ambiguity_checks(self):
        receipt = copy.deepcopy(self.receipt)
        receipt['logs'].append({'topics': ['unrelated'], 'data': 'large-transfer-data'})
        compact = receipt_proof(receipt)
        self.assertEqual(recover_wallet(self.trade, compact), recover_wallet(self.trade, receipt))
        self.assertEqual(len(compact['logs']), len(self.receipt['logs']))
        receipt['logs'].append(self.receipt['logs'][-1])
        self.assertEqual(recover_wallet(self.trade, receipt_proof(receipt))[1], 'ambiguous_or_missing_mint')

    def test_ethereum_receipt_uses_ethereum_deployment(self):
        receipt = json.loads((Path(__file__).parent / 'fixtures/ethereum_short_mint_receipt.json').read_text())
        trade = {'chain_id': 1, 'tx_hash': receipt['transactionHash'], 'quantity': '1000000000000000000',
                 'collateral': '0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2'}
        self.assertEqual(recover_wallet(trade, receipt),
                         ('0x47550e121654fed9bc17ed2f684e902a4b1ff102', 'verified_short_owner'))
        self.assertIsNone(recover_wallet({**trade, 'chain_id': 999}, receipt)[0])

    def test_rejects_ambiguous_mints_and_untrusted_emitters(self):
        receipt = copy.deepcopy(self.receipt)
        receipt['logs'].append(receipt['logs'][-1])
        self.assertIsNone(recover_wallet(self.trade, receipt)[0])
        receipt = copy.deepcopy(self.receipt)
        for log in receipt['logs']:
            log['address'] = '0x' + '1' * 40
        self.assertIsNone(recover_wallet(self.trade, receipt)[0])

    def test_requires_matching_quantity_collateral_hash_and_success(self):
        for field, value in [('quantity', '1'), ('collateral', '0xwrong'), ('chain_id', 1), ('tx_hash', 'other')]:
            trade = {**self.trade, field: value}
            self.assertIsNone(recover_wallet(trade, self.receipt)[0])
        self.assertIsNone(recover_wallet(self.trade, {**self.receipt, 'status': '0x0'})[0])
        self.assertEqual(recover_wallet(self.trade, None)[1], 'receipt_unavailable')


if __name__ == '__main__':
    unittest.main()
