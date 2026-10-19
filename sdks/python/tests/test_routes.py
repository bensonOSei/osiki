import sys
from typing import Any

import pytest
from fastapi import APIRouter, FastAPI
from starlette.applications import Starlette
from starlette.routing import Host, Mount, Route

from osiki_sdk.routes import Matched, NoMatch, Opaque, list_routes, match_route


async def _endpoint(request: object) -> None:
    return None


def test_list_routes_covers_api_and_plain_routes_sorted() -> None:
    app = FastAPI()
    router = APIRouter(prefix="/orders")
    items = APIRouter(prefix="/items")

    @router.get("/{order_id}")
    async def get_order(order_id: str) -> None:
        return None

    @items.put("/{item_id}")
    async def put_item(item_id: str) -> None:
        return None

    router.include_router(items)
    router.routes.append(Mount("/files", routes=[Route("/y", _endpoint)]))

    @app.delete("/invoices/{invoice_id}")
    async def delete_invoice(invoice_id: str) -> None:
        return None

    @app.api_route("/ping", methods=["GET", "HEAD", "OPTIONS"])
    async def ping() -> None:
        return None

    app.include_router(router)
    app.router.routes.append(Route("/plain", _endpoint, methods=["POST"]))
    app.router.routes.append(Mount("/static", routes=[Route("/x", _endpoint)]))

    routes = list_routes(app)
    assert ("GET", "/docs") in routes  # FastAPI's own routes are real routes
    ours = [r for r in routes if not r[1].startswith(("/docs", "/openapi", "/redoc"))]
    assert ours == [
        ("DELETE", "/invoices/{invoice_id}"),
        ("GET", "/orders/{order_id}"),
        ("GET", "/ping"),
        ("POST", "/plain"),
        ("PUT", "/orders/items/{item_id}"),
    ]


def test_list_routes_without_fastapi(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "fastapi.routing", None)
    app = Starlette(
        routes=[
            Route("/a", _endpoint, methods=["GET", "POST"]),
            Mount("/static", routes=[Route("/x", _endpoint)]),
        ]
    )
    assert list_routes(app) == [("GET", "/a"), ("POST", "/a")]


def _scope(method: str, path_: str, root_path: str = "") -> dict[str, Any]:
    return {
        "type": "http",
        "method": method,
        "path": path_,
        "root_path": root_path,
        "headers": [],
        "query_string": b"",
    }


class _AsgiEndpoint:
    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        return None


def _match_app() -> FastAPI:
    app = FastAPI()
    router = APIRouter(prefix="/orders")
    inner = APIRouter(prefix="/items")

    @router.get("/{order_id}")
    async def get_order(order_id: str) -> None:
        return None

    @inner.delete("/{item_id}")
    async def delete_item(item_id: int) -> None:
        return None

    router.include_router(inner)

    @app.get("/invoices/{invoice_id}")
    async def get_invoice(invoice_id: str) -> None:
        return None

    @app.post("/invoices")
    async def create_invoice() -> None:
        return None

    @app.get("/files/{name:path}")
    async def get_file(name: str) -> None:
        return None

    app.include_router(router)
    app.router.routes.append(Route("/plain/{n:int}", _endpoint, methods=["GET"]))
    app.router.routes.append(Route("/asgi", _AsgiEndpoint()))
    app.router.routes.append(Mount("/static", routes=[Route("/x", _endpoint)]))
    return app


def test_match_route_uses_template_and_string_params() -> None:
    app = _match_app()
    match = match_route(app, _scope("GET", "/invoices/42"))
    assert match == Matched("/invoices/{invoice_id}", {"invoice_id": "42"})
    plain = match_route(app, _scope("GET", "/plain/7"))
    assert plain == Matched("/plain/{n:int}", {"n": "7"})
    files = match_route(app, _scope("GET", "/files/a/b.txt"))
    assert files == Matched("/files/{name:path}", {"name": "a/b.txt"})


def test_match_route_resolves_included_routers_like_list_routes() -> None:
    app = _match_app()
    order = match_route(app, _scope("GET", "/orders/9"))
    item = match_route(app, _scope("DELETE", "/orders/items/3"))
    assert order == Matched("/orders/{order_id}", {"order_id": "9"})
    assert item == Matched("/orders/items/{item_id}", {"item_id": "3"})
    routes = list_routes(app)
    assert isinstance(order, Matched) and ("GET", order.path) in routes
    assert isinstance(item, Matched) and ("DELETE", item.path) in routes


