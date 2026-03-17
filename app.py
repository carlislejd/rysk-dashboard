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
from db import get_db, init_db
from global_services import (
    get_global_summary,
    get_global_trades,
    get_global_volume,
    get_asset_summary,
    get_asset_detail,
    get_outcome_summary,
)
from inventory_services import fetch_inventory

app = Flask(__name__)

# Configuration
ACCOUNT_ADDRESS = os.getenv("ACCOUNT_ADDRESS", "")

# Initialize database on startup
with app.app_context():
    init_db()


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
    """Global dashboard — aggregate protocol activity"""
    return render_template('global.html')

@app.route('/account')
def account():
    """Per-wallet dashboard"""
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

@app.route('/api/global/summary')
def api_global_summary():
    """Aggregate protocol stats"""
    try:
        days = request.args.get("days", 0, type=int)
        conn = get_db()
        data = get_global_summary(conn, days=days)
        conn.close()
        return jsonify({"success": True, **data})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/global/trades')
def api_global_trades():
    """Paginated global trades feed"""
    try:
        page = request.args.get("page", 1, type=int)
        limit = request.args.get("limit", 50, type=int)
        symbol = request.args.get("symbol", "").strip() or None
        conn = get_db()
        data = get_global_trades(conn, page=page, limit=limit, symbol=symbol)
        conn.close()
        return jsonify({"success": True, **data})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/global/volume')
def api_global_volume():
    """Time-bucketed volume data for charts"""
    try:
        interval = request.args.get("interval", "day")
        symbol = request.args.get("symbol", "").strip() or None
        days = request.args.get("days", 30, type=int)
        conn = get_db()
        data = get_global_volume(conn, interval=interval, symbol=symbol, days=days)
        conn.close()
        return jsonify({"success": True, **data})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/global/assets')
def api_global_assets():
    """Per-asset breakdown"""
    try:
        conn = get_db()
        data = get_asset_summary(conn)
        conn.close()
        return jsonify({"success": True, **data})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/global/asset/<symbol>')
def api_global_asset_detail(symbol):
    """Detailed data for a single asset: strikes, expiries"""
    try:
        conn = get_db()
        data = get_asset_detail(conn, symbol)
        conn.close()
        return jsonify({"success": True, **data})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/global/inventory')
def api_global_inventory():
    """Live options inventory from Rysk"""
    try:
        data = fetch_inventory()
        return jsonify({"success": True, **data})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/global/outcomes')
def api_global_outcomes():
    """Outcome analysis for expired trades"""
    try:
        conn = get_db()
        data = get_outcome_summary(conn)
        conn.close()
        return jsonify({"success": True, **data})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

def _start_sync_thread():
    """Run trade sync in a background thread every 10 minutes."""
    import threading
    import time as _time
    from scripts.sync import sync as run_sync

    interval = int(os.getenv("RYSK_SYNC_INTERVAL", "600"))  # 10 min default

    def _loop():
        while True:
            _time.sleep(interval)
            try:
                run_sync()
            except Exception as exc:
                print(f"Background sync error: {exc}")

    t = threading.Thread(target=_loop, daemon=True)
    t.start()
    print(f"Background sync thread started (every {interval}s)")


# Start background sync in production (gunicorn), skip in dev reloader
if not os.getenv("WERKZEUG_RUN_MAIN") and os.getenv("RYSK_SYNC_ENABLED", "").lower() in ("1", "true", "yes"):
    _start_sync_thread()

if __name__ == '__main__':
    port = int(os.getenv("PORT", "5001"))
    app.run(debug=True, host='0.0.0.0', port=port)
