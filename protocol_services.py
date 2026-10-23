"""Recorded protocol usage, with comparable windows and explicit data coverage."""

import sqlite3
import time

from chain_metadata import chain_fields
from observability import collection_status


FRESHNESS_SECONDS = 36 * 60 * 60


def _percent(part, total):
    return part / total * 100.0 if total > 0 else None


def _metric(current, previous):
    return {
        "value": current,
        "previous": previous,
        "change_pct": ((current - previous) / previous * 100.0) if previous > 0 else None,
    }


def _totals(conn, where, params):
    return conn.execute(f"""
        SELECT COUNT(*) AS trades,
               COALESCE(SUM(notional_f), 0) AS notional,
               COALESCE(SUM(premium_f), 0) AS premium,
               COALESCE(SUM(CASE WHEN is_put = 0 THEN notional_f ELSE 0 END), 0) AS call_notional,
               COALESCE(SUM(CASE WHEN is_put = 1 THEN notional_f ELSE 0 END), 0) AS put_notional
        FROM trades WHERE {where}
    """, params).fetchone()


def get_protocol_overview(conn, days=30, chain_id=None, now=None):
    """Summarize observed executions, not TVL, profit, or complete protocol activity.

    Both entry windows are half-open and equal in duration. Settlement coverage
    refers to expired executions entered in the selected window. A recent sync
    cursor establishes freshness even during quiet trading. Collector freshness
    uses the same threshold and failure signal as the operational status API;
    without a cursor, the last trade is a conservative 36-hour fallback.
    """
    if days not in (7, 30, 90):
        raise ValueError("days must be 7, 30, or 90")
    now = int(time.time() if now is None else now)
    start = now - days * 86400
    previous_start = start - days * 86400
    base = "symbol != ''"
    chain_params = []
    if chain_id is not None:
        base += " AND chain_id = ?"
        chain_params.append(chain_id)
    window_where = base + " AND created_at >= ? AND created_at < ?"
    current_params = [*chain_params, start, now]
    current = _totals(conn, window_where, current_params)
    previous = _totals(conn, window_where, [*chain_params, previous_start, start])
    current_yield = _percent(current["premium"], current["notional"])
    previous_yield = _percent(previous["premium"], previous["notional"])

    asset_rows = conn.execute(f"""
        SELECT symbol, chain_id, COUNT(*) AS trades,
               COALESCE(SUM(notional_f), 0) AS notional,
               COALESCE(SUM(premium_f), 0) AS premium
        FROM trades WHERE {window_where}
        GROUP BY symbol, chain_id ORDER BY notional DESC, symbol, chain_id
        LIMIT 8
    """, current_params).fetchall()
    chain_rows = conn.execute(f"""
        SELECT chain_id, COUNT(*) AS trades,
               COALESCE(SUM(notional_f), 0) AS notional,
               COALESCE(SUM(premium_f), 0) AS premium
        FROM trades WHERE {window_where}
        GROUP BY chain_id ORDER BY notional DESC, chain_id
    """, current_params).fetchall()
    outcomes = conn.execute(f"""
        SELECT COUNT(*) AS expired_count,
               COALESCE(SUM(CASE WHEN outcome = 'Assigned' THEN 1 ELSE 0 END), 0) AS assigned_count,
               COALESCE(SUM(CASE WHEN outcome = 'Returned' THEN 1 ELSE 0 END), 0) AS returned_count
        FROM trades WHERE {window_where} AND expiry <= ?
    """, [*current_params, now]).fetchone()
    assigned = outcomes["assigned_count"]
    returned = outcomes["returned_count"]
    settled = assigned + returned
    expired = outcomes["expired_count"]
    observed = conn.execute(f"""
        SELECT MIN(created_at) AS first_trade_at, MAX(created_at) AS last_trade_at
        FROM trades WHERE {base} AND created_at < ?
    """, [*chain_params, now]).fetchone()
    last_sync = None
    latest_sync_succeeded = None
    stale_after = FRESHNESS_SECONDS
    try:
        collection = collection_status(conn, now=now)["history"]
        last_sync = collection["synced_through"]
        latest_sync_succeeded = collection["latest_sync_succeeded"]
        if last_sync is not None:
            stale_after = collection["stale_after_seconds"]
    except (sqlite3.OperationalError, TypeError, ValueError):
        # Read-only fixtures and earlier database versions can lack sync metadata.
        pass
    last_trade = observed["last_trade_at"]
    freshness_at = last_sync if last_sync is not None else last_trade
    age = max(0, now - freshness_at) if freshness_at is not None else None
    stale = age is None or age > stale_after or latest_sync_succeeded is False
    prior_history = observed["first_trade_at"] is not None and observed["first_trade_at"] <= previous_start
    comparison_available = not stale and prior_history
    metrics = {
        "notional": _metric(current["notional"], previous["notional"]),
        "premium": _metric(current["premium"], previous["premium"]),
        "trades": _metric(current["trades"], previous["trades"]),
        "premium_yield_pct": {
            "value": current_yield, "previous": previous_yield,
            "change_pp": current_yield - previous_yield
            if current_yield is not None and previous_yield is not None else None,
        },
    }
    # A stale snapshot or an incomplete prior window cannot support a claim
    # that actual protocol usage grew or fell by the stored-data difference.
    if not comparison_available:
        for key in ("notional", "premium", "trades"):
            metrics[key]["change_pct"] = None
        metrics["premium_yield_pct"]["change_pp"] = None

    def breakdown(row):
        return {
            **chain_fields(row["chain_id"]),
            "trades": row["trades"],
            "notional": row["notional"],
            "premium": row["premium"],
            "share_pct": _percent(row["notional"], current["notional"]),
        }

    return {
        "window": {"days": days, "start_at": start, "end_at": now,
                   "previous_start_at": previous_start, "previous_end_at": start,
                   "comparison_available": comparison_available,
                   "comparison_reason": "stale_data" if stale else
                   ("limited_prior_history" if not prior_history else None)},
        "metrics": metrics,
        "strategy_mix": {
            "call_notional": current["call_notional"],
            "put_notional": current["put_notional"],
            "call_share_pct": _percent(current["call_notional"], current["notional"]),
            "put_share_pct": _percent(current["put_notional"], current["notional"]),
        },
        "top_assets": [{"symbol": row["symbol"], **breakdown(row)} for row in asset_rows],
        "chain_mix": [breakdown(row) for row in chain_rows],
        "observation": {
            "as_of": now, "first_trade_at": observed["first_trade_at"],
            "last_trade_at": last_trade, "last_sync_at": last_sync,
            "age_seconds": age, "is_stale": stale,
            "stale_after_seconds": stale_after,
            "latest_sync_succeeded": latest_sync_succeeded,
            "freshness_basis": "last_sync" if last_sync is not None else "last_trade",
            "status": "empty" if last_trade is None else ("stale" if stale else "fresh"),
            "current_window_has_trades": current["trades"] > 0,
        },
        "outcomes": {
            "expired_count": expired, "settled_count": settled,
            "pending_count": expired - settled,
            "assigned_count": assigned, "returned_count": returned,
            "coverage_pct": _percent(settled, expired),
            "assigned_pct": _percent(assigned, settled),
            "returned_pct": _percent(returned, settled),
            "basis": "Expired trades entered within the selected window; percentages use known outcomes.",
        },
        "filters": {"chain_id": chain_id, "days": days},
        "definitions": {
            "notional": "Recorded quantity multiplied by strike price; turnover, not TVL or unique capital.",
            "premium": "Recorded gross option premiums, before fees and settlement costs; not profit.",
            "premium_yield_pct": "Gross premium divided by strike notional; not annualized.",
            "comparison": "The immediately preceding equal-length entry window, based on stored history.",
        },
    }
