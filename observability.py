"""Optional visitor analytics and local-only operational status.

Public status is intentionally aggregate: no wallet IDs, filesystem paths,
credentials, raw sync errors or upstream requests belong in these responses.
"""
import ipaddress
import json
import os
from pathlib import Path
import re
import sqlite3
import time
from urllib.parse import urlsplit

from flask import Blueprint, jsonify, request

import db

PUBLIC_ANALYTICS_PATHS = frozenset(('/', '/analytics'))
TOKEN_RE = re.compile(r'^[0-9a-f]{32}$', re.IGNORECASE)


def _public_origin(value):
    """Accept an explicit HTTPS production origin, never local/preview defaults."""
    try:
        url = urlsplit(value.strip())
        host = url.hostname or ''
        if (url.scheme != 'https' or url.username or url.password
                or url.path not in ('', '/') or url.query or url.fragment
                or not host or '.' not in host or host.endswith(('.localhost', '.local'))
                or url.port not in (None, 443)):
            return None
        try:
            ipaddress.ip_address(host)
            return None
        except ValueError:
            pass
        return 'https://' + host.lower()
    except (ValueError, AttributeError):
        return None


def analytics_config(environ=None):
    """Return only public beacon configuration; disabled unless both values exist."""
    environ = os.environ if environ is None else environ
    token = environ.get('CF_WEB_ANALYTICS_TOKEN', '').strip()
    origin = _public_origin(environ.get('PUBLIC_BASE_URL', ''))
    if not origin or not TOKEN_RE.fullmatch(token):
        return None
    return {'token': token, 'origin': origin}


def _read_only_database(path):
    # mode=ro fails if the database is missing instead of creating a healthy
    # looking empty database during a readiness probe.
    conn = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True, timeout=1)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA query_only=ON')
    return conn


def _timestamp(value, now):
    try:
        parsed = int(value)
        return parsed if 0 < parsed <= now + 60 else None
    except (ValueError, TypeError, OverflowError):
        return None


def _sync_interval():
    try:
        return max(1, int(os.getenv('RYSK_SYNC_INTERVAL', '600')))
    except ValueError:
        return 600


def collection_status(conn, now=None):
    """Summarize persisted collection progress separately from last trade time."""
    now = int(time.time()) if now is None else int(now)
    rows = dict(conn.execute(
        "SELECT key,value FROM sync_meta WHERE key IN ('last_sync_ts','last_trade_audit_json')"
    ).fetchall())
    aggregate = conn.execute(
        'SELECT COUNT(*) AS count, MAX(created_at) AS latest FROM trades'
    ).fetchone()
    through = _timestamp(rows.get('last_sync_ts'), now)
    latest = _timestamp(aggregate['latest'], now)
    latest_succeeded = None
    try:
        audit = json.loads(rows.get('last_trade_audit_json', 'null'))
        if isinstance(audit, dict) and isinstance(audit.get('complete'), bool):
            latest_succeeded = audit['complete']
    except (TypeError, ValueError):
        pass
    interval = _sync_interval()
    stale_after = max(1800, interval * 3)
    age = max(0, now - through) if through is not None else None
    freshness = 'unknown' if age is None else ('stale' if age > stale_after else 'current')
    return {
        'success': True,
        'status': 'ok' if freshness == 'current' and latest_succeeded is not False else 'degraded',
        'checked_at': now,
        'database': 'ok',
        'history': {
            'recorded_trades': aggregate['count'],
            'latest_trade_at': latest,
            'synced_through': through,
            'sync_age_seconds': age,
            'freshness': freshness,
            'latest_sync_succeeded': latest_succeeded,
            'sync_interval_seconds': interval,
            'stale_after_seconds': stale_after,
        },
    }


def register_observability(app, database_path=None):
    """Register once after app initialization. Does not start threads or network IO."""
    config = analytics_config()
    blueprint = Blueprint('observability', __name__)

    def connect():
        return _read_only_database(database_path or db.DB_PATH)

    @app.context_processor
    def inject_analytics():
        # Excluding complete pages also excludes their DOM and resource timing
        # data. Docs can run wallet API requests, so they are private here too.
        eligible = request.path in PUBLIC_ANALYTICS_PATHS and not request.query_string
        return {'web_analytics': config if eligible else None}

    @app.after_request
    def analytics_privacy_headers(response):
        # Even same-origin navigation from a wallet page must not carry its
        # wallet-bearing URL into a later page's document.referrer.
        response.headers['Referrer-Policy'] = 'strict-origin'
        if response.mimetype == 'text/html':
            # Prevent a Cloudflare proxy's automatic beacon injection from
            # bypassing the route exclusions; use manual installation only.
            response.cache_control.no_transform = True
        return response

    @blueprint.get('/healthz')
    def health():
        conn = None
        try:
            conn = connect()
            conn.execute('SELECT 1 FROM trades LIMIT 1').fetchone()
            conn.execute('SELECT 1 FROM sync_meta LIMIT 1').fetchone()
            payload, code = {'status': 'ok', 'database': 'ok'}, 200
        except (sqlite3.Error, OSError, ValueError):
            payload, code = {'status': 'unavailable', 'database': 'unavailable'}, 503
        finally:
            if conn is not None:
                conn.close()
        response = jsonify(payload)
        response.headers['Cache-Control'] = 'no-store'
        return response, code

    @blueprint.get('/api/status')
    def status():
        conn = None
        try:
            conn = connect()
            payload, code = collection_status(conn), 200
        except (sqlite3.Error, OSError, ValueError):
            payload, code = {
                'success': False, 'status': 'unavailable', 'database': 'unavailable',
                'checked_at': int(time.time()), 'history': None,
            }, 503
        finally:
            if conn is not None:
                conn.close()
        response = jsonify(payload)
        response.headers['Cache-Control'] = 'no-store'
        return response, code

    app.register_blueprint(blueprint)
