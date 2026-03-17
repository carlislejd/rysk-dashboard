"""
Backfill script — walks from July 1 2025 to now in 7-day windows,
fetching all trades from the global history endpoint.

Usage: python scripts/backfill.py
"""

import os
import sys
import time

import requests

# Allow imports from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import get_db, init_db, insert_trades, get_last_sync_ts, set_last_sync_ts

API_BASE = os.getenv("RYSK_API_BASE", "https://v12.rysk.finance/api")
HISTORY_URL = f"{API_BASE}/history"

START_TS = 1751328000  # July 1 2025 00:00 UTC
WINDOW = 604800  # 7 days in seconds


def backfill():
    conn = get_db()
    init_db(conn)

    # Resume from last sync if available
    last_ts = get_last_sync_ts(conn)
    cursor = last_ts if last_ts and last_ts > START_TS else START_TS
    now = int(time.time())

    if cursor >= now:
        print("Already up to date.")
        conn.close()
        return

    print(f"Backfilling from {cursor} to {now}")
    window_count = 0

    while cursor < now:
        end = min(cursor + WINDOW, now)
        window_count += 1
        print(f"  Window {window_count}: {cursor} → {end} ...", end=" ", flush=True)

        try:
            resp = requests.get(HISTORY_URL, params={"from": cursor, "to": end}, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"ERROR: {e}")
            cursor = end
            time.sleep(2)
            continue

        trades = data if isinstance(data, list) else data.get("trades", data.get("data", []))
        before = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
        insert_trades(conn, trades)
        after = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
        new = after - before

        set_last_sync_ts(conn, end)
        print(f"fetched {len(trades)}, inserted {new} new")

        cursor = end
        time.sleep(1)  # rate limit

    total = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
    print(f"\nDone. Total trades in DB: {total}")
    conn.close()


if __name__ == "__main__":
    backfill()
