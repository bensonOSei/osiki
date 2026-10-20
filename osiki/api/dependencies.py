from functools import cache
from typing import Annotated

from fastapi import Depends

from osiki.api.actor import ActorDep
from osiki.api.environment import EnvironmentId
from osiki.repositories.access_logs.base_access_log_repository import (
    BaseAccessLogRepository,
)
from osiki.repositories.access_logs.mongodb_access_log_repository import (
    MongoDBAccessLogRepository,
)
from osiki.repositories.audit_logs.base_audit_log_repository import (
    BaseAuditLogRepository,
)
from osiki.repositories.audit_logs.mongodb_audit_log_repository import (
    MongoDBAuditLogRepository,
)
from osiki.repositories.conditions.base_condition_repository import (
    BaseConditionRepository,
)
from osiki.repositories.conditions.mongodb_condition_repository import (
    MongoDBConditionRepository,
)
from osiki.repositories.constraints.base_constraint_repository import (
    BaseConstraintRepository,
)
from osiki.repositories.constraints.mongodb_constraint_repository import (
    MongoDBConstraintRepository,
)
from osiki.repositories.endpoints.base_endpoint_repository import (
    BaseEndpointRepository,
)
from osiki.repositories.endpoints.mongodb_endpoint_repository import (
    MongoDBEndpointRepository,
)
from osiki.repositories.environment_state.base_environment_state_repository import (
    BaseEnvironmentStateRepository,
)
from osiki.repositories.environment_state.mongodb_environment_state_repository import (
    MongoDBEnvironmentStateRepository,
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
from osiki.repositories.tenant_team_locks.base_tenant_team_lock_repository import (
    BaseTenantTeamLockRepository,
)
from osiki.repositories.tenant_team_locks.mongodb_tenant_team_lock_repository import (
    MongoDBTenantTeamLockRepository,
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
from osiki.services.audit.audit_writer import AuditWriter
from osiki.services.authorization.authorization_service import AuthorizationService
from osiki.services.authorization.base_authorization_service import (
    BaseAuthorizationService,
)
from osiki.services.bundle_builder.bundle_builder import BundleBuilder
from osiki.services.constraint_validator.base_constraint_validator import (
    BaseConstraintValidator,
)
from osiki.services.constraint_validator.constraint_validator import ConstraintValidator
from osiki.services.snapshot_builder.snapshot_builder import (
    SnapshotBuilder,
    SnapshotCache,
)
from osiki.services.team.team_service import TeamService
from osiki.services.unit_of_work import UnitOfWork, get_unit_of_work


# Repository dependencies
def get_environment_state_repository(
    environment_id: EnvironmentId,
) -> BaseEnvironmentStateRepository:
    return MongoDBEnvironmentStateRepository(environment_id)


# Config repositories bump the environment's config version on every write.
EnvironmentStateRepository = Annotated[
    BaseEnvironmentStateRepository, Depends(get_environment_state_repository)
]


def get_user_repository(
    environment_id: EnvironmentId, state: EnvironmentStateRepository
) -> BaseUserRepository:
    return MongoDBUserRepository(environment_id, state)


def get_group_repository(
    environment_id: EnvironmentId, state: EnvironmentStateRepository
) -> BaseGroupRepository:
    return MongoDBGroupRepository(environment_id, state)


def get_role_repository(
    environment_id: EnvironmentId, state: EnvironmentStateRepository
) -> BaseRoleRepository:
    return MongoDBRoleRepository(environment_id, state)


def get_permission_repository(
    environment_id: EnvironmentId, state: EnvironmentStateRepository
) -> BasePermissionRepository:
    return MongoDBPermissionRepository(environment_id, state)


def get_user_role_repository(
    environment_id: EnvironmentId, state: EnvironmentStateRepository
) -> BaseUserRoleRepository:
    return MongoDBUserRoleRepository(environment_id, state)


def get_user_group_repository(
    environment_id: EnvironmentId, state: EnvironmentStateRepository
) -> BaseUserGroupRepository:
    return MongoDBUserGroupRepository(environment_id, state)


def get_group_role_repository(
    environment_id: EnvironmentId, state: EnvironmentStateRepository
) -> BaseGroupRoleRepository:
    return MongoDBGroupRoleRepository(environment_id, state)


def get_constraint_repository(
    environment_id: EnvironmentId, state: EnvironmentStateRepository
) -> BaseConstraintRepository:
    return MongoDBConstraintRepository(environment_id, state)


def get_condition_repository(
    environment_id: EnvironmentId, state: EnvironmentStateRepository
) -> BaseConditionRepository:
    return MongoDBConditionRepository(environment_id, state)


def get_endpoint_repository(
    environment_id: EnvironmentId, state: EnvironmentStateRepository
) -> BaseEndpointRepository:
    return MongoDBEndpointRepository(environment_id, state)


def get_access_log_repository(environment_id: EnvironmentId) -> BaseAccessLogRepository:
    return MongoDBAccessLogRepository(environment_id)


def get_audit_log_repository(environment_id: EnvironmentId) -> BaseAuditLogRepository:
    return MongoDBAuditLogRepository(environment_id)


def get_tenant_repository(
    environment_id: EnvironmentId, state: EnvironmentStateRepository
) -> BaseTenantRepository:
    return MongoDBTenantRepository(environment_id, state)


def get_tenant_member_repository(
    environment_id: EnvironmentId, state: EnvironmentStateRepository
) -> BaseTenantMemberRepository:
    return MongoDBTenantMemberRepository(environment_id, state)


def get_tenant_team_lock_repository(
    environment_id: EnvironmentId,
) -> BaseTenantTeamLockRepository:
    return MongoDBTenantTeamLockRepository(environment_id)


# Service dependencies
@cache
def get_snapshot_cache() -> SnapshotCache:
    """The one process-wide snapshot cache."""
    return SnapshotCache()


def get_constraint_validator(
    constraint_repository: Annotated[
        BaseConstraintRepository, Depends(get_constraint_repository)
    ],
    user_role_repository: Annotated[
        BaseUserRoleRepository, Depends(get_user_role_repository)
    ],
    role_repository: Annotated[BaseRoleRepository, Depends(get_role_repository)],
    group_role_repository: Annotated[
        BaseGroupRoleRepository, Depends(get_group_role_repository)
    ],
    user_group_repository: Annotated[
        BaseUserGroupRepository, Depends(get_user_group_repository)
    ],
    group_repository: Annotated[BaseGroupRepository, Depends(get_group_repository)],
) -> BaseConstraintValidator:
    return ConstraintValidator(
        constraint_repository=constraint_repository,
        user_role_repository=user_role_repository,
        role_repository=role_repository,
        group_role_repository=group_role_repository,
        user_group_repository=user_group_repository,
        group_repository=group_repository,
    )


def get_snapshot_builder(
    environment_id: EnvironmentId,
    state: EnvironmentStateRepository,
    role_repository: Annotated[BaseRoleRepository, Depends(get_role_repository)],
    permission_repository: Annotated[
        BasePermissionRepository, Depends(get_permission_repository)
    ],
    condition_repository: Annotated[
        BaseConditionRepository, Depends(get_condition_repository)
    ],
    constraint_repository: Annotated[
        BaseConstraintRepository, Depends(get_constraint_repository)
    ],
    endpoint_repository: Annotated[
        BaseEndpointRepository, Depends(get_endpoint_repository)
    ],
    snapshot_cache: Annotated[SnapshotCache, Depends(get_snapshot_cache)],
) -> SnapshotBuilder:
    return SnapshotBuilder(
        environment_id,
        state,
        role_repository,
        permission_repository,
        condition_repository,
        constraint_repository,
        endpoint_repository,
        cache=snapshot_cache,
    )


def get_bundle_builder(
    user_repository: Annotated[BaseUserRepository, Depends(get_user_repository)],
    user_role_repository: Annotated[
        BaseUserRoleRepository, Depends(get_user_role_repository)
    ],
    user_group_repository: Annotated[
        BaseUserGroupRepository, Depends(get_user_group_repository)
    ],
    group_repository: Annotated[BaseGroupRepository, Depends(get_group_repository)],
    group_role_repository: Annotated[
        BaseGroupRoleRepository, Depends(get_group_role_repository)
    ],
    tenant_member_repository: Annotated[
        BaseTenantMemberRepository, Depends(get_tenant_member_repository)
    ],
    tenant_repository: Annotated[BaseTenantRepository, Depends(get_tenant_repository)],
    role_repository: Annotated[BaseRoleRepository, Depends(get_role_repository)],
    permission_repository: Annotated[
        BasePermissionRepository, Depends(get_permission_repository)
    ],
    condition_repository: Annotated[
        BaseConditionRepository, Depends(get_condition_repository)
    ],
) -> BundleBuilder:
    return BundleBuilder(
        user_repository,
        user_role_repository,
        user_group_repository,
        group_repository,
        group_role_repository,
        tenant_member_repository,
        tenant_repository,
        role_repository,
        permission_repository,
        condition_repository,
    )


def get_authorization_service(
    snapshot_builder: Annotated[SnapshotBuilder, Depends(get_snapshot_builder)],
    bundle_builder: Annotated[BundleBuilder, Depends(get_bundle_builder)],
) -> BaseAuthorizationService:
    return AuthorizationService(
        snapshot_builder=snapshot_builder, bundle_builder=bundle_builder
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
ConditionRepository = Annotated[
    BaseConditionRepository, Depends(get_condition_repository)
]
EndpointRepository = Annotated[BaseEndpointRepository, Depends(get_endpoint_repository)]
AccessLogRepository = Annotated[
    BaseAccessLogRepository, Depends(get_access_log_repository)
]
AuditLogRepository = Annotated[
    BaseAuditLogRepository, Depends(get_audit_log_repository)
]
TenantRepository = Annotated[BaseTenantRepository, Depends(get_tenant_repository)]
TenantMemberRepository = Annotated[
    BaseTenantMemberRepository, Depends(get_tenant_member_repository)
]
TenantTeamLockRepository = Annotated[
    BaseTenantTeamLockRepository, Depends(get_tenant_team_lock_repository)
]
AuthorizationServiceDep = Annotated[
    BaseAuthorizationService, Depends(get_authorization_service)
]
SnapshotBuilderDep = Annotated[SnapshotBuilder, Depends(get_snapshot_builder)]
BundleBuilderDep = Annotated[BundleBuilder, Depends(get_bundle_builder)]
ConstraintValidatorDep = Annotated[
    BaseConstraintValidator, Depends(get_constraint_validator)
]
UnitOfWorkDep = Annotated[UnitOfWork, Depends(get_unit_of_work)]


def get_team_service(
    tenant_id: str,
    actor: ActorDep,
    environment_id: EnvironmentId,
    role_repository: RoleRepository,
    permission_repository: PermissionRepository,
    condition_repository: ConditionRepository,
    user_role_repository: UserRoleRepository,
    group_role_repository: GroupRoleRepository,
    user_repository: UserRepository,
    member_repository: TenantMemberRepository,
    lock_repository: TenantTeamLockRepository,
    audit_repository: AuditLogRepository,
    snapshot_builder: SnapshotBuilderDep,
    bundle_builder: BundleBuilderDep,
    validator: ConstraintValidatorDep,
    uow: UnitOfWorkDep,
) -> TeamService:
    return TeamService(
        environment_id,
        tenant_id,
        actor,
        role_repo=role_repository,
        permission_repo=permission_repository,
        condition_repo=condition_repository,
        user_role_repo=user_role_repository,
        group_role_repo=group_role_repository,
        user_repo=user_repository,
        member_repo=member_repository,
        lock_repo=lock_repository,
        snapshot_builder=snapshot_builder,
        bundle_builder=bundle_builder,
        validator=validator,
        uow=uow,
        audit=AuditWriter(audit_repository),
    )


TeamServiceDep = Annotated[TeamService, Depends(get_team_service)]
