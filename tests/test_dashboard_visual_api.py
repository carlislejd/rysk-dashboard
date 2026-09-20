"""Public chart filtering contracts and privacy-safe failures."""
import unittest
from unittest.mock import MagicMock, patch

import app


class TestDashboardVisualAPI(unittest.TestCase):
    def setUp(self):
        self.client = app.app.test_client()
        self.connection = MagicMock()
        self.db = patch.object(app, 'get_db', return_value=self.connection)
        self.db.start()

    def tearDown(self):
        self.db.stop()

    def test_global_chart_filters_reach_service(self):
        with patch.object(app, 'get_global_trades', return_value={'trades': []}) as service:
            response = self.client.get('/api/global/trades?symbol=ETH&chain_id=1&strike=2500.5&from_ts=100&to_ts=200&page=2&limit=25&open_only=true')
        self.assertEqual(response.status_code, 200)
        values = service.call_args.kwargs
        for key, value in {'symbol': 'ETH', 'chain_id': 1, 'strike': 2500.5,
                           'from_ts': 100, 'to_ts': 200, 'page': 2, 'limit': 25, 'open_only': True}.items():
            self.assertEqual(values[key], value)
        self.connection.close.assert_called_once()

    def test_existing_asset_drilldown_page_size_remains_supported(self):
        with patch.object(app, 'get_global_trades', return_value={'trades': []}) as service:
            response = self.client.get('/api/global/trades?limit=200&symbol=ETH')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(service.call_args.kwargs['limit'], 200)

    def test_bad_chart_bounds_are_client_errors(self):
        invalid = ('from_ts=-1', 'to_ts=nan', 'from_ts=1.5', 'to_ts=253402300800',
                   'from_ts=200&to_ts=100', 'from_ts=100&to_ts=100')
        with patch.object(app, 'PARTICIPANT_ALIAS_SECRET', 'test-secret'):
            for endpoint in ('/api/global/trades', '/api/analytics/traders/' + 'a' * 64):
                for query in invalid:
                    with self.subTest(endpoint=endpoint, query=query):
                        response = self.client.get(endpoint + '?' + query)
                        self.assertEqual(response.status_code, 400)
        self.connection.execute.assert_not_called()

    def test_invalid_global_strikes_and_pagination_are_rejected(self):
        for query in ('strike=nan', 'strike=inf', 'strike=-1', 'strike=text', 'page=0', 'page=nope', 'limit=201', 'limit=nope'):
            with self.subTest(query=query):
                self.assertEqual(self.client.get('/api/global/trades?' + query).status_code, 400)

    def test_trader_chart_filters_reach_service_without_changing_identity(self):
        token = 'a' * 64
        with patch.object(app, 'PARTICIPANT_ALIAS_SECRET', 'test-secret'):
            with patch.object(app, 'get_trader_history', return_value={'identity': {'trader_id': token}}) as service:
                response = self.client.get('/api/analytics/traders/' + token + '?symbol=ETH&from_ts=100&to_ts=200&days=90')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(service.call_args.args[1], token)
        self.assertEqual(service.call_args.kwargs['symbol'], 'ETH')
        self.assertEqual(service.call_args.kwargs['from_ts'], 100)
        self.assertEqual(service.call_args.kwargs['to_ts'], 200)
        self.assertEqual(service.call_args.kwargs['days'], 90)

    def test_execution_window_validation_and_failure(self):
        self.assertEqual(self.client.get('/api/global/execution-timeline?window=30d').status_code, 400)
        with patch.object(app, 'get_global_execution_timeline', return_value={'data': []}) as service:
            response = self.client.get('/api/global/execution-timeline?window=7d&chain_id=ethereum')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(service.call_args.kwargs, {'window': '7d', 'chain_id': 1})
        with patch.object(app, 'get_global_execution_timeline', side_effect=RuntimeError('private value')):
            with self.assertLogs(app.app.logger, level='ERROR'):
                response = self.client.get('/api/global/execution-timeline')
        self.assertEqual(response.status_code, 500)
        self.assertNotIn('private value', response.get_data(as_text=True))
