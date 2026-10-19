"""Integration tests for MongoDBRoleRepository."""

import pytest
from beanie import PydanticObjectId
from pymongo.errors import DuplicateKeyError

from osiki.models.permission import Permission
from osiki.models.role import Grant, Role
from osiki.repositories.environment_state.mongodb_environment_state_repository import (
    MongoDBEnvironmentStateRepository,
)
from osiki.repositories.permissions.mongodb_permission_repository import (
    MongoDBPermissionRepository,
)
from osiki.repositories.roles.mongodb_role_repository import MongoDBRoleRepository


async def test_create() -> None:
    repo = MongoDBRoleRepository(
        "default", MongoDBEnvironmentStateRepository("default")
    )
    role = Role(name="admin-role")
    result = await repo.create(role)
    assert result.id is not None
    assert result.name == "admin-role"


async def test_get_by_id() -> None:
    repo = MongoDBRoleRepository(
        "default", MongoDBEnvironmentStateRepository("default")
    )
    role = Role(name="reader-role")
    created = await repo.create(role)
    result = await repo.get_by_id(str(created.id))
    assert result is not None
    assert result.name == "reader-role"


async def test_get_by_id_not_found() -> None:
    repo = MongoDBRoleRepository(
        "default", MongoDBEnvironmentStateRepository("default")
    )
    result = await repo.get_by_id(str(PydanticObjectId()))
    assert result is None


async def test_get_by_name() -> None:
    repo = MongoDBRoleRepository(
        "default", MongoDBEnvironmentStateRepository("default")
    )
    role = Role(name="writer-role")
    await repo.create(role)
    result = await repo.get_by_name("writer-role")
    assert result is not None
    assert result.name == "writer-role"


async def test_get_by_ids() -> None:
    repo = MongoDBRoleRepository(
        "default", MongoDBEnvironmentStateRepository("default")
    )
    r1 = await repo.create(Role(name="role-a"))
    r2 = await repo.create(Role(name="role-b"))
    result = await repo.get_by_ids([str(r1.id), str(r2.id)])
    assert len(result) == 2


async def test_get_children() -> None:
    repo = MongoDBRoleRepository(
        "default", MongoDBEnvironmentStateRepository("default")
    )
    parent = await repo.create(Role(name="parent-role"))
    await repo.create(Role(name="child-1", parent_role_id=parent.id))
    await repo.create(Role(name="child-2", parent_role_id=parent.id))
    result = await repo.get_children(str(parent.id))
    assert len(result) == 2


async def test_update() -> None:
    repo = MongoDBRoleRepository(
        "default", MongoDBEnvironmentStateRepository("default")
    )
    role = Role(name="update-role")
    created = await repo.create(role)
    created.description = "Updated description"
    updated = await repo.update(created)
    assert updated.description == "Updated description"


async def test_add_permission() -> None:
    repo = MongoDBRoleRepository(
        "default", MongoDBEnvironmentStateRepository("default")
    )
    perm_repo = MongoDBPermissionRepository(
        "default", MongoDBEnvironmentStateRepository("default")
    )
    perm = await perm_repo.create(Permission(resource="docs", action="read"))
    role = await repo.create(Role(name="role-with-perm"))
    result = await repo.add_permission(str(role.id), str(perm.id))
    assert result is True
    updated = await repo.get_by_id(str(role.id))
    assert updated is not None
    assert updated.grants == [Grant(permission_id=perm.id)]


async def test_add_permission_not_found() -> None:
    repo = MongoDBRoleRepository(
        "default", MongoDBEnvironmentStateRepository("default")
    )
    result = await repo.add_permission(str(PydanticObjectId()), str(PydanticObjectId()))
    assert result is False


async def test_remove_permission() -> None:
    repo = MongoDBRoleRepository(
        "default", MongoDBEnvironmentStateRepository("default")
    )
    perm_id = PydanticObjectId()
    role = await repo.create(
        Role(name="role-with-perm-2", grants=[Grant(permission_id=perm_id)])
    )
    result = await repo.remove_permission(str(role.id), str(perm_id))
    assert result is True
    updated = await repo.get_by_id(str(role.id))
    assert updated is not None
    assert updated.grants == []


