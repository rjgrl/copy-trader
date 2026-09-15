"""Default configuration values.

Conservative defaults: copy trading OFF, dry run ON so a fresh install
never sends real MT5 orders until the user explicitly enables live mode.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------
APP_NAME = "Telegram MT5 Copier"
APP_MAGIC_NUMBER = 123456
DEFAULT_LOG_LEVEL = "INFO"

# ---------------------------------------------------------------------------
# Safety / trading defaults (RULE: never auto-trade on first launch)
# ---------------------------------------------------------------------------
DEFAULT_DRY_RUN = True
DEFAULT_COPY_TRADING_ENABLED = False

# ---------------------------------------------------------------------------
# Entry execution (intelligent mode)
# ---------------------------------------------------------------------------
DEFAULT_ENTRY_MODE = "intelligent"
DEFAULT_MAX_ENTRY_DEVIATION = 3.0  # price units
DEFAULT_DEVIATION_UNIT = "price"
DEFAULT_TP_PROXIMITY_PROTECTION = True
DEFAULT_USE_SL_BASED_DEVIATION = False
DEFAULT_MAX_SL_DISTANCE_PERCENT = 15.0
DEFAULT_ENTRY_DEVIATION_MODE = "fixed"  # fixed | sl_percent | stricter | permissive
DEFAULT_TOO_FAR_BEHAVIOR = "reject"  # reject | pending | manual

# ---------------------------------------------------------------------------
# Lot sizing
# ---------------------------------------------------------------------------
DEFAULT_LOT_MODE = "fixed"  # fixed | total_split
DEFAULT_FIXED_LOT = 0.01
DEFAULT_TOTAL_LOT = 0.03

# ---------------------------------------------------------------------------
# Safety limits
# ---------------------------------------------------------------------------
DEFAULT_MAX_SIMULTANEOUS_TRADES = 5
DEFAULT_MAX_ORDERS_PER_SIGNAL = 5
DEFAULT_MAX_LOT_PER_ORDER = 1.0
DEFAULT_MAX_TOTAL_LOT = 3.0
DEFAULT_MAX_SPREAD = 50.0  # in price units (user-configurable; 0 = disabled)

# ---------------------------------------------------------------------------
# Validation requirements
# ---------------------------------------------------------------------------
DEFAULT_REQUIRE_DIRECTION = True
DEFAULT_REQUIRE_SYMBOL = True
DEFAULT_REQUIRE_ENTRY = True
DEFAULT_REQUIRE_TP = True
DEFAULT_REQUIRE_SL = True
DEFAULT_MIN_TP_COUNT = 1

# ---------------------------------------------------------------------------
# Telegram / MT5 paths (relative to project root unless absolute)
# ---------------------------------------------------------------------------
DEFAULT_DATA_DIR = "data"
DEFAULT_LOG_DIR = "logs"
DEFAULT_DB_FILENAME = "copier.db"
DEFAULT_TELEGRAM_SESSION_NAME = "telegram_session"
DEFAULT_CONFIG_FILENAME = "config.json"

# ---------------------------------------------------------------------------
# Reconnection
# ---------------------------------------------------------------------------
DEFAULT_RECONNECT_INITIAL_DELAY_SEC = 1.0
DEFAULT_RECONNECT_MAX_DELAY_SEC = 60.0
DEFAULT_RECONNECT_MAX_ATTEMPTS = 10


def default_settings_dict() -> dict[str, Any]:
    """Flat defaults used to seed the settings table / AppSettings."""
    return {
        "dry_run": DEFAULT_DRY_RUN,
        "copy_trading_enabled": DEFAULT_COPY_TRADING_ENABLED,
        "magic_number": APP_MAGIC_NUMBER,
        "entry_mode": DEFAULT_ENTRY_MODE,
        "max_entry_deviation": DEFAULT_MAX_ENTRY_DEVIATION,
        "deviation_unit": DEFAULT_DEVIATION_UNIT,
        "tp_proximity_protection": DEFAULT_TP_PROXIMITY_PROTECTION,
        "use_sl_based_deviation": DEFAULT_USE_SL_BASED_DEVIATION,
        "max_sl_distance_percent": DEFAULT_MAX_SL_DISTANCE_PERCENT,
        "entry_deviation_mode": DEFAULT_ENTRY_DEVIATION_MODE,
        "too_far_behavior": DEFAULT_TOO_FAR_BEHAVIOR,
        "lot_mode": DEFAULT_LOT_MODE,
        "fixed_lot": DEFAULT_FIXED_LOT,
        "total_lot": DEFAULT_TOTAL_LOT,
        "max_simultaneous_trades": DEFAULT_MAX_SIMULTANEOUS_TRADES,
        "max_orders_per_signal": DEFAULT_MAX_ORDERS_PER_SIGNAL,
        "max_lot_per_order": DEFAULT_MAX_LOT_PER_ORDER,
        "max_total_lot": DEFAULT_MAX_TOTAL_LOT,
        "max_spread": DEFAULT_MAX_SPREAD,
        "require_direction": DEFAULT_REQUIRE_DIRECTION,
        "require_symbol": DEFAULT_REQUIRE_SYMBOL,
        "require_entry": DEFAULT_REQUIRE_ENTRY,
        "require_tp": DEFAULT_REQUIRE_TP,
        "require_sl": DEFAULT_REQUIRE_SL,
        "min_tp_count": DEFAULT_MIN_TP_COUNT,
        "kill_switch_active": False,
        "telegram_api_id": None,
        "telegram_api_hash": None,
        "mt5_terminal_path": None,
        "symbol_mappings": {"XAUUSD": "GOLD#", "GOLD": "GOLD#"},
        "log_level": DEFAULT_LOG_LEVEL,
    }
