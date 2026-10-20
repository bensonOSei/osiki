from typing import Any

from beanie import PydanticObjectId

from osiki.decision.models import (
    AssignmentEntry,
    ConstraintEntry,
    DecisionRequest,
    GrantEntry,
    RoleEntry,
    Snapshot,
    UserBundle,
)
from osiki.models.audit_log import AuditContext, AuditLog, Changes
from osiki.models.base import AttributeValue, Scope
from osiki.models.condition import Condition
from osiki.models.constraint import Constraint, ConstraintConfig, ConstraintType
from osiki.models.endpoint import DiscoveredEndpoint, EndpointMapping
from osiki.models.environment_state import EnvironmentState
from osiki.models.group import Group
from osiki.models.group_role import GroupRole
from osiki.models.permission import Permission
from osiki.models.role import Grant, Role
from osiki.models.tenant import Tenant
from osiki.models.tenant_member import TenantMember
from osiki.models.tenant_team_lock import TenantTeamLock
from osiki.models.user import User
from osiki.models.user_group import UserGroup
from osiki.models.user_role import UserRole


def make_user(
    external_id: str = "user-1",
    email: str | None = None,
    user_id: PydanticObjectId | None = None,
) -> User:
    user = User(external_id=external_id, email=email)
    user.id = user_id or PydanticObjectId()
    return user


def make_environment_state(
    environment_id: str = "default", config_version: int = 0
) -> EnvironmentState:
    state = EnvironmentState(
        environment_id=environment_id, config_version=config_version
    )
    state.id = PydanticObjectId()
    return state


def make_endpoint_mapping(
    method: str = "GET",
    path: str = "/invoices",
    permission: str | None = "invoices:read",
    public: bool = False,
) -> EndpointMapping:
    mapping = EndpointMapping(
        method=method, path=path, permission=permission, public=public
    )
    mapping.id = PydanticObjectId()
    return mapping


def make_discovered_endpoint(
    method: str = "GET", path: str = "/invoices", seen: float = 1.0
) -> DiscoveredEndpoint:
    found = DiscoveredEndpoint(
        method=method, path=path, first_seen=seen, last_seen=seen
    )
    found.id = PydanticObjectId()
    return found


def make_tenant(
    external_id: str = "tenant-1",
    name: str = "Tenant",
    attributes: dict[str, AttributeValue] | None = None,
) -> Tenant:
    tenant = Tenant(external_id=external_id, name=name, attributes=attributes or {})
    tenant.id = PydanticObjectId()
    return tenant


def make_tenant_member(
    tenant_id: str = "tenant-1", user_id: str = "user-1"
) -> TenantMember:
    member = TenantMember(tenant_id=tenant_id, user_id=user_id)
    member.id = PydanticObjectId()
    return member


def make_tenant_team_lock(
    tenant_id: str = "tenant-1", version: int = 0
) -> TenantTeamLock:
    lock = TenantTeamLock(tenant_id=tenant_id, version=version)
    lock.id = PydanticObjectId()
    return lock


def make_role(
    name: str = "test-role",
    permission_ids: list[PydanticObjectId] | None = None,
    grants: list[Grant] | None = None,
    parent_role_id: PydanticObjectId | None = None,
    role_id: PydanticObjectId | None = None,
    is_active: bool = True,
    tenant_id: str | None = None,
    is_template: bool = False,
    is_system: bool = False,
    copied_from: PydanticObjectId | None = None,
) -> Role:
    role = Role(
        name=name,
        grants=[
            *[Grant(permission_id=pid) for pid in (permission_ids or [])],
            *(grants or []),
        ],
        parent_role_id=parent_role_id,
        is_active=is_active,
        tenant_id=tenant_id,
        is_template=is_template,
        is_system=is_system,
        copied_from=copied_from,
    )
    role.id = role_id or PydanticObjectId()
    return role


def make_permission(
    resource: str = "resource",
    action: str = "read",
    permission_id: PydanticObjectId | None = None,
    assignable: bool = False,
) -> Permission:
    perm = Permission(resource=resource, action=action, assignable=assignable)
    perm.id = permission_id or PydanticObjectId()
    return perm


def make_user_role(
    user_id: PydanticObjectId,
    role_id: PydanticObjectId,
    scope: Scope | None = None,
    user_role_id: PydanticObjectId | None = None,
    expires_at: float | None = None,
) -> UserRole:
    ur = UserRole(
        user_id=user_id,
        role_id=role_id,
        scope=scope or Scope(),
        assigned_by="admin",
        expires_at=expires_at,
    )
    ur.id = user_role_id or PydanticObjectId()
    return ur


