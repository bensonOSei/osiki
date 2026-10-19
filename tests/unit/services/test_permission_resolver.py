import pytest
from beanie import PydanticObjectId

from osiki.models.base import Scope
from tests.conftest import (
    make_group_role,
    make_permission,
    make_role,
    make_user_group,
    make_user_role,
)


async def test_get_effective_permissions_no_roles(permission_resolver) -> None:
    user_id = str(PydanticObjectId())
    permissions = await permission_resolver.get_effective_permissions(user_id)
    assert permissions == set()


async def test_get_effective_permissions_direct_role(
    permission_resolver,
    mock_user_role_repository,
    mock_role_repository,
    mock_permission_repository,
) -> None:
    user_id = PydanticObjectId()
    perm = make_permission(resource="docs", action="read")
    await mock_permission_repository.create(perm)

    role = make_role(name="reader", permission_ids=[perm.id])
    await mock_role_repository.create(role)

    user_role = make_user_role(user_id=user_id, role_id=role.id)
    await mock_user_role_repository.create(user_role)

    permissions = await permission_resolver.get_effective_permissions(str(user_id))
    assert permissions == {"docs:read"}


async def test_get_effective_permissions_via_group(
    permission_resolver,
    mock_user_group_repository,
    mock_group_role_repository,
    mock_role_repository,
    mock_permission_repository,
) -> None:
    user_id = PydanticObjectId()
    group_id = PydanticObjectId()

    perm = make_permission(resource="files", action="write")
    await mock_permission_repository.create(perm)

    role = make_role(name="editor", permission_ids=[perm.id])
    await mock_role_repository.create(role)

    user_group = make_user_group(user_id=user_id, group_id=group_id)
    await mock_user_group_repository.create(user_group)

    group_role = make_group_role(group_id=group_id, role_id=role.id)
    await mock_group_role_repository.create(group_role)

    permissions = await permission_resolver.get_effective_permissions(str(user_id))
    assert permissions == {"files:write"}


async def test_get_effective_permissions_combines_direct_and_group(
    permission_resolver,
    mock_user_role_repository,
    mock_user_group_repository,
    mock_group_role_repository,
    mock_role_repository,
    mock_permission_repository,
) -> None:
    user_id = PydanticObjectId()
    group_id = PydanticObjectId()

    perm1 = make_permission(resource="docs", action="read")
    perm2 = make_permission(resource="files", action="write")
    await mock_permission_repository.create(perm1)
    await mock_permission_repository.create(perm2)

    direct_role = make_role(name="reader", permission_ids=[perm1.id])
    group_role_obj = make_role(name="editor", permission_ids=[perm2.id])
    await mock_role_repository.create(direct_role)
    await mock_role_repository.create(group_role_obj)

    user_role = make_user_role(user_id=user_id, role_id=direct_role.id)
    await mock_user_role_repository.create(user_role)

    user_group = make_user_group(user_id=user_id, group_id=group_id)
    await mock_user_group_repository.create(user_group)

    group_role = make_group_role(group_id=group_id, role_id=group_role_obj.id)
    await mock_group_role_repository.create(group_role)

    permissions = await permission_resolver.get_effective_permissions(str(user_id))
    assert permissions == {"docs:read", "files:write"}


async def test_get_effective_permissions_filters_by_scope(
    permission_resolver,
    mock_user_role_repository,
    mock_role_repository,
    mock_permission_repository,
) -> None:
    user_id = PydanticObjectId()

    perm1 = make_permission(resource="docs", action="read")
    perm2 = make_permission(resource="files", action="write")
    await mock_permission_repository.create(perm1)
    await mock_permission_repository.create(perm2)

    role1 = make_role(name="reader", permission_ids=[perm1.id])
    role2 = make_role(name="writer", permission_ids=[perm2.id])
    await mock_role_repository.create(role1)
    await mock_role_repository.create(role2)

    ur1 = make_user_role(user_id=user_id, role_id=role1.id, scope=Scope(tenant_id="t1"))
    ur2 = make_user_role(user_id=user_id, role_id=role2.id, scope=Scope(tenant_id="t2"))
    await mock_user_role_repository.create(ur1)
    await mock_user_role_repository.create(ur2)

    permissions = await permission_resolver.get_effective_permissions(
        str(user_id), scope={"tenant_id": "t1"}
    )
    assert permissions == {"docs:read"}