def test_match_route_opaque_for_mounts_and_asgi_endpoints() -> None:
    app = _match_app()
    # Opaque carries the matched route's own path, for ``public_routes``.
    assert match_route(app, _scope("GET", "/static/x")) == Opaque("/static")
    assert match_route(app, _scope("GET", "/static/anything")) == Opaque("/static")
    assert match_route(app, _scope("DELETE", "/asgi")) == Opaque("/asgi")


def test_match_route_host_is_opaque_without_a_path() -> None:
    app = Starlette(routes=[Host("api.example.com", app=_AsgiEndpoint())])
    scope = {**_scope("GET", "/x"), "headers": [(b"host", b"api.example.com")]}
    assert match_route(app, scope) == Opaque(None)


def test_match_route_no_match_and_partial() -> None:
    app = _match_app()
    assert match_route(app, _scope("GET", "/nowhere")) == NoMatch()
    # A wrong method is Starlette's 405: never dispatched to a handler.
    assert match_route(app, _scope("PUT", "/invoices")) == NoMatch()
    assert match_route(app, _scope("GET", "/plain/x")) == NoMatch()


def test_match_route_head_follows_get() -> None:
    app = _match_app()
    expected = Matched("/invoices/{invoice_id}", {"invoice_id": "1"})
    assert match_route(app, _scope("HEAD", "/invoices/1")) == expected
    # A plain Route accepts HEAD itself.
    assert match_route(app, _scope("HEAD", "/plain/1")) == Matched(
        "/plain/{n:int}", {"n": "1"}
    )
    assert match_route(app, _scope("HEAD", "/invoices")) == NoMatch()


def test_match_route_never_mutates_scope() -> None:
    app = _match_app()
    scope = _scope("HEAD", "/orders/items/3")
    before = dict(scope)
    match_route(app, scope)
    assert scope == before


def test_match_route_honours_root_path() -> None:
    app = _match_app()
    scope = _scope("GET", "/api/invoices/5", root_path="/api")
    assert match_route(app, scope) == Matched(
        "/invoices/{invoice_id}", {"invoice_id": "5"}
    )


def test_match_route_without_fastapi(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "fastapi.routing", None)
    app = Starlette(
        routes=[
            Route("/a/{x}", _endpoint, methods=["GET"]),
            Mount("/static", routes=[Route("/x", _endpoint)]),
        ]
    )
    assert match_route(app, _scope("GET", "/a/1")) == Matched("/a/{x}", {"x": "1"})
    assert match_route(app, _scope("GET", "/static/x")) == Opaque("/static")
    assert match_route(app, _scope("GET", "/b")) == NoMatch()


def test_match_route_frontend_is_opaque(tmp_path: Any) -> None:
    (tmp_path / "index.html").write_text("<html></html>")
    app = FastAPI()

    @app.get("/api/ping")
    async def ping() -> None:
        return None

    app.frontend("/", directory=tmp_path)
    assert match_route(app, _scope("GET", "/api/ping")) == Matched("/api/ping", {})
    assert match_route(app, _scope("GET", "/")) == Opaque(None)
    assert match_route(app, _scope("GET", "/index.html")) == Opaque(None)
    assert match_route(app, _scope("GET", "/app/deep/link")) == Opaque(None)
    # The app redirects a trailing-slash variant before the frontend sees it.
    assert match_route(app, _scope("GET", "/api/ping/")) == NoMatch()
    # A wrong method on a real route is still the app's 405.
    assert match_route(app, _scope("POST", "/api/ping")) == NoMatch()


def test_match_route_frontend_without_redirect_slashes(tmp_path: Any) -> None:
    (tmp_path / "index.html").write_text("<html></html>")
    app = FastAPI(redirect_slashes=False)

    @app.get("/api/ping")
    async def ping() -> None:
        return None

    app.frontend("/", directory=tmp_path)
    assert match_route(app, _scope("GET", "/api/ping/")) == Opaque(None)


def test_match_route_custom_router_default_is_opaque() -> None:
    app = FastAPI()

    @app.get("/api/ping")
    async def ping() -> None:
        return None

    app.router.default = _AsgiEndpoint()
    assert match_route(app, _scope("GET", "/anything")) == Opaque(None)
    assert match_route(app, _scope("GET", "/api/ping")) == Matched("/api/ping", {})
    assert match_route(app, _scope("GET", "/api/ping/")) == NoMatch()  # redirect
    assert match_route(app, _scope("POST", "/api/ping")) == NoMatch()  # 405