def make_user_group(
    user_id: PydanticObjectId,
    group_id: PydanticObjectId,
    user_group_id: PydanticObjectId | None = None,
) -> UserGroup:
    ug = UserGroup(user_id=user_id, group_id=group_id, added_by="admin")
    ug.id = user_group_id or PydanticObjectId()
    return ug


def make_group_role(
    group_id: PydanticObjectId,
    role_id: PydanticObjectId,
    scope: Scope | None = None,
    group_role_id: PydanticObjectId | None = None,
    expires_at: float | None = None,
) -> GroupRole:
    gr = GroupRole(
        group_id=group_id,
        role_id=role_id,
        scope=scope or Scope(),
        assigned_by="admin",
        expires_at=expires_at,
    )
    gr.id = group_role_id or PydanticObjectId()
    return gr


def make_group(
    name: str = "test-group",
    group_id: PydanticObjectId | None = None,
) -> Group:
    group = Group(name=name)
    group.id = group_id or PydanticObjectId()
    return group


def make_constraint(
    name: str,
    constraint_type: ConstraintType,
    config: ConstraintConfig,
    constraint_id: PydanticObjectId | None = None,
) -> Constraint:
    c = Constraint(name=name, type=constraint_type, config=config)
    c.id = constraint_id or PydanticObjectId()
    return c


def make_condition(
    key: str = "is_owner",
    expression: dict[str, Any] | None = None,
    condition_id: PydanticObjectId | None = None,
) -> Condition:
    c = Condition(
        key=key,
        name=key,
        expression=expression
        or {"op": "eq", "left": {"ref": "user.id"}, "right": {"value": "u1"}},
    )
    c.id = condition_id or PydanticObjectId()
    return c


# --- Pure decision models (osiki.decision.models) ---


def make_role_entry(
    role_id: str = "role-1",
    grants: list[tuple[str, str | None]] | None = None,
    parent_id: str | None = None,
    name: str | None = None,
) -> RoleEntry:
    """``grants`` is a list of ``(permission, condition_key)`` pairs."""
    return RoleEntry(
        id=role_id,
        name=name or role_id,
        parent_id=parent_id,
        grants=[
            GrantEntry(permission=permission, condition=condition)
            for permission, condition in grants or []
        ],
    )


def make_snapshot(
    roles: list[RoleEntry] | None = None,
    conditions: dict[str, dict[str, Any]] | None = None,
    constraints: list[ConstraintEntry] | None = None,
    environment_id: str = "default",
    version: int = 1,
) -> Snapshot:
    return Snapshot(
        environment_id=environment_id,
        version=version,
        roles=roles or [],
        conditions=conditions or {},
        constraints=constraints or [],
    )


def make_assignment_entry(
    role_id: str = "role-1",
    scope: dict[str, str] | None = None,
    expires_at: float | None = None,
    via: str = "direct",
) -> AssignmentEntry:
    return AssignmentEntry.model_validate(
        {"role_id": role_id, "scope": scope or {}, "expires_at": expires_at, "via": via}
    )


def make_user_bundle(
    assignments: list[AssignmentEntry] | None = None,
    user_id: str = "user-1",
    attributes: dict[str, Any] | None = None,
    tenants: dict[str, dict[str, Any]] | None = None,
    roles: list[RoleEntry] | None = None,
) -> UserBundle:
    return UserBundle(
        user_id=user_id,
        attributes=attributes or {},
        tenants=tenants or {},
        assignments=assignments or [],
        roles=roles or [],
    )


def make_decision_request(
    resource: str = "docs",
    action: str = "read",
    scope: dict[str, str] | None = None,
    record: dict[str, Any] | None = None,
    now: float = 1000,
) -> DecisionRequest:
    return DecisionRequest(
        resource=resource, action=action, scope=scope or {}, record=record, now=now
    )


def make_audit_log(
    action: str = "role.create",
    tenant_id: str | None = None,
    actor_id: str = "actor-1",
    actor_type: str = "developer",
    target_type: str = "role",
    target_id: str = "target-1",
    timestamp: float | None = None,
) -> AuditLog:
    log = AuditLog(
        actor_id=actor_id,
        actor_type=actor_type,
        action=action,
        target_type=target_type,
        target_id=target_id,
        tenant_id=tenant_id,
        changes=Changes(),
        context=AuditContext(),
    )
    if timestamp is not None:
        log.timestamp = timestamp
    log.id = PydanticObjectId()
    return log
