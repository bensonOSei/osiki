from typing import Any

from pydantic import BaseModel, ConfigDict


class UserCreate(BaseModel):
    external_id: str
    email: str | None = None
    metadata: dict[str, Any] | None = None


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    external_id: str
    email: str | None = None
    is_active: bool
    created_at: float
    updated_at: float
    metadata: dict[str, Any]


class UserUpdate(BaseModel):
    email: str | None = None
    metadata: dict[str, Any] | None = None
