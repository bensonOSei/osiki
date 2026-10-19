import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from conftest import OWN_TEAM, FakeClient, ManualClock, make_osiki, make_snapshot
from fastapi import APIRouter, FastAPI, Request
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.types import Receive, Scope, Send

import osiki_sdk
from osiki_sdk import EngineError, Osiki, OsikiConfig, OsikiGuard
from osiki_sdk._decision.models import Snapshot

GUARD_CONFIG = OsikiConfig(
    base_url="http://engine",
    poll_interval=60.0,
    public_routes=(("POST", "/auth/login"),),
    log_success_sample_rate=1.0,
    log_flush_interval=60.0,
)

ENDPOINTS: list[dict[str, Any]] = [
    {"method": "GET", "path": "/invoices", "permission": "invoices:list"},
    {
        "method": "GET",
        "path": "/invoices/{invoice_id}",
        "permission": "invoices:read",
    },
    {
        "method": "DELETE",
        "path": "/invoices/{invoice_id}",
        "permission": "invoices:delete",
        "record_type": "invoice",
        "record_id_param": "invoice_id",
    },
    {"method": "POST", "path": "/invoices", "permission": "invoices:create"},
    {"method": "GET", "path": "/health", "permission": None, "public": True},
]


def guard_snapshot(
    unmapped: str = "deny",
    endpoints: list[dict[str, Any]] | None = None,
    version: int = 1,
) -> Snapshot:
    return make_snapshot(
        version,
        roles=[
            {
                "id": "reader",
                "name": "reader",
                "grants": [
                    {"permission": "invoices:list"},
                    {"permission": "invoices:read"},
                    {"permission": "invoices:delete", "condition": "own_team"},
                    {"permission": "orders:read"},
                ],
            }
        ],
        conditions={"own_team": OWN_TEAM},
        endpoints=ENDPOINTS if endpoints is None else endpoints,
        settings={"unmapped": unmapped},
    )


class ObjectId:
    """Stands in for bson's ObjectId: ``to_record`` converts it by type name."""

    def __init__(self, value: str) -> None:
        self.value = value

    def __str__(self) -> str:
        return self.value


INVOICES: dict[str, Any] = {
    "1": {"id": "1", "team_id": "t1"},
    "2": {"id": "2", "team_id": "t2"},
    "oid": {"id": ObjectId("oid"), "team_id": ObjectId("t1")},
}


def resolve_user(request: Request) -> str | None:
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if token == "boom":
        raise ValueError("bad token")
    if scheme != "Bearer" or not token.startswith("user:"):
        return None
    return token.removeprefix("user:")


def bearer(user: str = "kofi") -> dict[str, str]:
    return {"Authorization": f"Bearer user:{user}"}


async def _static(request: Any) -> PlainTextResponse:
    return PlainTextResponse("static")


def build_app(osiki: Osiki) -> FastAPI:
    app = FastAPI()
    app.state.seen = []

    @app.get("/invoices")
    async def list_invoices() -> list[str]:
        return ["1", "2"]

    @app.get("/invoices/{invoice_id}")
    async def get_invoice(invoice_id: str) -> dict[str, str]:
        return {"id": invoice_id}

    @app.delete("/invoices/{invoice_id}")
    async def delete_invoice(invoice_id: str, request: Request) -> dict[str, Any]:
        record = request.state.osiki_record
        app.state.seen.append(record)
        return {"deleted": invoice_id, "same": record is INVOICES[invoice_id]}

    @app.post("/invoices")
    async def create_invoice() -> dict[str, str]:
        return {"created": "3"}

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"ok": "yes"}

    @app.post("/auth/login")
    async def login() -> dict[str, str]:
        return {"token": "t"}

    @app.options("/invoices")
    async def options_invoices() -> dict[str, str]:
        return {"allow": "GET, POST"}

    app.mount("/static", Starlette(routes=[Route("/x", _static)]))
    app.add_middleware(OsikiGuard, osiki=osiki)
    return app


class Env:
    def __init__(self, fake: FakeClient, osiki: Osiki, app: FastAPI) -> None:
        self.fake = fake
        self.osiki = osiki
        self.app = app
        self.loads: list[str] = []
        self.http = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        )

    async def drain(self) -> None:
        tasks = set(self.osiki._tasks)
        if tasks:
            await asyncio.wait(tasks)

    def logged(self) -> list[dict[str, Any]]:
        return list(self.osiki._batcher._queue)


