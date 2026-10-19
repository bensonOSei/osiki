from fastapi import APIRouter

from osiki.api.dependencies import PermissionRepository, RoleRepository
from osiki.api.exceptions import ConflictError
from osiki.schemas.environment import BootstrapRead
from osiki.services.builtins import BuiltinConflictError, ensure_builtins

router = APIRouter(prefix="/environment", tags=["environment"])


@router.put("/bootstrap")
async def bootstrap_environment(
    permission_repo: PermissionRepository, role_repo: RoleRepository
) -> BootstrapRead:
    """Create the ``osiki.*`` built-ins and the Owner template if missing."""
    try:
        builtins = await ensure_builtins(permission_repo, role_repo)
    except BuiltinConflictError as exc:
        raise ConflictError(str(exc)) from exc
    return BootstrapRead(
        team_manage_permission_id=builtins.team_manage_permission_id,
        owner_role_id=builtins.owner_role_id,
    )
