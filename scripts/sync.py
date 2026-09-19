"""Incremental all-chain history sync with persisted source reconciliation.

python scripts/sync.py [--from-date 2025-07-01]
Stops on failed windows without advancing past the gap. Missing hashes are
retained but cannot support owner attribution or a unique transaction audit.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import os
import sys
import time

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db import get_db, init_db, insert_trades, get_last_sync_ts, set_last_sync_ts

API_BASE = os.getenv('RYSK_API_BASE', 'https://v12.rysk.finance/api')
HISTORY_URL = f'{API_BASE}/history'
START_TS = 1751328000
WINDOW = 7 * 86400
OVERLAP = 300


def fetch_window(session, start, end):
    for attempt in range(4):
        try:
            response = session.get(HISTORY_URL, params={'from': start, 'to': end}, timeout=30)
            response.raise_for_status()
            data = response.json()
            rows = data if isinstance(data, list) else data.get('trades', data.get('data'))
            if not isinstance(rows, list):
                raise ValueError('Unexpected history response; cursor not advanced')
            # Split dense windows to avoid silently accepting a capped response.
            if len(rows) >= 1000:
                if end - start <= 1:
                    raise ValueError('History response may be truncated within one second')
                mid = (start + end) // 2
                return fetch_window(session, start, mid) + fetch_window(session, mid, end)
            if any(not start <= int(row.get('createdAt', row.get('created_at', 0))) <= end for row in rows):
                raise ValueError('History API returned rows outside the requested window')
            return rows
        except (requests.RequestException, ValueError):
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)


def sync(from_ts=None):
    conn = get_db()
    init_db(conn)
    previous = get_last_sync_ts(conn)
    start = from_ts if from_ts is not None else max(START_TS, (previous or START_TS) - OVERLAP)
    now = int(time.time())
    cursor = start
    seen = set()
    hashless = set()
    source_counts = Counter()
    new = 0
    result = {'started_at': now, 'from_ts': start, 'through_ts': start, 'complete': False}
    try:
        with requests.Session() as session:
            while cursor < now:
                end = min(cursor + WINDOW, now)
                rows = fetch_window(session, cursor, end)
                new += insert_trades(conn, rows)
                required = {(int(row.get('chainId') or row.get('chain_id') or 999),
                             (row.get('txHash') or row.get('tx_hash')).lower())
                            for row in rows if row.get('txHash') or row.get('tx_hash')}
                conn.executemany('INSERT OR REPLACE INTO trade_source_observations VALUES (?,?,?)',
                                 [(chain, tx_hash, now) for chain, tx_hash in required])
                conn.commit()
                hashes = list({tx_hash for _, tx_hash in required})
                persisted = set()
                for index in range(0, len(hashes), 400):
                    chunk = hashes[index:index + 400]
                    placeholders = ','.join('?' for _ in chunk)
                    persisted.update((row[0], row[1].lower()) for row in conn.execute(
                        f'SELECT chain_id,tx_hash FROM trades WHERE tx_hash IN ({placeholders})', chunk))
                if required - persisted:
                    raise ValueError('Source transactions failed to persist; cursor not advanced past this window')
                for row in rows:
                    chain = int(row.get('chainId') or row.get('chain_id') or 999)
                    tx_hash = row.get('txHash') or row.get('tx_hash')
                    if tx_hash:
                        key = (chain, tx_hash.lower())
                        if key not in seen:
                            source_counts[chain] += 1
                            seen.add(key)
                    else:
                        hashless.add(json.dumps(row, sort_keys=True))
                # Full audits must not move an existing newer cursor backwards.
                if end > (previous or 0):
                    set_last_sync_ts(conn, end)
                result['through_ts'] = end
                cursor = end
                print(f'History through {datetime.fromtimestamp(end, timezone.utc).date()}: '
                      f'{len(rows)} source rows, {new} new stored', flush=True)
        stored = {(row[0], row[1].lower()) for row in conn.execute(
            'SELECT chain_id,tx_hash FROM trades WHERE tx_hash IS NOT NULL AND created_at BETWEEN ? AND ?',
            (start, now))}
        missing = seen - stored
        extra = stored - seen
        result.update({
            'complete': not missing, 'presence_recorded': True, 'new_trades': new, 'source_unique_hashes': len(seen),
            'source_hashless_rows': len(hashless), 'source_by_chain': dict(source_counts),
            'missing_from_database': len(missing), 'stored_not_in_source': len(extra),
            'extra_by_chain': dict(Counter(chain for chain, _ in extra)),
            'missing_examples': sorted(missing)[:10], 'extra_examples': sorted(extra)[:10],
            'database_by_chain': dict(conn.execute('SELECT chain_id,count(*) FROM trades GROUP BY chain_id').fetchall()),
        })
        if missing:
            raise ValueError('Some source transaction hashes were not persisted; inspect the saved audit')
        print(json.dumps(result, sort_keys=True), flush=True)
        return result
    except Exception as exc:
        result['error'] = str(exc)
        raise
    finally:
        # Keep both the latest incremental audit and the latest full-history audit.
        conn.execute('INSERT OR REPLACE INTO sync_meta(key,value) VALUES (?,?)',
                     ('last_trade_audit_json', json.dumps(result)))
        if start == START_TS:
            conn.execute('INSERT OR REPLACE INTO sync_meta(key,value) VALUES (?,?)',
                         ('full_trade_audit_json', json.dumps(result)))
        conn.commit()
        conn.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--from-date', help='UTC YYYY-MM-DD for a full or bounded reconciliation')
    args = parser.parse_args()
    start = int(datetime.strptime(args.from_date, '%Y-%m-%d').replace(tzinfo=timezone.utc).timestamp()) if args.from_date else None
    sync(from_ts=start)
