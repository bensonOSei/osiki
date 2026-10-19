"""The policy store: a cached snapshot, cached user bundles and a version poller."""

import asyncio
import functools
import logging
import time
from collections import OrderedDict
from collections.abc import Callable

from osiki_sdk._decision.models import Snapshot, UserBundle
from osiki_sdk.client import EngineClient
from osiki_sdk.config import OsikiConfig

logger = logging.getLogger(__name__)


class PolicyStore:
    """Holds what local decisions need and keeps it fresh by polling versions.

    The snapshot is refreshed when the engine's config version moves; every
    cached bundle is dropped when its assignments version moves. Bundles live
    in an LRU of ``bundle_cache_size`` entries for at most ``bundle_ttl``
    seconds of ``clock`` time; a ``None`` (unknown user) is cached the same way.
    """

    def __init__(
        self,
        client: EngineClient,
        config: OsikiConfig,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client = client
        self._config = config
        self.clock = clock
        self.snapshot: Snapshot | None = None
        self._etag: str | None = None
        self._assignments_version: int | None = None
        self._bundles: OrderedDict[str, tuple[float, UserBundle | None]] = OrderedDict()
        # Bumped by every invalidation, so a fetch that started before one
        # never caches what it read.
        self._generation = 0
        # One shared fetch per user with a cold cache.
        self._inflight: dict[str, asyncio.Task[UserBundle | None]] = {}

    @property
    def available(self) -> bool:
        """Whether a snapshot has loaded at least once."""
        return self.snapshot is not None

    async def refresh_snapshot(self) -> None:
        snapshot, etag = await self._client.get_snapshot(self._etag)
        if snapshot is not None:
            self.snapshot = snapshot
            self._etag = etag

    async def get_bundle(self, user_id: str) -> UserBundle | None:
        """The user's bundle, from the cache or one shared engine fetch.

        Concurrent misses for one user share a single in-flight fetch: every
        caller gets its result or its exception. A caller's cancellation never
        cancels the shared fetch.
        """
        entry = self._bundles.get(user_id)
        if entry is not None and entry[0] > self.clock():
            self._bundles.move_to_end(user_id)
            return entry[1]
        task = self._inflight.get(user_id)
        if task is None:
            task = asyncio.create_task(
                self._fetch_bundle(user_id, self._generation),
                name="osiki-bundle-fetch",
            )
            self._inflight[user_id] = task
            task.add_done_callback(functools.partial(self._fetch_done, user_id))
        return await asyncio.shield(task)

    async def _fetch_bundle(self, user_id: str, generation: int) -> UserBundle | None:
        bundle = await self._client.get_bundle(user_id)
        if generation == self._generation:
            self._bundles[user_id] = (self.clock() + self._config.bundle_ttl, bundle)
            self._bundles.move_to_end(user_id)
            while len(self._bundles) > self._config.bundle_cache_size:
                self._bundles.popitem(last=False)
        return bundle

    def _fetch_done(
        self, user_id: str, task: "asyncio.Task[UserBundle | None]"
    ) -> None:
        if self._inflight.get(user_id) is task:
            del self._inflight[user_id]
        if not task.cancelled():
            # Every waiter may have been cancelled: mark the error retrieved.
            task.exception()

    def invalidate_user(self, user_id: str) -> None:
        self._generation += 1
        self._bundles.pop(user_id, None)
        # A later caller must not join a fetch that started before this.
        self._inflight.pop(user_id, None)

    def clear_bundles(self) -> None:
        self._generation += 1
        self._bundles.clear()
        self._inflight.clear()

    async def poll_once(self) -> None:
        config_version, assignments_version = await self._client.get_versions()
        if assignments_version != self._assignments_version:
            self.clear_bundles()
            self._assignments_version = assignments_version
        # Compared with the loaded snapshot, so a failed refresh retries.
        if self.snapshot is None or self.snapshot.version != config_version:
            await self.refresh_snapshot()

    async def run_poller(self) -> None:
        while True:
            try:
                await self.poll_once()
            except Exception as exc:
                logger.warning("osiki poll failed; keeping the last snapshot: %r", exc)
            await asyncio.sleep(self._config.poll_interval)
