"""E2E test fixtures with FastAPI TestClient and dependency overrides."""

from collections.abc import Generator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from osiki.api.dependencies import (
    get_access_log_repository,
    get_constraint_repository,
    get_group_repository,
    get_group_role_repository,
    get_permission_repository,
    get_role_repository,
    get_scope_matcher,
    get_user_group_repository,
    get_user_repository,
    get_user_role_repository,
)
from osiki.api.exceptions import (
    AuthorizationError,
    ValidationError,
    register_exception_handlers,
)
from osiki.api.middleware import RequestIDMiddleware
from osiki.api.routes import (
    authorization_router,
    constraints_router,
    groups_router,
    health_router,
    permissions_router,
    roles_router,
    users_router,
)
from osiki.configs.settings import get_settings
from tests.mocks.repositories import (
    MockAccessLogRepository,
    MockConstraintRepository,
    MockGroupRepository,
    MockGroupRoleRepository,
    MockPermissionRepository,
    MockRoleRepository,
    MockUserGroupRepository,
    MockUserRepository,
    MockUserRoleRepository,
)

settings = get_settings()

_user_repo = MockUserRepository()
_group_repo = MockGroupRepository()
_role_repo = MockRoleRepository()
_permission_repo = MockPermissionRepository()
_user_role_repo = MockUserRoleRepository()
_user_group_repo = MockUserGroupRepository()
_group_role_repo = MockGroupRoleRepository()
_constraint_repo = MockConstraintRepository()
_access_log_repo = MockAccessLogRepository()


def _reset_all_repos() -> None:
    _user_repo._data.clear()
    _group_repo._data.clear()
    _role_repo._data.clear()
    _permission_repo._data.clear()
    _user_role_repo._data.clear()
    _user_group_repo._data.clear()
    _group_role_repo._data.clear()
    _constraint_repo._data.clear()
    _access_log_repo._data.clear()


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
    test_app.include_router(constraints_router, prefix=settings.api_prefix)
    test_app.include_router(authorization_router, prefix=settings.api_prefix)

    @test_app.get("/_test/authorization-error")
    async def _trigger_authorization_error() -> None:
        raise AuthorizationError("forbidden", details={"reason": "test"})

    @test_app.get("/_test/validation-error")
    async def _trigger_validation_error() -> None:
        raise ValidationError("invalid input", details={"field": "test"})

    @test_app.get("/_test/internal-error")
    async def _trigger_internal_error() -> None:
        raise RuntimeError("unexpected failure")

    test_app.dependency_overrides[get_user_repository] = lambda: _user_repo
    test_app.dependency_overrides[get_group_repository] = lambda: _group_repo
    test_app.dependency_overrides[get_role_repository] = lambda: _role_repo
    test_app.dependency_overrides[get_permission_repository] = lambda: _permission_repo
    test_app.dependency_overrides[get_user_role_repository] = lambda: _user_role_repo
    test_app.dependency_overrides[get_user_group_repository] = lambda: _user_group_repo
    test_app.dependency_overrides[get_group_role_repository] = lambda: _group_role_repo
    test_app.dependency_overrides[get_constraint_repository] = lambda: _constraint_repo
    test_app.dependency_overrides[get_access_log_repository] = lambda: _access_log_repo
    test_app.dependency_overrides[get_scope_matcher] = get_scope_matcher

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
