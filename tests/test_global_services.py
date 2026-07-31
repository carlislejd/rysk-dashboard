import sqlite3
import unittest

from global_services import get_asset_detail


class TestGlobalServices(unittest.TestCase):
    def test_asset_detail_strikes_include_side_order_counts(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute(
            """
            CREATE TABLE trades (
                symbol TEXT,
                chain_id INTEGER,
                expiry INTEGER,
                strike_f REAL,
                notional_f REAL,
                premium_f REAL,
                apr_f REAL,
                is_put INTEGER,
                outcome TEXT,
                expiry_price_f REAL
            )
            """
        )
        conn.executemany(
            """
            INSERT INTO trades (
                symbol, expiry, strike_f, notional_f, premium_f, apr_f,
                is_put, outcome, expiry_price_f, chain_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ("WHYPE", 1774598400, 63.0, 100.0, 5.0, 20.0, 1, None, None, 999),
                ("WHYPE", 1774598400, 63.0, 200.0, 8.0, 30.0, 1, None, None, 999),
                ("WHYPE", 1774598400, 63.0, 300.0, 9.0, 40.0, 0, None, None, 999),
            ],
        )

        detail = get_asset_detail(conn, "WHYPE", expiry=1774598400)

        self.assertEqual(len(detail["strikes"]), 1)
        strike = detail["strikes"][0]
        self.assertEqual(strike["trade_count"], 3)
        self.assertEqual(strike["put_count"], 2)
        self.assertEqual(strike["call_count"], 1)
        self.assertEqual(strike["put_volume"], 300.0)
        self.assertEqual(strike["call_volume"], 300.0)
        self.assertEqual(strike["put_premium"], 13.0)
        self.assertEqual(strike["call_premium"], 9.0)


if __name__ == "__main__":
    unittest.main()
