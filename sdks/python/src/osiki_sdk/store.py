"""The policy store: a cached snapshot, cached user bundles and a version poller."""

import asyncio
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
        entry = self._bundles.get(user_id)
        if entry is not None and entry[0] > self.clock():
            self._bundles.move_to_end(user_id)
            return entry[1]
        generation = self._generation
        bundle = await self._client.get_bundle(user_id)
        if generation == self._generation:
            self._bundles[user_id] = (self.clock() + self._config.bundle_ttl, bundle)
            self._bundles.move_to_end(user_id)
            while len(self._bundles) > self._config.bundle_cache_size:
                self._bundles.popitem(last=False)
        return bundle

    def invalidate_user(self, user_id: str) -> None:
        self._generation += 1
        self._bundles.pop(user_id, None)

    def clear_bundles(self) -> None:
        self._generation += 1
        self._bundles.clear()

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
