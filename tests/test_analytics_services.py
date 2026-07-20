import sqlite3
import unittest
from unittest.mock import patch

from analytics_services import get_analytics_overview, get_otm_apr_surface, normalize_underlying


def build_connection():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE trades (
            created_at INTEGER,
            expiry INTEGER,
            symbol TEXT,
            chain_id INTEGER,
            strike_f REAL,
            notional_f REAL,
            premium_f REAL,
            apr_f REAL,
            is_put INTEGER,
            outcome TEXT
        )
        """
    )
    return conn


class TestAnalyticsServices(unittest.TestCase):
    def test_normalize_underlying_collapses_wrappers_and_pts(self):
        self.assertEqual(normalize_underlying("WHYPE"), "HYPE")
        self.assertEqual(normalize_underlying("kHYPE-PT-19MAR26"), "HYPE")
        self.assertEqual(normalize_underlying("UBTC"), "BTC")
        self.assertEqual(normalize_underlying("fXRP"), "XRP")

    def test_overview_builds_notional_stream_and_weighted_metrics(self):
        conn = build_connection()
        conn.executemany(
            "INSERT INTO trades VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (1_700_000_000, 1_700_864_000, "WHYPE", 999, 100, 1000, 20, 400, 0, "Returned"),
                (1_700_086_400, 1_701_814_400, "kHYPE", 999, 105, 3000, 30, 200, 1, "Assigned"),
                (1_700_172_800, 1_702_764_800, "UBTC", 999, 50_000, 6000, 60, 100, 0, "Returned"),
            ],
        )

        result = get_analytics_overview(conn, days=0)

        self.assertEqual(result["assets"], ["BTC", "HYPE"])
        self.assertEqual(result["totals"]["trade_count"], 3)
        # APR uses the same premium / strike-notional basis as headline yield,
        # capital-day weighted across 10d, 20d, and 30d observations. It does
        # not use the deliberately different quoted APRs.
        self.assertAlmostEqual(result["totals"]["weighted_apr"], 16.06)
        self.assertAlmostEqual(result["totals"]["quoted_weighted_apr"], 160.0)
        self.assertAlmostEqual(result["totals"]["weighted_dte_days"], 25.0)
        self.assertAlmostEqual(result["totals"]["premium_yield_pct"], 1.1)
        self.assertEqual(result["totals"]["call_count"], 2)
        self.assertEqual(result["totals"]["put_count"], 1)
        self.assertEqual(len(result["by_option_type"]), 2)
        self.assertEqual(len(result["by_asset_option_type"]), 3)
        self.assertEqual(result["totals"]["return_rate_pct"], 2 / 3 * 100)
        self.assertEqual(sum(point["total_notional"] for point in result["notional_series"]), 10_000)
        self.assertTrue(result["tenor_surface"])

        yield_metrics = {
            key: result["totals"][key]
            for key in ("notional", "premium", "premium_yield_pct", "weighted_apr", "weighted_dte_days")
        }
        conn.execute("UPDATE trades SET outcome = 'Assigned'")
        outcome_changed = get_analytics_overview(conn, days=0)
        self.assertEqual(
            yield_metrics,
            {key: outcome_changed["totals"][key] for key in yield_metrics},
        )
        conn.close()

    @patch("analytics_services.get_asset_volatility")
    def test_otm_surface_uses_previous_close_not_same_day_close(self, mock_volatility):
        conn = build_connection()
        trade_time = 1_704_240_000  # 2024-01-03 UTC
        conn.executemany(
            "INSERT INTO trades VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (trade_time, trade_time + 21 * 86400, "WHYPE", 999, 105, 1000, 20, 40, 0, "Returned"),
                (trade_time, trade_time + 21 * 86400, "kHYPE", 999, 110, 3000, 30, 20, 0, "Assigned"),
            ],
        )
        mock_volatility.return_value = {
            "latest": {"date": "2024-01-03", "close": 50},
            "series": [
                {"date": "2024-01-01", "close": 99},
                {"date": "2024-01-02", "close": 100},
                # This close is not known at trade entry and must not be used.
                {"date": "2024-01-03", "close": 50},
            ],
        }

        result = get_otm_apr_surface(
            conn,
            asset="HYPE",
            days=0,
            option_type="call",
            dte_min=14,
            dte_max=30,
        )

        self.assertEqual(result["observed_trades"], 2)
        self.assertEqual(result["price_coverage_pct"], 100)
        samples = result["samples"]
        self.assertEqual(samples[0]["spot_reference"], 100)
        self.assertEqual(samples[0]["spot_reference_date"], "2024-01-02")
        self.assertAlmostEqual(samples[0]["otm_pct"], 5.0)
        five_percent = next(bucket for bucket in result["buckets"] if bucket["label"] == "5 to 7.5%")
        self.assertEqual(five_percent["trade_count"], 1)
        self.assertAlmostEqual(five_percent["weighted_apr"], 2 / 21 * 365)
        conn.close()


if __name__ == "__main__":
    unittest.main()