def make_env(
    fake: FakeClient,
    clock: ManualClock,
    *,
    config: OsikiConfig = GUARD_CONFIG,
    tenant: Any = None,
    with_loader: bool = True,
) -> Env:
    osiki = make_osiki(fake, clock, config, user_id=resolve_user, tenant=tenant)
    env = Env(fake, osiki, build_app(osiki))
    if with_loader:

        @osiki.loader("invoice")
        async def load_invoice(invoice_id: str) -> Any:
            env.loads.append(invoice_id)
            if invoice_id == "explode":
                raise RuntimeError("db down")
            return INVOICES.get(invoice_id)

    return env


@pytest.fixture
async def env(fake: FakeClient, clock: ManualClock) -> AsyncIterator[Env]:
    fake.snapshot = guard_snapshot()
    instance = make_env(fake, clock)
    yield instance
    await instance.http.aclose()
    await instance.osiki.aclose()


def forbidden(reason: str) -> dict[str, str]:
    return {"detail": "forbidden", "reason": reason}


UNAVAILABLE = {"detail": "authorization unavailable"}


# Route matching ---------------------------------------------------------------


async def test_template_match_with_path_param(env: Env) -> None:
    response = await env.http.get("/invoices/42", headers=bearer())
    assert response.status_code == 200 and response.json() == {"id": "42"}
    [entry] = env.logged()
    assert entry["resource"] == "invoices" and entry["action"] == "read"
    assert entry["matched_permission"] == "invoices:read"


async def test_unmapped_denied_in_deny_env(env: Env) -> None:
    env.fake.snapshot = guard_snapshot(
        endpoints=[e for e in ENDPOINTS if e["method"] != "POST"]
    )
    response = await env.http.post("/invoices", headers=bearer())
    assert response.status_code == 403 and response.json() == forbidden("unmapped")
    assert env.logged() == []  # unmapped outcomes are not decision logs


async def test_unmapped_allowed_with_single_warning_in_allow_env(
    env: Env, caplog: pytest.LogCaptureFixture
) -> None:
    env.fake.snapshot = guard_snapshot(unmapped="allow", endpoints=[])
    with caplog.at_level(logging.WARNING, logger="osiki_sdk.guard"):
        for _ in range(3):
            assert (await env.http.post("/invoices")).status_code == 200
            assert (await env.http.get("/invoices/1")).status_code == 200
            assert (await env.http.get("/static/x")).status_code == 200
    warnings = [r.getMessage() for r in caplog.records if "unmapped" in r.getMessage()]
    assert len(warnings) == 3
    assert any("POST /invoices" in w for w in warnings)
    assert any("GET /invoices/{invoice_id}" in w for w in warnings)
    assert any("/static/x" in w for w in warnings)


async def test_mount_is_treated_as_unmapped(env: Env) -> None:
    response = await env.http.get("/static/x", headers=bearer())
    assert response.status_code == 403 and response.json() == forbidden("unmapped")
    missing = await env.http.get("/static/nothing-here", headers=bearer())
    assert missing.status_code == 403


async def test_included_router_matched_and_denied_when_unmapped(
    fake: FakeClient, clock: ManualClock
) -> None:
    fake.snapshot = guard_snapshot()
    osiki = make_osiki(fake, clock, GUARD_CONFIG, user_id=resolve_user)
    app = FastAPI()
    router = APIRouter(prefix="/orders")

    @router.get("/{order_id}")
    async def get_order(order_id: str) -> dict[str, str]:
        return {"order": order_id}

    app.include_router(router)
    app.add_middleware(OsikiGuard, osiki=osiki)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as http:
        denied = await http.get("/orders/7", headers=bearer())
        assert denied.status_code == 403 and denied.json() == forbidden("unmapped")
        fake.snapshot = guard_snapshot(
            endpoints=[
                {
                    "method": "GET",
                    "path": "/orders/{order_id}",
                    "permission": "orders:read",
                }
            ],
            version=2,
        )
        await osiki._store.refresh_snapshot()
        allowed = await http.get("/orders/7", headers=bearer())
        assert allowed.status_code == 200 and allowed.json() == {"order": "7"}
    await osiki.aclose()


