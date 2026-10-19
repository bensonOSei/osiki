"""Shared test fixtures for unit and integration tests."""

import asyncio
from collections.abc import AsyncGenerator

import pytest
from beanie import init_beanie
from mongomock_motor import AsyncMongoMockClient

from osiki.models.access_log import AccessLog
from osiki.models.audit_log import AuditLog
from osiki.models.condition import Condition
from osiki.models.constraint import Constraint
from osiki.models.environment_state import EnvironmentState
from osiki.models.group import Group
from osiki.models.group_role import GroupRole
from osiki.models.permission import Permission
from osiki.models.role import Role
from osiki.models.tenant import Tenant
from osiki.models.tenant_member import TenantMember
from osiki.models.user import User
from osiki.models.user_group import UserGroup
from osiki.models.user_role import UserRole
from osiki.repositories.constraints.base_constraint_repository import (
    BaseConstraintRepository,
)
from osiki.repositories.group_roles.base_group_role_repository import (
    BaseGroupRoleRepository,
)
from osiki.repositories.permissions.base_permission_repository import (
    BasePermissionRepository,
)
from osiki.repositories.roles.base_role_repository import BaseRoleRepository
from osiki.repositories.tenant_members.base_tenant_member_repository import (
    BaseTenantMemberRepository,
)
from osiki.repositories.user_groups.base_user_group_repository import (
    BaseUserGroupRepository,
)
from osiki.repositories.user_roles.base_user_role_repository import (
    BaseUserRoleRepository,
)
from osiki.repositories.users.base_user_repository import BaseUserRepository
from osiki.services.authorization.authorization_service import AuthorizationService
from osiki.services.bundle_builder.bundle_builder import BundleBuilder
from osiki.services.constraint_validator.constraint_validator import ConstraintValidator
from osiki.services.snapshot_builder.snapshot_builder import (
    SnapshotBuilder,
    SnapshotCache,
)
from tests.mocks import (
    MockConditionRepository,
    MockConstraintRepository,
    MockEnvironmentStateRepository,
    MockGroupRepository,
    MockGroupRoleRepository,
    MockPermissionRepository,
    MockRoleRepository,
    MockTenantMemberRepository,
    MockTenantRepository,
    MockUserGroupRepository,
    MockUserRepository,
    MockUserRoleRepository,
    make_assignment_entry,
    make_condition,
    make_constraint,
    make_decision_request,
    make_environment_state,
    make_group,
    make_group_role,
    make_permission,
    make_role,
    make_role_entry,
    make_snapshot,
    make_tenant,
    make_tenant_member,
    make_user,
    make_user_bundle,
    make_user_group,
    make_user_role,
)

# Re-export for backward compatibility
__all__ = [
    "make_assignment_entry",
    "make_decision_request",
    "make_environment_state",
    "make_condition",
    "make_constraint",
    "make_group",
    "make_group_role",
    "make_permission",
    "make_role",
    "make_role_entry",
    "make_snapshot",
    "make_tenant",
    "make_tenant_member",
    "make_user",
    "make_user_group",
    "make_user_role",
    "make_user_bundle",
    "MockConditionRepository",
    "MockConstraintRepository",
    "MockEnvironmentStateRepository",
    "MockGroupRepository",
    "MockGroupRoleRepository",
    "MockPermissionRepository",
    "MockRoleRepository",
    "MockTenantMemberRepository",
    "MockTenantRepository",
    "MockUserGroupRepository",
    "MockUserRepository",
    "MockUserRoleRepository",
]


# --- Event Loop ---


@pytest.fixture(scope="session")
def event_loop() -> asyncio.AbstractEventLoop:  # type: ignore
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# --- MongoDB Fixtures (for integration tests) ---


@pytest.fixture(scope="session")
async def mongo_client() -> AsyncGenerator[AsyncMongoMockClient]:
    client = AsyncMongoMockClient()
    yield client
    client.close()


@pytest.fixture(scope="session")
async def init_db(mongo_client: AsyncMongoMockClient) -> None:
    await init_beanie(
        database=mongo_client.osiki_test,
        document_models=[
            User,
            Group,
            Role,
            Permission,
            UserRole,
            UserGroup,
            GroupRole,
            Constraint,
            Condition,
            AuditLog,
            AccessLog,
            Tenant,
            TenantMember,
            EnvironmentState,
        ],
    )
    # mongomock's create_indexes() drops partialFilterExpression, which would turn
    # the (environment_id, email) index into a plain unique index that rejects
    # several users without an email. Recreate it the way MongoDB builds it.
    # The assignment unique indexes are partial on is_active the same way.
    partial_indexes = [
        (User, ["environment_id", "email"], {"email": {"$type": "string"}}),
        (
            UserRole,
            ["environment_id", "user_id", "role_id", "scope.tenant_id"],
            {"is_active": True},
        ),
        (
            GroupRole,
            ["environment_id", "group_id", "role_id", "scope.tenant_id"],
            {"is_active": True},
        ),
        (UserGroup, ["environment_id", "user_id", "group_id"], {"is_active": True}),
    ]
    for model, fields, partial in partial_indexes:
        collection = mongo_client.osiki_test[model.get_settings().name]
        await collection.drop_index("_".join(f"{field}_1" for field in fields))
        await collection.create_index(
            [(field, 1) for field in fields],
            unique=True,
            partialFilterExpression=partial,
        )


