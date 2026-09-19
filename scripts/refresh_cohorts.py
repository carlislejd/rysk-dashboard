"""Daily incremental all-chain history + owner refresh, with a single-run lock.

Run: poetry run python scripts/refresh_cohorts.py
Caches are durable in RYSK_DB_PATH. Historical receipt gaps are not fetched
again daily; only newly seen trades and unavailable receipts in the last week
are attempted. Use backfill_wallets.py --retry for an explicit historical retry.
"""
import fcntl
import json
import os
import sys
import time
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db import DB_PATH, get_db, init_db
from scripts.sync import sync
from scripts.backfill_wallets import main as recover
from cohort_services import get_retention_audit
from cohort_jobs import save_refresh_status
from scripts.reconcile_legacy_trades import reconcile


def refresh():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    inherited_fd = os.getenv('RYSK_REFRESH_LOCK_FD')
    lock_file = os.fdopen(int(inherited_fd), 'a') if inherited_fd else open(DB_PATH + '.refresh.lock', 'a')
    with lock_file as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('A cohort refresh is already running; skipping duplicate run')
            return 0
        result = {'run_id': os.getenv('RYSK_REFRESH_RUN_ID') or uuid.uuid4().hex, 'state': 'running',
                  'started_at': int(time.time()), 'success': False}
        try:
            save_refresh_status(result)
            result['sync'] = sync()
            failures = []
            for chain in (1, 999):
                if recover(['--chain', str(chain), '--workers', '4', '--batch-size', '3', '--rate', '6']):
                    failures.append(chain)
            conn = get_db()
            try:
                result['legacy_reconciliation'] = reconcile(conn)
            finally:
                conn.close()
            result['failed_chains'] = failures
            result['success'] = not failures
            return 1 if failures else 0
        except Exception as exc:
            result['error'] = str(exc)
            raise
        finally:
            result['finished_at'] = int(time.time())
            result['state'] = 'complete' if result['success'] else 'failed'
            conn = get_db()
            init_db(conn)
            result['by_chain'] = get_retention_audit(conn)['by_chain']
            conn.execute('INSERT OR REPLACE INTO sync_meta(key,value) VALUES (?,?)',
                         ('last_cohort_refresh_json', json.dumps(result)))
            conn.commit()
            conn.close()
            print(json.dumps(result, sort_keys=True), flush=True)


if __name__ == '__main__':
    raise SystemExit(refresh())
