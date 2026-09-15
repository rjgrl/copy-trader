"""Telegram message → signal processing pipeline.

Path to execution (MT5 wired later):
  Source whitelist → Classifier → Provider parser → Validator →
  Entry/Safety (later) → Trade Engine → order_send()

No shortcuts. When uncertain: do not trade.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field

from app.config.settings import AppSettings
from app.database.models import SignalRecord
from app.database.repositories import SignalRepository, TelegramSourceRepository
from app.signals.classifier import MessageClassifier, MessageKind
from app.signals.deduplicator import SignalDeduplicator
from app.signals.models import (
    ParsedSignal,
    SignalStatus,
    ValidationResult,
)
from app.signals.parser import DefaultSignalParser
from app.signals.profiles import ProfileRegistry
from app.signals.validator import SignalValidator
from app.telegram.models import IncomingTelegramMessage
from app.trading.engine import EntryCheckResult, IntelligentEntryEngine
from app.trading.executor import ExecutionResult, SignalTradeExecutor
from app.trading.lifecycle import InvalidTransitionError, transition
from app.trading.startup import LiveListeningPoint
from app.utils.time import LatencyTimestamps, ms_between, utc_now

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PipelineResult:
    """Outcome of processing one Telegram message."""

    status: SignalStatus
    message: IncomingTelegramMessage
    parsed: ParsedSignal | None = None
    validation: ValidationResult | None = None
    entry_check: EntryCheckResult | None = None
    execution: ExecutionResult | None = None
    db_id: int | None = None
    reason: str | None = None
    latency: LatencyTimestamps = field(default_factory=LatencyTimestamps)
    notes: list[str] = field(default_factory=list)
    message_kind: str | None = None
    profile_name: str | None = None


class SignalPipeline:
    """Thread-safe processing of Telegram messages into persisted signals."""

    def __init__(
        self,
        settings: AppSettings,
        signal_repo: SignalRepository,
        source_repo: TelegramSourceRepository | None = None,
        *,
        parser: DefaultSignalParser | None = None,
        validator: SignalValidator | None = None,
        classifier: MessageClassifier | None = None,
        profiles: ProfileRegistry | None = None,
        listening_point: LiveListeningPoint | None = None,
        entry_engine: IntelligentEntryEngine | None = None,
        trade_executor: SignalTradeExecutor | None = None,
        kill_switch_active: bool = False,
    ) -> None:
        self.settings = settings
        self._signals = signal_repo
        self._sources = source_repo
        self._profiles = profiles or ProfileRegistry()
        self._classifier = classifier or MessageClassifier()
        self._parser = parser
        self._validator = validator
        self.listening_point = listening_point
        self.entry_engine = entry_engine
        self.trade_executor = trade_executor
        self.kill_switch_active = kill_switch_active
        self._dedup = SignalDeduplicator(signal_repo)
        self._lock = threading.RLock()
        self._processing_keys: set[tuple[int, int]] = set()

    async def handle_message(self, message: IncomingTelegramMessage) -> PipelineResult:
        return self.process(message)

    async def handle_edit(self, message: IncomingTelegramMessage) -> PipelineResult:
        """Edited messages never become new trades in V1."""
        existing = self._signals.get_by_telegram_ids(message.chat_id, message.message_id)
        if existing is None:
            logger.info(
                "Edited message has no prior record — ignoring (chat=%s msg=%s)",
                message.chat_id,
                message.message_id,
            )
            return PipelineResult(
                status=SignalStatus.SKIPPED,
                message=message,
                reason="Edit for unknown message",
                notes=["MESSAGE_EDIT_IGNORED"],
            )

        terminal_executed = existing.status in {
            SignalStatus.EXECUTED.value,
            SignalStatus.PARTIALLY_EXECUTED.value,
            SignalStatus.EXECUTING.value,
            SignalStatus.EXECUTION_REQUIRES_REVIEW.value,
        }
        if terminal_executed:
            logger.warning(
                "MESSAGE_EDITED_AFTER_EXECUTION chat=%s msg=%s status=%s",
                message.chat_id,
                message.message_id,
                existing.status,
            )
            return PipelineResult(
                status=SignalStatus.SKIPPED,
                message=message,
                db_id=existing.id,
                reason="MESSAGE_EDITED_AFTER_EXECUTION",
                notes=["MESSAGE_EDITED_AFTER_EXECUTION"],
            )

        logger.info(
            "Message edited before execution — not re-processing "
            "(chat=%s msg=%s prior_status=%s)",
            message.chat_id,
            message.message_id,
            existing.status,
        )
        return PipelineResult(
            status=SignalStatus.SKIPPED,
            message=message,
            db_id=existing.id,
            reason="MESSAGE_EDITED_BEFORE_EXECUTION",
            notes=["MESSAGE_EDITED_BEFORE_EXECUTION"],
        )

    async def handle_delete(self, message: IncomingTelegramMessage) -> PipelineResult:
        """Message deletion must not close or modify MT5 positions in V1."""
        logger.info(
            "MESSAGE_DELETED chat=%s msg=%s — preserving execution records",
            message.chat_id,
            message.message_id,
        )
        return PipelineResult(
            status=SignalStatus.SKIPPED,
            message=message,
            reason="MESSAGE_DELETED_NO_TRADE_ACTION",
            notes=["MESSAGE_DELETED_NO_TRADE_ACTION"],
        )

    def process(self, message: IncomingTelegramMessage) -> PipelineResult:
        """Synchronous core processing path (also used by simulator / inspector feeds)."""
        received_at = utc_now()
        latency = LatencyTimestamps(
            telegram_at=message.date,
            received_at=received_at,
        )
        key = (message.chat_id, message.message_id)

        with self._lock:
            if key in self._processing_keys:
                return PipelineResult(
                    status=SignalStatus.DUPLICATE,
                    message=message,
                    reason="Already processing",
                    latency=latency,
                )
            if self._dedup.is_duplicate(message.chat_id, message.message_id):
                return PipelineResult(
                    status=SignalStatus.DUPLICATE,
                    message=message,
                    reason="Duplicate telegram_chat_id + message_id",
                    latency=latency,
                    notes=["DUPLICATE"],
                )
            self._processing_keys.add(key)

        try:
            return self._process_locked(message, latency)
        finally:
            with self._lock:
                self._processing_keys.discard(key)

    def _process_locked(
        self,
        message: IncomingTelegramMessage,
        latency: LatencyTimestamps,
    ) -> PipelineResult:
        profile = self._profiles.get_profile(message.chat_id)
        parser = self._parser or self._profiles.get_parser(message.chat_id)
        validator = self._validator or SignalValidator(
            profile.to_validation_rules(),
            validate_tp_ordering=profile.validate_tp_ordering,
            provider_matched=True,
        )

        logger.info(
            "Processing message chat=%s msg=%s source=%s profile=%s",
            message.chat_id,
            message.message_id,
            message.source_name,
            profile.name,
        )
        logger.debug("Raw message:\n%s", message.text)

        db_id = self._insert_received(message, latency)

        # --- Historical / downtime gate (message ID, not PC clock) ---
        is_historical = bool(message.raw.get("historical"))
        if (
            not is_historical
            and self.listening_point is not None
            and self.listening_point.is_historical(message.chat_id, message.message_id)
        ):
            is_historical = True

        if is_historical:
            reason = "HISTORICAL_SIGNAL_SKIPPED"
            logger.warning(
                "%s chat=%s msg=%s — will NOT execute",
                reason,
                message.chat_id,
                message.message_id,
            )
            self._finalize(db_id, SignalStatus.SKIPPED, reason=reason, latency=latency)
            return PipelineResult(
                status=SignalStatus.SKIPPED,
                message=message,
                db_id=db_id,
                reason=reason,
                latency=latency,
                notes=[reason],
                profile_name=profile.name,
                message_kind="historical",
            )

        # --- Classifier (false-positive protection) ---
        classification = self._classifier.classify(message.text)
        if classification.kind == MessageKind.CANCELLATION:
            reason = "CANCELLATION_SIGNAL_DETECTED"
            logger.warning("%s — not closing trades in V1", reason)
            self._finalize(db_id, SignalStatus.SKIPPED, reason=reason, latency=latency)
            return PipelineResult(
                status=SignalStatus.SKIPPED,
                message=message,
                db_id=db_id,
                reason=reason,
                latency=latency,
                notes=[reason],
                message_kind=classification.kind.value,
                profile_name=profile.name,
            )

        if classification.kind in {
            MessageKind.TRADE_UPDATE,
            MessageKind.ANALYSIS,
            MessageKind.CHATTER,
            MessageKind.EMPTY,
        }:
            reason = classification.reason
            logger.info(
                "Non-executable message (%s): %s",
                classification.kind.value,
                reason,
            )
            self._finalize(db_id, SignalStatus.SKIPPED, reason=reason, latency=latency)
            return PipelineResult(
                status=SignalStatus.SKIPPED,
                message=message,
                db_id=db_id,
                reason=reason,
                latency=latency,
                notes=[classification.kind.value, reason],
                message_kind=classification.kind.value,
                profile_name=profile.name,
            )

        # --- Deterministic parse (single-message requirement for V1) ---
        parsed = parser.parse(message.text)
        parsed.message_kind = classification.kind.value
        parsed.parser_name = profile.parser_name
        try:
            transition(SignalStatus.RECEIVED, SignalStatus.PARSED)
        except InvalidTransitionError:
            pass

        if parsed.is_cancellation:
            reason = "CANCELLATION_SIGNAL_DETECTED"
            self._finalize(
                db_id, SignalStatus.SKIPPED, parsed=parsed, reason=reason, latency=latency
            )
            return PipelineResult(
                status=SignalStatus.SKIPPED,
                message=message,
                parsed=parsed,
                db_id=db_id,
                reason=reason,
                latency=latency,
                notes=[reason],
                message_kind=MessageKind.CANCELLATION.value,
                profile_name=profile.name,
            )

        logger.info(
            "Signal candidate: %s %s entry=%s TPs=%s SL=%s",
            parsed.direction.value if parsed.direction else "?",
            parsed.symbol,
            parsed.entry,
            parsed.take_profits,
            parsed.stop_loss,
        )

        validation = validator.validate(parsed)
        if not validation.ok:
            final = validation.status
            self._finalize(
                db_id,
                final,
                parsed=parsed,
                reason=validation.reason,
                latency=latency,
            )
            logger.info("Signal %s: %s", final.value, validation.reason)
            return PipelineResult(
                status=final,
                message=message,
                parsed=parsed,
                validation=validation,
                db_id=db_id,
                reason=validation.reason,
                latency=latency,
                message_kind=classification.kind.value,
                profile_name=profile.name,
            )

        mapped = self.settings.map_symbol(parsed.symbol or "")
        if latency.telegram_at and latency.received_at:
            logger.info(
                "Latency Telegram->App: %.1f ms",
                ms_between(latency.telegram_at, latency.received_at),
            )
        if validation.confidence:
            logger.info(
                "Diagnostic confidence: %s/100 (does not override hard rules)",
                validation.confidence.score,
            )

        # Persist VALIDATED before entry check
        self._finalize(
            db_id,
            SignalStatus.VALIDATED,
            parsed=parsed,
            mapped=mapped,
            latency=latency,
        )

        # --- Phase 5: Intelligent entry check (requires MT5 engine) ---
        if self.entry_engine is None:
            note = "VALIDATED - entry engine not attached (no MT5 entry check)"
            logger.info(note)
            return PipelineResult(
                status=SignalStatus.VALIDATED,
                message=message,
                parsed=parsed,
                validation=validation,
                db_id=db_id,
                reason=note,
                latency=latency,
                notes=[note],
                message_kind=classification.kind.value,
                profile_name=profile.name,
            )

        entry_check = self.entry_engine.evaluate(parsed)
        mapped = entry_check.mapped_symbol or mapped

        if not entry_check.ok:
            self._finalize(
                db_id,
                entry_check.status,
                parsed=parsed,
                mapped=mapped,
                reason=entry_check.reason,
                latency=latency,
            )
            # Store deviation / current price when available
            if entry_check.decision.current_price is not None:
                self._signals.update_status(
                    db_id,
                    entry_check.status.value,
                    failure_reason=entry_check.reason,
                    processed_at=utc_now(),
                    actual_execution_price=None,
                    entry_deviation=entry_check.decision.deviation,
                )
            return PipelineResult(
                status=entry_check.status,
                message=message,
                parsed=parsed,
                validation=validation,
                entry_check=entry_check,
                db_id=db_id,
                reason=entry_check.reason,
                latency=latency,
                notes=list(entry_check.reasons),
                message_kind=classification.kind.value,
                profile_name=profile.name,
            )

        # ENTRY_CHECKED — then Phase 6 execution if trade_executor attached
        for preview in entry_check.would_execute:
            logger.info(
                "WOULD EXECUTE: %s %s vol=%s @ %s (signal entry %s, dev=%s) TP=%s SL=%s dry_run=%s",
                preview["direction"],
                preview["symbol"],
                preview.get("volume"),
                preview["execution_price"],
                preview["signal_entry"],
                preview.get("deviation"),
                preview["take_profit"],
                preview["stop_loss"],
                preview.get("dry_run"),
            )

        self._signals.update_status(
            db_id,
            SignalStatus.ENTRY_CHECKED.value,
            failure_reason=None,
            processed_at=utc_now(),
            actual_execution_price=entry_check.decision.current_price,
            entry_deviation=entry_check.decision.deviation,
        )
        self._update_parsed_fields(db_id, parsed, mapped, SignalStatus.ENTRY_CHECKED)

        if self.trade_executor is None:
            note = (
                f"ENTRY_CHECKED at {entry_check.decision.current_price} "
                f"(deviation {entry_check.decision.deviation}) — trade executor not attached"
            )
            logger.info(note)
            return PipelineResult(
                status=SignalStatus.ENTRY_CHECKED,
                message=message,
                parsed=parsed,
                validation=validation,
                entry_check=entry_check,
                db_id=db_id,
                reason=note,
                latency=latency,
                notes=[note, "VALID_MARKET_EXECUTION"],
                message_kind=classification.kind.value,
                profile_name=profile.name,
            )

        # Pre-execution gates (before EXECUTING)
        if self.kill_switch_active:
            note = "ENTRY_CHECKED - kill switch active, execution blocked"
            logger.warning(note)
            return PipelineResult(
                status=SignalStatus.ENTRY_CHECKED,
                message=message,
                parsed=parsed,
                validation=validation,
                entry_check=entry_check,
                db_id=db_id,
                reason=note,
                latency=latency,
                notes=[note],
                message_kind=classification.kind.value,
                profile_name=profile.name,
            )

        if not self.settings.dry_run and not self.settings.copy_trading_enabled:
            note = (
                "ENTRY_CHECKED - copy trading disabled and dry_run=false; "
                "not sending live orders"
            )
            logger.info(note)
            return PipelineResult(
                status=SignalStatus.ENTRY_CHECKED,
                message=message,
                parsed=parsed,
                validation=validation,
                entry_check=entry_check,
                db_id=db_id,
                reason=note,
                latency=latency,
                notes=[note],
                message_kind=classification.kind.value,
                profile_name=profile.name,
            )

        # --- Phase 6: MT5 order execution (one order per TP) ---
        self._signals.update_status(
            db_id,
            SignalStatus.EXECUTING.value,
            processed_at=utc_now(),
            actual_execution_price=entry_check.decision.current_price,
            entry_deviation=entry_check.decision.deviation,
        )
        logger.info("Signal %s EXECUTING (%s TP orders)", db_id, parsed.tp_count)

        execution = self.trade_executor.execute(
            parsed,
            entry_check,
            signal_db_id=db_id,
            telegram_message_id=message.message_id,
            kill_switch_active=False,
        )

        executed_at = utc_now()
        latency.executed_at = executed_at
        self._signals.update_status(
            db_id,
            execution.status.value,
            failure_reason=execution.reason if execution.status != SignalStatus.EXECUTED else None,
            processed_at=executed_at,
            actual_execution_price=entry_check.decision.current_price,
            entry_deviation=entry_check.decision.deviation,
            app_to_mt5_ms=latency.app_to_mt5_ms,
            total_latency_ms=latency.total_ms,
        )
        self._update_parsed_fields(db_id, parsed, mapped, execution.status)

        for outcome in execution.outcomes:
            mark = "OK" if outcome.result.ok else "FAIL"
            logger.info(
                "TP%s %s ticket=%s retcode=%s (%s) dry_run=%s",
                outcome.tp_index,
                mark,
                outcome.result.ticket,
                outcome.result.retcode,
                outcome.result.retcode_description,
                outcome.result.dry_run,
            )

        note = (
            f"{execution.status.value}: {execution.success_count}/{len(execution.outcomes)} "
            f"orders ok; dry_run={execution.dry_run}"
        )
        logger.info(note)
        return PipelineResult(
            status=execution.status,
            message=message,
            parsed=parsed,
            validation=validation,
            entry_check=entry_check,
            execution=execution,
            db_id=db_id,
            reason=note,
            latency=latency,
            notes=[note, *execution.reasons],
            message_kind=classification.kind.value,
            profile_name=profile.name,
        )

    def _insert_received(
        self,
        message: IncomingTelegramMessage,
        latency: LatencyTimestamps,
    ) -> int:
        record = SignalRecord(
            id=None,
            telegram_chat_id=message.chat_id,
            telegram_message_id=message.message_id,
            telegram_message_date=message.date,
            source_name=message.source_name,
            raw_message=message.text,
            direction=None,
            symbol=None,
            mapped_mt5_symbol=None,
            entry_price=None,
            tp1=None,
            tp2=None,
            tp3=None,
            additional_tps=None,
            stop_loss=None,
            received_at=latency.received_at or utc_now(),
            processed_at=None,
            actual_execution_price=None,
            entry_deviation=None,
            status=SignalStatus.RECEIVED.value,
            failure_reason=None,
            signal_hash=None,
            telegram_to_app_ms=(
                ms_between(latency.telegram_at, latency.received_at)
                if latency.telegram_at and latency.received_at
                else None
            ),
        )
        return self._signals.insert(record)

    def _update_parsed_fields(
        self,
        db_id: int,
        parsed: ParsedSignal,
        mapped: str | None,
        status: SignalStatus,
    ) -> None:
        additional = parsed.additional_tps()
        self._signals.update_parsed(
            db_id,
            direction=parsed.direction.value if parsed.direction else None,
            symbol=parsed.symbol,
            mapped_mt5_symbol=mapped,
            entry_price=parsed.entry,
            tp1=parsed.tp1,
            tp2=parsed.tp2,
            tp3=parsed.tp3,
            additional_tps=json.dumps(additional) if additional else None,
            stop_loss=parsed.stop_loss,
            status=status.value,
            signal_hash=SignalDeduplicator.compute_hash(parsed),
        )

    def _finalize(
        self,
        db_id: int,
        status: SignalStatus,
        *,
        parsed: ParsedSignal | None = None,
        mapped: str | None = None,
        reason: str | None = None,
        latency: LatencyTimestamps | None = None,
    ) -> None:
        if parsed is not None:
            self._update_parsed_fields(
                db_id,
                parsed,
                mapped or self.settings.map_symbol(parsed.symbol or ""),
                status,
            )
        self._signals.update_status(
            db_id,
            status.value,
            failure_reason=reason,
            processed_at=utc_now(),
            telegram_to_app_ms=(latency.telegram_to_app_ms if latency else None),
        )


class KillSwitch:
    """Immediate stop for new signal execution (monitoring may continue)."""

    def __init__(self) -> None:
        self._active = False
        self._lock = threading.Lock()

    @property
    def active(self) -> bool:
        with self._lock:
            return self._active

    def activate(self) -> None:
        with self._lock:
            self._active = True
        logger.warning("KILL SWITCH ACTIVATED - new signal execution stopped")

    def deactivate(self) -> None:
        with self._lock:
            self._active = False
        logger.info("Kill switch deactivated")
