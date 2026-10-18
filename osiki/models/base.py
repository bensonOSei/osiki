import time
from typing import Any

from pydantic import BaseModel, Field


class TimestampMixin(BaseModel):
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)


class EnvironmentMixin(BaseModel):
    environment_id: str = "default"


class SoftDeleteMixin(BaseModel):
    is_active: bool = True


class MetadataMixin(BaseModel):
    metadata: dict[str, Any] = Field(default_factory=dict)


class Scope(BaseModel):
    model_config = {"extra": "allow"}

    tenant_id: str | None = None
    region: str | None = None
    branch_id: str | None = None
    department: str | None = None

    def to_dict(self) -> dict[str, str]:
        return {k: v for k, v in self.model_dump().items() if v is not None}
