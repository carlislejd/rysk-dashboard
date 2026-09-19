import unittest
from unittest.mock import Mock, patch

from scripts import backfill_wallets as backfill


class TestReceiptBackfill(unittest.TestCase):
    def setUp(self):
        self.rows = [{'tx_hash': '0xfirst'}, {'tx_hash': '0xsecond'}]
        self.session = Mock()
        backfill._http.session = self.session
        backfill._next_request_at = 0

    def response(self, data):
        response = Mock()
        response.json.return_value = data
        return response

    def test_batch_ids_handle_out_of_order_responses_and_null_receipts(self):
        self.session.post.return_value = self.response([
            {'id': 1, 'result': None}, {'id': 0, 'result': {'transactionHash': '0xfirst'}}])
        result = backfill.fetch_batch(self.rows, 'https://example.invalid')
        self.assertEqual(result[0][1]['transactionHash'], '0xfirst')
        self.assertIsNone(result[1][1])

    @patch.object(backfill.time, 'sleep')
    def test_rate_limit_is_retried_not_misclassified_as_missing_receipt(self, sleep):
        self.session.post.side_effect = [
            self.response({'error': {'message': 'rate limited'}}),
            self.response([{'id': 0, 'result': None}, {'id': 1, 'result': None}]),
        ]
        result = backfill.fetch_batch(self.rows, 'https://example.invalid')
        self.assertEqual(len(result), 2)
        self.assertEqual(self.session.post.call_count, 2)
        self.assertTrue(sleep.called)

    @patch.object(backfill.time, 'sleep')
    def test_individual_errors_cannot_silently_become_null_receipts(self, sleep):
        self.session.post.return_value = self.response([
            {'id': 0, 'result': None}, {'id': 1, 'error': {'message': 'rate limited'}}])
        with self.assertRaises(ValueError):
            backfill.fetch_batch(self.rows, 'https://example.invalid')
        self.assertEqual(self.session.post.call_count, 4)


if __name__ == '__main__':
    unittest.main()
