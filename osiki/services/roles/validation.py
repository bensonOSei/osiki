"""Reference checks shared by the project roles API and the team service."""

from collections.abc import Sequence
from typing import Protocol

from beanie import PydanticObjectId

from osiki.api.exceptions import ValidationError
from osiki.repositories.conditions.base_condition_repository import (
    BaseConditionRepository,
)
from osiki.repositories.permissions.base_permission_repository import (
    BasePermissionRepository,
)
from osiki.repositories.roles.base_role_repository import BaseRoleRepository


class GrantReference(Protocol):
    @property
    def permission_id(self) -> str: ...

    @property
    def condition_id(self) -> str | None: ...


def check_object_id(value: str, field: str) -> None:
    if not PydanticObjectId.is_valid(value):
        raise ValidationError(f"Invalid {field}: {value}", details={field: value})


async def validate_references(
    grants: Sequence[GrantReference],
    parent_role_id: str | None,
    role_repo: BaseRoleRepository,
    permission_repo: BasePermissionRepository,
    condition_repo: BaseConditionRepository,
) -> None:
    """Every permission, condition and parent must exist in this environment."""
    for grant in grants:
        check_object_id(grant.permission_id, "permission_id")
        if await permission_repo.get_by_id(grant.permission_id) is None:
            raise ValidationError(
                f"Permission not found: {grant.permission_id}",
                details={"permission_id": grant.permission_id},
            )
        if grant.condition_id is not None:
            check_object_id(grant.condition_id, "condition_id")
            condition = await condition_repo.get_by_id(grant.condition_id)
            if condition is None or not condition.is_active:
                raise ValidationError(
                    f"Condition not found: {grant.condition_id}",
                    details={"condition_id": grant.condition_id},
                )
    if parent_role_id is not None:
        check_object_id(parent_role_id, "parent_role_id")
        parent = await role_repo.get_by_id(parent_role_id)
        if parent is None or parent.tenant_id is not None:
            raise ValidationError(
                f"Parent role not found: {parent_role_id}",
                details={"parent_role_id": parent_role_id},
            )
