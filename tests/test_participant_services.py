import sqlite3
import unittest
import json
from unittest.mock import patch

from participant_services import get_participant_analytics


def build_connection():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE trades (
            tx_hash TEXT, chain_id INTEGER, created_at INTEGER, expiry INTEGER,
            notional_f REAL, premium_f REAL, apr_f REAL, is_put INTEGER, outcome TEXT
        );
        CREATE TABLE trade_wallets (
            chain_id INTEGER, tx_hash TEXT, wallet TEXT, status TEXT
        );
    """)
    return conn


def add_trade(conn, index, wallet, created_at=1_700_000_000, chain_id=1,
              notional=100, premium=10, expiry_days=10):
    tx_hash = f"0x{index:04x}"
    conn.execute("INSERT INTO trades VALUES (?,?,?,?,?,?,?,?,?)", (
        tx_hash, chain_id, created_at, created_at + expiry_days * 86400,
        notional, premium, None, 0, None,
    ))
    if wallet is not None:
        conn.execute("INSERT INTO trade_wallets VALUES (?,?,?,?)", (
            chain_id, tx_hash, wallet, "verified_short_owner",
        ))


class TestParticipantServices(unittest.TestCase):
    def test_public_output_is_anonymous_and_leaderboard_is_deterministic(self):
        conn = build_connection()
        for index in range(20):
            add_trade(conn, index, f"0xABC{index:02X}", notional=100 + index, premium=10 + index)
        result = get_participant_analytics(conn, days=0, alias_secret="test-secret")
        rows = result["leaderboards"]["notional"]["rows"]
        self.assertEqual(result["leaderboards"]["notional"]["status"], "ready")
        self.assertEqual(len(rows), 10)
        self.assertTrue(rows[0]["alias"].startswith("Trader "))
        serialized = repr(result).lower()
        self.assertNotIn("0xabc", serialized)
        self.assertNotIn("participant_count", serialized)
        self.assertEqual(rows[0]["rank"], 1)
        conn.close()

    def test_small_population_and_missing_secret_do_not_return_rankings(self):
        conn = build_connection()
        for index in range(19):
            add_trade(conn, index, f"0x{index:x}")
        result = get_participant_analytics(conn, days=0, alias_secret="secret")
        self.assertEqual(result["leaderboards"]["notional"], {"status": "limited_history", "rows": []})
        result = get_participant_analytics(conn, days=0)
        self.assertEqual(result["leaderboards"]["premium"], {"status": "unavailable", "rows": []})
        conn.close()

    def test_apr_boundaries_and_invalid_duration_stay_in_the_denominator(self):
        conn = build_connection()
        base = 1_700_000_000
        # Twenty participants in each fixed band. Exact lower boundaries belong
        # to the higher band (10, 25, 50 and 100 respectively).
        premiums = [(5 / 36.5, "under_10"), (10 / 36.5, "10_to_25"),
                    (25 / 36.5, "25_to_50"), (50 / 36.5, "50_to_100"),
                    (100 / 36.5, "100_plus")]
        index = 0
        for premium, _band in premiums:
            for member in range(20):
                add_trade(conn, index, f"0x{index:x}", base, premium=premium)
                index += 1
        # Zero duration produces no annualizable APR but its capital remains in
        # segment share denominators.
        for member in range(20):
            add_trade(conn, index, f"0xinvalid{member:x}", base, premium=10, expiry_days=0)
            index += 1
        result = get_participant_analytics(conn, days=0, chain_id=1, alias_secret="secret")
        apr = {row["key"]: row for row in result["apr_segments"]}
        for _premium, key in premiums:
            self.assertEqual(apr[key]["status"], "ready")
            self.assertAlmostEqual(apr[key]["participant_share_pct"], 100 / 6)
        self.assertEqual(apr["unclassified"]["status"], "ready")
        self.assertAlmostEqual(apr["unclassified"]["notional_share_pct"], 100 / 6)
        conn.close()

    def test_activity_uses_utc_calendar_months(self):
        conn = build_connection()
        jan_31_2359 = 1_706_745_540  # 2024-01-31 23:59 UTC
        index = 0
        for group in range(20):
            add_trade(conn, index, f"0xsingle{group}", jan_31_2359)
            index += 1
        for group in range(20):
            wallet = f"0xrepeat{group}"
            add_trade(conn, index, wallet, jan_31_2359)
            add_trade(conn, index + 1000, wallet, jan_31_2359 + 30)
            index += 1
        for group in range(20):
            wallet = f"0xmonths{group}"
            add_trade(conn, index, wallet, jan_31_2359)
            add_trade(conn, index + 2000, wallet, jan_31_2359 + 120)
            index += 1
        segments = {row["key"]: row for row in get_participant_analytics(
            conn, days=0, alias_secret="secret"
        )["activity_segments"]}
        for row in segments.values():
            self.assertEqual(row["status"], "ready")
            self.assertAlmostEqual(row["participant_share_pct"], 100 / 3)
        conn.close()

    def test_weighted_apr_and_concentration(self):
        conn = build_connection()
        for index in range(100):
            add_trade(conn, index, f"0x{index:x}", notional=100, premium=10, expiry_days=10)
        # Give one participant an extra high-notional trade. The weighted APR remains capital-day weighted.
        add_trade(conn, 1000, "0x0", notional=900, premium=90, expiry_days=20)
        result = get_participant_analytics(conn, days=0, alias_secret="secret")
        self.assertEqual(result["concentration"]["status"], "ready")
        first = result["leaderboards"]["notional"]["rows"][0]
        self.assertAlmostEqual(first["weighted_apr"], 100 * 36500 / (100 * 10 + 900 * 20))
        self.assertGreater(result["concentration"]["rows"][0]["notional_share_pct"], 0)
        conn.close()

    def test_concentration_has_threshold_and_independent_rankings(self):
        conn = build_connection()
        for index in range(99):
            add_trade(conn, index, f"0x{index:x}", notional=1, premium=1)
        self.assertEqual(
            get_participant_analytics(conn, days=0, alias_secret="secret")["concentration"],
            {"status": "limited_history", "rows": []},
        )
        # Add a hundredth participant, then make notional and premium leaders
        # different addresses. The top groups use ceil(percent * population).
        add_trade(conn, 99, "0x63", notional=1, premium=1)
        add_trade(conn, 1000, "0x0", notional=999, premium=1)
        add_trade(conn, 1001, "0x1", notional=2, premium=499)
        result = get_participant_analytics(conn, days=0, alias_secret="secret")["concentration"]
        self.assertEqual(result["status"], "ready")
        totals = {"notional": 1101, "premium": 600}
        by_percentile = {row["percentile"]: row for row in result["rows"]}
        self.assertAlmostEqual(by_percentile[1]["notional_share_pct"], 1000 / totals["notional"] * 100)
        self.assertAlmostEqual(by_percentile[1]["premium_share_pct"], 500 / totals["premium"] * 100)
        self.assertAlmostEqual(by_percentile[5]["notional_share_pct"], 1006 / totals["notional"] * 100)
        self.assertAlmostEqual(by_percentile[5]["premium_share_pct"], 505 / totals["premium"] * 100)
        conn.close()

    def test_aliases_are_case_insensitive_cross_chain_stable_and_ties_sort_by_alias(self):
        conn = build_connection()
        for index in range(20):
            add_trade(conn, index, f"0xmember{index}", chain_id=1, notional=100, premium=10)
        add_trade(conn, 999, "0xmember0", chain_id=1, notional=200, premium=20)
        # This same wallet is the high-volume trader on a second chain.
        add_trade(conn, 1000, "0xMeMbEr0", chain_id=2, notional=900, premium=90)
        combined = get_participant_analytics(conn, days=0, alias_secret="secret")
        chain_one = get_participant_analytics(conn, days=0, chain_id=1, alias_secret="secret")
        with patch("participant_services.time.time", return_value=1_700_000_000 + 30 * 86400):
            windowed = get_participant_analytics(conn, days=365, alias_secret="secret")
        self.assertEqual(combined["leaderboards"]["notional"]["rows"][0]["alias"],
                         chain_one["leaderboards"]["notional"]["rows"][0]["alias"])
        self.assertEqual(combined["leaderboards"]["notional"]["rows"][0]["alias"],
                         windowed["leaderboards"]["notional"]["rows"][0]["alias"])
        tied = [row["alias"] for row in chain_one["leaderboards"]["notional"]["rows"]][1:]
        self.assertEqual(tied, sorted(tied))
        conn.close()

    @patch("participant_services.time.time", return_value=1_800_000_000)
    def test_days_filter_excludes_old_records(self, _time):
        conn = build_connection()
        add_trade(conn, 1, "0xold", created_at=1_700_000_000)
        add_trade(conn, 2, "0xnew", created_at=1_800_000_000 - 86400)
        result = get_participant_analytics(conn, days=30, alias_secret="secret")
        self.assertEqual(result["coverage"]["total_trades"], 1)
        self.assertEqual(result["filters"]["days"], 30)
        conn.close()

    def test_malformed_numbers_and_refresh_metadata_are_safe_for_json(self):
        conn = build_connection()
        for index in range(20):
            add_trade(conn, index, f"0x{index:x}")
        conn.execute("UPDATE trades SET notional_f='NaN', premium_f='Infinity' WHERE tx_hash='0x0000'")
        conn.execute("CREATE TABLE sync_meta (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO sync_meta VALUES (?, ?)", (
            "last_cohort_refresh_json", json.dumps({"finished_at": {"do_not_return": "nested"}}),
        ))
        result = get_participant_analytics(conn, days=0, alias_secret="secret")
        self.assertIsNone(result["coverage"]["last_refreshed"])
        # JSON's strict mode rejects NaN and Infinity; the public result must
        # remain serializable even if historical source fields are malformed.
        json.dumps(result, allow_nan=False)
        conn.execute("UPDATE sync_meta SET value=?", (json.dumps({"finished_at": "2026-09-19T12:34:56Z"}),))
        self.assertEqual(
            get_participant_analytics(conn, days=0, alias_secret="secret")["coverage"]["last_refreshed"],
            "2026-09-19T12:34:56Z",
        )
        conn.close()


if __name__ == "__main__":
    unittest.main()
