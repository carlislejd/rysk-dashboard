import json
import sqlite3
import unittest
from unittest.mock import patch

from participant_services import public_trader_identity
from trader_services import _timeline_bucket, get_trader_history


def build_connection():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE trades (
            tx_hash TEXT, chain_id INTEGER, created_at INTEGER, expiry INTEGER,
            symbol TEXT, is_buy INTEGER, is_put INTEGER, quantity_f REAL,
            strike_f REAL, premium_f REAL, notional_f REAL, apr_f REAL,
            status TEXT, outcome TEXT, expiry_price_f REAL
        );
        CREATE TABLE trade_wallets (chain_id INTEGER, tx_hash TEXT, wallet TEXT, status TEXT);
    """)
    return conn


def add_trade(conn, index, wallet, chain_id=1, created_at=1_800_000_000, verified=True,
              premium=10, notional=100, expiry_days=10, quoted_apr=365):
    tx_hash = f"0x{index:04x}"
    conn.execute("INSERT INTO trades VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
        tx_hash, chain_id, created_at, created_at + expiry_days * 86400, "UBTC", 0, 0,
        1, 100, premium, notional, quoted_apr, "Open", "Returned", 101,
    ))
    conn.execute("INSERT INTO trade_wallets VALUES (?,?,?,?)", (
        chain_id, tx_hash, wallet, "verified_short_owner" if verified else "pending",
    ))


class TestTraderServices(unittest.TestCase):
    def test_weekly_buckets_are_monday_based_across_month_boundary(self):
        # 2024-03-01 is a Friday; its UTC bucket starts on Monday Feb 26.
        self.assertEqual(_timeline_bucket(1709251200, 365), 1708905600)

    def test_identity_is_case_insensitive_and_opaque(self):
        first = public_trader_identity("0xAbC", "secret")
        second = public_trader_identity("0xabc", "secret")
        self.assertEqual(first, second)
        self.assertEqual(len(first["trader_id"]), 64)
        self.assertEqual(first["alias"], "Trader " + first["trader_id"][:8].upper())
        self.assertNotIn("0xabc", repr(first).lower())

    def test_history_scopes_verified_trades_pagination_and_chain(self):
        conn = build_connection()
        for index in range(3):
            add_trade(conn, index, "0xAbC", chain_id=1, created_at=1_800_000_000 + index)
        add_trade(conn, 3, "0xabc", chain_id=2, created_at=1_800_000_100)
        add_trade(conn, 4, "0xabc", chain_id=1, verified=False)
        identity = public_trader_identity("0xabc", "secret")
        result = get_trader_history(conn, identity["trader_id"], "secret", page=2, limit=2)
        self.assertEqual(result["identity"], identity)
        self.assertEqual(result["totals"]["trade_count"], 4)
        self.assertEqual(result["pagination"], {"page": 2, "limit": 2, "pages": 2, "total": 4})
        self.assertEqual(len(result["trades"]), 2)
        self.assertGreaterEqual(result["trades"][0]["created_at"], result["trades"][1]["created_at"])
        only_chain = get_trader_history(conn, identity["trader_id"], "secret", chain_id=1)
        self.assertEqual(only_chain["pagination"]["total"], 3)
        self.assertTrue(all(row["chain_id"] == 1 for row in only_chain["trades"]))
        encoded = json.dumps(result).lower()
        self.assertNotIn("0xabc", encoded)
        self.assertNotIn("tx_hash", encoded)
        conn.close()

    @patch("trader_services.time.time", return_value=1_800_000_000)
    def test_window_unknown_and_secret_failures(self, _time):
        conn = build_connection()
        add_trade(conn, 1, "0xabc", created_at=1_700_000_000)
        add_trade(conn, 2, "0xabc", created_at=1_800_000_000 - 86400)
        identity = public_trader_identity("0xabc", "secret")
        current = get_trader_history(conn, identity["trader_id"], "secret", days=30)
        self.assertEqual(current["pagination"]["total"], 1)
        for bad_token in ("xyz", "0" * 63, "g" * 64):
            with self.assertRaises(ValueError):
                get_trader_history(conn, bad_token, "secret")
        with self.assertRaises(ValueError):
            get_trader_history(conn, identity["trader_id"].upper(), "secret")
        with self.assertRaises(ValueError):
            get_trader_history(conn, identity["trader_id"], None)
        conn.close()

    def test_proof_without_a_matching_trade_is_not_a_resolvable_profile(self):
        conn = build_connection()
        conn.execute("INSERT INTO trade_wallets VALUES (?,?,?,?)", (
            1, "0xorphan", "0xorphanwallet", "verified_short_owner",
        ))
        orphan = public_trader_identity("0xorphanwallet", "secret")
        with self.assertRaises(ValueError):
            get_trader_history(conn, orphan["trader_id"], "secret")
        conn.close()

    def test_profile_row_apr_uses_derived_yield_and_invalid_duration_is_none(self):
        conn = build_connection()
        add_trade(conn, 1, "0xabc", premium=10, notional=100, expiry_days=20, quoted_apr=999)
        add_trade(conn, 2, "0xabc", premium=10, notional=100, expiry_days=0, quoted_apr=999)
        identity = public_trader_identity("0xabc", "secret")
        result = get_trader_history(conn, identity["trader_id"], "secret")
        by_expiry = {row["expiry"]: row for row in result["trades"]}
        self.assertAlmostEqual(by_expiry[1_800_000_000 + 20 * 86400]["apr"], 182.5)
        self.assertIsNone(by_expiry[1_800_000_000]["apr"])
        self.assertAlmostEqual(result["totals"]["weighted_apr"], 182.5)
        conn.close()

    @patch("trader_services.time.time", return_value=1_800_000_000)
    def test_visuals_use_full_window_while_table_filters_are_half_open(self, _time):
        conn = build_connection()
        # Monday 2026-12-28 and the following Sunday cross a calendar year.
        add_trade(conn, 1, "0xabc", created_at=1_798_800_000, notional=100)
        add_trade(conn, 2, "0xabc", created_at=1_799_318_400, notional=300)
        conn.execute("UPDATE trades SET symbol='ETH', is_put=1 WHERE tx_hash='0x0002'")
        identity = public_trader_identity("0xabc", "secret")
        result = get_trader_history(conn, identity["trader_id"], "secret", days=365,
                                    symbol="ETH", from_ts=1_799_318_400,
                                    to_ts=1_799_404_800, page=1, limit=1)
        self.assertEqual(result["pagination"]["total"], 1)
        self.assertEqual(result["trades"][0]["symbol"], "ETH")
        # The chart domain is deliberately based on the complete 365-day window.
        self.assertEqual(sum(point["notional"] for point in result["visuals"]["timeline"]), 400)
        self.assertEqual(result["visuals"]["bucket"], "week")
        assets = {row["symbol"]: row for row in result["visuals"]["assets"]}
        self.assertEqual(assets["ETH"]["puts_notional"], 300)
        self.assertNotIn("wallet", json.dumps(result).lower())
        self.assertNotIn("tx_hash", json.dumps(result).lower())
        conn.close()


if __name__ == "__main__":
    unittest.main()
