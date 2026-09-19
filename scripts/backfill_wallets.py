"""Resume receipt attribution: poetry run python scripts/backfill_wallets.py.

Uses public read-only RPC. Successful and rejected receipts are cached. New
trades and unavailable receipts from the past week are retried on the next run;
--retry also rechecks historical gaps and cached rejects.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
import json
import os
import sys
import time
import threading

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db import get_db, init_db
from wallet_attribution import recover_wallet, receipt_proof


_http = threading.local()
_rate_lock = threading.Lock()
_next_request_at = 0.0


def completed_batches(pool, batches, rpc, rate, workers):
    """Bound retained receipt payloads even during a months-long backfill."""
    iterator = iter(batches)
    pending = set()
    for _ in range(workers):
        batch = next(iterator, None)
        if batch is not None:
            pending.add(pool.submit(fetch_batch, batch, rpc, rate))
    while pending:
        done, pending = wait(pending, return_when=FIRST_COMPLETED)
        for future in done:
            yield future
            batch = next(iterator, None)
            if batch is not None:
                pending.add(pool.submit(fetch_batch, batch, rpc, rate))


def fetch_batch(rows, rpc, rate=8.0):
    global _next_request_at
    if not hasattr(_http, "session"):
        _http.session = requests.Session()
    payload = [{'jsonrpc': '2.0', 'id': i, 'method': 'eth_getTransactionReceipt',
                'params': [row['tx_hash']]} for i, row in enumerate(rows)]
    for attempt in range(4):
        with _rate_lock:
            delay = max(0, _next_request_at - time.monotonic())
            _next_request_at = max(_next_request_at, time.monotonic()) + len(payload) / rate
        if delay:
            time.sleep(delay)
        try:
            response = _http.session.post(rpc, json=payload, timeout=45)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, list):
                raise ValueError('RPC rejected batch: ' + str(data.get('error', {}).get('message', 'unknown error')))
            lookup = {item.get('id'): item for item in data}
            if any(i not in lookup or 'error' in lookup[i] for i in range(len(rows))):
                raise ValueError('RPC returned an incomplete or rejected batch')
            return [(row, lookup[i].get('result')) for i, row in enumerate(rows)]
        except (requests.RequestException, ValueError):
            if attempt == 3:
                raise
            # A shared cooldown prevents concurrent workers hammering a limited provider.
            with _rate_lock:
                _next_request_at = max(_next_request_at, time.monotonic() + 15 * (attempt + 1))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--chain', type=int, choices=[1, 999], default=999)
    parser.add_argument('--limit', type=int, default=0)
    parser.add_argument('--batch-size', type=int, default=20)
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--retry', action='store_true')
    parser.add_argument('--rate', type=float, default=8, help='Maximum receipt calls per second across workers')
    args = parser.parse_args(argv)
    if not 0 < args.rate <= 10:
        parser.error('Use rate > 0 and <= 10')
    if args.limit < 0 or not 1 <= args.batch_size <= 20 or not 1 <= args.workers <= 12:
        parser.error('Use limit >= 0, batch-size 1..20 and workers 1..12')
    conn = get_db()
    init_db(conn)
    rows = [dict(row) for row in conn.execute('''
        SELECT t.* FROM trades t LEFT JOIN trade_wallets w
        ON t.chain_id=w.chain_id AND t.tx_hash=w.tx_hash
        WHERE t.chain_id=? AND t.tx_hash IS NOT NULL
        AND (w.tx_hash IS NULL OR (w.status='receipt_unavailable' AND t.created_at >= ?)
             OR (? AND w.wallet IS NULL))
        ORDER BY t.created_at
        LIMIT ?
    ''', (args.chain, int(time.time()) - 7 * 86400, args.retry, args.limit or -1))]
    if not rows:
        print(f'Chain {args.chain}: no new transactions require attribution', flush=True)
        conn.close()
        return 0
    rpc = (os.getenv('ETHEREUM_RPC_URL', 'https://ethereum-rpc.publicnode.com') if args.chain == 1
           else os.getenv('RPC_URL', 'https://rpc.hyperliquid.xyz/evm'))
    check = requests.post(rpc, json={'jsonrpc': '2.0', 'id': 1, 'method': 'eth_chainId', 'params': []}, timeout=20)
    check.raise_for_status()
    if int(check.json().get('result') or '0x0', 16) != args.chain:
        raise ValueError(f'RPC must serve the requested chain {args.chain}')
    batches = [rows[i:i + args.batch_size] for i in range(0, len(rows), args.batch_size)]
    print(f'Attributing {len(rows)} transactions in {len(batches)} batches', flush=True)
    processed = verified = failures = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for future in completed_batches(pool, batches, rpc, args.rate, args.workers):
            try:
                results = future.result()
            except Exception as exc:
                failures += 1
                print(f'Batch failed (resume to retry): {type(exc).__name__}', flush=True)
                continue
            for row, receipt in results:
                wallet, status = recover_wallet(row, receipt)
                conn.execute('''INSERT OR REPLACE INTO trade_wallets
                    (chain_id,tx_hash,wallet,status,receipt_json,checked_at) VALUES (?,?,?,?,?,?)''',
                    (row['chain_id'], row['tx_hash'], wallet, status,
                     json.dumps(receipt_proof(receipt) if wallet else receipt, separators=(',', ':'))
                     if receipt else None, int(time.time())))
                processed += 1
                verified += bool(wallet)
            conn.commit()
            if processed % 300 == 0 or processed == len(rows):
                print(f'{processed}/{len(rows)} checked; {verified} verified; {failures} failed batches', flush=True)
    conn.close()
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
