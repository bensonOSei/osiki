import pytest
from beanie import PydanticObjectId

from osiki.models.base import Scope
from osiki.models.role import Grant
from osiki.models.user import User
from tests.conftest import (
    make_condition,
    make_permission,
    make_role,
    make_user,
    make_user_role,
)


@pytest.fixture
async def user(mock_user_repository) -> User:
    return await mock_user_repository.create(make_user(external_id="ext-user-1"))


async def test_authorize_grants_exact_permission(
    authorization_service,
    user,
    mock_user_role_repository,
    mock_role_repository,
    mock_permission_repository,
) -> None:
    user_id = user.id

    perm = make_permission(resource="docs", action="read")
    await mock_permission_repository.create(perm)

    role = make_role(name="reader", permission_ids=[perm.id])
    await mock_role_repository.create(role)

    user_role = make_user_role(user_id=user_id, role_id=role.id)
    await mock_user_role_repository.create(user_role)

    result = await authorization_service.authorize(
        user_id=user.external_id,
        resource="docs",
        action="read",
    )
    assert result.allowed is True
    assert result.matched_permission == "docs:read"


async def test_authorize_grants_resource_wildcard(
    authorization_service,
    user,
    mock_user_role_repository,
    mock_role_repository,
    mock_permission_repository,
) -> None:
    user_id = user.id

    perm = make_permission(resource="docs", action="*")
    await mock_permission_repository.create(perm)

    role = make_role(name="docs-admin", permission_ids=[perm.id])
    await mock_role_repository.create(role)

    user_role = make_user_role(user_id=user_id, role_id=role.id)
    await mock_user_role_repository.create(user_role)

    result = await authorization_service.authorize(
        user_id=user.external_id,
        resource="docs",
        action="delete",
    )
    assert result.allowed is True
    assert result.matched_permission == "docs:*"


async def test_authorize_grants_action_wildcard(
    authorization_service,
    user,
    mock_user_role_repository,
    mock_role_repository,
    mock_permission_repository,
) -> None:
    user_id = user.id

    perm = make_permission(resource="*", action="read")
    await mock_permission_repository.create(perm)

    role = make_role(name="reader-all", permission_ids=[perm.id])
    await mock_role_repository.create(role)

    user_role = make_user_role(user_id=user_id, role_id=role.id)
    await mock_user_role_repository.create(user_role)

    result = await authorization_service.authorize(
        user_id=user.external_id,
        resource="files",
        action="read",
    )
    assert result.allowed is True
    assert result.matched_permission == "*:read"


async def test_authorize_grants_full_wildcard(
    authorization_service,
    user,
    mock_user_role_repository,
    mock_role_repository,
    mock_permission_repository,
) -> None:
    user_id = user.id

    perm = make_permission(resource="*", action="*")
    await mock_permission_repository.create(perm)

    role = make_role(name="superadmin", permission_ids=[perm.id])
    await mock_role_repository.create(role)

    user_role = make_user_role(user_id=user_id, role_id=role.id)
    await mock_user_role_repository.create(user_role)

    result = await authorization_service.authorize(
        user_id=user.external_id,
        resource="anything",
        action="anything",
    )
    assert result.allowed is True
    assert result.matched_permission == "*:*"


async def test_authorize_denies_no_permission(authorization_service, user) -> None:
    result = await authorization_service.authorize(
        user_id=user.external_id,
        resource="docs",
        action="read",
    )
    assert result.allowed is False
    assert result.denial_reason == "no_permission"


async def test_authorize_checks_wildcards_in_order(
    authorization_service,
    user,
    mock_user_role_repository,
    mock_role_repository,
    mock_permission_repository,
) -> None:
    user_id = user.id

    perm_exact = make_permission(resource="docs", action="read")
    perm_resource = make_permission(resource="docs", action="*")
    await mock_permission_repository.create(perm_exact)
    await mock_permission_repository.create(perm_resource)

    role = make_role(name="admin", permission_ids=[perm_exact.id, perm_resource.id])
    await mock_role_repository.create(role)

    user_role = make_user_role(user_id=user_id, role_id=role.id)
    await mock_user_role_repository.create(user_role)

    result = await authorization_service.authorize(
        user_id=user.external_id,
        resource="docs",
        action="read",
    )
    assert result.allowed is True
    assert result.matched_permission == "docs:read"


