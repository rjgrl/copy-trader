"""Application path resolution for development and frozen (PyInstaller) builds.

Writable state never uses sys._MEIPASS. Packaged builds store data under
%LOCALAPPDATA%\\TelegramMT5Copier\\.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from app.config.defaults import DEFAULT_DATA_DIR, DEFAULT_LOG_DIR

APP_DIR_NAME = "TelegramMT5Copier"


def is_frozen() -> bool:
    """True when running inside a PyInstaller (or similar) bundle."""
    return bool(getattr(sys, "frozen", False))


def get_bundle_dir() -> Path:
    """Read-only bundle directory (PyInstaller extract dir when frozen)."""
    if is_frozen() and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parents[2]


def get_project_root() -> Path:
    """Source-tree project root (development). Prefer get_persistent_root for writable paths."""
    return Path(__file__).resolve().parents[2]


def get_persistent_root() -> Path:
    """Writable application root for DB, session, config, logs, and .env.

    - Development: repository root (keeps existing ./data and ./logs)
    - Frozen EXE: %LOCALAPPDATA%\\TelegramMT5Copier
    """
    if is_frozen():
        local = os.environ.get("LOCALAPPDATA")
        if local:
            root = Path(local) / APP_DIR_NAME
        else:
            root = Path.home() / "AppData" / "Local" / APP_DIR_NAME
        root.mkdir(parents=True, exist_ok=True)
        return root
    return get_project_root()


def get_default_data_dir() -> Path:
    return get_persistent_root() / DEFAULT_DATA_DIR


def get_default_log_dir() -> Path:
    return get_persistent_root() / DEFAULT_LOG_DIR


def get_env_file_path() -> Path:
    """Location of the optional .env secrets file (never bundled into the EXE)."""
    return get_persistent_root() / ".env"


def resolve_user_path(value: str | Path) -> Path:
    """Resolve a path; relative paths are anchored to the persistent root."""
    path = Path(value)
    if not path.is_absolute():
        path = get_persistent_root() / path
    return path
