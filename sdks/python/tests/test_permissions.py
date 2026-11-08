import json
from typing import Any

import httpx
import pytest

from osiki_sdk import (
    EngineError,
    EngineUnavailable,
    Osiki,
    PermissionDeleted,
    PermissionSpec,
)


class FakeEngine:
    """An in-memory /permissions endpoint behind an httpx.MockTransport."""

    def __init__(self, existing: list[dict[str, Any]] | None = None) -> None:
        self.perms = list(existing or [])
        self.writes: list[tuple[str, str, Any]] = []
        self.reads: list[str] = []
        self.conflict_on_create: dict[str, Any] | None = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/api/v1")
        body = json.loads(request.content) if request.content else None
        if request.method == "GET":
            page = int(request.url.params["page"])
            size = int(request.url.params["page_size"])
            self.reads.append(str(request.url.query, "ascii"))
            items = self.perms[(page - 1) * size : page * size]
            return httpx.Response(200, json={"items": items, "total": len(items)})
        self.writes.append((request.method, path, body))
        if request.method == "POST":
            if self.conflict_on_create is not None:
                return httpx.Response(409, json=self.conflict_on_create)
            perm = {
                "id": f"p{len(self.perms)}",
                "resource": body["resource"],
                "action": body["action"],
                "description": body.get("description"),
                "assignable": False,
            }
            self.perms.append(perm)
            return httpx.Response(201, json=perm)
        perm = next(p for p in self.perms if p["id"] == path.rsplit("/", 1)[1])
        perm.update(body)
        return httpx.Response(200, json=perm)


def make(engine: FakeEngine) -> Osiki:
    return Osiki(
        base_url="http://engine",
        environment="dev",
        user_id=lambda r: None,
        transport=httpx.MockTransport(engine),
    )


def perm(resource: str, action: str, **kw: Any) -> dict[str, Any]:
    base = {
        "id": f"{resource}-{action}",
        "resource": resource,
        "action": action,
        "description": None,
        "assignable": False,
    }
    return base | kw


SPECS = [
    PermissionSpec("sales", "create", description="Make a sale", assignable=True),
    PermissionSpec("refunds", "create", description="Refund", assignable=True),
]


async def test_ensure_creates_missing_and_sets_fields() -> None:
    engine = FakeEngine()
    osiki = make(engine)
    result = await osiki.permissions.ensure(SPECS)
    assert result.created == ("refunds:create", "sales:create")
    assert result.updated == () and result.unchanged == ()
    posts = [w for w in engine.writes if w[0] == "POST"]
    patches = [w for w in engine.writes if w[0] == "PATCH"]
    assert [p[2] for p in posts] == [
        {"resource": "sales", "action": "create", "description": "Make a sale"},
        {"resource": "refunds", "action": "create", "description": "Refund"},
    ]
    assert [p[2] for p in patches] == [{"assignable": True}, {"assignable": True}]
    await osiki.aclose()


async def test_ensure_updates_only_differing_fields() -> None:
    engine = FakeEngine([perm("sales", "create", description="Old", assignable=True)])
    osiki = make(engine)
    result = await osiki.permissions.ensure(SPECS[:1])
    assert result.updated == ("sales:create",)
    assert result.created == () and result.unchanged == ()
    assert engine.writes == [
        ("PATCH", "/permissions/sales-create", {"description": "Make a sale"})
    ]
    await osiki.aclose()


async def test_ensure_twice_is_noop() -> None:
    engine = FakeEngine()
    osiki = make(engine)
    await osiki.permissions.ensure(SPECS)
    engine.writes.clear()
    result = await osiki.permissions.ensure(SPECS)
    assert engine.writes == []
    assert result.unchanged == ("refunds:create", "sales:create")
    assert result.created == () and result.updated == ()
    await osiki.aclose()


async def test_ensure_none_fields_left_alone() -> None:
    engine = FakeEngine([perm("sales", "create", description="Keep", assignable=True)])
    osiki = make(engine)
    result = await osiki.permissions.ensure([PermissionSpec("sales", "create")])
    assert engine.writes == []
    assert result.unchanged == ("sales:create",)
    await osiki.aclose()


async def test_ensure_created_without_assignable_sends_no_patch() -> None:
    engine = FakeEngine()
    osiki = make(engine)
    await osiki.permissions.ensure(
        [PermissionSpec("sales", "create", assignable=False)]
    )
    assert [w[0] for w in engine.writes] == ["POST"]
    await osiki.aclose()


async def test_ensure_deleted_permission_raises() -> None:
    engine = FakeEngine()
    engine.conflict_on_create = {
        "error": "conflict",
        "message": "Permission refunds:create was deleted and cannot be recreated",
        "details": {"permission": "refunds:create", "reason": "deleted"},
    }
    osiki = make(engine)
    with pytest.raises(PermissionDeleted, match="refunds:create") as info:
        await osiki.permissions.ensure([PermissionSpec("refunds", "create")])
    assert info.value.permission == "refunds:create"
    assert isinstance(info.value, EngineError)
    assert info.value.status == 409
    await osiki.aclose()


