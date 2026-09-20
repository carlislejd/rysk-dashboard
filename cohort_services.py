"""Monthly repeat activity among on-chain attributed option sellers."""
from collections import defaultdict
from datetime import datetime, timezone
import math


def month_index(timestamp):
    date = datetime.fromtimestamp(timestamp, timezone.utc)
    return date.year * 12 + date.month - 1


def month_label(index):
    return f'{index // 12:04d}-{index % 12 + 1:02d}'


def get_retention_cohorts(conn, chain_id=None):
    # Read all history before assigning cohorts. Display windows must never
    # turn an established wallet into a newly acquired wallet.
    rows = conn.execute('''
        SELECT t.created_at,t.tx_hash,t.chain_id,CASE WHEN w.status='verified_short_owner' THEN w.wallet END AS wallet,w.status
        FROM trades t LEFT JOIN trade_wallets w
          ON t.chain_id=w.chain_id AND t.tx_hash=w.tx_hash
        WHERE (? IS NULL OR t.chain_id=?) ORDER BY t.created_at
    ''', (chain_id, chain_id)).fetchall()
    total = len(rows)
    attributed = [row for row in rows if row['wallet']]
    start = rows[0]['created_at'] if rows else None
    end = rows[-1]['created_at'] if rows else None
    latest = month_index(end) if end is not None else None
    coverage = defaultdict(lambda: {'total_trades': 0, 'attributed_trades': 0, 'pending_trades': 0})
    activity = defaultdict(lambda: defaultdict(int))
    for row in rows:
        month = month_index(row['created_at'])
        coverage[month]['total_trades'] += 1
        if row['tx_hash'] and row['status'] is None:
            coverage[month]['pending_trades'] += 1
        if row['wallet']:
            coverage[month]['attributed_trades'] += 1
            # Public addresses count as wallets, never as distinct people.
            activity[row['wallet'].lower()][month] += 1
    members = defaultdict(list)
    for wallet, months in activity.items():
        members[min(months)].append(wallet)
    width = latest - min(members) + 1 if members else 0
    cohorts = []
    for first, wallets in sorted(members.items()):
        cells = []
        for offset in range(width):
            month = first + offset
            if month > latest:
                cells.append(None)
                continue
            active = sum(activity[wallet].get(month, 0) > 0 for wallet in wallets)
            trades = sum(activity[wallet].get(month, 0) for wallet in wallets)
            pending = coverage[month]['pending_trades'] > 0 or coverage[first]['pending_trades'] > 0
            cells.append({
                'month': offset + 1, 'calendar_month': month_label(month),
                'active_wallets': None if pending else active,
                'retention_pct': None if pending else active / len(wallets) * 100,
                'trades': None if pending else trades,
                'trades_per_active_wallet': trades / active if active and not pending else None,
                'pending': pending,
                # Last month is conservatively partial: no verified ingestion watermark.
                'partial': month == latest,
                'attribution_complete': coverage[month]['attributed_trades'] == coverage[month]['total_trades'],
            })
        cohorts.append({'cohort': month_label(first), 'wallets': len(wallets), 'cells': cells})
    summary = []
    for offset in range(width):
        eligible = [row for row in cohorts if row['cells'][offset] is not None
                    and not row['cells'][offset]['partial']
                    and not row['cells'][offset]['pending']]
        denominator = sum(row['wallets'] for row in eligible)
        active = sum(row['cells'][offset]['active_wallets'] for row in eligible)
        summary.append({'month': offset + 1, 'eligible_wallets': denominator,
                        'active_wallets': active,
                        'retention_pct': active / denominator * 100 if denominator else None})
    return {
        'cohorts': cohorts, 'months': list(range(1, width + 1)), 'summary': summary,
        'pending_trades': sum(v['pending_trades'] for v in coverage.values()),
        'wallet_count': len(activity), 'total_trades': total, 'attributed_trades': len(attributed),
        'coverage_pct': len(attributed) / total * 100 if total else 0,
        'missing_hash_trades': sum(not row['tx_hash'] for row in rows),
        'observed_from': datetime.fromtimestamp(start, timezone.utc).isoformat() if start is not None else None,
        'observed_through': datetime.fromtimestamp(end, timezone.utc).isoformat() if end is not None else None,
        'monthly_coverage': [{'month': month_label(month), **counts} for month, counts in sorted(coverage.items())],
        'filters': {'chain_id': chain_id},
        'methodology': 'Month 1 is the first observed attributed option sale, in UTC calendar months. '
            'Later months count wallets with at least one option sale, even after a skipped month. '
            'Each percentage uses the original cohort size. Wallets are not people. '
            'Cohorts use all stored history; the Window filter does not apply. '
            'Missing attribution can shift cohort membership and undercount returns. '
            'History before the dataset begins is unknown. The final observed month is partial; '
            'future months are blank. Summaries pool original eligible cohort sizes, excluding partial '
            'and pending months; attribution gaps still make them provisional.',
    }


