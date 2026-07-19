"""
Flask application for Rysk Options Dashboard.
"""

from flask import Flask, render_template, jsonify, request
import os
from analytics_services import get_analytics_overview, get_otm_apr_surface
from chain_metadata import parse_chain_filter
from dashboard_services import (
    build_assignment_backtest,
    build_history_expiry_prices,
    build_history_deep_dive,
    build_positions_expiring,
    filter_expired_positions,
    filter_open_positions,
    get_history_payload,
    get_history_payload_for_accounts,
    get_positions_payload,
    get_positions_payload_for_accounts,
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
    get_expiry_overview,
    enrich_trades_with_iv,
    get_put_call_ratio_over_time,
    get_assignment_rate_trend,
    get_market_pulse,
    get_premium_over_time,
    get_next_expiry_top_positions,
)
from inventory_services import fetch_inventory
from hyperliquid_client import get_current_price
from risk_gate_services import build_clearance_board
from scripts.backfill_outcomes import backfill_outcomes
from volatility_services import get_asset_volatility, get_hype_volatility

app = Flask(__name__)

# Configuration
ACCOUNT_ADDRESS = os.getenv("ACCOUNT_ADDRESS", "")
ADMIN_BACKFILL_TOKEN = os.getenv("ADMIN_BACKFILL_TOKEN", "")

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


def resolve_account_addresses():
    """Return one or more unique dashboard wallet addresses."""
    raw_values = request.args.getlist("address")
    raw = ",".join(raw_values).strip()
    if not raw and ACCOUNT_ADDRESS:
        raw = ACCOUNT_ADDRESS
    candidates = [part.strip() for part in raw.replace("\n", ",").split(",") if part.strip()]
    if not candidates:
        raise ValueError("Wallet address required")
    if len(candidates) > 10:
        raise ValueError("A maximum of 10 wallet addresses is supported")
    addresses = []
    seen = set()
    for candidate in candidates:
        validated = validate_account_address(candidate)
        if validated.lower() not in seen:
            addresses.append(validated)
            seen.add(validated.lower())
    return addresses


def resolve_chain_filter():
    """Return the requested chain id, or None for all chains."""
    value = request.args.get("chain_id", None)
    if value is None:
        value = request.args.get("chain", None)
    return parse_chain_filter(value)


@app.route('/')
def index():
    """Global dashboard — aggregate protocol activity"""
    return render_template('global.html')

@app.route('/account')
def account():
    """Per-wallet dashboard"""
    return render_template('dashboard.html', account_address=ACCOUNT_ADDRESS)


@app.route('/analytics')
def analytics():
    """Protocol research desk."""
    return render_template('analytics.html')


@app.route('/docs')
def docs():
    """Documentation for CLI and hosted endpoints."""
    configured_base = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
    api_base = configured_base or request.host_url.rstrip("/")
    return render_template(
        'docs.html',
        api_base=api_base,
        sample_address=os.getenv("DOCS_SAMPLE_ADDRESS", ACCOUNT_ADDRESS or ""),
    )


@app.route('/api/positions')
def api_positions():
    """API endpoint for current positions."""
    try:
        account_addresses = resolve_account_addresses()
        payload = (get_positions_payload(account_addresses[0]) if len(account_addresses) == 1
                   else get_positions_payload_for_accounts(account_addresses))
        payload["accounts"] = account_addresses
        return jsonify({"success": True, **payload})
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


