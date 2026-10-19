"""E2E test fixtures with FastAPI TestClient and dependency overrides."""

from collections.abc import Callable, Generator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from osiki.api.dependencies import (
    get_access_log_repository,
    get_condition_repository,
    get_constraint_repository,
    get_environment_state_repository,
    get_group_repository,
    get_group_role_repository,
    get_permission_repository,
    get_role_repository,
    get_snapshot_cache,
    get_tenant_member_repository,
    get_tenant_repository,
    get_user_group_repository,
    get_user_repository,
    get_user_role_repository,
)
from osiki.api.environment import EnvironmentId
from osiki.api.exceptions import (
    AuthorizationError,
    ValidationError,
    register_exception_handlers,
)
from osiki.api.middleware import RequestIDMiddleware
from osiki.api.routes import (
    access_logs_router,
    authorization_router,
    conditions_router,
    constraints_router,
    groups_router,
    health_router,
    permissions_router,
    roles_router,
    snapshot_router,
    tenants_router,
    users_router,
)
from osiki.configs.settings import get_settings
from osiki.services.snapshot_builder.snapshot_builder import SnapshotCache
from tests.mocks.repositories import (
    MockAccessLogRepository,
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
)

settings = get_settings()

_user_repos: dict[str, MockUserRepository] = {}
_group_repos: dict[str, MockGroupRepository] = {}
_role_repos: dict[str, MockRoleRepository] = {}
_permission_repos: dict[str, MockPermissionRepository] = {}
_user_role_repos: dict[str, MockUserRoleRepository] = {}
_user_group_repos: dict[str, MockUserGroupRepository] = {}
_group_role_repos: dict[str, MockGroupRoleRepository] = {}
_constraint_repos: dict[str, MockConstraintRepository] = {}
_condition_repos: dict[str, MockConditionRepository] = {}
_access_log_repos: dict[str, MockAccessLogRepository] = {}
_tenant_repos: dict[str, MockTenantRepository] = {}
_tenant_member_repos: dict[str, MockTenantMemberRepository] = {}
_state_repos: dict[str, MockEnvironmentStateRepository] = {}
# Replaced per test: the mock state repos restart at version 0, so a cache
# kept across tests would serve the previous test's snapshot.
_snapshot_cache = SnapshotCache()


def _repo_provider[R](
    store: dict[str, R], factory: Callable[[str], R]
) -> Callable[[EnvironmentId], R]:
    """Build a dependency override returning one mock repo per environment."""

    def provide(environment_id: EnvironmentId) -> R:
        if environment_id not in store:
            store[environment_id] = factory(environment_id)
        return store[environment_id]

    return provide


def _state_for(environment_id: str) -> MockEnvironmentStateRepository:
    if environment_id not in _state_repos:
        _state_repos[environment_id] = MockEnvironmentStateRepository(environment_id)
    return _state_repos[environment_id]


def _provide_state(environment_id: EnvironmentId) -> MockEnvironmentStateRepository:
    return _state_for(environment_id)


def _config_repo_provider[R](
    store: dict[str, R], factory: Callable[[str, MockEnvironmentStateRepository], R]
) -> Callable[[EnvironmentId], R]:
    """Like ``_repo_provider``, sharing the environment's one state repo."""
    return _repo_provider(store, lambda env: factory(env, _state_for(env)))


def _provide_snapshot_cache() -> SnapshotCache:
    return _snapshot_cache


def _reset_all_repos() -> None:
    global _snapshot_cache
    _snapshot_cache = SnapshotCache()
    for store in (
        _user_repos,
        _group_repos,
        _role_repos,
        _permission_repos,
        _user_role_repos,
        _user_group_repos,
        _group_role_repos,
        _constraint_repos,
        _condition_repos,
        _access_log_repos,
        _tenant_repos,
        _tenant_member_repos,
        _state_repos,
    ):
        store.clear()


def _create_test_app() -> FastAPI:
    """Create a FastAPI app identical to main but without the database lifespan."""
    test_app = FastAPI(title=settings.app_name)

    test_app.add_middleware(RequestIDMiddleware)

    register_exception_handlers(test_app)

    test_app.include_router(health_router)
    test_app.include_router(users_router, prefix=settings.api_prefix)
    test_app.include_router(groups_router, prefix=settings.api_prefix)
    test_app.include_router(roles_router, prefix=settings.api_prefix)
    test_app.include_router(permissions_router, prefix=settings.api_prefix)
    test_app.include_router(conditions_router, prefix=settings.api_prefix)
    test_app.include_router(constraints_router, prefix=settings.api_prefix)
    test_app.include_router(tenants_router, prefix=settings.api_prefix)
    test_app.include_router(authorization_router, prefix=settings.api_prefix)
    test_app.include_router(snapshot_router, prefix=settings.api_prefix)
    test_app.include_router(access_logs_router, prefix=settings.api_prefix)

    @test_app.get("/_test/authorization-error")
    async def _trigger_authorization_error() -> None:
        raise AuthorizationError("forbidden", details={"reason": "test"})

    @test_app.get("/_test/validation-error")
    async def _trigger_validation_error() -> None:
        raise ValidationError("invalid input", details={"field": "test"})

    @test_app.get("/_test/internal-error")
    async def _trigger_internal_error() -> None:
        raise RuntimeError("unexpected failure")

    test_app.dependency_overrides[get_user_repository] = _repo_provider(
        _user_repos, MockUserRepository
    )
    test_app.dependency_overrides[get_group_repository] = _repo_provider(
        _group_repos, MockGroupRepository
    )
    test_app.dependency_overrides[get_role_repository] = _config_repo_provider(
        _role_repos, MockRoleRepository
    )
    test_app.dependency_overrides[get_permission_repository] = _config_repo_provider(
        _permission_repos, MockPermissionRepository
    )
    test_app.dependency_overrides[get_user_role_repository] = _repo_provider(
        _user_role_repos, MockUserRoleRepository
    )
    test_app.dependency_overrides[get_user_group_repository] = _repo_provider(
        _user_group_repos, MockUserGroupRepository
    )
    test_app.dependency_overrides[get_group_role_repository] = _repo_provider(
        _group_role_repos, MockGroupRoleRepository
    )
    test_app.dependency_overrides[get_constraint_repository] = _config_repo_provider(
        _constraint_repos, MockConstraintRepository
    )
    test_app.dependency_overrides[get_condition_repository] = _config_repo_provider(
        _condition_repos, MockConditionRepository
    )
    test_app.dependency_overrides[get_access_log_repository] = _repo_provider(
        _access_log_repos, MockAccessLogRepository
    )
    test_app.dependency_overrides[get_tenant_repository] = _repo_provider(
        _tenant_repos, MockTenantRepository
    )
    test_app.dependency_overrides[get_tenant_member_repository] = _repo_provider(
        _tenant_member_repos, MockTenantMemberRepository
    )
    test_app.dependency_overrides[get_environment_state_repository] = _provide_state
    test_app.dependency_overrides[get_snapshot_cache] = _provide_snapshot_cache

    return test_app


app = _create_test_app()


@pytest.fixture(autouse=True)
def reset_repos() -> Generator[None]:
    _reset_all_repos()
    yield
    _reset_all_repos()


@pytest.fixture
def client() -> Generator[TestClient]:
    with TestClient(app) as c:
        yield c


API = "/api/v1"
