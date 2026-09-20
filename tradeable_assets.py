"""Small cached view of assets listed in Rysk's live options inventory."""

import threading
import time

from analytics_services import normalize_underlying
from inventory_services import fetch_inventory


# Confirmed against live inventory on 2026-09-19. Used only until this process
# can fetch inventory; a temporary outage must not reintroduce retired assets.
KNOWN_ASSETS = ('BTC', 'ETH', 'HYPE', 'PUMP', 'PURR', 'SOL', 'XAUT')
_snapshot = None
_retry_after = 0
_lock = threading.Lock()


def get_tradeable_assets():
    global _snapshot, _retry_after
    with _lock:
        now = time.time()
        if now >= _retry_after:
            try:
                inventory = fetch_inventory()
                assets = sorted({normalize_underlying(row['asset'])
                                 for row in inventory['assets'] if row.get('options')})
                _snapshot = {'assets': assets, 'source': 'live_inventory', 'checked_at': int(now)}
                _retry_after = now + 300
            except Exception:
                _retry_after = now + 60
                if _snapshot:
                    _snapshot = {**_snapshot, 'source': 'cached_inventory'}
        return dict(_snapshot or {
            'assets': list(KNOWN_ASSETS), 'source': 'last_known_listing', 'checked_at': None,
        })
