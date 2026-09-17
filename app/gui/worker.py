"""Background asyncio worker so the Qt UI thread never blocks."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from typing import Any

from PySide6.QtCore import QObject, QThread, Signal, Slot

logger = logging.getLogger(__name__)


class AsyncWorker(QObject):
    """Owns an asyncio event loop on a dedicated QThread."""

    started = Signal()
    error = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread = QThread()
        self.moveToThread(self._thread)
        self._thread.started.connect(self._run_loop)

    def start(self) -> None:
        self._thread.start()

    def run_and_wait(self, coro: Coroutine[Any, Any, Any], timeout: float = 6.0) -> Any:
        """Run a coroutine on the worker and wait (for shutdown)."""
        if self._loop is None or not self._loop.is_running():
            return None
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        try:
            return future.result(timeout=timeout)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Async worker wait failed: %s", exc)
            return None

    def stop(self) -> None:
        if self._loop and self._loop.is_running():
            loop = self._loop

            def _halt() -> None:
                for task in asyncio.all_tasks(loop):
                    task.cancel()
                loop.stop()

            loop.call_soon_threadsafe(_halt)
        self._thread.quit()
        if not self._thread.wait(4000):
            logger.warning("Async worker thread did not stop — terminating")
            self._thread.terminate()
            self._thread.wait(2000)

    @Slot()
    def _run_loop(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self.started.emit()
        try:
            self._loop.run_forever()
        finally:
            pending = asyncio.all_tasks(self._loop)
            for task in pending:
                task.cancel()
            try:
                self._loop.run_until_complete(
                    asyncio.gather(*pending, return_exceptions=True)
                )
            except Exception:  # noqa: BLE001
                pass
            self._loop.close()

    def submit(self, coro: Coroutine[Any, Any, Any], on_done: Callable[[Any], None] | None = None) -> None:
        if self._loop is None or not self._loop.is_running():
            self.error.emit("Async worker is not running")
            return

        future = asyncio.run_coroutine_threadsafe(coro, self._loop)

        def _done(fut) -> None:
            try:
                result = fut.result()
                if on_done:
                    on_done(result)
            except Exception as exc:  # noqa: BLE001
                logger.exception("Async worker task failed")
                self.error.emit(str(exc))

        future.add_done_callback(_done)
