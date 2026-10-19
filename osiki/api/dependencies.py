from typing import Annotated

from fastapi import Depends

from osiki.api.environment import EnvironmentId
from osiki.repositories.access_logs.base_access_log_repository import (
    BaseAccessLogRepository,
)
from osiki.repositories.access_logs.mongodb_access_log_repository import (
    MongoDBAccessLogRepository,
)
from osiki.repositories.constraints.base_constraint_repository import (
    BaseConstraintRepository,
)
from osiki.repositories.constraints.mongodb_constraint_repository import (
    MongoDBConstraintRepository,
)
from osiki.repositories.group_roles.base_group_role_repository import (
    BaseGroupRoleRepository,
)
from osiki.repositories.group_roles.mongodb_group_role_repository import (
    MongoDBGroupRoleRepository,
)
from osiki.repositories.groups.base_group_repository import BaseGroupRepository
from osiki.repositories.groups.mongodb_group_repository import MongoDBGroupRepository
from osiki.repositories.permissions.base_permission_repository import (
    BasePermissionRepository,
)
from osiki.repositories.permissions.mongodb_permission_repository import (
    MongoDBPermissionRepository,
)
from osiki.repositories.roles.base_role_repository import BaseRoleRepository
from osiki.repositories.roles.mongodb_role_repository import MongoDBRoleRepository
from osiki.repositories.tenant_members.base_tenant_member_repository import (
    BaseTenantMemberRepository,
)
from osiki.repositories.tenant_members.mongodb_tenant_member_repository import (
    MongoDBTenantMemberRepository,
)
from osiki.repositories.tenants.base_tenant_repository import BaseTenantRepository
from osiki.repositories.tenants.mongodb_tenant_repository import (
    MongoDBTenantRepository,
)
from osiki.repositories.user_groups.base_user_group_repository import (
    BaseUserGroupRepository,
)
from osiki.repositories.user_groups.mongodb_user_group_repository import (
    MongoDBUserGroupRepository,
)
from osiki.repositories.user_roles.base_user_role_repository import (
    BaseUserRoleRepository,
)
from osiki.repositories.user_roles.mongodb_user_role_repository import (
    MongoDBUserRoleRepository,
)
from osiki.repositories.users.base_user_repository import BaseUserRepository
from osiki.repositories.users.mongodb_user_repository import MongoDBUserRepository
from osiki.services.authorization.authorization_service import AuthorizationService
from osiki.services.authorization.base_authorization_service import (
    BaseAuthorizationService,
)
from osiki.services.constraint_validator.base_constraint_validator import (
    BaseConstraintValidator,
)
from osiki.services.constraint_validator.constraint_validator import ConstraintValidator
from osiki.services.permission_resolver.base_permission_resolver import (
    BasePermissionResolver,
)
from osiki.services.permission_resolver.permission_resolver import PermissionResolver
from osiki.services.scope_matcher.base_scope_matcher import BaseScopeMatcher
from osiki.services.scope_matcher.scope_matcher import ScopeMatcher


# Repository dependencies
def get_user_repository(environment_id: EnvironmentId) -> BaseUserRepository:
    return MongoDBUserRepository(environment_id)


def get_group_repository(environment_id: EnvironmentId) -> BaseGroupRepository:
    return MongoDBGroupRepository(environment_id)


def get_role_repository(environment_id: EnvironmentId) -> BaseRoleRepository:
    return MongoDBRoleRepository(environment_id)


def get_permission_repository(
    environment_id: EnvironmentId,
) -> BasePermissionRepository:
    return MongoDBPermissionRepository(environment_id)


def get_user_role_repository(environment_id: EnvironmentId) -> BaseUserRoleRepository:
    return MongoDBUserRoleRepository(environment_id)


def get_user_group_repository(environment_id: EnvironmentId) -> BaseUserGroupRepository:
    return MongoDBUserGroupRepository(environment_id)


def get_group_role_repository(environment_id: EnvironmentId) -> BaseGroupRoleRepository:
    return MongoDBGroupRoleRepository(environment_id)


