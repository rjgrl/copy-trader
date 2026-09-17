"""Repository layer for SQLite persistence."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from app.database.database import Database
from app.database.models import OrderRecord, SignalRecord, TelegramSourceRecord
from app.utils.time import utc_now

logger = logging.getLogger(__name__)


def _dt_to_str(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.isoformat()


def _str_to_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


class SignalRepository:
    """CRUD and duplicate checks for signals."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def exists(self, chat_id: int, message_id: int) -> bool:
        row = self._db.fetchone(
            "SELECT 1 FROM signals WHERE telegram_chat_id=? AND telegram_message_id=?",
            (chat_id, message_id),
        )
        return row is not None

    def get_by_telegram_ids(self, chat_id: int, message_id: int) -> SignalRecord | None:
        row = self._db.fetchone(
            "SELECT * FROM signals WHERE telegram_chat_id=? AND telegram_message_id=?",
            (chat_id, message_id),
        )
        return self._row_to_signal(row) if row else None

    def get_by_id(self, signal_id: int) -> SignalRecord | None:
        row = self._db.fetchone("SELECT * FROM signals WHERE id=?", (signal_id,))
        return self._row_to_signal(row) if row else None

    def insert(self, signal: SignalRecord) -> int:
        cur = self._db.execute(
            """
            INSERT INTO signals (
                telegram_chat_id, telegram_message_id, telegram_message_date,
                source_name, raw_message, direction, symbol, mapped_mt5_symbol,
                entry_price, tp1, tp2, tp3, additional_tps, stop_loss,
                received_at, processed_at, actual_execution_price, entry_deviation,
                status, failure_reason, signal_hash,
                telegram_to_app_ms, app_to_mt5_ms, total_latency_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                signal.telegram_chat_id,
                signal.telegram_message_id,
                _dt_to_str(signal.telegram_message_date),
                signal.source_name,
                signal.raw_message,
                signal.direction,
                signal.symbol,
                signal.mapped_mt5_symbol,
                signal.entry_price,
                signal.tp1,
                signal.tp2,
                signal.tp3,
                signal.additional_tps,
                signal.stop_loss,
                _dt_to_str(signal.received_at) or utc_now().isoformat(),
                _dt_to_str(signal.processed_at),
                signal.actual_execution_price,
                signal.entry_deviation,
                signal.status,
                signal.failure_reason,
                signal.signal_hash,
                signal.telegram_to_app_ms,
                signal.app_to_mt5_ms,
                signal.total_latency_ms,
            ),
        )
        return int(cur.lastrowid)

    def update_parsed(
        self,
        signal_id: int,
        *,
        direction: str | None,
        symbol: str | None,
        mapped_mt5_symbol: str | None,
        entry_price: float | None,
        tp1: float | None,
        tp2: float | None,
        tp3: float | None,
        additional_tps: str | None,
        stop_loss: float | None,
        status: str,
        signal_hash: str | None,
    ) -> None:
        self._db.execute(
            """
            UPDATE signals SET
                direction=?, symbol=?, mapped_mt5_symbol=?,
                entry_price=?, tp1=?, tp2=?, tp3=?, additional_tps=?,
                stop_loss=?, status=?, signal_hash=?
            WHERE id=?
            """,
            (
                direction,
                symbol,
                mapped_mt5_symbol,
                entry_price,
                tp1,
                tp2,
                tp3,
                additional_tps,
                stop_loss,
                status,
                signal_hash,
                signal_id,
            ),
        )

    def update_status(
        self,
        signal_id: int,
        status: str,
        *,
        failure_reason: str | None = None,
        processed_at: datetime | None = None,
        actual_execution_price: float | None = None,
        entry_deviation: float | None = None,
        telegram_to_app_ms: float | None = None,
        app_to_mt5_ms: float | None = None,
        total_latency_ms: float | None = None,
    ) -> None:
        fields: list[str] = ["status=?"]
        params: list[Any] = [status]
        if failure_reason is not None:
            fields.append("failure_reason=?")
            params.append(failure_reason)
        if processed_at is not None:
            fields.append("processed_at=?")
            params.append(_dt_to_str(processed_at))
        if actual_execution_price is not None:
            fields.append("actual_execution_price=?")
            params.append(actual_execution_price)
        if entry_deviation is not None:
            fields.append("entry_deviation=?")
            params.append(entry_deviation)
        if telegram_to_app_ms is not None:
            fields.append("telegram_to_app_ms=?")
            params.append(telegram_to_app_ms)
        if app_to_mt5_ms is not None:
            fields.append("app_to_mt5_ms=?")
            params.append(app_to_mt5_ms)
        if total_latency_ms is not None:
            fields.append("total_latency_ms=?")
            params.append(total_latency_ms)
        params.append(signal_id)
        self._db.execute(
            f"UPDATE signals SET {', '.join(fields)} WHERE id=?",
            tuple(params),
        )

    def list_by_statuses(self, statuses: list[str]) -> list[SignalRecord]:
        if not statuses:
            return []
        placeholders = ",".join("?" * len(statuses))
        rows = self._db.fetchall(
            f"SELECT * FROM signals WHERE status IN ({placeholders}) ORDER BY id",
            tuple(statuses),
        )
        return [self._row_to_signal(r) for r in rows]

    def list_recent(self, limit: int = 100) -> list[SignalRecord]:
        rows = self._db.fetchall(
            "SELECT * FROM signals ORDER BY received_at DESC LIMIT ?",
            (limit,),
        )
        return [self._row_to_signal(r) for r in rows]

    @staticmethod
    def _row_to_signal(row) -> SignalRecord:
        return SignalRecord(
            id=row["id"],
            telegram_chat_id=row["telegram_chat_id"],
            telegram_message_id=row["telegram_message_id"],
            telegram_message_date=_str_to_dt(row["telegram_message_date"]),
            source_name=row["source_name"],
            raw_message=row["raw_message"],
            direction=row["direction"],
            symbol=row["symbol"],
            mapped_mt5_symbol=row["mapped_mt5_symbol"],
            entry_price=row["entry_price"],
            tp1=row["tp1"],
            tp2=row["tp2"],
            tp3=row["tp3"],
            additional_tps=row["additional_tps"],
            stop_loss=row["stop_loss"],
            received_at=_str_to_dt(row["received_at"]) or utc_now(),
            processed_at=_str_to_dt(row["processed_at"]),
            actual_execution_price=row["actual_execution_price"],
            entry_deviation=row["entry_deviation"],
            status=row["status"],
            failure_reason=row["failure_reason"],
            signal_hash=row["signal_hash"],
            telegram_to_app_ms=row["telegram_to_app_ms"],
            app_to_mt5_ms=row["app_to_mt5_ms"],
            total_latency_ms=row["total_latency_ms"],
        )


class OrderRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def insert(self, order: OrderRecord) -> int:
        cur = self._db.execute(
            """
            INSERT INTO orders (
                signal_id, mt5_ticket, symbol, direction, volume,
                entry_price, stop_loss, take_profit, tp_index,
                status, retcode, retcode_description, comment, dry_run
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                order.signal_id,
                order.mt5_ticket,
                order.symbol,
                order.direction,
                order.volume,
                order.entry_price,
                order.stop_loss,
                order.take_profit,
                order.tp_index,
                order.status,
                order.retcode,
                order.retcode_description,
                order.comment,
                1 if order.dry_run else 0,
            ),
        )
        return int(cur.lastrowid)

    def list_for_signal(self, signal_id: int) -> list[OrderRecord]:
        rows = self._db.fetchall(
            "SELECT * FROM orders WHERE signal_id=? ORDER BY tp_index",
            (signal_id,),
        )
        return [self._row_to_order(r) for r in rows]

    def list_recent(self, limit: int = 100) -> list[OrderRecord]:
        rows = self._db.fetchall(
            "SELECT * FROM orders ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        return [self._row_to_order(r) for r in rows]

    def delete_by_ids(self, ids: list[int]) -> int:
        if not ids:
            return 0
        placeholders = ",".join("?" * len(ids))
        cur = self._db.execute(
            f"DELETE FROM orders WHERE id IN ({placeholders}) AND dry_run=1",
            tuple(ids),
        )
        return int(cur.rowcount or 0)

    def delete_dry_run(self) -> int:
        cur = self._db.execute("DELETE FROM orders WHERE dry_run=1")
        return int(cur.rowcount or 0)

    @staticmethod
    def _row_to_order(row) -> OrderRecord:
        return OrderRecord(
            id=row["id"],
            signal_id=row["signal_id"],
            mt5_ticket=row["mt5_ticket"],
            symbol=row["symbol"],
            direction=row["direction"],
            volume=row["volume"],
            entry_price=row["entry_price"],
            stop_loss=row["stop_loss"],
            take_profit=row["take_profit"],
            tp_index=row["tp_index"],
            status=row["status"],
            retcode=row["retcode"],
            retcode_description=row["retcode_description"],
            comment=row["comment"],
            created_at=_str_to_dt(row["created_at"]),
            updated_at=_str_to_dt(row["updated_at"]),
            dry_run=bool(row["dry_run"]),
        )


class TelegramSourceRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def upsert(self, source: TelegramSourceRecord) -> int:
        existing = self._db.fetchone(
            "SELECT id FROM telegram_sources WHERE telegram_id=?",
            (source.telegram_id,),
        )
        now = utc_now().isoformat()
        if existing:
            self._db.execute(
                """
                UPDATE telegram_sources SET
                    name=?, source_type=?, enabled=?,
                    connection_status=COALESCE(?, connection_status),
                    last_message_id=COALESCE(?, last_message_id),
                    last_message_at=COALESCE(?, last_message_at),
                    last_signal_at=COALESCE(?, last_signal_at),
                    updated_at=?
                WHERE telegram_id=?
                """,
                (
                    source.name,
                    source.source_type,
                    1 if source.enabled else 0,
                    source.connection_status or None,
                    source.last_message_id,
                    _dt_to_str(source.last_message_at),
                    _dt_to_str(source.last_signal_at),
                    now,
                    source.telegram_id,
                ),
            )
            return int(existing["id"])
        cur = self._db.execute(
            """
            INSERT INTO telegram_sources (
                telegram_id, name, source_type, enabled, connection_status,
                last_message_id, last_message_at, last_signal_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source.telegram_id,
                source.name,
                source.source_type,
                1 if source.enabled else 0,
                source.connection_status,
                source.last_message_id,
                _dt_to_str(source.last_message_at),
                _dt_to_str(source.last_signal_at),
            ),
        )
        return int(cur.lastrowid)

    def list_all(self) -> list[TelegramSourceRecord]:
        rows = self._db.fetchall("SELECT * FROM telegram_sources ORDER BY name")
        return [self._row_to_source(r) for r in rows]

    def list_enabled(self) -> list[TelegramSourceRecord]:
        rows = self._db.fetchall(
            "SELECT * FROM telegram_sources WHERE enabled=1 ORDER BY name"
        )
        return [self._row_to_source(r) for r in rows]

    def set_enabled(
        self,
        telegram_id: int,
        enabled: bool,
        *,
        name: str | None = None,
        source_type: str | None = None,
    ) -> None:
        existing = self._db.fetchone(
            "SELECT id FROM telegram_sources WHERE telegram_id=?",
            (telegram_id,),
        )
        now = utc_now().isoformat()
        if existing:
            self._db.execute(
                "UPDATE telegram_sources SET enabled=?, updated_at=? WHERE telegram_id=?",
                (1 if enabled else 0, now, telegram_id),
            )
            return
        self._db.execute(
            """
            INSERT INTO telegram_sources (telegram_id, name, source_type, enabled)
            VALUES (?, ?, ?, ?)
            """,
            (
                telegram_id,
                name or f"chat:{telegram_id}",
                source_type or "unknown",
                1 if enabled else 0,
            ),
        )

    def delete(self, telegram_id: int) -> None:
        self._db.execute(
            "DELETE FROM telegram_sources WHERE telegram_id=?",
            (telegram_id,),
        )

    @staticmethod
    def _row_to_source(row) -> TelegramSourceRecord:
        return TelegramSourceRecord(
            id=row["id"],
            telegram_id=row["telegram_id"],
            name=row["name"],
            source_type=row["source_type"],
            enabled=bool(row["enabled"]),
            connection_status=row["connection_status"],
            last_message_id=row["last_message_id"],
            last_message_at=_str_to_dt(row["last_message_at"]),
            last_signal_at=_str_to_dt(row["last_signal_at"]),
            created_at=_str_to_dt(row["created_at"]),
            updated_at=_str_to_dt(row["updated_at"]),
        )


class SettingsRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def get(self, key: str, default: Any = None) -> Any:
        row = self._db.fetchone("SELECT value FROM settings WHERE key=?", (key,))
        if row is None:
            return default
        try:
            return json.loads(row["value"])
        except json.JSONDecodeError:
            return row["value"]

    def set(self, key: str, value: Any) -> None:
        self._db.execute(
            """
            INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
            """,
            (key, json.dumps(value), utc_now().isoformat()),
        )

    def get_all(self) -> dict[str, Any]:
        rows = self._db.fetchall("SELECT key, value FROM settings")
        result: dict[str, Any] = {}
        for row in rows:
            try:
                result[row["key"]] = json.loads(row["value"])
            except json.JSONDecodeError:
                result[row["key"]] = row["value"]
        return result
