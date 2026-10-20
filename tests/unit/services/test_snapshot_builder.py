"""Unit tests for SnapshotBuilder and SnapshotCache."""

from unittest.mock import patch

import pytest
from beanie import PydanticObjectId

from osiki.decision.decide import decide
from osiki.decision.models import (
    ConstraintEntry,
    EndpointEntry,
    EnvironmentSettings,
    GrantEntry,
    RoleEntry,
)
from osiki.models.constraint import ConstraintConfig, ConstraintType
from osiki.models.role import Grant
from osiki.services.snapshot_builder import SnapshotBuilder, SnapshotCache
from tests.mocks import (
    MockConditionRepository,
    MockConstraintRepository,
    MockEndpointRepository,
    MockEnvironmentStateRepository,
    MockPermissionRepository,
    MockRoleRepository,
    make_assignment_entry,
    make_condition,
    make_constraint,
    make_decision_request,
    make_permission,
    make_role,
    make_user_bundle,
)

EXPR = {"op": "eq", "left": {"ref": "record.team_id"}, "right": {"ref": "user.team_id"}}


class Env:
    def __init__(self, environment_id: str = "default") -> None:
        self.state = MockEnvironmentStateRepository(environment_id)
        self.roles = MockRoleRepository(environment_id, self.state)
        self.permissions = MockPermissionRepository(environment_id, self.state)
        self.conditions = MockConditionRepository(environment_id, self.state)
        self.constraints = MockConstraintRepository(environment_id, self.state)
        self.endpoints = MockEndpointRepository(environment_id, self.state)
        self.cache = SnapshotCache()
        self.environment_id = environment_id

    def builder(self) -> SnapshotBuilder:
        return SnapshotBuilder(
            self.environment_id,
            self.state,
            self.roles,
            self.permissions,
            self.conditions,
            self.constraints,
            self.endpoints,
            cache=self.cache,
        )


@pytest.fixture
def env() -> Env:
    return Env()


async def test_empty_environment_builds_empty_snapshot(env: Env) -> None:
    snapshot = await env.builder().build()

    assert snapshot.environment_id == "default"
    assert snapshot.version == 0
    assert snapshot.roles == []
    assert snapshot.conditions == {}
    assert snapshot.constraints == []
    assert snapshot.endpoints == []
    assert snapshot.settings == EnvironmentSettings(unmapped="deny")


async def test_snapshot_renders_the_stored_settings(env: Env) -> None:
    env.state.settings = EnvironmentSettings(unmapped="allow")

    snapshot = await env.builder().build()

    assert snapshot.settings.unmapped == "allow"


async def test_snapshot_renders_roles_grants_conditions_and_constraints(
    env: Env,
) -> None:
    read = await env.permissions.create(make_permission("invoices", "read"))
    write = await env.permissions.create(make_permission("invoices", "write"))
    cond = await env.conditions.create(make_condition(key="own_team", expression=EXPR))
    parent = await env.roles.create(make_role(name="base", permission_ids=[read.id]))
    child = await env.roles.create(
        make_role(
            name="clerk",
            grants=[Grant(permission_id=write.id, condition_id=cond.id)],
            parent_role_id=parent.id,
        )
    )
    role_id = PydanticObjectId()
    constraint = await env.constraints.create(
        make_constraint(
            "c",
            ConstraintType.CARDINALITY,
            ConstraintConfig(role_ids=[role_id], max_assignments=2),
        )
    )

    snapshot = await env.builder().build()

    assert snapshot.version == await env.state.get_config_version()
    assert snapshot.roles == [
        RoleEntry(
            id=str(parent.id),
            name="base",
            grants=[GrantEntry(permission="invoices:read")],
        ),
        RoleEntry(
            id=str(child.id),
            name="clerk",
            parent_id=str(parent.id),
            grants=[GrantEntry(permission="invoices:write", condition="own_team")],
        ),
    ]
    assert snapshot.conditions == {"own_team": EXPR}
    assert snapshot.constraints == [
        ConstraintEntry(
            id=str(constraint.id),
            name=constraint.name,
            type=constraint.type.value,
            config={"role_ids": [str(role_id)], "max_assignments": 2},
        )
    ]


async def test_snapshot_excludes_inactive(env: Env) -> None:
    live = await env.permissions.create(make_permission("docs", "read"))
    dead = await env.permissions.create(make_permission("docs", "write"))
    await env.permissions.deactivate(str(dead.id))
    gone = await env.conditions.create(make_condition(key="gone", expression=EXPR))
    await env.conditions.deactivate(str(gone.id))
    kept = await env.roles.create(
        make_role(name="kept", permission_ids=[live.id, dead.id])
    )
    dropped = await env.roles.create(
        make_role(name="dropped", permission_ids=[live.id])
    )
    await env.roles.deactivate(str(dropped.id))
    constraint = await env.constraints.create(
        make_constraint("c", ConstraintType.CARDINALITY, ConstraintConfig())
    )
    await env.constraints.deactivate(str(constraint.id))

    snapshot = await env.builder().build()

    assert [r.id for r in snapshot.roles] == [str(kept.id)]
    assert snapshot.roles[0].grants == [GrantEntry(permission="docs:read")]
    assert snapshot.conditions == {}
    assert snapshot.constraints == []


