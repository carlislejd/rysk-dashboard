"""Resume all-chain trade history backfill using the gap-safe sync pipeline.

Usage: python scripts/backfill.py
Full reconciliation: python scripts/sync.py --from-date 2025-07-01
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.sync import sync


def backfill():
    return sync()


if __name__ == '__main__':
    backfill()
