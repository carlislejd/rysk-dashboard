import sqlite3
import os
import unittest
from unittest.mock import patch

from db import init_db
from global_services import get_asset_summary, get_global_summary
from protocol_services import FRESHNESS_SECONDS, get_protocol_overview


class ProtocolOverviewTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        init_db(self.conn)
        self.addCleanup(self.conn.close)
        self.now = 1_800_000_000
        self.start = self.now - 30 * 86400

    def trade(self, key, created=None, expiry=None, chain=999, symbol="HYPE",
              notional=100, premium=5, put=0, outcome=None):
        self.conn.execute("""INSERT INTO trades
            (tx_hash,address,chain_id,created_at,expiry,is_buy,is_put,symbol,
             quantity,strike,price,premium,quantity_f,strike_f,premium_f,notional_f,outcome)
            VALUES (?,'asset',?,?,?,1,?,?,'1','1','1','1',1,1,?,?,?)""",
            (key, chain, self.now - 1 if created is None else created,
             self.now + 100 if expiry is None else expiry, put, symbol,
             premium, notional, outcome))

    def test_equal_windows_exclude_future_and_blank_rows_and_reconcile_mix(self):
        self.trade("previous", created=self.start - 1, notional=100, premium=2)
        self.trade("start", created=self.start, notional=120, premium=3)
        self.trade("current-put", chain=1, symbol="ETH", put=1, notional=80, premium=5)
        self.trade("future", created=self.now, notional=9999)
        self.trade("blank", symbol="", notional=9999)
        self.trade("too-old", created=self.start - 30 * 86400 - 1, notional=9999)

        result = get_protocol_overview(self.conn, now=self.now)

        self.assertEqual(result["metrics"]["notional"], {"value": 200, "previous": 100, "change_pct": 100})
        self.assertEqual(result["metrics"]["premium"]["value"], 8)
        self.assertEqual(result["metrics"]["trades"]["value"], 2)
        self.assertEqual(result["metrics"]["premium_yield_pct"], {"value": 4, "previous": 2, "change_pp": 2})
        self.assertEqual(result["strategy_mix"]["call_share_pct"], 60)
        self.assertEqual(result["strategy_mix"]["put_share_pct"], 40)
        self.assertEqual(sum(row["notional"] for row in result["chain_mix"]), 200)
        self.assertEqual(sum(row["share_pct"] for row in result["top_assets"]), 100)
        filtered = get_protocol_overview(self.conn, chain_id=1, now=self.now)
        self.assertEqual(filtered["metrics"]["notional"]["value"], 80)
        self.assertIsNone(filtered["metrics"]["notional"]["change_pct"])
        self.assertEqual(len(filtered["top_assets"]), 1)
        self.assertEqual(filtered["top_assets"][0]["symbol"], "ETH")

    def test_settlement_coverage_includes_null_and_unknown_without_lowering_known_rate(self):
        for key, outcome in [("assigned", "Assigned"), ("returned", "Returned"),
                             ("null", None), ("unknown", "Unknown")]:
            self.trade(key, expiry=self.now - 1, outcome=outcome)
        self.trade("open")
        self.trade("old-settled", created=self.start - 1, expiry=self.start, outcome="Assigned")

        outcomes = get_protocol_overview(self.conn, now=self.now)["outcomes"]

        self.assertEqual(outcomes["expired_count"], 4)
        self.assertEqual(outcomes["settled_count"], 2)
        self.assertEqual(outcomes["pending_count"], 2)
        self.assertEqual(outcomes["coverage_pct"], 50)
        self.assertEqual(outcomes["assigned_pct"], 50)
        self.assertEqual(outcomes["returned_pct"], 50)

    def test_stale_history_is_not_reported_as_fresh_and_quiet_recent_sync_is_distinct(self):
        self.trade("old", created=self.now - FRESHNESS_SECONDS - 1)
        stale = get_protocol_overview(self.conn, now=self.now)["observation"]
        self.assertEqual(stale["status"], "stale")
        self.assertTrue(stale["is_stale"])
        self.assertEqual(stale["freshness_basis"], "last_trade")
        self.assertIsNone(get_protocol_overview(self.conn, now=self.now)["metrics"]["trades"]["change_pct"])

        self.conn.execute("INSERT INTO sync_meta VALUES ('last_sync_ts', ?)", (str(self.now - 60),))
        recent = get_protocol_overview(self.conn, now=self.now)["observation"]
        self.assertEqual(recent["status"], "fresh")
        self.assertEqual(recent["age_seconds"], 60)
        self.assertEqual(recent["last_trade_at"], stale["last_trade_at"])
        self.assertEqual(recent["freshness_basis"], "last_sync")

    def test_stale_or_incomplete_prior_history_suppresses_growth_claims(self):
        self.trade("prior-window", created=self.start - 1)
        self.trade("old", created=self.start - 31 * 86400)
        stale = get_protocol_overview(self.conn, now=self.now)
        self.assertEqual(stale["metrics"]["trades"]["value"], 0)
        self.assertIsNone(stale["metrics"]["trades"]["change_pct"])
        self.assertEqual(stale["window"]["comparison_reason"], "stale_data")
        self.conn.execute("DELETE FROM trades WHERE tx_hash = 'old'")
        self.trade("recent")
        limited = get_protocol_overview(self.conn, now=self.now)
        self.assertFalse(limited["window"]["comparison_available"])
        self.assertEqual(limited["window"]["comparison_reason"], "limited_prior_history")
        self.assertIsNone(limited["metrics"]["trades"]["change_pct"])

    def test_collector_threshold_and_failed_latest_run_override_recent_trade(self):
        self.trade("recent")
        self.conn.execute("INSERT INTO sync_meta VALUES ('last_sync_ts', ?)", (str(self.now - 1801),))
        with patch.dict(os.environ, {"RYSK_SYNC_INTERVAL": "600"}):
            stale = get_protocol_overview(self.conn, now=self.now)["observation"]
            self.assertTrue(stale["is_stale"])
            self.assertEqual(stale["stale_after_seconds"], 1800)
        with patch.dict(os.environ, {"RYSK_SYNC_INTERVAL": "1200"}):
            fresh = get_protocol_overview(self.conn, now=self.now)["observation"]
            self.assertFalse(fresh["is_stale"])
            self.assertEqual(fresh["stale_after_seconds"], 3600)
            self.conn.execute("INSERT INTO sync_meta VALUES ('last_trade_audit_json', ?)", ('{"complete": false}',))
            failed = get_protocol_overview(self.conn, now=self.now)["observation"]
            self.assertTrue(failed["is_stale"])
            self.assertFalse(failed["latest_sync_succeeded"])

    def test_empty_dataset_does_not_invent_percentages_or_settlement_success(self):
        result = get_protocol_overview(self.conn, now=self.now)
        self.assertEqual(result["observation"]["status"], "empty")
        self.assertIsNone(result["metrics"]["premium_yield_pct"]["value"])
        self.assertIsNone(result["outcomes"]["coverage_pct"])
        self.assertIsNone(result["outcomes"]["assigned_pct"])
        self.assertIsNone(result["strategy_mix"]["call_share_pct"])
        with self.assertRaises(ValueError):
            get_protocol_overview(self.conn, days=365, now=self.now)

    def test_overdue_unresolved_rows_never_inflate_open_summary_or_asset_count(self):
        self.trade("open", premium=7)
        self.trade("pending-null", expiry=self.now - 1, premium=11)
        self.trade("pending-unknown", expiry=self.now, premium=13, outcome="Unknown")
        self.trade("settled", expiry=self.now - 2, premium=17, outcome="Returned")
        self.trade("future", created=self.now + 1, premium=999)
        self.trade("other-chain", expiry=self.now - 1, chain=1, premium=50)

        with patch("global_services.time.time", return_value=self.now):
            summary = get_global_summary(self.conn, chain_id=999)
            asset = get_asset_summary(self.conn, chain_id=999)["assets"][0]

        self.assertEqual(summary["total_premium"], 48)
        self.assertEqual(summary["active_premium"], 7)
        self.assertEqual(summary["active_count"], 1)
        self.assertEqual(summary["expired_premium"], 41)
        self.assertEqual(summary["pending_settlement_premium"], 24)
        self.assertEqual(summary["pending_settlement_count"], 2)
        self.assertEqual(asset["active_count"], 1)
        self.assertEqual(asset["expired_count"], 3)
        self.assertEqual(asset["pending_settlement_count"], 2)
        self.assertEqual(asset["returned"], 1)


if __name__ == "__main__":
    unittest.main()