async def test_remove_permission_not_found() -> None:
    repo = MongoDBRoleRepository(
        "default", MongoDBEnvironmentStateRepository("default")
    )
    result = await repo.remove_permission(
        str(PydanticObjectId()), str(PydanticObjectId())
    )
    assert result is False


async def test_deactivate() -> None:
    repo = MongoDBRoleRepository(
        "default", MongoDBEnvironmentStateRepository("default")
    )
    role = await repo.create(Role(name="to-deactivate-role"))
    result = await repo.deactivate(str(role.id))
    assert result is True
    updated = await repo.get_by_id(str(role.id))
    assert updated is not None
    assert updated.is_active is False


async def test_deactivate_system_role() -> None:
    repo = MongoDBRoleRepository(
        "default", MongoDBEnvironmentStateRepository("default")
    )
    role = await repo.create(Role(name="system-role", is_system=True))
    result = await repo.deactivate(str(role.id))
    assert result is False


async def test_deactivate_not_found() -> None:
    repo = MongoDBRoleRepository(
        "default", MongoDBEnvironmentStateRepository("default")
    )
    result = await repo.deactivate(str(PydanticObjectId()))
    assert result is False


async def test_list_active() -> None:
    repo = MongoDBRoleRepository(
        "default", MongoDBEnvironmentStateRepository("default")
    )
    await repo.create(Role(name="active-role-1"))
    await repo.create(Role(name="active-role-2"))
    result = await repo.list_active()
    assert len(result) >= 2


async def test_add_permission_is_idempotent_per_exact_grant() -> None:
    repo = MongoDBRoleRepository(
        "default", MongoDBEnvironmentStateRepository("default")
    )
    pid, cid = PydanticObjectId(), PydanticObjectId()
    role = await repo.create(Role(name="idem-role"))

    assert await repo.add_permission(str(role.id), str(pid)) is True
    assert await repo.add_permission(str(role.id), str(pid)) is True
    assert await repo.add_permission(str(role.id), str(pid), str(cid)) is True

    updated = await repo.get_by_id(str(role.id))
    assert updated is not None
    assert updated.grants == [
        Grant(permission_id=pid),
        Grant(permission_id=pid, condition_id=cid),
    ]


async def test_remove_exact_grant_only() -> None:
    repo = MongoDBRoleRepository(
        "default", MongoDBEnvironmentStateRepository("default")
    )
    pid, cid = PydanticObjectId(), PydanticObjectId()
    role = await repo.create(
        Role(
            name="exact-role",
            grants=[
                Grant(permission_id=pid),
                Grant(permission_id=pid, condition_id=cid),
            ],
        )
    )

    assert await repo.remove_permission(str(role.id), str(pid), str(cid)) is True

    updated = await repo.get_by_id(str(role.id))
    assert updated is not None
    assert updated.grants == [Grant(permission_id=pid)]


async def test_remove_missing_grant_is_noop() -> None:
    repo = MongoDBRoleRepository(
        "default", MongoDBEnvironmentStateRepository("default")
    )
    role = await repo.create(Role(name="noop-role"))

    assert await repo.remove_permission(str(role.id), str(PydanticObjectId())) is True


async def test_is_condition_in_use() -> None:
    repo = MongoDBRoleRepository(
        "default", MongoDBEnvironmentStateRepository("default")
    )
    cid = PydanticObjectId()
    await repo.create(
        Role(
            name="uses-cond",
            grants=[Grant(permission_id=PydanticObjectId(), condition_id=cid)],
        )
    )
    inactive = PydanticObjectId()
    gone = await repo.create(
        Role(
            name="gone",
            grants=[Grant(permission_id=PydanticObjectId(), condition_id=inactive)],
        )
    )
    await repo.deactivate(str(gone.id))

    assert await repo.is_condition_in_use(str(cid)) is True
    assert await repo.is_condition_in_use(str(inactive)) is False
    assert await repo.is_condition_in_use(str(PydanticObjectId())) is False
    assert (
        await MongoDBRoleRepository(
            "other", MongoDBEnvironmentStateRepository("other")
        ).is_condition_in_use(str(cid))
        is False
    )


