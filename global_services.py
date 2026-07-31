"""
Query functions for the global dashboard, reading from the local SQLite DB.

The global API does not expose trader wallet addresses — all address fields
are token contracts. This service layer focuses on protocol-level and
per-asset analytics.
"""

import time

import requests as _requests

from chain_metadata import chain_fields
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


def _where_clause(parts):
    return "WHERE " + " AND ".join(parts) if parts else ""


def _add_chain_filter(parts, params, chain_id):
    if chain_id is not None:
        parts.append("chain_id = ?")
        params.append(chain_id)


def _chain_breakdown(conn, where_parts=None, params=None):
    where = _where_clause(where_parts or [])
    rows = conn.execute(f"""
        SELECT chain_id,
               COUNT(*) as trade_count,
               COALESCE(SUM(notional_f), 0) as total_volume,
               COALESCE(SUM(premium_f), 0) as total_premium,
               COUNT(DISTINCT symbol) as asset_count
        FROM trades {where}
        GROUP BY chain_id
        ORDER BY total_volume DESC
    """, params or []).fetchall()
    return [
        {
            **chain_fields(r["chain_id"]),
            "trade_count": r["trade_count"],
            "total_volume": r["total_volume"],
            "total_premium": r["total_premium"],
            "asset_count": r["asset_count"],
        }
        for r in rows
    ]


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


def get_global_summary(conn, days=0, chain_id=None):
    """Protocol-level aggregate stats. days=0 means all time."""
    now = int(time.time())
    where_parts = []
    params = []
    if days > 0:
        cutoff = now - days * 86400
        where_parts.append("created_at >= ?")
        params.append(cutoff)
    _add_chain_filter(where_parts, params, chain_id)
    where = _where_clause(where_parts)

    row = conn.execute(f"""
        SELECT COUNT(*) as total_trades,
               SUM(notional_f) as total_volume,
               SUM(premium_f) as total_premium,
               AVG(apr_f) as avg_apr
        FROM trades {where}
    """, params).fetchone()

    day_ago = now - 86400
    week_ago = now - 604800

    day_parts = ["created_at >= ?"]
    day_params = [day_ago]
    _add_chain_filter(day_parts, day_params, chain_id)
    row_24h = conn.execute("""
        SELECT COUNT(*) as trades,
               COALESCE(SUM(notional_f), 0) as volume,
               COALESCE(SUM(premium_f), 0) as premium
        FROM trades {where}
    """.format(where=_where_clause(day_parts)), day_params).fetchone()

    week_parts = ["created_at >= ?"]
    week_params = [week_ago]
    _add_chain_filter(week_parts, week_params, chain_id)
    row_7d = conn.execute("""
        SELECT COUNT(*) as trades,
               COALESCE(SUM(notional_f), 0) as volume,
               COALESCE(SUM(premium_f), 0) as premium
        FROM trades {where}
    """.format(where=_where_clause(week_parts)), week_params).fetchone()

    asset_parts = ["symbol != ''"]
    asset_params = []
    _add_chain_filter(asset_parts, asset_params, chain_id)
    assets = [r[0] for r in conn.execute(
        f"SELECT DISTINCT symbol FROM trades {_where_clause(asset_parts)} ORDER BY symbol",
        asset_params,
    ).fetchall()]

    # Active vs expired premium split
    expired_parts = ["outcome IS NOT NULL"]
    expired_params = []
    if days > 0:
        expired_parts.append("created_at >= ?")
        expired_params.append(now - days * 86400)
    _add_chain_filter(expired_parts, expired_params, chain_id)
    expired_where = _where_clause(expired_parts)
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
        "chain_breakdown": _chain_breakdown(conn, where_parts, params),
        "filters": {"chain_id": chain_id, "days": days},
    }


