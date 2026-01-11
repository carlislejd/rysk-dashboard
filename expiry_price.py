"""
Expiry price oracle client for Rysk covered call analysis.

Provides cached access to the getExpiryPrice(view) function exposed by the
HyperEVM contract so we can determine whether a position finished in-the-money
or out-of-the-money at expiry.
"""

import os
import time
import json
from typing import Optional, Tuple

from web3 import Web3

from rpc_client import get_rpc_connection, TOKEN_ADDRESSES, HYPE_ADDRESSES


# Oracle contract (can be overridden via env for testing)
EXPIRY_ORACLE_ADDRESS = os.getenv(
    "RYSK_EXPIRY_ORACLE",
    "0x664aD80F6891cD663228Dc9d1510a6A5Db57e815"
)

# ABI fragment for getExpiryPrice(address underlying, uint256 expiry)
GET_EXPIRY_PRICE_ABI = [{
    "name": "getExpiryPrice",
    "type": "function",
    "stateMutability": "view",
    "inputs": [
        {"name": "underlying", "type": "address"},
        {"name": "expiry", "type": "uint256"}
    ],
    "outputs": [
        {"name": "price", "type": "uint256"},
        {"name": "isFinalized", "type": "bool"}
    ]
}]


# Mapping of Rysk symbols to underlying asset addresses used by the oracle
SYMBOL_ADDRESS_MAP = {
    "BTC": TOKEN_ADDRESSES.get("BTC"),
    "UBTC": TOKEN_ADDRESSES.get("BTC"),
    "ETH": TOKEN_ADDRESSES.get("ETH"),
    "UETH": TOKEN_ADDRESSES.get("ETH"),
    "SOL": TOKEN_ADDRESSES.get("SOL"),
    "USOL": TOKEN_ADDRESSES.get("SOL"),
    "PUMP": TOKEN_ADDRESSES.get("PUMP"),
    "UPUMP": TOKEN_ADDRESSES.get("PUMP"),
    "PURR": TOKEN_ADDRESSES.get("PURR"),
    "USDT0": TOKEN_ADDRESSES.get("USDT0"),
    "ZEC": TOKEN_ADDRESSES.get("ZEC"),
    "UZEC": TOKEN_ADDRESSES.get("ZEC"),
    "HYPE": HYPE_ADDRESSES[0] if HYPE_ADDRESSES else None,
    "WHYPE": HYPE_ADDRESSES[0] if HYPE_ADDRESSES else None,
    "KHYPE": HYPE_ADDRESSES[1] if len(HYPE_ADDRESSES) > 1 else None,
    "KHYPE-PT": HYPE_ADDRESSES[1] if len(HYPE_ADDRESSES) > 1 else None,
    "HYPE-PT": HYPE_ADDRESSES[0] if HYPE_ADDRESSES else None,
}


# Simple in-memory cache so we don't hammer the RPC for historical expiries
_expiry_cache = {}
EXPIRY_CACHE_TTL = int(os.getenv("RYSK_EXPIRY_CACHE_TTL", str(12 * 3600)))  # 12 hours

# Optional persistent cache on disk (JSON) to reuse expiry oracle lookups across runs
EXPIRY_CACHE_FILE = os.getenv("RYSK_EXPIRY_CACHE_FILE", "data/expiry_cache.json")

def _cache_key(address: str, expiry: int) -> str:
    return f"{(address or '').lower()}::{int(expiry)}"

def _load_persistent_cache():
    if not EXPIRY_CACHE_FILE:
        return
    try:
        if os.path.exists(EXPIRY_CACHE_FILE):
            with open(EXPIRY_CACHE_FILE, "r") as f:
                data = json.load(f)
            now = time.time()
            for key, entry in data.items():
                ts = entry.get("timestamp", 0)
                if now - ts < EXPIRY_CACHE_TTL:
                    _expiry_cache[key] = entry
    except Exception as exc:
        print(f"Warning: failed to load expiry cache file {EXPIRY_CACHE_FILE}: {exc}")

def _save_persistent_cache():
    if not EXPIRY_CACHE_FILE:
        return
    try:
        os.makedirs(os.path.dirname(EXPIRY_CACHE_FILE) or ".", exist_ok=True)
        # Keep only fresh entries when writing to disk
        now = time.time()
        data = {
            k: v for k, v in _expiry_cache.items()
            if (now - v.get("timestamp", 0)) < EXPIRY_CACHE_TTL
        }
        with open(EXPIRY_CACHE_FILE, "w") as f:
            json.dump(data, f)
    except Exception as exc:
        print(f"Warning: failed to save expiry cache file {EXPIRY_CACHE_FILE}: {exc}")

# Load persistent cache on module import
_load_persistent_cache()

_oracle_contract = None


def _get_oracle_contract():
    """Get (and cache) the oracle contract instance."""
    global _oracle_contract
    if _oracle_contract is None:
        w3 = get_rpc_connection()
        if not w3.is_connected():
            raise RuntimeError("Unable to reach Hyperliquid RPC for expiry oracle")
        _oracle_contract = w3.eth.contract(
            address=Web3.to_checksum_address(EXPIRY_ORACLE_ADDRESS),
            abi=GET_EXPIRY_PRICE_ABI
        )
    return _oracle_contract


def get_expiry_price(asset_address: str, expiry: int) -> Tuple[Optional[float], bool]:
    """Fetch the finalized expiry price from the oracle.

    Args:
        asset_address: Underlying ERC20 address used by the option series.
        expiry: Expiry timestamp (unix seconds).

    Returns:
        (price_in_usd, is_finalized) where price is a float (USD) if available.
    """
    if not asset_address or not expiry:
        return None, False

    cache_key = _cache_key(asset_address, expiry)
    cached = _expiry_cache.get(cache_key)
    if cached and (time.time() - cached["timestamp"] < EXPIRY_CACHE_TTL):
        return cached["price"], cached["finalized"]

    try:
        contract = _get_oracle_contract()
        price_raw, finalized = contract.functions.getExpiryPrice(
            Web3.to_checksum_address(asset_address),
            int(expiry)
        ).call()

        # Oracle returns prices scaled to 1e8
        price = float(price_raw) / 1e8 if price_raw else 0.0

        _expiry_cache[cache_key] = {
            "price": price,
            "finalized": bool(finalized),
            "timestamp": time.time()
        }
        _save_persistent_cache()

        return price, bool(finalized)
    except Exception as exc:
        print(f"Error fetching expiry price for {asset_address} @ {expiry}: {exc}")
        _expiry_cache[cache_key] = {
            "price": None,
            "finalized": False,
            "timestamp": time.time()
        }
        _save_persistent_cache()
        return None, False


def get_underlying_address(symbol: Optional[str]) -> Optional[str]:
    """Map a Rysk symbol (e.g. UBTC, kHYPE) to the underlying asset address."""
    if not symbol:
        return None
    symbol_upper = symbol.upper()
    if symbol_upper in SYMBOL_ADDRESS_MAP:
        return SYMBOL_ADDRESS_MAP[symbol_upper]

    # Handle prefixed symbols like "U" + base (UBTC) dynamically
    if symbol_upper.startswith("U") and symbol_upper[1:] in SYMBOL_ADDRESS_MAP:
        return SYMBOL_ADDRESS_MAP.get(symbol_upper[1:])

    return None
