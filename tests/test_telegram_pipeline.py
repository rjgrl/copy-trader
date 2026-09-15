"""Phase 3 tests: pipeline, simulator, listener filtering, reconnect policy."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.config.settings import AppSettings, reset_settings_cache
from app.database.database import Database
from app.database.models import SignalRecord, TelegramSourceRecord
from app.database.repositories import SignalRepository, TelegramSourceRepository
from app.signals.models import SignalStatus
from app.telegram.listener import TelegramListener
from app.telegram.models import IncomingTelegramMessage
from app.telegram.pipeline import SignalPipeline
from app.utils.reconnect import ReconnectPolicy
from app.telegram.simulator import SAMPLE_SELL_XAUUSD, TelegramSimulator
from app.telegram.sources import TelegramSourceManager, classify_entity
from app.utils.time import utc_now


@pytest.fixture
def settings(tmp_path: Path) -> AppSettings:
    reset_settings_cache()
    s = AppSettings(
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "logs",
        telegram_api_id=12345,
        telegram_api_hash="fakehash",
    )
    s.ensure_directories()
    return s


@pytest.fixture
def db(settings: AppSettings) -> Database:
    database = Database(settings.database_path)
    database.initialize()
    return database


@pytest.fixture
def pipeline(settings: AppSettings, db: Database) -> SignalPipeline:
    return SignalPipeline(
        settings,
        SignalRepository(db),
        source_repo=TelegramSourceRepository(db),
    )


class TestSignalPipeline:
    def test_valid_signal_reaches_validated(self, pipeline: SignalPipeline) -> None:
        msg = IncomingTelegramMessage(
            chat_id=-1001,
            message_id=18392,
            text=SAMPLE_SELL_XAUUSD,
            date=utc_now(),
            source_name="Gold VIP",
        )
        result = pipeline.process(msg)
        assert result.status == SignalStatus.VALIDATED
        assert result.parsed is not None
        assert result.parsed.direction.value == "SELL"
        assert result.parsed.tp_count == 3
        assert result.db_id is not None

    def test_duplicate_message_not_reprocessed(self, pipeline: SignalPipeline) -> None:
        msg = IncomingTelegramMessage(
            chat_id=-1001,
            message_id=18392,
            text=SAMPLE_SELL_XAUUSD,
            date=utc_now(),
            source_name="Gold VIP",
        )
        first = pipeline.process(msg)
        second = pipeline.process(msg)
        assert first.status == SignalStatus.VALIDATED
        assert second.status == SignalStatus.DUPLICATE

    def test_missing_sl_rejected(self, pipeline: SignalPipeline) -> None:
        msg = IncomingTelegramMessage(
            chat_id=-1001,
            message_id=10,
            text="SELL XAUUSD 4291.5\nTP 4287.5\nTP 4283",
            date=utc_now(),
            source_name="Gold VIP",
        )
        result = pipeline.process(msg)
        assert result.status == SignalStatus.REJECTED
        assert "Missing Stop Loss" in (result.reason or "")

    def test_cancellation_skipped(self, pipeline: SignalPipeline) -> None:
        msg = IncomingTelegramMessage(
            chat_id=-1001,
            message_id=11,
            text="CANCEL XAUUSD",
            date=utc_now(),
            source_name="Gold VIP",
        )
        result = pipeline.process(msg)
        assert result.status == SignalStatus.SKIPPED
        assert "CANCELLATION_SIGNAL_DETECTED" in (result.reason or "")

    def test_chatter_skipped(self, pipeline: SignalPipeline) -> None:
        msg = IncomingTelegramMessage(
            chat_id=-1001,
            message_id=12,
            text="Good morning traders!",
            date=utc_now(),
            source_name="Gold VIP",
        )
        result = pipeline.process(msg)
        assert result.status == SignalStatus.SKIPPED

    @pytest.mark.asyncio
    async def test_edit_after_executed_logged(
        self, pipeline: SignalPipeline, db: Database
    ) -> None:
        repo = SignalRepository(db)
        repo.insert(
            SignalRecord(
                id=None,
                telegram_chat_id=-1001,
                telegram_message_id=99,
                telegram_message_date=None,
                source_name="Gold VIP",
                raw_message=SAMPLE_SELL_XAUUSD,
                direction="SELL",
                symbol="XAUUSD",
                mapped_mt5_symbol="XAUUSD",
                entry_price=4291.5,
                tp1=4287.5,
                tp2=None,
                tp3=None,
                additional_tps=None,
                stop_loss=4306.5,
                received_at=utc_now(),
                processed_at=utc_now(),
                actual_execution_price=4293.2,
                entry_deviation=1.7,
                status=SignalStatus.EXECUTED.value,
                failure_reason=None,
                signal_hash=None,
            )
        )
        edit = IncomingTelegramMessage(
            chat_id=-1001,
            message_id=99,
            text=SAMPLE_SELL_XAUUSD + "\n(edited)",
            date=utc_now(),
            source_name="Gold VIP",
            is_edit=True,
        )
        result = await pipeline.handle_edit(edit)
        assert result.reason == "MESSAGE_EDITED_AFTER_EXECUTION"
        assert result.status == SignalStatus.SKIPPED


class TestSimulator:
    def test_inject_sample(self, pipeline: SignalPipeline) -> None:
        sim = TelegramSimulator(pipeline)
        result = sim.inject(SAMPLE_SELL_XAUUSD)
        assert result.status == SignalStatus.VALIDATED
        assert result.parsed is not None
        assert result.parsed.symbol == "XAUUSD"


class TestReconnectPolicy:
    def test_backoff_increases(self) -> None:
        policy = ReconnectPolicy(initial_delay=1.0, max_delay=60.0, max_attempts=5, jitter=0)
        d1 = policy.next_delay()
        d2 = policy.next_delay()
        assert d1 == pytest.approx(1.0)
        assert d2 == pytest.approx(2.0)

    def test_exhausted(self) -> None:
        policy = ReconnectPolicy(max_attempts=2, jitter=0)
        policy.next_delay()
        policy.next_delay()
        assert policy.exhausted is True


class TestSourceFiltering:
    def test_disabled_sources_ignored(self, settings: AppSettings, db: Database) -> None:
        repo = TelegramSourceRepository(db)
        repo.upsert(
            TelegramSourceRecord(
                id=None,
                telegram_id=-1001,
                name="Enabled Source",
                source_type="channel",
                enabled=True,
            )
        )
        repo.upsert(
            TelegramSourceRecord(
                id=None,
                telegram_id=-1002,
                name="Disabled Source",
                source_type="channel",
                enabled=False,
            )
        )
        client = MagicMock()
        client.is_connected = True
        mgr = TelegramSourceManager(client, repo)  # type: ignore[arg-type]
        assert mgr.is_enabled(-1001) is True
        assert mgr.is_enabled(-1002) is False
        assert mgr.is_enabled(-9999) is False


class TestListenerNewMessagesOnly:
    @pytest.mark.asyncio
    async def test_listener_ignores_disabled_and_forwards_enabled(
        self, settings: AppSettings, db: Database
    ) -> None:
        repo = TelegramSourceRepository(db)
        repo.upsert(
            TelegramSourceRecord(
                id=None,
                telegram_id=-1001,
                name="Gold VIP",
                source_type="channel",
                enabled=True,
            )
        )
        client_service = MagicMock()
        client_service.is_connected = True
        fake_client = MagicMock()
        client_service.client = fake_client

        handlers: dict[type, list] = {}

        def on_decorator(event_builder):
            def wrapper(func):
                handlers.setdefault(type(event_builder), []).append(func)
                return func

            return wrapper

        fake_client.on = on_decorator

        received: list[IncomingTelegramMessage] = []

        async def on_message(msg: IncomingTelegramMessage) -> None:
            received.append(msg)

        from app.trading.startup import LiveListeningPoint
        from app.utils.time import utc_now as _utc

        point = LiveListeningPoint(
            established_at=_utc(),
            session_id="test",
            watermarks={-1001: 10},  # only msg > 10 are live
            active=True,
        )

        mgr = TelegramSourceManager(client_service, repo)
        listener = TelegramListener(
            client_service,
            mgr,
            on_message=on_message,
            listening_point=point,
        )
        listener.start()
        assert listener.is_listening
        assert listener.started_at is not None

        enabled_event = MagicMock()
        enabled_event.chat_id = -1001
        enabled_event.message = MagicMock(
            id=55,
            message=SAMPLE_SELL_XAUUSD,
            text=SAMPLE_SELL_XAUUSD,
            date=datetime.now(timezone.utc),
            reply_to_msg_id=None,
            fwd_from=None,
        )
        enabled_event.get_chat = AsyncMock(
            return_value=MagicMock(title="Gold VIP", megagroup=False)
        )
        enabled_event.get_sender = AsyncMock(return_value=MagicMock(id=1))

        disabled_event = MagicMock()
        disabled_event.chat_id = -1002
        disabled_event.message = MagicMock(
            id=56,
            message=SAMPLE_SELL_XAUUSD,
            text=SAMPLE_SELL_XAUUSD,
            date=datetime.now(timezone.utc),
            reply_to_msg_id=None,
            fwd_from=None,
        )
        disabled_event.get_chat = AsyncMock()
        disabled_event.get_sender = AsyncMock(return_value=None)

        new_handlers = [h for key, hs in handlers.items() for h in hs]
        assert new_handlers, "Expected NewMessage handler registration"
        await new_handlers[0](enabled_event)
        await new_handlers[0](disabled_event)

        assert len(received) == 1
        assert received[0].chat_id == -1001
        assert received[0].message_id == 55

    @pytest.mark.asyncio
    async def test_listener_marks_historical_below_watermark(
        self, settings: AppSettings, db: Database
    ) -> None:
        repo = TelegramSourceRepository(db)
        repo.upsert(
            TelegramSourceRecord(
                id=None,
                telegram_id=-1001,
                name="Gold VIP",
                source_type="channel",
                enabled=True,
            )
        )
        client_service = MagicMock()
        client_service.is_connected = True
        fake_client = MagicMock()
        client_service.client = fake_client
        handlers: list = []

        def on_decorator(event_builder):
            def wrapper(func):
                handlers.append(func)
                return func

            return wrapper

        fake_client.on = on_decorator
        received: list[IncomingTelegramMessage] = []

        async def on_message(msg: IncomingTelegramMessage) -> None:
            received.append(msg)

        from app.trading.startup import LiveListeningPoint
        from app.utils.time import utc_now as _utc

        point = LiveListeningPoint(
            established_at=_utc(),
            session_id="test",
            watermarks={-1001: 100},
            active=True,
        )
        mgr = TelegramSourceManager(client_service, repo)
        listener = TelegramListener(
            client_service, mgr, on_message=on_message, listening_point=point
        )
        listener.start()

        old_event = MagicMock()
        old_event.chat_id = -1001
        old_event.message = MagicMock(
            id=50,
            message=SAMPLE_SELL_XAUUSD,
            text=SAMPLE_SELL_XAUUSD,
            date=datetime.now(timezone.utc),
            reply_to_msg_id=None,
            fwd_from=None,
        )
        old_event.get_chat = AsyncMock(return_value=MagicMock(title="Gold VIP"))
        old_event.get_sender = AsyncMock(return_value=None)

        await handlers[0](old_event)
        assert len(received) == 1
        assert received[0].raw.get("historical") is True


class TestClassifyEntity:
    def test_channel_vs_group(self) -> None:
        from telethon.tl.types import Channel, Chat, User

        channel = MagicMock(spec=Channel)
        channel.megagroup = False
        channel.gigagroup = False
        assert classify_entity(channel).value == "channel"

        group = MagicMock(spec=Channel)
        group.megagroup = True
        group.gigagroup = False
        assert classify_entity(group).value == "group"

        chat = MagicMock(spec=Chat)
        assert classify_entity(chat).value == "group"

        user = MagicMock(spec=User)
        user.bot = False
        assert classify_entity(user).value == "user"

        bot = MagicMock(spec=User)
        bot.bot = True
        assert classify_entity(bot).value == "bot"
