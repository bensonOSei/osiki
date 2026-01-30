from fastapi import APIRouter, Query, status

from osiki.api.dependencies import RoleRepository
from osiki.api.exceptions import ConflictError, NotFoundError
from osiki.models.role import Role
from osiki.schemas.base import PaginatedResponse
from osiki.schemas.role import RoleCreate, RoleRead, RoleUpdate

router = APIRouter(prefix="/roles", tags=["roles"])


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_role(
    data: RoleCreate,
    role_repo: RoleRepository,
) -> RoleRead:
    existing = await role_repo.get_by_name(data.name)
    if existing:
        raise ConflictError(
            "Role with this name already exists",
            details={"name": data.name},
        )

    from beanie import PydanticObjectId

    role = Role(
        name=data.name,
        description=data.description,
        parent_role_id=(
            PydanticObjectId(data.parent_role_id) if data.parent_role_id else None
        ),
        permission_ids=[PydanticObjectId(pid) for pid in (data.permission_ids or [])],
        is_system=data.is_system,
        metadata=data.metadata or {},
    )
    created = await role_repo.create(role)
    return RoleRead(
        id=str(created.id),
        name=created.name,
        description=created.description,
        parent_role_id=str(created.parent_role_id) if created.parent_role_id else None,
        permission_ids=[str(pid) for pid in created.permission_ids],
        is_system=created.is_system,
        is_active=created.is_active,
        created_at=created.created_at,
        updated_at=created.updated_at,
        metadata=created.metadata,
    )


@router.get("/{role_id}")
async def get_role(
    role_id: str,
    role_repo: RoleRepository,
) -> RoleRead:
    role = await role_repo.get_by_id(role_id)
    if not role:
        raise NotFoundError("Role not found", details={"role_id": role_id})

    return RoleRead(
        id=str(role.id),
        name=role.name,
        description=role.description,
        parent_role_id=str(role.parent_role_id) if role.parent_role_id else None,
        permission_ids=[str(pid) for pid in role.permission_ids],
        is_system=role.is_system,
        is_active=role.is_active,
        created_at=role.created_at,
        updated_at=role.updated_at,
        metadata=role.metadata,
    )


@router.patch("/{role_id}")
async def update_role(
    role_id: str,
    data: RoleUpdate,
    role_repo: RoleRepository,
) -> RoleRead:
    role = await role_repo.get_by_id(role_id)
    if not role:
        raise NotFoundError("Role not found", details={"role_id": role_id})

    from beanie import PydanticObjectId

    if data.name is not None:
        role.name = data.name
    if data.description is not None:
        role.description = data.description
    if data.parent_role_id is not None:
        role.parent_role_id = PydanticObjectId(data.parent_role_id)
    if data.permission_ids is not None:
        role.permission_ids = [PydanticObjectId(pid) for pid in data.permission_ids]
    if data.metadata is not None:
        role.metadata = data.metadata

    updated = await role_repo.update(role)
    return RoleRead(
        id=str(updated.id),
        name=updated.name,
        description=updated.description,
        parent_role_id=str(updated.parent_role_id) if updated.parent_role_id else None,
        permission_ids=[str(pid) for pid in updated.permission_ids],
        is_system=updated.is_system,
        is_active=updated.is_active,
        created_at=updated.created_at,
        updated_at=updated.updated_at,
        metadata=updated.metadata,
    )


@router.delete("/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_role(
    role_id: str,
    role_repo: RoleRepository,
) -> None:
    success = await role_repo.deactivate(role_id)
    if not success:
        raise NotFoundError("Role not found", details={"role_id": role_id})


@router.get("")
async def list_roles(
    role_repo: RoleRepository,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> PaginatedResponse[RoleRead]:
    skip = (page - 1) * page_size
    roles = await role_repo.list_active(skip=skip, limit=page_size)

    items = [
        RoleRead(
            id=str(r.id),
            name=r.name,
            description=r.description,
            parent_role_id=str(r.parent_role_id) if r.parent_role_id else None,
            permission_ids=[str(pid) for pid in r.permission_ids],
            is_system=r.is_system,
            is_active=r.is_active,
            created_at=r.created_at,
            updated_at=r.updated_at,
            metadata=r.metadata,
        )
        for r in roles
    ]

    total = len(items) + skip
    return PaginatedResponse.create(items, total, page, page_size)
