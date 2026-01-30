from fastapi import APIRouter, Query, status

from osiki.api.dependencies import GroupRepository, GroupRoleRepository
from osiki.api.exceptions import ConflictError, NotFoundError
from osiki.models.group import Group
from osiki.schemas.base import PaginatedResponse
from osiki.schemas.group import GroupCreate, GroupRead, GroupUpdate
from osiki.schemas.role_assignment import (
    GroupRoleAssignmentRequest,
    GroupRoleAssignmentResponse,
)

router = APIRouter(prefix="/groups", tags=["groups"])


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_group(
    data: GroupCreate,
    group_repo: GroupRepository,
) -> GroupRead:
    existing = await group_repo.get_by_name(data.name)
    if existing:
        raise ConflictError(
            "Group with this name already exists",
            details={"name": data.name},
        )

    group = Group(
        name=data.name,
        description=data.description,
        metadata=data.metadata or {},
    )
    created = await group_repo.create(group)
    return GroupRead(
        id=str(created.id),
        name=created.name,
        description=created.description,
        is_active=created.is_active,
        created_at=created.created_at,
        updated_at=created.updated_at,
        metadata=created.metadata,
    )


@router.get("/{group_id}")
async def get_group(
    group_id: str,
    group_repo: GroupRepository,
) -> GroupRead:
    group = await group_repo.get_by_id(group_id)
    if not group:
        raise NotFoundError("Group not found", details={"group_id": group_id})

    return GroupRead(
        id=str(group.id),
        name=group.name,
        description=group.description,
        is_active=group.is_active,
        created_at=group.created_at,
        updated_at=group.updated_at,
        metadata=group.metadata,
    )


@router.patch("/{group_id}")
async def update_group(
    group_id: str,
    data: GroupUpdate,
    group_repo: GroupRepository,
) -> GroupRead:
    group = await group_repo.get_by_id(group_id)
    if not group:
        raise NotFoundError("Group not found", details={"group_id": group_id})

    if data.name is not None:
        group.name = data.name
    if data.description is not None:
        group.description = data.description
    if data.metadata is not None:
        group.metadata = data.metadata

    updated = await group_repo.update(group)
    return GroupRead(
        id=str(updated.id),
        name=updated.name,
        description=updated.description,
        is_active=updated.is_active,
        created_at=updated.created_at,
        updated_at=updated.updated_at,
        metadata=updated.metadata,
    )


@router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_group(
    group_id: str,
    group_repo: GroupRepository,
) -> None:
    success = await group_repo.deactivate(group_id)
    if not success:
        raise NotFoundError("Group not found", details={"group_id": group_id})


@router.get("")
async def list_groups(
    group_repo: GroupRepository,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> PaginatedResponse[GroupRead]:
    skip = (page - 1) * page_size
    groups = await group_repo.list_active(skip=skip, limit=page_size)

    items = [
        GroupRead(
            id=str(g.id),
            name=g.name,
            description=g.description,
            is_active=g.is_active,
            created_at=g.created_at,
            updated_at=g.updated_at,
            metadata=g.metadata,
        )
        for g in groups
    ]

    total = len(items) + skip
    return PaginatedResponse.create(items, total, page, page_size)


@router.post("/{group_id}/roles", status_code=status.HTTP_201_CREATED)
async def assign_role_to_group(
    group_id: str,
    data: GroupRoleAssignmentRequest,
    group_repo: GroupRepository,
    group_role_repo: GroupRoleRepository,
) -> GroupRoleAssignmentResponse:
    group = await group_repo.get_by_id(group_id)
    if not group:
        raise NotFoundError("Group not found", details={"group_id": group_id})

    from beanie import PydanticObjectId

    from osiki.models.base import Scope
    from osiki.models.group_role import GroupRole
    from osiki.schemas.scope import ScopeSchema

    scope = Scope(**(data.scope.model_dump() if data.scope else {}))
    group_role = GroupRole(
        group_id=PydanticObjectId(group_id),
        role_id=PydanticObjectId(data.role_id),
        scope=scope,
        assigned_by=data.assigned_by,
        expires_at=data.expires_at,
        assignment_reason=data.assignment_reason,
    )
    created = await group_role_repo.create(group_role)

    return GroupRoleAssignmentResponse(
        id=str(created.id),
        group_id=str(created.group_id),
        role_id=str(created.role_id),
        scope=ScopeSchema(**created.scope.model_dump()),
        assigned_by=created.assigned_by,
        assigned_at=created.assigned_at,
        expires_at=created.expires_at,
        assignment_reason=created.assignment_reason,
        is_active=created.is_active,
    )


@router.delete(
    "/{group_id}/roles/{role_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revoke_role_from_group(
    group_id: str,
    role_id: str,
    group_role_repo: GroupRoleRepository,
) -> None:
    assignment = await group_role_repo.find_assignment(group_id, role_id)
    if not assignment:
        raise NotFoundError(
            "Role assignment not found",
            details={"group_id": group_id, "role_id": role_id},
        )
    await group_role_repo.revoke(str(assignment.id))
