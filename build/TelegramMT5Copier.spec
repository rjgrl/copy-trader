# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller ONEDIR spec for Telegram MT5 Copier.

Primary production build is windowed (no console).
Set TELEGRAM_MT5_CONSOLE=1 for a debug console build.

Icon (optional): place assets/TelegramMT5Copier.ico and uncomment icon= below.
"""

from __future__ import annotations

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules, copy_metadata

SPECDIR = Path(SPEC).resolve().parent  # noqa: F821 — injected by PyInstaller
ROOT = SPECDIR.parent

console = os.environ.get("TELEGRAM_MT5_CONSOLE", "0") == "1"
app_name = "TelegramMT5Copier_debug" if console else "TelegramMT5Copier"

# Optional icon — leave None until assets/TelegramMT5Copier.ico exists
_icon_candidate = ROOT / "assets" / "TelegramMT5Copier.ico"
ICON = str(_icon_candidate) if _icon_candidate.is_file() else None

hiddenimports = [
    "app",
    "app.config",
    "app.config.defaults",
    "app.config.settings",
    "app.database",
    "app.database.database",
    "app.database.models",
    "app.database.repositories",
    "app.gui",
    "app.gui.app",
    "app.gui.controller",
    "app.gui.dashboard",
    "app.gui.logs_page",
    "app.gui.main_window",
    "app.gui.orders_page",
    "app.gui.settings_page",
    "app.gui.signals_page",
    "app.gui.styles",
    "app.gui.telegram_page",
    "app.gui.worker",
    "app.main",
    "app.mt5",
    "app.mt5.client",
    "app.mt5.gateway",
    "app.mt5.service",
    "app.mt5.symbols",
    "app.signals",
    "app.signals.classifier",
    "app.signals.deduplicator",
    "app.signals.inspector",
    "app.signals.models",
    "app.signals.parser",
    "app.signals.profiles",
    "app.signals.validator",
    "app.telegram",
    "app.telegram.auth",
    "app.telegram.client",
    "app.telegram.listener",
    "app.telegram.models",
    "app.telegram.pipeline",
    "app.telegram.service",
    "app.telegram.simulator",
    "app.telegram.sources",
    "app.trading",
    "app.trading.engine",
    "app.trading.entry",
    "app.trading.executor",
    "app.trading.lifecycle",
    "app.trading.risk",
    "app.trading.safety",
    "app.trading.startup",
    "app.utils",
    "app.utils.formatting",
    "app.utils.logging",
    "app.utils.paths",
    "app.utils.reconnect",
    "app.utils.time",
    "MetaTrader5",
    "dotenv",
    # numpy / MT5 often miss these without explicit collection
    "numpy",
    "numpy._core",
    "numpy._core.multiarray",
    "numpy._core._multiarray_umath",
    "numpy.core",
    "numpy.core.multiarray",
]

hiddenimports += collect_submodules("telethon")
hiddenimports += collect_submodules("pydantic")
hiddenimports += collect_submodules("pydantic_core")
hiddenimports += collect_submodules("pydantic_settings")

datas: list = []
binaries: list = []

# MetaTrader5 depends on numpy C extensions + DLLs under numpy.libs
for pkg in ("numpy", "MetaTrader5"):
    pkg_datas, pkg_binaries, pkg_hidden = collect_all(pkg)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden

datas += copy_metadata("pydantic")
datas += copy_metadata("pydantic-settings")
try:
    datas += copy_metadata("telethon")
except Exception:
    pass
try:
    datas += copy_metadata("numpy")
except Exception:
    pass

a = Analysis(  # noqa: F821
    [str(ROOT / "launcher.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "pytest",
        "pytest_asyncio",
        "_pytest",
        "tkinter",
        "matplotlib",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=app_name,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=console,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON,
)

coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=app_name,
)
