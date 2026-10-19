"""Reserved ``osiki.*`` built-ins and the default role template.

The resource prefix ``osiki.`` belongs to the engine. The only built-in
permission is ``osiki.team:manage`` (what lets a tenant admin manage their own
team), and the default template is the system role ``Owner`` that grants it.
``ensure_builtins`` creates both on demand and is safe to run repeatedly and
concurrently.
"""

from dataclasses import dataclass

from beanie import PydanticObjectId
from pymongo.errors import DuplicateKeyError

from osiki.models.permission import Permission
from osiki.models.role import Grant, Role
from osiki.repositories.permissions.base_permission_repository import (
    BasePermissionRepository,
)
from osiki.repositories.roles.base_role_repository import BaseRoleRepository

RESERVED_PREFIX = "osiki."
BUILTIN_TEAM_MANAGE = ("osiki.team", "manage")
OWNER_TEMPLATE_NAME = "Owner"


class BuiltinConflictError(Exception):
    """A user-made role squats on a built-in's name."""


@dataclass(frozen=True)
class Builtins:
    team_manage_permission_id: str
    owner_role_id: str


def is_builtin(permission: Permission) -> bool:
    """True for a permission in the reserved ``osiki.`` namespace."""
    return permission.resource.startswith(RESERVED_PREFIX)


async def _ensure_permission(permission_repo: BasePermissionRepository) -> Permission:
    resource, action = BUILTIN_TEAM_MANAGE
    existing = await permission_repo.get_by_resource_action(resource, action)
    if existing is not None:
        return existing
    try:
        return await permission_repo.create(
            Permission(
                resource=resource,
                action=action,
                description="Manage the members and roles of one's own tenant",
            )
        )
    except DuplicateKeyError:
        # A concurrent bootstrap won the race; use its permission.
        winner = await permission_repo.get_by_resource_action(resource, action)
        if winner is None:
            raise
        return winner


def _is_owner_template(role: Role) -> bool:
    return role.is_template and role.is_system


async def _ensure_owner(role_repo: BaseRoleRepository, permission: Permission) -> Role:
    existing = await role_repo.get_by_name(OWNER_TEMPLATE_NAME)
    if existing is not None:
        return _require_owner_template(existing)
    assert permission.id is not None
    try:
        return await role_repo.create(
            Role(
                name=OWNER_TEMPLATE_NAME,
                description="Default role for a tenant's first admin",
                grants=[Grant(permission_id=PydanticObjectId(permission.id))],
                is_system=True,
                is_template=True,
            )
        )
    except DuplicateKeyError:
        winner = await role_repo.get_by_name(OWNER_TEMPLATE_NAME)
        if winner is None:
            raise
        return _require_owner_template(winner)


def _require_owner_template(role: Role) -> Role:
    if not _is_owner_template(role):
        raise BuiltinConflictError(
            f"A role named {OWNER_TEMPLATE_NAME!r} already exists and is not the "
            "built-in template; rename it and bootstrap again"
        )
    return role


async def ensure_builtins(
    permission_repo: BasePermissionRepository, role_repo: BaseRoleRepository
) -> Builtins:
    permission = await _ensure_permission(permission_repo)
    owner = await _ensure_owner(role_repo, permission)
    return Builtins(
        team_manage_permission_id=str(permission.id),
        owner_role_id=str(owner.id),
    )
