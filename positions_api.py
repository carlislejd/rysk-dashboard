"""
Rysk Positions API Client
Fetches current open positions and historical trade data from the V12 API
"""

import os
import time
from datetime import datetime, timezone
from decimal import Decimal, getcontext

import requests

from expiry_price import get_expiry_price, get_underlying_address
from hyperliquid_client import get_current_price


# Configure high precision for decimal conversions
getcontext().prec = 28

# API configuration
API_BASE = os.getenv("RYSK_API_BASE", "https://v12.rysk.finance/api")
USER_POSITIONS_URL = os.getenv("USER_POSITIONS_URL", f"{API_BASE}/user/positions")
TRADE_HISTORY_URL = os.getenv("HISTORY_API_URL", f"{API_BASE}/history")

CACHE_TTL = int(os.getenv("RYSK_API_CACHE_TTL", "30"))

_positions_cache = {}
_history_cache = {}
_expired_positions_store = {}


def _from_wei(value, decimals=18):
    """Convert wei-denominated string/number to float"""
    if value is None:
        return 0.0
    try:
        return float(Decimal(str(value)) / (Decimal(10) ** decimals))
    except (ValueError, ArithmeticError):
        return 0.0


def _as_bool(value):
    """Parse permissive bool values from API payloads."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return False


def _is_put_position(item: dict) -> bool:
    """Support both camelCase and snake_case fields."""
    return _as_bool(item.get("isPut")) or _as_bool(item.get("is_put"))


def _parse_timestamp(ts):
    """Convert unix timestamp to datetime, human string, and status"""
    if not ts:
        return None, None, "Unknown"
    dt = datetime.fromtimestamp(int(ts), tz=timezone.utc)
    human = dt.strftime("%Y-%m-%d %H:%M")
    return dt, human, human.split(" ")[0]


def _parse_expiry(ts):
    """Return expiry datetime, date string, days to expiry, and status"""
    if not ts:
        return None, "Unknown", 0.0, "Unknown"
    dt = datetime.fromtimestamp(int(ts), tz=timezone.utc)
    now = datetime.now(tz=timezone.utc)
    delta_days = round((dt - now).total_seconds() / 86400, 2)
    days_remaining = max(delta_days, 0.0)
    status = "Active" if dt > now else "Expired"
    return dt, dt.strftime("%Y-%m-%d"), days_remaining, status


def _fetch_json(url, params=None):
    response = requests.get(url, params=params, timeout=10)
    response.raise_for_status()
    return response.json()


def _infer_strategy_key(position: dict) -> str:
    """Classify short option legs for UI strategy labeling."""
    side = str(position.get("side") or "").strip().lower()
    opt_type = str(position.get("type") or "").strip().lower()

    sell_like = side in {"sell", "short", "write"}
    buy_like = side in {"buy", "long"}

    if opt_type == "put" and (sell_like or not buy_like):
        return "cash_secured_put"
    if opt_type == "call" and (sell_like or not buy_like):
        return "covered_call"
    return "other"


def _symbol_to_market_asset(symbol: str) -> str:
    """Map position symbols to Hyperliquid spot market symbols."""
    sym = str(symbol or "").strip().upper()
    if not sym:
        return ""

    direct = {
        "BTC": "BTC",
        "UBTC": "BTC",
        "ETH": "ETH",
        "UETH": "ETH",
        "SOL": "SOL",
        "USOL": "SOL",
        "HYPE": "HYPE",
        "WHYPE": "HYPE",
        "KHYPE": "HYPE",
        "KHYPE-PT": "HYPE",
        "HYPE-PT": "HYPE",
        "PUMP": "PUMP",
        "UPUMP": "PUMP",
        "PURR": "PURR",
    }
    if sym in direct:
        return direct[sym]

    if sym.startswith("U") and sym[1:] in {"BTC", "ETH", "SOL", "PUMP", "PURR"}:
        return sym[1:]

    return sym


def _annotate_expired_position(position: dict):
    """Attach expiry price and outcome information to an expired position."""
    if not position or position.get("status") != "Expired":
        return

    symbol = position.get("symbol")
    expiry = position.get("expiry")
    strike = position.get("strike") or 0.0
    option_type = (position.get("type") or "").lower()

    asset_address = get_underlying_address(symbol)
    if not asset_address or not expiry:
        position.setdefault("outcome", "Unknown")
        return

    expiry_ts = int(expiry)

    # Try primary expiry timestamp
    price, finalized = get_expiry_price(asset_address, expiry_ts)

    # Fallback: normalize to midnight UTC for the expiry date if not finalized/available
    if (price is None or not finalized) and expiry_ts:
        try:
            dt = datetime.fromtimestamp(expiry_ts, tz=timezone.utc)
            midnight_ts = int(dt.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
            if midnight_ts != expiry_ts:
                price_fallback, finalized_fallback = get_expiry_price(asset_address, midnight_ts)
                if price_fallback is not None:
                    price, finalized = price_fallback, finalized_fallback
                    position["expiry_fallback_ts"] = midnight_ts
        except Exception:
            # If normalization fails, continue with whatever we have
            pass

    position["expiry_price"] = price
    position["expiry_price_finalized"] = finalized

    if not finalized or price is None:
        position.setdefault("outcome", "Unknown")
        return

    outcome = "Unknown"

    if option_type == "call":
        outcome = "Returned" if price <= strike else "Assigned"
    elif option_type == "put":
        outcome = "Assigned" if price <= strike else "Returned"

    position["outcome"] = outcome


def fetch_positions(account_address: str):
    """Fetch open taker positions for an address"""
    if not account_address:
        return {
            "open_positions": [],
            "summary": {}
        }
    address_key = account_address.lower()
    cached = _positions_cache.get(address_key)
    if cached and (time.time() - cached["timestamp"] < CACHE_TTL):
        return cached["data"]

    try:
        taker_raw = _fetch_json(USER_POSITIONS_URL, params={"address": account_address})
    except Exception as exc:
        print(f"Error fetching user positions: {exc}")
        taker_raw = []

    open_positions = []
    expired_positions = []
    asset_summary = {}
    open_premium_total = 0.0
    open_notional_total = 0.0
    weighted_days_sum = 0.0
    annualized_premium_sum = 0.0
    notional_weighted_apr_sum = 0.0

    for item in taker_raw or []:
        expiry_dt, expiry_date, days_to_expiry, status = _parse_expiry(item.get("expiry"))
        created_dt, created_human, created_date = _parse_timestamp(item.get("createdAt"))

        quantity = _from_wei(item.get("quantity"))
        strike = _from_wei(item.get("strike"))
        premium = _from_wei(item.get("premium"))
        price = _from_wei(item.get("price"))
        notional = quantity * strike if quantity and strike else 0.0
        premium_signed = premium if item.get("isBuy") else -premium
        days_for_calc = max(days_to_expiry, 0.01) if days_to_expiry is not None else 0.01

        is_buy = _as_bool(item.get("isBuy"))
        is_put = _is_put_position(item)

        position = {
            "symbol": item.get("symbol"),
            # Rysk payload marks written shorts with isBuy=true in this endpoint.
            "side": "Sell" if is_buy else "Buy",
            "type": "Put" if is_put else "Call",
            "apr": float(item.get("apr")) if item.get("apr") else None,
            "created_at": created_human,
            "created_at_iso": created_dt.isoformat() if created_dt else None,
            "expiry": item.get("expiry"),
            "expiry_date": expiry_date,
            "days_to_expiry": days_to_expiry,
            "status": status,
            "quantity": quantity,
            "strike": strike,
            "premium": premium,
            "price": price,
            "notional": notional,
            "tx_hash": item.get("txHash"),
            "usd_address": item.get("usd"),
        }
        position["strategy"] = _infer_strategy_key(position)

        if status == "Active":
            open_positions.append(position)
            open_premium_total += premium_signed
            if notional > 0:
                open_notional_total += notional
                weighted_days_sum += notional * days_for_calc
                annualized_premium_sum += premium_signed * (365.0 / days_for_calc)
                if position["apr"] is not None:
                    notional_weighted_apr_sum += position["apr"] * notional

            # Aggregate by asset symbol
            asset_symbol = (position["symbol"] or "UNKNOWN").upper()
            entry = asset_summary.setdefault(asset_symbol, {
                "symbol": asset_symbol,
                "count": 0,
                "quantity_total": 0.0,
                "premium_total": 0.0,
                "notional_total": 0.0,
                "apr_sum": 0.0,
                "apr_count": 0,
                "strikes": {}
            })

            entry["count"] += 1
            entry["quantity_total"] += quantity
            entry["premium_total"] += premium_signed
            entry["notional_total"] += notional
            if position["apr"] is not None:
                entry["apr_sum"] += position["apr"]
                entry["apr_count"] += 1

            strike_key = str(position["strike"])
            strike_entry = entry["strikes"].setdefault(strike_key, {
                "strike": position["strike"],
                "count": 0,
                "quantity_total": 0.0,
                "premium_total": 0.0,
                "notional_total": 0.0,
                "apr_sum": 0.0,
                "apr_count": 0,
                "covered_call_notional": 0.0,
                "cash_secured_put_notional": 0.0,
                "other_notional": 0.0,
            })
            strike_entry["count"] += 1
            strike_entry["quantity_total"] += quantity
            strike_entry["premium_total"] += premium_signed
            strike_entry["notional_total"] += notional
            if position["apr"] is not None:
                strike_entry["apr_sum"] += position["apr"]
                strike_entry["apr_count"] += 1

            strategy_key = _infer_strategy_key(position)
            if strategy_key == "covered_call":
                strike_entry["covered_call_notional"] += notional
            elif strategy_key == "cash_secured_put":
                strike_entry["cash_secured_put_notional"] += notional
            else:
                strike_entry["other_notional"] += notional
        else:
            expired_positions.append(position)

    for expired_position in expired_positions:
        _annotate_expired_position(expired_position)

    limit = int(os.getenv("RYSK_POSITIONS_LIMIT", "100"))

    open_sorted = sorted(open_positions, key=lambda x: (x.get("expiry") or 0, x.get("created_at_iso") or ""))

    asset_summary_list = []
    for symbol, entry in asset_summary.items():
        strikes_list = []
        for strike_key, strike_entry in entry["strikes"].items():
            avg_apr = strike_entry["apr_sum"] / strike_entry["apr_count"] if strike_entry["apr_count"] else None
            strategy_values = {
                "covered_call": strike_entry["covered_call_notional"],
                "cash_secured_put": strike_entry["cash_secured_put_notional"],
                "other": strike_entry["other_notional"],
            }
            dominant_strategy = max(strategy_values, key=strategy_values.get)
            non_zero_strategies = sum(1 for value in strategy_values.values() if value > 0)
            if non_zero_strategies > 1:
                dominant_strategy = "mixed"

            strikes_list.append({
                "strike": strike_entry["strike"],
                "count": strike_entry["count"],
                "quantity_total": strike_entry["quantity_total"],
                "premium_total": strike_entry["premium_total"],
                "notional_total": strike_entry["notional_total"],
                "avg_apr": avg_apr,
                "dominant_strategy": dominant_strategy,
                "strategy_notional": strategy_values,
            })
        strikes_list.sort(key=lambda s: s["strike"] or 0)

        avg_apr = entry["apr_sum"] / entry["apr_count"] if entry["apr_count"] else None
        market_asset = _symbol_to_market_asset(symbol)
        current_price = get_current_price(market_asset) if market_asset else None
        asset_summary_list.append({
            "symbol": symbol,
            "count": entry["count"],
            "quantity_total": entry["quantity_total"],
            "premium_total": entry["premium_total"],
            "notional_total": entry["notional_total"],
            "avg_apr": avg_apr,
            "current_price": current_price,
            "strikes": strikes_list
        })

    asset_summary_list.sort(key=lambda x: (-x["notional_total"], x["symbol"]))

    results = {
        "open_positions": open_sorted[:limit],
        "asset_summary": asset_summary_list,
        "summary": {
            "open_count": len(open_positions),
            "open_premium_total": open_premium_total,
            "open_notional_total": open_notional_total,
            "open_weighted_days": (weighted_days_sum / open_notional_total) if open_notional_total > 0 else None,
            "open_annualized_premium_total": annualized_premium_sum,
            # Notional-weighted APR using provided APR values, not inferred from premium timing
            "open_weighted_apr": (notional_weighted_apr_sum / open_notional_total) if open_notional_total > 0 else None,
        }
    }

    cache_entry = {
        "timestamp": time.time(),
        "data": results,
        "expired_positions": expired_positions
    }

    _positions_cache[address_key] = cache_entry
    _expired_positions_store[address_key] = {
        "timestamp": cache_entry["timestamp"],
        "positions": expired_positions
    }
    return results


def fetch_history(account_address: str, limit: int = 0):
    """Fetch trade history for an address"""
    if not account_address:
        return {"trades": [], "summary": {}}

    address_key = f"{account_address.lower()}::{limit}"
    cached = _history_cache.get(address_key)
    if cached and (time.time() - cached["timestamp"] < CACHE_TTL):
        return cached["data"]

    try:
        raw_history = _fetch_json(TRADE_HISTORY_URL, params={"address": account_address})
    except Exception as exc:
        print(f"Error fetching trade history: {exc}")
        raw_history = []

    trades = []

    for item in raw_history or []:
        created_dt, created_human, created_date = _parse_timestamp(item.get("createdAt"))
        expiry_dt, expiry_date, days_to_expiry, status = _parse_expiry(item.get("expiry"))

        quantity = _from_wei(item.get("quantity"))
        strike = _from_wei(item.get("strike"))
        premium = _from_wei(item.get("premium"))
        price = _from_wei(item.get("price"))
        notional = quantity * strike if quantity and strike else 0.0

        trades.append({
            "symbol": item.get("symbol"),
            "side": "Sell" if _as_bool(item.get("isBuy")) else "Buy",
            "type": "Put" if _is_put_position(item) else "Call",
            "apr": float(item.get("apr")) if item.get("apr") else None,
            "created_at": created_human,
            "created_at_iso": created_dt.isoformat() if created_dt else None,
            "expiry": item.get("expiry"),
            "expiry_date": expiry_date,
            "days_to_expiry": days_to_expiry,
            "status": status,
            "quantity": quantity,
            "strike": strike,
            "premium": premium,
            "price": price,
            "notional": notional,
        })

    trades_sorted = sorted(
        trades,
        key=lambda x: (x.get("created_at_iso") or ""),
        reverse=True
    )

    # Pull expired positions from cache or regenerate
    expired_cached = _expired_positions_store.get(account_address.lower())
    expired_positions = []
    expired_premium_total = 0.0
    expired_notional_total = 0.0

    if expired_cached and (time.time() - expired_cached["timestamp"] < CACHE_TTL):
        expired_positions = expired_cached.get("positions", [])
    else:
        # Populate by refreshing positions
        fetch_positions(account_address)
        expired_cached = _expired_positions_store.get(account_address.lower(), {})
        expired_positions = expired_cached.get("positions", [])

    for expired_position in expired_positions:
        if (
            "expiry_price" not in expired_position
            or not expired_position.get("expiry_price_finalized", False)
            or (expired_position.get("outcome") or "").lower() == "unknown"
        ):
            _annotate_expired_position(expired_position)

    expired_limit_env = int(os.getenv("RYSK_HISTORY_LIMIT", str(limit))) if limit is not None else 0
    expired_sorted = sorted(
        expired_positions,
        key=lambda x: (x.get("expiry") or 0, x.get("created_at_iso") or ""),
        reverse=True
    )
    expired_limit = expired_limit_env if expired_limit_env > 0 else None

    asset_outcomes = {}
    total_assigned_positions = 0
    total_returned_positions = 0
    total_unknown_positions = 0
    total_assigned_notional = 0.0
    total_returned_quantity = 0.0

    for pos in expired_sorted:
        premium = pos.get("premium") or 0.0
        notional = pos.get("notional") or 0.0
        quantity = pos.get("quantity") or 0.0
        strike = pos.get("strike") or 0.0
        expiry_price = pos.get("expiry_price") if pos.get("expiry_price") is not None else None
        outcome = (pos.get("outcome") or "").capitalize()
        symbol = (pos.get("symbol") or "UNKNOWN").upper()

        expired_premium_total += premium
        expired_notional_total += notional

        entry = asset_outcomes.setdefault(symbol, {
            "symbol": symbol,
            "total_positions": 0,
            "assigned_count": 0,
            "returned_count": 0,
            "unknown_count": 0,
            "assigned_quantity": 0.0,
            "returned_quantity": 0.0,
            "assigned_notional": 0.0,
            "premium_total": 0.0,
            "total_notional": 0.0,
            "expiry_price_assigned_sum": 0.0,
            "expiry_price_returned_sum": 0.0,
            "expiry_price_assigned_count": 0,
            "expiry_price_returned_count": 0,
        })

        entry["total_positions"] += 1
        entry["premium_total"] += premium
        entry["total_notional"] += notional

        if outcome == "Assigned":
            entry["assigned_count"] += 1
            entry["assigned_quantity"] += quantity
            entry["assigned_notional"] += notional if notional else (quantity * strike)
            total_assigned_positions += 1
            total_assigned_notional += notional if notional else (quantity * strike)
            if expiry_price is not None:
                entry["expiry_price_assigned_sum"] += expiry_price
                entry["expiry_price_assigned_count"] += 1
        elif outcome == "Returned":
            entry["returned_count"] += 1
            entry["returned_quantity"] += quantity
            total_returned_positions += 1
            total_returned_quantity += quantity
            if expiry_price is not None:
                entry["expiry_price_returned_sum"] += expiry_price
                entry["expiry_price_returned_count"] += 1
        else:
            entry["unknown_count"] += 1
            total_unknown_positions += 1

    asset_outcome_list = []
    for symbol, entry in asset_outcomes.items():
        assigned_avg_price = None
        if entry["assigned_quantity"] > 0:
            assigned_avg_price = entry["assigned_notional"] / entry["assigned_quantity"]

        avg_assigned_expiry = None
        if entry["expiry_price_assigned_count"] > 0:
            avg_assigned_expiry = entry["expiry_price_assigned_sum"] / entry["expiry_price_assigned_count"]

        avg_returned_expiry = None
        if entry["expiry_price_returned_count"] > 0:
            avg_returned_expiry = entry["expiry_price_returned_sum"] / entry["expiry_price_returned_count"]

        asset_outcome_list.append({
            "symbol": symbol,
            "total_positions": entry["total_positions"],
            "assigned_count": entry["assigned_count"],
            "returned_count": entry["returned_count"],
            "unknown_count": entry["unknown_count"],
            "assigned_quantity": entry["assigned_quantity"],
            "returned_quantity": entry["returned_quantity"],
            "assigned_notional": entry["assigned_notional"],
            "total_notional": entry["total_notional"],
            "avg_assignment_price": assigned_avg_price,
            "avg_assigned_expiry": avg_assigned_expiry,
            "avg_returned_expiry": avg_returned_expiry,
            "premium_total": entry["premium_total"],
        })

    asset_outcome_list.sort(key=lambda x: (-x["assigned_count"], -x["returned_count"], x["symbol"]))

    results = {
        "trades": [],
        "expired_positions": expired_sorted if expired_limit is None else expired_sorted[:expired_limit],
        "summary": {
            "expired_count": len(expired_positions),
            "net_premium": expired_premium_total,
            "total_notional": expired_notional_total,
            "assigned_count": total_assigned_positions,
            "unknown_count": total_unknown_positions,
            "assigned_notional_total": total_assigned_notional,
            "returned_count": total_returned_positions,
            "returned_quantity_total": total_returned_quantity,
            "asset_outcomes": asset_outcome_list,
        }
    }

    _history_cache[address_key] = {
        "timestamp": time.time(),
        "data": results
    }
    return results

