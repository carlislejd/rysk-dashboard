"""
Assignment avoidance backtests for expired short option positions.

The first pass intentionally uses fields that are known at entry time from the
wallet history payload. Expiry price is used only for outcome metrics and
diagnostics, not as a rule input.
"""

from __future__ import annotations

from datetime import datetime, timezone
from bisect import bisect_right
from typing import Any, Callable, Dict, Iterable, List, Optional


RulePredicate = Callable[[Dict[str, Any]], bool]


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _parse_iso(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        text = str(value)
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except ValueError:
        return None


def _entry_dte_days(position: Dict[str, Any]) -> Optional[float]:
    created = _parse_iso(position.get("created_at_iso"))
    expiry = position.get("expiry")
    if created is None or expiry is None:
        return None
    try:
        expiry_dt = datetime.fromtimestamp(int(expiry), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None
    return max((expiry_dt - created).total_seconds() / 86400.0, 0.0)


def _normalize_position(position: Dict[str, Any]) -> Dict[str, Any]:
    row = dict(position)
    symbol = (row.get("symbol") or "UNKNOWN").upper()
    strategy = (row.get("strategy") or "").lower()
    option_type = (row.get("type") or "").lower()
    outcome = (row.get("outcome") or "Unknown").capitalize()
    premium = _to_float(row.get("premium"))
    notional = _to_float(row.get("notional"))
    strike = _to_float(row.get("strike"))
    expiry_price = row.get("expiry_price")
    expiry_price_f = _to_float(expiry_price) if expiry_price is not None else None
    premium_yield = (premium / notional) if notional > 0 else 0.0

    breach_pct = None
    if strike > 0 and expiry_price_f is not None:
        if option_type == "call":
            breach_pct = (expiry_price_f - strike) / strike
        elif option_type == "put":
            breach_pct = (strike - expiry_price_f) / strike

    row.update(
        {
            "symbol": symbol,
            "strategy": strategy,
            "type": option_type.capitalize() if option_type else row.get("type"),
            "outcome": outcome,
            "premium": premium,
            "notional": notional,
            "apr": row.get("apr"),
            "apr_f": _to_float(row.get("apr")) if row.get("apr") is not None else None,
            "entry_dte_days": _entry_dte_days(row),
            "premium_yield": premium_yield,
            "premium_yield_pct": premium_yield * 100.0,
            "breach_pct": breach_pct,
            "breach_pct_display": breach_pct * 100.0 if breach_pct is not None else None,
        }
    )
    return row


def _date_key_from_position(row: Dict[str, Any]) -> Optional[str]:
    created = _parse_iso(row.get("created_at_iso"))
    if created is None:
        return None
    return created.astimezone(timezone.utc).strftime("%Y-%m-%d")


def _attach_hype_volatility(rows: List[Dict[str, Any]], volatility_points: Optional[List[Dict[str, Any]]]) -> None:
    if not volatility_points:
        return

    points = sorted(
        [p for p in volatility_points if p.get("date")],
        key=lambda p: p["date"],
    )
    dates = [p["date"] for p in points]

    for row in rows:
        symbol = row.get("symbol") or ""
        if "HYPE" not in symbol:
            continue
        entry_date = _date_key_from_position(row)
        if not entry_date:
            continue
        idx = bisect_right(dates, entry_date) - 1
        if idx < 0:
            continue
        point = points[idx]
        row["hype_vol_date"] = point.get("date")
        row["hype_rv_3d"] = point.get("rv_3d")
        row["hype_rv_7d"] = point.get("rv_7d")
        row["hype_rv_30d"] = point.get("rv_30d")
        row["hype_return_1d_pct"] = point.get("return_1d_pct")
        row["hype_abs_return_1d_pct"] = point.get("abs_return_1d_pct")
        row["hype_return_3d_pct"] = point.get("return_3d_pct")
        row["hype_abs_return_3d_pct"] = point.get("abs_return_3d_pct")


def _summarize(rows: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    data = list(rows)
    assigned = [r for r in data if r.get("outcome") == "Assigned"]
    returned = [r for r in data if r.get("outcome") == "Returned"]
    premium = sum(_to_float(r.get("premium")) for r in data)
    notional = sum(_to_float(r.get("notional")) for r in data)
    assigned_notional = sum(_to_float(r.get("notional")) for r in assigned)
    apr_notional = sum(
        _to_float(r.get("apr_f")) * _to_float(r.get("notional"))
        for r in data
        if r.get("apr_f") is not None and _to_float(r.get("notional")) > 0
    )
    apr_denominator = sum(
        _to_float(r.get("notional"))
        for r in data
        if r.get("apr_f") is not None and _to_float(r.get("notional")) > 0
    )
    return {
        "count": len(data),
        "assigned_count": len(assigned),
        "returned_count": len(returned),
        "premium": premium,
        "notional": notional,
        "assigned_notional": assigned_notional,
        "assignment_rate": (len(assigned) / len(data)) if data else 0.0,
        "assigned_notional_rate": (assigned_notional / notional) if notional > 0 else 0.0,
        "notional_weighted_apr": (apr_notional / apr_denominator) if apr_denominator > 0 else None,
    }


def _rule_result(
    rule_id: str,
    name: str,
    description: str,
    rows: List[Dict[str, Any]],
    baseline: Dict[str, Any],
    predicate: RulePredicate,
) -> Dict[str, Any]:
    skipped = [r for r in rows if predicate(r)]
    kept = [r for r in rows if not predicate(r)]
    skipped_summary = _summarize(skipped)
    kept_summary = _summarize(kept)
    baseline_premium = baseline["premium"]
    baseline_assigned = baseline["assigned_count"]
    baseline_assigned_notional = baseline["assigned_notional"]
    premium_lost = skipped_summary["premium"]
    returned_premium_lost = sum(
        _to_float(r.get("premium"))
        for r in skipped
        if r.get("outcome") == "Returned"
    )

    return {
        "rule_id": rule_id,
        "name": name,
        "description": description,
        "skipped": skipped_summary,
        "kept": kept_summary,
        "premium_retained_pct": (kept_summary["premium"] / baseline_premium * 100.0) if baseline_premium > 0 else 0.0,
        "notional_retained_pct": (kept_summary["notional"] / baseline["notional"] * 100.0) if baseline["notional"] > 0 else 0.0,
        "assigned_count_avoided": skipped_summary["assigned_count"],
        "assigned_count_avoided_pct": (skipped_summary["assigned_count"] / baseline_assigned * 100.0) if baseline_assigned > 0 else 0.0,
        "assigned_notional_avoided": skipped_summary["assigned_notional"],
        "assigned_notional_avoided_pct": (
            skipped_summary["assigned_notional"] / baseline_assigned_notional * 100.0
        ) if baseline_assigned_notional > 0 else 0.0,
        "premium_lost": premium_lost,
        "returned_premium_lost": returned_premium_lost,
        "avoided_assigned_notional_per_premium_lost": (
            skipped_summary["assigned_notional"] / premium_lost
        ) if premium_lost > 0 else None,
    }


def _candidate_rules(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    symbols = sorted({r["symbol"] for r in rows if r.get("symbol")})
    strategies = sorted({r["strategy"] for r in rows if r.get("strategy")})
    rules: List[Dict[str, Any]] = []

    for strategy in strategies:
        label = strategy.replace("_", " ")
        rules.append(
            {
                "rule_id": f"skip_strategy:{strategy}",
                "name": f"Skip {label}",
                "description": f"Skip all {label} positions.",
                "predicate": lambda r, strategy=strategy: r.get("strategy") == strategy,
            }
        )

    for symbol in symbols:
        rules.append(
            {
                "rule_id": f"skip_symbol:{symbol}",
                "name": f"Skip {symbol}",
                "description": f"Skip all {symbol} positions.",
                "predicate": lambda r, symbol=symbol: r.get("symbol") == symbol,
            }
        )
        for strategy in strategies:
            label = strategy.replace("_", " ")
            rules.append(
                {
                    "rule_id": f"skip_symbol_strategy:{symbol}:{strategy}",
                    "name": f"Skip {symbol} {label}",
                    "description": f"Skip {symbol} positions tagged as {label}.",
                    "predicate": lambda r, symbol=symbol, strategy=strategy: (
                        r.get("symbol") == symbol and r.get("strategy") == strategy
                    ),
                }
            )

    for threshold in (20, 25, 30, 35, 40, 50, 60):
        rules.append(
            {
                "rule_id": f"max_apr:{threshold}",
                "name": f"Cap APR at {threshold}%",
                "description": f"Skip positions with quoted APR above {threshold}%.",
                "predicate": lambda r, threshold=threshold: (
                    r.get("apr_f") is not None and r.get("apr_f") > threshold
                ),
            }
        )

    for threshold in (0.5, 0.75, 1.0, 1.25, 1.5, 2.0):
        rules.append(
            {
                "rule_id": f"max_premium_yield:{threshold}",
                "name": f"Cap premium yield at {threshold}%",
                "description": f"Skip positions where premium/notional is above {threshold}%.",
                "predicate": lambda r, threshold=threshold: r.get("premium_yield_pct", 0.0) > threshold,
            }
        )

    for threshold in (7, 14, 21, 28, 35):
        rules.append(
            {
                "rule_id": f"max_dte:{threshold}",
                "name": f"Skip DTE over {threshold}d",
                "description": f"Skip positions opened more than {threshold} days before expiry.",
                "predicate": lambda r, threshold=threshold: (
                    r.get("entry_dte_days") is not None and r.get("entry_dte_days") > threshold
                ),
            }
        )

    vol_specs = [
        ("hype_rv_3d", "3d HYPE realized vol"),
        ("hype_rv_7d", "7d HYPE realized vol"),
        ("hype_rv_30d", "30d HYPE realized vol"),
    ]
    for field, label in vol_specs:
        observed = sorted({_to_float(r.get(field)) for r in rows if r.get(field) is not None})
        if not observed:
            continue
        fixed_thresholds = [50.0, 75.0, 100.0, 125.0, 150.0]
        percentile_thresholds = []
        for pct in (0.5, 0.65, 0.8):
            idx = min(len(observed) - 1, max(0, int(round((len(observed) - 1) * pct))))
            percentile_thresholds.append(round(observed[idx], 1))
        thresholds = sorted({t for t in fixed_thresholds + percentile_thresholds if t > 0})
        for threshold in thresholds:
            rules.append(
                {
                    "rule_id": f"max_{field}:{threshold}",
                    "name": f"Cap {label} at {threshold:g}%",
                    "description": f"Skip HYPE-linked positions when entry {label} is above {threshold:g}%.",
                    "predicate": lambda r, field=field, threshold=threshold: (
                        "HYPE" in (r.get("symbol") or "") and r.get(field) is not None and _to_float(r.get(field)) > threshold
                    ),
                }
            )

    movement_specs = [
        ("hype_abs_return_1d_pct", "1d HYPE absolute move", [3.0, 5.0, 7.5, 10.0, 12.5]),
        ("hype_abs_return_3d_pct", "3d HYPE absolute move", [5.0, 7.5, 10.0, 15.0, 20.0]),
    ]
    for field, label, fixed_thresholds in movement_specs:
        observed = sorted({_to_float(r.get(field)) for r in rows if r.get(field) is not None})
        if not observed:
            continue
        percentile_thresholds = []
        for pct in (0.5, 0.65, 0.8):
            idx = min(len(observed) - 1, max(0, int(round((len(observed) - 1) * pct))))
            percentile_thresholds.append(round(observed[idx], 1))
        thresholds = sorted({t for t in fixed_thresholds + percentile_thresholds if t > 0})
        for threshold in thresholds:
            rules.append(
                {
                    "rule_id": f"max_{field}:{threshold}",
                    "name": f"Cap {label} at {threshold:g}%",
                    "description": f"Skip HYPE-linked positions when entry {label} is above {threshold:g}%.",
                    "predicate": lambda r, field=field, threshold=threshold: (
                        "HYPE" in (r.get("symbol") or "") and r.get(field) is not None and _to_float(r.get(field)) > threshold
                    ),
                }
            )

    directional_specs = [
        (
            "hype_return_1d_pct",
            "1d HYPE up move",
            "covered_call",
            "covered calls",
            [2.5, 5.0, 7.5, 10.0],
            lambda value, threshold: value > threshold,
        ),
        (
            "hype_return_1d_pct",
            "1d HYPE down move",
            "cash_secured_put",
            "cash-secured puts",
            [-2.5, -5.0, -7.5, -10.0],
            lambda value, threshold: value < threshold,
        ),
        (
            "hype_return_3d_pct",
            "3d HYPE up move",
            "covered_call",
            "covered calls",
            [5.0, 10.0, 15.0, 20.0],
            lambda value, threshold: value > threshold,
        ),
        (
            "hype_return_3d_pct",
            "3d HYPE down move",
            "cash_secured_put",
            "cash-secured puts",
            [-5.0, -10.0, -15.0, -20.0],
            lambda value, threshold: value < threshold,
        ),
    ]
    for field, label, strategy, strategy_label, thresholds, comparator in directional_specs:
        if not any(r.get(field) is not None and r.get("strategy") == strategy for r in rows):
            continue
        for threshold in thresholds:
            direction = "above" if threshold > 0 else "below"
            rules.append(
                {
                    "rule_id": f"directional_{field}:{strategy}:{threshold}",
                    "name": f"Skip HYPE {strategy_label} after {label} {direction} {threshold:g}%",
                    "description": (
                        f"Skip HYPE-linked {strategy_label} when entry {label} is {direction} {threshold:g}%."
                    ),
                    "predicate": lambda r, field=field, strategy=strategy, threshold=threshold, comparator=comparator: (
                        "HYPE" in (r.get("symbol") or "")
                        and r.get("strategy") == strategy
                        and r.get(field) is not None
                        and comparator(_to_float(r.get(field)), threshold)
                    ),
                }
            )

    combined_specs = [
        (
            "cc_rich_longer_dte",
            "Skip rich longer-DTE covered calls",
            "Skip covered calls with DTE over 14d and premium yield above 0.75%.",
            lambda r: (
                r.get("strategy") == "covered_call"
                and r.get("entry_dte_days") is not None
                and r.get("entry_dte_days") > 14
                and r.get("premium_yield_pct", 0.0) > 0.75
            ),
        ),
        (
            "csp_rich",
            "Skip rich CSPs",
            "Skip cash-secured puts with premium yield above 1.0%.",
            lambda r: r.get("strategy") == "cash_secured_put" and r.get("premium_yield_pct", 0.0) > 1.0,
        ),
        (
            "high_apr_long_dte",
            "Skip high-APR longer-DTE",
            "Skip positions with APR above 35% and DTE over 14d.",
            lambda r: (
                r.get("apr_f") is not None
                and r.get("apr_f") > 35
                and r.get("entry_dte_days") is not None
                and r.get("entry_dte_days") > 14
            ),
        ),
    ]
    for rule_id, name, description, predicate in combined_specs:
        rules.append({"rule_id": rule_id, "name": name, "description": description, "predicate": predicate})

    return rules


def build_assignment_backtest(
    history: Dict[str, Any],
    symbol: Optional[str] = None,
    strategy: Optional[str] = None,
    min_premium_retained_pct: float = 70.0,
    volatility_points: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Score assignment-avoidance veto rules against expired wallet history."""
    rows = [_normalize_position(p) for p in history.get("expired_positions") or []]
    rows = [r for r in rows if r.get("outcome") in {"Assigned", "Returned"}]
    _attach_hype_volatility(rows, volatility_points)

    if symbol:
        wanted_symbol = symbol.upper()
        rows = [r for r in rows if r.get("symbol") == wanted_symbol]
    if strategy:
        wanted_strategy = strategy.lower()
        strategy_map = {
            "cc": "covered_call",
            "covered_call": "covered_call",
            "csp": "cash_secured_put",
            "cash_secured_put": "cash_secured_put",
        }
        wanted_strategy = strategy_map.get(wanted_strategy, wanted_strategy)
        rows = [r for r in rows if r.get("strategy") == wanted_strategy]

    baseline = _summarize(rows)
    rule_results = [
        _rule_result(rule["rule_id"], rule["name"], rule["description"], rows, baseline, rule["predicate"])
        for rule in _candidate_rules(rows)
    ]
    rule_results = [
        r for r in rule_results
        if r["skipped"]["count"] > 0 and r["kept"]["count"] > 0
    ]

    filtered = [
        r for r in rule_results
        if r["premium_retained_pct"] >= min_premium_retained_pct
    ]
    filtered.sort(
        key=lambda r: (
            -r["assigned_notional_avoided_pct"],
            -r["assigned_count_avoided_pct"],
            -r["premium_retained_pct"],
            r["premium_lost"],
        )
    )

    all_ranked = sorted(
        rule_results,
        key=lambda r: (
            -r["assigned_notional_avoided_pct"],
            -r["premium_retained_pct"],
            r["premium_lost"],
        ),
    )

    return {
        "filters": {
            "symbol": symbol,
            "strategy": strategy,
            "min_premium_retained_pct": min_premium_retained_pct,
        },
        "data_notes": [
            "Rules use entry-known wallet fields only: symbol, strategy, APR, premium/notional, DTE, and notional.",
            "HYPE realized volatility rules use the latest daily HYPE vol point available on or before trade entry when provided.",
            "HYPE movement rules use close-to-close daily returns known on or before trade entry when provided.",
            "Expiry price is used only to evaluate assignment outcomes and breach diagnostics.",
            "Entry-time spot, delta, and market-wide replacement trades are not yet included.",
        ],
        "baseline": baseline,
        "rule_count": len(rule_results),
        "recommended_rules": filtered[:10],
        "top_rules": all_ranked[:25],
        "diagnostics": _build_diagnostics(rows),
    }


def _build_diagnostics(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_symbol_strategy: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        key = f"{row.get('symbol')}:{row.get('strategy')}"
        entry = by_symbol_strategy.setdefault(
            key,
            {
                "symbol": row.get("symbol"),
                "strategy": row.get("strategy"),
                "count": 0,
                "assigned_count": 0,
                "premium": 0.0,
                "notional": 0.0,
                "assigned_notional": 0.0,
                "breach_pct_sum": 0.0,
                "breach_pct_count": 0,
            },
        )
        entry["count"] += 1
        entry["premium"] += _to_float(row.get("premium"))
        entry["notional"] += _to_float(row.get("notional"))
        if row.get("outcome") == "Assigned":
            entry["assigned_count"] += 1
            entry["assigned_notional"] += _to_float(row.get("notional"))
            if row.get("breach_pct") is not None:
                entry["breach_pct_sum"] += _to_float(row.get("breach_pct"))
                entry["breach_pct_count"] += 1

    groups = []
    for entry in by_symbol_strategy.values():
        groups.append(
            {
                "symbol": entry["symbol"],
                "strategy": entry["strategy"],
                "count": entry["count"],
                "assigned_count": entry["assigned_count"],
                "assignment_rate": entry["assigned_count"] / entry["count"] if entry["count"] else 0.0,
                "premium": entry["premium"],
                "notional": entry["notional"],
                "assigned_notional": entry["assigned_notional"],
                "assigned_notional_rate": (
                    entry["assigned_notional"] / entry["notional"]
                ) if entry["notional"] > 0 else 0.0,
                "avg_assigned_breach_pct": (
                    entry["breach_pct_sum"] / entry["breach_pct_count"] * 100.0
                ) if entry["breach_pct_count"] else None,
            }
        )

    groups.sort(key=lambda g: (-g["assigned_notional"], -g["assigned_count"], g["symbol"], g["strategy"]))
    return {"by_symbol_strategy": groups}
