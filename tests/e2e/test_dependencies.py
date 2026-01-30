from osiki.api.dependencies import (
    get_access_log_repository,
    get_constraint_repository,
    get_constraint_validator,
    get_group_repository,
    get_group_role_repository,
    get_permission_repository,
    get_role_repository,
    get_scope_matcher,
    get_user_group_repository,
    get_user_repository,
    get_user_role_repository,
)
from osiki.repositories.access_logs.mongodb_access_log_repository import (
    MongoDBAccessLogRepository,
)
from osiki.repositories.constraints.mongodb_constraint_repository import (
    MongoDBConstraintRepository,
)
from osiki.repositories.group_roles.mongodb_group_role_repository import (
    MongoDBGroupRoleRepository,
)
from osiki.repositories.groups.mongodb_group_repository import MongoDBGroupRepository
from osiki.repositories.permissions.mongodb_permission_repository import (
    MongoDBPermissionRepository,
)
from osiki.repositories.roles.mongodb_role_repository import MongoDBRoleRepository
from osiki.repositories.user_groups.mongodb_user_group_repository import (
    MongoDBUserGroupRepository,
)
from osiki.repositories.user_roles.mongodb_user_role_repository import (
    MongoDBUserRoleRepository,
)
from osiki.repositories.users.mongodb_user_repository import MongoDBUserRepository
from osiki.services.constraint_validator.constraint_validator import ConstraintValidator
from osiki.services.scope_matcher.scope_matcher import ScopeMatcher


def test_get_user_repository() -> None:
    assert isinstance(get_user_repository(), MongoDBUserRepository)


def test_get_group_repository() -> None:
    assert isinstance(get_group_repository(), MongoDBGroupRepository)


def test_get_role_repository() -> None:
    assert isinstance(get_role_repository(), MongoDBRoleRepository)


def test_get_permission_repository() -> None:
    assert isinstance(get_permission_repository(), MongoDBPermissionRepository)


def test_get_user_role_repository() -> None:
    assert isinstance(get_user_role_repository(), MongoDBUserRoleRepository)


def test_get_user_group_repository() -> None:
    assert isinstance(get_user_group_repository(), MongoDBUserGroupRepository)


def test_get_group_role_repository() -> None:
    assert isinstance(get_group_role_repository(), MongoDBGroupRoleRepository)


def test_get_constraint_repository() -> None:
    assert isinstance(get_constraint_repository(), MongoDBConstraintRepository)


def test_get_access_log_repository() -> None:
    assert isinstance(get_access_log_repository(), MongoDBAccessLogRepository)


def test_get_scope_matcher() -> None:
    assert isinstance(get_scope_matcher(), ScopeMatcher)


def test_get_constraint_validator() -> None:
    constraint_repo = get_constraint_repository()
    user_role_repo = get_user_role_repository()
    validator = get_constraint_validator(constraint_repo, user_role_repo)
    assert isinstance(validator, ConstraintValidator)
