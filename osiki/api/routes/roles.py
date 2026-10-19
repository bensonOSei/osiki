from beanie import PydanticObjectId
from fastapi import APIRouter, Query, status

from osiki.api.dependencies import (
    ConditionRepository,
    PermissionRepository,
    RoleRepository,
)
from osiki.api.exceptions import ConflictError, NotFoundError, ValidationError
from osiki.models.role import Grant, Role
from osiki.schemas.base import PaginatedResponse
from osiki.schemas.role import GrantSchema, RoleCreate, RoleRead, RoleUpdate
from osiki.services.builtins import BUILTIN_TEAM_MANAGE, is_owner_template

router = APIRouter(prefix="/roles", tags=["roles"])


def _to_read(role: Role) -> RoleRead:
    return RoleRead(
        id=str(role.id),
        name=role.name,
        description=role.description,
        parent_role_id=str(role.parent_role_id) if role.parent_role_id else None,
        grants=[
            GrantSchema(
                permission_id=str(g.permission_id),
                condition_id=str(g.condition_id) if g.condition_id else None,
            )
            for g in role.grants
        ],
        is_system=role.is_system,
        is_template=role.is_template,
        tenant_id=role.tenant_id,
        copied_from=str(role.copied_from) if role.copied_from else None,
        is_active=role.is_active,
        created_at=role.created_at,
        updated_at=role.updated_at,
        metadata=role.metadata,
    )


async def _get_project_role(role_id: str, role_repo: RoleRepository) -> Role:
    """A project role by id; tenant-owned roles do not exist for this API."""
    role = await role_repo.get_by_id(role_id)
    if role is None or role.tenant_id is not None:
        raise NotFoundError("Role not found", details={"role_id": role_id})
    return role


def _merge_grants(
    grants: list[GrantSchema] | None, permission_ids: list[str] | None
) -> list[GrantSchema]:
    """Merge shorthand permission ids with explicit grants, deduplicated."""
    merged = [GrantSchema(permission_id=pid) for pid in (permission_ids or [])]
    merged.extend(grants or [])
    seen: set[tuple[str, str | None]] = set()
    unique: list[GrantSchema] = []
    for grant in merged:
        key = (grant.permission_id, grant.condition_id)
        if key not in seen:
            seen.add(key)
            unique.append(grant)
    return unique


def _check_object_id(value: str, field: str) -> None:
    if not PydanticObjectId.is_valid(value):
        raise ValidationError(f"Invalid {field}: {value}", details={field: value})


async def _validate_references(
    grants: list[GrantSchema],
    parent_role_id: str | None,
    role_repo: RoleRepository,
    permission_repo: PermissionRepository,
    condition_repo: ConditionRepository,
) -> None:
    """Every permission, condition and parent must exist in this environment."""
    for grant in grants:
        _check_object_id(grant.permission_id, "permission_id")
        if await permission_repo.get_by_id(grant.permission_id) is None:
            raise ValidationError(
                f"Permission not found: {grant.permission_id}",
                details={"permission_id": grant.permission_id},
            )
        if grant.condition_id is not None:
            _check_object_id(grant.condition_id, "condition_id")
            condition = await condition_repo.get_by_id(grant.condition_id)
            if condition is None or not condition.is_active:
                raise ValidationError(
                    f"Condition not found: {grant.condition_id}",
                    details={"condition_id": grant.condition_id},
                )
    if parent_role_id is not None:
        _check_object_id(parent_role_id, "parent_role_id")
        parent = await role_repo.get_by_id(parent_role_id)
        if parent is None or parent.tenant_id is not None:
            raise ValidationError(
                f"Parent role not found: {parent_role_id}",
                details={"parent_role_id": parent_role_id},
            )


async def _reject_parent_cycle(
    role_id: str, parent_role_id: str, role_repo: RoleRepository
) -> None:
    """Refuse a parent whose ancestor chain reaches the role (incl. itself)."""
    visited: set[str] = set()
    current: str | None = parent_role_id
    while current is not None and current not in visited:
        if current == role_id:
            raise ValidationError(
                f"Parent role would create a cycle: {parent_role_id}",
                details={"parent_role_id": parent_role_id},
            )
        visited.add(current)
        ancestor = await role_repo.get_by_id(current)
        current = (
            str(ancestor.parent_role_id)
            if ancestor is not None and ancestor.parent_role_id
            else None
        )


