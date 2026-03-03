"""
Shared service helpers for dashboard API routes and CLI commands.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional

from hyperliquid_client import get_price_history
from inventory_api import fetch_inventory, get_call_options
from positions_api import fetch_history, fetch_positions
from rpc_client import TOKEN_ADDRESSES, get_all_balances
from suggestions import get_suggestions


ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")


def validate_account_address(address: str) -> str:
    normalized = (address or "").strip()
    if not ADDRESS_RE.match(normalized):
        raise ValueError("Invalid wallet address format")
    return normalized


def get_balances_payload(account_address: str) -> Dict:
    balances = get_all_balances(account_address)

    inventory_data = fetch_inventory()
    prices = {}
    if inventory_data:
        for asset in balances.keys():
            if asset in inventory_data:
                asset_data = inventory_data[asset]
                combinations = asset_data.get("combinations", {})
                for combo_data in combinations.values():
                    index = combo_data.get("index", 0)
                    if index > 0:
                        prices[asset] = index
                        break

    notional = {}
    for asset, balance in balances.items():
        price = prices.get(asset, 0)
        notional[asset] = balance * price if price > 0 else 0

    if "USDT0" in balances and prices.get("USDT0", 0) == 0:
        prices["USDT0"] = 1.0
        notional["USDT0"] = balances["USDT0"] * 1.0

    addresses = {}
    for asset in balances.keys():
        if asset in TOKEN_ADDRESSES:
            addresses[asset] = TOKEN_ADDRESSES[asset]

    return {
        "account": account_address,
        "balances": balances,
        "prices": prices,
        "notional": notional,
        "addresses": addresses,
    }


def get_inventory_payload() -> Dict:
    inventory_data = fetch_inventory()
    if not inventory_data:
        raise RuntimeError("Failed to fetch inventory")

    inventory = {}
    for asset in ["BTC", "ETH", "HYPE", "SOL", "PUMP", "PURR"]:
        if asset in inventory_data:
            options = get_call_options(inventory_data, asset, max_assignment_risk=25.0)
            inventory[asset] = options

    return {"inventory": inventory}


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


def get_suggestions_payload(account_address: str) -> Dict:
    return {
        "target_apr": 25.0,
        "account": account_address,
        "suggestions": get_suggestions(account_address, max_suggestions_per_asset=3),
    }


def get_chart_payload(account_address: str, asset: str, days: int = 7) -> Dict:
    asset = (asset or "").upper()
    if not asset:
        raise ValueError("Asset parameter required")

    price_data = get_price_history(asset, days=days, interval="1h")
    if price_data is None:
        raise RuntimeError(f"Failed to fetch price data for {asset}")

    strikes = []
    try:
        suggestions = get_suggestions(account_address, max_suggestions_per_asset=3)
        if asset in suggestions:
            for opt in suggestions[asset].get("options", []):
                strikes.append(
                    {
                        "strike": opt["strike"],
                        "apy": opt["apy"],
                        "assignment_risk": opt["assignment_risk"],
                        "expiry": opt["expiry"],
                    }
                )
    except Exception:
        # Non-critical for chart response.
        pass

    chart_data = {
        "times": [candle["time"].isoformat() for candle in price_data],
        "opens": [candle["open"] for candle in price_data],
        "highs": [candle["high"] for candle in price_data],
        "lows": [candle["low"] for candle in price_data],
        "closes": [candle["close"] for candle in price_data],
        "volumes": [candle["volume"] for candle in price_data],
        "strikes": strikes,
    }

    return {"account": account_address, "asset": asset, "data": chart_data}


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
    summary = history.get("summary") or {}
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
