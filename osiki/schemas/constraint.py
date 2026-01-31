from pydantic import BaseModel, ConfigDict


class ConstraintConfigSchema(BaseModel):
    role_ids: list[str] | None = None
    role_id: str | None = None
    max_assignments: int | None = None
    scope_level: str | None = None
    requires_role_id: str | None = None


class ConstraintCreate(BaseModel):
    name: str
    description: str | None = None
    type: str
    config: ConstraintConfigSchema


class ConstraintRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str | None = None
    type: str
    config: ConstraintConfigSchema
    is_active: bool
    created_at: float
    updated_at: float


class ConstraintUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    config: ConstraintConfigSchema | None = None