def public_retention_cohorts(data, min_participants=20):
    """Project internal cohort calculations into the public, count-free schema.

    The cohort service deliberately retains denominators for correct calculations
    and internal audit work.  This projection is the only shape suitable for a
    public endpoint: it excludes wallet totals and withholds rates where the
    original cohort is too small to publish.
    """
    cohorts = []
    for row in data['cohorts']:
        limited_history = row['wallets'] < min_participants
        cells = []
        for cell in row['cells']:
            if cell is None:
                cells.append(None)
                continue
            public_cell = {
                'month': cell['month'],
                'calendar_month': cell['calendar_month'],
                'trades': cell['trades'],
                'pending': cell['pending'],
                'partial': cell['partial'],
                'attribution_complete': cell['attribution_complete'],
                'limited_history': limited_history,
            }
            if not limited_history:
                public_cell['retention_pct'] = cell['retention_pct']
            else:
                public_cell['retention_pct'] = None
            cells.append(public_cell)
        cohorts.append({
            'cohort': row['cohort'],
            'limited_history': limited_history,
            'cells': cells,
        })

    summary = []
    for row in data['summary']:
        limited_history = row['eligible_wallets'] < min_participants
        summary.append({
            'month': row['month'],
            'retention_pct': None if limited_history else row['retention_pct'],
            'limited_history': limited_history,
        })

    # These fields are all trade-level totals or descriptive metadata.  Do not
    # copy data wholesale: an internal field added later must not become public
    # without an explicit privacy review.
    return {
        'cohorts': cohorts,
        'months': data['months'],
        'summary': summary,
        'pending_trades': data['pending_trades'],
        'total_trades': data['total_trades'],
        'attributed_trades': data['attributed_trades'],
        'coverage_pct': data['coverage_pct'],
        'missing_hash_trades': data['missing_hash_trades'],
        'observed_from': data['observed_from'],
        'observed_through': data['observed_through'],
        'monthly_coverage': [
            {
                'month': row['month'],
                'total_trades': row['total_trades'],
                'attributed_trades': row['attributed_trades'],
                'pending_trades': row['pending_trades'],
            }
            for row in data['monthly_coverage']
        ],
        'filters': data['filters'],
        'methodology': data['methodology'],
    }


def public_retention_audit(audit):
    """Return a strictly allowlisted, trade-level attribution audit."""
    def nonnegative_number(value):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        if not math.isfinite(value) or value < 0:
            return None
        return value

    def chain_count_map(value):
        """Keep only numeric chain identifiers and finite trade totals."""
        if not isinstance(value, dict):
            return {}
        result = {}
        for chain_id, count in value.items():
            try:
                normalized_chain_id = str(int(chain_id))
            except (TypeError, ValueError):
                continue
            numeric_count = nonnegative_number(count)
            if numeric_count is not None:
                result[normalized_chain_id] = numeric_count
        return result

    def numeric_fields(row, fields):
        return {
            key: number for key in fields
            if (number := nonnegative_number(row.get(key))) is not None
        }

    chain_fields = (
        'chain_id', 'chain_name', 'total_trades', 'hashed_trades',
        'unique_hashes', 'attributed_trades', 'pending_trades',
        'unavailable_receipts', 'missing_hash_trades', 'unattributed_trades',
        'coverage_pct', 'source_trade_count', 'source_attributed_trades',
    )
    public_chains = []
    for row in audit.get('by_chain', []):
        if not isinstance(row, dict):
            continue
        public_row = numeric_fields(row, tuple(key for key in chain_fields if key != 'chain_name'))
        if isinstance(row.get('chain_name'), str):
            public_row['chain_name'] = row['chain_name']
        public_chains.append(public_row)

    safe_statuses = {'verified_short_owner', 'receipt_unavailable', 'pending', 'missing_hash'}
    public_statuses = []
    for row in audit.get('statuses', []):
        if not isinstance(row, dict):
            continue
        public_row = numeric_fields(row, ('chain_id', 'trades'))
        status = row.get('status')
        if isinstance(status, str):
            public_row['status'] = status if status in safe_statuses else 'other'
        public_statuses.append(public_row)

    # Full source audits can include representative transaction hashes.  The
    # dashboard only needs aggregate reconciliation measures.
    source = audit.get('source_reconciliation')
    public_source = None
    if isinstance(source, dict):
        public_source = numeric_fields(source, (
            'started_at', 'through_ts', 'new_trades', 'source_unique_hashes',
            'source_hashless_rows', 'missing_from_database', 'stored_not_in_source',
        ))
        for key in ('complete', 'presence_recorded'):
            if isinstance(source.get(key), bool):
                public_source[key] = source[key]
        for key in ('source_by_chain', 'extra_by_chain', 'database_by_chain'):
            public_source[key] = chain_count_map(source.get(key))

    refresh = audit.get('latest_refresh')
    public_refresh = None
    if isinstance(refresh, dict):
        public_refresh = numeric_fields(refresh, ('started_at', 'finished_at'))
        if refresh.get('state') in {'queued', 'running', 'complete', 'failed', 'never_run'}:
            public_refresh['state'] = refresh['state']
        if isinstance(refresh.get('success'), bool):
            public_refresh['success'] = refresh['success']
    return {
        'by_chain': public_chains,
        'statuses': public_statuses,
        'reconciled_legacy_rows': audit.get('reconciled_legacy_rows', 0),
        'global_trade_count': audit.get('global_trade_count', 0),
        'source_reconciliation': public_source,
        'latest_refresh': public_refresh,
    }


