"""Analytics privacy boundaries and network-free health/freshness semantics."""
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from flask import Flask, render_template

from db import init_db
from observability import analytics_config, collection_status, register_observability

TOKEN = 'a' * 32
NOW = 1_800_000_000


class ObservabilityTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'test.db'
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        init_db(self.conn)

    def tearDown(self):
        self.conn.close()
        self.temp.cleanup()

    def create_app(self, path=None):
        app = Flask(__name__, template_folder=str(Path(__file__).resolve().parents[1] / 'templates'))
        with patch.dict(os.environ, {'PUBLIC_BASE_URL': 'https://rysk.example', 'CF_WEB_ANALYTICS_TOKEN': TOKEN}):
            register_observability(app, database_path=path or self.path)
        for index, route in enumerate(('/', '/analytics', '/docs', '/account', '/trader/<trader_id>')):
            app.add_url_rule(route, f'page_{index}', lambda **kwargs: render_template('partials/head.html'))
        return app

    def test_configuration_is_explicit_validated_and_public_only(self):
        self.assertIsNone(analytics_config({}))
        self.assertIsNone(analytics_config({'PUBLIC_BASE_URL': 'https://rysk.example'}))
        for origin in ('http://rysk.example', 'https://localhost', 'https://127.0.0.1',
                       'https://user:password@rysk.example', 'https://rysk.example/path',
                       'https://rysk.example?wallet=123', 'https://rysk.example/#private',
                       'https://rysk.example:3000', 'https://app.localhost'):
            with self.subTest(origin=origin):
                self.assertIsNone(analytics_config({'PUBLIC_BASE_URL': origin, 'CF_WEB_ANALYTICS_TOKEN': TOKEN}))
        self.assertIsNone(analytics_config({'PUBLIC_BASE_URL': 'https://rysk.example', 'CF_WEB_ANALYTICS_TOKEN': 'not-a-token'}))
        self.assertEqual(analytics_config({'PUBLIC_BASE_URL': 'https://rysk.example/', 'CF_WEB_ANALYTICS_TOKEN': TOKEN}),
                         {'token': TOKEN, 'origin': 'https://rysk.example'})

    def test_only_aggregate_pages_receive_beacon_configuration(self):
        client = self.create_app().test_client()
        for path in ('/', '/analytics'):
            self.assertIn(b'js/observability.js', client.get(path).data)
        for path in ('/account', '/trader/' + 'a' * 64, '/docs', '/?address=0xabc', '/analytics?chain=999'):
            with self.subTest(path=path):
                response = client.get(path)
                self.assertNotIn(b'js/observability.js', response.data)
                self.assertNotIn(TOKEN.encode(), response.data)
                self.assertEqual(response.headers['Referrer-Policy'], 'strict-origin')
                self.assertTrue(response.cache_control.no_transform)

    def test_readiness_does_not_call_upstream_or_require_recent_trading(self):
        client = self.create_app().test_client()
        with patch('socket.socket', side_effect=AssertionError('health must not call the network')):
            response = client.get('/healthz')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {'status': 'ok', 'database': 'ok'})
        self.assertEqual(response.headers['Cache-Control'], 'no-store')

    def test_missing_database_returns_503_without_creating_file_or_exposing_path(self):
        missing = Path(self.temp.name) / 'missing.db'
        client = self.create_app(missing).test_client()
        for route in ('/healthz', '/api/status'):
            response = client.get(route)
            self.assertEqual(response.status_code, 503)
            self.assertNotIn(self.temp.name, response.get_data(as_text=True))
        self.assertFalse(missing.exists())

    def test_fresh_collection_is_independent_of_age_of_last_trade(self):
        self.conn.execute("INSERT INTO sync_meta VALUES ('last_sync_ts', ?)", (str(NOW - 10),))
        self.conn.execute('''INSERT INTO trades
            (tx_hash,address,chain_id,created_at,is_buy,is_put,symbol,quantity,strike,
             price,premium,quantity_f,strike_f,premium_f,notional_f)
            VALUES ('hash','asset',999,?,1,0,'HYPE','1','1','1','1',1,1,1,1)''', (NOW - 86400,))
        status = collection_status(self.conn, now=NOW)
        self.assertEqual(status['status'], 'ok')
        self.assertEqual(status['history']['freshness'], 'current')
        self.assertEqual(status['history']['sync_age_seconds'], 10)
        self.assertEqual(status['history']['latest_trade_at'], NOW - 86400)
        self.assertEqual(status['history']['recorded_trades'], 1)

    def test_stale_unknown_corrupt_and_failed_sync_are_not_reported_as_live(self):
        self.assertEqual(collection_status(self.conn, NOW)['history']['freshness'], 'unknown')
        for value, expected in ((str(NOW - 3600), 'stale'), ('invalid', 'unknown'), (str(NOW + 3600), 'unknown')):
            self.conn.execute("INSERT OR REPLACE INTO sync_meta VALUES ('last_sync_ts', ?)", (value,))
            status = collection_status(self.conn, NOW)
            self.assertEqual(status['history']['freshness'], expected)
            self.assertEqual(status['status'], 'degraded')
        secret = 'private-wallet-or-upstream-error'
        self.conn.execute("INSERT OR REPLACE INTO sync_meta VALUES ('last_sync_ts', ?)", (str(NOW - 10),))
        self.conn.execute("INSERT OR REPLACE INTO sync_meta VALUES ('last_trade_audit_json', ?)",
                          (json.dumps({'complete': False, 'error': secret, 'extra_examples': [secret]}),))
        self.conn.commit()
        with patch('observability.time.time', return_value=NOW), patch('socket.socket', side_effect=AssertionError('no network')):
            response = self.create_app().test_client().get('/api/status')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['status'], 'degraded')
        self.assertFalse(response.json['history']['latest_sync_succeeded'])
        self.assertNotIn(secret, response.get_data(as_text=True))
        self.assertEqual(response.headers['Cache-Control'], 'no-store')


if __name__ == '__main__':
    unittest.main()
