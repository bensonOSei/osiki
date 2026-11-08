"""A role replace is one transaction: revoke, assign and audit commit together
or not at all (M4a D6)."""

import asyncio
from typing import Any

import pytest
from beanie import PydanticObjectId
from pymongo.errors import DuplicateKeyError

from osiki.api.actor import Actor
from osiki.api.dependencies import get_permission_repository
from osiki.models.base import Scope
from osiki.models.role import Role
from osiki.models.user_role import UserRole
from osiki.services.team.models import LastManager
from tests.mocks import make_permission, make_role, make_user, make_user_role
from tests.realmongo.conftest import ENVIRONMENT_ID, RealMongoEnv
from tests.realmongo.test_last_manager_race import (
    TENANT,
    owners_left,
    service,
    two_owners,
)

pytestmark = pytest.mark.realmongo

DEVELOPER = Actor(type="developer", id="dev")


async def tenant_role(env: RealMongoEnv, name: str) -> Role:
    till = await get_permission_repository(ENVIRONMENT_ID, env.state).create(
        make_permission("till", name.lower().replace(" ", "-"))
    )
    return await env.roles.create(
        make_role(name, permission_ids=[till.id], tenant_id=TENANT)
    )


async def staff_holding(env: RealMongoEnv, role: Role) -> PydanticObjectId:
    user = await env.users.create(make_user(external_id="staff"))
    await env.members.add(TENANT, "staff")
    assert user.id is not None and role.id is not None
    await env.user_roles.create(
        make_user_role(user.id, role.id, scope=Scope(tenant_id=TENANT))
    )
    return user.id


async def live_roles(env: RealMongoEnv, user_id: PydanticObjectId) -> set[str]:
    return {
        str(a.role_id)
        for a in await env.user_roles.get_by_tenant(TENANT)
        if a.user_id == user_id
    }


async def replaces(env: RealMongoEnv) -> int:
    return sum(
        e.action == "assignment.replace" for e in await env.audit.list(None, 0, 50)
    )


async def test_a_failure_after_the_revoke_rolls_the_replace_back(
    realmongo_env: RealMongoEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The assign fails after the revoke was written (a concurrent assign took
    the slot): the revoke is rolled back and no audit entry is written."""
    await two_owners(realmongo_env)
    cashier = await tenant_role(realmongo_env, "Cashier")
    weekend = await tenant_role(realmongo_env, "Weekend cashier")
    staff = await staff_holding(realmongo_env, cashier)
    revoked: list[str] = []
    real_revoke = realmongo_env.user_roles.revoke

    async def tracking_revoke(user_role_id: str, **kwargs: Any) -> bool:
        revoked.append(user_role_id)
        return await real_revoke(user_role_id, **kwargs)

    async def taken(user_role: UserRole, **kwargs: Any) -> UserRole:
        raise DuplicateKeyError("E11000 duplicate key")

    monkeypatch.setattr(realmongo_env.user_roles, "revoke", tracking_revoke)
    monkeypatch.setattr(realmongo_env.user_roles, "create", taken)

    with pytest.raises(Exception, match="Role already assigned"):
        await service(realmongo_env, DEVELOPER).replace_role(
            "staff", str(cashier.id), str(weekend.id)
        )

    assert revoked, "the revoke ran before the failing assign"
    assert await live_roles(realmongo_env, staff) == {str(cashier.id)}
    assert await replaces(realmongo_env) == 0


async def test_two_concurrent_replaces_of_one_role_apply_once(
    realmongo_env: RealMongoEnv,
) -> None:
    """Both swap Cashier away; the loser re-runs its checks after the winner
    commits, finds Cashier gone and is refused, so the member never ends up
    with both new roles."""
    await two_owners(realmongo_env)
    cashier = await tenant_role(realmongo_env, "Cashier")
    weekend = await tenant_role(realmongo_env, "Weekend cashier")
    stock = await tenant_role(realmongo_env, "Stock")
    staff = await staff_holding(realmongo_env, cashier)

    results = await asyncio.gather(
        service(realmongo_env, DEVELOPER).replace_role(
            "staff", str(cashier.id), str(weekend.id)
        ),
        service(realmongo_env, DEVELOPER).replace_role(
            "staff", str(cashier.id), str(stock.id)
        ),
        return_exceptions=True,
    )

    assert sorted(type(r).__name__ for r in results) == ["NotFoundError", "TeamMember"]
    held = await live_roles(realmongo_env, staff)
    assert len(held) == 1 and held <= {str(weekend.id), str(stock.id)}
    assert await replaces(realmongo_env) == 1


# Mongo matches an ObjectId whatever its hex case; the guards must see the same
# row the write then revokes (review fix round 1).


async def test_replace_with_an_uppercase_id_keeps_the_last_manager(
    realmongo_env: RealMongoEnv,
) -> None:
    owner_id = await two_owners(realmongo_env)
    await service(realmongo_env, DEVELOPER).revoke_role("bob", owner_id)
    cashier = await tenant_role(realmongo_env, "Cashier")

    with pytest.raises(LastManager):
        await service(realmongo_env, DEVELOPER).replace_role(
            "alice", owner_id.upper(), str(cashier.id)
        )

    assert await owners_left(realmongo_env, owner_id) == 1
    assert await replaces(realmongo_env) == 0


async def test_revoke_with_an_uppercase_id_keeps_the_last_manager(
    realmongo_env: RealMongoEnv,
) -> None:
    owner_id = await two_owners(realmongo_env)
    await service(realmongo_env, DEVELOPER).revoke_role("bob", owner_id)

    with pytest.raises(LastManager):
        await service(realmongo_env, DEVELOPER).revoke_role("alice", owner_id.upper())

    assert await owners_left(realmongo_env, owner_id) == 1
