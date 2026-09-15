"""Logging setup for the application."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


LOG_FORMAT = "%(asctime)s.%(msecs)03d | %(levelname)-8s | %(name)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(
    log_dir: Path,
    level: str = "INFO",
    console: bool = True,
    filename: str = "app.log",
    max_bytes: int = 5_000_000,
    backup_count: int = 5,
) -> None:
    """Configure root logger with rotating file handler and optional console."""
    log_dir.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

    file_handler = RotatingFileHandler(
        log_dir / filename,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    if console:
        # Windows consoles may be cp1252 — replace unencodable chars instead of crashing
        stream = sys.stdout
        try:
            stream.reconfigure(errors="replace")  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass
        console_handler = logging.StreamHandler(stream)
        console_handler.setFormatter(formatter)
        root.addHandler(console_handler)

    # Quiet noisy third-party loggers
    logging.getLogger("telethon").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)


class GuiLogHandler(logging.Handler):
    """Optional handler that forwards log records to a GUI callback."""

    def __init__(self, callback) -> None:
        super().__init__()
        self._callback = callback
        self.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._callback(self.format(record), record.levelname)
        except Exception:  # noqa: BLE001 — never break logging from GUI sink
            self.handleError(record)
