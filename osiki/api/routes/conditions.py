from fastapi import APIRouter, Query, status

from osiki.api.dependencies import ConditionRepository, RoleRepository
from osiki.api.exceptions import ConflictError, NotFoundError, ValidationError
from osiki.decision.rules import RuleError, validate_rule
from osiki.models.condition import Condition
from osiki.schemas.base import PaginatedResponse
from osiki.schemas.condition import ConditionCreate, ConditionRead, ConditionUpdate

router = APIRouter(prefix="/conditions", tags=["conditions"])


def _to_read(c: Condition) -> ConditionRead:
    return ConditionRead(
        id=str(c.id),
        key=c.key,
        name=c.name,
        description=c.description,
        expression=c.expression,
        is_active=c.is_active,
        created_at=c.created_at,
        updated_at=c.updated_at,
    )


def _validate(expression: dict[str, object]) -> None:
    try:
        validate_rule(expression)
    except RuleError as e:
        raise ValidationError(
            "Invalid condition expression",
            details={"path": e.path, "message": e.message},
        ) from e


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_condition(
    data: ConditionCreate,
    condition_repo: ConditionRepository,
) -> ConditionRead:
    _validate(data.expression)
    if await condition_repo.get_by_key(data.key):
        raise ConflictError(
            "Condition with this key already exists", details={"key": data.key}
        )
    condition = Condition(
        key=data.key,
        name=data.name,
        description=data.description,
        expression=data.expression,
    )
    return _to_read(await condition_repo.create(condition))


@router.get("/{condition_id}")
async def get_condition(
    condition_id: str,
    condition_repo: ConditionRepository,
) -> ConditionRead:
    condition = await condition_repo.get_by_id(condition_id)
    if not condition:
        raise NotFoundError(
            "Condition not found", details={"condition_id": condition_id}
        )
    return _to_read(condition)


@router.patch("/{condition_id}")
async def update_condition(
    condition_id: str,
    data: ConditionUpdate,
    condition_repo: ConditionRepository,
) -> ConditionRead:
    condition = await condition_repo.get_by_id(condition_id)
    if not condition:
        raise NotFoundError(
            "Condition not found", details={"condition_id": condition_id}
        )

    if data.expression is not None:
        _validate(data.expression)
        condition.expression = data.expression
    if data.name is not None:
        condition.name = data.name
    if data.description is not None:
        condition.description = data.description

    return _to_read(await condition_repo.update(condition))


@router.delete("/{condition_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_condition(
    condition_id: str,
    condition_repo: ConditionRepository,
    role_repo: RoleRepository,
) -> None:
    if await role_repo.is_condition_in_use(condition_id):
        raise ConflictError(
            "Condition is in use", details={"condition_id": condition_id}
        )
    if not await condition_repo.deactivate(condition_id):
        raise NotFoundError(
            "Condition not found", details={"condition_id": condition_id}
        )


@router.get("")
async def list_conditions(
    condition_repo: ConditionRepository,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> PaginatedResponse[ConditionRead]:
    skip = (page - 1) * page_size
    conditions = await condition_repo.list_active(skip=skip, limit=page_size)
    items = [_to_read(c) for c in conditions]
    return PaginatedResponse.create(items, len(items) + skip, page, page_size)
