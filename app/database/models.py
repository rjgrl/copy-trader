"""Database domain models (dataclass representations of SQLite rows)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class TelegramSourceRecord:
    id: int | None
    telegram_id: int
    name: str
    source_type: str  # group | channel | user | unknown
    enabled: bool = True
    connection_status: str = "unknown"
    last_message_id: int | None = None
    last_message_at: datetime | None = None
    last_signal_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(slots=True)
class SignalRecord:
    id: int | None
    telegram_chat_id: int
    telegram_message_id: int
    telegram_message_date: datetime | None
    source_name: str
    raw_message: str
    direction: str | None
    symbol: str | None
    mapped_mt5_symbol: str | None
    entry_price: float | None
    tp1: float | None
    tp2: float | None
    tp3: float | None
    additional_tps: str | None  # JSON array of floats beyond tp3
    stop_loss: float | None
    received_at: datetime
    processed_at: datetime | None
    actual_execution_price: float | None
    entry_deviation: float | None
    status: str
    failure_reason: str | None
    signal_hash: str | None
    telegram_to_app_ms: float | None = None
    app_to_mt5_ms: float | None = None
    total_latency_ms: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class OrderRecord:
    id: int | None
    signal_id: int
    mt5_ticket: int | None
    symbol: str
    direction: str
    volume: float
    entry_price: float | None
    stop_loss: float | None
    take_profit: float | None
    tp_index: int
    status: str
    retcode: int | None
    retcode_description: str | None
    comment: str | None
    created_at: datetime | None
    updated_at: datetime | None
    dry_run: bool = False
