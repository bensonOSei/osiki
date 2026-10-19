"""Route discovery over a Starlette (or FastAPI) application."""

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, TypeAlias

from starlette.applications import Starlette
from starlette.routing import Match, Route, Router
from starlette.types import Scope

_SKIPPED_METHODS = frozenset({"HEAD", "OPTIONS"})


@dataclass(frozen=True)
class Matched:
    """A full match on a ``Route``: its declared template and string params."""

    path: str
    params: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Opaque:
    """A full match on something the guard cannot see into (a mount, a host,
    a sub-app, an ASGI endpoint or a frontend): treated as unmapped.

    ``path`` is the matched route's own path (a mount's prefix such as
    ``"/static"``, an ASGI endpoint's path), so ``public_routes`` can list
    it. It is ``None`` for a ``Host`` and for the router's fallbacks
    (``frontend()`` routes, a custom ``default`` app), which cannot be public.
    """

    path: str | None


@dataclass(frozen=True)
class NoMatch:
    """No route takes the request: the app answers 404, 405 or a redirect."""


RouteMatch: TypeAlias = Matched | Opaque | NoMatch  # noqa: UP040


def _flat_routes(app: Starlette) -> Iterable[Any]:
    """The app's routes with included routers flattened.

    FastAPI 0.146+ keeps an included router as one lazy ``_IncludedRouter``
    entry in ``app.routes``; ``iter_route_contexts`` yields the effective
    routes (prefixed paths) behind it. Older FastAPI and plain Starlette copy
    routes into ``app.routes`` directly.
    """
    try:
        from fastapi.routing import iter_route_contexts
    except ImportError:
        return app.routes
    return iter_route_contexts(app.routes)


def list_routes(app: Starlette) -> list[tuple[str, str]]:
    """Every ``(METHOD, path)`` of the app's ``Route``s, HEAD/OPTIONS excluded.

    FastAPI's ``APIRoute`` is a ``Route``. Mounts and sub-apps are not
    descended into: their paths are opaque to the guard.
    """
    pairs = {
        (method, route.path)
        for route in _flat_routes(app)
        if isinstance(getattr(route, "original_route", route), Route)
        for method in route.methods or ()
        if method not in _SKIPPED_METHODS
    }
    return sorted(pairs)


def _is_route(route: Any) -> bool:
    """A real ``Route`` with declared methods (not an ASGI-class endpoint)."""
    return (
        isinstance(getattr(route, "original_route", route), Route)
        and route.methods is not None
    )


def _route_path(scope: Scope) -> str:
    from starlette._utils import get_route_path

    return get_route_path(scope)


def _custom_default(router: Any) -> bool:
    """Whether the router sends unmatched requests to an app of its own."""
    return getattr(router.default, "__func__", None) is not Router.not_found


def _fallback_is_opaque(app: Starlette, scope: Scope) -> bool:
    """Whether an unmatched request still reaches app code the guard can't see.

    After every regular route misses, the router redirects a trailing-slash
    variant, then tries FastAPI's low-priority routes (``frontend()``), then
    calls its ``default`` app. This mirrors that order.
    """
    router = app.router
    iter_low_priority = getattr(router, "_iter_low_priority_routes", None)
    candidates = list(iter_low_priority()) if iter_low_priority is not None else []
    custom_default = _custom_default(router)
    if not candidates and not custom_default:
        return False
    route_path = _route_path(scope)
    if router.redirect_slashes and route_path != "/":
        redirect_scope = dict(scope)
        if route_path.endswith("/"):
            redirect_scope["path"] = redirect_scope["path"].rstrip("/")
        else:
            redirect_scope["path"] = redirect_scope["path"] + "/"
        for route in router.routes:
            if route.matches(redirect_scope)[0] is not Match.NONE:
                return False
    return custom_default or any(
        route.matches(dict(scope))[0] is not Match.NONE for route in candidates
    )


def _match(app: Starlette, scope: Scope) -> RouteMatch:
    partial = False
    for route in _flat_routes(app):
        match, child_scope = route.matches(dict(scope))
        if match is Match.FULL:
            if not _is_route(route):
                return Opaque(getattr(route, "path", None))
            params = child_scope.get("path_params", {})
            return Matched(route.path, {k: str(v) for k, v in params.items()})
        partial = partial or match is Match.PARTIAL
    if not partial and _fallback_is_opaque(app, scope):
        return Opaque(None)
    return NoMatch()


def match_route(app: Starlette, scope: Scope) -> RouteMatch:
    """The route the app dispatches ``scope`` to, matched like its router does.

    The first full match wins. A ``HEAD`` request no route takes is matched
    as ``GET``. The scope is never mutated.
    """
    result = _match(app, scope)
    if isinstance(result, NoMatch) and scope["method"] == "HEAD":
        result = _match(app, {**scope, "method": "GET"})
    return result
