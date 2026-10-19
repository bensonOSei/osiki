"""The ``Osiki`` facade: local check/filter, loaders, sync and lifecycle."""

import asyncio
import logging
import time
import weakref
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
from starlette.applications import Starlette
from starlette.requests import Request

from osiki_sdk._decision.decide import decide, list_filter
from osiki_sdk._decision.models import (
    Decision,
    DecisionRequest,
    FilterResult,
    Snapshot,
)
from osiki_sdk.client import EngineClient
from osiki_sdk.config import OsikiConfig
from osiki_sdk.records import to_record
from osiki_sdk.routes import list_routes
from osiki_sdk.store import PolicyStore

logger = logging.getLogger(__name__)

UserResolver = Callable[[Request], str | None | Awaitable[str | None]]
TenantResolver = Callable[[Request], str | None | Awaitable[str | None]]
LoaderFn = Callable[[str], Awaitable[Any | None]]

# Minimum seconds between endpoint reports for an app whose last report failed.
_DISCOVER_RETRY_AFTER = 30.0


class OsikiUnavailable(Exception):  # noqa: N818
    """No snapshot has ever loaded, so no local decision can be made."""


def _scope(tenant: str | None) -> dict[str, str]:
    return {"tenant_id": tenant} if tenant else {}


class _Users:
    def __init__(self, osiki: "Osiki") -> None:
        self._osiki = osiki

    async def upsert(
        self,
        id: str,
        *,
        name: str | None = None,
        email: str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> None:
        await self._osiki._client.upsert_user(
            id, name=name, email=email, attributes=attributes
        )
        self._osiki._store.invalidate_user(id)


class _Tenants:
    def __init__(self, osiki: "Osiki") -> None:
        self._osiki = osiki

    async def upsert(
        self,
        id: str,
        *,
        name: str,
        attributes: dict[str, Any] | None = None,
    ) -> None:
        await self._osiki._client.upsert_tenant(id, name=name, attributes=attributes)
        # Tenant attributes are copied into every member's bundle.
        self._osiki._store.clear_bundles()

    async def add_member(self, tenant_id: str, user_id: str) -> None:
        await self._osiki._client.add_member(tenant_id, user_id)
        self._osiki._store.invalidate_user(user_id)

    async def remove_member(self, tenant_id: str, user_id: str) -> bool:
        removed = await self._osiki._client.remove_member(tenant_id, user_id)
        self._osiki._store.invalidate_user(user_id)
        return removed


class Osiki:
    """Local authorization decisions against a cached Osiki snapshot."""

    def __init__(
        self,
        config: OsikiConfig | None = None,
        *,
        user_id: UserResolver,
        tenant: TenantResolver | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        **config_kwargs: Any,
    ) -> None:
        if config is None:
            config = OsikiConfig(**config_kwargs)
        elif config_kwargs:
            raise TypeError("pass either config or config fields, not both")
        self.config = config
        self.user_resolver = user_id
        self.tenant_resolver = tenant
        self._client = EngineClient(config, transport=transport)
        self._store = PolicyStore(self._client, config)
        self._loaders: dict[str, LoaderFn] = {}
        self._lifecycle_lock = asyncio.Lock()
        self._discovered: weakref.WeakSet[Starlette] = weakref.WeakSet()
        self._discovering: weakref.WeakSet[Starlette] = weakref.WeakSet()
        self._discover_failed_at: weakref.WeakKeyDictionary[Starlette, float] = (
            weakref.WeakKeyDictionary()
        )
        self._poller: asyncio.Task[None] | None = None
        self._closed = False
        self.started = False
        self.users = _Users(self)
        self.tenants = _Tenants(self)

    # Loaders -----------------------------------------------------------------

    def loader(self, record_type: str) -> Callable[[LoaderFn], LoaderFn]:
        """Register the async loader that fetches a ``record_type`` by id."""

        def register(fn: LoaderFn) -> LoaderFn:
            if record_type in self._loaders:
                raise ValueError(f"a loader for {record_type!r} is already registered")
            self._loaders[record_type] = fn
            return fn

        return register

    def get_loader(self, record_type: str) -> LoaderFn | None:
        return self._loaders.get(record_type)

    # Lifecycle ---------------------------------------------------------------

    async def start(self) -> None:
        """Load the first snapshot and start polling; safe to call repeatedly."""
        if self.started:
            return
        async with self._lifecycle_lock:
            if self.started:
                return
            if self._closed:
                raise RuntimeError("Osiki is closed")
            try:
                await self._store.refresh_snapshot()
            except Exception as exc:
                logger.warning("osiki could not load the first snapshot: %r", exc)
            self._poller = asyncio.create_task(
                self._store.run_poller(), name="osiki-poller"
            )
            self.started = True

    async def aclose(self) -> None:
        """Stop polling and close the engine client; safe to call twice."""
        async with self._lifecycle_lock:
            if self._closed:
                return
            self._closed = True
            self.started = False
            poller, self._poller = self._poller, None
            if poller is not None:
                poller.cancel()
                # wait() neither re-raises the poller's cancellation nor
                # swallows one aimed at this task.
                await asyncio.wait({poller})
            await self._client.aclose()

    async def discover(self, app: Starlette) -> None:
        """Report the app's routes to the engine once.

        Returns at once when the app is already reported, a report for it is
        in flight, or its last report failed less than
        ``max(poll_interval, 30)`` seconds ago; the first call after that
        window retries.
        """
        if app in self._discovered or app in self._discovering:
            return
        failed_at = self._discover_failed_at.get(app)
        if failed_at is not None and self._store.clock() - failed_at < max(
            self.config.poll_interval, _DISCOVER_RETRY_AFTER
        ):
            return
        self._discovering.add(app)
        try:
            await self._client.report_endpoints(list_routes(app))
        except Exception as exc:
            logger.warning("osiki endpoint discovery failed: %r", exc)
            self._discover_failed_at[app] = self._store.clock()
        else:
            self._discovered.add(app)
            self._discover_failed_at.pop(app, None)
        finally:
            self._discovering.discard(app)

    # Decisions ---------------------------------------------------------------

    def _snapshot(self) -> Snapshot:
        snapshot = self._store.snapshot
        if snapshot is None:
            raise OsikiUnavailable("no Osiki snapshot has loaded yet")
        return snapshot

    async def check(
        self,
        user_id: str,
        resource: str,
        action: str,
        *,
        tenant: str | None = None,
        record: Any | None = None,
    ) -> Decision:
        """Decide locally whether ``user_id`` may ``action`` on ``resource``."""
        self._snapshot()
        bundle = await self._store.get_bundle(user_id)
        if bundle is None:
            return Decision(allowed=False, denial_reason="unknown_user")
        request = DecisionRequest(
            resource=resource,
            action=action,
            scope=_scope(tenant),
            record=None if record is None else to_record(record),
            now=time.time(),
        )
        return decide(self._snapshot(), bundle, request)

    async def filter(
        self,
        user_id: str,
        resource: str,
        action: str,
        *,
        tenant: str | None = None,
    ) -> FilterResult:
        """The records ``user_id`` may ``action`` on ``resource``, as a filter."""
        self._snapshot()
        bundle = await self._store.get_bundle(user_id)
        if bundle is None:
            return FilterResult(mode="none")
        return list_filter(
            self._snapshot(), bundle, resource, action, _scope(tenant), time.time()
        )
