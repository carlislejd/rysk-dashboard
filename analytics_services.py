"""Protocol research helpers for the analytics dashboard.

The analytics layer deliberately separates observed trade history from live
quotes.  In particular, the OTM/APR surface uses the prior daily close as its
entry reference, so it can be reproduced without implying that an RFQ is live.
"""

from __future__ import annotations

from bisect import bisect_left
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from statistics import median
import time
from typing import Any, Dict, List, Optional, Tuple

from volatility_services import get_asset_volatility


SECONDS_PER_DAY = 86400

OTM_BUCKETS: Tuple[Tuple[float, float, str], ...] = (
    (-1000.0, -10.0, "< -10%"),
    (-10.0, -5.0, "-10 to -5%"),
    (-5.0, -2.5, "-5 to -2.5%"),
    (-2.5, 0.0, "-2.5 to 0%"),
    (0.0, 2.5, "0 to 2.5%"),
    (2.5, 5.0, "2.5 to 5%"),
    (5.0, 7.5, "5 to 7.5%"),
    (7.5, 10.0, "7.5 to 10%"),
    (10.0, 15.0, "10 to 15%"),
    (15.0, 20.0, "15 to 20%"),
    (20.0, 30.0, "20 to 30%"),
    (30.0, 1000.0, "30%+"),
)

TENOR_BUCKETS: Tuple[Tuple[float, float, str], ...] = (
    (0.0, 7.0, "0–7d"),
    (7.0, 14.0, "8–14d"),
    (14.0, 30.0, "15–30d"),
    (30.0, 60.0, "31–60d"),
    (60.0, 10000.0, "60d+"),
)


def normalize_underlying(symbol: str) -> str:
    """Collapse Rysk wrapper symbols into their market underlyings."""
    raw = str(symbol or "").strip().upper()
    if not raw:
        return "UNKNOWN"

    direct = {
        "UBTC": "BTC",
        "UETH": "ETH",
        "USOL": "SOL",
        "WHYPE": "HYPE",
        "KHYPE": "HYPE",
        "LHYPE": "HYPE",
        "WSTHYPE": "HYPE",
        "UPUMP": "PUMP",
    }
    mapped = direct.get(raw, raw)
    for asset in ("HYPE", "BTC", "ETH", "SOL", "PUMP", "PURR", "XRP", "ZEC"):
        if asset in mapped or asset in raw:
            return asset
    return mapped or raw


def _where_clause(parts: List[str]) -> str:
    return "WHERE " + " AND ".join(parts) if parts else ""


def _date_bucket(timestamp: int, days: int) -> str:
    dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
    if days == 0 or days > 120:
        dt = dt - timedelta(days=dt.weekday())
    return dt.strftime("%Y-%m-%d")


def _tenor_bucket(days: Optional[float]) -> Optional[str]:
    if days is None or days < 0:
        return None
    for lower, upper, label in TENOR_BUCKETS:
        if lower <= days < upper:
            return label
    return None


def _new_aggregate() -> Dict[str, Any]:
    return {
        "trade_count": 0,
        "notional": 0.0,
        "premium": 0.0,
        "yield_apr_values": [],
        "annualizable_premium": 0.0,
        "quoted_apr_notional": 0.0,
        "quoted_apr_denominator": 0.0,
        "dte_notional": 0.0,
        "dte_denominator": 0.0,
        "assigned": 0,
        "returned": 0,
        "settled": 0,
        "put_count": 0,
        "call_count": 0,
        "put_notional": 0.0,
        "call_notional": 0.0,
    }


def _add_row(aggregate: Dict[str, Any], row: Dict[str, Any]) -> None:
    notional = float(row.get("notional_f") or 0)
    premium = float(row.get("premium_f") or 0)
    aggregate["trade_count"] += 1
    aggregate["notional"] += notional
    aggregate["premium"] += premium
    if row.get("is_put"):
        aggregate["put_count"] += 1
        aggregate["put_notional"] += notional
    else:
        aggregate["call_count"] += 1
        aggregate["call_notional"] += notional

    # Use the same strike-notional capital basis for both raw premium yield and
    # its annualized form. The APR supplied by the protocol can use a different
    # basis for covered calls, so mixing it with premium / strike notional makes
    # the two headline metrics look comparable when they are not.
    created_at = row.get("created_at")
    expiry = row.get("expiry")
    dte = None
    if created_at is not None and expiry is not None:
        dte = (float(expiry) - float(created_at)) / SECONDS_PER_DAY
    if dte is not None and dte > 0 and notional > 0:
        yield_apr = premium / notional * 100.0 * 365.0 / dte
        aggregate["yield_apr_values"].append(yield_apr)
        aggregate["annualizable_premium"] += premium
        aggregate["dte_notional"] += dte * notional
        aggregate["dte_denominator"] += notional

    quoted_apr = row.get("apr_f")
    if quoted_apr is not None:
        quoted_apr_value = float(quoted_apr)
        if notional > 0:
            aggregate["quoted_apr_notional"] += quoted_apr_value * notional
            aggregate["quoted_apr_denominator"] += notional
    outcome = row.get("outcome")
    if outcome in ("Assigned", "Returned"):
        aggregate["settled"] += 1
        aggregate[outcome.lower()] += 1


