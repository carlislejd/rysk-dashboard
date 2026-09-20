import sqlite3
import unittest

from db import init_db
from global_services import get_asset_detail, get_global_trades


class TestGlobalServices(unittest.TestCase):
    def test_global_trades_expose_only_stable_anonymous_identity(self):
        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        init_db(conn)
        conn.executemany('''INSERT INTO trades
            (tx_hash,address,chain_id,created_at,is_buy,is_put,symbol,quantity,strike,
             price,premium,quantity_f,strike_f,premium_f,notional_f)
            VALUES (?,?,?,?,1,0,'HYPE','1','1','1','1',1,1,1,1)''', [
                ('hash-one', 'asset', 999, 3),
                ('hash-two', 'asset', 1, 2),
                ('hash-pending', 'asset', 999, 1),
            ])
        conn.executemany('INSERT INTO trade_wallets VALUES (?,?,?,?,?,?)', [
            (999, 'hash-one', '0x1234567890abcdef', 'verified_short_owner', None, 0),
            (1, 'hash-two', '0x1234567890ABCDEF', 'verified_short_owner', None, 0),
        ])

        payload = get_global_trades(conn, alias_secret='test-secret')
        first, second, pending = payload['trades']

        self.assertNotIn('seller_wallet', first)
        self.assertEqual(first['owner_status'], 'verified_short_owner')
        self.assertEqual(first['trader_id'], second['trader_id'])
        self.assertEqual(first['trader_alias'], second['trader_alias'])
        self.assertEqual(len(first['trader_id']), 64)
        self.assertRegex(first['trader_alias'], r'^Trader [0-9A-F]{8}$')
        self.assertIsNone(pending['trader_id'])
        self.assertIsNone(pending['trader_alias'])
        self.assertNotIn('0x1234567890abcdef', str(payload))

    def test_global_trades_with_no_alias_secret_do_not_emit_identity(self):
        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        init_db(conn)
        conn.execute('''INSERT INTO trades
            (tx_hash,address,chain_id,created_at,is_buy,is_put,symbol,quantity,strike,
             price,premium,quantity_f,strike_f,premium_f,notional_f)
            VALUES ('hash','asset',999,1,1,0,'HYPE','1','1','1','1',1,1,1,1)''')
        conn.execute("INSERT INTO trade_wallets VALUES (999,'hash','0x1234567890abcdef', 'verified_short_owner',NULL,0)")

        trade = get_global_trades(conn)['trades'][0]

        self.assertIsNone(trade['trader_id'])
        self.assertIsNone(trade['trader_alias'])
        self.assertNotIn('0x1234567890abcdef', str(trade))

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
