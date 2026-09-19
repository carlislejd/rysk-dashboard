"""Export a consistent SQLite snapshot, or merge one into a deployment's cache.

Export: python scripts/cohort_cache.py export data/cohort-seed.sqlite.gz
Import: RYSK_DB_PATH=/data/rysk_trades.db python scripts/cohort_cache.py import /data/cohort-seed.sqlite.gz
Import adds missing trades/proofs and preserves existing deployment data.
"""
import argparse
import gzip
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db import get_db, init_db, insert_trades, set_last_sync_ts
from scripts.reconcile_legacy_trades import reconcile
from wallet_attribution import recover_wallet


def export_cache(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as directory:
        snapshot = os.path.join(directory, 'snapshot.db')
        source, target = get_db(), sqlite3.connect(snapshot)
        try:
            source.backup(target)
            target.execute('VACUUM')
        finally:
            target.close()
            source.close()
        with open(snapshot, 'rb') as source, gzip.open(path, 'wb') as target:
            shutil.copyfileobj(source, target)
    return {'snapshot': str(path), 'bytes': os.path.getsize(path)}


def merge_cache(source, target):
    """Only schema-defined data is imported; no SQL from the snapshot is run."""
    source.row_factory = sqlite3.Row
    init_db(target)
    trades = [dict(row) for row in source.execute('SELECT * FROM trades')]
    imported = insert_trades(target, trades)
    with target:
        for row in trades:
            target.execute('''UPDATE trades SET outcome=COALESCE(outcome,?),
                           expiry_price_f=COALESCE(expiry_price_f,?) WHERE chain_id=? AND tx_hash=?''',
                           (row.get('outcome'), row.get('expiry_price_f'), row['chain_id'], row['tx_hash']))
        proofs = 0
        for row in source.execute('SELECT * FROM trade_wallets'):
            if row['wallet']:
                trade = target.execute('SELECT * FROM trades WHERE chain_id=? AND tx_hash=?',
                                       (row['chain_id'], row['tx_hash'])).fetchone()
                if trade is None:
                    continue
                derived = recover_wallet(dict(trade), json.loads(row['receipt_json']))
                if derived != (row['wallet'], row['status']):
                    raise ValueError('Imported wallet proof does not validate against destination trade')
            result = target.execute('''INSERT INTO trade_wallets VALUES (?,?,?,?,?,?)
                ON CONFLICT(chain_id,tx_hash) DO UPDATE SET wallet=excluded.wallet,status=excluded.status,
                receipt_json=excluded.receipt_json,checked_at=excluded.checked_at
                WHERE trade_wallets.wallet IS NULL AND excluded.wallet IS NOT NULL''', tuple(row))
            proofs += result.rowcount
        for row in source.execute('SELECT * FROM trade_source_observations'):
            target.execute('''INSERT INTO trade_source_observations VALUES (?,?,?)
                ON CONFLICT(chain_id,tx_hash) DO UPDATE SET last_seen_at=MAX(last_seen_at,excluded.last_seen_at)''', tuple(row))
        for row in source.execute('SELECT * FROM reconciled_trade_records'):
            target.execute('INSERT OR IGNORE INTO reconciled_trade_records VALUES (?,?,?,?,?,?)', tuple(row))
        for key in ('full_trade_audit_json', 'last_trade_audit_json'):
            row = source.execute('SELECT value FROM sync_meta WHERE key=?', (key,)).fetchone()
            if not row:
                continue
            incoming = json.loads(row[0])
            existing = target.execute('SELECT value FROM sync_meta WHERE key=?', (key,)).fetchone()
            if incoming.get('complete') and (not existing or incoming['started_at'] > json.loads(existing[0]).get('started_at', 0)):
                target.execute('INSERT OR REPLACE INTO sync_meta VALUES (?,?)', (key, row[0]))
    # Advance only to a completed full audit, never an unverified source cursor.
    full = source.execute("SELECT value FROM sync_meta WHERE key='full_trade_audit_json'").fetchone()
    if full and json.loads(full[0]).get('complete'):
        set_last_sync_ts(target, json.loads(full[0])['through_ts'])
    return {'new_trades': imported, 'new_or_verified_proofs': proofs, 'legacy': reconcile(target)}


def import_cache(path):
    with tempfile.TemporaryDirectory() as directory:
        snapshot = os.path.join(directory, 'snapshot.db')
        with gzip.open(path, 'rb') as source, open(snapshot, 'wb') as target:
            size = 0
            while True:
                chunk = source.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > 256 * 1024 * 1024:
                    raise ValueError('Snapshot exceeds 256 MiB; compact the source database first')
                target.write(chunk)
        source, target = sqlite3.connect(snapshot), get_db()
        try:
            return merge_cache(source, target)
        finally:
            source.close()
            target.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('export', 'import', 'upload'))
    parser.add_argument('path')
    args = parser.parse_args()
    if args.action == 'upload':
        import requests
        url = os.environ['RYSK_SERVICE_URL'].rstrip('/') + '/api/admin/cohort-cache'
        with open(args.path, 'rb') as snapshot:
            response = requests.post(url, headers={'X-Admin-Token': os.environ['ADMIN_BACKFILL_TOKEN']},
                                     files={'snapshot': ('snapshot.sqlite.gz', snapshot, 'application/gzip')},
                                     timeout=120)
        response.raise_for_status()
        print(json.dumps(response.json()))
    else:
        print(json.dumps(export_cache(args.path) if args.action == 'export' else import_cache(args.path)))
