"""Shared test fixtures for unit and integration tests."""

import asyncio
from collections.abc import AsyncGenerator

import pytest
from beanie import init_beanie
from mongomock_motor import AsyncMongoMockClient

from osiki.models.access_log import AccessLog
from osiki.models.audit_log import AuditLog
from osiki.models.constraint import Constraint
from osiki.models.group import Group
from osiki.models.group_role import GroupRole
from osiki.models.permission import Permission
from osiki.models.role import Role
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
from osiki.repositories.user_groups.base_user_group_repository import (
    BaseUserGroupRepository,
)
from osiki.repositories.user_roles.base_user_role_repository import (
    BaseUserRoleRepository,
)
from osiki.services.authorization.authorization_service import AuthorizationService
from osiki.services.constraint_validator.constraint_validator import ConstraintValidator
from osiki.services.permission_resolver.permission_resolver import PermissionResolver
from osiki.services.scope_matcher.scope_matcher import ScopeMatcher
from tests.mocks import (
    MockConstraintRepository,
    MockGroupRoleRepository,
    MockPermissionRepository,
    MockRoleRepository,
    MockUserGroupRepository,
    MockUserRoleRepository,
    make_constraint,
    make_group,
    make_group_role,
    make_permission,
    make_role,
    make_user,
    make_user_group,
    make_user_role,
)

# Re-export for backward compatibility
__all__ = [
    "make_constraint",
    "make_group",
    "make_group_role",
    "make_permission",
    "make_role",
    "make_user",
    "make_user_group",
    "make_user_role",
    "MockConstraintRepository",
    "MockGroupRoleRepository",
    "MockPermissionRepository",
    "MockRoleRepository",
    "MockUserGroupRepository",
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
            AuditLog,
            AccessLog,
        ],
    )
    # mongomock's create_indexes() drops partialFilterExpression, which would turn
    # the (environment_id, email) index into a plain unique index that rejects
    # several users without an email. Recreate it the way MongoDB builds it.
    users = mongo_client.osiki_test[User.get_settings().name]
    await users.drop_index("environment_id_1_email_1")
    await users.create_index(
        [("environment_id", 1), ("email", 1)],
        unique=True,
        partialFilterExpression={"email": {"$type": "string"}},
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
def mock_user_role_repository() -> BaseUserRoleRepository:
    return MockUserRoleRepository("default")


@pytest.fixture
def mock_user_group_repository() -> BaseUserGroupRepository:
    return MockUserGroupRepository("default")


@pytest.fixture
def mock_group_role_repository() -> BaseGroupRoleRepository:
    return MockGroupRoleRepository("default")


@pytest.fixture
def mock_role_repository() -> BaseRoleRepository:
    return MockRoleRepository("default")


@pytest.fixture
def mock_permission_repository() -> BasePermissionRepository:
    return MockPermissionRepository("default")


@pytest.fixture
def mock_constraint_repository() -> BaseConstraintRepository:
    return MockConstraintRepository("default")


# --- Service Fixtures (for unit tests) ---


@pytest.fixture
def scope_matcher() -> ScopeMatcher:
    return ScopeMatcher()


@pytest.fixture
def permission_resolver(
    mock_user_role_repository,
    mock_user_group_repository,
    mock_group_role_repository,
    mock_role_repository,
    mock_permission_repository,
    scope_matcher,
) -> PermissionResolver:
    return PermissionResolver(
        user_role_repository=mock_user_role_repository,
        user_group_repository=mock_user_group_repository,
        group_role_repository=mock_group_role_repository,
        role_repository=mock_role_repository,
        permission_repository=mock_permission_repository,
        scope_matcher=scope_matcher,
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
def authorization_service(permission_resolver) -> AuthorizationService:
    return AuthorizationService(permission_resolver=permission_resolver)