@app.route('/api/cli/account/validate')
def api_cli_account_validate():
    """CLI-shaped endpoint for address validation."""
    try:
        account_address = resolve_account_address()
        return jsonify({
            "success": True,
            "ok": True,
            "address": account_address,
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


@app.route('/api/cli/positions/open')
def api_cli_positions_open():
    """CLI-shaped endpoint for open positions."""
    try:
        account_address = resolve_account_address()
        symbol = request.args.get("symbol", "").strip() or None
        strategy = request.args.get("strategy", "").strip() or None

        payload = get_positions_payload(account_address)
        open_positions = payload["positions"].get("open_positions") or []
        filtered = filter_open_positions(open_positions, symbol=symbol, strategy=strategy)
        return jsonify({
            "success": True,
            "account": account_address,
            "count": len(filtered),
            "filters": {"symbol": symbol, "strategy": strategy},
            "open_positions": filtered,
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


@app.route('/api/cli/positions/strikes')
def api_cli_positions_strikes():
    """CLI-shaped endpoint for strikes by asset."""
    try:
        account_address = resolve_account_address()
        symbol = request.args.get("symbol", "").strip() or None

        payload = get_positions_payload(account_address)
        asset_summary = payload["positions"].get("asset_summary") or []
        if symbol:
            wanted = symbol.upper()
            asset_summary = [a for a in asset_summary if (a.get("symbol") or "").upper() == wanted]

        result_assets = []
        for asset in asset_summary:
            result_assets.append(
                {
                    "symbol": asset.get("symbol"),
                    "current_price": asset.get("current_price"),
                    "strikes": asset.get("strikes") or [],
                }
            )

        return jsonify({
            "success": True,
            "account": account_address,
            "assets": result_assets,
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
    """API endpoint for historical performance."""
    try:
        account_addresses = resolve_account_addresses()
        payload = (get_history_payload(account_addresses[0]) if len(account_addresses) == 1
                   else get_history_payload_for_accounts(account_addresses))
        payload["accounts"] = account_addresses
        return jsonify({"success": True, **payload})
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

@app.route('/api/cli/positions/expiring')
def api_cli_positions_expiring():
    """CLI-shaped endpoint for expiring open position notional."""
    try:
        account_address = resolve_account_address()
        expiry_date = request.args.get("expiry_date", "").strip()
        if not expiry_date:
            raise ValueError("expiry_date query param is required (YYYY-MM-DD)")
        symbol = request.args.get("symbol", "").strip() or None
        strategy = request.args.get("strategy", "").strip() or None
        chain_id = resolve_chain_filter()

        payload = get_positions_payload(account_address)
        open_positions = payload["positions"].get("open_positions") or []
        result = build_positions_expiring(
            open_positions,
            expiry_date=expiry_date,
            symbol=symbol,
            strategy=strategy,
            chain_id=chain_id,
        )
        return jsonify({
            "success": True,
            "account": account_address,
            **result,
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


@app.route('/api/cli/history/expiry-prices')
def api_cli_history_expiry_prices():
    """CLI-shaped endpoint for realized expiry prices."""
    try:
        account_address = resolve_account_address()
        symbol = request.args.get("symbol", "").strip() or None
        expiry_date = request.args.get("expiry_date", "").strip() or None
        chain_id = resolve_chain_filter()

        payload = get_history_payload(account_address)
        expired_positions = payload["history"].get("expired_positions") or []
        result = build_history_expiry_prices(
            expired_positions,
            symbol=symbol,
            expiry_date=expiry_date,
            chain_id=chain_id,
        )
        return jsonify({
            "success": True,
            "account": account_address,
            **result,
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


@app.route('/api/cli/history/summary')
def api_cli_history_summary():
    """CLI-shaped endpoint for history summary."""
    try:
        account_address = resolve_account_address()
        payload = get_history_payload(account_address)
        summary = dict(payload["history"].get("summary") or {})
        summary.pop("unknown_count", None)
        return jsonify({
            "success": True,
            "account": account_address,
            "summary": summary,
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


@app.route('/api/cli/history/expired')
def api_cli_history_expired():
    """CLI-shaped endpoint for filtered expired positions."""
    try:
        account_address = resolve_account_address()
        symbol = request.args.get("symbol", "").strip() or None
        outcome = request.args.get("outcome", "").strip() or None

        payload = get_history_payload(account_address)
        expired_positions = payload["history"].get("expired_positions") or []
        filtered = filter_expired_positions(expired_positions, symbol=symbol, outcome=outcome)
        return jsonify({
            "success": True,
            "account": account_address,
            "count": len(filtered),
            "filters": {"symbol": symbol, "outcome": outcome},
            "expired_positions": filtered,
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


@app.route('/api/cli/history/deep-dive')
def api_cli_history_deep_dive():
    """CLI-shaped endpoint for deep-dive history analytics."""
    try:
        account_address = resolve_account_address()
        symbol = request.args.get("symbol", "").strip() or None

        payload = get_history_payload(account_address)
        deep_dive = build_history_deep_dive(payload["history"], symbol=symbol)
        return jsonify({
            "success": True,
            "account": account_address,
            "symbol": symbol,
            "deep_dive": deep_dive,
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


@app.route('/api/cli/history/assignment-backtest')
def api_cli_history_assignment_backtest():
    """CLI-shaped endpoint for assignment-avoidance backtesting."""
    try:
        account_address = resolve_account_address()
        symbol = request.args.get("symbol", "").strip() or None
        strategy = request.args.get("strategy", "").strip() or None
        min_premium_retained = request.args.get("min_premium_retained", 70.0, type=float)
        include_hype_vol = request.args.get("include_hype_vol", "").lower() in ("1", "true", "yes")
        hype_vol_days = request.args.get("hype_vol_days", 730, type=int)

        payload = get_history_payload(account_address)
        volatility_points = None
        if include_hype_vol:
            volatility_points = get_hype_volatility(days=hype_vol_days).get("series") or []
        backtest = build_assignment_backtest(
            payload["history"],
            symbol=symbol,
            strategy=strategy,
            min_premium_retained_pct=min_premium_retained,
            volatility_points=volatility_points,
        )
        return jsonify({
            "success": True,
            "account": account_address,
            "symbol": symbol,
            "strategy": strategy,
            "assignment_backtest": backtest,
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


@app.route('/api/global/hype-volatility')
def api_global_hype_volatility():
    """HYPE realized volatility index from daily Hyperliquid candles."""
    try:
        days = request.args.get("days", 365, type=int)
        data = get_hype_volatility(days=days)
        return jsonify({"success": True, **data})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/global/volatility')
def api_global_volatility():
    """Realized volatility index for a Hyperliquid asset."""
    try:
        asset = request.args.get("asset", "HYPE").strip().upper() or "HYPE"
        days = request.args.get("days", 365, type=int)
        data = get_asset_volatility(asset=asset, days=days)
        return jsonify({"success": True, **data})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/analytics/overview')
def api_analytics_overview():
    """Time-series, tenor, efficiency, and outcome research datasets."""
    try:
        days = request.args.get("days", 365, type=int)
        chain_id = resolve_chain_filter()
        conn = get_db()
        try:
            data = get_analytics_overview(conn, days=days, chain_id=chain_id)
        finally:
            conn.close()
        return jsonify({"success": True, **data})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/analytics/otm-apr')
def api_analytics_otm_apr():
    """Historical APR by strike distance from the prior daily close."""
    try:
        asset = request.args.get("asset", "HYPE").strip().upper() or "HYPE"
        days = request.args.get("days", 365, type=int)
        option_type = request.args.get("option_type", "call").strip().lower() or "call"
        dte_min = request.args.get("dte_min", None, type=float)
        dte_max = request.args.get("dte_max", None, type=float)
        chain_id = resolve_chain_filter()
        conn = get_db()
        try:
            data = get_otm_apr_surface(
                conn,
                asset=asset,
                days=days,
                option_type=option_type,
                dte_min=dte_min,
                dte_max=dte_max,
                chain_id=chain_id,
            )
        finally:
            conn.close()
        return jsonify({"success": True, **data})
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/strategy/clearance')
def api_strategy_clearance():
    """Pre-trade clearance board for CC/CSP entries."""
    try:
        assets_raw = request.args.get("assets", "HYPE,BTC")
        assets = [a.strip().upper() for a in assets_raw.split(",") if a.strip()]
        strategy = request.args.get("strategy", "").strip().lower() or None
        strategies = [strategy] if strategy else None
        target_dte = request.args.get("target_dte", None, type=float)
        days = request.args.get("days", 180, type=int)
        data = build_clearance_board(
            assets=assets or ["HYPE", "BTC"],
            strategies=strategies,
            target_dte=target_dte,
            days=days,
        )
        return jsonify({"success": True, **data})
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/global/summary')
def api_global_summary():
    """Aggregate protocol stats"""
    try:
        days = request.args.get("days", 0, type=int)
        chain_id = resolve_chain_filter()
        conn = get_db()
        try:
            data = get_global_summary(conn, days=days, chain_id=chain_id)
        finally:
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
        expiry = request.args.get("expiry", None, type=int)
        chain_id = resolve_chain_filter()
        iv = request.args.get("iv", "").lower() in ("1", "true")
        conn = get_db()
        try:
            data = get_global_trades(conn, page=page, limit=limit, symbol=symbol, expiry=expiry, chain_id=chain_id)
        finally:
            conn.close()
        if iv:
            enrich_trades_with_iv(data["trades"])
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
        expiry = request.args.get("expiry", None, type=int)
        chain_id = resolve_chain_filter()
        conn = get_db()
        try:
            data = get_global_volume(conn, interval=interval, symbol=symbol, days=days, expiry=expiry, chain_id=chain_id)
        finally:
            conn.close()
        return jsonify({"success": True, **data})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/global/assets')
def api_global_assets():
    """Per-asset breakdown"""
    try:
        chain_id = resolve_chain_filter()
        conn = get_db()
        try:
            data = get_asset_summary(conn, chain_id=chain_id)
        finally:
            conn.close()
        return jsonify({"success": True, **data})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/global/asset/<symbol>')
def api_global_asset_detail(symbol):
    """Detailed data for a single asset: strikes, expiries, current price"""
    try:
        expiry = request.args.get("expiry", None, type=int)
        chain_id = resolve_chain_filter()
        conn = get_db()
        try:
            data = get_asset_detail(conn, symbol, expiry=expiry, chain_id=chain_id)
        finally:
            conn.close()
        # Fetch live price for the asset
        short = symbol.split('-')[0] if '-' in symbol else symbol
        current_price = get_current_price(short)
        data["current_price"] = current_price
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
        chain_id = resolve_chain_filter()
        conn = get_db()
        try:
            data = get_outcome_summary(conn, chain_id=chain_id)
        finally:
            conn.close()
        return jsonify({"success": True, **data})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/global/expiries')
def api_global_expiries():
    """Rich per-expiry overview stats"""
    try:
        chain_id = resolve_chain_filter()
        conn = get_db()
        try:
            data = get_expiry_overview(conn, chain_id=chain_id)
        finally:
            conn.close()
        return jsonify({"success": True, **data})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/global/put-call-ratio')
def api_global_put_call_ratio():
    """Put/Call ratio over time for trend analysis"""
    try:
        days = request.args.get("days", 90, type=int)
        symbol = request.args.get("symbol", "").strip() or None
        chain_id = resolve_chain_filter()
        conn = get_db()
        try:
            data = get_put_call_ratio_over_time(conn, days=days, symbol=symbol, chain_id=chain_id)
        finally:
            conn.close()
        return jsonify({"success": True, **data})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/global/assignment-trend')
def api_global_assignment_trend():
    """Assignment rate trend by expiry date"""
    try:
        chain_id = resolve_chain_filter()
        conn = get_db()
        try:
            data = get_assignment_rate_trend(conn, chain_id=chain_id)
        finally:
            conn.close()
        return jsonify({"success": True, **data})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/global/next-expiry-positions')
def api_global_next_expiry_positions():
    """Top positions by notional for the next upcoming expiry"""
    try:
        limit = request.args.get("limit", 5, type=int)
        chain_id = resolve_chain_filter()
        conn = get_db()
        try:
            data = get_next_expiry_top_positions(conn, limit=limit, chain_id=chain_id)
        finally:
            conn.close()
        return jsonify({"success": True, **data})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/global/market-pulse')
def api_global_market_pulse():
    """Market pulse: what's hot right now"""
    try:
        chain_id = resolve_chain_filter()
        conn = get_db()
        try:
            data = get_market_pulse(conn, chain_id=chain_id)
        finally:
            conn.close()
        return jsonify({"success": True, **data})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/global/premium-over-time')
def api_global_premium_over_time():
    """Cumulative premium collected over time (for global PnL view)"""
    try:
        days = request.args.get("days", 365, type=int)
        symbol = request.args.get("symbol", "").strip() or None
        chain_id = resolve_chain_filter()
        conn = get_db()
        try:
            data = get_premium_over_time(conn, days=days, symbol=symbol, chain_id=chain_id)
        finally:
            conn.close()
        return jsonify({"success": True, **data})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/admin/backfill-outcomes', methods=['POST'])
def api_admin_backfill_outcomes():
    """Protected admin endpoint to run outcome backfill on-demand."""
    try:
        if not ADMIN_BACKFILL_TOKEN:
            return jsonify({
                "success": False,
                "error": "ADMIN_BACKFILL_TOKEN is not configured"
            }), 503

        provided = (request.headers.get("X-Admin-Token") or "").strip()
        if not provided:
            auth = (request.headers.get("Authorization") or "").strip()
            if auth.lower().startswith("bearer "):
                provided = auth[7:].strip()

        if provided != ADMIN_BACKFILL_TOKEN:
            return jsonify({"success": False, "error": "Unauthorized"}), 401

        result = backfill_outcomes() or {}
        return jsonify({"success": True, **result})
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