def _finish_aggregate(aggregate: Dict[str, Any]) -> Dict[str, Any]:
    notional = aggregate["notional"]
    settled = aggregate["settled"]
    yield_apr_values = aggregate["yield_apr_values"]
    return {
        "trade_count": aggregate["trade_count"],
        "notional": notional,
        "premium": aggregate["premium"],
        "premium_yield_pct": (aggregate["premium"] / notional * 100.0) if notional > 0 else None,
        "median_apr": median(yield_apr_values) if yield_apr_values else None,
        "weighted_apr": (
            aggregate["annualizable_premium"] * 36500.0 / aggregate["dte_notional"]
            if aggregate["dte_notional"] > 0 else None
        ),
        "quoted_weighted_apr": (
            aggregate["quoted_apr_notional"] / aggregate["quoted_apr_denominator"]
            if aggregate["quoted_apr_denominator"] > 0 else None
        ),
        "weighted_dte_days": (
            aggregate["dte_notional"] / aggregate["dte_denominator"]
            if aggregate["dte_denominator"] > 0 else None
        ),
        "assigned": aggregate["assigned"],
        "returned": aggregate["returned"],
        "settled": settled,
        "assignment_rate_pct": aggregate["assigned"] / settled * 100.0 if settled else None,
        "return_rate_pct": aggregate["returned"] / settled * 100.0 if settled else None,
        "put_count": aggregate["put_count"],
        "call_count": aggregate["call_count"],
        "put_notional": aggregate["put_notional"],
        "call_notional": aggregate["call_notional"],
    }