async def test_tenant_scoped_role_does_not_apply_in_another_tenant(
    authorization_service,
    user,
    mock_user_role_repository,
    mock_role_repository,
    mock_permission_repository,
    mock_tenant_member_repository,
    mock_tenant_repository,
) -> None:
    user_id = user.id

    perm = make_permission(resource="docs", action="read")
    await mock_permission_repository.create(perm)

    role = make_role(name="reader", permission_ids=[perm.id])
    await mock_role_repository.create(role)

    user_role = make_user_role(
        user_id=user_id, role_id=role.id, scope=Scope(tenant_id="t1")
    )
    await mock_user_role_repository.create(user_role)
    # Member of t2, so the denial comes from the t1/t2 scope mismatch itself.
    await mock_tenant_repository.upsert("t2", "T2", {})
    await mock_tenant_member_repository.add("t2", user.external_id)

    result = await authorization_service.authorize(
        user_id=user.external_id,
        resource="docs",
        action="read",
        scope={"tenant_id": "t2"},
    )
    assert result.allowed is False
    assert result.denial_reason == "no_permission"


async def test_authorize_result_contains_matched_permission(
    authorization_service,
    user,
    mock_user_role_repository,
    mock_role_repository,
    mock_permission_repository,
) -> None:
    user_id = user.id

    perm = make_permission(resource="files", action="write")
    await mock_permission_repository.create(perm)

    role = make_role(name="writer", permission_ids=[perm.id])
    await mock_role_repository.create(role)

    user_role = make_user_role(user_id=user_id, role_id=role.id)
    await mock_user_role_repository.create(user_role)

    result = await authorization_service.authorize(
        user_id=user.external_id,
        resource="files",
        action="write",
    )
    assert result.allowed is True
    assert result.matched_permission == "files:write"


async def test_authorize_result_contains_denial_reason(
    authorization_service, user
) -> None:
    result = await authorization_service.authorize(
        user_id=user.external_id,
        resource="secret",
        action="access",
    )
    assert result.allowed is False
    assert result.denial_reason == "no_permission"


async def test_authorize_with_none_scope(
    authorization_service,
    user,
    mock_user_role_repository,
    mock_role_repository,
    mock_permission_repository,
) -> None:
    user_id = user.id

    perm = make_permission(resource="docs", action="read")
    await mock_permission_repository.create(perm)

    role = make_role(name="reader", permission_ids=[perm.id])
    await mock_role_repository.create(role)

    user_role = make_user_role(user_id=user_id, role_id=role.id)
    await mock_user_role_repository.create(user_role)

    result = await authorization_service.authorize(
        user_id=user.external_id,
        resource="docs",
        action="read",
        scope=None,
    )
    assert result.allowed is True


async def test_authorize_with_empty_permissions(
    authorization_service,
    user,
    mock_user_role_repository,
    mock_role_repository,
) -> None:
    user_id = user.id

    role = make_role(name="empty-role", permission_ids=[])
    await mock_role_repository.create(role)

    user_role = make_user_role(user_id=user_id, role_id=role.id)
    await mock_user_role_repository.create(user_role)

    result = await authorization_service.authorize(
        user_id=user.external_id,
        resource="docs",
        action="read",
    )
    assert result.allowed is False
    assert result.denial_reason == "no_permission"


async def test_authorize_multiple_permissions_finds_match(
    authorization_service,
    user,
    mock_user_role_repository,
    mock_role_repository,
    mock_permission_repository,
) -> None:
    user_id = user.id

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
        user_id=user.external_id,
        resource="users",
        action="manage",
    )
    assert result.allowed is True
    assert result.matched_permission == "users:manage"


# --- Strict tenancy ---