async def test_asgi_class_route_is_treated_as_unmapped(
    fake: FakeClient, clock: ManualClock
) -> None:
    class Endpoint:
        async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
            await PlainTextResponse("raw")(scope, receive, send)

    fake.snapshot = guard_snapshot()
    osiki = make_osiki(fake, clock, GUARD_CONFIG, user_id=resolve_user)
    app = FastAPI()
    app.router.routes.append(Route("/raw", Endpoint()))
    app.add_middleware(OsikiGuard, osiki=osiki)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as http:
        response = await http.delete("/raw", headers=bearer())
    assert response.status_code == 403 and response.json() == forbidden("unmapped")
    await osiki.aclose()


async def test_head_follows_get_mapping(env: Env) -> None:
    response = await env.http.head("/invoices/1", headers=bearer())
    # The guard decided with the GET mapping; FastAPI then answers 405 for HEAD.
    assert response.status_code == 405
    [entry] = env.logged()
    assert entry["matched_permission"] == "invoices:read" and entry["allowed"]
    assert (await env.http.head("/invoices/1")).status_code == 401
    ghost = await env.http.head("/invoices/1", headers=bearer("ghost"))
    assert ghost.status_code == 403
    assert env.logged()[-1]["denial_reason"] == "unknown_user"


async def test_options_preflight_to_ordinary_route_reaches_app(env: Env) -> None:
    # No route takes OPTIONS here (Starlette's PARTIAL): the app answers itself.
    unrouted = await env.http.options("/invoices/1")
    assert unrouted.status_code == 405  # the app's answer, never a 500
    assert env.logged() == []


async def test_explicit_options_handler_is_unmapped(env: Env) -> None:
    response = await env.http.options("/invoices")
    assert response.status_code == 403 and response.json() == forbidden("unmapped")
    mount = await env.http.options("/static/x")
    assert mount.status_code == 403 and mount.json() == forbidden("unmapped")


async def test_explicit_options_handler_public_in_code(
    fake: FakeClient, clock: ManualClock
) -> None:
    fake.snapshot = guard_snapshot()
    config = OsikiConfig(
        base_url="http://engine",
        poll_interval=60.0,
        public_routes=(("OPTIONS", "/invoices"),),
    )
    env = make_env(fake, clock, config=config)
    async with env.http:
        response = await env.http.options("/invoices")
        assert response.status_code == 200
        assert response.json() == {"allow": "GET, POST"}
    await env.osiki.aclose()


async def test_options_to_asgi_class_route_is_unmapped(
    fake: FakeClient, clock: ManualClock
) -> None:
    class Endpoint:
        async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
            await PlainTextResponse("raw")(scope, receive, send)  # pragma: no cover

    fake.snapshot = guard_snapshot()
    osiki = make_osiki(fake, clock, GUARD_CONFIG, user_id=resolve_user)
    app = FastAPI()
    app.router.routes.append(Route("/raw", Endpoint()))
    app.add_middleware(OsikiGuard, osiki=osiki)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as http:
        response = await http.options("/raw", headers=bearer())
    assert response.status_code == 403 and response.json() == forbidden("unmapped")
    await osiki.aclose()


async def test_unknown_path_falls_through_to_404(env: Env) -> None:
    response = await env.http.get("/nowhere", headers=bearer())
    assert response.status_code == 404
    wrong_method = await env.http.put("/invoices")
    assert wrong_method.status_code == 405


async def test_trailing_slash_redirect_is_guarded_on_follow(env: Env) -> None:
    response = await env.http.get("/invoices/", headers=bearer())
    assert response.status_code == 307
    follow = await env.http.get(response.headers["location"])
    assert follow.status_code == 401


# Public routes ----------------------------------------------------------------


async def test_public_routes_in_code_skip_snapshot(env: Env) -> None:
    response = await env.http.post("/auth/login")
    assert response.status_code == 200 and response.json() == {"token": "t"}
    env.fake.fail.add("get_snapshot")  # even with no snapshot at all
    cold = make_env(env.fake, ManualClock())
    async with cold.http:
        assert (await cold.http.post("/auth/login")).status_code == 200
    await cold.osiki.aclose()


async def test_public_routes_methods_are_case_insensitive(
    fake: FakeClient, clock: ManualClock
) -> None:
    fake.snapshot = guard_snapshot(endpoints=[])
    config = OsikiConfig(
        base_url="http://engine",
        poll_interval=60.0,
        public_routes=(("post", "/auth/login"), ("get", "/health")),
    )
    env = make_env(fake, clock, config=config)
    async with env.http:
        assert (await env.http.post("/auth/login")).status_code == 200
        assert (await env.http.head("/health")).status_code == 405
    await env.osiki.aclose()


