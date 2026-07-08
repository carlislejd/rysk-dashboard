"""
Chain metadata and parsing helpers for Rysk multi-chain views.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional


HYPEREVM_CHAIN_ID = 999
ETHEREUM_CHAIN_ID = 1


CHAIN_METADATA: Dict[int, Dict[str, str]] = {
    HYPEREVM_CHAIN_ID: {
        "id": HYPEREVM_CHAIN_ID,
        "name": "HyperEVM",
        "slug": "hyperevm",
        "short_name": "HyperEVM",
    },
    ETHEREUM_CHAIN_ID: {
        "id": ETHEREUM_CHAIN_ID,
        "name": "Ethereum",
        "slug": "ethereum",
        "short_name": "ETH",
    },
}


CHAIN_ALIASES = {
    "hyper": HYPEREVM_CHAIN_ID,
    "hyperevm": HYPEREVM_CHAIN_ID,
    "hyper-evm": HYPEREVM_CHAIN_ID,
    "hyper_evm": HYPEREVM_CHAIN_ID,
    "hyperliquid": HYPEREVM_CHAIN_ID,
    "hyperliquid-evm": HYPEREVM_CHAIN_ID,
    "hl": HYPEREVM_CHAIN_ID,
    "999": HYPEREVM_CHAIN_ID,
    "eth": ETHEREUM_CHAIN_ID,
    "ethereum": ETHEREUM_CHAIN_ID,
    "ethereum-mainnet": ETHEREUM_CHAIN_ID,
    "mainnet": ETHEREUM_CHAIN_ID,
    "1": ETHEREUM_CHAIN_ID,
}


def parse_chain_id(value: Any, default: Optional[int] = None) -> Optional[int]:
    """Parse a chain id from an API/env/query value."""
    if value is None or value == "":
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)

    text = str(value).strip()
    if not text:
        return default
    lowered = text.lower()
    if lowered in CHAIN_ALIASES:
        return CHAIN_ALIASES[lowered]

    try:
        return int(text)
    except ValueError:
        return default


def parse_chain_filter(value: Any) -> Optional[int]:
    """Parse a chain filter; blank/all returns None."""
    text = str(value or "").strip().lower()
    if text in {"", "all", "any"}:
        return None
    chain_id = parse_chain_id(text)
    if chain_id is None:
        raise ValueError(f"Unsupported chain filter: {value}")
    return chain_id


def default_chain_id() -> int:
    return parse_chain_id(os.getenv("RYSK_DEFAULT_CHAIN_ID"), default=HYPEREVM_CHAIN_ID) or HYPEREVM_CHAIN_ID


def chain_meta(chain_id: Any) -> Dict[str, Any]:
    parsed = parse_chain_id(chain_id)
    if parsed in CHAIN_METADATA:
        return dict(CHAIN_METADATA[parsed])
    if parsed is None:
        return {
            "id": None,
            "name": "Unknown",
            "slug": "unknown",
            "short_name": "Unknown",
        }
    return {
        "id": parsed,
        "name": f"Chain {parsed}",
        "slug": f"chain-{parsed}",
        "short_name": str(parsed),
    }


def chain_fields(chain_id: Any) -> Dict[str, Any]:
    meta = chain_meta(chain_id)
    return {
        "chain_id": meta["id"],
        "chain_name": meta["name"],
        "chain_slug": meta["slug"],
        "chain_short_name": meta["short_name"],
    }
