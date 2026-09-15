"""GUI / packaged entrypoint for Telegram MT5 Copier.

PyInstaller builds should use this module as the analysis entry script.
Development CLI remains available via run.py.

Packaged helpers:
  TelegramMT5Copier.exe          → GUI (windowed build)
  TelegramMT5Copier_debug.exe auth → interactive Telegram login (console build)
"""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)

    # Allow first-time Telegram auth from the console/debug EXE:
    #   TelegramMT5Copier_debug.exe auth
    if args and args[0] in {"auth", "dialogs", "status", "simulate", "inspect", "mt5", "listen"}:
        from app.main import run

        return run(args)

    from app.gui.app import run_gui

    return run_gui()


if __name__ == "__main__":
    raise SystemExit(main())
