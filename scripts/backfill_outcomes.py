"""
Backfill outcome data for expired trades.

Groups trades by (symbol, expiry) to minimize RPC calls, then uses the
on-chain oracle to determine settlement prices and compute outcomes.

Usage: poetry run python scripts/backfill_outcomes.py
"""

import os
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import get_db, init_db
from expiry_price import get_expiry_price, get_underlying_address


def backfill_outcomes():
    conn = get_db()
    init_db(conn)

    now = int(time.time())

    # Find distinct (symbol, chain, expiry, underlying) groups that need outcomes.
    groups = conn.execute("""
        SELECT DISTINCT symbol, expiry, chain_id, address
        FROM trades
        WHERE expiry IS NOT NULL
          AND expiry < ?
          AND (
            outcome IS NULL
            OR (outcome = 'Unknown' AND (expiry_price_f IS NULL OR expiry_price_f = 0))
          )
          AND symbol != ''
        ORDER BY expiry
    """, (now,)).fetchall()

    if not groups:
        print("No expired trades need outcome annotation.")
        conn.close()
        return

    print(f"Processing {len(groups)} (symbol, chain, expiry) groups...")
    total_updated = 0

    for i, group in enumerate(groups):
        symbol = group["symbol"]
        expiry_ts = group["expiry"]
        chain_id = group["chain_id"]
        underlying_address = group["address"]

        asset_address = underlying_address or get_underlying_address(symbol, chain_id=chain_id)
        if not asset_address:
            print(f"  [{i+1}/{len(groups)}] {symbol} chain={chain_id} @ {expiry_ts} — no underlying address, skipping")
            continue

        # Get settlement price from oracle
        price, finalized = get_expiry_price(asset_address, expiry_ts, chain_id=chain_id)

        # Fallback: try midnight UTC normalization
        if (price is None or not finalized) and expiry_ts:
            try:
                dt = datetime.fromtimestamp(expiry_ts, tz=timezone.utc)
                midnight_ts = int(dt.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
                if midnight_ts != expiry_ts:
                    price_fb, finalized_fb = get_expiry_price(asset_address, midnight_ts, chain_id=chain_id)
                    if price_fb is not None:
                        price, finalized = price_fb, finalized_fb
            except Exception:
                pass

        chain_predicate = "chain_id IS NULL" if chain_id is None else "chain_id = ?"
        group_params = [symbol, expiry_ts]
        if chain_id is not None:
            group_params.append(chain_id)
        address_predicate = "address IS NULL" if underlying_address is None else "address = ?"
        if underlying_address is not None:
            group_params.append(underlying_address)

        if price is None or not finalized:
            # Mark unresolved rows as Unknown. Assigned/Returned rows are never overwritten.
            conn.execute(f"""
                UPDATE trades
                SET outcome = 'Unknown'
                WHERE symbol = ? AND expiry = ? AND {chain_predicate} AND {address_predicate}
                  AND (
                    outcome IS NULL
                    OR (outcome = 'Unknown' AND (expiry_price_f IS NULL OR expiry_price_f = 0))
                  )
            """, group_params)
            count = conn.total_changes
            conn.commit()
            print(f"  [{i+1}/{len(groups)}] {symbol} chain={chain_id} @ {expiry_ts} — price not finalized, {count} marked Unknown")
            total_updated += count
            continue

        # Compute outcomes only for unresolved rows in this group.
        trades = conn.execute(f"""
            SELECT rowid, is_put, strike_f
            FROM trades
            WHERE symbol = ? AND expiry = ? AND {chain_predicate} AND {address_predicate}
              AND (
                outcome IS NULL
                OR (outcome = 'Unknown' AND (expiry_price_f IS NULL OR expiry_price_f = 0))
              )
        """, group_params).fetchall()

        for trade in trades:
            is_put = trade["is_put"]
            strike = trade["strike_f"]

            if is_put:
                outcome = "Assigned" if price <= strike else "Returned"
            else:
                outcome = "Returned" if price <= strike else "Assigned"

            conn.execute("""
                UPDATE trades SET outcome = ?, expiry_price_f = ?
                WHERE rowid = ?
            """, (outcome, price, trade["rowid"]))

        conn.commit()
        count = len(trades)
        total_updated += count
        assigned = sum(1 for t in trades if (t["is_put"] and price <= t["strike_f"]) or (not t["is_put"] and price > t["strike_f"]))
        print(f"  [{i+1}/{len(groups)}] {symbol} chain={chain_id} @ {expiry_ts} — price=${price:,.2f}, {count} trades ({assigned} assigned, {count - assigned} returned)")

        time.sleep(0.5)  # rate limit RPC

    total = conn.execute("SELECT COUNT(*) FROM trades WHERE outcome IS NOT NULL").fetchone()[0]
    print(f"\nDone. Updated {total_updated} trades. Total with outcomes: {total}")
    conn.close()
    return {
        "groups_processed": len(groups),
        "rows_updated": total_updated,
        "rows_with_outcomes": total,
    }


if __name__ == "__main__":
    backfill_outcomes()
