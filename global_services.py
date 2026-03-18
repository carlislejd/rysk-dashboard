"""
Query functions for the global dashboard, reading from the local SQLite DB.

The global API does not expose trader wallet addresses — all address fields
are token contracts. This service layer focuses on protocol-level and
per-asset analytics.
"""

import time

import requests as _requests

from iv_calc import implied_volatility
from positions_api import _symbol_to_market_asset

RISK_FREE_RATE = 0.045  # 4.5%
_HL_INFO_URL = "https://api.hyperliquid.xyz/info"

# Cache spot lookups: key (coin, minute_ts) -> (price, fetched_at)
_spot_cache = {}
_SPOT_CACHE_TTL = 300  # 5 minutes — recent trades don't change

# Cache the full enriched recent trades result
_recent_iv_cache = {"data": None, "timestamp": 0}
_RECENT_IV_TTL = 60  # 1 minute


def _prefetch_spots(trades):
    """Batch-fetch spot prices for all trades, one API call per unique coin."""
    # Group trades by coin, find time range per coin
    coin_ranges = {}  # coin -> (min_ts, max_ts)
    for t in trades:
        market = _symbol_to_market_asset(t.get("symbol", ""))
        created = t.get("created_at")
        if not market or not created:
            continue
        minute_key = (market, created // 60)
        cached = _spot_cache.get(minute_key)
        if cached and (time.time() - cached[1]) < _SPOT_CACHE_TTL:
            continue  # already cached
        if market not in coin_ranges:
            coin_ranges[market] = (created, created)
        else:
            lo, hi = coin_ranges[market]
            coin_ranges[market] = (min(lo, created), max(hi, created))

    # One API call per coin covering the full time range
    now_ts = time.time()
    for coin, (lo, hi) in coin_ranges.items():
        try:
            resp = _requests.post(_HL_INFO_URL, json={
                "type": "candleSnapshot",
                "req": {
                    "coin": coin, "interval": "1m",
                    "startTime": int(lo * 1000) - 60000,
                    "endTime": int(hi * 1000) + 60000,
                }
            }, timeout=10)
            candles = resp.json()
            # Index candles by minute
            for c in candles:
                minute = c["t"] // 60000
                _spot_cache[(coin, minute)] = (float(c["c"]), now_ts)
        except Exception:
            pass


def enrich_trades_with_iv(trades):
    """Add implied_volatility field to trades using spot price at time of trade."""
    # Return cached result if the same trades were recently enriched
    now_ts = time.time()
    trade_key = tuple(t.get("tx_hash") for t in trades)
    if (_recent_iv_cache["data"] is not None
            and now_ts - _recent_iv_cache["timestamp"] < _RECENT_IV_TTL
            and _recent_iv_cache.get("key") == trade_key):
        for t, cached in zip(trades, _recent_iv_cache["data"]):
            t["iv"] = cached.get("iv")
            t["spot_at_trade"] = cached.get("spot_at_trade")
        return trades

    # Batch-fetch all spot prices (one call per coin)
    _prefetch_spots(trades)

    for t in trades:
        market = _symbol_to_market_asset(t.get("symbol", ""))
        created = t.get("created_at")
        strike = t.get("strike")
        premium = t.get("premium")
        expiry = t.get("expiry")
        is_put = t.get("type") == "Put"
        quantity = t.get("quantity", 0)

        if not (market and created and strike and premium and expiry and quantity):
            t["iv"] = None
            continue

        T = (expiry - created) / (365.25 * 86400)
        if T <= 0:
            t["iv"] = None
            continue

        spot_entry = _spot_cache.get((market, created // 60))
        spot = spot_entry[0] if spot_entry else None

        if not spot:
            t["iv"] = None
            continue

        price_per_unit = premium / quantity if quantity > 0 else 0
        iv = implied_volatility(price_per_unit, spot, strike, T, RISK_FREE_RATE, is_put)
        t["iv"] = round(iv * 100, 1) if iv is not None else None
        t["spot_at_trade"] = spot

    # Cache the result
    _recent_iv_cache["data"] = [{"iv": t.get("iv"), "spot_at_trade": t.get("spot_at_trade")} for t in trades]
    _recent_iv_cache["timestamp"] = now_ts
    _recent_iv_cache["key"] = trade_key

    return trades


def get_global_summary(conn, days=0):
    """Protocol-level aggregate stats. days=0 means all time."""
    now = int(time.time())
    where = ""
    params = []
    if days > 0:
        cutoff = now - days * 86400
        where = "WHERE created_at >= ?"
        params = [cutoff]

    row = conn.execute(f"""
        SELECT COUNT(*) as total_trades,
               SUM(notional_f) as total_volume,
               SUM(premium_f) as total_premium,
               AVG(apr_f) as avg_apr
        FROM trades {where}
    """, params).fetchone()

    day_ago = now - 86400
    week_ago = now - 604800

    row_24h = conn.execute("""
        SELECT COUNT(*) as trades,
               COALESCE(SUM(notional_f), 0) as volume,
               COALESCE(SUM(premium_f), 0) as premium
        FROM trades WHERE created_at >= ?
    """, (day_ago,)).fetchone()

    row_7d = conn.execute("""
        SELECT COUNT(*) as trades,
               COALESCE(SUM(notional_f), 0) as volume,
               COALESCE(SUM(premium_f), 0) as premium
        FROM trades WHERE created_at >= ?
    """, (week_ago,)).fetchone()

    assets = [r[0] for r in conn.execute(
        "SELECT DISTINCT symbol FROM trades WHERE symbol != '' ORDER BY symbol"
    ).fetchall()]

    # Active vs expired premium split
    expired_where = "WHERE outcome IS NOT NULL" + (" AND created_at >= ?" if days > 0 else "")
    expired_params = params if days > 0 else []
    expired_prem = conn.execute(f"""
        SELECT COALESCE(SUM(premium_f), 0) FROM trades {expired_where}
    """, expired_params).fetchone()[0]
    total_prem = row["total_premium"] or 0
    active_prem = total_prem - expired_prem

    return {
        "total_trades": row["total_trades"],
        "total_volume": row["total_volume"] or 0,
        "total_premium": total_prem,
        "expired_premium": expired_prem,
        "active_premium": active_prem,
        "avg_apr": row["avg_apr"],
        "assets": assets,
        "last_24h": {
            "trades": row_24h["trades"],
            "volume": row_24h["volume"],
            "premium": row_24h["premium"],
        },
        "last_7d": {
            "trades": row_7d["trades"],
            "volume": row_7d["volume"],
            "premium": row_7d["premium"],
        },
    }


def get_asset_summary(conn):
    """Rich per-asset breakdown with time windows and put/call split."""
    now = int(time.time())
    day_ago = now - 86400
    week_ago = now - 604800

    # All-time stats per asset
    all_time = conn.execute("""
        SELECT symbol,
               COUNT(*) as trade_count,
               SUM(notional_f) as total_volume,
               SUM(premium_f) as total_premium,
               AVG(apr_f) as avg_apr,
               MIN(created_at) as first_trade,
               MAX(created_at) as last_trade,
               SUM(CASE WHEN is_put = 1 THEN 1 ELSE 0 END) as put_count,
               SUM(CASE WHEN is_put = 0 THEN 1 ELSE 0 END) as call_count,
               SUM(CASE WHEN is_put = 1 THEN notional_f ELSE 0 END) as put_volume,
               SUM(CASE WHEN is_put = 0 THEN notional_f ELSE 0 END) as call_volume,
               SUM(CASE WHEN is_put = 1 THEN premium_f ELSE 0 END) as put_premium,
               SUM(CASE WHEN is_put = 0 THEN premium_f ELSE 0 END) as call_premium,
               AVG(quantity_f) as avg_quantity,
               AVG(strike_f) as avg_strike
        FROM trades
        WHERE symbol != ''
        GROUP BY symbol
        ORDER BY total_volume DESC
    """).fetchall()

    # 24h stats per asset
    recent_24h = {}
    for r in conn.execute("""
        SELECT symbol,
               COUNT(*) as trades,
               COALESCE(SUM(notional_f), 0) as volume,
               COALESCE(SUM(premium_f), 0) as premium
        FROM trades WHERE created_at >= ? AND symbol != ''
        GROUP BY symbol
    """, (day_ago,)).fetchall():
        recent_24h[r["symbol"]] = {
            "trades": r["trades"],
            "volume": r["volume"],
            "premium": r["premium"],
        }

    # 7d stats per asset
    recent_7d = {}
    for r in conn.execute("""
        SELECT symbol,
               COUNT(*) as trades,
               COALESCE(SUM(notional_f), 0) as volume,
               COALESCE(SUM(premium_f), 0) as premium
        FROM trades WHERE created_at >= ? AND symbol != ''
        GROUP BY symbol
    """, (week_ago,)).fetchall():
        recent_7d[r["symbol"]] = {
            "trades": r["trades"],
            "volume": r["volume"],
            "premium": r["premium"],
        }

    # Outcome stats per asset
    outcomes_by_asset = {}
    for r in conn.execute("""
        SELECT symbol,
               SUM(CASE WHEN outcome = 'Assigned' THEN 1 ELSE 0 END) as assigned,
               SUM(CASE WHEN outcome = 'Returned' THEN 1 ELSE 0 END) as returned,
               COUNT(*) as expired_total
        FROM trades
        WHERE outcome IS NOT NULL AND symbol != ''
        GROUP BY symbol
    """).fetchall():
        outcomes_by_asset[r["symbol"]] = {
            "assigned": r["assigned"],
            "returned": r["returned"],
            "expired_total": r["expired_total"],
        }

    assets = []
    for r in all_time:
        sym = r["symbol"]
        oc = outcomes_by_asset.get(sym, {"assigned": 0, "returned": 0, "expired_total": 0})
        active_count = r["trade_count"] - oc["expired_total"]
        assets.append({
            "symbol": sym,
            "trade_count": r["trade_count"],
            "total_volume": r["total_volume"],
            "total_premium": r["total_premium"],
            "avg_apr": r["avg_apr"],
            "first_trade": r["first_trade"],
            "last_trade": r["last_trade"],
            "put_count": r["put_count"],
            "call_count": r["call_count"],
            "put_volume": r["put_volume"],
            "call_volume": r["call_volume"],
            "put_premium": r["put_premium"],
            "call_premium": r["call_premium"],
            "avg_quantity": r["avg_quantity"],
            "avg_strike": r["avg_strike"],
            "active_count": active_count,
            "expired_count": oc["expired_total"],
            "assigned": oc["assigned"],
            "returned": oc["returned"],
            "last_24h": recent_24h.get(sym, {"trades": 0, "volume": 0, "premium": 0}),
            "last_7d": recent_7d.get(sym, {"trades": 0, "volume": 0, "premium": 0}),
        })

    return {"assets": assets}


def get_asset_detail(conn, symbol, expiry=None):
    """Deep detail for a single asset, optionally filtered to a single expiry."""
    # Build conditional WHERE
    where = "WHERE symbol = ?"
    params = [symbol]
    if expiry:
        where += " AND expiry = ?"
        params.append(expiry)

    # Strike distribution
    strikes = conn.execute(f"""
        SELECT strike_f,
               COUNT(*) as trade_count,
               SUM(notional_f) as volume,
               SUM(premium_f) as premium,
               AVG(apr_f) as avg_apr,
               SUM(CASE WHEN is_put = 1 THEN notional_f ELSE 0 END) as put_volume,
               SUM(CASE WHEN is_put = 0 THEN notional_f ELSE 0 END) as call_volume
        FROM trades
        {where}
        GROUP BY strike_f
        ORDER BY strike_f
    """, params).fetchall()

    # Expiry breakdown with outcome data (always unfiltered so we can show the full list)
    expiries = conn.execute("""
        SELECT expiry,
               COUNT(*) as trade_count,
               SUM(notional_f) as volume,
               SUM(premium_f) as premium,
               AVG(apr_f) as avg_apr,
               SUM(CASE WHEN is_put = 1 THEN 1 ELSE 0 END) as put_count,
               SUM(CASE WHEN is_put = 0 THEN 1 ELSE 0 END) as call_count,
               SUM(CASE WHEN outcome = 'Assigned' THEN 1 ELSE 0 END) as assigned,
               SUM(CASE WHEN outcome = 'Returned' THEN 1 ELSE 0 END) as returned,
               SUM(CASE WHEN outcome = 'Unknown' THEN 1 ELSE 0 END) as unknown,
               SUM(CASE WHEN outcome = 'Assigned' THEN notional_f ELSE 0 END) as assigned_notional,
               SUM(CASE WHEN outcome = 'Returned' THEN premium_f ELSE 0 END) as returned_premium,
               MAX(expiry_price_f) as expiry_price
        FROM trades
        WHERE symbol = ?
        GROUP BY expiry
        ORDER BY expiry DESC
    """, (symbol,)).fetchall()

    return {
        "symbol": symbol,
        "strikes": [
            {
                "strike": r["strike_f"],
                "trade_count": r["trade_count"],
                "volume": r["volume"],
                "premium": r["premium"],
                "avg_apr": r["avg_apr"],
                "put_volume": r["put_volume"],
                "call_volume": r["call_volume"],
            }
            for r in strikes
        ],
        "expiries": [
            {
                "expiry": r["expiry"],
                "trade_count": r["trade_count"],
                "volume": r["volume"],
                "premium": r["premium"],
                "avg_apr": r["avg_apr"],
                "put_count": r["put_count"],
                "call_count": r["call_count"],
                "assigned": r["assigned"],
                "returned": r["returned"],
                "unknown": r["unknown"],
                "assigned_notional": r["assigned_notional"],
                "returned_premium": r["returned_premium"],
                "expiry_price": r["expiry_price"],
            }
            for r in expiries
        ],
    }


def get_global_trades(conn, page=1, limit=50, symbol=None, expiry=None):
    """Paginated recent trades feed, optionally filtered by asset and/or expiry."""
    offset = (page - 1) * limit
    where_parts = []
    params = []
    if symbol:
        where_parts.append("symbol = ?")
        params.append(symbol)
    if expiry:
        where_parts.append("expiry = ?")
        params.append(expiry)
    where = "WHERE " + " AND ".join(where_parts) if where_parts else ""

    count_row = conn.execute(
        f"SELECT COUNT(*) FROM trades {where}", params
    ).fetchone()
    total = count_row[0]

    rows = conn.execute(
        f"""SELECT tx_hash, symbol, created_at, expiry,
                   is_buy, is_put, quantity_f, strike_f, premium_f,
                   notional_f, apr_f, status, outcome, expiry_price_f
            FROM trades {where}
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?""",
        params + [limit, offset],
    ).fetchall()

    trades = []
    for r in rows:
        trades.append({
            "tx_hash": r["tx_hash"],
            "symbol": r["symbol"],
            "created_at": r["created_at"],
            "expiry": r["expiry"],
            "side": "Buy" if r["is_buy"] else "Sell",
            "type": "Put" if r["is_put"] else "Call",
            "quantity": r["quantity_f"],
            "strike": r["strike_f"],
            "premium": r["premium_f"],
            "notional": r["notional_f"],
            "apr": r["apr_f"],
            "status": r["status"],
            "outcome": r["outcome"],
            "expiry_price": r["expiry_price_f"],
        })

    return {
        "trades": trades,
        "total": total,
        "page": page,
        "limit": limit,
        "pages": max(1, -(-total // limit)),
    }


def get_global_volume(conn, interval="day", symbol=None, days=30, expiry=None):
    """Time-bucketed volume/premium/count for charts."""
    cutoff = int(time.time()) - days * 86400
    where_parts = ["created_at >= ?"]
    params = [cutoff]
    if symbol:
        where_parts.append("symbol = ?")
        params.append(symbol)
    if expiry:
        where_parts.append("expiry = ?")
        params.append(expiry)
    where = "WHERE " + " AND ".join(where_parts)

    if interval == "hour":
        bucket = "strftime('%Y-%m-%d %H:00', created_at, 'unixepoch')"
    else:
        bucket = "date(created_at, 'unixepoch')"

    rows = conn.execute(
        f"""SELECT {bucket} as bucket,
                   COUNT(*) as trade_count,
                   SUM(notional_f) as volume,
                   SUM(premium_f) as premium
            FROM trades {where}
            GROUP BY bucket
            ORDER BY bucket""",
        params,
    ).fetchall()

    return {
        "interval": interval,
        "days": days,
        "data": [
            {
                "date": r["bucket"],
                "trade_count": r["trade_count"],
                "volume": r["volume"],
                "premium": r["premium"],
            }
            for r in rows
        ],
    }


def get_outcome_summary(conn):
    """Aggregate outcome data: by asset, by expiry, and totals."""
    now = int(time.time())

    # By asset
    by_asset = conn.execute("""
        SELECT symbol,
               COUNT(*) as total,
               SUM(CASE WHEN outcome = 'Assigned' THEN 1 ELSE 0 END) as assigned,
               SUM(CASE WHEN outcome = 'Returned' THEN 1 ELSE 0 END) as returned,
               SUM(CASE WHEN outcome = 'Unknown' THEN 1 ELSE 0 END) as unknown,
               SUM(premium_f) as total_premium,
               SUM(notional_f) as total_notional,
               SUM(CASE WHEN outcome = 'Assigned' THEN notional_f ELSE 0 END) as assigned_notional,
               SUM(CASE WHEN outcome = 'Returned' THEN premium_f ELSE 0 END) as returned_premium
        FROM trades
        WHERE outcome IS NOT NULL AND symbol != ''
        GROUP BY symbol
        ORDER BY total_notional DESC
    """).fetchall()

    # By expiry (across all assets)
    by_expiry = conn.execute("""
        SELECT symbol, expiry,
               COUNT(*) as total,
               SUM(CASE WHEN outcome = 'Assigned' THEN 1 ELSE 0 END) as assigned,
               SUM(CASE WHEN outcome = 'Returned' THEN 1 ELSE 0 END) as returned,
               SUM(CASE WHEN outcome = 'Unknown' THEN 1 ELSE 0 END) as unknown,
               SUM(notional_f) as total_notional,
               SUM(premium_f) as total_premium,
               SUM(CASE WHEN outcome = 'Assigned' THEN notional_f ELSE 0 END) as assigned_notional,
               SUM(CASE WHEN outcome = 'Returned' THEN premium_f ELSE 0 END) as returned_premium,
               MAX(expiry_price_f) as expiry_price
        FROM trades
        WHERE outcome IS NOT NULL AND symbol != ''
        GROUP BY symbol, expiry
        ORDER BY expiry DESC
    """).fetchall()

    # Totals
    totals_row = conn.execute("""
        SELECT COUNT(*) as total,
               SUM(CASE WHEN outcome = 'Assigned' THEN 1 ELSE 0 END) as assigned,
               SUM(CASE WHEN outcome = 'Returned' THEN 1 ELSE 0 END) as returned,
               SUM(CASE WHEN outcome = 'Unknown' THEN 1 ELSE 0 END) as unknown,
               SUM(premium_f) as total_premium,
               SUM(CASE WHEN outcome = 'Returned' THEN premium_f ELSE 0 END) as returned_premium
        FROM trades
        WHERE outcome IS NOT NULL
    """).fetchone()

    total = totals_row["total"] or 0
    assigned = totals_row["assigned"] or 0
    returned = totals_row["returned"] or 0

    return {
        "by_asset": [
            {
                "symbol": r["symbol"],
                "total": r["total"],
                "assigned": r["assigned"],
                "returned": r["returned"],
                "unknown": r["unknown"],
                "assigned_pct": round(r["assigned"] / r["total"] * 100, 1) if r["total"] else 0,
                "total_premium": r["total_premium"],
                "total_notional": r["total_notional"],
                "assigned_notional": r["assigned_notional"],
                "returned_premium": r["returned_premium"],
            }
            for r in by_asset
        ],
        "by_expiry": [
            {
                "symbol": r["symbol"],
                "expiry": r["expiry"],
                "total": r["total"],
                "assigned": r["assigned"],
                "returned": r["returned"],
                "unknown": r["unknown"],
                "total_notional": r["total_notional"],
                "total_premium": r["total_premium"],
                "assigned_notional": r["assigned_notional"],
                "returned_premium": r["returned_premium"],
                "expiry_price": r["expiry_price"],
            }
            for r in by_expiry
        ],
        "totals": {
            "total": total,
            "assigned": assigned,
            "returned": returned,
            "unknown": totals_row["unknown"] or 0,
            "assigned_pct": round(assigned / total * 100, 1) if total else 0,
            "returned_pct": round(returned / total * 100, 1) if total else 0,
            "total_premium": totals_row["total_premium"] or 0,
            "returned_premium": totals_row["returned_premium"] or 0,
        },
    }
