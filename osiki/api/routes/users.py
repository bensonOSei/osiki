from fastapi import APIRouter, Query, status

from osiki.api.dependencies import (
    UserGroupRepository,
    UserRepository,
    UserRoleRepository,
)
from osiki.api.exceptions import ConflictError, NotFoundError
from osiki.models.user import User
from osiki.schemas.base import PaginatedResponse
from osiki.schemas.role_assignment import (
    UserGroupRequest,
    UserGroupResponse,
    UserRoleAssignmentRequest,
    UserRoleAssignmentResponse,
)
from osiki.schemas.user import UserCreate, UserRead, UserUpdate

router = APIRouter(prefix="/users", tags=["users"])


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_user(
    data: UserCreate,
    user_repo: UserRepository,
) -> UserRead:
    existing = await user_repo.get_by_external_id(data.external_id)
    if existing:
        raise ConflictError(
            "User with this external_id already exists",
            details={"external_id": data.external_id},
        )

    user = User(
        external_id=data.external_id,
        email=data.email,
        metadata=data.metadata or {},
    )
    created = await user_repo.create(user)
    return UserRead(
        id=str(created.id),
        external_id=created.external_id,
        email=created.email,
        is_active=created.is_active,
        created_at=created.created_at,
        updated_at=created.updated_at,
        metadata=created.metadata,
    )


@router.get("/{user_id}")
async def get_user(
    user_id: str,
    user_repo: UserRepository,
) -> UserRead:
    user = await user_repo.get_by_id(user_id)
    if not user:
        raise NotFoundError("User not found", details={"user_id": user_id})

    return UserRead(
        id=str(user.id),
        external_id=user.external_id,
        email=user.email,
        is_active=user.is_active,
        created_at=user.created_at,
        updated_at=user.updated_at,
        metadata=user.metadata,
    )


@router.patch("/{user_id}")
async def update_user(
    user_id: str,
    data: UserUpdate,
    user_repo: UserRepository,
) -> UserRead:
    user = await user_repo.get_by_id(user_id)
    if not user:
        raise NotFoundError("User not found", details={"user_id": user_id})

    if data.email is not None:
        user.email = data.email
    if data.metadata is not None:
        user.metadata = data.metadata

    updated = await user_repo.update(user)
    return UserRead(
        id=str(updated.id),
        external_id=updated.external_id,
        email=updated.email,
        is_active=updated.is_active,
        created_at=updated.created_at,
        updated_at=updated.updated_at,
        metadata=updated.metadata,
    )


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: str,
    user_repo: UserRepository,
) -> None:
    success = await user_repo.deactivate(user_id)
    if not success:
        raise NotFoundError("User not found", details={"user_id": user_id})


@router.get("")
async def list_users(
    user_repo: UserRepository,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> PaginatedResponse[UserRead]:
    skip = (page - 1) * page_size
    users = await user_repo.list_active(skip=skip, limit=page_size)

    items = [
        UserRead(
            id=str(u.id),
            external_id=u.external_id,
            email=u.email,
            is_active=u.is_active,
            created_at=u.created_at,
            updated_at=u.updated_at,
            metadata=u.metadata,
        )
        for u in users
    ]

    # Note: For proper pagination, we'd need a count method on the repository
    # For now, estimate based on returned results
    total = len(items) + skip
    return PaginatedResponse.create(items, total, page, page_size)


@router.post("/{user_id}/roles", status_code=status.HTTP_201_CREATED)
async def assign_role_to_user(
    user_id: str,
    data: UserRoleAssignmentRequest,
    user_repo: UserRepository,
    user_role_repo: UserRoleRepository,
) -> UserRoleAssignmentResponse:
    user = await user_repo.get_by_id(user_id)
    if not user:
        raise NotFoundError("User not found", details={"user_id": user_id})

    from beanie import PydanticObjectId

    from osiki.models.base import Scope
    from osiki.models.user_role import UserRole
    from osiki.schemas.scope import ScopeSchema

    scope = Scope(**(data.scope.model_dump() if data.scope else {}))
    user_role = UserRole(
        user_id=PydanticObjectId(user_id),
        role_id=PydanticObjectId(data.role_id),
        scope=scope,
        assigned_by=data.assigned_by,
        expires_at=data.expires_at,
        assignment_reason=data.assignment_reason,
    )
    created = await user_role_repo.create(user_role)

    return UserRoleAssignmentResponse(
        id=str(created.id),
        user_id=str(created.user_id),
        role_id=str(created.role_id),
        scope=ScopeSchema(**created.scope.model_dump()),
        assigned_by=created.assigned_by,
        assigned_at=created.assigned_at,
        expires_at=created.expires_at,
        assignment_reason=created.assignment_reason,
        is_active=created.is_active,
    )


@router.delete(
    "/{user_id}/roles/{role_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revoke_role_from_user(
    user_id: str,
    role_id: str,
    user_role_repo: UserRoleRepository,
) -> None:
    assignment = await user_role_repo.find_assignment(user_id, role_id)
    if not assignment:
        raise NotFoundError(
            "Role assignment not found",
            details={"user_id": user_id, "role_id": role_id},
        )
    await user_role_repo.revoke(str(assignment.id))


@router.post("/{user_id}/groups", status_code=status.HTTP_201_CREATED)
async def add_user_to_group(
    user_id: str,
    data: UserGroupRequest,
    user_repo: UserRepository,
    user_group_repo: UserGroupRepository,
) -> UserGroupResponse:
    user = await user_repo.get_by_id(user_id)
    if not user:
        raise NotFoundError("User not found", details={"user_id": user_id})

    from beanie import PydanticObjectId

    from osiki.models.user_group import UserGroup

    user_group = UserGroup(
        user_id=PydanticObjectId(user_id),
        group_id=PydanticObjectId(data.group_id),
        added_by=data.added_by,
        membership_type=data.membership_type,
    )
    created = await user_group_repo.create(user_group)

    return UserGroupResponse(
        id=str(created.id),
        user_id=str(created.user_id),
        group_id=str(created.group_id),
        added_by=created.added_by,
        added_at=created.added_at,
        membership_type=created.membership_type,
        is_active=created.is_active,
    )


@router.delete(
    "/{user_id}/groups/{group_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_user_from_group(
    user_id: str,
    group_id: str,
    user_group_repo: UserGroupRepository,
) -> None:
    membership = await user_group_repo.find_membership(user_id, group_id)
    if not membership:
        raise NotFoundError(
            "Group membership not found",
            details={"user_id": user_id, "group_id": group_id},
        )
    await user_group_repo.remove(str(membership.id))
