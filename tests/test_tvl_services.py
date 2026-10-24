"""TVL scope, source validation, and bounded outage behavior."""

from concurrent.futures import ThreadPoolExecutor
import threading
import unittest
from unittest.mock import Mock, patch

import requests

import tvl_services as tvl


NOW = 1_800_000_000


def source_payload(timestamp=NOW - 60):
    return {
        "tvl": [{"date": timestamp, "totalLiquidityUSD": 375}],
        "currentChainTvls": {"Ethereum": 125.25, "Hyperliquid L1": 250.50,
                             "staking": 9000, "Arbitrum": 8000},
        "chainTvls": {
            "Ethereum": {"tvl": [{"date": timestamp, "totalLiquidityUSD": 125}]},
            "Hyperliquid L1": {"tvl": [{"date": timestamp, "totalLiquidityUSD": 250}]},
        },
    }


def response(payload):
    result = Mock()
    result.json.return_value = payload
    return result


class TVLServiceTests(unittest.TestCase):
    def setUp(self):
        for name, value in (("_snapshot", None), ("_retry_after", 0),
                            ("_last_refresh_failed", False)):
            patcher = patch.object(tvl, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        clock = patch.object(tvl.time, "time", return_value=NOW)
        self.clock = clock.start()
        self.addCleanup(clock.stop)
        fetcher = patch.object(tvl.requests, "get", return_value=response(source_payload()))
        self.fetch = fetcher.start()
        self.addCleanup(fetcher.stop)

    def test_scopes_share_one_snapshot_and_sum_only_tracked_networks(self):
        overall = tvl.get_protocol_tvl()
        ethereum = tvl.get_protocol_tvl(1)
        hyper = tvl.get_protocol_tvl(999)
        self.assertEqual(overall["tvl"], {
            "usd": 375.75, "as_of": NOW - 60, "fetched_at": NOW,
            "is_stale": False, "source": "DeFiLlama",
            "source_url": "https://defillama.com/protocol/rysk-v12", "protocol": "Rysk V12",
        })
        self.assertEqual(ethereum["tvl"]["usd"], 125.25)
        self.assertEqual(hyper["tvl"]["usd"], 250.50)
        self.assertEqual(overall["filters"], {"chain_id": None})
        self.assertEqual(hyper["filters"], {"chain_id": 999})
        self.fetch.assert_called_once_with(tvl.API_URL, timeout=tvl.REQUEST_TIMEOUT)
        overall["tvl"]["usd"] = 99999
        self.assertEqual(tvl.get_protocol_tvl()["tvl"]["usd"], 375.75)

    def test_all_networks_use_oldest_contributing_timestamp(self):
        payload = source_payload()
        payload["chainTvls"]["Ethereum"]["tvl"][-1]["date"] = NOW - 600
        self.fetch.return_value = response(payload)
        self.assertEqual(tvl.get_protocol_tvl()["tvl"]["as_of"], NOW - 600)
        self.assertEqual(tvl.get_protocol_tvl(1)["tvl"]["as_of"], NOW - 600)
        self.assertEqual(tvl.get_protocol_tvl(999)["tvl"]["as_of"], NOW - 60)

    def test_zero_is_valid_but_unsupported_scopes_do_not_fetch(self):
        for scope in (42161, "1", True, 1.0, -1):
            with self.subTest(scope=scope), self.assertRaises(ValueError):
                tvl.get_protocol_tvl(scope)
        self.fetch.assert_not_called()
        payload = source_payload()
        payload["currentChainTvls"]["Ethereum"] = 0
        self.fetch.return_value = response(payload)
        self.assertEqual(tvl.get_protocol_tvl(1)["tvl"]["usd"], 0)

    def test_cache_refreshes_after_five_minutes(self):
        tvl.get_protocol_tvl()
        self.clock.return_value = NOW + tvl.CACHE_TTL_SECONDS - 1
        tvl.get_protocol_tvl(1)
        self.assertEqual(self.fetch.call_count, 1)
        self.clock.return_value += 1
        payload = source_payload(timestamp=NOW + 250)
        payload["currentChainTvls"]["Ethereum"] = 130
        self.fetch.return_value = response(payload)
        result = tvl.get_protocol_tvl()
        self.assertEqual(self.fetch.call_count, 2)
        self.assertEqual(result["tvl"]["usd"], 380.50)
        self.assertEqual(result["tvl"]["fetched_at"], NOW + 300)
        self.assertFalse(result["tvl"]["is_stale"])

    def test_refresh_failure_returns_explicit_stale_cache_and_backs_off(self):
        tvl.get_protocol_tvl()
        self.clock.return_value = NOW + 300
        self.fetch.side_effect = requests.Timeout("upstream request timed out")
        stale = tvl.get_protocol_tvl(999)["tvl"]
        self.assertEqual(stale["usd"], 250.50)
        self.assertTrue(stale["is_stale"])
        self.assertEqual(stale["as_of"], NOW - 60)
        self.assertEqual(stale["fetched_at"], NOW)
        tvl.get_protocol_tvl()
        self.assertEqual(self.fetch.call_count, 2)
        self.clock.return_value += tvl.FAILURE_RETRY_SECONDS
        self.fetch.side_effect = None
        recovered = tvl.get_protocol_tvl()
        self.assertFalse(recovered["tvl"]["is_stale"])
        self.assertEqual(self.fetch.call_count, 3)

    def test_failure_without_cache_is_unavailable_and_retries_are_bounded(self):
        self.fetch.side_effect = requests.ConnectionError("private network detail")
        for scope in (None, 1, 999):
            with self.assertRaises(tvl.TVLUnavailable):
                tvl.get_protocol_tvl(scope)
        self.assertEqual(self.fetch.call_count, 1)

    def test_source_and_cache_cannot_survive_beyond_a_day(self):
        tvl.get_protocol_tvl()
        self.fetch.side_effect = requests.Timeout()
        self.clock.return_value = NOW + tvl.MAX_STALE_SECONDS - 60
        self.assertTrue(tvl.get_protocol_tvl()["tvl"]["is_stale"])
        self.clock.return_value += 1
        with self.assertRaises(tvl.TVLUnavailable):
            tvl.get_protocol_tvl()
        self.clock.return_value = NOW + tvl.MAX_STALE_SECONDS + 1
        with self.assertRaises(tvl.TVLUnavailable):
            tvl.get_protocol_tvl()

    def test_old_source_is_stale_even_immediately_after_successful_fetch(self):
        self.fetch.return_value = response(source_payload(NOW - tvl.SOURCE_FRESHNESS_SECONDS - 1))
        result = tvl.get_protocol_tvl()["tvl"]
        self.assertTrue(result["is_stale"])
        self.assertEqual(result["fetched_at"], NOW)

    def test_invalid_values_and_missing_chains_are_never_replaced_with_zero(self):
        invalid = [None, True, False, "125", -1, float("nan"), float("inf"), 10 ** 1000]
        for value in invalid:
            with self.subTest(value=str(value)[:20]):
                payload = source_payload()
                payload["currentChainTvls"]["Ethereum"] = value
                with self.assertRaises(ValueError):
                    tvl._read_snapshot(payload, NOW)
        payload = source_payload()
        del payload["currentChainTvls"]["Ethereum"]
        self.fetch.return_value = response(payload)
        with self.assertRaises(tvl.TVLUnavailable):
            tvl.get_protocol_tvl(999)

    def test_invalid_source_dates_never_masquerade_as_fresh(self):
        invalid = [None, True, "1800000000", 0, -1, NOW + 1,
                   NOW - tvl.MAX_STALE_SECONDS - 1, float("nan"), NOW - 0.5]
        for value in invalid:
            for scope in ("total", "Ethereum", "Hyperliquid L1"):
                with self.subTest(value=value, scope=scope):
                    payload = source_payload()
                    series = payload["tvl"] if scope == "total" else payload["chainTvls"][scope]["tvl"]
                    series[-1]["date"] = value
                    with self.assertRaises(ValueError):
                        tvl._read_snapshot(payload, NOW)
        for payload in (None, [], {}, {"currentChainTvls": {}},
                        {**source_payload(), "tvl": []},
                        {**source_payload(), "chainTvls": {}}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                tvl._read_snapshot(payload, NOW)

    def test_malformed_refresh_does_not_replace_good_cache(self):
        tvl.get_protocol_tvl()
        self.clock.return_value = NOW + 300
        self.fetch.return_value = response({"currentChainTvls": {"Ethereum": 99999}})
        result = tvl.get_protocol_tvl()["tvl"]
        self.assertEqual(result["usd"], 375.75)
        self.assertEqual(result["fetched_at"], NOW)
        self.assertTrue(result["is_stale"])

    def test_concurrent_requests_do_not_stampede_upstream(self):
        started = threading.Event()
        release = threading.Event()

        def delayed_response(*args, **kwargs):
            started.set()
            if not release.wait(timeout=2):
                raise AssertionError("Test did not release the fetch")
            return response(source_payload())

        self.fetch.side_effect = delayed_response
        with ThreadPoolExecutor(max_workers=6) as pool:
            first = pool.submit(tvl.get_protocol_tvl)
            self.assertTrue(started.wait(timeout=2))
            others = [pool.submit(tvl.get_protocol_tvl, scope) for scope in (1, 999, None, 1, 999)]
            release.set()
            self.assertEqual(first.result()["tvl"]["usd"], 375.75)
            for future in others:
                future.result()
        self.fetch.assert_called_once()


if __name__ == "__main__":
    unittest.main()
