import sqlite3
import unittest

from db import init_db
from global_services import (get_asset_detail, get_global_execution_timeline,
                             get_global_trades, get_market_pulse)


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

    def test_global_trade_filters_are_composable_and_time_is_half_open(self):
        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        init_db(conn)
        expiry = 2_000
        conn.executemany('''INSERT INTO trades
            (tx_hash,address,chain_id,created_at,expiry,is_buy,is_put,symbol,quantity,strike,
             price,premium,quantity_f,strike_f,premium_f,notional_f,outcome)
            VALUES (?,?,?,?,?,1,0,?,'1',?,'1','1',1,?,1,?,?)''', [
                ('before', 'a', 999, 99, expiry, 'HYPE', 10, 10, 100, None),
                ('match', 'a', 999, 100, expiry, 'HYPE', 10, 10, 100, None),
                ('end', 'a', 999, 200, expiry, 'HYPE', 10, 10, 100, None),
                ('other-strike', 'a', 999, 150, expiry, 'HYPE', 11, 11, 100, None),
            ])
        payload = get_global_trades(conn, symbol='HYPE', strike=10, from_ts=100, to_ts=200)
        self.assertEqual(payload['total'], 1)
        self.assertEqual(payload['trades'][0]['tx_hash'], 'match')
        open_payload = get_global_trades(conn, symbol='HYPE', open_only=True, now=150)
        self.assertEqual(open_payload['total'], 4)

    def test_execution_timeline_fills_known_utc_buckets(self):
        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        init_db(conn)
        now = 1_800_000_123
        hour_end = (now // 3600) * 3600 + 3600
        conn.execute('''INSERT INTO trades
            (tx_hash,address,chain_id,created_at,is_buy,is_put,symbol,quantity,strike,
             price,premium,quantity_f,strike_f,premium_f,notional_f)
            VALUES ('hour', 'a',999,?,1,0,'HYPE','1','1','1','7',1,1,7,70)''', (hour_end - 7200,))
        timeline = get_global_execution_timeline(conn, window='24h', now=now)
        # The response does not fabricate zeros before the first observed trade.
        self.assertEqual(len(timeline['data']), 1)
        matched = [row for row in timeline['data'] if row['start'] == hour_end - 7200][0]
        self.assertEqual(matched['notional'], 70)
        self.assertEqual(matched['premium'], 7)
        self.assertEqual(sum(row['trade_count'] for row in timeline['data']), 1)

    def test_market_pulse_open_exposure_reconciles_and_splits_sides(self):
        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        init_db(conn)
        now = 1_900_000_000
        conn.executemany('''INSERT INTO trades
            (tx_hash,address,chain_id,created_at,expiry,is_buy,is_put,symbol,quantity,strike,
             price,premium,quantity_f,strike_f,premium_f,notional_f,outcome)
            VALUES (?,?,?,?,?,1,?,?,?,?, '1','1',1,1,1,?,?)''', [
                ('call', 'a', 999, now - 1, now + 1000, 0, 'HYPE', '1', '1', 40, None),
                ('put', 'a', 1, now - 1, now + 2000, 1, 'BTC', '1', '1', 60, None),
                ('settled', 'a', 999, now - 1, now - 1, 0, 'HYPE', '1', '1', 80, None),
                ('outcome', 'a', 999, now - 1, now + 1000, 0, 'HYPE', '1', '1', 90, 'Returned'),
            ])
        # Pin time while retaining the production function's one-time snapshot.
        import global_services
        original = global_services.time.time
        global_services.time.time = lambda: now
        try:
            pulse = get_market_pulse(conn)
        finally:
            global_services.time.time = original
        exposure = pulse['open_exposure']
        self.assertEqual(exposure['total_notional'], 100)
        self.assertEqual(sum(row['total_notional'] for row in exposure['by_asset']), 100)
        self.assertEqual(sum(row['total_notional'] for row in exposure['by_expiry']), 100)
        self.assertEqual(sum(row['call_notional'] for row in exposure['by_asset']), 40)
        self.assertEqual(sum(row['put_notional'] for row in exposure['by_asset']), 60)


if __name__ == "__main__":
    unittest.main()
