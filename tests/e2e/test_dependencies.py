from typing import Annotated

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from osiki.api.dependencies import (
    get_access_log_repository,
    get_authorization_service,
    get_bundle_builder,
    get_condition_repository,
    get_constraint_repository,
    get_constraint_validator,
    get_environment_state_repository,
    get_group_repository,
    get_group_role_repository,
    get_permission_repository,
    get_role_repository,
    get_snapshot_builder,
    get_snapshot_cache,
    get_tenant_member_repository,
    get_tenant_repository,
    get_user_group_repository,
    get_user_repository,
    get_user_role_repository,
)
from osiki.repositories.access_logs.mongodb_access_log_repository import (
    MongoDBAccessLogRepository,
)
from osiki.repositories.conditions.mongodb_condition_repository import (
    MongoDBConditionRepository,
)
from osiki.repositories.constraints.mongodb_constraint_repository import (
    MongoDBConstraintRepository,
)
from osiki.repositories.environment_state.mongodb_environment_state_repository import (
    MongoDBEnvironmentStateRepository,
)
from osiki.repositories.group_roles.mongodb_group_role_repository import (
    MongoDBGroupRoleRepository,
)
from osiki.repositories.groups.mongodb_group_repository import MongoDBGroupRepository
from osiki.repositories.permissions.mongodb_permission_repository import (
    MongoDBPermissionRepository,
)
from osiki.repositories.roles.mongodb_role_repository import MongoDBRoleRepository
from osiki.repositories.tenant_members.mongodb_tenant_member_repository import (
    MongoDBTenantMemberRepository,
)
from osiki.repositories.tenants.mongodb_tenant_repository import (
    MongoDBTenantRepository,
)
from osiki.repositories.user_groups.mongodb_user_group_repository import (
    MongoDBUserGroupRepository,
)
from osiki.repositories.user_roles.mongodb_user_role_repository import (
    MongoDBUserRoleRepository,
)
from osiki.repositories.users.mongodb_user_repository import MongoDBUserRepository
from osiki.services.authorization.authorization_service import AuthorizationService
from osiki.services.constraint_validator.constraint_validator import ConstraintValidator
from osiki.services.snapshot_builder.snapshot_builder import SnapshotCache


def _state() -> MongoDBEnvironmentStateRepository:
    return MongoDBEnvironmentStateRepository("default")


def test_get_user_repository() -> None:
    assert isinstance(get_user_repository("default"), MongoDBUserRepository)


def test_get_group_repository() -> None:
    assert isinstance(get_group_repository("default"), MongoDBGroupRepository)


def test_get_role_repository() -> None:
    assert isinstance(get_role_repository("default", _state()), MongoDBRoleRepository)


def test_get_permission_repository() -> None:
    assert isinstance(
        get_permission_repository("default", _state()), MongoDBPermissionRepository
    )


def test_get_user_role_repository() -> None:
    assert isinstance(get_user_role_repository("default"), MongoDBUserRoleRepository)


def test_get_user_group_repository() -> None:
    assert isinstance(get_user_group_repository("default"), MongoDBUserGroupRepository)


def test_get_group_role_repository() -> None:
    assert isinstance(get_group_role_repository("default"), MongoDBGroupRoleRepository)


def test_get_constraint_repository() -> None:
    assert isinstance(
        get_constraint_repository("default", _state()), MongoDBConstraintRepository
    )


def test_get_condition_repository() -> None:
    assert isinstance(
        get_condition_repository("default", _state()), MongoDBConditionRepository
    )


def test_get_access_log_repository() -> None:
    assert isinstance(get_access_log_repository("default"), MongoDBAccessLogRepository)


def test_get_snapshot_cache_is_process_wide() -> None:
    assert isinstance(get_snapshot_cache(), SnapshotCache)
    assert get_snapshot_cache() is get_snapshot_cache()


def test_snapshot_cache_resolves_once_through_depends() -> None:
    probe = FastAPI()

    @probe.get("/cache")
    def read(cache: Annotated[SnapshotCache, Depends(get_snapshot_cache)]) -> int:
        return id(cache)

    with TestClient(probe) as client:
        first = client.get("/cache")
        second = client.get("/cache")

    assert first.status_code == 200
    assert first.json() == second.json() == id(get_snapshot_cache())


def test_get_environment_state_repository() -> None:
    assert isinstance(
        get_environment_state_repository("default"),
        MongoDBEnvironmentStateRepository,
    )


def test_get_authorization_service() -> None:
    state = get_environment_state_repository("default")
    snapshot_builder = get_snapshot_builder(
        "default",
        state,
        get_role_repository("default", state),
        get_permission_repository("default", state),
        get_condition_repository("default", state),
        get_constraint_repository("default", state),
        get_snapshot_cache(),
    )
    bundle_builder = get_bundle_builder(
        get_user_repository("default"),
        get_user_role_repository("default"),
        get_user_group_repository("default"),
        get_group_role_repository("default"),
        get_tenant_member_repository("default"),
        get_tenant_repository("default"),
    )
    service = get_authorization_service(snapshot_builder, bundle_builder)
    assert isinstance(service, AuthorizationService)


def test_get_constraint_validator() -> None:
    constraint_repo = get_constraint_repository("default", _state())
    user_role_repo = get_user_role_repository("default")
    validator = get_constraint_validator(constraint_repo, user_role_repo)
    assert isinstance(validator, ConstraintValidator)


def test_get_tenant_repository() -> None:
    assert isinstance(get_tenant_repository("default"), MongoDBTenantRepository)


def test_get_tenant_member_repository() -> None:
    assert isinstance(
        get_tenant_member_repository("default"), MongoDBTenantMemberRepository
    )
