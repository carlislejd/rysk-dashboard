"""
Hyperliquid API Client
Fetches price history data for charting
"""

from hyperliquid.info import Info
from datetime import datetime, timedelta
import time

# Asset name mapping (Rysk names -> Hyperliquid names)
ASSET_MAPPING = {
    "BTC": "BTC",
    "ETH": "ETH",
    "HYPE": "HYPE",  # May need to check if this is correct
    "SOL": "SOL",
    "PUMP": "PUMP",  # May need to check if this is correct
    "PURR": "PURR",  # May need to check if this is correct
}

# Cache for API instance
_api_instance = None

# Cache all_mids result to avoid redundant full-fetch per asset
_mids_cache = {"data": None, "timestamp": 0}
_MIDS_CACHE_TTL = 30  # 30 seconds

def get_hyperliquid_api():
    """Get or create Hyperliquid API instance"""
    global _api_instance
    if _api_instance is None:
        _api_instance = Info(base_url="https://api.hyperliquid.xyz", skip_ws=True)
    return _api_instance

def get_price_history(asset: str, days: int = 7, interval: str = "1h"):
    """
    Get price history for an asset
    
    Args:
        asset: Asset name (BTC, ETH, etc.)
        days: Number of days of history to fetch
        interval: Candle interval (1h, 4h, 1d, etc.)
    
    Returns:
        List of candle data with timestamps and OHLCV
    """
    api = get_hyperliquid_api()
    
    # Map asset name
    hyperliquid_name = ASSET_MAPPING.get(asset.upper())
    if not hyperliquid_name:
        return None
    
    # Calculate time range
    end_time = int(time.time() * 1000)  # milliseconds
    start_time = int((time.time() - (days * 24 * 60 * 60)) * 1000)  # milliseconds
    
    try:
        candles = api.candles_snapshot(
            name=hyperliquid_name,
            interval=interval,
            startTime=start_time,
            endTime=end_time
        )
        
        # Format data for charting
        chart_data = []
        for candle in candles:
            chart_data.append({
                "time": datetime.fromtimestamp(candle["t"] / 1000),
                "open": float(candle["o"]),
                "high": float(candle["h"]),
                "low": float(candle["l"]),
                "close": float(candle["c"]),
                "volume": float(candle["v"])
            })
        
        return chart_data
    except Exception as e:
        print(f"Error fetching price history for {asset}: {e}")
        return None

def get_current_price(asset: str):
    """Get current price for an asset (cached to avoid redundant API calls)"""
    api = get_hyperliquid_api()

    hyperliquid_name = ASSET_MAPPING.get(asset.upper())
    if not hyperliquid_name:
        return None

    try:
        now = time.time()
        if _mids_cache["data"] is None or (now - _mids_cache["timestamp"]) >= _MIDS_CACHE_TTL:
            _mids_cache["data"] = api.all_mids()
            _mids_cache["timestamp"] = now

        mids = _mids_cache["data"]
        if hyperliquid_name in mids:
            return float(mids[hyperliquid_name])
        return None
    except Exception as e:
        print(f"Error fetching current price for {asset}: {e}")
        return None

