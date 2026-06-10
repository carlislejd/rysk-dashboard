"""
Realized volatility helpers for HYPE.

Volatility is annualized from daily log returns. A 7d value means the standard
deviation of the last seven daily returns multiplied by sqrt(365).
"""

from __future__ import annotations

import math
import time
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

import requests


HL_INFO_URL = "https://api.hyperliquid.xyz/info"
SECONDS_PER_DAY = 86400
_CACHE_TTL = 300
_asset_vol_cache: Dict[str, Dict[str, Any]] = {}


def _to_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _date_key_from_ms(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


def _stddev(values: List[float]) -> Optional[float]:
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    return math.sqrt(variance)


def compute_rolling_volatility(candles: Iterable[Dict[str, Any]], windows=(3, 7, 30)) -> List[Dict[str, Any]]:
    """Return daily close series with rolling annualized realized vol percentages."""
    cleaned = []
    for candle in candles or []:
        ts = candle.get("t")
        close = _to_float(candle.get("c"))
        if ts is None or close is None or close <= 0:
            continue
        cleaned.append({"ts": int(ts), "date": _date_key_from_ms(int(ts)), "close": close})

    cleaned.sort(key=lambda row: row["ts"])
    if not cleaned:
        return []

    returns: List[Optional[float]] = [None]
    for prev, curr in zip(cleaned, cleaned[1:]):
        returns.append(math.log(curr["close"] / prev["close"]))

    output = []
    for idx, row in enumerate(cleaned):
        item = dict(row)
        item["return"] = returns[idx]
        item["return_1d_pct"] = returns[idx] * 100.0 if returns[idx] is not None else None
        item["abs_return_1d_pct"] = abs(returns[idx]) * 100.0 if returns[idx] is not None else None
        return_3d_sample = [r for r in returns[max(1, idx - 2): idx + 1] if r is not None]
        item["return_3d_pct"] = sum(return_3d_sample) * 100.0 if len(return_3d_sample) == 3 else None
        item["abs_return_3d_pct"] = abs(item["return_3d_pct"]) if item["return_3d_pct"] is not None else None
        for window in windows:
            sample = [r for r in returns[max(1, idx - window + 1): idx + 1] if r is not None]
            sigma = _stddev(sample)
            item[f"rv_{window}d"] = sigma * math.sqrt(365) * 100.0 if sigma is not None else None
        output.append(item)
    return output


def fetch_asset_daily_candles(asset: str = "HYPE", days: int = 365) -> List[Dict[str, Any]]:
    """Fetch daily candles from Hyperliquid."""
    coin = (asset or "HYPE").upper()
    now_ms = int(time.time() * 1000)
    start_ms = now_ms - int((days + 35) * SECONDS_PER_DAY * 1000)
    response = requests.post(
        HL_INFO_URL,
        json={
            "type": "candleSnapshot",
            "req": {
                "coin": coin,
                "interval": "1d",
                "startTime": start_ms,
                "endTime": now_ms,
            },
        },
        timeout=10,
    )
    response.raise_for_status()
    data = response.json()
    return data if isinstance(data, list) else []


def fetch_hype_daily_candles(days: int = 365) -> List[Dict[str, Any]]:
    """Fetch daily HYPE candles from Hyperliquid."""
    return fetch_asset_daily_candles("HYPE", days=days)


def get_asset_volatility(asset: str = "HYPE", days: int = 365) -> Dict[str, Any]:
    """Return cached daily closes and 3d/7d/30d realized vol for an asset."""
    coin = (asset or "HYPE").upper()
    now = time.time()
    cache_entry = _asset_vol_cache.get(coin, {"timestamp": 0, "data": None, "days": None})
    cached = cache_entry.get("data")
    if cached is not None and cache_entry.get("days") == days and now - cache_entry["timestamp"] < _CACHE_TTL:
        return cached

    candles = fetch_asset_daily_candles(coin, days=days)
    series = compute_rolling_volatility(candles)
    if days > 0:
        series = series[-days:]

    latest = series[-1] if series else None
    result = {
        "asset": coin,
        "windows": [3, 7, 30],
        "days": days,
        "point_count": len(series),
        "latest": latest,
        "series": series,
    }
    _asset_vol_cache[coin] = {"timestamp": now, "data": result, "days": days}
    return result


def get_hype_volatility(days: int = 365) -> Dict[str, Any]:
    """Return cached HYPE daily closes and 3d/7d/30d realized vol."""
    return get_asset_volatility("HYPE", days=days)
