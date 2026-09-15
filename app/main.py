"""Application bootstrap and CLI entry points."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from app.config.settings import AppSettings, get_settings
from app.database.database import Database
from app.utils.logging import setup_logging

logger = logging.getLogger(__name__)


def bootstrap(settings: AppSettings | None = None) -> tuple[AppSettings, Database]:
    """Initialize logging, settings, and SQLite database."""
    settings = settings or get_settings()
    setup_logging(
        log_dir=settings.log_dir,
        level=settings.log_level,
        console=True,
    )
    settings.ensure_directories()
    db = Database(settings.database_path)
    db.initialize()
    logger.info("Application bootstrap complete (v%s)", _version())
    logger.info(
        "Data dir: %s | DB: %s | Dry run: %s",
        settings.data_dir,
        settings.database_path,
        settings.dry_run,
    )
    return settings, db


def _version() -> str:
    from app import __version__

    return __version__


def _cmd_status(settings: AppSettings, db: Database) -> int:
    print("=" * 60)
    print("Telegram MT5 Copier — Phase 7")
    print("=" * 60)
    print(f"Version:     {_version()}")
    print(f"Data dir:    {settings.data_dir}")
    print(f"Database:    {settings.database_path}")
    print(f"Dry run:     {settings.dry_run}")
    print(f"Copy trade:  {settings.copy_trading_enabled}")
    print(f"API ID set:  {bool(settings.telegram_api_id)}")
    print(f"API hash:    {'set' if settings.telegram_api_hash else 'missing'}")
    print(f"Session:     {settings.telegram_session_path}.session")
    print(f"MT5 path:    {settings.mt5_terminal_path or '(auto)'}")
    print(f"Mappings:    {settings.symbol_mappings}")
    print(f"DB tables:   {', '.join(db.table_names())}")
    print()
    print("Commands:")
    print("  python run.py                  Show status")
    print("  python run.py auth             Interactive Telegram login")
    print("  python run.py dialogs          List Telegram dialogs")
    print("  python run.py simulate         Inject a sample signal")
    print("  python run.py inspect          Signal Inspector")
    print("  python run.py listen           Safe Telegram listen")
    print("  python run.py mt5              MT5 connection / account / symbols")
    print("  python run.py gui              Launch desktop GUI")
    print("=" * 60)
    return 0


def _cmd_mt5(settings: AppSettings, db: Database) -> int:
    from app.mt5.client import MT5Error
    from app.mt5.service import MT5Service

    service = MT5Service(settings)
    try:
        account = service.connect()
        terminal = service.client.get_terminal_info()
        print("=" * 60)
        print("MT5 CONNECTION")
        print("=" * 60)
        print(f"Status:     CONNECTED")
        print(f"Account:    {account.login}")
        print(f"Name:       {account.name}")
        print(f"Server:     {account.server}")
        print(f"Company:    {account.company}")
        print(f"Currency:   {account.currency}")
        print(f"Balance:    {account.balance:.2f}")
        print(f"Equity:     {account.equity:.2f}")
        print(f"Margin:     {account.margin:.2f}")
        print(f"Free:       {account.margin_free:.2f}")
        print(f"Trade OK:   {account.trade_allowed} (expert={account.trade_expert})")
        if terminal:
            print(f"Terminal:   {terminal.name} build {terminal.build}")
            print(f"Path:       {terminal.path}")
            print(f"Ping:       {terminal.ping_last} us")
        print()
        print("Symbol checks (from mappings):")
        for tg_sym, mt5_sym in settings.symbol_mappings.items():
            result = service.validate_symbol(tg_sym, direction="SELL")
            if result.ok and result.spec and result.tick:
                spread_p, spread_pts = service.pricing.spread(result.mt5_symbol)
                print(
                    f"  {tg_sym} -> {result.mt5_symbol}: OK  "
                    f"bid={result.tick.bid} ask={result.tick.ask}  "
                    f"point={result.spec.point}  "
                    f"spread={spread_p:.5f} ({spread_pts:.1f} pts)  "
                    f"mode={result.spec.trade_mode.value}"
                )
            else:
                print(f"  {tg_sym} -> {mt5_sym}: FAIL - {result.reason}")
                hints = service.symbols.find_symbols(tg_sym[:3], limit=8)
                if hints:
                    print(f"    hints: {', '.join(hints)}")
        print("=" * 60)
        return 0
    except MT5Error as exc:
        print(f"MT5 error: {exc}")
        return 1
    except Exception as exc:
        logger.exception("MT5 command failed")
        print(f"Unexpected error: {exc}")
        return 1
    finally:
        service.disconnect()


async def _cmd_auth(settings: AppSettings, db: Database) -> int:
    from app.telegram.service import TelegramService

    service = TelegramService(settings, db)
    try:
        await service.connect(interactive_auth=True)
        print("Telegram authorization successful.")
        print(f"Status: {service.client_service.auth_status.step.value}")
        print(f"User:   {service.client_service.auth_status.username or service.client_service.auth_status.user_id}")
        return 0
    except Exception as exc:
        logger.error("Auth failed: %s", exc)
        return 1
    finally:
        await service.stop()


async def _cmd_dialogs(settings: AppSettings, db: Database) -> int:
    from app.telegram.service import TelegramService

    service = TelegramService(settings, db)
    try:
        await service.connect(interactive_auth=False)
        if not service.client_service.is_authorized:
            print("Not authorized. Run: python run.py auth")
            return 1
        dialogs = await service.sources.fetch_dialogs()
        print(f"{'ID':<16} {'Type':<10} {'Mon':<4} Name")
        print("-" * 70)
        for d in dialogs:
            mon = "Y" if d.is_monitored else ""
            print(f"{d.telegram_id:<16} {d.dialog_type.value:<10} {mon:<4} {d.name}")
        print(f"\n{len(dialogs)} dialogs. Enable sources via GUI (Phase 7) or DB.")
        return 0
    except Exception as exc:
        logger.error("Failed to list dialogs: %s", exc)
        return 1
    finally:
        await service.stop()


def _cmd_simulate(settings: AppSettings, db: Database) -> int:
    from time import time_ns

    from app.mt5.client import MT5Error
    from app.mt5.gateway import MockMT5Gateway
    from app.telegram.service import TelegramService
    from app.telegram.simulator import SAMPLE_SELL_XAUUSD

    # Use mock market near sample entry so Phase 6 dry-run is demonstrable.
    # Live gold may already be past TP1 (correctly rejected by entry protection).
    mock = MockMT5Gateway()
    mock.set_tick("GOLD#", bid=4293.2, ask=4293.5)
    service = TelegramService(settings, db, mt5_gateway=mock, attach_mt5=True)
    assert service.mt5 is not None
    service.mt5.connect()
    used = "mock (bid=4293.2 — use live MT5 via listen/mt5)"

    msg_id = int(time_ns() % 2_000_000_000) + 1
    result = service.simulator.inject(SAMPLE_SELL_XAUUSD, message_id=msg_id)
    print("=" * 60)
    print("SIMULATION RESULT (Phase 6 dry-run execution)")
    print("=" * 60)
    print(f"MT5 data: {used}")
    print(f"Mapping:  XAUUSD -> {settings.map_symbol('XAUUSD')}")
    print(f"Status:   {result.status.value}")
    print(f"DB id:    {result.db_id}")
    print(f"Msg id:   {result.message.message_id}")
    print(f"Reason:   {result.reason}")
    print(f"Dry run:  {settings.dry_run} | Copy trading: {settings.copy_trading_enabled}")
    if result.parsed:
        print(f"Direction:{result.parsed.direction}")
        print(f"Symbol:   {result.parsed.symbol} -> {settings.map_symbol(result.parsed.symbol or '')}")
        print(f"Entry:    {result.parsed.entry}")
        print(f"TPs:      {result.parsed.take_profits}")
        print(f"SL:       {result.parsed.stop_loss}")
    if result.entry_check and result.entry_check.snapshot:
        snap = result.entry_check.snapshot
        d = result.entry_check.decision
        print(f"Market:   bid={snap.tick.bid} ask={snap.tick.ask}")
        print(f"Exec @ :  {d.current_price} (deviation={d.deviation})")
        print(f"Spread:   {snap.spread_price:.5f} ({snap.spread_points:.1f} pts)")
        print(f"Point:    {snap.spec.point}")
    if result.execution:
        print(
            f"Orders:   {result.execution.success_count}/{len(result.execution.outcomes)} "
            f"ok (dry_run={result.execution.dry_run})"
        )
        for o in result.execution.outcomes:
            print(
                f"  TP{o.tp_index}: {o.result.status_label} "
                f"ticket={o.result.ticket} vol={o.volume} tp={o.take_profit} "
                f"retcode={o.result.retcode}"
            )
    result2 = service.simulator.inject(
        SAMPLE_SELL_XAUUSD,
        message_id=result.message.message_id,
    )
    print(f"Replay:   {result2.status.value} ({result2.reason})")
    print("=" * 60)
    if service.mt5:
        try:
            service.mt5.disconnect()
        except MT5Error:
            pass
    return 0


async def _cmd_listen(settings: AppSettings, db: Database) -> int:
    from app.telegram.service import TelegramService

    service = TelegramService(settings, db)
    try:
        await service.connect(interactive_auth=False)
        if not service.client_service.is_authorized:
            print("Not authorized. Run: python run.py auth")
            return 1
        enabled = service.sources.list_enabled()
        if not enabled:
            print(
                "No enabled Telegram sources. Add via dialogs + DB, or wait for GUI.\n"
                "Example: use simulate for offline testing."
            )
            return 1
        print(f"Safe startup for {len(enabled)} source(s). Ctrl+C to stop.")
        for src in enabled:
            print(f"  • {src.name} ({src.telegram_id})")
        await service.start_listening()
        point = service.startup.listening_point
        if point:
            print(f"Live session: {point.session_id}")
            print(f"Watermarks:   {point.watermarks}")
        print("Waiting for NEW messages only (historical will be SKIPPED).")
        await service.client_service.run_until_disconnected()
        return 0
    except KeyboardInterrupt:
        print("\nStopped.")
        return 0
    except Exception as exc:
        logger.error("Listen failed: %s", exc)
        return 1
    finally:
        await service.stop()


def _cmd_inspect(settings: AppSettings, db: Database) -> int:
    from app.signals.inspector import SignalInspector
    from app.telegram.simulator import SAMPLE_SELL_XAUUSD

    print("Signal Inspector — paste a Telegram message.")
    print("End with a blank line (or Ctrl+Z then Enter on Windows).")
    print("Tip: press Enter twice immediately to inspect the sample SELL XAUUSD signal.")
    print("-" * 50)
    lines: list[str] = []
    try:
        while True:
            line = input()
            if line == "" and lines:
                break
            if line == "" and not lines:
                lines = SAMPLE_SELL_XAUUSD.splitlines()
                break
            lines.append(line)
    except EOFError:
        pass
    text = "\n".join(lines).strip()
    if not text:
        print("No message provided.")
        return 1
    result = SignalInspector().inspect(text)
    print(result.format_report())
    return 0 if result.signal_detected or result.message_kind.value != "empty" else 1


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Telegram MT5 Signal Copier")
    parser.add_argument(
        "command",
        nargs="?",
        default="status",
        choices=["status", "auth", "dialogs", "simulate", "listen", "inspect", "mt5", "gui"],
        help="CLI command",
    )
    args = parser.parse_args(argv)

    if args.command == "gui":
        from app.gui.app import run_gui

        return run_gui()

    try:
        settings, db = bootstrap()
    except Exception:
        logging.exception("Bootstrap failed")
        return 1

    try:
        if args.command == "status":
            return _cmd_status(settings, db)
        if args.command == "simulate":
            return _cmd_simulate(settings, db)
        if args.command == "inspect":
            return _cmd_inspect(settings, db)
        if args.command == "mt5":
            return _cmd_mt5(settings, db)
        if args.command == "auth":
            return asyncio.run(_cmd_auth(settings, db))
        if args.command == "dialogs":
            return asyncio.run(_cmd_dialogs(settings, db))
        if args.command == "listen":
            return asyncio.run(_cmd_listen(settings, db))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(run())
