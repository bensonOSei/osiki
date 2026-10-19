from typing import Any

from beanie import PydanticObjectId

from osiki.models.base import AttributeValue, Scope
from osiki.models.condition import Condition
from osiki.models.constraint import Constraint, ConstraintConfig, ConstraintType
from osiki.models.group import Group
from osiki.models.group_role import GroupRole
from osiki.models.permission import Permission
from osiki.models.role import Grant, Role
from osiki.models.tenant import Tenant
from osiki.models.tenant_member import TenantMember
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


def make_role(
    name: str = "test-role",
    permission_ids: list[PydanticObjectId] | None = None,
    grants: list[Grant] | None = None,
    parent_role_id: PydanticObjectId | None = None,
    role_id: PydanticObjectId | None = None,
    is_active: bool = True,
) -> Role:
    role = Role(
        name=name,
        grants=[
            *[Grant(permission_id=pid) for pid in (permission_ids or [])],
            *(grants or []),
        ],
        parent_role_id=parent_role_id,
        is_active=is_active,
    )
    role.id = role_id or PydanticObjectId()
    return role


def make_permission(
    resource: str = "resource",
    action: str = "read",
    permission_id: PydanticObjectId | None = None,
) -> Permission:
    perm = Permission(resource=resource, action=action)
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
) -> GroupRole:
    gr = GroupRole(
        group_id=group_id,
        role_id=role_id,
        scope=scope or Scope(),
        assigned_by="admin",
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
