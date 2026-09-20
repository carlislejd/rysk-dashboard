"""Verified, anonymous trader profile history."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from datetime import datetime, timezone, timedelta
import math
import re
import time

from analytics_services import SECONDS_PER_DAY, _add_row, _finish_aggregate, _new_aggregate
from chain_metadata import chain_fields
from participant_services import _safe_trade_row, public_trader_identity


def _where_clause(parts: List[str]) -> str:
    return "WHERE " + " AND ".join(parts) if parts else ""


def _identity_wallet(conn, trader_id: str, alias_secret: Optional[str]) -> str:
    if not alias_secret:
        raise ValueError("Trader profiles are unavailable until an alias secret is configured")
    if not isinstance(trader_id, str) or not re.fullmatch(r"[0-9a-f]{64}", trader_id):
        raise ValueError("Unknown trader")
    rows = conn.execute("""
        SELECT DISTINCT lower(w.wallet) AS wallet FROM trade_wallets w
        JOIN trades t ON t.chain_id=w.chain_id AND t.tx_hash=w.tx_hash
        WHERE w.status='verified_short_owner' AND w.wallet IS NOT NULL
    """).fetchall()
    matches = [
        row["wallet"] for row in rows
        if public_trader_identity(row["wallet"], alias_secret)["trader_id"] == trader_id.lower()
    ]
    if len(matches) != 1:
        raise ValueError("Unknown trader")
    return matches[0]


def _derived_apr(row: Dict[str, Any]) -> Optional[float]:
    """Use the same strike-notional-day APR basis as profile totals."""
    notional = row["notional_f"]
    expiry = row["expiry"]
    created_at = row["created_at"]
    if notional <= 0 or expiry is None:
        return None
    dte = (expiry - created_at) / SECONDS_PER_DAY
    if dte <= 0:
        return None
    value = row["premium_f"] / notional * 36500.0 / dte
    return value if math.isfinite(value) else None


def _timeline_bucket(timestamp: int, days: int) -> int:
    """Return a UTC bucket start without relying on SQLite's local timezone."""
    moment = datetime.fromtimestamp(int(timestamp), tz=timezone.utc)
    if days in (30, 90):
        return int(datetime(moment.year, moment.month, moment.day, tzinfo=timezone.utc).timestamp())
    if days == 365:
        monday = moment.replace(hour=0, minute=0, second=0, microsecond=0)
        return int((monday - timedelta(days=monday.weekday())).timestamp())
    return int(datetime(moment.year, moment.month, 1, tzinfo=timezone.utc).timestamp())


def _next_timeline_bucket(bucket: int, days: int) -> int:
    moment = datetime.fromtimestamp(bucket, tz=timezone.utc)
    if days in (30, 90):
        return bucket + SECONDS_PER_DAY
    if days == 365:
        return bucket + 7 * SECONDS_PER_DAY
    year, month = moment.year, moment.month
    return int(datetime(year + (month == 12), 1 if month == 12 else month + 1, 1, tzinfo=timezone.utc).timestamp())


def _full_window_visuals(rows: List[Dict[str, Any]], days: int) -> Dict[str, Any]:
    """Build public aggregates from the whole matching window, never a page."""
    by_bucket: Dict[int, Dict[str, float]] = {}
    assets: Dict[str, Dict[str, float]] = {}
    for row in rows:
        created_at = int(row["created_at"])
        bucket = _timeline_bucket(created_at, days)
        point = by_bucket.setdefault(bucket, {"notional": 0.0, "premium": 0.0, "trades": 0})
        point["notional"] += float(row["notional_f"] or 0)
        point["premium"] += float(row["premium_f"] or 0)
        point["trades"] += 1
        symbol = row["symbol"] or "Unknown"
        asset = assets.setdefault(symbol, {"notional": 0.0, "premium": 0.0, "trades": 0, "calls_notional": 0.0, "puts_notional": 0.0})
        asset["notional"] += float(row["notional_f"] or 0)
        asset["premium"] += float(row["premium_f"] or 0)
        asset["trades"] += 1
        asset["puts_notional" if row["is_put"] else "calls_notional"] += float(row["notional_f"] or 0)

    timeline = []
    if by_bucket:
        cursor, end = min(by_bucket), max(by_bucket)
        while cursor <= end:
            value = by_bucket.get(cursor, {"notional": 0.0, "premium": 0.0, "trades": 0})
            next_cursor = _next_timeline_bucket(cursor, days)
            timeline.append({"start": cursor, "end": next_cursor, **value})
            cursor = next_cursor
    return {
        "bucket": "day" if days in (30, 90) else "week" if days == 365 else "month",
        "timeline": timeline,
        "assets": [{"symbol": symbol, **value} for symbol, value in sorted(assets.items(), key=lambda item: item[1]["notional"], reverse=True)],
    }


