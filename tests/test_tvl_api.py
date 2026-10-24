"""Public TVL response boundaries do not depend on the trade database."""

import unittest
from unittest.mock import patch

import app
from tvl_services import TVLUnavailable


class TVLAPITests(unittest.TestCase):
    def setUp(self):
        self.client = app.app.test_client()

    def test_supported_scopes_and_aliases_do_not_access_database(self):
        for query, chain_id in (("", None), ("chain=all", None),
                                ("chain=hyperevm", 999), ("chain=ethereum", 1),
                                ("chain_id=999", 999), ("chain_id=ethereum", 1)):
            payload = {"tvl": {"usd": 123, "is_stale": False}, "filters": {"chain_id": chain_id}}
            with self.subTest(query=query), patch.object(app, "get_db") as database, patch.object(
                    app, "get_protocol_tvl", return_value=payload) as service:
                result = self.client.get("/api/global/tvl?" + query)
                self.assertEqual(result.status_code, 200)
                self.assertEqual(result.json, {"success": True, **payload})
                self.assertEqual(result.headers["Cache-Control"], "no-store")
                service.assert_called_once_with(chain_id=chain_id)
                database.assert_not_called()

    def test_invalid_and_unsupported_chains_are_rejected_before_network_or_database(self):
        with patch("tvl_services.requests.get") as fetch, patch.object(app, "get_db") as database:
            for query in ("chain=bad", "chain=42161", "chain_id=0", "chain_id=-1", "chain_id=true"):
                with self.subTest(query=query):
                    result = self.client.get("/api/global/tvl?" + query)
                    self.assertEqual(result.status_code, 400)
                    self.assertFalse(result.json["success"])
            fetch.assert_not_called()
            database.assert_not_called()

    def test_unavailable_is_503_without_a_fabricated_tvl(self):
        with patch.object(app, "get_protocol_tvl", side_effect=TVLUnavailable("private detail")):
            result = self.client.get("/api/global/tvl")
        self.assertEqual(result.status_code, 503)
        self.assertEqual(result.json, {"success": False, "error": "TVL temporarily unavailable"})

    def test_unexpected_failure_is_sanitized(self):
        with patch.object(app, "get_protocol_tvl", side_effect=RuntimeError("private detail")):
            with self.assertLogs(app.app.logger, level="ERROR"):
                result = self.client.get("/api/global/tvl")
        self.assertEqual(result.status_code, 503)
        self.assertEqual(result.json, {"success": False, "error": "TVL temporarily unavailable"})


if __name__ == "__main__":
    unittest.main()
