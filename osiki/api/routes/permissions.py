from fastapi import APIRouter, Query, status

from osiki.api.dependencies import AuthorizationServiceDep, PermissionRepository
from osiki.api.exceptions import ConflictError, NotFoundError
from osiki.models.permission import Permission
from osiki.schemas.base import PaginatedResponse
from osiki.schemas.permission import (
    EffectiveGrantRead,
    PermissionCreate,
    PermissionRead,
)

router = APIRouter(prefix="/permissions", tags=["permissions"])


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_permission(
    data: PermissionCreate,
    permission_repo: PermissionRepository,
) -> PermissionRead:
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
    return PermissionRead(
        id=str(created.id),
        resource=created.resource,
        action=created.action,
        description=created.description,
        is_active=created.is_active,
        created_at=created.created_at,
        metadata=created.metadata,
    )


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

    return PermissionRead(
        id=str(permission.id),
        resource=permission.resource,
        action=permission.action,
        description=permission.description,
        is_active=permission.is_active,
        created_at=permission.created_at,
        metadata=permission.metadata,
    )


@router.delete("/{permission_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_permission(
    permission_id: str,
    permission_repo: PermissionRepository,
) -> None:
    success = await permission_repo.deactivate(permission_id)
    if not success:
        raise NotFoundError(
            "Permission not found", details={"permission_id": permission_id}
        )


@router.get("")
async def list_permissions(
    permission_repo: PermissionRepository,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> PaginatedResponse[PermissionRead]:
    skip = (page - 1) * page_size
    permissions = await permission_repo.list_active(skip=skip, limit=page_size)

    items = [
        PermissionRead(
            id=str(p.id),
            resource=p.resource,
            action=p.action,
            description=p.description,
            is_active=p.is_active,
            created_at=p.created_at,
            metadata=p.metadata,
        )
        for p in permissions
    ]

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