async def test_grant_with_inactive_condition_keeps_its_key_and_denies(
    env: Env,
) -> None:
    perm = await env.permissions.create(make_permission("invoices", "read"))
    cond = await env.conditions.create(make_condition(key="own_team", expression=EXPR))
    await env.conditions.deactivate(str(cond.id))
    role = await env.roles.create(
        make_role(name="r", grants=[Grant(permission_id=perm.id, condition_id=cond.id)])
    )

    snapshot = await env.builder().build()

    assert snapshot.roles[0].grants == [
        GrantEntry(permission="invoices:read", condition="own_team")
    ]
    assert "own_team" not in snapshot.conditions
    bundle = make_user_bundle(
        assignments=[make_assignment_entry(role_id=str(role.id))],
        attributes={"team_id": "t1"},
    )
    decision = decide(
        snapshot,
        bundle,
        make_decision_request("invoices", "read", record={"team_id": "t1"}),
    )
    assert decision.allowed is False
    assert decision.denial_reason == "condition_failed"


async def test_grant_with_missing_condition_is_never_unconditional(
    env: Env,
) -> None:
    perm = await env.permissions.create(make_permission("invoices", "read"))
    missing = PydanticObjectId()
    role = await env.roles.create(
        make_role(name="r", grants=[Grant(permission_id=perm.id, condition_id=missing)])
    )

    snapshot = await env.builder().build()

    assert snapshot.roles[0].grants == [
        GrantEntry(permission="invoices:read", condition=f"missing:{missing}")
    ]
    bundle = make_user_bundle(assignments=[make_assignment_entry(role_id=str(role.id))])
    with_record = decide(
        snapshot, bundle, make_decision_request("invoices", "read", record={})
    )
    assert with_record.allowed is False
    assert with_record.denial_reason == "condition_failed"
    without_record = decide(snapshot, bundle, make_decision_request("invoices", "read"))
    assert without_record.allowed is False
    assert without_record.denial_reason == "record_required"


async def test_snapshot_cached_until_version_changes(env: Env) -> None:
    await env.roles.create(make_role(name="r"))
    builder = env.builder()

    with patch.object(
        env.roles, "get_all_active", wraps=env.roles.get_all_active
    ) as spy:
        first = await builder.build()
        second = await env.builder().build()
        assert spy.call_count == 1
        assert second is first

        await env.state.bump_config_version()
        third = await builder.build()

        assert spy.call_count == 2
        assert third.version == first.version + 1


async def test_config_write_invalidates_the_cached_snapshot(env: Env) -> None:
    builder = env.builder()
    assert (await builder.build()).roles == []

    role = await env.roles.create(make_role(name="new"))

    assert [r.id for r in (await builder.build()).roles] == [str(role.id)]


async def test_cache_is_keyed_by_environment() -> None:
    a = Env("a")
    b = Env("b")
    b.cache = a.cache
    await a.roles.create(make_role(name="only-in-a"))
    # Same version in both environments: only the key can tell them apart.
    await b.state.bump_config_version()
    assert await a.state.get_config_version() == await b.state.get_config_version()

    snap_a = await a.builder().build()
    snap_b = await b.builder().build()

    assert snap_a.environment_id == "a"
    assert [r.name for r in snap_a.roles] == ["only-in-a"]
    assert snap_b.environment_id == "b"
    assert snap_b.roles == []
    assert snap_b is not snap_a


async def test_snapshot_cache_get_and_put() -> None:
    cache = SnapshotCache()
    assert cache.get("default") is None

    snapshot = await Env().builder().build()
    cache.put(snapshot)

    assert cache.get("default") is snapshot


async def test_mappings_render_into_the_snapshot_sorted(env: Env) -> None:
    for method, path in [("POST", "/b"), ("GET", "/b"), ("GET", "/a")]:
        await env.endpoints.upsert_mapping(
            EndpointEntry(method=method, path=path, permission="x:y")
        )

    snapshot = await env.builder().build()

    assert [(e.path, e.method) for e in snapshot.endpoints] == [
        ("/a", "GET"),
        ("/b", "GET"),
        ("/b", "POST"),
    ]


async def test_snapshot_excludes_tenant_roles(env: Env) -> None:
    permission = await env.permissions.create(make_permission("docs", "read"))
    project = await env.roles.create(
        make_role(name="project", permission_ids=[permission.id])
    )
    await env.roles.create(
        make_role(name="project", permission_ids=[permission.id], tenant_id="acme")
    )
    template = await env.roles.create(
        make_role(name="starter", permission_ids=[permission.id], is_template=True)
    )

    snapshot = await env.builder().build()

    assert [r.id for r in snapshot.roles] == [str(project.id), str(template.id)]
