"""SQLite database connection and schema initialization."""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from threading import RLock

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY NOT NULL,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key        TEXT PRIMARY KEY NOT NULL,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS telegram_sources (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id        INTEGER NOT NULL UNIQUE,
    name               TEXT NOT NULL,
    source_type        TEXT NOT NULL DEFAULT 'unknown',
    enabled            INTEGER NOT NULL DEFAULT 1,
    connection_status  TEXT NOT NULL DEFAULT 'unknown',
    last_message_id    INTEGER,
    last_message_at    TEXT,
    last_signal_at     TEXT,
    created_at         TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at         TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS signals (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_chat_id        INTEGER NOT NULL,
    telegram_message_id     INTEGER NOT NULL,
    telegram_message_date   TEXT,
    source_name             TEXT NOT NULL DEFAULT '',
    raw_message             TEXT NOT NULL,
    direction               TEXT,
    symbol                  TEXT,
    mapped_mt5_symbol       TEXT,
    entry_price             REAL,
    tp1                     REAL,
    tp2                     REAL,
    tp3                     REAL,
    additional_tps          TEXT,
    stop_loss               REAL,
    received_at             TEXT NOT NULL,
    processed_at            TEXT,
    actual_execution_price  REAL,
    entry_deviation         REAL,
    status                  TEXT NOT NULL,
    failure_reason          TEXT,
    signal_hash             TEXT,
    telegram_to_app_ms      REAL,
    app_to_mt5_ms           REAL,
    total_latency_ms        REAL,
    UNIQUE (telegram_chat_id, telegram_message_id)
);

CREATE INDEX IF NOT EXISTS idx_signals_status ON signals(status);
CREATE INDEX IF NOT EXISTS idx_signals_received ON signals(received_at DESC);
CREATE INDEX IF NOT EXISTS idx_signals_hash ON signals(signal_hash);

CREATE TABLE IF NOT EXISTS orders (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id           INTEGER NOT NULL,
    mt5_ticket          INTEGER,
    symbol              TEXT NOT NULL,
    direction           TEXT NOT NULL,
    volume              REAL NOT NULL,
    entry_price         REAL,
    stop_loss           REAL,
    take_profit         REAL,
    tp_index            INTEGER NOT NULL,
    status              TEXT NOT NULL,
    retcode             INTEGER,
    retcode_description TEXT,
    comment             TEXT,
    dry_run             INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (signal_id) REFERENCES signals(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_orders_signal ON orders(signal_id);
CREATE INDEX IF NOT EXISTS idx_orders_ticket ON orders(mt5_ticket);

CREATE TABLE IF NOT EXISTS logs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    level      TEXT NOT NULL,
    logger     TEXT,
    message    TEXT NOT NULL,
    signal_id  INTEGER,
    extra      TEXT
);

CREATE INDEX IF NOT EXISTS idx_logs_created ON logs(created_at DESC);
"""


class Database:
    """Thread-safe SQLite access with schema initialization."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = RLock()
        self._conn: sqlite3.Connection | None = None

    def connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(
                self.path,
                check_same_thread=False,
                timeout=30.0,
            )
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA foreign_keys = ON")
            self._conn.execute("PRAGMA journal_mode = WAL")
        return self._conn

    def initialize(self) -> None:
        with self._lock:
            conn = self.connect()
            conn.executescript(SCHEMA_SQL)
            conn.execute(
                "INSERT OR REPLACE INTO schema_meta (key, value) VALUES (?, ?)",
                ("version", str(SCHEMA_VERSION)),
            )
            conn.commit()
            logger.info("SQLite initialized at %s (schema v%s)", self.path, SCHEMA_VERSION)

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    def execute(self, sql: str, params: tuple | dict = ()) -> sqlite3.Cursor:
        with self._lock:
            conn = self.connect()
            cur = conn.execute(sql, params)
            conn.commit()
            return cur

    def executemany(self, sql: str, seq_of_params) -> sqlite3.Cursor:
        with self._lock:
            conn = self.connect()
            cur = conn.executemany(sql, seq_of_params)
            conn.commit()
            return cur

    def fetchone(self, sql: str, params: tuple | dict = ()) -> sqlite3.Row | None:
        with self._lock:
            conn = self.connect()
            return conn.execute(sql, params).fetchone()

    def fetchall(self, sql: str, params: tuple | dict = ()) -> list[sqlite3.Row]:
        with self._lock:
            conn = self.connect()
            return list(conn.execute(sql, params).fetchall())

    def table_names(self) -> list[str]:
        rows = self.fetchall(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        return [r["name"] for r in rows]

    @property
    def lock(self) -> RLock:
        """Expose lock for multi-statement transactions."""
        return self._lock

    def transaction(self):
        """Context manager for multi-statement transactions."""
        return _Transaction(self)


class _Transaction:
    def __init__(self, db: Database) -> None:
        self._db = db

    def __enter__(self) -> sqlite3.Connection:
        self._db.lock.acquire()
        conn = self._db.connect()
        conn.execute("BEGIN")
        return conn

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            conn = self._db.connect()
            if exc_type is None:
                conn.commit()
            else:
                conn.rollback()
        finally:
            self._db.lock.release()