def get_asset_summary(conn, chain_id=None):
    """Rich per-asset breakdown with time windows and put/call split."""
    now = int(time.time())
    day_ago = now - 86400
    week_ago = now - 604800
    chain_parts = ["symbol != ''"]
    chain_params = []
    _add_chain_filter(chain_parts, chain_params, chain_id)
    chain_where = _where_clause(chain_parts)

    # All-time stats per asset
    all_time = conn.execute(f"""
        SELECT symbol,
               chain_id,
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
        {chain_where}
        GROUP BY symbol, chain_id
        ORDER BY total_volume DESC
    """, chain_params).fetchall()

    # 24h stats per asset
    recent_24h = {}
    recent_parts = ["created_at >= ?", "symbol != ''"]
    recent_params = [day_ago]
    _add_chain_filter(recent_parts, recent_params, chain_id)
    for r in conn.execute(f"""
        SELECT symbol,
               chain_id,
               COUNT(*) as trades,
               COALESCE(SUM(notional_f), 0) as volume,
               COALESCE(SUM(premium_f), 0) as premium
        FROM trades {_where_clause(recent_parts)}
        GROUP BY symbol, chain_id
    """, recent_params).fetchall():
        recent_24h[(r["symbol"], r["chain_id"])] = {
            "trades": r["trades"],
            "volume": r["volume"],
            "premium": r["premium"],
        }

    # 7d stats per asset
    recent_7d = {}
    week_parts = ["created_at >= ?", "symbol != ''"]
    week_params = [week_ago]
    _add_chain_filter(week_parts, week_params, chain_id)
    for r in conn.execute(f"""
        SELECT symbol,
               chain_id,
               COUNT(*) as trades,
               COALESCE(SUM(notional_f), 0) as volume,
               COALESCE(SUM(premium_f), 0) as premium
        FROM trades {_where_clause(week_parts)}
        GROUP BY symbol, chain_id
    """, week_params).fetchall():
        recent_7d[(r["symbol"], r["chain_id"])] = {
            "trades": r["trades"],
            "volume": r["volume"],
            "premium": r["premium"],
        }

    # Outcome stats per asset
    outcomes_by_asset = {}
    outcome_parts = ["outcome IS NOT NULL", "symbol != ''"]
    outcome_params = []
    _add_chain_filter(outcome_parts, outcome_params, chain_id)
    for r in conn.execute(f"""
        SELECT symbol,
               chain_id,
               SUM(CASE WHEN outcome = 'Assigned' THEN 1 ELSE 0 END) as assigned,
               SUM(CASE WHEN outcome = 'Returned' THEN 1 ELSE 0 END) as returned,
               COUNT(*) as expired_total
        FROM trades
        {_where_clause(outcome_parts)}
        GROUP BY symbol, chain_id
    """, outcome_params).fetchall():
        outcomes_by_asset[(r["symbol"], r["chain_id"])] = {
            "assigned": r["assigned"],
            "returned": r["returned"],
            "expired_total": r["expired_total"],
        }

    assets = []
    for r in all_time:
        sym = r["symbol"]
        key = (sym, r["chain_id"])
        oc = outcomes_by_asset.get(key, {"assigned": 0, "returned": 0, "expired_total": 0})
        active_count = r["trade_count"] - oc["expired_total"]
        assets.append({
            "symbol": sym,
            **chain_fields(r["chain_id"]),
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
            "last_24h": recent_24h.get(key, {"trades": 0, "volume": 0, "premium": 0}),
            "last_7d": recent_7d.get(key, {"trades": 0, "volume": 0, "premium": 0}),
        })

    return {"assets": assets, "filters": {"chain_id": chain_id}}


