"""
Incremental sync script — fetches new trades since last sync.
Overlaps by 5 minutes to catch stragglers.

Usage: python scripts/sync.py
       Or schedule via cron: */10 * * * * cd /path/to/rysk && python scripts/sync.py
"""

import os
import sys
import time

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import get_db, init_db, insert_trades, get_last_sync_ts, set_last_sync_ts

API_BASE = os.getenv("RYSK_API_BASE", "https://v12.rysk.finance/api")
HISTORY_URL = f"{API_BASE}/history"

WINDOW = 604800  # 7 days
OVERLAP = 300  # 5 minutes


def sync():
    conn = get_db()
    init_db(conn)

    last_ts = get_last_sync_ts(conn)
    if not last_ts:
        print("No previous sync found. Run backfill.py first.")
        conn.close()
        return

    now = int(time.time())
    cursor = last_ts - OVERLAP  # overlap to catch stragglers

    if cursor >= now:
        print("Already up to date.")
        conn.close()
        return

    total_fetched = 0
    total_new = 0

    while cursor < now:
        end = min(cursor + WINDOW, now)
        try:
            resp = requests.get(HISTORY_URL, params={"from": cursor, "to": end}, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"Error fetching {cursor}→{end}: {e}")
            cursor = end
            time.sleep(2)
            continue

        trades = data if isinstance(data, list) else data.get("trades", data.get("data", []))
        before = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
        insert_trades(conn, trades)
        after = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
        new = after - before

        total_fetched += len(trades)
        total_new += new

        set_last_sync_ts(conn, end)
        cursor = end
        if cursor < now:
            time.sleep(1)

    print(f"Sync complete. Fetched {total_fetched} trades, {total_new} new.")
    conn.close()


if __name__ == "__main__":
    sync()
