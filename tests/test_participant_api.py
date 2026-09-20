import json
import os
import tempfile
import unittest
from unittest.mock import patch

import app
from db import get_db, init_db
from participant_services import public_trader_identity


class TestParticipantAPI(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.directory.name, 'test.db')
        conn = get_db(self.path)
        init_db(conn)
        conn.close()
        self.db_patch = patch.object(app, 'get_db', side_effect=lambda: get_db(self.path))
        self.db_patch.start()
        self.client = app.app.test_client()

    def tearDown(self):
        self.db_patch.stop()
        self.directory.cleanup()

    def test_empty_database_is_a_valid_suppressed_response(self):
        response = self.client.get('/api/analytics/participants?days=0&chain_id=ethereum')
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(data['filters'], {'days': 0, 'chain_id': 1})
        self.assertEqual(data['leaderboards']['notional']['rows'], [])
        self.assertEqual(data['concentration']['status'], 'limited_history')
        self.assertEqual(data['coverage']['total_trades'], 0)
        for forbidden in ('wallet_count', 'participant_count', 'eligible_wallets', 'seller_wallet'):
            self.assertNotIn(forbidden, json.dumps(data))

    def test_default_window_and_alias_configuration_are_passed_to_service(self):
        with patch.object(app, 'get_participant_analytics', return_value={}) as service:
            with patch.object(app, 'PARTICIPANT_ALIAS_SECRET', 'test-only-secret'):
                response = self.client.get('/api/analytics/participants')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(service.call_args.kwargs['days'], 365)
        self.assertIsNone(service.call_args.kwargs['chain_id'])
        self.assertEqual(service.call_args.kwargs['alias_secret'], 'test-only-secret')

    def test_invalid_filter_inputs_are_client_errors(self):
        for query in ('days=-1', 'days=nope', 'days=1.5', 'days=36501', 'chain_id=invalid'):
            with self.subTest(query=query):
                response = self.client.get('/api/analytics/participants?' + query)
                self.assertEqual(response.status_code, 400)
                self.assertFalse(response.get_json()['success'])

    def test_unexpected_errors_do_not_echo_private_data(self):
        with patch.object(app, 'get_participant_analytics', side_effect=RuntimeError('private-wallet-data')):
            with self.assertLogs(app.app.logger, level='ERROR'):
                response = self.client.get('/api/analytics/participants')
        self.assertEqual(response.status_code, 500)
        self.assertNotIn('private-wallet-data', response.get_data(as_text=True))

    def test_global_identity_opens_matching_address_free_history(self):
        owner = '0x' + 'ab' * 20
        conn = get_db(self.path)
        conn.execute('''INSERT INTO trades
            (tx_hash,address,chain_id,created_at,expiry,is_buy,is_put,symbol,quantity,strike,
             price,premium,quantity_f,strike_f,premium_f,notional_f)
            VALUES ('hash','asset',1,1767225600,1768089600,0,0,'ETH','1','100','2','2',1,100,2,100)''')
        conn.execute('INSERT INTO trade_wallets VALUES (?,?,?,?,?,?)',
                     (1, 'hash', owner, 'verified_short_owner', None, 0))
        conn.commit()
        conn.close()
        with patch.object(app, 'PARTICIPANT_ALIAS_SECRET', 'test-only-secret'):
            global_data = self.client.get('/api/global/trades?chain_id=1').get_json()
            trade = global_data['trades'][0]
            identity = public_trader_identity(owner, 'test-only-secret')
            self.assertEqual(trade['trader_alias'], identity['alias'])
            self.assertEqual(trade['trader_id'], identity['trader_id'])
            response = self.client.get('/api/analytics/traders/' + trade['trader_id'])
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data['identity'], identity)
            self.assertEqual(data['totals']['trade_count'], 1)
            self.assertEqual(data['totals']['premium'], 2)
            self.assertNotIn(owner, response.get_data(as_text=True))
            self.assertNotIn('tx_hash', data['trades'][0])
            page = self.client.get('/trader/' + trade['trader_id'])
            self.assertEqual(page.status_code, 200)
            self.assertNotIn(owner, page.get_data(as_text=True))
            self.assertNotIn('wallet-input', page.get_data(as_text=True))

    def test_trader_route_rejects_invalid_inputs_without_exposing_identity(self):
        trader_id = 'a' * 64
        with patch.object(app, 'PARTICIPANT_ALIAS_SECRET', 'test-only-secret'):
            for query in ('days=-1', 'page=0', 'limit=101', 'days=xyz', 'chain_id=bogus'):
                response = self.client.get('/api/analytics/traders/' + trader_id + '?' + query)
                self.assertEqual(response.status_code, 400)
            self.assertEqual(self.client.get('/api/analytics/traders/' + trader_id).status_code, 404)
            self.assertEqual(self.client.get('/api/analytics/traders/not-an-id').status_code, 404)
        with patch.object(app, 'PARTICIPANT_ALIAS_SECRET', ''):
            self.assertEqual(self.client.get('/api/analytics/traders/' + trader_id).status_code, 503)

    def test_overview_exposes_current_listing_without_removing_historical_totals(self):
        with patch.object(app, 'get_tradeable_assets', return_value={'assets': ['ETH'], 'source': 'live_inventory'}):
            with patch.object(app, 'get_analytics_overview', return_value={'totals': {'notional': 123}}):
                response = self.client.get('/api/analytics/overview')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['tradeable_assets']['assets'], ['ETH'])
        self.assertEqual(response.get_json()['totals']['notional'], 123)


if __name__ == '__main__':
    unittest.main()
