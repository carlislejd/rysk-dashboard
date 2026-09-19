import os
import tempfile
import unittest
from unittest.mock import patch

import app
from db import get_db, init_db


class TestRetentionAPI(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.directory.name, 'test.db')
        conn = get_db(self.path)
        init_db(conn)
        conn.close()
        self.mock_db = patch.object(app, 'get_db', side_effect=lambda: get_db(self.path))
        self.mock_db.start()
        self.client = app.app.test_client()

    def tearDown(self):
        self.mock_db.stop()
        self.directory.cleanup()

    def test_empty_database_returns_valid_schema_and_chain_filter(self):
        response = self.client.get('/api/analytics/retention?chain_id=hyperevm&days=30')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json['success'])
        self.assertEqual(response.json['cohorts'], [])
        self.assertEqual(response.json['filters']['chain_id'], 999)
        self.assertEqual(response.json['pending_trades'], 0)

    def test_invalid_chain_returns_client_error(self):
        response = self.client.get('/api/analytics/retention?chain_id=invalid')
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json['success'])
