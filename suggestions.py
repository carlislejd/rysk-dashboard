"""
Suggestion engine for Rysk covered calls
Recommends options based on balances and 25% APR goal
"""

from inventory_api import fetch_inventory, get_call_options
from rpc_client import get_all_balances
from pricing_analysis import analyze_option

# Target APR
TARGET_APR = 25.0

# Expected APR ranges by asset (for portfolio balancing)
ASSET_APR_RANGES = {
    "BTC": (18, 25),      # Lower APR expected (preserves capital)
    "ETH": (30, 40),      # Higher APR
    "HYPE": (24, 35),     # Medium-high APR
    "SOL": (30, 40),      # Higher APR
    "PUMP": (30, 40),    # Higher APR
    "PURR": (25, 35),    # Medium-high APR
}

def get_suggestions(account_address: str, max_suggestions_per_asset: int = 3):
    """
    Get suggested options based on balances and 25% APR goal
    
    Args:
        account_address: Account address to check balances
        max_suggestions_per_asset: Max suggestions per asset
    
    Returns:
        Dictionary of asset -> list of suggested options
    """
    # Get current balances
    balances = get_all_balances(account_address)
    
    # Filter to assets with non-zero balances
    assets_with_balance = {asset: bal for asset, bal in balances.items() if bal > 0.001}
    
    if not assets_with_balance:
        return {}
    
    # Get inventory
    inventory_data = fetch_inventory()
    if not inventory_data:
        return {}
    
    suggestions = {}
    
    for asset, balance in assets_with_balance.items():
        if asset not in inventory_data:
            continue
        
        # Get all options for this asset
        all_options = get_call_options(inventory_data, asset, max_assignment_risk=25.0)
        
        if not all_options:
            continue
        
        # Get target APR range for this asset
        target_min, target_max = ASSET_APR_RANGES.get(asset, (20, 35))
        
        # Filter options within target range
        target_options = [
            opt for opt in all_options
            if target_min <= opt["apy"] <= target_max
        ]
        
        # If no options in exact range, get closest ones
        if not target_options:
            # Sort by how close to target range
            target_mid = (target_min + target_max) / 2
            all_options.sort(key=lambda x: abs(x["apy"] - target_mid))
            target_options = all_options[:max_suggestions_per_asset]
        else:
            # Sort by APY (highest first) and take top N
            target_options.sort(key=lambda x: -x["apy"])
            target_options = target_options[:max_suggestions_per_asset]
        
        if target_options:
            # Get current price for analysis
            asset_data = inventory_data[asset]
            combinations = asset_data.get("combinations", {})
            current_price = 0
            for combo_data in combinations.values():
                index = combo_data.get("index", 0)
                if index > 0:
                    current_price = index
                    break
            
            # Analyze each option
            analyzed_options = []
            for opt in target_options:
                analyzed_opt = analyze_option(opt, asset, current_price)
                analyzed_options.append(analyzed_opt)
            
            suggestions[asset] = {
                "balance": balance,
                "options": analyzed_options,
                "target_range": f"{target_min}-{target_max}%",
                "current_price": current_price
            }
    
    return suggestions

def calculate_portfolio_impact(current_positions_apr: float, new_suggestion: dict):
    """
    Calculate how a suggestion would impact portfolio average APR
    
    Args:
        current_positions_apr: Current average APR of existing positions
        new_suggestion: Suggested option with APY
    
    Returns:
        Estimated new portfolio APR
    """
    # Simplified calculation (would need actual position counts for accuracy)
    # This is a rough estimate
    if current_positions_apr == 0:
        return new_suggestion["apy"]
    
    # Weighted average (assuming equal weight for simplicity)
    return (current_positions_apr + new_suggestion["apy"]) / 2

