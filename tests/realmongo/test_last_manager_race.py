"""The last-manager guard under concurrent transactions (Review Focus 3).

Two revokes that each leave one manager pass the guard on their own; run
together, both bumping the tenant lock makes one write-conflict, retry and
re-evaluate the guard against the winner's commit.
"""

import asyncio

import pytest
from beanie import PydanticObjectId

from osiki.api.actor import Actor
from osiki.api.dependencies import (
    get_bundle_builder,
    get_condition_repository,
    get_constraint_repository,
    get_constraint_validator,
    get_endpoint_repository,
    get_group_repository,
    get_group_role_repository,
    get_permission_repository,
    get_snapshot_builder,
    get_tenant_repository,
    get_tenant_team_lock_repository,
    get_user_group_repository,
)
from osiki.configs.database import get_client
from osiki.models.base import Scope
from osiki.services.audit.audit_writer import AuditWriter
from osiki.services.builtins import ensure_builtins
from osiki.services.snapshot_builder.snapshot_builder import SnapshotCache
from osiki.services.team.models import LastManager, NotManager
from osiki.services.team.team_service import TeamService
from osiki.services.unit_of_work import MongoUnitOfWork
from tests.mocks import make_user, make_user_role
from tests.realmongo.conftest import ENVIRONMENT_ID, RealMongoEnv

pytestmark = pytest.mark.realmongo

TENANT = "acme"


def service(env: RealMongoEnv, actor: Actor) -> TeamService:
    """A TeamService wired to the real database, as one request would get."""
    state = env.state
    permissions = get_permission_repository(ENVIRONMENT_ID, state)
    conditions = get_condition_repository(ENVIRONMENT_ID, state)
    constraints = get_constraint_repository(ENVIRONMENT_ID, state)
    group_roles = get_group_role_repository(ENVIRONMENT_ID, state)
    return TeamService(
        ENVIRONMENT_ID,
        TENANT,
        actor,
        role_repo=env.roles,
        permission_repo=permissions,
        condition_repo=conditions,
        user_role_repo=env.user_roles,
        group_role_repo=group_roles,
        user_repo=env.users,
        member_repo=env.members,
        lock_repo=get_tenant_team_lock_repository(ENVIRONMENT_ID),
        snapshot_builder=get_snapshot_builder(
            ENVIRONMENT_ID,
            state,
            env.roles,
            permissions,
            conditions,
            constraints,
            get_endpoint_repository(ENVIRONMENT_ID, state),
            SnapshotCache(),
        ),
        bundle_builder=get_bundle_builder(
            env.users,
            env.user_roles,
            get_user_group_repository(ENVIRONMENT_ID, state),
            get_group_repository(ENVIRONMENT_ID, state),
            group_roles,
            env.members,
            get_tenant_repository(ENVIRONMENT_ID, state),
            env.roles,
            permissions,
            conditions,
        ),
        validator=get_constraint_validator(constraints, env.user_roles),
        uow=MongoUnitOfWork(get_client(), enabled=True),
        audit=AuditWriter(env.audit),
    )


async def two_owners(env: RealMongoEnv) -> str:
    builtins = await ensure_builtins(
        get_permission_repository(ENVIRONMENT_ID, env.state), env.roles
    )
    await get_tenant_repository(ENVIRONMENT_ID, env.state).upsert(TENANT, TENANT, {})
    for external_id in ("alice", "bob"):
        user = await env.users.create(make_user(external_id=external_id))
        await env.members.add(TENANT, external_id)
        assert user.id is not None
        await env.user_roles.create(
            make_user_role(
                user.id,
                PydanticObjectId(builtins.owner_role_id),
                scope=Scope(tenant_id=TENANT),
            )
        )
    return builtins.owner_role_id


async def owners_left(env: RealMongoEnv, owner_id: str) -> int:
    return len(await env.user_roles.get_by_tenant(TENANT, owner_id))


async def test_two_managers_revoking_each_other_concurrently(
    realmongo_env: RealMongoEnv,
) -> None:
    """The brief's case: each revoke alone would leave one manager."""
    owner_id = await two_owners(realmongo_env)
    developer = Actor(type="developer", id="dev")

    results = await asyncio.gather(
        service(realmongo_env, developer).revoke_role("alice", owner_id),
        service(realmongo_env, developer).revoke_role("bob", owner_id),
        return_exceptions=True,
    )

    assert sorted(type(r).__name__ for r in results) == ["LastManager", "NoneType"]
    assert await owners_left(realmongo_env, owner_id) == 1
    revokes = [
        e
        for e in await realmongo_env.audit.list(None, 0, 10)
        if e.action == "assignment.revoke"
    ]
    assert len(revokes) == 1


async def test_two_owners_revoking_each_other_as_tenant_users(
    realmongo_env: RealMongoEnv,
) -> None:
    """Alice revokes Bob while Bob revokes Alice. The loser re-runs every
    check, so it is refused either as no longer a manager or as the last."""
    owner_id = await two_owners(realmongo_env)

    results = await asyncio.gather(
        service(realmongo_env, Actor(type="tenant_user", id="alice")).revoke_role(
            "bob", owner_id
        ),
        service(realmongo_env, Actor(type="tenant_user", id="bob")).revoke_role(
            "alice", owner_id
        ),
        return_exceptions=True,
    )

    assert sum(r is None for r in results) == 1
    assert sum(isinstance(r, LastManager | NotManager) for r in results) == 1
    assert await owners_left(realmongo_env, owner_id) == 1


async def test_two_managers_removed_concurrently(
    realmongo_env: RealMongoEnv,
) -> None:
    owner_id = await two_owners(realmongo_env)
    developer = Actor(type="developer", id="dev")

    results = await asyncio.gather(
        service(realmongo_env, developer).remove_member("alice"),
        service(realmongo_env, developer).remove_member("bob"),
        return_exceptions=True,
    )

    assert sorted(type(r).__name__ for r in results) == ["LastManager", "NoneType"]
    assert await owners_left(realmongo_env, owner_id) == 1
    remaining = [
        m for m in ("alice", "bob") if await realmongo_env.members.is_member(TENANT, m)
    ]
    assert len(remaining) == 1