def get_trader_history(
    conn,
    trader_id: str,
    alias_secret: Optional[str],
    days: int = 0,
    chain_id: Optional[int] = None,
    page: int = 1,
    limit: int = 50,
    symbol: Optional[str] = None,
    from_ts: Optional[int] = None,
    to_ts: Optional[int] = None,
) -> Dict[str, Any]:
    """Return public-safe history for a verified trader identity.

    The opaque ``trader_id`` is an HMAC routing token. Responses never contain
    a wallet address or transaction hash.
    """
    wallet = _identity_wallet(conn, trader_id, alias_secret)
    try:
        days = int(days or 0)
        page = max(1, int(page))
        limit = min(100, max(1, int(limit)))
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid pagination or window") from exc
    parts = ["lower(w.wallet)=?", "w.status='verified_short_owner'"]
    params: List[Any] = [wallet]
    if days > 0:
        parts.append("t.created_at >= ?")
        params.append(int(time.time()) - days * SECONDS_PER_DAY)
    if chain_id is not None:
        parts.append("t.chain_id=?")
        params.append(chain_id)
    base_parts, base_params = list(parts), list(params)
    if symbol:
        parts.append("upper(t.symbol)=?")
        params.append(str(symbol).upper())
    if from_ts is not None:
        parts.append("t.created_at >= ?")
        params.append(int(from_ts))
    if to_ts is not None:
        parts.append("t.created_at < ?")
        params.append(int(to_ts))
    where = _where_clause(parts)
    base_where = _where_clause(base_parts)
    base_sql = "FROM trades t JOIN trade_wallets w ON t.chain_id=w.chain_id AND t.tx_hash=w.tx_hash"
    total = conn.execute(f"SELECT COUNT(*) {base_sql} {where}", params).fetchone()[0]

    selected = [
        _safe_trade_row(dict(row))
        for row in conn.execute(
            f"""SELECT t.symbol,t.chain_id,t.created_at,t.expiry,t.is_buy,t.is_put,
                       t.quantity_f,t.strike_f,t.premium_f,t.notional_f,t.apr_f,
                       t.status,t.outcome,t.expiry_price_f,t.tx_hash
                {base_sql} {where}
                ORDER BY t.created_at DESC,t.tx_hash DESC LIMIT ? OFFSET ?""",
            params + [limit, (page - 1) * limit],
        ).fetchall()
    ]
    aggregate = _new_aggregate()
    for row in conn.execute(
        f"""SELECT t.created_at,t.expiry,t.notional_f,t.premium_f,t.apr_f,
                       t.is_put,t.outcome {base_sql} {where}""",
        params,
    ).fetchall():
        _add_row(aggregate, _safe_trade_row(dict(row)))
    finished = _finish_aggregate(aggregate)
    visual_rows = [dict(row) for row in conn.execute(
        f"SELECT t.created_at,t.symbol,t.notional_f,t.premium_f,t.is_put {base_sql} {base_where}", base_params
    ).fetchall()]
    trades = [
        {
            "symbol": row["symbol"],
            **chain_fields(row["chain_id"]),
            "created_at": row["created_at"],
            "expiry": row["expiry"],
            "side": "Buy" if row["is_buy"] else "Sell",
            "type": "Put" if row["is_put"] else "Call",
            "quantity": row["quantity_f"],
            "strike": row["strike_f"],
            "premium": row["premium_f"],
            "notional": row["notional_f"],
            "apr": _derived_apr(row),
            "status": row["status"],
            "outcome": row["outcome"],
            "expiry_price": row["expiry_price_f"],
        }
        for row in selected
    ]
    return {
        "identity": public_trader_identity(wallet, alias_secret),
        "totals": {
            "notional": finished["notional"],
            "premium": finished["premium"],
            "weighted_apr": finished["weighted_apr"],
            "trade_count": finished["trade_count"],
        },
        "trades": trades,
        "pagination": {"page": page, "limit": limit, "pages": max(1, -(-total // limit)), "total": total},
        "filters": {"days": days, "chain_id": chain_id, "symbol": symbol, "from_ts": from_ts, "to_ts": to_ts},
        "visuals": _full_window_visuals(visual_rows, days),
    }