async def _grant_docs_read(
    user: User,
    mock_user_role_repository,
    mock_role_repository,
    mock_permission_repository,
    scope: Scope | None = None,
) -> None:
    perm = make_permission(resource="docs", action="read")
    await mock_permission_repository.create(perm)
    role = make_role(name="reader", permission_ids=[perm.id])
    await mock_role_repository.create(role)
    await mock_user_role_repository.create(
        make_user_role(user_id=user.id, role_id=role.id, scope=scope or Scope())
    )


async def test_tenant_scoped_role_does_not_apply_without_tenant(
    authorization_service,
    user,
    mock_user_role_repository,
    mock_role_repository,
    mock_permission_repository,
    mock_tenant_member_repository,
    mock_tenant_repository,
) -> None:
    await _grant_docs_read(
        user,
        mock_user_role_repository,
        mock_role_repository,
        mock_permission_repository,
        scope=Scope(tenant_id="t"),
    )
    await mock_tenant_repository.upsert("t", "T", {})
    await mock_tenant_member_repository.add("t", user.external_id)

    result = await authorization_service.authorize(
        user_id=user.external_id, resource="docs", action="read", scope=None
    )
    assert result.allowed is False
    assert result.denial_reason == "no_permission"

    empty = await authorization_service.authorize(
        user_id=user.external_id, resource="docs", action="read", scope={}
    )
    assert empty.allowed is False


async def test_tenant_scoped_role_applies_in_its_tenant(
    authorization_service,
    user,
    mock_user_role_repository,
    mock_role_repository,
    mock_permission_repository,
    mock_tenant_member_repository,
    mock_tenant_repository,
) -> None:
    await _grant_docs_read(
        user,
        mock_user_role_repository,
        mock_role_repository,
        mock_permission_repository,
        scope=Scope(tenant_id="t"),
    )
    await mock_tenant_repository.upsert("t", "T", {})
    await mock_tenant_member_repository.add("t", user.external_id)

    result = await authorization_service.authorize(
        user_id=user.external_id,
        resource="docs",
        action="read",
        scope={"tenant_id": "t"},
    )
    assert result.allowed is True


async def test_project_wide_role_requires_membership(
    authorization_service,
    user,
    mock_user_role_repository,
    mock_role_repository,
    mock_permission_repository,
    mock_tenant_member_repository,
    mock_tenant_repository,
) -> None:
    await _grant_docs_read(
        user,
        mock_user_role_repository,
        mock_role_repository,
        mock_permission_repository,
    )

    denied = await authorization_service.authorize(
        user_id=user.external_id,
        resource="docs",
        action="read",
        scope={"tenant_id": "t"},
    )
    assert denied.allowed is False
    assert denied.denial_reason == "not_tenant_member"

    await mock_tenant_repository.upsert("t", "T", {})
    await mock_tenant_member_repository.add("t", user.external_id)

    allowed = await authorization_service.authorize(
        user_id=user.external_id,
        resource="docs",
        action="read",
        scope={"tenant_id": "t"},
    )
    assert allowed.allowed is True
    assert allowed.matched_permission == "docs:read"


async def test_membership_is_checked_against_external_id(
    authorization_service,
    user,
    mock_user_role_repository,
    mock_role_repository,
    mock_permission_repository,
    mock_tenant_member_repository,
) -> None:
    await _grant_docs_read(
        user,
        mock_user_role_repository,
        mock_role_repository,
        mock_permission_repository,
    )
    # Membership recorded under the internal id must not count.
    await mock_tenant_member_repository.add("t", str(user.id))

    result = await authorization_service.authorize(
        user_id=user.external_id,
        resource="docs",
        action="read",
        scope={"tenant_id": "t"},
    )
    assert result.allowed is False
    assert result.denial_reason == "not_tenant_member"


async def test_unknown_user_denied(authorization_service, user) -> None:
    result = await authorization_service.authorize(
        user_id="nobody", resource="docs", action="read"
    )
    assert result.allowed is False
    assert result.denial_reason == "unknown_user"


