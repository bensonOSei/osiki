from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field

# One segment of "resource:action": non-empty and colon-free, so the string
# splits back unambiguously. "*" (wildcard) is allowed.
PermissionPart = Annotated[str, Field(min_length=1, pattern=r"^[^:]+$")]


class PermissionCreate(BaseModel):
    resource: PermissionPart
    action: PermissionPart
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


class EffectiveGrantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    permission: str
    condition: str | None = None
    via: Literal["direct", "group"]
