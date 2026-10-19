"""Route discovery over a Starlette (or FastAPI) application."""

from collections.abc import Iterable
from typing import Any

from starlette.applications import Starlette
from starlette.routing import Route

_SKIPPED_METHODS = frozenset({"HEAD", "OPTIONS"})


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
