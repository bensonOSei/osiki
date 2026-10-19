"""Decision logs: recorded on the request path, sent in background batches."""

import asyncio
import logging
import random
from collections import deque
from typing import Any

from osiki_sdk.client import EngineClient
from osiki_sdk.config import OsikiConfig

logger = logging.getLogger(__name__)

# Pending entries kept at most; on overflow the oldest are dropped.
MAX_PENDING = 10_000


class DecisionLogBatcher:
    """Queues decision log entries and sends them to the engine in batches.

    ``record`` never blocks or awaits. Every denial is kept and a success is
    kept with probability ``log_success_sample_rate``. A background task sends
    what is pending every ``log_flush_interval`` seconds, or as soon as
    ``log_batch_size`` entries are pending. A failed send is logged and its
    batch dropped: logging never retries into a struggling engine.
    """

    def __init__(self, client: EngineClient, config: OsikiConfig) -> None:
        self._client = client
        self._config = config
        self._queue: deque[dict[str, Any]] = deque(maxlen=MAX_PENDING)
        self._wake = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._stopping = False

    def record(self, entry: dict[str, Any]) -> None:
        if entry["allowed"] and not random.random() < (
            self._config.log_success_sample_rate
        ):
            return
        self._queue.append(entry)
        if len(self._queue) >= self._config.log_batch_size:
            self._wake.set()

    def start(self) -> None:
        """Start the background flush loop; safe to call repeatedly."""
        if self._task is None:
            self._stopping = False
            self._task = asyncio.create_task(self._run(), name="osiki-log-flush")

    async def stop(self) -> None:
        """Stop the flush loop (after any in-flight send) and flush the rest."""
        task, self._task = self._task, None
        if task is not None:
            self._stopping = True
            self._wake.set()
            await task
        await self._flush()

    async def _run(self) -> None:
        while not self._stopping:
            try:
                await asyncio.wait_for(
                    self._wake.wait(), timeout=self._config.log_flush_interval
                )
            except TimeoutError:
                pass
            self._wake.clear()
            if not self._stopping:
                await self._flush()

    async def _flush(self) -> None:
        if not self._queue:
            return
        batch = list(self._queue)
        self._queue.clear()
        try:
            await self._client.send_access_logs(batch)
        except Exception as exc:
            logger.warning("osiki dropped %d decision log entries: %r", len(batch), exc)
