"""
Flask application for Rysk Covered Calls Dashboard
"""

from flask import Flask, render_template, jsonify, request
import os
from rpc_client import get_all_balances, TOKEN_ADDRESSES
from inventory_api import fetch_inventory, get_call_options
from positions_api import fetch_positions, fetch_history
from suggestions import get_suggestions
from hyperliquid_client import get_price_history

app = Flask(__name__)

# Configuration
ACCOUNT_ADDRESS = os.getenv("ACCOUNT_ADDRESS", "")


def resolve_account_address():
    """Return the requested account address or fall back to the default."""
    address = request.args.get("address", "").strip()
    if address:
        if not address.startswith("0x") or len(address) != 42:
            raise ValueError("Invalid wallet address format")
        return address
    if ACCOUNT_ADDRESS:
        return ACCOUNT_ADDRESS
    raise ValueError("Wallet address required")


@app.route('/')
def index():
    """Main dashboard page"""
    return render_template('dashboard.html', account_address=ACCOUNT_ADDRESS)

@app.route('/api/balances')
def api_balances():
    """API endpoint for token balances with prices and notional values"""
    try:
        account_address = resolve_account_address()
        balances = get_all_balances(account_address)
        
        # Get current prices from inventory API
        inventory_data = fetch_inventory()
        prices = {}
        if inventory_data:
            for asset in balances.keys():
                if asset in inventory_data:
                    asset_data = inventory_data[asset]
                    combinations = asset_data.get("combinations", {})
                    # Get first available index price
                    for combo_data in combinations.values():
                        index = combo_data.get("index", 0)
                        if index > 0:
                            prices[asset] = index
                            break
        
        # Calculate notional values
        notional = {}
        for asset, balance in balances.items():
            price = prices.get(asset, 0)
            notional[asset] = balance * price if price > 0 else 0

        # Fallback price for stable if missing
        if 'USDT0' in balances and prices.get('USDT0', 0) == 0:
            prices['USDT0'] = 1.0
            notional['USDT0'] = balances['USDT0'] * 1.0
        
        # Include token addresses
        addresses = {}
        for asset in balances.keys():
            if asset in TOKEN_ADDRESSES:
                addresses[asset] = TOKEN_ADDRESSES[asset]
        
        return jsonify({
            "success": True,
            "account": account_address,
            "balances": balances,
            "prices": prices,
            "notional": notional,
            "addresses": addresses
        })
    except ValueError as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 400
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route('/api/inventory')
def api_inventory():
    """API endpoint for available inventory"""
    try:
        inventory_data = fetch_inventory()
        if not inventory_data:
            return jsonify({
                "success": False,
                "error": "Failed to fetch inventory"
            }), 500
        
        # Get options for each asset
        inventory = {}
        for asset in ["BTC", "ETH", "HYPE", "SOL", "PUMP", "PURR"]:
            if asset in inventory_data:
                options = get_call_options(inventory_data, asset, max_assignment_risk=25.0)
                inventory[asset] = options
        
        return jsonify({
            "success": True,
            "inventory": inventory
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route('/api/positions')
def api_positions():
    """API endpoint for current positions"""
    try:
        account_address = resolve_account_address()
        return jsonify({
            "success": True,
            "account": account_address,
            "positions": fetch_positions(account_address)
        })
    except ValueError as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 400
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route('/api/history')
def api_history():
    """API endpoint for historical performance"""
    try:
        account_address = resolve_account_address()
        return jsonify({
            "success": True,
            "account": account_address,
            "history": fetch_history(account_address)
        })
    except ValueError as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 400
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route('/api/suggestions')
def api_suggestions():
    """API endpoint for suggested options based on balances and 25% APR goal"""
    try:
        account_address = resolve_account_address()
        suggestions = get_suggestions(account_address, max_suggestions_per_asset=3)
        return jsonify({
            "success": True,
            "target_apr": 25.0,
            "account": account_address,
            "suggestions": suggestions
        })
    except ValueError as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 400
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route('/api/chart')
def api_chart():
    """API endpoint for price chart data with strike prices"""
    try:
        asset = request.args.get('asset', '').upper()
        days = int(request.args.get('days', 7))
        account_address = resolve_account_address()
        
        if not asset:
            return jsonify({
                "success": False,
                "error": "Asset parameter required"
            }), 400
        
        # Get price history
        price_data = get_price_history(asset, days=days, interval="1h")
        
        if price_data is None:
            return jsonify({
                "success": False,
                "error": f"Failed to fetch price data for {asset}"
            }), 500
        
        # Get strike prices from suggestions
        strikes = []
        try:
            suggestions = get_suggestions(account_address, max_suggestions_per_asset=3)
            if asset in suggestions:
                for opt in suggestions[asset].get("options", []):
                    strikes.append({
                        "strike": opt["strike"],
                        "apy": opt["apy"],
                        "assignment_risk": opt["assignment_risk"],
                        "expiry": opt["expiry"]
                    })
        except:
            pass  # If suggestions fail, just show price chart
        
        # Format data for frontend
        chart_data = {
            "times": [candle["time"].isoformat() for candle in price_data],
            "opens": [candle["open"] for candle in price_data],
            "highs": [candle["high"] for candle in price_data],
            "lows": [candle["low"] for candle in price_data],
            "closes": [candle["close"] for candle in price_data],
            "volumes": [candle["volume"] for candle in price_data],
            "strikes": strikes
        }
        
        return jsonify({
            "success": True,
            "account": account_address,
            "asset": asset,
            "data": chart_data
        })
    except ValueError as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 400
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

if __name__ == '__main__':
    port = int(os.getenv("PORT", "5001"))
    app.run(debug=True, host='0.0.0.0', port=port)

