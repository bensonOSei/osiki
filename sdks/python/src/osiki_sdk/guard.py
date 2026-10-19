"""``OsikiGuard``: the pure ASGI middleware that authorizes every HTTP request."""

import inspect
import logging
import time
from collections.abc import Callable
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

from osiki_sdk._decision.models import EndpointEntry, Snapshot
from osiki_sdk.osiki import Osiki
from osiki_sdk.routes import Matched, NoMatch, match_route

logger = logging.getLogger(__name__)

_READ_METHODS = frozenset({"GET"})


def _json(status: int, body: dict[str, str]) -> Response:
    return JSONResponse(body, status_code=status)


def _unavailable() -> Response:
    return _json(503, {"detail": "authorization unavailable"})


def _misconfigured() -> Response:
    return _json(503, {"detail": "authorization misconfigured"})


def _forbidden(reason: str) -> Response:
    return _json(403, {"detail": "forbidden", "reason": reason})


def _unauthenticated() -> Response:
    return _json(401, {"detail": "unauthenticated"})


class _UnresolvedError(Exception):
    """A resolver raised or returned no usable value."""


async def _resolve(resolver: Callable[[Request], Any], request: Request) -> Any:
    value = resolver(request)
    if inspect.isawaitable(value):
        value = await value
    return value


class OsikiGuard:
    """Authorize each HTTP request against the cached Osiki snapshot.

    Add it with ``app.add_middleware(OsikiGuard, osiki=osiki)``. A request
    reaches the app only when it is public, unmapped in an ``allow``
    environment, allowed by ``decide``, or matched by no route (the app then
    answers 404/405/redirect itself). Any error inside the guard answers 503:
    it never falls through to the app.
    """

    def __init__(self, app: ASGIApp, osiki: Osiki) -> None:
        self.app = app
        self.osiki = osiki
        self._public = {
            (method.upper(), template)
            for method, template in osiki.config.public_routes
        }
        self._index: tuple[Snapshot, dict[tuple[str, str], EndpointEntry]] | None = None
        # Bounded: keys are declared (method, template) pairs plus one for
        # every opaque match, never raw request paths.
        self._warned_unmapped: set[tuple[str, str | None]] = set()
        self._warned_loaders: set[str] = set()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        try:
            response = await self._authorize(scope)
        except Exception:
            logger.exception("osiki guard failed; denying the request")
            response = _unavailable()
        # The app runs outside the try: its own errors are never turned into
        # a 503 after it may have started responding.
        if response is None:
            await self.app(scope, receive, send)
        else:
            await response(scope, receive, send)

    def _mappings(self, snapshot: Snapshot) -> dict[tuple[str, str], EndpointEntry]:
        if self._index is None or self._index[0] is not snapshot:
            entries = {(e.method.upper(), e.path): e for e in snapshot.endpoints}
            self._index = (snapshot, entries)
        return self._index[1]

    def _warn_unmapped(self, method: str, template: str | None, path: str) -> None:
        key = (method, template) if template is not None else ("*", None)
        if key in self._warned_unmapped:
            return
        self._warned_unmapped.add(key)
        if template is None:
            logger.warning(
                "osiki allowed an unmapped mounted app (first seen at %s); "
                "every mount is unmapped",
                path,
            )
        else:
            logger.warning("osiki allowed unmapped route %s %s", method, template)

    async def _authorize(self, scope: Scope) -> Response | None:
        """The response that ends the request, or ``None`` to call the app."""
        osiki = self.osiki
        # 1. Lifecycle: start is idempotent; discovery never blocks a request.
        await osiki.start()
        app = scope["app"]
        osiki.discover_in_background(app)

        # 2. CORS preflights belong to the app.
        method: str = scope["method"]
        if method == "OPTIONS":
            return None
        lookup_method = "GET" if method == "HEAD" else method

        # 3. Route matching by template.
        match = match_route(app, scope)
        if isinstance(match, NoMatch):
            return None
        template, params = (
            (match.path, match.params) if isinstance(match, Matched) else (None, {})
        )
        if template is not None and (lookup_method, template) in self._public:
            return None

        # 4. No snapshot has ever loaded: follow the failure mode.
        snapshot = osiki._store.snapshot
        if snapshot is None:
            if lookup_method in _READ_METHODS:
                policy = osiki.config.read_on_unavailable
            else:
                policy = "deny"
            return None if policy == "allow" else _unavailable()

        # 5-7. The endpoint mapping.
        entry = None
        if template is not None:
            entry = self._mappings(snapshot).get((lookup_method, template))
        if entry is None:
            if snapshot.settings.unmapped == "allow":
                self._warn_unmapped(lookup_method, template, scope["path"])
                return None
            return _forbidden("unmapped")
        if entry.public:
            return None
        if entry.permission is None:
            logger.error(
                "osiki mapping %s %s has no permission", entry.method, entry.path
            )
            return _misconfigured()

        # 8-9. The caller (the resolver is the trust boundary).
        request = Request(scope)
        try:
            user_id = await _resolve(osiki.user_resolver, request)
            if not isinstance(user_id, str) or not user_id:
                raise _UnresolvedError
            tenant = None
            if osiki.tenant_resolver is not None:
                tenant = await _resolve(osiki.tenant_resolver, request) or None
        except Exception as exc:
            if not isinstance(exc, _UnresolvedError):
                logger.info("osiki resolver raised; answering 401: %r", exc)
            return _unauthenticated()

        # 10. The record, through the registered loader.
        record = None
        if entry.record_type is not None:
            loader = osiki.get_loader(entry.record_type)
            record_id = params.get(entry.record_id_param or "")
            if loader is None or record_id is None:
                if entry.record_type not in self._warned_loaders:
                    self._warned_loaders.add(entry.record_type)
                    logger.error(
                        "osiki has no loader for record type %r or no path "
                        "parameter %r on %s %s",
                        entry.record_type,
                        entry.record_id_param,
                        entry.method,
                        entry.path,
                    )
                return _misconfigured()
            try:
                record = await loader(record_id)
            except Exception:
                logger.exception(
                    "osiki loader for %r raised; answering 503", entry.record_type
                )
                return _unavailable()
            if record is None:
                return _json(404, {"detail": "not found"})
            scope.setdefault("state", {})["osiki_record"] = record

        # 11. Decide locally (a missing bundle is "unknown_user").
        resource, _, action = entry.permission.partition(":")
        started = time.perf_counter()
        decision = await osiki.check(
            user_id, resource, action, tenant=tenant, record=record
        )
        latency_ms = (time.perf_counter() - started) * 1000

        # 12. Log the decision; the batcher never blocks.
        osiki._batcher.record(
            {
                "timestamp": time.time(),
                "user_id": user_id,
                "resource": resource,
                "action": action,
                "scope": {"tenant_id": tenant} if tenant else {},
                "allowed": decision.allowed,
                "matched_permission": decision.matched_permission,
                "condition": decision.condition,
                "denial_reason": decision.denial_reason,
                "latency_ms": latency_ms,
            }
        )
        if decision.allowed:
            return None
        return _forbidden(decision.denial_reason or "no_permission")
