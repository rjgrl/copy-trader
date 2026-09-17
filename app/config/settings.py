"""Application settings loaded from defaults, .env, and optional config.json."""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.config.defaults import (
    APP_MAGIC_NUMBER,
    DEFAULT_COPY_TRADING_ENABLED,
    DEFAULT_DB_FILENAME,
    DEFAULT_DEVIATION_UNIT,
    DEFAULT_DRY_RUN,
    DEFAULT_ENTRY_DEVIATION_MODE,
    DEFAULT_ENTRY_MODE,
    DEFAULT_FIXED_LOT,
    DEFAULT_LOG_LEVEL,
    DEFAULT_LOT_MODE,
    DEFAULT_MAX_ENTRY_DEVIATION,
    DEFAULT_MAX_LOT_PER_ORDER,
    DEFAULT_MAX_ORDERS_PER_SIGNAL,
    DEFAULT_MAX_SIMULTANEOUS_TRADES,
    DEFAULT_MAX_SL_DISTANCE_PERCENT,
    DEFAULT_MAX_SPREAD,
    DEFAULT_MAX_TOTAL_LOT,
    DEFAULT_MIN_TP_COUNT,
    DEFAULT_REQUIRE_DIRECTION,
    DEFAULT_REQUIRE_ENTRY,
    DEFAULT_REQUIRE_SL,
    DEFAULT_REQUIRE_SYMBOL,
    DEFAULT_REQUIRE_TP,
    DEFAULT_TELEGRAM_SESSION_NAME,
    DEFAULT_TOO_FAR_BEHAVIOR,
    DEFAULT_TOTAL_LOT,
    DEFAULT_TP_PROXIMITY_PROTECTION,
    DEFAULT_USE_SL_BASED_DEVIATION,
    default_settings_dict,
)
from app.utils.paths import (
    get_default_data_dir,
    get_default_log_dir,
    get_env_file_path,
    get_project_root,
    resolve_user_path,
)

logger = logging.getLogger(__name__)

# Backward-compatible alias (development repo root)
PROJECT_ROOT = get_project_root()

EntryDeviationMode = Literal["fixed", "sl_percent", "stricter", "permissive"]
TooFarBehavior = Literal["reject", "pending", "manual", "market"]
LotMode = Literal["fixed", "total_split"]
DeviationUnit = Literal["price", "points"]


class ValidationRules(BaseModel):
    """Configurable signal field requirements."""

    require_direction: bool = DEFAULT_REQUIRE_DIRECTION
    require_symbol: bool = DEFAULT_REQUIRE_SYMBOL
    require_entry: bool = DEFAULT_REQUIRE_ENTRY
    require_tp: bool = DEFAULT_REQUIRE_TP
    require_sl: bool = DEFAULT_REQUIRE_SL
    min_tp_count: int = DEFAULT_MIN_TP_COUNT


class EntrySettings(BaseModel):
    """Intelligent entry validation settings."""

    entry_mode: str = DEFAULT_ENTRY_MODE
    max_entry_deviation: float = DEFAULT_MAX_ENTRY_DEVIATION
    deviation_unit: DeviationUnit = DEFAULT_DEVIATION_UNIT
    tp_proximity_protection: bool = DEFAULT_TP_PROXIMITY_PROTECTION
    use_sl_based_deviation: bool = DEFAULT_USE_SL_BASED_DEVIATION
    max_sl_distance_percent: float = DEFAULT_MAX_SL_DISTANCE_PERCENT
    entry_deviation_mode: EntryDeviationMode = DEFAULT_ENTRY_DEVIATION_MODE
    too_far_behavior: TooFarBehavior = DEFAULT_TOO_FAR_BEHAVIOR


class RiskSettings(BaseModel):
    """Lot sizing and exposure limits (V1: fixed / total split)."""

    lot_mode: LotMode = DEFAULT_LOT_MODE
    fixed_lot: float = DEFAULT_FIXED_LOT
    total_lot: float = DEFAULT_TOTAL_LOT
    max_lot_per_order: float = DEFAULT_MAX_LOT_PER_ORDER
    max_total_lot: float = DEFAULT_MAX_TOTAL_LOT
    max_orders_per_signal: int = DEFAULT_MAX_ORDERS_PER_SIGNAL
    max_simultaneous_trades: int = DEFAULT_MAX_SIMULTANEOUS_TRADES
    max_spread: float = DEFAULT_MAX_SPREAD


