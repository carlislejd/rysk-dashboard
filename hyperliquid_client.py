"""
Hyperliquid API Client
Fetches current market prices.
"""

from hyperliquid.info import Info
import requests
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
_HYPERLIQUID_BASE_URL = "https://api.hyperliquid.xyz"


class MinimalPerpInfo:
    """Small fallback for perp mids when SDK Info initialization fails."""

    def __init__(self, base_url=_HYPERLIQUID_BASE_URL):
        self.base_url = base_url.rstrip("/")

    def all_mids(self):
        response = requests.post(
            f"{self.base_url}/info",
            json={"type": "allMids"},
            timeout=10,
        )
        response.raise_for_status()
        return response.json()

def get_hyperliquid_api():
    """Get or create Hyperliquid API instance"""
    global _api_instance
    if _api_instance is None:
        try:
            _api_instance = Info(base_url=_HYPERLIQUID_BASE_URL, skip_ws=True)
        except IndexError as e:
            print(f"Hyperliquid SDK init failed; falling back to perp-only HTTP client: {e}")
            _api_instance = MinimalPerpInfo()
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