def get_analytics_overview(conn, days: int = 365, chain_id: Optional[int] = None) -> Dict[str, Any]:
    """Build reusable protocol-level datasets for the research dashboard."""
    parts = ["symbol != ''"]
    params: List[Any] = []
    if days > 0:
        parts.append("created_at >= ?")
        params.append(int(time.time()) - days * SECONDS_PER_DAY)
    if chain_id is not None:
        parts.append("chain_id = ?")
        params.append(chain_id)

    rows = conn.execute(
        f"""
        SELECT created_at, expiry, symbol, notional_f, premium_f, apr_f,
               is_put, outcome
        FROM trades
        {_where_clause(parts)}
        ORDER BY created_at
        """,
        params,
    ).fetchall()
    records = [dict(row) for row in rows]

    totals = _new_aggregate()
    by_asset: Dict[str, Dict[str, Any]] = defaultdict(_new_aggregate)
    by_option_type: Dict[str, Dict[str, Any]] = defaultdict(_new_aggregate)
    by_asset_option_type: Dict[Tuple[str, str], Dict[str, Any]] = defaultdict(_new_aggregate)
    by_date: Dict[str, Dict[str, Dict[str, float]]] = defaultdict(
        lambda: defaultdict(lambda: {"notional": 0.0, "premium": 0.0, "trade_count": 0})
    )
    tenor: Dict[Tuple[str, str], Dict[str, Any]] = defaultdict(_new_aggregate)

    for row in records:
        asset = normalize_underlying(row.get("symbol"))
        option_type = "put" if row.get("is_put") else "call"
        _add_row(totals, row)
        _add_row(by_asset[asset], row)
        _add_row(by_option_type[option_type], row)
        _add_row(by_asset_option_type[(asset, option_type)], row)

        bucket = _date_bucket(int(row["created_at"]), days)
        point = by_date[bucket][asset]
        point["notional"] += float(row.get("notional_f") or 0)
        point["premium"] += float(row.get("premium_f") or 0)
        point["trade_count"] += 1

        expiry = row.get("expiry")
        dte = ((float(expiry) - float(row["created_at"])) / SECONDS_PER_DAY) if expiry else None
        tenor_label = _tenor_bucket(dte)
        if tenor_label:
            _add_row(tenor[(asset, tenor_label)], row)

    finished_assets = []
    for asset, aggregate in by_asset.items():
        finished_assets.append({"asset": asset, **_finish_aggregate(aggregate)})
    finished_assets.sort(key=lambda item: item["notional"], reverse=True)

    finished_option_types = [
        {"option_type": option_type, **_finish_aggregate(by_option_type[option_type])}
        for option_type in ("call", "put")
        if option_type in by_option_type
    ]
    finished_asset_option_types = [
        {"asset": asset, "option_type": option_type, **_finish_aggregate(aggregate)}
        for (asset, option_type), aggregate in by_asset_option_type.items()
    ]
    finished_asset_option_types.sort(key=lambda item: item["notional"], reverse=True)

    # Keep the stream readable. Long-tail assets are still included in the
    # efficiency and strategy-yield datasets and filters.
    stream_assets = [item["asset"] for item in finished_assets[:7]]
    stream_points = []
    for date in sorted(by_date):
        values = {asset: 0.0 for asset in stream_assets}
        premium = 0.0
        trade_count = 0
        other = 0.0
        for asset, point in by_date[date].items():
            premium += point["premium"]
            trade_count += point["trade_count"]
            if asset in values:
                values[asset] += point["notional"]
            else:
                other += point["notional"]
        if other > 0:
            values["OTHER"] = other
        stream_points.append({
            "date": date,
            "assets": values,
            "premium": premium,
            "trade_count": trade_count,
            "total_notional": sum(values.values()),
        })
    if any("OTHER" in point["assets"] for point in stream_points):
        stream_assets.append("OTHER")

    tenor_surface = []
    tenor_order = {label: idx for idx, (_, _, label) in enumerate(TENOR_BUCKETS)}
    for (asset, label), aggregate in tenor.items():
        tenor_surface.append({
            "asset": asset,
            "tenor": label,
            "tenor_order": tenor_order[label],
            **_finish_aggregate(aggregate),
        })
    tenor_surface.sort(key=lambda item: (item["tenor_order"], -item["notional"]))

    return {
        "days": days,
        "filters": {"chain_id": chain_id},
        "totals": _finish_aggregate(totals),
        "assets": [item["asset"] for item in finished_assets],
        "by_asset": finished_assets,
        "by_option_type": finished_option_types,
        "by_asset_option_type": finished_asset_option_types,
        "stream_assets": stream_assets,
        "notional_series": stream_points,
        "tenor_buckets": [label for _, _, label in TENOR_BUCKETS],
        "tenor_surface": tenor_surface,
        "methodology": {
            "scope": "All observed covered-call and cash-secured-put executions, regardless of assignment outcome.",
            "notional": "Quantity multiplied by strike; used as a consistent capital proxy without inferring holder cost basis.",
            "premium_yield": "Total observed premium divided by total strike notional; not annualized.",
            "apr": "Total premium divided by total strike-notional-days, annualized on a 365-day basis.",
        },
    }


def _bucket_for_otm(otm_pct: float) -> Optional[Tuple[float, float, str]]:
    for lower, upper, label in OTM_BUCKETS:
        if lower <= otm_pct < upper:
            return lower, upper, label
    return None


def _downsample(rows: List[Dict[str, Any]], limit: int = 1800) -> List[Dict[str, Any]]:
    if len(rows) <= limit:
        return rows
    step = len(rows) / limit
    return [rows[min(int(index * step), len(rows) - 1)] for index in range(limit)]