async def test_get_effective_permissions_skips_inactive_roles(
    permission_resolver,
    mock_user_role_repository,
    mock_role_repository,
    mock_permission_repository,
) -> None:
    user_id = PydanticObjectId()

    perm = make_permission(resource="docs", action="read")
    await mock_permission_repository.create(perm)

    role = make_role(name="reader", permission_ids=[perm.id], is_active=False)
    await mock_role_repository.create(role)

    user_role = make_user_role(user_id=user_id, role_id=role.id)
    await mock_user_role_repository.create(user_role)

    permissions = await permission_resolver.get_effective_permissions(str(user_id))
    assert permissions == set()


async def test_get_effective_permissions_multiple_permissions_per_role(
    permission_resolver,
    mock_user_role_repository,
    mock_role_repository,
    mock_permission_repository,
) -> None:
    user_id = PydanticObjectId()

    perm1 = make_permission(resource="docs", action="read")
    perm2 = make_permission(resource="docs", action="write")
    perm3 = make_permission(resource="docs", action="delete")
    await mock_permission_repository.create(perm1)
    await mock_permission_repository.create(perm2)
    await mock_permission_repository.create(perm3)

    role = make_role(name="admin", permission_ids=[perm1.id, perm2.id, perm3.id])
    await mock_role_repository.create(role)

    user_role = make_user_role(user_id=user_id, role_id=role.id)
    await mock_user_role_repository.create(user_role)

    permissions = await permission_resolver.get_effective_permissions(str(user_id))
    assert permissions == {"docs:read", "docs:write", "docs:delete"}


async def test_get_role_ancestors_single_role(
    permission_resolver,
    mock_role_repository,
) -> None:
    role = make_role(name="reader")
    await mock_role_repository.create(role)

    ancestors = await permission_resolver.get_role_ancestors(str(role.id))
    assert ancestors == [str(role.id)]


async def test_get_role_ancestors_two_levels(
    permission_resolver,
    mock_role_repository,
) -> None:
    parent = make_role(name="parent")
    await mock_role_repository.create(parent)

    child = make_role(name="child", parent_role_id=parent.id)
    await mock_role_repository.create(child)

    ancestors = await permission_resolver.get_role_ancestors(str(child.id))
    assert ancestors == [str(child.id), str(parent.id)]


async def test_get_role_ancestors_three_levels(
    permission_resolver,
    mock_role_repository,
) -> None:
    grandparent = make_role(name="grandparent")
    await mock_role_repository.create(grandparent)

    parent = make_role(name="parent", parent_role_id=grandparent.id)
    await mock_role_repository.create(parent)

    child = make_role(name="child", parent_role_id=parent.id)
    await mock_role_repository.create(child)

    ancestors = await permission_resolver.get_role_ancestors(str(child.id))
    assert ancestors == [str(child.id), str(parent.id), str(grandparent.id)]


async def test_get_role_ancestors_stops_at_nonexistent(
    permission_resolver,
    mock_role_repository,
) -> None:
    nonexistent_parent = PydanticObjectId()
    child = make_role(name="child", parent_role_id=nonexistent_parent)
    await mock_role_repository.create(child)

    ancestors = await permission_resolver.get_role_ancestors(str(child.id))
    assert ancestors == [str(child.id)]


async def test_get_role_ancestors_detects_circular(
    permission_resolver,
    mock_role_repository,
) -> None:
    role_a_id = PydanticObjectId()
    role_b_id = PydanticObjectId()

    role_a = make_role(name="role_a", parent_role_id=role_b_id, role_id=role_a_id)
    role_b = make_role(name="role_b", parent_role_id=role_a_id, role_id=role_b_id)

    await mock_role_repository.create(role_a)
    await mock_role_repository.create(role_b)

    with pytest.raises(ValueError, match="Circular role hierarchy"):
        await permission_resolver.get_role_ancestors(str(role_a_id))


