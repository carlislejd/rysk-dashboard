"""
Shared service helpers for dashboard API routes and CLI commands.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from backtest_services import build_assignment_backtest
from chain_metadata import chain_fields, parse_chain_id
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


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _tag_rows(rows: List[Dict], account_address: str) -> List[Dict]:
    return [{**row, "wallet_address": account_address} for row in (rows or [])]


def _merge_asset_summaries(payloads: List[Dict]) -> List[Dict]:
    merged: Dict[Tuple[str, Any], Dict] = {}
    for payload in payloads:
        for asset in payload.get("asset_summary") or []:
            key = ((asset.get("symbol") or "UNKNOWN").upper(), asset.get("chain_id"))
            entry = merged.setdefault(key, {
                "symbol": key[0], **chain_fields(key[1]),
                "count": 0, "quantity_total": 0.0, "premium_total": 0.0,
                "notional_total": 0.0, "current_price": asset.get("current_price"), "strikes": {},
                "apr_weighted": 0.0, "apr_weight": 0.0,
            })
            count = int(asset.get("count") or 0)
            entry["count"] += count
            for field in ("quantity_total", "premium_total", "notional_total"):
                entry[field] += _number(asset.get(field))
            if entry["current_price"] is None:
                entry["current_price"] = asset.get("current_price")
            if asset.get("avg_apr") is not None:
                entry["apr_weighted"] += _number(asset.get("avg_apr")) * count
                entry["apr_weight"] += count
            for strike in asset.get("strikes") or []:
                strike_key = str(strike.get("strike"))
                target = entry["strikes"].setdefault(strike_key, {
                    "strike": strike.get("strike"), "count": 0, "quantity_total": 0.0,
                    "premium_total": 0.0, "notional_total": 0.0, "apr_weighted": 0.0,
                    "apr_weight": 0.0, "strategy_notional": {},
                })
                strike_count = int(strike.get("count") or 0)
                target["count"] += strike_count
                for field in ("quantity_total", "premium_total", "notional_total"):
                    target[field] += _number(strike.get(field))
                if strike.get("avg_apr") is not None:
                    target["apr_weighted"] += _number(strike.get("avg_apr")) * strike_count
                    target["apr_weight"] += strike_count
                for strategy, notional in (strike.get("strategy_notional") or {}).items():
                    target["strategy_notional"][strategy] = target["strategy_notional"].get(strategy, 0.0) + _number(notional)

    results = []
    for entry in merged.values():
        strikes = []
        for strike in entry.pop("strikes").values():
            strategy_values = strike["strategy_notional"]
            non_zero = [name for name, value in strategy_values.items() if value > 0]
            strike["dominant_strategy"] = non_zero[0] if len(non_zero) == 1 else ("mixed" if non_zero else "other")
            strike["avg_apr"] = strike.pop("apr_weighted") / strike["apr_weight"] if strike["apr_weight"] else None
            strike.pop("apr_weight")
            strikes.append(strike)
        strikes.sort(key=lambda row: row.get("strike") or 0)
        entry["strikes"] = strikes
        entry["avg_apr"] = entry.pop("apr_weighted") / entry["apr_weight"] if entry["apr_weight"] else None
        entry.pop("apr_weight")
        results.append(entry)
    return sorted(results, key=lambda row: (-row["notional_total"], row["symbol"], row.get("chain_id") or 0))


def get_positions_payload_for_accounts(account_addresses: List[str]) -> Dict:
    payloads = [fetch_positions(address) for address in account_addresses]
    open_positions = []
    for address, payload in zip(account_addresses, payloads):
        open_positions.extend(_tag_rows(payload.get("open_positions") or [], address))
    open_positions.sort(key=lambda row: (row.get("expiry") or 0, row.get("created_at_iso") or ""))
    summaries = [payload.get("summary") or {} for payload in payloads]
    total_notional = sum(_number(summary.get("open_notional_total")) for summary in summaries)
    weighted_apr = sum(
        _number(summary.get("open_weighted_apr")) * _number(summary.get("open_notional_total"))
        for summary in summaries if summary.get("open_weighted_apr") is not None
    )
    weighted_days = sum(
        _number(summary.get("open_weighted_days")) * _number(summary.get("open_notional_total"))
        for summary in summaries if summary.get("open_weighted_days") is not None
    )
    return {
        "account": account_addresses[0] if len(account_addresses) == 1 else None,
        "accounts": account_addresses,
        "positions": {
            "open_positions": open_positions,
            "asset_summary": _merge_asset_summaries(payloads),
            "summary": {
                "open_count": sum(int(summary.get("open_count") or 0) for summary in summaries),
                "open_premium_total": sum(_number(summary.get("open_premium_total")) for summary in summaries),
                "open_notional_total": total_notional,
                "open_weighted_days": weighted_days / total_notional if total_notional else None,
                "open_annualized_premium_total": sum(_number(summary.get("open_annualized_premium_total")) for summary in summaries),
                "open_weighted_apr": weighted_apr / total_notional if total_notional else None,
            },
        },
    }


def _merge_asset_outcomes(summaries: List[Dict]) -> List[Dict]:
    merged: Dict[Tuple[str, Any], Dict] = {}
    additive = ("total_positions", "assigned_count", "returned_count", "unknown_count", "assigned_quantity",
                "returned_quantity", "assigned_notional", "premium_total", "total_notional")
    for summary in summaries:
        for asset in summary.get("asset_outcomes") or []:
            key = ((asset.get("symbol") or "UNKNOWN").upper(), asset.get("chain_id"))
            entry = merged.setdefault(key, {"symbol": key[0], **chain_fields(key[1])})
            for field in additive:
                entry[field] = entry.get(field, 0) + _number(asset.get(field))
            for value_field, count_field in (("avg_assigned_expiry", "assigned_count"), ("avg_returned_expiry", "returned_count")):
                if asset.get(value_field) is not None:
                    entry[value_field + "_sum"] = entry.get(value_field + "_sum", 0.0) + _number(asset[value_field]) * _number(asset.get(count_field))
                    entry[value_field + "_count"] = entry.get(value_field + "_count", 0.0) + _number(asset.get(count_field))
    results = []
    for entry in merged.values():
        entry["avg_assignment_price"] = entry["assigned_notional"] / entry["assigned_quantity"] if entry["assigned_quantity"] else None
        for field in ("avg_assigned_expiry", "avg_returned_expiry"):
            total = entry.pop(field + "_sum", 0.0)
            count = entry.pop(field + "_count", 0.0)
            entry[field] = total / count if count else None
        results.append(entry)
    return sorted(results, key=lambda row: (-row["assigned_count"], -row["returned_count"], row["symbol"], row.get("chain_id") or 0))


def get_history_payload_for_accounts(account_addresses: List[str]) -> Dict:
    payloads = [fetch_history(address) for address in account_addresses]
    trades, expired = [], []
    for address, payload in zip(account_addresses, payloads):
        trades.extend(_tag_rows(payload.get("trades") or [], address))
        expired.extend(_tag_rows(payload.get("expired_positions") or [], address))
    trades.sort(key=lambda row: row.get("created_at_iso") or "", reverse=True)
    expired.sort(key=lambda row: (row.get("expiry") or 0, row.get("created_at_iso") or ""), reverse=True)
    summaries = [payload.get("summary") or {} for payload in payloads]
    return {
        "account": account_addresses[0] if len(account_addresses) == 1 else None,
        "accounts": account_addresses,
        "history": {
            "trades": trades,
            "expired_positions": expired,
            "summary": {
                "expired_count": sum(int(summary.get("expired_count") or 0) for summary in summaries),
                "net_premium": sum(_number(summary.get("net_premium")) for summary in summaries),
                "total_notional": sum(_number(summary.get("total_notional")) for summary in summaries),
                "assigned_count": sum(int(summary.get("assigned_count") or 0) for summary in summaries),
                "unknown_count": sum(int(summary.get("unknown_count") or 0) for summary in summaries),
                "assigned_notional_total": sum(_number(summary.get("assigned_notional_total")) for summary in summaries),
                "returned_count": sum(int(summary.get("returned_count") or 0) for summary in summaries),
                "returned_quantity_total": sum(_number(summary.get("returned_quantity_total")) for summary in summaries),
                "asset_outcomes": _merge_asset_outcomes(summaries),
            },
        },
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


def filter_positions_by_chain(positions: List[Dict], chain_id: Optional[int]) -> List[Dict]:
    if chain_id is None:
        return list(positions or [])
    return [p for p in positions or [] if parse_chain_id(p.get("chain_id")) == chain_id]


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
    chain_id: Optional[int] = None,
) -> Dict[str, Any]:
    filtered = filter_open_positions(open_positions, symbol=symbol, strategy=strategy)
    filtered = filter_positions_by_chain(filtered, chain_id)
    expiring = [p for p in filtered if (p.get("expiry_date") or "") == expiry_date]
    total_notional = sum(_to_float(p.get("notional")) for p in expiring)
    total_premium = sum(_to_float(p.get("premium")) for p in expiring)

    by_symbol: Dict[str, float] = {}
    by_strategy: Dict[str, float] = {}
    by_chain: Dict[str, float] = {}
    for p in expiring:
        sym = (p.get("symbol") or "UNKNOWN").upper()
        strat = (p.get("strategy") or "other").lower()
        by_symbol[sym] = by_symbol.get(sym, 0.0) + _to_float(p.get("notional"))
        by_strategy[strat] = by_strategy.get(strat, 0.0) + _to_float(p.get("notional"))
        chain_name = chain_fields(p.get("chain_id"))["chain_name"]
        by_chain[chain_name] = by_chain.get(chain_name, 0.0) + _to_float(p.get("notional"))

    return {
        "expiry_date": expiry_date,
        "count": len(expiring),
        "filters": {"symbol": symbol, "strategy": strategy, "chain_id": chain_id},
        "totals": {
            "notional": total_notional,
            "premium": total_premium,
        },
        "breakdown": {
            "by_symbol_notional": by_symbol,
            "by_strategy_notional": by_strategy,
            "by_chain_notional": by_chain,
        },
        "positions": expiring,
    }


def build_history_expiry_prices(
    expired_positions: List[Dict],
    symbol: Optional[str] = None,
    expiry_date: Optional[str] = None,
    chain_id: Optional[int] = None,
) -> Dict[str, Any]:
    filtered = filter_expired_positions(expired_positions, symbol=symbol, outcome=None)
    filtered = filter_positions_by_chain(filtered, chain_id)
    if expiry_date:
        filtered = [p for p in filtered if (p.get("expiry_date") or "") == expiry_date]

    grouped: Dict[Tuple[str, int, Optional[int]], Dict[str, Any]] = {}
    for pos in filtered:
        sym = (pos.get("symbol") or "UNKNOWN").upper()
        pos_chain_id = parse_chain_id(pos.get("chain_id"))
        expiry_raw = pos.get("expiry")
        expiry_ts = int(_to_float(expiry_raw)) if expiry_raw is not None else 0
        expiry_day = pos.get("expiry_date") or "Unknown"
        key = (sym, expiry_ts, pos_chain_id)
        entry = grouped.setdefault(
            key,
            {
                "symbol": sym,
                "expiry": expiry_ts if expiry_ts > 0 else None,
                "expiry_date": expiry_day,
                **chain_fields(pos_chain_id),
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
    rows.sort(key=lambda r: (-(r.get("expiry") or 0), (r.get("symbol") or ""), r.get("chain_id") or 0))
    return {
        "filters": {"symbol": symbol, "expiry_date": expiry_date, "chain_id": chain_id},
        "groups": rows,
        "group_count": len(rows),
        "positions_considered": len(filtered),
    }