def get_otm_apr_surface(
    conn,
    asset: str = "HYPE",
    days: int = 365,
    option_type: str = "call",
    dte_min: Optional[float] = None,
    dte_max: Optional[float] = None,
    chain_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Relate executed APR to strike distance using a prior-close reference."""
    underlying = normalize_underlying(asset)
    option_type = str(option_type or "call").strip().lower()
    if option_type not in ("call", "put", "all"):
        raise ValueError("option_type must be call, put, or all")

    parts = ["symbol != ''", "strike_f > 0", "notional_f > 0", "expiry > created_at"]
    params: List[Any] = []
    if days > 0:
        parts.append("created_at >= ?")
        params.append(int(time.time()) - days * SECONDS_PER_DAY)
    if option_type != "all":
        parts.append("is_put = ?")
        params.append(1 if option_type == "put" else 0)
    if chain_id is not None:
        parts.append("chain_id = ?")
        params.append(chain_id)

    raw_rows = conn.execute(
        f"""
        SELECT created_at, expiry, symbol, strike_f, notional_f, premium_f,
               apr_f, is_put, outcome
        FROM trades
        {_where_clause(parts)}
        ORDER BY created_at
        """,
        params,
    ).fetchall()
    rows = [dict(row) for row in raw_rows if normalize_underlying(row["symbol"]) == underlying]

    if rows:
        oldest = min(int(row["created_at"]) for row in rows)
        history_days = max(45, int((time.time() - oldest) / SECONDS_PER_DAY) + 10)
    else:
        history_days = max(days, 45) if days > 0 else 365
    volatility = get_asset_volatility(underlying, days=min(history_days, 1095))
    price_points = sorted(
        [point for point in volatility.get("series", []) if point.get("date") and point.get("close")],
        key=lambda point: point["date"],
    )
    price_dates = [point["date"] for point in price_points]

    buckets: Dict[str, Dict[str, Any]] = defaultdict(_new_aggregate)
    samples: List[Dict[str, Any]] = []
    skipped_for_price = 0
    skipped_for_tenor = 0

    for row in rows:
        dte = (float(row["expiry"]) - float(row["created_at"])) / SECONDS_PER_DAY
        if dte_min is not None and dte < dte_min:
            skipped_for_tenor += 1
            continue
        if dte_max is not None and dte > dte_max:
            skipped_for_tenor += 1
            continue

        entry_date = datetime.fromtimestamp(int(row["created_at"]), tz=timezone.utc).strftime("%Y-%m-%d")
        # Use the previous candle, never the same day's closing price. This
        # avoids introducing information that was not known when the RFQ traded.
        price_idx = bisect_left(price_dates, entry_date) - 1
        if price_idx < 0:
            skipped_for_price += 1
            continue
        spot = float(price_points[price_idx]["close"])
        strike = float(row["strike_f"])
        if spot <= 0:
            skipped_for_price += 1
            continue

        is_put = bool(row["is_put"])
        otm_pct = ((1.0 - strike / spot) if is_put else (strike / spot - 1.0)) * 100.0
        if otm_pct < -100 or otm_pct >= 100:
            continue
        bucket = _bucket_for_otm(otm_pct)
        if not bucket:
            continue
        lower, upper, label = bucket
        _add_row(buckets[label], row)
        samples.append({
            "date": entry_date,
            "symbol": row["symbol"],
            "option_type": "Put" if is_put else "Call",
            "strike": strike,
            "spot_reference": spot,
            "spot_reference_date": price_points[price_idx]["date"],
            "otm_pct": otm_pct,
            "apr": float(row["premium_f"] or 0) / float(row["notional_f"]) * 100.0 * 365.0 / dte,
            "premium_yield_pct": (
                float(row["premium_f"] or 0) / float(row["notional_f"] or 0) * 100.0
                if float(row["notional_f"] or 0) > 0 else None
            ),
            "notional": float(row["notional_f"] or 0),
            "dte": dte,
            "outcome": row.get("outcome"),
        })

    finished_buckets = []
    for lower, upper, label in OTM_BUCKETS:
        if label not in buckets:
            continue
        item = _finish_aggregate(buckets[label])
        bucket_samples = [sample for sample in samples if _bucket_for_otm(sample["otm_pct"])[2] == label]
        finished_buckets.append({
            "label": label,
            "lower": lower,
            "upper": upper,
            "midpoint": median([sample["otm_pct"] for sample in bucket_samples]),
            **item,
        })

    samples.sort(key=lambda sample: (sample["otm_pct"], sample["date"]))
    latest = volatility.get("latest") or {}
    eligible_trades = len(rows) - skipped_for_tenor
    priced_trades = max(eligible_trades - skipped_for_price, 0)
    return {
        "asset": underlying,
        "option_type": option_type,
        "days": days,
        "dte_min": dte_min,
        "dte_max": dte_max,
        "current_reference_price": latest.get("close"),
        "current_reference_date": latest.get("date"),
        "eligible_trades": eligible_trades,
        "priced_trades": priced_trades,
        "observed_trades": len(samples),
        "price_coverage_pct": (
            priced_trades / eligible_trades * 100.0
            if eligible_trades > 0 else 0.0
        ),
        "buckets": finished_buckets,
        "samples": _downsample(samples),
        "filters": {"chain_id": chain_id},
        "methodology": {
            "spot_reference": "Previous Hyperliquid daily close before the trade date.",
            "otm": "Calls: strike / reference - 1. Puts: 1 - strike / reference.",
            "apr": "Total premium divided by total strike-notional-days, annualized on a 365-day basis; assignment outcome is not a filter.",
            "warning": "Historical execution benchmark only. This is not a live RFQ or executable premium quote.",
        },
    }
