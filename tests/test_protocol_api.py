"""Overview boundary validation, availability and public response contracts."""
import unittest
from unittest.mock import MagicMock, patch

import app
from positions_api import WalletDataUnavailable


class ProtocolAPITest(unittest.TestCase):
    def setUp(self):
        self.client = app.app.test_client()

    def test_supported_scope_and_connection_cleanup(self):
        connection = MagicMock()
        with patch.object(app, 'get_db', return_value=connection), patch.object(
                app, 'get_protocol_overview', return_value={'metrics': {}}) as service:
            response = self.client.get('/api/global/protocol-overview?days=90&chain_id=ethereum')
        self.assertEqual(response.status_code, 200)
        service.assert_called_once_with(connection, days=90, chain_id=1)
        connection.close.assert_called_once()
        self.assertEqual(response.headers['Cache-Control'], 'no-store')

    def test_invalid_scope_does_not_open_database(self):
        with patch.object(app, 'get_db') as connect:
            for query in ('days=0', 'days=-7', 'days=365', 'days=nope', 'chain_id=bad'):
                self.assertEqual(self.client.get('/api/global/protocol-overview?' + query).status_code, 400)
        connect.assert_not_called()

    def test_database_failure_is_sanitized(self):
        with patch.object(app, 'get_db', side_effect=RuntimeError('/private/path')):
            with self.assertLogs(app.app.logger, level='ERROR'):
                response = self.client.get('/api/global/protocol-overview')
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json, {'success': False, 'error': 'Protocol overview unavailable'})

    def test_wallet_outage_never_becomes_empty_success(self):
        for route, service in (('/api/positions', 'get_positions_payload'),
                               ('/api/history', 'get_history_payload')):
            with patch.object(app, service, side_effect=WalletDataUnavailable('Wallet data unavailable')):
                response = self.client.get(route + '?address=0x' + 'a' * 40)
            self.assertEqual(response.status_code, 503)
            self.assertFalse(response.json['success'])


if __name__ == '__main__':
    unittest.main()
