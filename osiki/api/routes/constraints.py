from beanie import PydanticObjectId
from fastapi import APIRouter, Query, status

from osiki.api.dependencies import ConstraintRepository, RoleRepository
from osiki.api.exceptions import NotFoundError, ValidationError
from osiki.models.constraint import (
    Constraint,
    ConstraintConfig,
    ConstraintType,
    ScopeLevel,
)
from osiki.schemas.base import PaginatedResponse
from osiki.schemas.constraint import (
    ConstraintConfigSchema,
    ConstraintCreate,
    ConstraintRead,
    ConstraintUpdate,
)

router = APIRouter(prefix="/constraints", tags=["constraints"])


def _to_read(c: Constraint) -> ConstraintRead:
    return ConstraintRead(
        id=str(c.id),
        name=c.name,
        description=c.description,
        type=c.type.value,
        config={
            "role_ids": (
                [str(rid) for rid in c.config.role_ids] if c.config.role_ids else None
            ),
            "role_id": str(c.config.role_id) if c.config.role_id else None,
            "max_assignments": c.config.max_assignments,
            "scope_level": c.config.scope_level.value if c.config.scope_level else None,
            "requires_role_id": (
                str(c.config.requires_role_id) if c.config.requires_role_id else None
            ),
        },
        is_active=c.is_active,
        created_at=c.created_at,
        updated_at=c.updated_at,
    )


def _build_config(cfg: ConstraintConfigSchema) -> ConstraintConfig:
    return ConstraintConfig(
        role_ids=(
            [PydanticObjectId(rid) for rid in cfg.role_ids] if cfg.role_ids else None
        ),
        role_id=PydanticObjectId(cfg.role_id) if cfg.role_id else None,
        max_assignments=cfg.max_assignments,
        scope_level=ScopeLevel(cfg.scope_level) if cfg.scope_level else None,
        requires_role_id=(
            PydanticObjectId(cfg.requires_role_id) if cfg.requires_role_id else None
        ),
    )


async def _require_project_roles(
    config: ConstraintConfig, role_repo: RoleRepository
) -> None:
    """Constraints target project roles and templates, never a tenant's own."""
    ids = [*(config.role_ids or []), config.role_id, config.requires_role_id]
    for role_id in filter(None, ids):
        role = await role_repo.get_by_id(str(role_id))
        if role is not None and role.tenant_id is not None:
            raise ValidationError(
                "Constraints cannot target a tenant role",
                details={"role_id": str(role_id)},
            )


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_constraint(
    data: ConstraintCreate,
    constraint_repo: ConstraintRepository,
    role_repo: RoleRepository,
) -> ConstraintRead:
    config = _build_config(data.config)
    await _require_project_roles(config, role_repo)

    constraint = Constraint(
        name=data.name,
        description=data.description,
        type=ConstraintType(data.type),
        config=config,
    )
    created = await constraint_repo.create(constraint)
    return _to_read(created)


@router.get("/{constraint_id}")
async def get_constraint(
    constraint_id: str,
    constraint_repo: ConstraintRepository,
) -> ConstraintRead:
    constraint = await constraint_repo.get_by_id(constraint_id)
    if not constraint:
        raise NotFoundError(
            "Constraint not found", details={"constraint_id": constraint_id}
        )
    return _to_read(constraint)


@router.patch("/{constraint_id}")
async def update_constraint(
    constraint_id: str,
    data: ConstraintUpdate,
    constraint_repo: ConstraintRepository,
    role_repo: RoleRepository,
) -> ConstraintRead:
    constraint = await constraint_repo.get_by_id(constraint_id)
    if not constraint:
        raise NotFoundError(
            "Constraint not found", details={"constraint_id": constraint_id}
        )

    if data.name is not None:
        constraint.name = data.name
    if data.description is not None:
        constraint.description = data.description
    if data.config is not None:
        config = _build_config(data.config)
        await _require_project_roles(config, role_repo)
        constraint.config = config

    updated = await constraint_repo.update(constraint)
    return _to_read(updated)


@router.delete("/{constraint_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_constraint(
    constraint_id: str,
    constraint_repo: ConstraintRepository,
) -> None:
    success = await constraint_repo.deactivate(constraint_id)
    if not success:
        raise NotFoundError(
            "Constraint not found", details={"constraint_id": constraint_id}
        )


@router.get("")
async def list_constraints(
    constraint_repo: ConstraintRepository,
    type: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> PaginatedResponse[ConstraintRead]:
    if type:
        constraints = await constraint_repo.get_by_type(ConstraintType(type))
    else:
        constraints = await constraint_repo.get_active()

    total = len(constraints)
    skip = (page - 1) * page_size
    page_items = constraints[skip : skip + page_size]
    items = [_to_read(c) for c in page_items]

    return PaginatedResponse.create(items, total, page, page_size)
