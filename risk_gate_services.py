"""
Pre-trade clearance gates for selling covered calls and cash-secured puts.

These gates are intentionally simple and explainable: they use daily realized
movement/volatility known before entry, plus an optional target DTE.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from volatility_services import get_asset_volatility


DEFAULT_GATE_CONFIG: Dict[str, Dict[str, Any]] = {
    "HYPE": {
        "rv7_warn": 90.0,
        "rv7_block": 112.3,
        "abs_1d_warn": 5.0,
        "abs_1d_block": 7.5,
        "abs_3d_warn": 10.0,
        "abs_3d_block": 15.0,
        "cc_up_warn": 1.0,
        "cc_up_block": 2.5,
        "csp_down_warn": -3.0,
        "csp_down_block": -5.0,
        "dte_warn": 21.0,
        "dte_block": 28.0,
    },
    "BTC": {
        "rv7_warn": 45.0,
        "rv7_block": 65.0,
        "abs_1d_warn": 2.5,
        "abs_1d_block": 4.0,
        "abs_3d_warn": 5.0,
        "abs_3d_block": 8.0,
        "cc_up_warn": 1.5,
        "cc_up_block": 2.5,
        "csp_down_warn": -1.5,
        "csp_down_block": -2.5,
        "dte_warn": 21.0,
        "dte_block": 28.0,
    },
}


STRATEGY_ALIASES = {
    "cc": "covered_call",
    "covered_call": "covered_call",
    "call": "covered_call",
    "csp": "cash_secured_put",
    "cash_secured_put": "cash_secured_put",
    "put": "cash_secured_put",
}


def _to_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _status_from_bounds(value: Optional[float], warn: float, block: float, direction: str) -> str:
    if value is None:
        return "unknown"
    if direction == "above":
        if value > block:
            return "block"
        if value > warn:
            return "warn"
        return "clear"
    if value < block:
        return "block"
    if value < warn:
        return "warn"
    return "clear"


def _gate(name: str, status: str, value: Optional[float], threshold: Any, message: str) -> Dict[str, Any]:
    return {
        "name": name,
        "status": status,
        "value": value,
        "threshold": threshold,
        "message": message,
    }


def _overall(gates: List[Dict[str, Any]]) -> str:
    statuses = {g["status"] for g in gates}
    if "block" in statuses:
        return "block"
    if "warn" in statuses or "unknown" in statuses:
        return "warn"
    return "clear"


def _strategy_label(strategy: str) -> str:
    return "Covered Call" if strategy == "covered_call" else "Cash-Secured Put"


def _asset_config(asset: str) -> Dict[str, Any]:
    return DEFAULT_GATE_CONFIG.get(asset.upper(), DEFAULT_GATE_CONFIG["HYPE"])


def _recommendation(overall: str, asset: str, strategy_label: str, gates: List[Dict[str, Any]]) -> str:
    drivers = [g["name"] for g in gates if g["status"] == "block"]
    if overall == "block":
        return f"Do not sell this {asset} {strategy_label} today; blocking gates: {', '.join(drivers)}."
    drivers = [g["name"] for g in gates if g["status"] in {"warn", "unknown"}]
    if overall == "warn":
        return f"Use caution selling this {asset} {strategy_label}; watch: {', '.join(drivers)}."
    return f"Clear to sell this {asset} {strategy_label} based on current gates."


def build_strategy_clearance(
    asset: str,
    strategy: str,
    target_dte: Optional[float] = None,
    days: int = 180,
    volatility_payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build one asset/strategy clearance checklist."""
    coin = (asset or "HYPE").upper()
    normalized_strategy = STRATEGY_ALIASES.get((strategy or "").lower(), strategy)
    if normalized_strategy not in {"covered_call", "cash_secured_put"}:
        raise ValueError("strategy must be cc, covered_call, csp, or cash_secured_put")

    config = _asset_config(coin)
    data = volatility_payload or get_asset_volatility(coin, days=days)
    latest = data.get("latest") or {}

    rv7 = _to_float(latest.get("rv_7d"))
    ret_1d = _to_float(latest.get("return_1d_pct"))
    abs_1d = _to_float(latest.get("abs_return_1d_pct"))
    abs_3d = _to_float(latest.get("abs_return_3d_pct"))

    gates: List[Dict[str, Any]] = []

    rv_status = _status_from_bounds(rv7, config["rv7_warn"], config["rv7_block"], "above")
    gates.append(_gate(
        "7d realized volatility",
        rv_status,
        rv7,
        {"warn": config["rv7_warn"], "block": config["rv7_block"]},
        f"{coin} 7d realized volatility should be below {config['rv7_block']}%.",
    ))

    abs_1d_status = _status_from_bounds(abs_1d, config["abs_1d_warn"], config["abs_1d_block"], "above")
    gates.append(_gate(
        "1d absolute move",
        abs_1d_status,
        abs_1d,
        {"warn": config["abs_1d_warn"], "block": config["abs_1d_block"]},
        f"{coin} one-day move should not be a large shock.",
    ))

    abs_3d_status = _status_from_bounds(abs_3d, config["abs_3d_warn"], config["abs_3d_block"], "above")
    gates.append(_gate(
        "3d absolute move",
        abs_3d_status,
        abs_3d,
        {"warn": config["abs_3d_warn"], "block": config["abs_3d_block"]},
        f"{coin} three-day move should not be extended.",
    ))

    if normalized_strategy == "covered_call":
        direction_status = _status_from_bounds(ret_1d, config["cc_up_warn"], config["cc_up_block"], "above")
        gates.append(_gate(
            "covered-call upside chase",
            direction_status,
            ret_1d,
            {"warn": config["cc_up_warn"], "block": config["cc_up_block"]},
            f"Avoid selling {coin} calls after a strong up day.",
        ))
    else:
        direction_status = _status_from_bounds(ret_1d, config["csp_down_warn"], config["csp_down_block"], "below")
        gates.append(_gate(
            "put downside slide",
            direction_status,
            ret_1d,
            {"warn": config["csp_down_warn"], "block": config["csp_down_block"]},
            f"Avoid selling {coin} puts after a strong down day.",
        ))

    if target_dte is not None:
        dte = _to_float(target_dte)
        dte_status = _status_from_bounds(dte, config["dte_warn"], config["dte_block"], "above")
        gates.append(_gate(
            "target DTE",
            dte_status,
            dte,
            {"warn": config["dte_warn"], "block": config["dte_block"]},
            "Shorter dated entries have backtested cleaner for this wallet.",
        ))

    overall = _overall(gates)
    strategy_label = _strategy_label(normalized_strategy)
    metrics = {
        "close": latest.get("close"),
        "return_1d_pct": ret_1d,
        "abs_return_1d_pct": abs_1d,
        "return_3d_pct": _to_float(latest.get("return_3d_pct")),
        "abs_return_3d_pct": abs_3d,
        "rv_3d": _to_float(latest.get("rv_3d")),
        "rv_7d": rv7,
        "rv_30d": _to_float(latest.get("rv_30d")),
    }
    return {
        "asset": coin,
        "strategy": normalized_strategy,
        "strategy_label": strategy_label,
        "overall": overall,
        "clear_to_sell": overall == "clear",
        "recommendation": _recommendation(overall, coin, strategy_label, gates),
        "as_of_date": latest.get("date"),
        "close": latest.get("close"),
        "metrics": metrics,
        "gates": gates,
        "latest": latest,
        "config": config,
    }


def build_clearance_board(
    assets: Optional[List[str]] = None,
    strategies: Optional[List[str]] = None,
    target_dte: Optional[float] = None,
    days: int = 180,
) -> Dict[str, Any]:
    """Build a board of clearance checklists for asset/strategy pairs."""
    selected_assets = [a.upper() for a in (assets or ["HYPE", "BTC"])]
    selected_strategies = strategies or ["covered_call", "cash_secured_put"]

    market_data = {
        asset: get_asset_volatility(asset, days=days)
        for asset in selected_assets
    }

    entries = []
    for asset in selected_assets:
        for strategy in selected_strategies:
            entries.append(build_strategy_clearance(
                asset,
                strategy,
                target_dte=target_dte,
                days=days,
                volatility_payload=market_data[asset],
            ))

    return {
        "assets": selected_assets,
        "strategies": selected_strategies,
        "target_dte": target_dte,
        "entries": entries,
        "notes": [
            "HYPE thresholds are seeded from this wallet's assignment backtests.",
            "BTC thresholds are initial defaults and should be tuned once BTC-specific backtests are run.",
        ],
    }
