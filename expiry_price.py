"""
Expiry price oracle client for Rysk option outcome analysis.

Provides cached access to the getExpiryPrice(view) function exposed by the
Rysk expiry oracle so we can determine whether a position finished
in-the-money or out-of-the-money at expiry.
"""

import os
import time
import json
from typing import Optional, Tuple

from web3 import Web3

from chain_metadata import ETHEREUM_CHAIN_ID, HYPEREVM_CHAIN_ID, chain_meta, default_chain_id, parse_chain_id
from rpc_client import (
    ETHEREUM_TOKEN_ADDRESSES,
    HYPE_ADDRESSES,
    TOKEN_ADDRESSES,
    get_rpc_connection,
)


# Expiry oracle contracts. RYSK_EXPIRY_ORACLE remains the backwards-compatible
# HyperEVM override. Ethereum is opt-in until Rysk publishes/updates docs.
HYPEREVM_EXPIRY_ORACLE_ADDRESS = os.getenv(
    "RYSK_HYPEREVM_EXPIRY_ORACLE",
    os.getenv("RYSK_EXPIRY_ORACLE", "0x664aD80F6891cD663228Dc9d1510a6A5Db57e815"),
)
ETHEREUM_EXPIRY_ORACLE_ADDRESS = os.getenv(
    "RYSK_ETHEREUM_EXPIRY_ORACLE",
    os.getenv("RYSK_MAINNET_EXPIRY_ORACLE", ""),
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


# Mapping of Rysk symbols to underlying asset addresses used by HyperEVM oracle
HYPEREVM_SYMBOL_ADDRESS_MAP = {
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
    "BZEC": TOKEN_ADDRESSES.get("ZEC"),
    "XRP": TOKEN_ADDRESSES.get("XRP"),
    "FXRP": TOKEN_ADDRESSES.get("XRP"),
    "HYPE": HYPE_ADDRESSES[0] if HYPE_ADDRESSES else None,
    "WHYPE": HYPE_ADDRESSES[0] if HYPE_ADDRESSES else None,
    "LHYPE": HYPE_ADDRESSES[0] if HYPE_ADDRESSES else None,
    "WSTHYPE": HYPE_ADDRESSES[0] if HYPE_ADDRESSES else None,
    "KHYPE": HYPE_ADDRESSES[1] if len(HYPE_ADDRESSES) > 1 else None,
    "KHYPE-PT": HYPE_ADDRESSES[1] if len(HYPE_ADDRESSES) > 1 else None,
    "KHYPE-PT-19MAR26": HYPE_ADDRESSES[1] if len(HYPE_ADDRESSES) > 1 else None,
    "HYPE-PT": HYPE_ADDRESSES[0] if HYPE_ADDRESSES else None,
}

ETHEREUM_SYMBOL_ADDRESS_MAP = {
    "BTC": ETHEREUM_TOKEN_ADDRESSES.get("BTC"),
    "WBTC": ETHEREUM_TOKEN_ADDRESSES.get("WBTC"),
    "UBTC": ETHEREUM_TOKEN_ADDRESSES.get("BTC"),
    "ETH": ETHEREUM_TOKEN_ADDRESSES.get("ETH"),
    "WETH": ETHEREUM_TOKEN_ADDRESSES.get("WETH"),
    "UETH": ETHEREUM_TOKEN_ADDRESSES.get("ETH"),
    "USDC": ETHEREUM_TOKEN_ADDRESSES.get("USDC"),
    "USDT": ETHEREUM_TOKEN_ADDRESSES.get("USDT"),
}

SYMBOL_ADDRESS_MAP = HYPEREVM_SYMBOL_ADDRESS_MAP


# Simple in-memory cache so we don't hammer the RPC for historical expiries
_expiry_cache = {}
EXPIRY_CACHE_TTL = int(os.getenv("RYSK_EXPIRY_CACHE_TTL", str(12 * 3600)))  # 12 hours
# Unfinalized or errored lookups must NOT be cached for 12 hours — a single
# rate-limited RPC burst would otherwise poison outcomes (and the premium
# totals derived from them) until the cache expires. Retry these quickly.
EXPIRY_NEG_CACHE_TTL = int(os.getenv("RYSK_EXPIRY_NEG_CACHE_TTL", "900"))  # 15 minutes

# Optional persistent cache on disk (JSON) to reuse expiry oracle lookups across runs
EXPIRY_CACHE_FILE = os.getenv("RYSK_EXPIRY_CACHE_FILE", "data/expiry_cache.json")

def _cache_key(address: str, expiry: int) -> str:
    return f"{(address or '').lower()}::{int(expiry)}"

def _entry_fresh(entry, now=None) -> bool:
    """Finalized prices live for the full TTL; everything else retries soon."""
    now = now if now is not None else time.time()
    ttl = EXPIRY_CACHE_TTL if entry.get("finalized") and entry.get("price") is not None else EXPIRY_NEG_CACHE_TTL
    return (now - entry.get("timestamp", 0)) < ttl

def _load_persistent_cache():
    if not EXPIRY_CACHE_FILE:
        return
    try:
        if os.path.exists(EXPIRY_CACHE_FILE):
            with open(EXPIRY_CACHE_FILE, "r") as f:
                data = json.load(f)
            now = time.time()
            for key, entry in data.items():
                if _entry_fresh(entry, now):
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
            if _entry_fresh(v, now)
        }
        with open(EXPIRY_CACHE_FILE, "w") as f:
            json.dump(data, f)
    except Exception as exc:
        print(f"Warning: failed to save expiry cache file {EXPIRY_CACHE_FILE}: {exc}")