def get_retention_audit(conn):
    """Reconcile attribution against the exact trades table used by Global."""
    import json
    from chain_metadata import chain_meta

    chains = []
    for row in conn.execute('''
        SELECT t.chain_id,COUNT(*) AS total_trades,COUNT(t.tx_hash) AS hashed_trades,
               COUNT(DISTINCT t.tx_hash) AS unique_hashes,
               SUM(CASE WHEN w.status='verified_short_owner' THEN 1 ELSE 0 END) AS attributed_trades,
               COUNT(DISTINCT CASE WHEN w.status='verified_short_owner' THEN w.wallet END) AS wallets,
               SUM(CASE WHEN t.tx_hash IS NOT NULL AND w.status IS NULL THEN 1 ELSE 0 END) AS pending_trades,
               SUM(CASE WHEN w.status='receipt_unavailable' THEN 1 ELSE 0 END) AS unavailable_receipts
        FROM trades t LEFT JOIN trade_wallets w ON t.chain_id=w.chain_id AND t.tx_hash=w.tx_hash
        GROUP BY t.chain_id ORDER BY t.chain_id
    '''):
        item = dict(row)
        item['chain_name'] = chain_meta(row['chain_id'])['name']
        item['missing_hash_trades'] = row['total_trades'] - row['hashed_trades']
        item['unattributed_trades'] = row['total_trades'] - row['attributed_trades']
        item['coverage_pct'] = row['attributed_trades'] / row['total_trades'] * 100
        chains.append(item)
    statuses = [dict(row) for row in conn.execute('''
        SELECT t.chain_id,COALESCE(w.status,CASE WHEN t.tx_hash IS NULL THEN 'missing_hash'
            ELSE 'pending' END) AS status,COUNT(*) AS trades
        FROM trades t LEFT JOIN trade_wallets w ON t.chain_id=w.chain_id AND t.tx_hash=w.tx_hash
        GROUP BY t.chain_id,2 ORDER BY t.chain_id,2
    ''')]
    metadata = dict(conn.execute("SELECT key,value FROM sync_meta WHERE key IN ('last_trade_audit_json','full_trade_audit_json','last_cohort_refresh_json')").fetchall())
    full_audit = json.loads(metadata['full_trade_audit_json']) if 'full_trade_audit_json' in metadata else None
    if full_audit and full_audit.get('presence_recorded'):
        for chain in chains:
            source = conn.execute("""
                SELECT COUNT(*),SUM(CASE WHEN w.status='verified_short_owner' THEN 1 ELSE 0 END)
                FROM trade_source_observations s LEFT JOIN trade_wallets w
                ON s.chain_id=w.chain_id AND s.tx_hash=w.tx_hash
                WHERE s.chain_id=? AND s.last_seen_at >= ?
            """, (chain['chain_id'], full_audit['started_at'])).fetchone()
            chain['source_trade_count'] = source[0]
            chain['source_attributed_trades'] = source[1] or 0
    return {'by_chain': chains, 'statuses': statuses,
            # Local and production snapshots can preserve the same legacy
            # representation with different insertion/settlement metadata.
            'reconciled_legacy_rows': conn.execute('''SELECT COUNT(*) FROM (
                SELECT chain_id,canonical_tx_hash,json_extract(original_json,'$.tx_hash')
                FROM reconciled_trade_records GROUP BY 1,2,3
            )''').fetchone()[0],
            'global_trade_count': sum(row['total_trades'] for row in chains),
            'source_reconciliation': json.loads(metadata['full_trade_audit_json']) if 'full_trade_audit_json' in metadata else None,
            'latest_sync': json.loads(metadata['last_trade_audit_json']) if 'last_trade_audit_json' in metadata else None,
            'latest_refresh': json.loads(metadata['last_cohort_refresh_json']) if 'last_cohort_refresh_json' in metadata else None}
