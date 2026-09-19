"""Archive uniquely matched legacy trade representations without losing records.

Requires a completed full source audit and verified on-chain replacement.
Unmatched, ambiguous, or genuinely separate verified trades remain untouched.
"""
from collections import defaultdict
import hashlib
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db import get_db, init_db

# Every source field must agree, including price, fees, collateral and direction.
FIELDS = ('chain_id', 'created_at', 'expiry', 'address', 'is_buy', 'is_put',
          'symbol', 'quantity', 'strike', 'price', 'premium', 'fees', 'apr',
          'collateral', 'usd', 'status')


def reconcile(conn):
    raw = conn.execute("SELECT value FROM sync_meta WHERE key='full_trade_audit_json'").fetchone()
    audit = json.loads(raw[0]) if raw else {}
    if not audit.get('complete') or not audit.get('presence_recorded'):
        return {'archived': 0, 'reason': 'Full source audit required'}
    current = {(r[0], r[1]) for r in conn.execute(
        'SELECT chain_id,tx_hash FROM trade_source_observations WHERE last_seen_at>=?',
        (audit['started_at'],))}
    owners = {(r[0], r[1]): r[2] for r in conn.execute('SELECT chain_id,tx_hash,status FROM trade_wallets')}
    rows = [dict(r) for r in conn.execute('SELECT rowid AS legacy_rowid,* FROM trades')]
    indexed, legacy = defaultdict(list), defaultdict(list)
    for row in rows:
        key = (row['chain_id'], row['tx_hash'])
        signature = tuple(row[field] for field in FIELDS)
        if key in current:
            indexed[signature].append(row)
        elif not row['tx_hash'] or owners.get(key) == 'receipt_unavailable':
            legacy[signature].append(row)
    count = 0
    with conn:
        for signature, originals in legacy.items():
            matches = indexed[signature]
            if len(originals) != 1 or len(matches) != 1:
                continue
            old, new = originals[0], matches[0]
            if owners.get((new['chain_id'], new['tx_hash'])) != 'verified_short_owner':
                continue
            # Conflicting settlement facts require a separate investigation.
            if any(old.get(k) is not None and new.get(k) is not None and old[k] != new[k]
                   for k in ('outcome', 'expiry_price_f')):
                continue
            payload = json.dumps({k: v for k, v in old.items() if k != 'legacy_rowid'}, sort_keys=True)
            record_key = hashlib.sha256(payload.encode()).hexdigest()
            conn.execute('INSERT OR IGNORE INTO reconciled_trade_records VALUES (?,?,?,?,?,?)',
                         (record_key, old['chain_id'], new['tx_hash'], payload,
                          'Exact unique source-field match to verified current transaction', int(time.time())))
            conn.execute('''UPDATE trades SET outcome=COALESCE(outcome,?),
                         expiry_price_f=COALESCE(expiry_price_f,?) WHERE rowid=?''',
                         (old.get('outcome'), old.get('expiry_price_f'), new['legacy_rowid']))
            conn.execute('DELETE FROM trades WHERE rowid=? AND tx_hash IS ?',
                         (old['legacy_rowid'], old['tx_hash']))
            count += 1
    return {'archived': count, 'preserved_in': 'reconciled_trade_records'}


if __name__ == '__main__':
    connection = get_db()
    init_db(connection)
    print(json.dumps(reconcile(connection)))
    connection.close()