async def test_role_hierarchy_inherits_permissions(
    permission_resolver,
    mock_user_role_repository,
    mock_role_repository,
    mock_permission_repository,
) -> None:
    user_id = PydanticObjectId()

    perm_parent = make_permission(resource="docs", action="read")
    perm_child = make_permission(resource="docs", action="write")
    await mock_permission_repository.create(perm_parent)
    await mock_permission_repository.create(perm_child)

    parent_role = make_role(name="reader", permission_ids=[perm_parent.id])
    await mock_role_repository.create(parent_role)

    child_role = make_role(
        name="writer", permission_ids=[perm_child.id], parent_role_id=parent_role.id
    )
    await mock_role_repository.create(child_role)

    user_role = make_user_role(user_id=user_id, role_id=child_role.id)
    await mock_user_role_repository.create(user_role)

    permissions = await permission_resolver.get_effective_permissions(str(user_id))
    assert permissions == {"docs:read", "docs:write"}


async def test_scope_filter_removes_non_matching(
    permission_resolver,
    mock_user_role_repository,
    mock_role_repository,
    mock_permission_repository,
) -> None:
    user_id = PydanticObjectId()

    perm = make_permission(resource="docs", action="read")
    await mock_permission_repository.create(perm)

    role = make_role(name="reader", permission_ids=[perm.id])
    await mock_role_repository.create(role)

    ur = make_user_role(
        user_id=user_id, role_id=role.id, scope=Scope(tenant_id="t1", region="us-west")
    )
    await mock_user_role_repository.create(ur)

    permissions = await permission_resolver.get_effective_permissions(
        str(user_id), scope={"tenant_id": "t1", "region": "us-east"}
    )
    assert permissions == set()


async def test_deduplicates_permissions(
    permission_resolver,
    mock_user_role_repository,
    mock_user_group_repository,
    mock_group_role_repository,
    mock_role_repository,
    mock_permission_repository,
) -> None:
    user_id = PydanticObjectId()
    group_id = PydanticObjectId()

    perm = make_permission(resource="docs", action="read")
    await mock_permission_repository.create(perm)

    role = make_role(name="reader", permission_ids=[perm.id])
    await mock_role_repository.create(role)

    user_role = make_user_role(user_id=user_id, role_id=role.id)
    await mock_user_role_repository.create(user_role)

    user_group = make_user_group(user_id=user_id, group_id=group_id)
    await mock_user_group_repository.create(user_group)

    group_role = make_group_role(group_id=group_id, role_id=role.id)
    await mock_group_role_repository.create(group_role)

    permissions = await permission_resolver.get_effective_permissions(str(user_id))
    assert permissions == {"docs:read"}


async def test_get_role_ancestors_nonexistent_initial_role(permission_resolver) -> None:
    """When initial role doesn't exist, still return it for backward compatibility."""
    nonexistent_role_id = str(PydanticObjectId())
    ancestors = await permission_resolver.get_role_ancestors(nonexistent_role_id)
    assert ancestors == [nonexistent_role_id]


async def test_tenant_scoped_assignments_excluded_without_request_scope(
    permission_resolver,
    mock_user_role_repository,
    mock_user_group_repository,
    mock_group_role_repository,
    mock_role_repository,
    mock_permission_repository,
) -> None:
    user_id = PydanticObjectId()
    group_id = PydanticObjectId()

    scoped = make_permission(resource="docs", action="read")
    scoped_via_group = make_permission(resource="files", action="read")
    unscoped = make_permission(resource="wiki", action="read")
    for perm in (scoped, scoped_via_group, unscoped):
        await mock_permission_repository.create(perm)

    scoped_role = make_role(name="scoped", permission_ids=[scoped.id])
    group_role = make_role(name="group-scoped", permission_ids=[scoped_via_group.id])
    open_role = make_role(name="open", permission_ids=[unscoped.id])
    for role in (scoped_role, group_role, open_role):
        await mock_role_repository.create(role)

    await mock_user_role_repository.create(
        make_user_role(
            user_id=user_id, role_id=scoped_role.id, scope=Scope(tenant_id="t")
        )
    )
    await mock_user_role_repository.create(
        make_user_role(user_id=user_id, role_id=open_role.id)
    )
    await mock_user_group_repository.create(
        make_user_group(user_id=user_id, group_id=group_id)
    )
    await mock_group_role_repository.create(
        make_group_role(
            group_id=group_id, role_id=group_role.id, scope=Scope(tenant_id="t")
        )
    )

    for request_scope in (None, {}):
        permissions = await permission_resolver.get_effective_permissions(
            str(user_id), scope=request_scope
        )
        assert permissions == {"wiki:read"}
