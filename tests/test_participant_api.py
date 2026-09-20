import json
import os
import tempfile
import unittest
from unittest.mock import patch

import app
from db import get_db, init_db


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


if __name__ == '__main__':
    unittest.main()
