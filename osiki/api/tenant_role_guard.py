"""Guard: a tenant-owned role may only be assigned inside its own tenant."""

from osiki.api.exceptions import ValidationError
from osiki.repositories.roles.base_role_repository import BaseRoleRepository
from osiki.schemas.scope import ScopeSchema


async def ensure_role_in_own_tenant(
    role_repo: BaseRoleRepository, role_id: str, scope: ScopeSchema | None
) -> None:
    """Refuse a tenant role whose scope is empty or names another tenant.

    Unknown ids pass through: the constraint validator and later reads already
    treat an unknown role as grantless.
    """
    role = await role_repo.get_by_id(role_id)
    if role is None or role.tenant_id is None:
        return
    if (scope.tenant_id if scope else None) != role.tenant_id:
        raise ValidationError(
            "A tenant role can only be assigned within its own tenant",
            details={"role_id": role_id, "tenant_id": role.tenant_id},
        )