def get_constraint_repository(
    environment_id: EnvironmentId,
) -> BaseConstraintRepository:
    return MongoDBConstraintRepository(environment_id)


def get_access_log_repository(environment_id: EnvironmentId) -> BaseAccessLogRepository:
    return MongoDBAccessLogRepository(environment_id)


def get_tenant_repository(environment_id: EnvironmentId) -> BaseTenantRepository:
    return MongoDBTenantRepository(environment_id)


def get_tenant_member_repository(
    environment_id: EnvironmentId,
) -> BaseTenantMemberRepository:
    return MongoDBTenantMemberRepository(environment_id)


# Service dependencies
def get_scope_matcher() -> BaseScopeMatcher:
    return ScopeMatcher()


def get_constraint_validator(
    constraint_repository: Annotated[
        BaseConstraintRepository, Depends(get_constraint_repository)
    ],
    user_role_repository: Annotated[
        BaseUserRoleRepository, Depends(get_user_role_repository)
    ],
) -> BaseConstraintValidator:
    return ConstraintValidator(
        constraint_repository=constraint_repository,
        user_role_repository=user_role_repository,
    )


def get_permission_resolver(
    user_role_repository: Annotated[
        BaseUserRoleRepository, Depends(get_user_role_repository)
    ],
    user_group_repository: Annotated[
        BaseUserGroupRepository, Depends(get_user_group_repository)
    ],
    group_role_repository: Annotated[
        BaseGroupRoleRepository, Depends(get_group_role_repository)
    ],
    role_repository: Annotated[BaseRoleRepository, Depends(get_role_repository)],
    permission_repository: Annotated[
        BasePermissionRepository, Depends(get_permission_repository)
    ],
    scope_matcher: Annotated[BaseScopeMatcher, Depends(get_scope_matcher)],
) -> BasePermissionResolver:
    return PermissionResolver(
        user_role_repository=user_role_repository,
        user_group_repository=user_group_repository,
        group_role_repository=group_role_repository,
        role_repository=role_repository,
        permission_repository=permission_repository,
        scope_matcher=scope_matcher,
    )


def get_authorization_service(
    permission_resolver: Annotated[
        BasePermissionResolver, Depends(get_permission_resolver)
    ],
    user_repository: Annotated[BaseUserRepository, Depends(get_user_repository)],
    tenant_member_repository: Annotated[
        BaseTenantMemberRepository, Depends(get_tenant_member_repository)
    ],
) -> BaseAuthorizationService:
    return AuthorizationService(
        permission_resolver=permission_resolver,
        user_repository=user_repository,
        tenant_member_repository=tenant_member_repository,
    )


# Type aliases for dependency injection
UserRepository = Annotated[BaseUserRepository, Depends(get_user_repository)]
GroupRepository = Annotated[BaseGroupRepository, Depends(get_group_repository)]
RoleRepository = Annotated[BaseRoleRepository, Depends(get_role_repository)]
PermissionRepository = Annotated[
    BasePermissionRepository, Depends(get_permission_repository)
]
UserRoleRepository = Annotated[
    BaseUserRoleRepository, Depends(get_user_role_repository)
]
UserGroupRepository = Annotated[
    BaseUserGroupRepository, Depends(get_user_group_repository)
]
GroupRoleRepository = Annotated[
    BaseGroupRoleRepository, Depends(get_group_role_repository)
]
ConstraintRepository = Annotated[
    BaseConstraintRepository, Depends(get_constraint_repository)
]
AccessLogRepository = Annotated[
    BaseAccessLogRepository, Depends(get_access_log_repository)
]
TenantRepository = Annotated[BaseTenantRepository, Depends(get_tenant_repository)]
TenantMemberRepository = Annotated[
    BaseTenantMemberRepository, Depends(get_tenant_member_repository)
]
AuthorizationServiceDep = Annotated[
    BaseAuthorizationService, Depends(get_authorization_service)
]
PermissionResolverDep = Annotated[
    BasePermissionResolver, Depends(get_permission_resolver)
]
ConstraintValidatorDep = Annotated[
    BaseConstraintValidator, Depends(get_constraint_validator)
]