async def test_public_mapping_skips_user_resolution(env: Env) -> None:
    response = await env.http.get("/health", headers={"Authorization": "Bearer boom"})
    assert response.status_code == 200 and response.json() == {"ok": "yes"}
    assert env.logged() == []


# Users and tenants ------------------------------------------------------------


async def test_resolver_decodes_bearer_header(env: Env) -> None:
    assert (await env.http.get("/invoices", headers=bearer())).status_code == 200
    assert env.logged()[0]["user_id"] == "kofi"


async def test_missing_user_401(env: Env) -> None:
    response = await env.http.get("/invoices")
    assert response.status_code == 401
    assert response.json() == {"detail": "unauthenticated"}
    assert env.logged() == []


async def test_resolver_exception_401(env: Env) -> None:
    response = await env.http.get("/invoices", headers={"Authorization": "Bearer boom"})
    assert response.status_code == 401
    assert response.json() == {"detail": "unauthenticated"}


@pytest.mark.parametrize("value", ["", 42])
async def test_resolver_non_string_or_empty_401(
    fake: FakeClient, clock: ManualClock, value: Any
) -> None:
    fake.snapshot = guard_snapshot()
    osiki = make_osiki(fake, clock, GUARD_CONFIG, user_id=lambda request: value)
    app = build_app(osiki)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as http:
        assert (await http.get("/invoices")).status_code == 401
    await osiki.aclose()


async def test_async_resolvers_and_tenant_scope(
    fake: FakeClient, clock: ManualClock
) -> None:
    fake.snapshot = guard_snapshot()

    async def user(request: Request) -> str | None:
        return resolve_user(request)

    async def tenant(request: Request) -> str | None:
        value = request.headers.get("x-tenant")
        if value == "boom":
            raise ValueError("bad tenant")
        return value

    osiki = make_osiki(fake, clock, GUARD_CONFIG, user_id=user, tenant=tenant)
    app = build_app(osiki)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as http:
        member = await http.get("/invoices", headers={**bearer(), "X-Tenant": "acme"})
        assert member.status_code == 200
        other = await http.get("/invoices", headers={**bearer(), "X-Tenant": "globex"})
        assert other.status_code == 403
        assert other.json() == forbidden("not_tenant_member")
        none = await http.get("/invoices", headers=bearer())
        assert none.status_code == 200
        broken = await http.get("/invoices", headers={**bearer(), "X-Tenant": "boom"})
        assert broken.status_code == 401
        assert broken.json() == {"detail": "unauthenticated"}
    scopes = [entry["scope"] for entry in osiki._batcher._queue]
    assert scopes == [{"tenant_id": "acme"}, {"tenant_id": "globex"}, {}]
    await osiki.aclose()


async def test_unknown_user_403(env: Env) -> None:
    response = await env.http.get("/invoices", headers=bearer("ghost"))
    assert response.status_code == 403 and response.json() == forbidden("unknown_user")
    [entry] = env.logged()
    assert entry["allowed"] is False and entry["denial_reason"] == "unknown_user"
    assert entry["user_id"] == "ghost"


async def test_no_permission_403(env: Env) -> None:
    response = await env.http.post("/invoices", headers=bearer())
    assert response.status_code == 403 and response.json() == forbidden("no_permission")


# Records ----------------------------------------------------------------------


async def test_record_rule_allows_own_team_denies_other(env: Env) -> None:
    own = await env.http.delete("/invoices/1", headers=bearer())
    assert own.status_code == 200 and own.json()["deleted"] == "1"
    other = await env.http.delete("/invoices/2", headers=bearer())
    assert other.status_code == 403 and other.json() == forbidden("condition_failed")
    allowed, denied = env.logged()
    assert allowed["condition"] == "own_team" and allowed["allowed"] is True
    assert denied["denial_reason"] == "condition_failed"


async def test_loader_none_404(env: Env) -> None:
    response = await env.http.delete("/invoices/missing", headers=bearer())
    assert response.status_code == 404 and response.json() == {"detail": "not found"}
    assert env.logged() == []


async def test_loader_raises_503(env: Env, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.ERROR, logger="osiki_sdk.guard"):
        response = await env.http.delete("/invoices/explode", headers=bearer())
    assert response.status_code == 503 and response.json() == UNAVAILABLE
    assert "loader" in caplog.text