async def test_internal_id_is_not_accepted_as_user_id(
    authorization_service,
    user,
    mock_user_role_repository,
    mock_role_repository,
    mock_permission_repository,
) -> None:
    await _grant_docs_read(
        user,
        mock_user_role_repository,
        mock_role_repository,
        mock_permission_repository,
    )

    result = await authorization_service.authorize(
        user_id=str(user.id), resource="docs", action="read"
    )
    assert result.allowed is False
    assert result.denial_reason == "unknown_user"


async def test_inactive_user_denied(
    snapshot_builder,
    mock_user_role_repository,
    mock_user_group_repository,
    mock_group_repository,
    mock_group_role_repository,
    mock_tenant_member_repository,
    mock_tenant_repository,
) -> None:
    from unittest.mock import AsyncMock

    from osiki.services.authorization.authorization_service import (
        AuthorizationService,
    )
    from osiki.services.bundle_builder.bundle_builder import BundleBuilder

    inactive = make_user(external_id="gone")
    inactive.is_active = False
    user_repository = AsyncMock()
    user_repository.get_by_external_id.return_value = inactive
    service = AuthorizationService(
        snapshot_builder=snapshot_builder,
        bundle_builder=BundleBuilder(
            user_repository,
            mock_user_role_repository,
            mock_user_group_repository,
            mock_group_repository,
            mock_group_role_repository,
            mock_tenant_member_repository,
            mock_tenant_repository,
        ),
    )

    result = await service.authorize(user_id="gone", resource="docs", action="read")
    assert result.allowed is False
    assert result.denial_reason == "unknown_user"
    assert await service.effective_grants("gone") is None


async def test_grant_with_missing_condition_is_never_unconditional(
    authorization_service,
    user,
    mock_user_role_repository,
    mock_role_repository,
    mock_permission_repository,
) -> None:
    perm = make_permission(resource="invoices", action="read")
    await mock_permission_repository.create(perm)
    role = make_role(
        name="own-team",
        grants=[Grant(permission_id=perm.id, condition_id=PydanticObjectId())],
    )
    await mock_role_repository.create(role)
    await mock_user_role_repository.create(
        make_user_role(user_id=user.id, role_id=role.id)
    )

    without_record = await authorization_service.authorize(
        user_id=user.external_id, resource="invoices", action="read"
    )
    with_record = await authorization_service.authorize(
        user_id=user.external_id,
        resource="invoices",
        action="read",
        record={"team_id": "t1"},
    )

    assert without_record.allowed is False
    assert without_record.denial_reason == "record_required"
    assert with_record.allowed is False
    assert with_record.denial_reason == "condition_failed"


async def test_conditional_grant_allows_matching_record(
    authorization_service,
    mock_user_repository,
    mock_user_role_repository,
    mock_role_repository,
    mock_permission_repository,
    mock_condition_repository,
) -> None:
    member = make_user(external_id="ext-team")
    member.attributes = {"team_id": "t1"}
    await mock_user_repository.create(member)
    perm = await mock_permission_repository.create(
        make_permission(resource="invoices", action="read")
    )
    cond = await mock_condition_repository.create(
        make_condition(
            key="own_team",
            expression={
                "op": "eq",
                "left": {"ref": "record.team_id"},
                "right": {"ref": "user.team_id"},
            },
        )
    )
    role = await mock_role_repository.create(
        make_role(
            name="clerk", grants=[Grant(permission_id=perm.id, condition_id=cond.id)]
        )
    )
    await mock_user_role_repository.create(
        make_user_role(user_id=member.id, role_id=role.id)
    )

    same = await authorization_service.authorize(
        user_id="ext-team", resource="invoices", action="read", record={"team_id": "t1"}
    )
    other = await authorization_service.authorize(
        user_id="ext-team", resource="invoices", action="read", record={"team_id": "t2"}
    )

    assert same.allowed is True
    assert same.condition == "own_team"
    assert same.matched_via == "direct"
    assert other.allowed is False
    assert other.denial_reason == "condition_failed"
