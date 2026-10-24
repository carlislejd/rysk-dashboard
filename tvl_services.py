"""DeFiLlama collateral TVL for the Rysk V12 networks tracked by this dashboard."""

import math
import threading
import time

import requests


API_URL = "https://api.llama.fi/protocol/rysk-v12"
SOURCE_URL = "https://defillama.com/protocol/rysk-v12"
CHAIN_NAMES = {1: "Ethereum", 999: "Hyperliquid L1"}
CACHE_TTL_SECONDS = 300
FAILURE_RETRY_SECONDS = 60
SOURCE_FRESHNESS_SECONDS = 6 * 60 * 60
MAX_STALE_SECONDS = 24 * 60 * 60
REQUEST_TIMEOUT = (3.05, 8)

_snapshot = None
_retry_after = 0
_last_refresh_failed = False
_lock = threading.Lock()


class TVLUnavailable(Exception):
    """No sufficiently recent, validated TVL observation is available."""


def _number(value):
    # JSON booleans and numeric-looking strings are not measured USD values.
    if type(value) not in (int, float):
        raise ValueError("Invalid TVL value")
    try:
        valid = math.isfinite(value) and value >= 0
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError("Invalid TVL value")
    return value


def _latest_timestamp(series, now):
    if not isinstance(series, list) or not series or not isinstance(series[-1], dict):
        raise ValueError("Missing TVL observation")
    timestamp = _number(series[-1].get("date"))
    if (timestamp != int(timestamp) or timestamp <= 0 or timestamp > now
            or now - timestamp > MAX_STALE_SECONDS):
        raise ValueError("Invalid or outdated TVL observation")
    return int(timestamp)


def _read_snapshot(payload, now):
    if not isinstance(payload, dict):
        raise ValueError("Invalid TVL response")
    current = payload.get("currentChainTvls")
    histories = payload.get("chainTvls")
    if not isinstance(current, dict) or not isinstance(histories, dict):
        raise ValueError("Missing chain TVL")
    values = {}
    timestamps = {}
    for chain_id, chain_name in CHAIN_NAMES.items():
        values[chain_id] = _number(current.get(chain_name))
        history = histories.get(chain_name)
        if not isinstance(history, dict):
            raise ValueError("Missing chain TVL observation")
        timestamps[chain_id] = _latest_timestamp(history.get("tvl"), now)
    values[None] = _number(sum(values.values()))
    # Use the oldest contributing source observation if updates are staggered.
    timestamps[None] = min(_latest_timestamp(payload.get("tvl"), now),
                           *timestamps.values())
    return {"values": values, "timestamps": timestamps, "fetched_at": now}


def _fetch_snapshot():
    response = requests.get(API_URL, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return _read_snapshot(response.json(), int(time.time()))


def get_protocol_tvl(chain_id=None):
    """Return collateral TVL, independent of trading windows and local history.

    All scopes share one bounded cache and refresh lock. A failed refresh keeps
    a recent observation explicitly stale; absent or day-old data is unavailable.
    """
    global _snapshot, _retry_after, _last_refresh_failed
    if chain_id is not None and (type(chain_id) is not int or chain_id not in CHAIN_NAMES):
        raise ValueError("TVL supports only Ethereum (1) and HyperEVM (999)")

    with _lock:
        now = int(time.time())
        if now >= _retry_after:
            try:
                snapshot = _fetch_snapshot()
            except (requests.RequestException, ValueError, TypeError, OverflowError):
                _last_refresh_failed = True
                _retry_after = int(time.time()) + FAILURE_RETRY_SECONDS
            else:
                _snapshot = snapshot
                _last_refresh_failed = False
                _retry_after = snapshot["fetched_at"] + CACHE_TTL_SECONDS
        now = int(time.time())
        if _snapshot is None:
            raise TVLUnavailable("TVL temporarily unavailable")
        as_of = _snapshot["timestamps"][chain_id]
        fetched_at = _snapshot["fetched_at"]
        if not (0 <= now - as_of <= MAX_STALE_SECONDS
                and 0 <= now - fetched_at <= MAX_STALE_SECONDS):
            raise TVLUnavailable("TVL temporarily unavailable")
        return {
            "tvl": {
                "usd": _snapshot["values"][chain_id],
                "as_of": as_of,
                "fetched_at": fetched_at,
                "is_stale": (_last_refresh_failed
                             or now - as_of > SOURCE_FRESHNESS_SECONDS
                             or now - fetched_at >= CACHE_TTL_SECONDS),
                "source": "DeFiLlama",
                "source_url": SOURCE_URL,
                "protocol": "Rysk V12",
            },
            "filters": {"chain_id": chain_id},
        }
