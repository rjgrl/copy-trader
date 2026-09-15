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

    def stop(self) -> None:
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.quit()
        if not self._thread.wait(5000):
            logger.warning("Async worker thread did not stop cleanly")

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
            self._loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
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
