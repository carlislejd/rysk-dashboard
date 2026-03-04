"""
Shared service helpers for dashboard API routes and CLI commands.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional

from positions_api import fetch_history, fetch_positions


ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")


def validate_account_address(address: str) -> str:
    normalized = (address or "").strip()
    if not ADDRESS_RE.match(normalized):
        raise ValueError("Invalid wallet address format")
    return normalized


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
