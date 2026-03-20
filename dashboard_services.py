"""
Shared service helpers for dashboard API routes and CLI commands.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from positions_api import fetch_history, fetch_positions


ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")


def validate_account_address(address: str) -> str:
    normalized = (address or "").strip()
    if not ADDRESS_RE.match(normalized):
        raise ValueError("Invalid wallet address format")
    return normalized


def get_positions_payload(account_address: str) -> Dict:
    return {
        "account": account_address,
        "positions": fetch_positions(account_address),
    }


def get_history_payload(account_address: str) -> Dict:
    return {
        "account": account_address,
        "history": fetch_history(account_address),
    }


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def filter_open_positions(positions: List[Dict], symbol: Optional[str], strategy: Optional[str]) -> List[Dict]:
    rows = list(positions or [])
    if symbol:
        wanted = symbol.upper()
        rows = [p for p in rows if (p.get("symbol") or "").upper() == wanted]

    if strategy:
        strategy = strategy.lower()
        strategy_map = {
            "csp": "cash_secured_put",
            "cash_secured_put": "cash_secured_put",
            "cc": "covered_call",
            "covered_call": "covered_call",
        }
        wanted_strategy = strategy_map.get(strategy)
        if wanted_strategy:
            rows = [p for p in rows if (p.get("strategy") or "").lower() == wanted_strategy]
    return rows


def filter_expired_positions(expired_positions: List[Dict], symbol: Optional[str], outcome: Optional[str]) -> List[Dict]:
    rows = list(expired_positions or [])
    if symbol:
        wanted = symbol.upper()
        rows = [p for p in rows if (p.get("symbol") or "").upper() == wanted]
    if outcome:
        wanted = outcome.lower()
        rows = [p for p in rows if (p.get("outcome") or "").lower() == wanted]
    return rows


def build_history_deep_dive(history: Dict, symbol: Optional[str] = None) -> Dict:
    summary = dict(history.get("summary") or {})
    summary.pop("unknown_count", None)
    expired_positions = history.get("expired_positions") or []
    filtered = filter_expired_positions(expired_positions, symbol=symbol, outcome=None)

    top_premium = sorted(filtered, key=lambda x: float(x.get("premium") or 0), reverse=True)[:15]
    top_apr = sorted(
        [x for x in filtered if x.get("apr") is not None],
        key=lambda x: float(x.get("apr") or 0),
        reverse=True,
    )[:15]

    asset_outcomes = summary.get("asset_outcomes") or []
    if symbol:
        symbol_upper = symbol.upper()
        asset_outcomes = [a for a in asset_outcomes if (a.get("symbol") or "").upper() == symbol_upper]

    return {
        "summary": summary,
        "asset_outcomes": asset_outcomes,
        "positions_considered": len(filtered),
        "top_premium_positions": top_premium,
        "top_apr_positions": top_apr,
    }


def build_positions_expiring(
    open_positions: List[Dict],
    expiry_date: str,
    symbol: Optional[str] = None,
    strategy: Optional[str] = None,
) -> Dict[str, Any]:
    filtered = filter_open_positions(open_positions, symbol=symbol, strategy=strategy)
    expiring = [p for p in filtered if (p.get("expiry_date") or "") == expiry_date]
    total_notional = sum(_to_float(p.get("notional")) for p in expiring)
    total_premium = sum(_to_float(p.get("premium")) for p in expiring)

    by_symbol: Dict[str, float] = {}
    by_strategy: Dict[str, float] = {}
    for p in expiring:
        sym = (p.get("symbol") or "UNKNOWN").upper()
        strat = (p.get("strategy") or "other").lower()
        by_symbol[sym] = by_symbol.get(sym, 0.0) + _to_float(p.get("notional"))
        by_strategy[strat] = by_strategy.get(strat, 0.0) + _to_float(p.get("notional"))

    return {
        "expiry_date": expiry_date,
        "count": len(expiring),
        "filters": {"symbol": symbol, "strategy": strategy},
        "totals": {
            "notional": total_notional,
            "premium": total_premium,
        },
        "breakdown": {
            "by_symbol_notional": by_symbol,
            "by_strategy_notional": by_strategy,
        },
        "positions": expiring,
    }


def build_history_expiry_prices(
    expired_positions: List[Dict],
    symbol: Optional[str] = None,
    expiry_date: Optional[str] = None,
) -> Dict[str, Any]:
    filtered = filter_expired_positions(expired_positions, symbol=symbol, outcome=None)
    if expiry_date:
        filtered = [p for p in filtered if (p.get("expiry_date") or "") == expiry_date]

    grouped: Dict[Tuple[str, int], Dict[str, Any]] = {}
    for pos in filtered:
        sym = (pos.get("symbol") or "UNKNOWN").upper()
        expiry_raw = pos.get("expiry")
        expiry_ts = int(_to_float(expiry_raw)) if expiry_raw is not None else 0
        expiry_day = pos.get("expiry_date") or "Unknown"
        key = (sym, expiry_ts)
        entry = grouped.setdefault(
            key,
            {
                "symbol": sym,
                "expiry": expiry_ts if expiry_ts > 0 else None,
                "expiry_date": expiry_day,
                "positions_total": 0,
                "positions_with_price": 0,
                "assigned_count": 0,
                "returned_count": 0,
                "expiry_price": None,
            },
        )

        entry["positions_total"] += 1
        outcome = (pos.get("outcome") or "Unknown").lower()
        if outcome == "assigned":
            entry["assigned_count"] += 1
        elif outcome == "returned":
            entry["returned_count"] += 1

        expiry_price = pos.get("expiry_price")
        if expiry_price is None:
            continue
        price = _to_float(expiry_price)
        entry["positions_with_price"] += 1
        # Rysk has one settlement print per underlying + expiry.
        if entry["expiry_price"] is None:
            entry["expiry_price"] = price

    rows = list(grouped.values())
    rows.sort(key=lambda r: (-(r.get("expiry") or 0), (r.get("symbol") or "")))
    return {
        "filters": {"symbol": symbol, "expiry_date": expiry_date},
        "groups": rows,
        "group_count": len(rows),
        "positions_considered": len(filtered),
    }
