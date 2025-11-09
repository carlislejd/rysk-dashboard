"""
Rysk Inventory API Client
Fetches available options inventory from Rysk API
"""

import requests
from datetime import datetime
import time

API_URL = "https://v12.rysk.finance/api/inventory"

# Cache for inventory data
_inventory_cache = None
_cache_timestamp = 0
CACHE_TTL = 15  # Cache for 15 seconds

def fetch_inventory(use_cache=True):
    """
    Fetch inventory data from Rysk API with caching
    
    Args:
        use_cache: If True, use cached data if available and fresh
    
    Returns:
        Inventory data dictionary or None
    """
    global _inventory_cache, _cache_timestamp
    
    current_time = time.time()
    
    # Return cached data if still fresh
    if use_cache and _inventory_cache is not None:
        if current_time - _cache_timestamp < CACHE_TTL:
            return _inventory_cache
    
    # Fetch fresh data
    try:
        response = requests.get(API_URL, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        # Update cache
        _inventory_cache = data
        _cache_timestamp = current_time
        
        return data
    except Exception as e:
        print(f"Error fetching inventory: {e}")
        # Return stale cache if available, otherwise None
        if use_cache and _inventory_cache is not None:
            return _inventory_cache
        return None

def timestamp_to_date(ts):
    """Convert Unix timestamp to readable date"""
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")

def get_asset_inventory(data: dict, asset: str):
    """Get inventory for a specific asset"""
    if asset not in data:
        return None
    return data[asset]

def get_call_options(data: dict, asset: str, max_assignment_risk: float = 25.0):
    """
    Get CALL options for an asset with assignment risk filter
    
    Args:
        data: Full inventory data
        asset: Asset name (BTC, HYPE, etc.)
        max_assignment_risk: Maximum assignment risk percentage
    
    Returns:
        List of call option dictionaries
    """
    if asset not in data:
        return []
    
    asset_data = data[asset]
    combinations = asset_data.get("combinations", {})
    
    options = []
    for combo_key, combo_data in combinations.items():
        is_put = combo_data.get("isPut", False)
        if not is_put:  # Only CALL options for covered calls
            strike = combo_data.get("strike", 0)
            apy = combo_data.get("apy", 0)
            delta = combo_data.get("delta", 0)
            index = combo_data.get("index", 0)
            expiry_ts = combo_data.get("expiration_timestamp", 0)
            expiry_date = timestamp_to_date(expiry_ts)
            days_to_expiry = combo_data.get("timeToExpiryDays", 0)
            bid_iv = combo_data.get("bidIv", 0)
            ask_iv = combo_data.get("askIv", 0)
            
            if strike > 0 and index > 0:
                # Calculate assignment risk
                if abs(delta) > 0.001:
                    assignment_risk = abs(delta) * 100
                else:
                    # Estimate if delta not available
                    assignment_risk = estimate_assignment_probability(strike, index, days_to_expiry) * 100
                
                if assignment_risk < max_assignment_risk:
                    options.append({
                        "strike": strike,
                        "apy": apy,
                        "assignment_risk": assignment_risk,
                        "expiry": expiry_date,
                        "days_to_expiry": days_to_expiry,
                        "index": index,
                        "moneyness": (strike / index - 1) * 100,
                        "delta": delta,
                        "bid_iv": bid_iv,
                        "ask_iv": ask_iv,
                        "mid_iv": (bid_iv + ask_iv) / 2 if (bid_iv > 0 and ask_iv > 0) else 0
                    })
    
    return sorted(options, key=lambda x: x["apy"], reverse=True)

def estimate_assignment_probability(strike, current_price, days_to_expiry):
    """Estimate assignment probability when delta is not available"""
    if strike <= 0 or current_price <= 0 or days_to_expiry <= 0:
        return 0.0
    
    moneyness = strike / current_price
    
    if moneyness < 1.0:
        if moneyness < 0.95:
            return 0.85
        return 0.70
    
    if moneyness > 1.20:
        return 0.05
    if moneyness > 1.15:
        return 0.08
    if moneyness > 1.10:
        return 0.12
    
    distance_from_atm = (moneyness - 1.0) * 100
    time_to_expiry = days_to_expiry / 365.0
    
    if distance_from_atm < 2:
        base_prob = 0.25 - (distance_from_atm * 0.05)
    elif distance_from_atm < 5:
        base_prob = 0.20 - ((distance_from_atm - 2) * 0.02)
    elif distance_from_atm < 10:
        base_prob = 0.15 - ((distance_from_atm - 5) * 0.01)
    else:
        base_prob = 0.10 - ((distance_from_atm - 10) * 0.01)
    
    if time_to_expiry < 0.03:
        time_factor = 0.9
    elif time_to_expiry < 0.06:
        time_factor = 1.0
    else:
        time_factor = 1.1
    
    estimated_prob = base_prob * time_factor
    return max(0.05, min(0.40, estimated_prob))

