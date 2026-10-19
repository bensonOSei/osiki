import sys

import pytest
from fastapi import APIRouter, FastAPI
from starlette.applications import Starlette
from starlette.routing import Mount, Route

from osiki_sdk.routes import list_routes


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
