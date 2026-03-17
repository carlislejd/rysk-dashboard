"""
SQLite database layer for storing global trade history.

Note: The global /api/history endpoint does NOT return trader wallet addresses.
The `address` field contains the underlying asset contract, `collateral` is the
collateral token contract, and `usd` is the settlement token. Trader-level
analytics are not possible from this data source.
"""

import os
import sqlite3
from decimal import Decimal, getcontext

getcontext().prec = 28

DB_PATH = os.getenv("RYSK_DB_PATH", os.path.join(os.path.dirname(__file__), "data", "rysk_trades.db"))

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS trades (
    tx_hash       TEXT PRIMARY KEY,
    address       TEXT NOT NULL,
    chain_id      INTEGER,
    created_at    INTEGER NOT NULL,
    expiry        INTEGER,
    is_buy        INTEGER NOT NULL,
    is_put        INTEGER NOT NULL,
    symbol        TEXT NOT NULL,
    quantity      TEXT NOT NULL,
    strike        TEXT NOT NULL,
    price         TEXT NOT NULL,
    premium       TEXT NOT NULL,
    fees          TEXT,
    apr           TEXT,
    collateral    TEXT,
    usd           TEXT,
    status        TEXT,
    quantity_f    REAL NOT NULL,
    strike_f      REAL NOT NULL,
    premium_f     REAL NOT NULL,
    notional_f    REAL NOT NULL,
    apr_f         REAL,
    inserted_at   INTEGER NOT NULL DEFAULT (strftime('%s','now'))
);

CREATE TABLE IF NOT EXISTS sync_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_trades_created_at ON trades(created_at);
CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol);
CREATE INDEX IF NOT EXISTS idx_trades_symbol_created ON trades(symbol, created_at);
CREATE INDEX IF NOT EXISTS idx_trades_expiry ON trades(expiry);
"""


def get_db(path=None):
    """Return a connection with Row factory and WAL mode."""
    db_path = path or DB_PATH
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db(conn=None):
    """Create tables and indexes if they don't exist."""
    close = False
    if conn is None:
        conn = get_db()
        close = True
    conn.executescript(SCHEMA_SQL)
    _migrate(conn)
    conn.commit()
    if close:
        conn.close()


def _migrate(conn):
    """Add columns introduced after the initial schema."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(trades)").fetchall()}
    if "outcome" not in cols:
        conn.execute("ALTER TABLE trades ADD COLUMN outcome TEXT")
    if "expiry_price_f" not in cols:
        conn.execute("ALTER TABLE trades ADD COLUMN expiry_price_f REAL")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_trades_outcome ON trades(outcome)")


def _from_wei(value, decimals=18):
    """Convert wei-denominated string/number to float."""
    if value is None:
        return 0.0
    try:
        return float(Decimal(str(value)) / (Decimal(10) ** decimals))
    except (ValueError, ArithmeticError):
        return 0.0


def insert_trades(conn, rows):
    """Batch insert trades, computing float fields. Skips duplicates via INSERT OR IGNORE."""
    if not rows:
        return 0
    inserted = 0
    for row in rows:
        quantity_f = _from_wei(row.get("quantity"))
        strike_f = _from_wei(row.get("strike"))
        premium_f = _from_wei(row.get("premium"))
        notional_f = quantity_f * strike_f
        # APR comes as a plain percentage string (e.g. "51.17"), NOT wei
        apr_raw = row.get("apr")
        try:
            apr_f = float(apr_raw) if apr_raw else None
        except (ValueError, TypeError):
            apr_f = None

        try:
            conn.execute(
                """INSERT OR IGNORE INTO trades
                   (tx_hash, address, chain_id, created_at, expiry,
                    is_buy, is_put, symbol, quantity, strike, price, premium,
                    fees, apr, collateral, usd, status,
                    quantity_f, strike_f, premium_f, notional_f, apr_f)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    row.get("txHash") or row.get("tx_hash"),
                    row.get("address", ""),
                    row.get("chainId") or row.get("chain_id"),
                    row.get("createdAt") or row.get("created_at"),
                    row.get("expiry"),
                    1 if row.get("isBuy") or row.get("is_buy") else 0,
                    1 if row.get("isPut") or row.get("is_put") else 0,
                    row.get("symbol", ""),
                    str(row.get("quantity", "0")),
                    str(row.get("strike", "0")),
                    str(row.get("price", "0")),
                    str(row.get("premium", "0")),
                    str(row.get("fees")) if row.get("fees") is not None else None,
                    str(row.get("apr")) if row.get("apr") is not None else None,
                    str(row.get("collateral")) if row.get("collateral") is not None else None,
                    str(row.get("usd")) if row.get("usd") is not None else None,
                    row.get("status"),
                    quantity_f,
                    strike_f,
                    premium_f,
                    notional_f,
                    apr_f,
                ),
            )
            inserted += conn.total_changes  # approximate
        except sqlite3.IntegrityError:
            pass
    conn.commit()
    return inserted


def get_last_sync_ts(conn):
    """Return the last sync timestamp or None."""
    row = conn.execute(
        "SELECT value FROM sync_meta WHERE key = 'last_sync_ts'"
    ).fetchone()
    return int(row["value"]) if row else None


def set_last_sync_ts(conn, ts):
    """Upsert the last sync timestamp."""
    conn.execute(
        "INSERT OR REPLACE INTO sync_meta (key, value) VALUES ('last_sync_ts', ?)",
        (str(int(ts)),),
    )
    conn.commit()
