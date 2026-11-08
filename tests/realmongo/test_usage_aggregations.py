"""The usage aggregations on a real server (the mongomock suite shims them)."""

import time

import pytest
from beanie import PydanticObjectId

from osiki.models.base import Scope
from osiki.models.group_role import GroupRole
from osiki.models.role import Role
from osiki.models.user_role import UserRole
from osiki.repositories.environment_state.mongodb_environment_state_repository import (
    MongoDBEnvironmentStateRepository,
)
from osiki.repositories.group_roles.mongodb_group_role_repository import (
    MongoDBGroupRoleRepository,
)
from osiki.repositories.roles.mongodb_role_repository import MongoDBRoleRepository
from osiki.repositories.user_roles.mongodb_user_role_repository import (
    MongoDBUserRoleRepository,
)
from tests.realmongo.conftest import RealMongoEnv

pytestmark = pytest.mark.realmongo


def _state(env: str) -> MongoDBEnvironmentStateRepository:
    return MongoDBEnvironmentStateRepository(env)


async def test_user_role_tenants_with_role(realmongo_env: RealMongoEnv) -> None:
    repo = realmongo_env.user_roles
    elsewhere = MongoDBUserRoleRepository("elsewhere", _state("elsewhere"))
    role, other = PydanticObjectId(), PydanticObjectId()
    now = time.time()

    async def give(
        r: MongoDBUserRoleRepository,
        role_id: PydanticObjectId,
        tenant: str | None,
        expires_at: float | None = None,
    ) -> UserRole:
        return await r.create(
            UserRole(
                user_id=PydanticObjectId(),
                role_id=role_id,
                scope=Scope(tenant_id=tenant),
                assigned_by="admin",
                expires_at=expires_at,
            )
        )

    await give(repo, role, "a")
    await give(repo, role, "a")
    await give(repo, role, "b", now + 3600)
    await give(repo, role, "expired", now - 1)
    await give(repo, role, None)
    revoked = await give(repo, role, "revoked")
    await repo.revoke(str(revoked.id))
    await give(repo, other, "c")
    await give(elsewhere, role, "z")

    result = await repo.tenants_with_role([str(role), str(PydanticObjectId())], now)

    assert result == {str(role): {"a", "b"}}


async def test_group_role_tenants_with_role(realmongo_env: RealMongoEnv) -> None:
    repo = MongoDBGroupRoleRepository("default", realmongo_env.state)
    elsewhere = MongoDBGroupRoleRepository("elsewhere", _state("elsewhere"))
    role = PydanticObjectId()
    now = time.time()

    async def give(
        r: MongoDBGroupRoleRepository,
        tenant: str | None,
        expires_at: float | None = None,
    ) -> GroupRole:
        return await r.create(
            GroupRole(
                group_id=PydanticObjectId(),
                role_id=role,
                scope=Scope(tenant_id=tenant),
                assigned_by="admin",
                expires_at=expires_at,
            )
        )

    await give(repo, "a")
    await give(repo, "a")
    await give(repo, "b", now + 3600)
    await give(repo, "expired", now - 1)
    await give(repo, None)
    revoked = await give(repo, "revoked")
    await repo.revoke(str(revoked.id))
    await give(elsewhere, "z")

    assert await repo.tenants_with_role([str(role)], now) == {str(role): {"a", "b"}}
    assert await repo.tenants_with_role([str(PydanticObjectId())], now) == {}


async def test_copies_of(realmongo_env: RealMongoEnv) -> None:
    repo = realmongo_env.roles
    elsewhere = MongoDBRoleRepository("elsewhere", _state("elsewhere"))
    template = await repo.create(Role(name="Editor", is_template=True))
    other = await repo.create(Role(name="Viewer", is_template=True))
    for tenant in ("acme", "beta"):
        await repo.create(
            Role(name="Editor", tenant_id=tenant, copied_from=template.id)
        )
    await repo.create(Role(name="Viewer", tenant_id="acme", copied_from=other.id))
    gone = await repo.create(
        Role(name="Editor", tenant_id="gone", copied_from=template.id)
    )
    await repo.deactivate(str(gone.id))
    await elsewhere.create(
        Role(name="Editor", tenant_id="acme", copied_from=template.id)
    )

    result = await repo.copies_of([str(template.id), str(PydanticObjectId())])

    assert result == {str(template.id): 2}
