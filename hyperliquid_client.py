"""
Hyperliquid API Client
Fetches current market prices.
"""

from hyperliquid.info import Info
import time

# Asset name mapping (Rysk names -> Hyperliquid names)
ASSET_MAPPING = {
    # Direct matches
    "BTC": "BTC",
    "ETH": "ETH",
    "HYPE": "HYPE",
    "SOL": "SOL",
    "PUMP": "PUMP",
    "PURR": "PURR",
    "XRP": "XRP",
    "ZEC": "ZEC",
    # Wrapped / prefixed Rysk variants → Hyperliquid underlying
    "UBTC": "BTC",
    "UETH": "ETH",
    "USOL": "SOL",
    "UPUMP": "PUMP",
    "WHYPE": "HYPE",
    "KHYPE": "HYPE",
    "KHYPE-PT": "HYPE",
    "KHYPE-PT-19MAR26": "HYPE",
    "LHYPE": "HYPE",
    "WSTHYPE": "HYPE",
    "BZEC": "ZEC",
    "FXRP": "XRP",
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
