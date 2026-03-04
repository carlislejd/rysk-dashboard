"""
Flask application for Rysk Options Dashboard.
"""

from flask import Flask, render_template, jsonify, request
import os
from dashboard_services import (
    get_history_payload,
    get_positions_payload,
    validate_account_address,
)

app = Flask(__name__)

# Configuration
ACCOUNT_ADDRESS = os.getenv("ACCOUNT_ADDRESS", "")


def resolve_account_address():
    """Return the requested account address or fall back to the default."""
    address = request.args.get("address", "").strip()
    if address:
        return validate_account_address(address)
    if ACCOUNT_ADDRESS:
        return validate_account_address(ACCOUNT_ADDRESS)
    raise ValueError("Wallet address required")


@app.route('/')
def index():
    """Main dashboard page"""
    return render_template('dashboard.html', account_address=ACCOUNT_ADDRESS)

@app.route('/api/positions')
def api_positions():
    """API endpoint for current positions"""
    try:
        account_address = resolve_account_address()
        return jsonify({
            "success": True,
            **get_positions_payload(account_address)
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
            **get_history_payload(account_address)
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