async def test_missing_loader_503(
    fake: FakeClient, clock: ManualClock, caplog: pytest.LogCaptureFixture
) -> None:
    fake.snapshot = guard_snapshot()
    env = make_env(fake, clock, with_loader=False)
    misconfigured = {"detail": "authorization misconfigured"}
    async with env.http:
        with caplog.at_level(logging.ERROR, logger="osiki_sdk.guard"):
            for _ in range(3):
                response = await env.http.delete("/invoices/1", headers=bearer())
                assert response.status_code == 503
                assert response.json() == misconfigured
    messages = [r for r in caplog.records if "no loader" in r.getMessage()]
    assert len(messages) == 1
    await env.osiki.aclose()


async def test_mapping_without_permission_or_id_param_is_misconfigured(
    fake: FakeClient, clock: ManualClock
) -> None:
    fake.snapshot = guard_snapshot(
        endpoints=[
            {"method": "GET", "path": "/invoices", "permission": None},
            {
                "method": "DELETE",
                "path": "/invoices/{invoice_id}",
                "permission": "invoices:delete",
                "record_type": "invoice",
                "record_id_param": "id",
            },
        ]
    )
    env = make_env(fake, clock)
    misconfigured = {"detail": "authorization misconfigured"}
    async with env.http:
        listed = await env.http.get("/invoices", headers=bearer())
        assert listed.status_code == 503 and listed.json() == misconfigured
        deleted = await env.http.delete("/invoices/1", headers=bearer())
        assert deleted.status_code == 503 and deleted.json() == misconfigured
    assert env.loads == []
    await env.osiki.aclose()


async def test_record_shared_on_request_state(env: Env) -> None:
    response = await env.http.delete("/invoices/1", headers=bearer())
    assert response.status_code == 200 and response.json()["same"] is True
    assert env.loads == ["1"]
    assert env.app.state.seen == [INVOICES["1"]]


async def test_converted_objectid_record_matches_rule(env: Env) -> None:
    response = await env.http.delete("/invoices/oid", headers=bearer())
    assert response.status_code == 200 and response.json()["same"] is True


async def test_unconvertible_record_503(fake: FakeClient, clock: ManualClock) -> None:
    fake.snapshot = guard_snapshot()
    env = make_env(fake, clock, with_loader=False)

    @env.osiki.loader("invoice")
    async def load_invoice(invoice_id: str) -> Any:
        return object()

    async with env.http:
        response = await env.http.delete("/invoices/1", headers=bearer())
    assert response.status_code == 503 and response.json() == UNAVAILABLE
    await env.osiki.aclose()


# Availability -----------------------------------------------------------------


async def test_cold_start_write_503_read_default_503_read_allow_when_configured(
    fake: FakeClient, clock: ManualClock
) -> None:
    fake.snapshot = guard_snapshot()
    fake.fail.add("get_snapshot")
    env = make_env(fake, clock)
    async with env.http:
        write = await env.http.post("/invoices", headers=bearer())
        assert write.status_code == 503 and write.json() == UNAVAILABLE
        read = await env.http.get("/invoices", headers=bearer())
        assert read.status_code == 503 and read.json() == UNAVAILABLE
        head = await env.http.head("/invoices/1", headers=bearer())
        assert head.status_code == 503
        mount = await env.http.get("/static/x")
        assert mount.status_code == 503
    await env.osiki.aclose()

    config = OsikiConfig(
        base_url="http://engine", poll_interval=60.0, read_on_unavailable="allow"
    )
    env = make_env(fake, ManualClock(), config=config)
    async with env.http:
        read = await env.http.get("/invoices")
        assert read.status_code == 200 and read.json() == ["1", "2"]
        write = await env.http.delete("/invoices/1", headers=bearer())
        assert write.status_code == 503 and write.json() == UNAVAILABLE
    assert env.loads == []
    await env.osiki.aclose()


