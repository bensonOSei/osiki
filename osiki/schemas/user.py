from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from osiki.models.base import AttributeValue


class UserCreate(BaseModel):
    external_id: str
    email: str | None = None
    metadata: dict[str, Any] | None = None


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    external_id: str
    name: str | None = None
    email: str | None = None
    attributes: dict[str, AttributeValue] = Field(default_factory=dict)
    is_active: bool
    created_at: float
    updated_at: float
    metadata: dict[str, Any]


class UserUpdate(BaseModel):
    email: str | None = None
    metadata: dict[str, Any] | None = None


class UserUpsert(BaseModel):
    name: str | None = None
    email: str | None = None
    attributes: dict[str, AttributeValue] | None = None
