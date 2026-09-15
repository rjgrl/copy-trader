"""Formatting helpers for prices, volumes, and display strings."""

from __future__ import annotations


def format_price(value: float | None, digits: int = 5) -> str:
    if value is None:
        return "—"
    return f"{value:.{digits}f}".rstrip("0").rstrip(".") if digits else str(value)


def format_volume(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:.2f}".rstrip("0").rstrip(".") if value != int(value) else f"{int(value)}"


def truncate_comment(text: str, max_len: int = 31) -> str:
    """MT5 order comments are typically limited (~31 chars on many brokers)."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def build_order_comment(symbol: str, message_id: int, tp_index: int) -> str:
    """Structured order comment, e.g. TG-XAUUSD-18392-TP1."""
    raw = f"TG-{symbol}-{message_id}-TP{tp_index}"
    return truncate_comment(raw, 31)
