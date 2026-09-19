import json
from pathlib import Path
import sqlite3
import unittest

from db import init_db, insert_trades
from scripts.cohort_cache import merge_cache
from wallet_attribution import recover_wallet


class TestCacheTransfer(unittest.TestCase):
    def test_repeat_import_preserves_deployment_rows_and_validates_proof(self):
        source, target = sqlite3.connect(':memory:'), sqlite3.connect(':memory:')
        try:
            for conn in (source, target):
                conn.row_factory = sqlite3.Row
                init_db(conn)
            receipt = json.loads((Path(__file__).parent / 'fixtures/short_mint_receipt.json').read_text())
            row = {'txHash': receipt['transactionHash'], 'chainId': 999, 'createdAt': 10,
                   'expiry': 20, 'address': 'asset', 'symbol': 'HYPE',
                   'quantity': '1000000000000000000000', 'collateral': '0x' + '5' * 40}
            insert_trades(source, [row])
            trade = dict(source.execute('SELECT * FROM trades').fetchone())
            wallet, status = recover_wallet(trade, receipt)
            source.execute('INSERT INTO trade_wallets VALUES (?,?,?,?,?,?)',
                           (999, row['txHash'], wallet, status, json.dumps(receipt), 100))
            insert_trades(target, [{**row, 'txHash': 'deployment-only'}])
            self.assertEqual(merge_cache(source, target)['new_trades'], 1)
            target.execute("UPDATE trades SET outcome='Returned' WHERE tx_hash=?", (row['txHash'],))
            target.commit()
            self.assertEqual(merge_cache(source, target)['new_trades'], 0)
            self.assertEqual(target.execute('SELECT count(*) FROM trades').fetchone()[0], 2)
            self.assertEqual(target.execute('SELECT wallet FROM trade_wallets').fetchone()[0], wallet)
            self.assertEqual(target.execute('SELECT outcome FROM trades WHERE tx_hash=?', (row['txHash'],)).fetchone()[0], 'Returned')
            source.execute("UPDATE trade_wallets SET wallet='wrong'")
            with self.assertRaises(ValueError):
                merge_cache(source, target)
        finally:
            source.close()
            target.close()


class TestCacheUpload(unittest.TestCase):
    def test_upload_requires_existing_admin_token_and_file(self):
        import app
        from unittest.mock import patch
        from io import BytesIO
        client = app.app.test_client()
        with patch.object(app, 'ADMIN_BACKFILL_TOKEN', 'test-token'):
            self.assertEqual(client.post('/api/admin/cohort-cache').status_code, 401)
            headers = {'X-Admin-Token': 'test-token'}
            self.assertEqual(client.post('/api/admin/cohort-cache', headers=headers).status_code, 400)
            with patch('scripts.cohort_cache.import_cache', return_value={'new_trades': 0}) as merge:
                result = client.post('/api/admin/cohort-cache', headers=headers,
                                     data={'snapshot': (BytesIO(b'example'), 'snapshot.gz')})
                self.assertEqual(result.status_code, 200)
                merge.assert_called_once()
