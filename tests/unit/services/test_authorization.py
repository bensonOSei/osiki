from beanie import PydanticObjectId

from tests.conftest import make_permission, make_role, make_user_role


async def test_authorize_grants_exact_permission(
    authorization_service,
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

    result = await authorization_service.authorize(
        user_id=str(user_id),
        resource="docs",
        action="read",
    )
    assert result.allowed is True
    assert result.matched_permission == "docs:read"


async def test_authorize_grants_resource_wildcard(
    authorization_service,
    mock_user_role_repository,
    mock_role_repository,
    mock_permission_repository,
) -> None:
    user_id = PydanticObjectId()

    perm = make_permission(resource="docs", action="*")
    await mock_permission_repository.create(perm)

    role = make_role(name="docs-admin", permission_ids=[perm.id])
    await mock_role_repository.create(role)

    user_role = make_user_role(user_id=user_id, role_id=role.id)
    await mock_user_role_repository.create(user_role)

    result = await authorization_service.authorize(
        user_id=str(user_id),
        resource="docs",
        action="delete",
    )
    assert result.allowed is True
    assert result.matched_permission == "docs:*"


async def test_authorize_grants_action_wildcard(
    authorization_service,
    mock_user_role_repository,
    mock_role_repository,
    mock_permission_repository,
) -> None:
    user_id = PydanticObjectId()

    perm = make_permission(resource="*", action="read")
    await mock_permission_repository.create(perm)

    role = make_role(name="reader-all", permission_ids=[perm.id])
    await mock_role_repository.create(role)

    user_role = make_user_role(user_id=user_id, role_id=role.id)
    await mock_user_role_repository.create(user_role)

    result = await authorization_service.authorize(
        user_id=str(user_id),
        resource="files",
        action="read",
    )
    assert result.allowed is True
    assert result.matched_permission == "*:read"


async def test_authorize_grants_full_wildcard(
    authorization_service,
    mock_user_role_repository,
    mock_role_repository,
    mock_permission_repository,
) -> None:
    user_id = PydanticObjectId()

    perm = make_permission(resource="*", action="*")
    await mock_permission_repository.create(perm)

    role = make_role(name="superadmin", permission_ids=[perm.id])
    await mock_role_repository.create(role)

    user_role = make_user_role(user_id=user_id, role_id=role.id)
    await mock_user_role_repository.create(user_role)

    result = await authorization_service.authorize(
        user_id=str(user_id),
        resource="anything",
        action="anything",
    )
    assert result.allowed is True
    assert result.matched_permission == "*:*"


async def test_authorize_denies_no_permission(authorization_service) -> None:
    result = await authorization_service.authorize(
        user_id=str(PydanticObjectId()),
        resource="docs",
        action="read",
    )
    assert result.allowed is False
    assert result.denial_reason == "no_permission"


async def test_authorize_checks_wildcards_in_order(
    authorization_service,
    mock_user_role_repository,
    mock_role_repository,
    mock_permission_repository,
) -> None:
    user_id = PydanticObjectId()

    perm_exact = make_permission(resource="docs", action="read")
    perm_resource = make_permission(resource="docs", action="*")
    await mock_permission_repository.create(perm_exact)
    await mock_permission_repository.create(perm_resource)

    role = make_role(name="admin", permission_ids=[perm_exact.id, perm_resource.id])
    await mock_role_repository.create(role)

    user_role = make_user_role(user_id=user_id, role_id=role.id)
    await mock_user_role_repository.create(user_role)

    result = await authorization_service.authorize(
        user_id=str(user_id),
        resource="docs",
        action="read",
    )
    assert result.allowed is True
    assert result.matched_permission == "docs:read"


async def test_authorize_passes_scope_to_resolver(
    authorization_service,
    mock_user_role_repository,
    mock_role_repository,
    mock_permission_repository,
) -> None:
    from osiki.models.base import Scope

    user_id = PydanticObjectId()

    perm = make_permission(resource="docs", action="read")
    await mock_permission_repository.create(perm)

    role = make_role(name="reader", permission_ids=[perm.id])
    await mock_role_repository.create(role)

    user_role = make_user_role(
        user_id=user_id, role_id=role.id, scope=Scope(tenant_id="t1")
    )
    await mock_user_role_repository.create(user_role)

    result = await authorization_service.authorize(
        user_id=str(user_id),
        resource="docs",
        action="read",
        scope={"tenant_id": "t2"},
    )
    assert result.allowed is False


async def test_authorize_result_contains_matched_permission(
    authorization_service,
    mock_user_role_repository,
    mock_role_repository,
    mock_permission_repository,
) -> None:
    user_id = PydanticObjectId()

    perm = make_permission(resource="files", action="write")
    await mock_permission_repository.create(perm)

    role = make_role(name="writer", permission_ids=[perm.id])
    await mock_role_repository.create(role)

    user_role = make_user_role(user_id=user_id, role_id=role.id)
    await mock_user_role_repository.create(user_role)

    result = await authorization_service.authorize(
        user_id=str(user_id),
        resource="files",
        action="write",
    )
    assert result.allowed is True
    assert result.matched_permission == "files:write"


async def test_authorize_result_contains_denial_reason(authorization_service) -> None:
    result = await authorization_service.authorize(
        user_id=str(PydanticObjectId()),
        resource="secret",
        action="access",
    )
    assert result.allowed is False
    assert result.denial_reason == "no_permission"


async def test_authorize_with_none_scope(
    authorization_service,
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

    result = await authorization_service.authorize(
        user_id=str(user_id),
        resource="docs",
        action="read",
        scope=None,
    )
    assert result.allowed is True


async def test_authorize_with_empty_permissions(
    authorization_service,
    mock_user_role_repository,
    mock_role_repository,
) -> None:
    user_id = PydanticObjectId()

    role = make_role(name="empty-role", permission_ids=[])
    await mock_role_repository.create(role)

    user_role = make_user_role(user_id=user_id, role_id=role.id)
    await mock_user_role_repository.create(user_role)

    result = await authorization_service.authorize(
        user_id=str(user_id),
        resource="docs",
        action="read",
    )
    assert result.allowed is False
    assert result.denial_reason == "no_permission"


async def test_authorize_multiple_permissions_finds_match(
    authorization_service,
    mock_user_role_repository,
    mock_role_repository,
    mock_permission_repository,
) -> None:
    user_id = PydanticObjectId()

    perm1 = make_permission(resource="docs", action="read")
    perm2 = make_permission(resource="files", action="write")
    perm3 = make_permission(resource="users", action="manage")
    await mock_permission_repository.create(perm1)
    await mock_permission_repository.create(perm2)
    await mock_permission_repository.create(perm3)

    role = make_role(name="multi", permission_ids=[perm1.id, perm2.id, perm3.id])
    await mock_role_repository.create(role)

    user_role = make_user_role(user_id=user_id, role_id=role.id)
    await mock_user_role_repository.create(user_role)

    result = await authorization_service.authorize(
        user_id=str(user_id),
        resource="users",
        action="manage",
    )
    assert result.allowed is True
    assert result.matched_permission == "users:manage"