# Load persistent cache on module import
_load_persistent_cache()

_oracle_contracts = {}


def _oracle_address_for_chain(chain_id: Optional[int]) -> Optional[str]:
    resolved = parse_chain_id(chain_id, default=default_chain_id()) or default_chain_id()
    if resolved == HYPEREVM_CHAIN_ID:
        return HYPEREVM_EXPIRY_ORACLE_ADDRESS
    if resolved == ETHEREUM_CHAIN_ID:
        return ETHEREUM_EXPIRY_ORACLE_ADDRESS
    return os.getenv(f"RYSK_CHAIN_{resolved}_EXPIRY_ORACLE", "")


def _get_oracle_contract(chain_id: Optional[int]):
    """Get (and cache) the oracle contract instance."""
    resolved = parse_chain_id(chain_id, default=default_chain_id()) or default_chain_id()
    oracle_address = _oracle_address_for_chain(resolved)
    if not oracle_address:
        meta = chain_meta(resolved)
        raise RuntimeError(f"No Rysk expiry oracle configured for {meta['name']}")

    if resolved not in _oracle_contracts:
        w3 = get_rpc_connection(resolved)
        if not w3.is_connected():
            meta = chain_meta(resolved)
            raise RuntimeError(f"Unable to reach {meta['name']} RPC for expiry oracle")
        _oracle_contracts[resolved] = w3.eth.contract(
            address=Web3.to_checksum_address(oracle_address),
            abi=GET_EXPIRY_PRICE_ABI
        )
    return _oracle_contracts[resolved]


def get_expiry_price(asset_address: str, expiry: int, chain_id: Optional[int] = None) -> Tuple[Optional[float], bool]:
    """Fetch the finalized expiry price from the oracle.

    Args:
        asset_address: Underlying ERC20 address used by the option series.
        expiry: Expiry timestamp (unix seconds).
        chain_id: EVM chain id for the expiry oracle.

    Returns:
        (price_in_usd, is_finalized) where price is a float (USD) if available.
    """
    if not asset_address or not expiry:
        return None, False

    resolved_chain_id = parse_chain_id(chain_id, default=default_chain_id()) or default_chain_id()
    cache_key = f"{resolved_chain_id}::{_cache_key(asset_address, expiry)}"
    cached = _expiry_cache.get(cache_key)
    if cached and _entry_fresh(cached):
        return cached["price"], cached["finalized"]

    try:
        contract = _get_oracle_contract(resolved_chain_id)
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
        meta = chain_meta(resolved_chain_id)
        print(f"Error fetching expiry price on {meta['name']} for {asset_address} @ {expiry}: {exc}")
        _expiry_cache[cache_key] = {
            "price": None,
            "finalized": False,
            "timestamp": time.time()
        }
        _save_persistent_cache()
        return None, False


def get_underlying_address(symbol: Optional[str], chain_id: Optional[int] = None) -> Optional[str]:
    """Map a Rysk symbol (e.g. UBTC, kHYPE) to the underlying asset address."""
    if not symbol:
        return None
    symbol_upper = symbol.upper()
    resolved_chain_id = parse_chain_id(chain_id, default=default_chain_id()) or default_chain_id()
    chain_map = ETHEREUM_SYMBOL_ADDRESS_MAP if resolved_chain_id == ETHEREUM_CHAIN_ID else HYPEREVM_SYMBOL_ADDRESS_MAP
    if symbol_upper in chain_map:
        return chain_map[symbol_upper]

    # Handle prefixed symbols like "U" + base (UBTC) dynamically
    if symbol_upper.startswith("U") and symbol_upper[1:] in chain_map:
        return chain_map.get(symbol_upper[1:])

    return None