def _unavailable_env(fake: FakeClient, read_on_unavailable: str = "deny") -> Env:
    endpoints = [
        {"method": "GET", "path": "/invoices", "permission": "invoices:list"},
        {
            "method": "GET",
            "path": "/invoices/{invoice_id}",
            "permission": "invoices:read",
            "on_unavailable": "deny",
        },
        {
            "method": "POST",
            "path": "/invoices",
            "permission": "invoices:create",
            "on_unavailable": "allow",
        },
        {
            "method": "DELETE",
            "path": "/invoices/{invoice_id}",
            "permission": "invoices:delete",
        },
    ]
    fake.snapshot = guard_snapshot(endpoints=endpoints)
    config = OsikiConfig(
        base_url="http://engine",
        poll_interval=60.0,
        read_on_unavailable=read_on_unavailable,  # type: ignore[arg-type]
        log_success_sample_rate=1.0,
        log_flush_interval=60.0,
    )
    return make_env(fake, ManualClock(), config=config)


async def test_bundle_fetch_unavailable_read_follows_read_on_unavailable(
    fake: FakeClient,
) -> None:
    fake.fail.add("get_bundle")
    allow = _unavailable_env(fake, "allow")
    async with allow.http:
        response = await allow.http.get("/invoices", headers=bearer())
        assert response.status_code == 200 and response.json() == ["1", "2"]
        head = await allow.http.head("/invoices", headers=bearer())
        assert head.status_code == 405  # passed the guard; FastAPI has no HEAD
    assert allow.logged() == []  # no decision was made
    await allow.osiki.aclose()

    deny = _unavailable_env(fake)
    async with deny.http:
        response = await deny.http.get("/invoices", headers=bearer())
        assert response.status_code == 503 and response.json() == UNAVAILABLE
    await deny.osiki.aclose()


async def test_bundle_fetch_unavailable_mapping_on_unavailable_wins(
    fake: FakeClient,
) -> None:
    fake.fail.add("get_bundle")
    env = _unavailable_env(fake, "allow")
    async with env.http:
        write = await env.http.post("/invoices", headers=bearer())
        assert write.status_code == 200 and write.json() == {"created": "3"}
        read = await env.http.get("/invoices/1", headers=bearer())
        assert read.status_code == 503 and read.json() == UNAVAILABLE
    assert env.logged() == []
    await env.osiki.aclose()


async def test_bundle_fetch_unavailable_write_without_policy_503(
    fake: FakeClient,
) -> None:
    fake.fail.add("get_bundle")
    env = _unavailable_env(fake, "allow")
    async with env.http:
        response = await env.http.delete("/invoices/1", headers=bearer())
        assert response.status_code == 503 and response.json() == UNAVAILABLE
    await env.osiki.aclose()