async def test_get_all_active_is_unpaginated_and_skips_inactive() -> None:
    repo = MongoDBRoleRepository(
        "default", MongoDBEnvironmentStateRepository("default")
    )
    for i in range(105):
        await repo.create(Role(name=f"bulk-{i}"))
    dead = await repo.create(Role(name="dead"))
    await repo.deactivate(str(dead.id))
    other = MongoDBRoleRepository("other", MongoDBEnvironmentStateRepository("other"))
    await other.create(Role(name="elsewhere"))

    result = await repo.get_all_active()

    assert len(result) == 105
    assert all(r.is_active and r.environment_id == "default" for r in result)


def _repo(environment: str = "default") -> MongoDBRoleRepository:
    return MongoDBRoleRepository(
        environment, MongoDBEnvironmentStateRepository(environment)
    )


async def test_get_by_name_is_scoped_to_project_or_tenant() -> None:
    repo = _repo()
    project = await repo.create(Role(name="scoped-name"))
    acme = await repo.create(Role(name="scoped-name", tenant_id="acme"))

    found_project = await repo.get_by_name("scoped-name")
    found_acme = await repo.get_by_name("scoped-name", "acme")

    assert found_project is not None and found_project.id == project.id
    assert found_acme is not None and found_acme.id == acme.id
    assert await repo.get_by_name("scoped-name", "other") is None
    assert await repo.get_by_name("only-in-acme-x") is None


async def test_get_by_name_ignores_inactive() -> None:
    repo = _repo()
    role = await repo.create(Role(name="gone-name", tenant_id="acme"))
    await repo.deactivate(str(role.id))
    assert await repo.get_by_name("gone-name", "acme") is None


async def test_names_are_unique_per_environment_and_tenant() -> None:
    repo = _repo()
    await repo.create(Role(name="dup-name", tenant_id="acme"))
    await repo.create(Role(name="dup-name", tenant_id="globex"))
    await repo.create(Role(name="dup-name"))
    await _repo("other-env").create(Role(name="dup-name", tenant_id="acme"))

    with pytest.raises(DuplicateKeyError):
        await repo.create(Role(name="dup-name", tenant_id="acme"))
    with pytest.raises(DuplicateKeyError):
        await repo.create(Role(name="dup-name"))


async def test_list_tenant_returns_only_that_tenants_active_roles() -> None:
    repo = _repo()
    mine = await repo.create(Role(name="lt-a", tenant_id="lt-acme"))
    dead = await repo.create(Role(name="lt-b", tenant_id="lt-acme"))
    await repo.deactivate(str(dead.id))
    await repo.create(Role(name="lt-c", tenant_id="lt-globex"))
    await repo.create(Role(name="lt-d"))
    await _repo("other-env").create(Role(name="lt-e", tenant_id="lt-acme"))

    assert [r.id for r in await repo.list_tenant("lt-acme")] == [mine.id]
    assert await repo.list_tenant("lt-nobody") == []


async def test_list_templates_returns_active_project_templates_only() -> None:
    repo = _repo("tpl-env")
    template = await repo.create(Role(name="tpl-a", is_template=True))
    dead = await repo.create(Role(name="tpl-b", is_template=True))
    await repo.deactivate(str(dead.id))
    await repo.create(Role(name="tpl-c"))
    await repo.create(Role(name="tpl-d", is_template=True, tenant_id="acme"))
    await _repo("tpl-other").create(Role(name="tpl-e", is_template=True))

    assert [r.id for r in await repo.list_templates()] == [template.id]


async def test_list_active_excludes_tenant_roles() -> None:
    repo = _repo("la-env")
    project = await repo.create(Role(name="la-a"))
    await repo.create(Role(name="la-b", tenant_id="acme"))

    assert [r.id for r in await repo.list_active()] == [project.id]
    # get_all_active still sees everything; the snapshot filters itself.
    assert len(await repo.get_all_active()) == 2


async def test_role_tenant_fields_round_trip() -> None:
    repo = _repo()
    source = PydanticObjectId()
    created = await repo.create(
        Role(name="rt-a", tenant_id="acme", copied_from=source, is_template=False)
    )
    loaded = await repo.get_by_id(str(created.id))
    assert loaded is not None
    assert (loaded.tenant_id, loaded.copied_from) == ("acme", source)
