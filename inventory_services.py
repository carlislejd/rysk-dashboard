"""
Fetch and transform the live Rysk inventory (available options).
"""

import os
import requests

API_BASE = os.getenv("RYSK_API_BASE", "https://v12.rysk.finance/api")
INVENTORY_URL = f"{API_BASE}/inventory"


def fetch_inventory():
    """Fetch live inventory and return structured data per asset."""
    resp = requests.get(INVENTORY_URL, timeout=15)
    resp.raise_for_status()
    raw = resp.json()

    assets = []
    for asset_name, info in sorted(raw.items()):
        combinations = info.get("combinations", {})
        if not combinations:
            continue

        options = []
        index_price = None
        for combo in combinations.values():
            if index_price is None:
                index_price = combo.get("index")
            options.append({
                "strike": combo.get("strike"),
                "expiry": combo.get("expiration_timestamp"),
                "expiry_label": combo.get("expiry"),
                "is_put": combo.get("isPut", False),
                "delta": combo.get("delta", 0),
                "bid": combo.get("bid", 0),
                "ask": combo.get("ask", 0),
                "bid_iv": combo.get("bidIv", 0),
                "ask_iv": combo.get("askIv", 0),
                "apy": combo.get("apy", 0),
                "days_to_expiry": combo.get("timeToExpiryDays", 0),
                "index": combo.get("index"),
            })

        # Sort by expiry then strike
        options.sort(key=lambda o: (o["expiry"] or 0, o["strike"] or 0))

        put_count = sum(1 for o in options if o["is_put"])
        call_count = len(options) - put_count
        expiries = sorted(set(o["expiry"] for o in options if o["expiry"]))

        assets.append({
            "asset": asset_name,
            "index": index_price,
            "expiries": expiries,
            "total_options": len(options),
            "put_count": put_count,
            "call_count": call_count,
            "options": options,
        })

    return {"assets": assets}
