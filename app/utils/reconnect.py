"""Exponential backoff helper for Telegram/MT5 reconnection."""

from __future__ import annotations

import asyncio
import logging
import random

logger = logging.getLogger(__name__)


class ReconnectPolicy:
    """Controlled reconnection with exponential backoff and jitter."""

    def __init__(
        self,
        initial_delay: float = 1.0,
        max_delay: float = 60.0,
        max_attempts: int = 10,
        multiplier: float = 2.0,
        jitter: float = 0.2,
    ) -> None:
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self.max_attempts = max_attempts
        self.multiplier = multiplier
        self.jitter = jitter
        self.attempts = 0

    def reset(self) -> None:
        self.attempts = 0

    @property
    def exhausted(self) -> bool:
        return self.attempts >= self.max_attempts

    def next_delay(self) -> float:
        delay = min(
            self.initial_delay * (self.multiplier**self.attempts),
            self.max_delay,
        )
        self.attempts += 1
        if self.jitter > 0:
            delay *= 1.0 + random.uniform(-self.jitter, self.jitter)
        return max(0.1, delay)

    async def wait(self) -> bool:
        """Sleep for the next backoff delay. Returns False if attempts exhausted."""
        if self.exhausted:
            logger.error("Reconnect attempts exhausted (%s)", self.max_attempts)
            return False
        delay = self.next_delay()
        logger.warning(
            "Reconnecting in %.1fs (attempt %s/%s)",
            delay,
            self.attempts,
            self.max_attempts,
        )
        await asyncio.sleep(delay)
        return True
