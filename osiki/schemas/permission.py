from typing import Any

from pydantic import BaseModel, ConfigDict, computed_field


class PermissionCreate(BaseModel):
    resource: str
    action: str
    description: str | None = None
    metadata: dict[str, Any] | None = None


class PermissionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    resource: str
    action: str
    description: str | None = None
    is_active: bool
    created_at: float
    metadata: dict[str, Any]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def permission_string(self) -> str:
        return f"{self.resource}:{self.action}"