@pytest.fixture(autouse=True)
async def clean_db(
    init_db: None, mongo_client: AsyncMongoMockClient
) -> AsyncGenerator[None]:
    _ = init_db  # Ensure DB is initialized before cleanup
    yield
    db = mongo_client.osiki_test
    for collection_name in await db.list_collection_names():
        await db[collection_name].delete_many({})


# --- Mock Repository Fixtures (for unit tests) ---


@pytest.fixture
def mock_user_role_repository(
    mock_environment_state_repository,
) -> BaseUserRoleRepository:
    return MockUserRoleRepository("default", mock_environment_state_repository)


@pytest.fixture
def mock_user_group_repository(
    mock_environment_state_repository,
) -> BaseUserGroupRepository:
    return MockUserGroupRepository("default", mock_environment_state_repository)


@pytest.fixture
def mock_group_repository(mock_environment_state_repository) -> MockGroupRepository:
    return MockGroupRepository("default", mock_environment_state_repository)


@pytest.fixture
def mock_group_role_repository(
    mock_environment_state_repository,
) -> BaseGroupRoleRepository:
    return MockGroupRoleRepository("default", mock_environment_state_repository)


@pytest.fixture
def mock_environment_state_repository() -> MockEnvironmentStateRepository:
    return MockEnvironmentStateRepository("default")


@pytest.fixture
def mock_role_repository(mock_environment_state_repository) -> BaseRoleRepository:
    return MockRoleRepository("default", mock_environment_state_repository)


@pytest.fixture
def mock_permission_repository(
    mock_environment_state_repository,
) -> BasePermissionRepository:
    return MockPermissionRepository("default", mock_environment_state_repository)


@pytest.fixture
def mock_condition_repository(
    mock_environment_state_repository,
) -> MockConditionRepository:
    return MockConditionRepository("default", mock_environment_state_repository)


@pytest.fixture
def mock_constraint_repository(
    mock_environment_state_repository,
) -> BaseConstraintRepository:
    return MockConstraintRepository("default", mock_environment_state_repository)


@pytest.fixture
def mock_user_repository(mock_environment_state_repository) -> BaseUserRepository:
    return MockUserRepository("default", mock_environment_state_repository)


@pytest.fixture
def mock_tenant_member_repository(
    mock_environment_state_repository,
) -> BaseTenantMemberRepository:
    return MockTenantMemberRepository("default", mock_environment_state_repository)


@pytest.fixture
def mock_tenant_repository(mock_environment_state_repository) -> MockTenantRepository:
    return MockTenantRepository("default", mock_environment_state_repository)


# --- Service Fixtures (for unit tests) ---


@pytest.fixture
def snapshot_builder(
    mock_environment_state_repository,
    mock_role_repository,
    mock_permission_repository,
    mock_condition_repository,
    mock_constraint_repository,
) -> SnapshotBuilder:
    return SnapshotBuilder(
        "default",
        mock_environment_state_repository,
        mock_role_repository,
        mock_permission_repository,
        mock_condition_repository,
        mock_constraint_repository,
        cache=SnapshotCache(),
    )


@pytest.fixture
def bundle_builder(
    mock_user_repository,
    mock_user_role_repository,
    mock_user_group_repository,
    mock_group_repository,
    mock_group_role_repository,
    mock_tenant_member_repository,
    mock_tenant_repository,
) -> BundleBuilder:
    return BundleBuilder(
        mock_user_repository,
        mock_user_role_repository,
        mock_user_group_repository,
        mock_group_repository,
        mock_group_role_repository,
        mock_tenant_member_repository,
        mock_tenant_repository,
    )


@pytest.fixture
def constraint_validator(
    mock_constraint_repository,
    mock_user_role_repository,
) -> ConstraintValidator:
    return ConstraintValidator(
        constraint_repository=mock_constraint_repository,
        user_role_repository=mock_user_role_repository,
    )


@pytest.fixture
def authorization_service(snapshot_builder, bundle_builder) -> AuthorizationService:
    return AuthorizationService(
        snapshot_builder=snapshot_builder, bundle_builder=bundle_builder
    )