def get_asset_detail(conn, symbol, expiry=None, chain_id=None):
    """Deep detail for a single asset, optionally filtered to a single expiry."""
    # Build conditional WHERE
    where = "WHERE symbol = ?"
    params = [symbol]
    if expiry:
        where += " AND expiry = ?"
        params.append(expiry)
    if chain_id is not None:
        where += " AND chain_id = ?"
        params.append(chain_id)

    # Strike distribution
    strikes = conn.execute(f"""
        SELECT strike_f,
               COUNT(*) as trade_count,
               SUM(notional_f) as volume,
               SUM(premium_f) as premium,
               AVG(apr_f) as avg_apr,
               SUM(CASE WHEN is_put = 1 THEN 1 ELSE 0 END) as put_count,
               SUM(CASE WHEN is_put = 0 THEN 1 ELSE 0 END) as call_count,
               SUM(CASE WHEN is_put = 1 THEN notional_f ELSE 0 END) as put_volume,
               SUM(CASE WHEN is_put = 0 THEN notional_f ELSE 0 END) as call_volume,
               SUM(CASE WHEN is_put = 1 THEN premium_f ELSE 0 END) as put_premium,
               SUM(CASE WHEN is_put = 0 THEN premium_f ELSE 0 END) as call_premium
        FROM trades
        {where}
        GROUP BY strike_f
        ORDER BY strike_f
    """, params).fetchall()

    # Expiry breakdown with outcome data (always unfiltered so we can show the full list)
    expiry_parts = ["symbol = ?"]
    expiry_params = [symbol]
    _add_chain_filter(expiry_parts, expiry_params, chain_id)
    expiries = conn.execute(f"""
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
        {_where_clause(expiry_parts)}
        GROUP BY expiry
        ORDER BY expiry DESC
    """, expiry_params).fetchall()

    return {
        "symbol": symbol,
        **chain_fields(chain_id),
        "strikes": [
            {
                "strike": r["strike_f"],
                "trade_count": r["trade_count"],
                "volume": r["volume"],
                "premium": r["premium"],
                "avg_apr": r["avg_apr"],
                "put_count": r["put_count"],
                "call_count": r["call_count"],
                "put_volume": r["put_volume"],
                "call_volume": r["call_volume"],
                "put_premium": r["put_premium"],
                "call_premium": r["call_premium"],
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


def get_expiry_overview(conn, chain_id=None):
    """List of all expiry dates with rich aggregate stats for the expiry section."""
    now = int(time.time())
    parts = ["expiry IS NOT NULL", "symbol != ''"]
    params = []
    _add_chain_filter(parts, params, chain_id)

    rows = conn.execute(f"""
        SELECT expiry,
               chain_id,
               COUNT(*) as total_orders,
               COUNT(DISTINCT symbol) as asset_count,
               SUM(notional_f) as total_notional,
               SUM(premium_f) as total_premium,
               AVG(apr_f) as avg_apr,
               SUM(CASE WHEN is_put = 1 THEN 1 ELSE 0 END) as put_count,
               SUM(CASE WHEN is_put = 0 THEN 1 ELSE 0 END) as call_count,
               SUM(CASE WHEN is_put = 1 THEN notional_f ELSE 0 END) as put_notional,
               SUM(CASE WHEN is_put = 0 THEN notional_f ELSE 0 END) as call_notional,
               SUM(CASE WHEN outcome = 'Assigned' THEN 1 ELSE 0 END) as assigned,
               SUM(CASE WHEN outcome = 'Returned' THEN 1 ELSE 0 END) as returned,
               AVG(expiry - created_at) as avg_dte_seconds,
               MAX(premium_f) as max_single_premium,
               MAX(notional_f) as max_single_notional
        FROM trades
        {_where_clause(parts)}
        GROUP BY expiry, chain_id
        ORDER BY expiry DESC
    """, params).fetchall()

    expiries = []
    for r in rows:
        expired = r["expiry"] < now
        total = r["total_orders"]
        assigned = r["assigned"] or 0
        returned = r["returned"] or 0
        outcome_total = assigned + returned
        premium_yield = (r["total_premium"] / r["total_notional"] * 100) if r["total_notional"] else 0
        avg_dte_days = (r["avg_dte_seconds"] or 0) / 86400

        # Most traded asset for this expiry
        top_parts = ["expiry = ?", "symbol != ''"]
        top_params = [r["expiry"]]
        _add_chain_filter(top_parts, top_params, r["chain_id"])
        top_asset = conn.execute(f"""
            SELECT symbol, COUNT(*) as cnt FROM trades
            {_where_clause(top_parts)}
            GROUP BY symbol ORDER BY cnt DESC LIMIT 1
        """, top_params).fetchone()

        # All assets for this expiry
        assets = [row[0] for row in conn.execute(f"""
            SELECT DISTINCT symbol FROM trades
            {_where_clause(top_parts)} ORDER BY symbol
        """, top_params).fetchall()]

        expiries.append({
            "expiry": r["expiry"],
            **chain_fields(r["chain_id"]),
            "expired": expired,
            "total_orders": total,
            "asset_count": r["asset_count"],
            "assets": assets,
            "top_asset": top_asset["symbol"] if top_asset else None,
            "total_notional": r["total_notional"],
            "total_premium": r["total_premium"],
            "premium_yield": round(premium_yield, 2),
            "avg_apr": r["avg_apr"],
            "avg_dte_days": round(avg_dte_days, 1),
            "put_count": r["put_count"],
            "call_count": r["call_count"],
            "put_notional": r["put_notional"],
            "call_notional": r["call_notional"],
            "assigned": assigned,
            "returned": returned,
            "return_rate": round(returned / outcome_total * 100, 1) if outcome_total else None,
            "max_single_premium": r["max_single_premium"],
            "max_single_notional": r["max_single_notional"],
        })

    return {"expiries": expiries, "filters": {"chain_id": chain_id}}


def get_global_trades(conn, page=1, limit=50, symbol=None, expiry=None, chain_id=None):
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
    _add_chain_filter(where_parts, params, chain_id)
    where = "WHERE " + " AND ".join(where_parts) if where_parts else ""

    count_row = conn.execute(
        f"SELECT COUNT(*) FROM trades {where}", params
    ).fetchone()
    total = count_row[0]

    rows = conn.execute(
        f"""SELECT tx_hash, symbol, chain_id, created_at, expiry,
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
            **chain_fields(r["chain_id"]),
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
        "filters": {"symbol": symbol, "expiry": expiry, "chain_id": chain_id},
    }


def get_global_volume(conn, interval="day", symbol=None, days=30, expiry=None, chain_id=None):
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
    _add_chain_filter(where_parts, params, chain_id)
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

    by_chain_rows = conn.execute(
        f"""SELECT {bucket} as bucket,
                   chain_id,
                   COUNT(*) as trade_count,
                   SUM(notional_f) as volume,
                   SUM(premium_f) as premium
            FROM trades {where}
            GROUP BY bucket, chain_id
            ORDER BY bucket, chain_id""",
        params,
    ).fetchall()

    return {
        "interval": interval,
        "days": days,
        "filters": {"symbol": symbol, "expiry": expiry, "chain_id": chain_id},
        "data": [
            {
                "date": r["bucket"],
                "trade_count": r["trade_count"],
                "volume": r["volume"],
                "premium": r["premium"],
            }
            for r in rows
        ],
        "by_chain": [
            {
                "date": r["bucket"],
                **chain_fields(r["chain_id"]),
                "trade_count": r["trade_count"],
                "volume": r["volume"],
                "premium": r["premium"],
            }
            for r in by_chain_rows
        ],
    }


def get_outcome_summary(conn, chain_id=None):
    """Aggregate outcome data: by asset, by expiry, and totals."""
    now = int(time.time())
    outcome_parts = ["outcome IS NOT NULL", "symbol != ''"]
    outcome_params = []
    _add_chain_filter(outcome_parts, outcome_params, chain_id)

    # By asset
    by_asset = conn.execute(f"""
        SELECT symbol,
               chain_id,
               COUNT(*) as total,
               SUM(CASE WHEN outcome = 'Assigned' THEN 1 ELSE 0 END) as assigned,
               SUM(CASE WHEN outcome = 'Returned' THEN 1 ELSE 0 END) as returned,
               SUM(CASE WHEN outcome = 'Unknown' THEN 1 ELSE 0 END) as unknown,
               SUM(premium_f) as total_premium,
               SUM(notional_f) as total_notional,
               SUM(CASE WHEN outcome = 'Assigned' THEN notional_f ELSE 0 END) as assigned_notional,
               SUM(CASE WHEN outcome = 'Returned' THEN premium_f ELSE 0 END) as returned_premium
        FROM trades
        {_where_clause(outcome_parts)}
        GROUP BY symbol, chain_id
        ORDER BY total_notional DESC
    """, outcome_params).fetchall()

    # By expiry (across all assets)
    by_expiry = conn.execute(f"""
        SELECT symbol, chain_id, expiry,
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
        {_where_clause(outcome_parts)}
        GROUP BY symbol, chain_id, expiry
        ORDER BY expiry DESC
    """, outcome_params).fetchall()

    # Totals
    total_parts = ["outcome IS NOT NULL"]
    total_params = []
    _add_chain_filter(total_parts, total_params, chain_id)
    totals_row = conn.execute(f"""
        SELECT COUNT(*) as total,
               SUM(CASE WHEN outcome = 'Assigned' THEN 1 ELSE 0 END) as assigned,
               SUM(CASE WHEN outcome = 'Returned' THEN 1 ELSE 0 END) as returned,
               SUM(CASE WHEN outcome = 'Unknown' THEN 1 ELSE 0 END) as unknown,
               SUM(premium_f) as total_premium,
               SUM(CASE WHEN outcome = 'Returned' THEN premium_f ELSE 0 END) as returned_premium
        FROM trades
        {_where_clause(total_parts)}
    """, total_params).fetchone()

    total = totals_row["total"] or 0
    assigned = totals_row["assigned"] or 0
    returned = totals_row["returned"] or 0

    return {
        "by_asset": [
            {
                "symbol": r["symbol"],
                **chain_fields(r["chain_id"]),
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
                **chain_fields(r["chain_id"]),
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
        "chain_breakdown": _chain_breakdown(conn, total_parts, total_params),
        "filters": {"chain_id": chain_id},
    }


def get_put_call_ratio_over_time(conn, days=90, symbol=None, chain_id=None):
    """Weekly put/call ratio trend — shows market sentiment over time."""
    cutoff = int(time.time()) - days * 86400
    where_parts = ["created_at >= ?"]
    params = [cutoff]
    if symbol:
        where_parts.append("symbol = ?")
        params.append(symbol)
    _add_chain_filter(where_parts, params, chain_id)
    where = "WHERE " + " AND ".join(where_parts)

    rows = conn.execute(f"""
        SELECT date(created_at, 'unixepoch', 'weekday 0', '-6 days') as week_start,
               SUM(CASE WHEN is_put = 1 THEN 1 ELSE 0 END) as put_count,
               SUM(CASE WHEN is_put = 0 THEN 1 ELSE 0 END) as call_count,
               SUM(CASE WHEN is_put = 1 THEN notional_f ELSE 0 END) as put_notional,
               SUM(CASE WHEN is_put = 0 THEN notional_f ELSE 0 END) as call_notional,
               COUNT(*) as total
        FROM trades {where}
        GROUP BY week_start
        ORDER BY week_start
    """, params).fetchall()

    data = []
    for r in rows:
        put_notional = r["put_notional"] or 0
        call_notional = r["call_notional"] or 0
        total_notional = put_notional + call_notional
        ratio = round(put_notional / call_notional, 2) if call_notional > 0 else None
        put_pct = round(put_notional / total_notional * 100, 1) if total_notional > 0 else 0
        data.append({
            "week": r["week_start"],
            "put_count": r["put_count"],
            "call_count": r["call_count"],
            "put_notional": put_notional,
            "call_notional": call_notional,
            "ratio": ratio,
            "put_pct": put_pct,
            "total": r["total"],
        })

    return {"days": days, "data": data, "filters": {"symbol": symbol, "chain_id": chain_id}}


def get_assignment_rate_trend(conn, chain_id=None):
    """Assignment rate per expiry date — shows how outcomes trend over time."""
    now = int(time.time())
    parts = ["outcome IS NOT NULL", "expiry < ?"]
    params = [now]
    _add_chain_filter(parts, params, chain_id)

    rows = conn.execute(f"""
        SELECT expiry,
               chain_id,
               COUNT(*) as total,
               SUM(CASE WHEN outcome = 'Assigned' THEN 1 ELSE 0 END) as assigned,
               SUM(CASE WHEN outcome = 'Returned' THEN 1 ELSE 0 END) as returned,
               SUM(notional_f) as total_notional,
               SUM(CASE WHEN outcome = 'Assigned' THEN notional_f ELSE 0 END) as assigned_notional
        FROM trades
        {_where_clause(parts)}
        GROUP BY expiry, chain_id
        ORDER BY expiry
    """, params).fetchall()

    data = []
    for r in rows:
        total = r["total"]
        assigned = r["assigned"] or 0
        returned = r["returned"] or 0
        outcome_total = assigned + returned
        data.append({
            "expiry": r["expiry"],
            **chain_fields(r["chain_id"]),
            "total": total,
            "assigned": assigned,
            "returned": returned,
            "assignment_rate": round(assigned / outcome_total * 100, 1) if outcome_total > 0 else None,
            "return_rate": round(returned / outcome_total * 100, 1) if outcome_total > 0 else None,
            "total_notional": r["total_notional"],
            "assigned_notional": r["assigned_notional"],
        })

    return {"data": data, "filters": {"chain_id": chain_id}}


def get_next_expiry_top_positions(conn, limit=5, chain_id=None):
    """Top positions by total notional for the next upcoming expiry, grouped by asset+strike."""
    now = int(time.time())
    next_parts = ["expiry > ?", "symbol != ''"]
    next_params = [now]
    _add_chain_filter(next_parts, next_params, chain_id)

    # Find the next expiry timestamp
    next_exp = conn.execute(f"""
        SELECT MIN(expiry) as next_expiry
        FROM trades
        {_where_clause(next_parts)}
    """, next_params).fetchone()

    if not next_exp or not next_exp["next_expiry"]:
        return {"next_expiry": None, "positions": [], "filters": {"chain_id": chain_id}}

    expiry_ts = next_exp["next_expiry"]
    exp_parts = ["expiry = ?", "symbol != ''"]
    exp_params = [expiry_ts]
    _add_chain_filter(exp_parts, exp_params, chain_id)

    totals = conn.execute(f"""
        SELECT COUNT(*) as total_orders,
               COUNT(DISTINCT symbol || '|' || strike_f || '|' || COALESCE(chain_id, '')) as total_strikes
        FROM trades
        {_where_clause(exp_parts)}
    """, exp_params).fetchone()

    rows = conn.execute(f"""
        SELECT symbol,
               chain_id,
               strike_f,
               COUNT(*) as order_count,
               SUM(quantity_f) as total_quantity,
               SUM(notional_f) as total_notional,
               SUM(premium_f) as total_premium,
               AVG(apr_f) as avg_apr,
               SUM(CASE WHEN is_put = 1 THEN 1 ELSE 0 END) as put_count,
               SUM(CASE WHEN is_put = 0 THEN 1 ELSE 0 END) as call_count
        FROM trades
        {_where_clause(exp_parts)}
        GROUP BY symbol, chain_id, strike_f
        ORDER BY total_notional DESC
        LIMIT ?
    """, exp_params + [limit]).fetchall()

    positions = []
    for r in rows:
        put_count = r["put_count"] or 0
        call_count = r["call_count"] or 0
        dominant_type = "Put" if put_count > call_count else "Call" if call_count > put_count else "Mixed"
        positions.append({
            "symbol": r["symbol"],
            **chain_fields(r["chain_id"]),
            "strike": r["strike_f"],
            "order_count": r["order_count"],
            "total_quantity": r["total_quantity"],
            "total_notional": r["total_notional"],
            "total_premium": r["total_premium"],
            "avg_apr": r["avg_apr"],
            "dominant_type": dominant_type,
            "put_count": put_count,
            "call_count": call_count,
        })

    return {
        "next_expiry": expiry_ts,
        "positions": positions,
        "total_orders": totals["total_orders"] if totals else 0,
        "total_strikes": totals["total_strikes"] if totals else 0,
        "filters": {"chain_id": chain_id},
    }


def get_market_pulse(conn, chain_id=None):
    """What's hot right now: top asset last 24h, popular strikes, avg DTE."""
    now = int(time.time())
    day_ago = now - 86400
    week_ago = now - 604800
    day_parts = ["created_at >= ?", "symbol != ''"]
    day_params = [day_ago]
    _add_chain_filter(day_parts, day_params, chain_id)
    week_parts = ["created_at >= ?", "symbol != ''"]
    week_params = [week_ago]
    _add_chain_filter(week_parts, week_params, chain_id)

    # Top asset by 24h volume
    top_24h = conn.execute(f"""
        SELECT symbol,
               chain_id,
               COUNT(*) as trades,
               SUM(notional_f) as volume,
               SUM(premium_f) as premium,
               AVG(apr_f) as avg_apr
        FROM trades
        {_where_clause(day_parts)}
        GROUP BY symbol, chain_id
        ORDER BY volume DESC
        LIMIT 1
    """, day_params).fetchone()

    # Most popular strike range last 7d
    popular_strikes = conn.execute(f"""
        SELECT symbol, chain_id, strike_f,
               COUNT(*) as cnt,
               SUM(notional_f) as volume,
               AVG(apr_f) as avg_apr,
               SUM(CASE WHEN is_put = 1 THEN 1 ELSE 0 END) as put_count,
               SUM(CASE WHEN is_put = 0 THEN 1 ELSE 0 END) as call_count
        FROM trades
        {_where_clause(week_parts)}
        GROUP BY symbol, chain_id, strike_f
        ORDER BY cnt DESC
        LIMIT 5
    """, week_params).fetchall()

    # Average DTE of trades placed in last 7d
    dte_parts = ["created_at >= ?", "expiry IS NOT NULL"]
    dte_params = [week_ago]
    _add_chain_filter(dte_parts, dte_params, chain_id)
    avg_dte = conn.execute(f"""
        SELECT AVG(expiry - created_at) / 86400.0 as avg_dte_days,
               MIN(expiry - created_at) / 86400.0 as min_dte_days,
               MAX(expiry - created_at) / 86400.0 as max_dte_days
        FROM trades
        {_where_clause(dte_parts)}
    """, dte_params).fetchone()

    # 24h vs 7d comparison
    stats_24h = conn.execute(f"""
        SELECT COUNT(*) as trades, COALESCE(SUM(notional_f), 0) as volume,
               COALESCE(SUM(premium_f), 0) as premium
        FROM trades {_where_clause(day_parts)}
    """, day_params).fetchone()

    stats_7d = conn.execute(f"""
        SELECT COUNT(*) as trades, COALESCE(SUM(notional_f), 0) as volume,
               COALESCE(SUM(premium_f), 0) as premium
        FROM trades {_where_clause(week_parts)}
    """, week_params).fetchone()

    daily_avg_volume = (stats_7d["volume"] / 7) if stats_7d["volume"] else 0
    volume_vs_avg = None
    if daily_avg_volume > 0:
        volume_vs_avg = round((stats_24h["volume"] / daily_avg_volume - 1) * 100, 1)

    # Active positions (not yet expired)
    active_parts = ["expiry > ?", "outcome IS NULL"]
    active_params = [now]
    _add_chain_filter(active_parts, active_params, chain_id)
    active = conn.execute(f"""
        SELECT COUNT(*) as cnt, COALESCE(SUM(notional_f), 0) as notional,
               COALESCE(SUM(premium_f), 0) as premium
        FROM trades {_where_clause(active_parts)}
    """, active_params).fetchone()

    return {
        "top_asset_24h": {
            "symbol": top_24h["symbol"] if top_24h else None,
            **chain_fields(top_24h["chain_id"] if top_24h else None),
            "trades": top_24h["trades"] if top_24h else 0,
            "volume": top_24h["volume"] if top_24h else 0,
            "premium": top_24h["premium"] if top_24h else 0,
            "avg_apr": top_24h["avg_apr"] if top_24h else None,
        } if top_24h else None,
        "popular_strikes": [
            {
                "symbol": r["symbol"],
                **chain_fields(r["chain_id"]),
                "strike": r["strike_f"],
                "count": r["cnt"],
                "volume": r["volume"],
                "avg_apr": r["avg_apr"],
                "put_count": r["put_count"],
                "call_count": r["call_count"],
                "dominant_type": (
                    "Put" if r["put_count"] and not r["call_count"]
                    else "Call" if r["call_count"] and not r["put_count"]
                    else "Mixed"
                ),
            }
            for r in popular_strikes
        ],
        "avg_dte": {
            "avg": round(avg_dte["avg_dte_days"], 1) if avg_dte and avg_dte["avg_dte_days"] else None,
            "min": round(avg_dte["min_dte_days"], 1) if avg_dte and avg_dte["min_dte_days"] else None,
            "max": round(avg_dte["max_dte_days"], 1) if avg_dte and avg_dte["max_dte_days"] else None,
        },
        "activity": {
            "trades_24h": stats_24h["trades"],
            "volume_24h": stats_24h["volume"],
            "premium_24h": stats_24h["premium"],
            "trades_7d": stats_7d["trades"],
            "volume_7d": stats_7d["volume"],
            "premium_7d": stats_7d["premium"],
            "volume_vs_daily_avg": volume_vs_avg,
        },
        "active_positions": {
            "count": active["cnt"],
            "notional": active["notional"],
            "premium": active["premium"],
        },
        "filters": {"chain_id": chain_id},
    }


def get_premium_over_time(conn, days=365, symbol=None, chain_id=None):
    """Cumulative premium collected over time for PnL charting."""
    cutoff = int(time.time()) - days * 86400
    where_parts = ["created_at >= ?"]
    params = [cutoff]
    if symbol:
        where_parts.append("symbol = ?")
        params.append(symbol)
    _add_chain_filter(where_parts, params, chain_id)
    where = "WHERE " + " AND ".join(where_parts)

    rows = conn.execute(f"""
        SELECT date(created_at, 'unixepoch') as day,
               SUM(premium_f) as daily_premium,
               SUM(notional_f) as daily_notional,
               COUNT(*) as trade_count,
               SUM(CASE WHEN outcome = 'Returned' THEN premium_f ELSE 0 END) as returned_premium,
               SUM(CASE WHEN outcome = 'Assigned' THEN premium_f ELSE 0 END) as assigned_premium
        FROM trades {where}
        GROUP BY day
        ORDER BY day
    """, params).fetchall()

    cumulative = 0
    cumulative_returned = 0
    data = []
    for r in rows:
        cumulative += r["daily_premium"]
        cumulative_returned += r["returned_premium"] or 0
        data.append({
            "date": r["day"],
            "daily_premium": r["daily_premium"],
            "daily_notional": r["daily_notional"],
            "trade_count": r["trade_count"],
            "cumulative_premium": cumulative,
            "cumulative_returned_premium": cumulative_returned,
        })

    return {"days": days, "data": data, "filters": {"symbol": symbol, "chain_id": chain_id}}
