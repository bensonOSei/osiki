from fastapi import APIRouter, Query, status

from osiki.api.actor import ActorDep
from osiki.api.dependencies import (
    AuditWriterDep,
    AuthorizationServiceDep,
    PermissionRepository,
)
from osiki.api.exceptions import ConflictError, NotFoundError, ValidationError
from osiki.models.permission import Permission
from osiki.schemas.base import PaginatedResponse
from osiki.schemas.permission import (
    EffectiveGrantRead,
    PermissionCreate,
    PermissionRead,
    PermissionUpdate,
)
from osiki.services.audit.project_state import permission_audit_state
from osiki.services.builtins import RESERVED_PREFIX, is_builtin

router = APIRouter(prefix="/permissions", tags=["permissions"])


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_permission(
    data: PermissionCreate,
    permission_repo: PermissionRepository,
    audit: AuditWriterDep,
    actor: ActorDep,
) -> PermissionRead:
    if data.resource.startswith(RESERVED_PREFIX):
        raise ValidationError(
            f"The resource prefix {RESERVED_PREFIX!r} is reserved for built-ins",
            details={"resource": data.resource},
        )
    existing = await permission_repo.get_by_resource_action(data.resource, data.action)
    if existing:
        raise ConflictError(
            "Permission with this resource and action already exists",
            details={"resource": data.resource, "action": data.action},
        )

    permission = Permission(
        resource=data.resource,
        action=data.action,
        description=data.description,
        metadata=data.metadata or {},
    )
    created = await permission_repo.create(permission)
    await audit.record(
        actor,
        "permission.create",
        "permission",
        str(created.id),
        tenant_id=None,
        before=None,
        after=permission_audit_state(created),
    )
    return PermissionRead.from_model(created)


@router.get("/{permission_id}")
async def get_permission(
    permission_id: str,
    permission_repo: PermissionRepository,
) -> PermissionRead:
    permission = await permission_repo.get_by_id(permission_id)
    if not permission:
        raise NotFoundError(
            "Permission not found", details={"permission_id": permission_id}
        )

    return PermissionRead.from_model(permission)


@router.patch("/{permission_id}")
async def update_permission(
    permission_id: str,
    data: PermissionUpdate,
    permission_repo: PermissionRepository,
    audit: AuditWriterDep,
    actor: ActorDep,
) -> PermissionRead:
    permission = await permission_repo.get_by_id(permission_id)
    if not permission:
        raise NotFoundError(
            "Permission not found", details={"permission_id": permission_id}
        )
    if data.assignable and is_builtin(permission):
        raise ValidationError(
            "Built-in permissions can never be assignable",
            details={"permission_id": permission_id},
        )
    before = permission_audit_state(permission)
    if data.assignable is not None:
        permission.assignable = data.assignable
    if data.description is not None:
        permission.description = data.description
    updated = await permission_repo.update(permission)
    await audit.record(
        actor,
        "permission.update",
        "permission",
        permission_id,
        tenant_id=None,
        before=before,
        after=permission_audit_state(updated),
    )
    return PermissionRead.from_model(updated)


@router.delete("/{permission_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_permission(
    permission_id: str,
    permission_repo: PermissionRepository,
    audit: AuditWriterDep,
    actor: ActorDep,
) -> None:
    permission = await permission_repo.get_by_id(permission_id)
    if permission is not None and is_builtin(permission):
        raise ValidationError(
            "Built-in permissions cannot be deleted",
            details={"permission_id": permission_id},
        )
    before = permission_audit_state(permission) if permission is not None else None
    success = await permission_repo.deactivate(permission_id)
    if not success:
        raise NotFoundError(
            "Permission not found", details={"permission_id": permission_id}
        )
    await audit.record(
        actor,
        "permission.delete",
        "permission",
        permission_id,
        tenant_id=None,
        before=before,
        after=None,
    )


@router.get("")
async def list_permissions(
    permission_repo: PermissionRepository,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> PaginatedResponse[PermissionRead]:
    skip = (page - 1) * page_size
    permissions = await permission_repo.list_active(skip=skip, limit=page_size)

    items = [PermissionRead.from_model(p) for p in permissions]

    total = len(items) + skip
    return PaginatedResponse.create(items, total, page, page_size)


@router.get("/users/{user_id}/effective")
async def get_user_effective_permissions(
    user_id: str,
    auth_service: AuthorizationServiceDep,
    tenant_id: str | None = Query(None),
) -> list[EffectiveGrantRead]:
    """The grants the user (EXTERNAL id) holds; [] in a non-member tenant."""
    scope = {"tenant_id": tenant_id} if tenant_id is not None else None
    grants = await auth_service.effective_grants(user_id, scope)
    if grants is None:
        raise NotFoundError("User not found", details={"user_id": user_id})
    return [EffectiveGrantRead.model_validate(g) for g in grants]
