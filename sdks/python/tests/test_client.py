import json
from collections.abc import Callable

import httpx
import pytest

from osiki_sdk.client import EngineClient, EngineError, EngineUnavailable
from osiki_sdk.config import OsikiConfig

Handler = Callable[[httpx.Request], httpx.Response]


def make_client(
    handler: Handler, api_key: str | None = None, environment: str = "default"
) -> EngineClient:
    config = OsikiConfig(
        base_url="http://engine", environment=environment, api_key=api_key
    )
    return EngineClient(config, transport=httpx.MockTransport(handler))


SNAPSHOT = {"environment_id": "e1", "version": 3}


async def test_snapshot_304_returns_none_with_etag() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(304)

    client = make_client(handler)
    assert await client.get_snapshot('"3"') == (None, '"3"')
    assert seen[0].headers["If-None-Match"] == '"3"'
    assert seen[0].url.path == "/api/v1/snapshot"
    await client.aclose()


async def test_snapshot_200_parses_and_returns_etag() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "If-None-Match" not in request.headers
        return httpx.Response(200, json=SNAPSHOT, headers={"ETag": '"3"'})

    client = make_client(handler)
    snapshot, etag = await client.get_snapshot(None)
    assert snapshot is not None and snapshot.version == 3
    assert etag == '"3"'
    await client.aclose()


async def test_get_versions() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/snapshot/version"
        return httpx.Response(200, json={"version": 4, "assignments_version": 9})

    client = make_client(handler)
    assert await client.get_versions() == (4, 9)
    await client.aclose()


async def test_headers_sent() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"version": 1, "assignments_version": 1})

    client = make_client(handler, api_key="k1", environment="prod")
    await client.get_versions()
    assert seen[0].headers["Authorization"] == "Bearer k1"
    assert seen[0].headers["X-Osiki-Environment"] == "prod"
    await client.aclose()

    seen.clear()
    client = make_client(handler)
    await client.get_versions()
    assert "Authorization" not in seen[0].headers
    assert seen[0].headers["X-Osiki-Environment"] == "default"
    await client.aclose()


async def test_bundle_200_and_404_none() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/missing/bundle"):
            return httpx.Response(404, json={"detail": "nope"})
        return httpx.Response(200, json={"user_id": "u1"})

    client = make_client(handler)
    bundle = await client.get_bundle("u1")
    assert bundle is not None and bundle.user_id == "u1"
    assert await client.get_bundle("missing") is None
    await client.aclose()


async def test_user_id_url_encoded() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(404)

    client = make_client(handler)
    await client.get_bundle("a/b")
    assert seen[0].url.raw_path.decode() == "/api/v1/users/by-external/a%2Fb/bundle"
    await client.aclose()


async def test_5xx_and_connect_error_raise_unavailable() -> None:
    client = make_client(lambda request: httpx.Response(503))
    with pytest.raises(EngineUnavailable):
        await client.get_versions()
    await client.aclose()

    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    client = make_client(boom)
    with pytest.raises(EngineUnavailable):
        await client.get_versions()
    await client.aclose()


async def test_4xx_raises_engine_error() -> None:
    client = make_client(lambda request: httpx.Response(422, json={"detail": "bad"}))
    with pytest.raises(EngineError) as info:
        await client.get_versions()
    assert info.value.status == 422
    assert info.value.body == {"detail": "bad"}
    await client.aclose()


async def test_4xx_non_json_body() -> None:
    client = make_client(lambda request: httpx.Response(403, text="forbidden"))
    with pytest.raises(EngineError) as info:
        await client.get_versions()
    assert info.value.body == "forbidden"
    await client.aclose()


async def test_report_endpoints_chunks_1000() -> None:
    bodies: list[dict[str, list[dict[str, str]]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/endpoints/discovered"
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={})

    client = make_client(handler)
    await client.report_endpoints([("GET", f"/p{i}") for i in range(2500)])
    assert [len(b["endpoints"]) for b in bodies] == [1000, 1000, 500]
    assert bodies[0]["endpoints"][0] == {"method": "GET", "path": "/p0"}
    bodies.clear()
    await client.report_endpoints([])
    assert bodies == []
    await client.aclose()


async def test_access_logs_chunks_500() -> None:
    bodies: list[dict[str, list[dict[str, int]]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/access-logs/batch"
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={})

    client = make_client(handler)
    await client.send_access_logs([{"n": i} for i in range(1001)])
    assert [len(b["entries"]) for b in bodies] == [500, 500, 1]
    await client.aclose()


async def test_sync_calls() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.method == "DELETE" and "gone" in request.url.path:
            return httpx.Response(404)
        if "/members/" in request.url.path:
            return httpx.Response(204)
        return httpx.Response(200, json={})

    client = make_client(handler)
    await client.upsert_user("u/1", name="N", email="e@x.io", attributes={"a": 1})
    await client.upsert_user("u2")
    await client.upsert_tenant("t/1", name="T", attributes={"plan": "pro"})
    await client.upsert_tenant("t2", name="T2")
    await client.add_member("t/1", "u/1")
    assert await client.remove_member("t/1", "u/1") is True
    assert await client.remove_member("t/1", "gone") is False

    raw = [(r.method, r.url.raw_path.decode()) for r in seen]
    assert raw == [
        ("PUT", "/api/v1/users/by-external/u%2F1"),
        ("PUT", "/api/v1/users/by-external/u2"),
        ("PUT", "/api/v1/tenants/t%2F1"),
        ("PUT", "/api/v1/tenants/t2"),
        ("PUT", "/api/v1/tenants/t%2F1/members/u%2F1"),
        ("DELETE", "/api/v1/tenants/t%2F1/members/u%2F1"),
        ("DELETE", "/api/v1/tenants/t%2F1/members/gone"),
    ]
    assert json.loads(seen[0].content) == {
        "name": "N",
        "email": "e@x.io",
        "attributes": {"a": 1},
    }
    assert json.loads(seen[1].content) == {
        "name": None,
        "email": None,
        "attributes": None,
    }
    assert json.loads(seen[2].content) == {"name": "T", "attributes": {"plan": "pro"}}
    assert json.loads(seen[3].content) == {"name": "T2", "attributes": {}}
    await client.aclose()


async def test_default_client_without_transport() -> None:
    client = EngineClient(OsikiConfig(base_url="http://engine/"))
    await client.aclose()