def _to_grants(grants: list[GrantSchema]) -> list[Grant]:
    return [
        Grant(
            permission_id=PydanticObjectId(g.permission_id),
            condition_id=PydanticObjectId(g.condition_id) if g.condition_id else None,
        )
        for g in grants
    ]


async def _protect_owner_template(
    role: Role,
    data: RoleUpdate,
    new_grants: list[GrantSchema] | None,
    permission_repo: PermissionRepository,
) -> None:
    """The seeded Owner template stays editable, but bootstrap must keep
    finding it and it must keep granting osiki.team:manage."""
    if data.name is not None and data.name != role.name:
        raise ValidationError(
            "The built-in Owner template cannot be renamed",
            details={"role_id": str(role.id)},
        )
    if data.is_template is not None and data.is_template != role.is_template:
        raise ValidationError(
            "The built-in Owner template must stay a template",
            details={"role_id": str(role.id)},
        )
    if new_grants is None:
        return
    manage = await permission_repo.get_by_resource_action(*BUILTIN_TEAM_MANAGE)
    manage_id = str(manage.id) if manage is not None else None
    if not any(
        g.permission_id == manage_id and g.condition_id is None for g in new_grants
    ):
        raise ValidationError(
            "The built-in Owner template must keep granting osiki.team:manage",
            details={"role_id": str(role.id)},
        )


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_role(
    data: RoleCreate,
    role_repo: RoleRepository,
    permission_repo: PermissionRepository,
    condition_repo: ConditionRepository,
) -> RoleRead:
    existing = await role_repo.get_by_name(data.name)
    if existing:
        raise ConflictError(
            "Role with this name already exists",
            details={"name": data.name},
        )

    grants = _merge_grants(data.grants, data.permission_ids)
    await _validate_references(
        grants, data.parent_role_id, role_repo, permission_repo, condition_repo
    )

    role = Role(
        name=data.name,
        description=data.description,
        parent_role_id=(
            PydanticObjectId(data.parent_role_id) if data.parent_role_id else None
        ),
        grants=_to_grants(grants),
        is_system=data.is_system,
        is_template=data.is_template,
        metadata=data.metadata or {},
    )
    return _to_read(await role_repo.create(role))


@router.get("/{role_id}")
async def get_role(
    role_id: str,
    role_repo: RoleRepository,
) -> RoleRead:
    return _to_read(await _get_project_role(role_id, role_repo))


@router.patch("/{role_id}")
async def update_role(
    role_id: str,
    data: RoleUpdate,
    role_repo: RoleRepository,
    permission_repo: PermissionRepository,
    condition_repo: ConditionRepository,
) -> RoleRead:
    role = await _get_project_role(role_id, role_repo)

    replace_grants = data.grants is not None or data.permission_ids is not None
    grants = _merge_grants(data.grants, data.permission_ids)
    await _validate_references(
        grants, data.parent_role_id, role_repo, permission_repo, condition_repo
    )

    if data.parent_role_id is not None:
        await _reject_parent_cycle(role_id, data.parent_role_id, role_repo)

    if is_owner_template(role):
        await _protect_owner_template(
            role, data, grants if replace_grants else None, permission_repo
        )

    if data.name is not None:
        role.name = data.name
    if data.description is not None:
        role.description = data.description
    if data.parent_role_id is not None:
        role.parent_role_id = PydanticObjectId(data.parent_role_id)
    if replace_grants:
        role.grants = _to_grants(grants)
    if data.is_template is not None:
        role.is_template = data.is_template
    if data.metadata is not None:
        role.metadata = data.metadata

    return _to_read(await role_repo.update(role))


@router.delete("/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_role(
    role_id: str,
    role_repo: RoleRepository,
) -> None:
    await _get_project_role(role_id, role_repo)
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

    items = [_to_read(r) for r in roles]

    total = len(items) + skip
    return PaginatedResponse.create(items, total, page, page_size)