async def test_bundle_fetch_engine_error_503(
    fake: FakeClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken(user_id: str) -> Any:
        raise EngineError(400, "bad")

    monkeypatch.setattr(fake, "get_bundle", broken)
    env = _unavailable_env(fake, "allow")
    async with env.http:
        read = await env.http.get("/invoices", headers=bearer())
        assert read.status_code == 503 and read.json() == UNAVAILABLE
        write = await env.http.post("/invoices", headers=bearer())
        assert write.status_code == 503
    await env.osiki.aclose()


async def test_guard_internal_error_returns_503(
    env: Env, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def explode(*args: Any) -> Any:
        raise RuntimeError("guard bug")

    monkeypatch.setattr(osiki_sdk.guard, "match_route", explode)
    with caplog.at_level(logging.ERROR, logger="osiki_sdk.guard"):
        response = await env.http.get("/invoices", headers=bearer())
    assert response.status_code == 503 and response.json() == UNAVAILABLE
    assert "guard bug" in caplog.text


async def test_handler_errors_are_not_converted(
    fake: FakeClient, clock: ManualClock
) -> None:
    fake.snapshot = guard_snapshot()
    osiki = make_osiki(fake, clock, GUARD_CONFIG, user_id=resolve_user)
    app = FastAPI()

    @app.get("/invoices")
    async def broken() -> None:
        raise LookupError("handler bug")

    app.add_middleware(OsikiGuard, osiki=osiki)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as http:
        with pytest.raises(LookupError, match="handler bug"):
            await http.get("/invoices", headers=bearer())
    await osiki.aclose()


async def test_request_after_aclose_503(env: Env) -> None:
    assert (await env.http.get("/invoices", headers=bearer())).status_code == 200
    await env.osiki.aclose()
    response = await env.http.get("/invoices", headers=bearer())
    assert response.status_code == 503 and response.json() == UNAVAILABLE


async def test_scope_without_app_503(fake: FakeClient, clock: ManualClock) -> None:
    fake.snapshot = guard_snapshot()
    osiki = make_osiki(fake, clock, GUARD_CONFIG, user_id=resolve_user)
    reached: list[str] = []

    async def inner(scope: Scope, receive: Receive, send: Send) -> None:
        reached.append(scope["path"])  # pragma: no cover - must never run

    guard = OsikiGuard(inner, osiki=osiki)
    transport = httpx.ASGITransport(app=guard)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as http:
        response = await http.get("/invoices", headers=bearer())
    assert response.status_code == 503 and reached == []
    await osiki.aclose()


async def test_non_http_scopes_pass_through(
    fake: FakeClient, clock: ManualClock
) -> None:
    osiki = make_osiki(fake, clock, GUARD_CONFIG, user_id=resolve_user)
    seen: list[str] = []

    async def inner(scope: Scope, receive: Receive, send: Send) -> None:
        seen.append(scope["type"])

    guard = OsikiGuard(inner, osiki=osiki)

    async def receive() -> Any:  # pragma: no cover - never called
        return {}

    async def send(message: Any) -> None:  # pragma: no cover - never called
        return None

    await guard({"type": "lifespan"}, receive, send)
    await guard({"type": "websocket", "path": "/ws"}, receive, send)
    assert seen == ["lifespan", "websocket"]
    assert osiki.started is False
    await osiki.aclose()


# Lifecycle and discovery ------------------------------------------------------


async def test_concurrent_cold_requests_start_once(env: Env) -> None:
    env.fake.snapshot_delay = True
    responses = await asyncio.gather(
        *(env.http.get("/invoices", headers=bearer()) for _ in range(10))
    )
    assert [r.status_code for r in responses] == [200] * 10
    assert env.fake.count("get_snapshot") == 1
    assert env.osiki.started is True


async def test_routes_reported_once(env: Env) -> None:
    env.fake.report_gate = asyncio.Event()
    responses = await asyncio.gather(
        *(env.http.get("/invoices", headers=bearer()) for _ in range(5))
    )
    # Discovery runs in the background: requests never wait for it.
    assert [r.status_code for r in responses] == [200] * 5
    env.fake.report_gate.set()
    await env.drain()
    await env.http.get("/invoices", headers=bearer())
    await env.drain()
    assert env.fake.count("report_endpoints") == 1
    [report] = [c[1] for c in env.fake.calls if c[0] == "report_endpoints"]
    assert ("DELETE", "/invoices/{invoice_id}") in report
    assert env.osiki._tasks == set()


async def test_background_discover_errors_are_logged(
    env: Env, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    async def explode(app: Any) -> None:
        raise RuntimeError("discover bug")

    monkeypatch.setattr(env.osiki, "discover", explode)
    with caplog.at_level(logging.WARNING, logger="osiki_sdk.osiki"):
        response = await env.http.get("/invoices", headers=bearer())
        await env.drain()
    assert response.status_code == 200
    assert "discover bug" in caplog.text


async def test_aclose_cancels_pending_discovery_and_flushes_logs(
    fake: FakeClient, clock: ManualClock
) -> None:
    fake.snapshot = guard_snapshot()
    fake.report_gate = asyncio.Event()  # discovery never finishes on its own
    env = make_env(fake, clock)
    async with env.http:
        assert (await env.http.get("/invoices", headers=bearer())).status_code == 200
    await asyncio.sleep(0)
    assert len(env.osiki._tasks) == 1
    await env.osiki.aclose()
    assert env.osiki._tasks == set()
    [batch] = [c[1] for c in fake.calls if c[0] == "send_access_logs"]
    assert [e["resource"] for e in batch] == ["invoices"]


# Decision logs ----------------------------------------------------------------


async def test_decision_log_entry_matches_ingest_shape(env: Env) -> None:
    await env.http.delete("/invoices/2", headers=bearer())
    [entry] = env.logged()
    assert set(entry) == {
        "timestamp",
        "user_id",
        "resource",
        "action",
        "scope",
        "allowed",
        "matched_permission",
        "condition",
        "denial_reason",
        "latency_ms",
    }
    assert entry["action"] == "delete" and entry["scope"] == {}
    assert entry["allowed"] is False and entry["matched_permission"] is None
    assert isinstance(entry["timestamp"], float) and entry["latency_ms"] >= 0


def test_guard_is_exported() -> None:
    assert "OsikiGuard" in osiki_sdk.__all__
    assert "DecisionLogBatcher" in osiki_sdk.__all__