async def test_ensure_other_create_errors_propagate() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json={"items": []})
        return httpx.Response(422, json={"error": "bad"})

    osiki = Osiki(
        base_url="http://engine",
        environment="dev",
        user_id=lambda r: None,
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(EngineError) as info:
        await osiki.permissions.ensure([PermissionSpec("a", "b")])
    assert not isinstance(info.value, PermissionDeleted)
    await osiki.aclose()


async def test_ensure_pages_through_permissions() -> None:
    engine = FakeEngine([perm("r", f"a{i}") for i in range(150)])
    osiki = make(engine)
    specs = [PermissionSpec("r", "a0"), PermissionSpec("r", "a149")]
    result = await osiki.permissions.ensure(specs)
    assert result.unchanged == ("r:a0", "r:a149")
    assert engine.writes == []
    assert len(engine.reads) == 2
    await osiki.aclose()


async def test_ensure_pages_past_an_exact_full_page() -> None:
    engine = FakeEngine([perm("r", f"a{i}") for i in range(100)])
    osiki = make(engine)
    await osiki.permissions.ensure([PermissionSpec("r", "a5")])
    assert len(engine.reads) == 2
    await osiki.aclose()


async def test_ensure_rejects_duplicate_specs() -> None:
    engine = FakeEngine()
    osiki = make(engine)
    with pytest.raises(ValueError, match="sales:create"):
        await osiki.permissions.ensure(
            [PermissionSpec("sales", "create"), PermissionSpec("sales", "create", "x")]
        )
    assert engine.reads == [] and engine.writes == []
    await osiki.aclose()


async def test_ensure_malformed_list_is_engine_error() -> None:
    osiki = Osiki(
        base_url="http://engine",
        environment="dev",
        user_id=lambda r: None,
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json={"items": [1]})
        ),
    )
    with pytest.raises(EngineError):
        await osiki.permissions.ensure([PermissionSpec("a", "b")])
    await osiki.aclose()


async def test_ensure_engine_down_raises_unavailable() -> None:
    osiki = Osiki(
        base_url="http://engine",
        environment="dev",
        user_id=lambda r: None,
        transport=httpx.MockTransport(lambda r: httpx.Response(503)),
    )
    with pytest.raises(EngineUnavailable):
        await osiki.permissions.ensure([PermissionSpec("a", "b")])
    await osiki.aclose()


async def test_ensure_race_409_adopts_the_winner() -> None:
    engine = FakeEngine()
    osiki = make(engine)
    winner = perm("sales", "create", description="Old", assignable=False)
    original = engine.__call__

    def racing(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            engine.perms.append(winner)  # another replica got there first
            return httpx.Response(
                409,
                json={
                    "error": "conflict",
                    "details": {"permission": "sales:create", "reason": "exists"},
                },
            )
        return original(request)

    osiki._client._http._transport = httpx.MockTransport(racing)  # type: ignore[attr-defined]
    result = await osiki.permissions.ensure(
        [PermissionSpec("sales", "create", description="New", assignable=False)]
    )
    assert result.created == () and result.updated == ("sales:create",)
    assert engine.writes == [
        ("PATCH", "/permissions/sales-create", {"description": "New"})
    ]
    await osiki.aclose()


async def test_ensure_unexplained_409_still_raises() -> None:
    engine = FakeEngine()
    engine.conflict_on_create = {"error": "conflict"}
    osiki = make(engine)
    with pytest.raises(EngineError) as info:
        await osiki.permissions.ensure([PermissionSpec("a", "b")])
    assert not isinstance(info.value, PermissionDeleted)
    assert info.value.status == 409
    await osiki.aclose()


async def test_ensure_409_with_non_dict_body_is_not_deleted() -> None:
    osiki = Osiki(
        base_url="http://engine",
        environment="dev",
        user_id=lambda r: None,
        transport=httpx.MockTransport(
            lambda r: (
                httpx.Response(200, json={"items": []})
                if r.method == "GET"
                else httpx.Response(409, text="nope")
            )
        ),
    )
    with pytest.raises(EngineError) as info:
        await osiki.permissions.ensure([PermissionSpec("a", "b")])
    assert not isinstance(info.value, PermissionDeleted)
    await osiki.aclose()


@pytest.mark.parametrize(
    "item",
    [
        {"resource": "a", "action": "b"},
        {"id": 5, "resource": "a", "action": "b"},
        {"id": "x", "resource": None, "action": "b"},
        {"id": "x", "resource": "a", "action": 3},
        {"id": "x", "resource": "a", "action": "b", "assignable": "yes"},
    ],
)
async def test_ensure_malformed_item_is_engine_error(item: dict[str, Any]) -> None:
    osiki = Osiki(
        base_url="http://engine",
        environment="dev",
        user_id=lambda r: None,
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json={"items": [item]})
        ),
    )
    with pytest.raises(EngineError):
        await osiki.permissions.ensure([PermissionSpec("a", "b")])
    await osiki.aclose()


async def test_ensure_malformed_create_response_is_engine_error() -> None:
    osiki = Osiki(
        base_url="http://engine",
        environment="dev",
        user_id=lambda r: None,
        transport=httpx.MockTransport(
            lambda r: (
                httpx.Response(200, json={"items": []})
                if r.method == "GET"
                else httpx.Response(201, json={"id": 1})
            )
        ),
    )
    with pytest.raises(EngineError):
        await osiki.permissions.ensure([PermissionSpec("a", "b")])
    await osiki.aclose()


def test_ensure_result_is_hashable() -> None:
    from osiki_sdk import EnsureResult

    assert hash(EnsureResult(("a:b",), (), ())) == hash(EnsureResult(("a:b",), (), ()))
