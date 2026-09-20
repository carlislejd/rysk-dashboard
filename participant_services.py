"""Anonymous, public-safe participant analytics.

The database retains exact wallet attribution for audit and calculation, but
this module deliberately never returns a wallet address or participant total.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import hmac
import json
import math
import time
from typing import Any, Dict, List, Optional

from analytics_services import SECONDS_PER_DAY, _add_row, _finish_aggregate, _new_aggregate


MIN_SEGMENT_POPULATION = 20
MIN_CONCENTRATION_POPULATION = 100

APR_SEGMENTS = (
    ("under_10", "Under 10%", None, 10.0),
    ("10_to_25", "10–25%", 10.0, 25.0),
    ("25_to_50", "25–50%", 25.0, 50.0),
    ("50_to_100", "50–100%", 50.0, 100.0),
    ("100_plus", "100%+", 100.0, None),
    ("unclassified", "Unclassified APR", None, None),
)


def _alias(wallet: str, secret: str) -> str:
    return public_trader_identity(wallet, secret)["alias"]


def public_trader_identity(wallet: str, secret: str) -> Dict[str, str]:
    """Return a stable opaque identity without exposing the wallet itself."""
    if not secret:
        raise ValueError("A trader alias secret is required")
    trader_id = hmac.new(
        secret.encode("utf-8"), str(wallet).lower().encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return {"trader_id": trader_id, "alias": f"Trader {trader_id[:8].upper()}"}


def _month(timestamp: int) -> str:
    return datetime.fromtimestamp(int(timestamp), timezone.utc).strftime("%Y-%m")


def _share(value: float, total: float) -> Optional[float]:
    return value / total * 100.0 if total else None


def _safe_refresh_metadata(conn) -> Optional[Any]:
    """Return the refresh timestamp when present without requiring metadata."""
    try:
        row = conn.execute(
            "SELECT value FROM sync_meta WHERE key='last_cohort_refresh_json'"
        ).fetchone()
    except Exception:  # Lightweight test databases need not contain sync_meta.
        return None
    if not row:
        return None
    try:
        payload = json.loads(row[0])
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    for key in ("finished_at", "completed_at", "started_at", "refreshed_at"):
        value = payload.get(key)
        if isinstance(value, (int, float)) and math.isfinite(value):
            return value
        if isinstance(value, str):
            # Keep a conventional ISO-8601 timestamp, not arbitrary metadata.
            try:
                datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                continue
            return value
    return None


def _finite_or(value: Any, fallback: Optional[float] = 0.0) -> Optional[float]:
    """Keep malformed numeric source values from producing NaN JSON."""
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return fallback
    return numeric if math.isfinite(numeric) else fallback


def _safe_trade_row(row: Dict[str, Any]) -> Dict[str, Any]:
    safe = dict(row)
    safe["notional_f"] = _finite_or(row.get("notional_f"), 0.0)
    safe["premium_f"] = _finite_or(row.get("premium_f"), 0.0)
    safe["apr_f"] = _finite_or(row.get("apr_f"), None)
    safe["created_at"] = _finite_or(row.get("created_at"), 0.0)
    safe["expiry"] = _finite_or(row.get("expiry"), None)
    return safe


def _segment_row(
    key: str,
    label: str,
    members: List[Dict[str, Any]],
    participant_total: int,
    totals: Dict[str, Any],
) -> Dict[str, Any]:
    if len(members) < MIN_SEGMENT_POPULATION:
        return {
            "key": key,
            "label": label,
            "status": "limited_history",
            "participant_share_pct": None,
            "notional_share_pct": None,
            "premium_share_pct": None,
        }
    notional = sum(member["metrics"]["notional"] for member in members)
    premium = sum(member["metrics"]["premium"] for member in members)
    return {
        "key": key,
        "label": label,
        "status": "ready",
        "participant_share_pct": _share(len(members), participant_total),
        "notional_share_pct": _share(notional, totals["notional"]),
        "premium_share_pct": _share(premium, totals["premium"]),
    }


def _leaderboard(
    members: List[Dict[str, Any]], metric: str, total: float, alias_secret: Optional[str]
) -> Dict[str, Any]:
    if not alias_secret:
        return {"status": "unavailable", "rows": []}
    if not members:
        return {"status": "limited_history", "rows": []}
    if len(members) < MIN_SEGMENT_POPULATION:
        return {"status": "limited_history", "rows": []}
    ordered = sorted(
        members,
        key=lambda member: (-member["metrics"][metric], member["alias"]),
    )[:10]
    return {
        "status": "ready",
        "rows": [
            {
                "rank": rank,
                "trader_id": member["trader_id"],
                "alias": member["alias"],
                "notional": member["metrics"]["notional"],
                "premium": member["metrics"]["premium"],
                "share_pct": _share(member["metrics"][metric], total),
                "weighted_apr": member["metrics"]["weighted_apr"],
            }
            for rank, member in enumerate(ordered, start=1)
        ],
    }


def _concentration(members: List[Dict[str, Any]], totals: Dict[str, Any]) -> Dict[str, Any]:
    if len(members) < MIN_CONCENTRATION_POPULATION:
        return {"status": "limited_history", "rows": []}
    rows = []
    for percentile in (1, 5, 10):
        amount = math.ceil(percentile / 100.0 * len(members))
        notional = sum(
            item["metrics"]["notional"]
            for item in sorted(members, key=lambda item: -item["metrics"]["notional"])[:amount]
        )
        premium = sum(
            item["metrics"]["premium"]
            for item in sorted(members, key=lambda item: -item["metrics"]["premium"])[:amount]
        )
        rows.append({
            "percentile": percentile,
            "notional_share_pct": _share(notional, totals["notional"]),
            "premium_share_pct": _share(premium, totals["premium"]),
        })
    return {"status": "ready", "rows": rows}


def get_participant_analytics(
    conn, days: int = 365, chain_id: Optional[int] = None, alias_secret: Optional[str] = None
) -> Dict[str, Any]:
    """Build anonymous trader analytics from verified short-owner attribution.

    ``days=0`` reads all stored history. Exact identities are used only inside
    this function and are never included in the returned dictionary.
    """
    days = int(days or 0)
    parts: List[str] = []
    params: List[Any] = []
    if days > 0:
        parts.append("t.created_at >= ?")
        params.append(int(time.time()) - days * SECONDS_PER_DAY)
    if chain_id is not None:
        parts.append("t.chain_id = ?")
        params.append(chain_id)
    where = "WHERE " + " AND ".join(parts) if parts else ""
    all_rows = [_safe_trade_row(dict(row)) for row in conn.execute(
        f"""
        SELECT t.created_at,t.expiry,t.notional_f,t.premium_f,t.apr_f,t.is_put,t.outcome,
               CASE WHEN w.status='verified_short_owner' THEN w.wallet END AS wallet
        FROM trades t LEFT JOIN trade_wallets w
          ON t.chain_id=w.chain_id AND t.tx_hash=w.tx_hash
        {where}
        ORDER BY t.created_at
        """,
        params,
    ).fetchall()]

    attributed_rows = [row for row in all_rows if row["wallet"]]
    by_wallet: Dict[str, Dict[str, Any]] = {}
    for row in attributed_rows:
        wallet = str(row["wallet"]).lower()
        member = by_wallet.setdefault(wallet, {"aggregate": _new_aggregate(), "months": set()})
        _add_row(member["aggregate"], row)
        member["months"].add(_month(row["created_at"]))

    members = []
    for wallet, member in by_wallet.items():
        metrics = _finish_aggregate(member["aggregate"])
        identity = public_trader_identity(wallet, alias_secret) if alias_secret else None
        members.append({
            "alias": identity["alias"] if identity else None,
            "trader_id": identity["trader_id"] if identity else None,
            "metrics": metrics,
            "months": member["months"],
        })
    totals_aggregate = _new_aggregate()
    for row in attributed_rows:
        _add_row(totals_aggregate, row)
    totals = _finish_aggregate(totals_aggregate)

    apr_members: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    activity_members: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for member in members:
        apr = member["metrics"]["weighted_apr"]
        if apr is None or not math.isfinite(apr):
            apr_key = "unclassified"
        elif apr < 10:
            apr_key = "under_10"
        elif apr < 25:
            apr_key = "10_to_25"
        elif apr < 50:
            apr_key = "25_to_50"
        elif apr < 100:
            apr_key = "50_to_100"
        else:
            apr_key = "100_plus"
        apr_members[apr_key].append(member)

        if member["metrics"]["trade_count"] == 1:
            activity_key = "one_trade"
        elif len(member["months"]) == 1:
            activity_key = "repeat_one_month"
        else:
            activity_key = "multiple_months"
        activity_members[activity_key].append(member)

    observed = [row["created_at"] for row in all_rows]
    return {
        "leaderboards": {
            "notional": _leaderboard(members, "notional", totals["notional"], alias_secret),
            "premium": _leaderboard(members, "premium", totals["premium"], alias_secret),
        },
        "apr_segments": [
            _segment_row(key, label, apr_members[key], len(members), totals)
            for key, label, _lower, _upper in APR_SEGMENTS
        ],
        "activity_segments": [
            _segment_row("one_trade", "One trade", activity_members["one_trade"], len(members), totals),
            _segment_row("repeat_one_month", "Repeat in one UTC month", activity_members["repeat_one_month"], len(members), totals),
            _segment_row("multiple_months", "Multiple UTC months", activity_members["multiple_months"], len(members), totals),
        ],
        "concentration": _concentration(members, totals),
        "coverage": {
            "total_trades": len(all_rows),
            "attributed_trades": len(attributed_rows),
            "coverage_pct": _share(len(attributed_rows), len(all_rows)) or 0.0,
            "observed_from": datetime.fromtimestamp(min(observed), timezone.utc).isoformat() if observed else None,
            "observed_through": datetime.fromtimestamp(max(observed), timezone.utc).isoformat() if observed else None,
            "last_refreshed": _safe_refresh_metadata(conn),
        },
        "filters": {"days": days, "chain_id": chain_id},
        "methodology": {
            "weighted_apr": "Premium yield at entry, annualized from premium and strike-notional-days over 365 days; it is not realized profit.",
            "privacy": "Wallet addresses and participant totals are withheld. Small populations are shown as Limited history.",
            "coverage": "Percentages use verified attributed trading activity in the selected window and chain filter.",
            "concentration": "Concentration ranks notional and premium independently; percentile group sizes are rounded up to a whole trader.",
        },
    }
