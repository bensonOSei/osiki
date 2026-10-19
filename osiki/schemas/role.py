from typing import Any

from pydantic import BaseModel, ConfigDict


class GrantSchema(BaseModel):
    permission_id: str
    condition_id: str | None = None


class RoleCreate(BaseModel):
    name: str
    description: str | None = None
    parent_role_id: str | None = None
    grants: list[GrantSchema] | None = None
    # Shorthand for unconditional grants; merged with `grants`.
    permission_ids: list[str] | None = None
    is_system: bool = False
    metadata: dict[str, Any] | None = None


class RoleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str | None = None
    parent_role_id: str | None = None
    grants: list[GrantSchema]
    is_system: bool
    is_active: bool
    created_at: float
    updated_at: float
    metadata: dict[str, Any]


class RoleUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    parent_role_id: str | None = None
    grants: list[GrantSchema] | None = None
    permission_ids: list[str] | None = None
    metadata: dict[str, Any] | None = None
