from typing import Any

from pydantic import BaseModel, Field

from osiki.models.condition import CONDITION_KEY_PATTERN


class ConditionCreate(BaseModel):
    key: str = Field(pattern=CONDITION_KEY_PATTERN)
    name: str
    description: str | None = None
    expression: dict[str, Any]


class ConditionRead(BaseModel):
    id: str
    key: str
    name: str
    description: str | None = None
    expression: dict[str, Any]
    is_active: bool
    created_at: float
    updated_at: float


class ConditionUpdate(BaseModel):
    """`key` is immutable: it is not a field here, so a supplied one is ignored."""

    name: str | None = None
    description: str | None = None
    expression: dict[str, Any] | None = None