class AppSettings(BaseSettings):
    """Central application configuration.

    Load order:
    1. Built-in defaults
    2. Environment variables / .env (dev: repo root; packaged: LOCALAPPDATA)
    3. Optional data/config.json overlays (non-secret UI settings)
    """

    model_config = SettingsConfigDict(
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Paths — defaults use persistent root (repo in dev, LOCALAPPDATA when frozen)
    data_dir: Path = Field(default_factory=get_default_data_dir)
    log_dir: Path = Field(default_factory=get_default_log_dir)
    log_level: str = DEFAULT_LOG_LEVEL

    # Telegram (secrets — prefer .env; never bundled into the EXE)
    telegram_api_id: int | None = None
    telegram_api_hash: str | None = None
    telegram_session_name: str = DEFAULT_TELEGRAM_SESSION_NAME

    # MT5
    mt5_terminal_path: str | None = None
    magic_number: int = APP_MAGIC_NUMBER

    # Trading switches
    dry_run: bool = DEFAULT_DRY_RUN
    copy_trading_enabled: bool = DEFAULT_COPY_TRADING_ENABLED
    kill_switch_active: bool = False

    # Nested groups
    entry: EntrySettings = Field(default_factory=EntrySettings)
    risk: RiskSettings = Field(default_factory=RiskSettings)
    validation: ValidationRules = Field(default_factory=ValidationRules)

    # Symbol mapping: Telegram symbol → MT5 symbol (XM Ultra Low uses GOLD#)
    symbol_mappings: dict[str, str] = Field(
        default_factory=lambda: {"XAUUSD": "GOLD#", "GOLD": "GOLD#"}
    )

    def __init__(self, **kwargs: Any) -> None:
        env_file = kwargs.pop("_env_file", None)
        if env_file is None:
            env_path = get_env_file_path()
            # Only pass an existing file; missing .env is fine (env vars still work)
            env_file = env_path if env_path.is_file() else None
        super().__init__(_env_file=env_file, **kwargs)

    @field_validator("data_dir", "log_dir", mode="before")
    @classmethod
    def _resolve_path(cls, value: Any) -> Path:
        if value is None:
            return get_default_data_dir()
        return resolve_user_path(value)

    @property
    def database_path(self) -> Path:
        return self.data_dir / DEFAULT_DB_FILENAME

    @property
    def telegram_session_path(self) -> Path:
        return self.data_dir / self.telegram_session_name

    @property
    def config_json_path(self) -> Path:
        return self.data_dir / "config.json"

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def map_symbol(self, telegram_symbol: str) -> str:
        """Map a Telegram symbol to the broker MT5 symbol."""
        key = telegram_symbol.strip().upper()
        return self.symbol_mappings.get(key, key)

    def apply_config_json(self) -> None:
        """Overlay non-secret settings from data/config.json if present."""
        path = self.config_json_path
        if not path.exists():
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Failed to load config.json: %s", exc)
            return
        self._apply_overlay(raw)

    def save_config_json(self) -> None:
        """Persist non-secret settings to data/config.json."""
        self.ensure_directories()
        payload = {
            "dry_run": self.dry_run,
            "copy_trading_enabled": self.copy_trading_enabled,
            "kill_switch_active": self.kill_switch_active,
            "magic_number": self.magic_number,
            "mt5_terminal_path": self.mt5_terminal_path,
            "telegram_session_name": self.telegram_session_name,
            "log_level": self.log_level,
            "entry": self.entry.model_dump(),
            "risk": self.risk.model_dump(),
            "validation": self.validation.model_dump(),
            "symbol_mappings": self.symbol_mappings,
        }
        self.config_json_path.write_text(
            json.dumps(payload, indent=2),
            encoding="utf-8",
        )

    def _apply_overlay(self, raw: dict[str, Any]) -> None:
        for key in (
            "dry_run",
            "copy_trading_enabled",
            "kill_switch_active",
            "magic_number",
            "mt5_terminal_path",
            "telegram_session_name",
            "log_level",
            "symbol_mappings",
        ):
            if key in raw and raw[key] is not None:
                setattr(self, key, raw[key])
        if "entry" in raw and isinstance(raw["entry"], dict):
            self.entry = EntrySettings(**{**self.entry.model_dump(), **raw["entry"]})
        if "risk" in raw and isinstance(raw["risk"], dict):
            self.risk = RiskSettings(**{**self.risk.model_dump(), **raw["risk"]})
        if "validation" in raw and isinstance(raw["validation"], dict):
            self.validation = ValidationRules(
                **{**self.validation.model_dump(), **raw["validation"]}
            )


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    """Return the singleton AppSettings instance (env + optional config.json)."""
    settings = AppSettings()
    settings.ensure_directories()
    settings.apply_config_json()
    return settings


def reset_settings_cache() -> None:
    """Clear the settings cache (useful in tests)."""
    get_settings.cache_clear()


def seed_defaults() -> dict[str, Any]:
    """Expose flat defaults for database seeding."""
    return default_settings_dict()
