from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field

from osiki.models.permission import Permission

# One segment of "resource:action": non-empty and colon-free, so the string
# splits back unambiguously. "*" (wildcard) is allowed.
PermissionPart = Annotated[str, Field(min_length=1, pattern=r"^[^:]+$")]


class PermissionCreate(BaseModel):
    resource: PermissionPart
    action: PermissionPart
    description: str | None = None
    metadata: dict[str, Any] | None = None


class PermissionUpdate(BaseModel):
    assignable: bool | None = None
    description: str | None = None


class PermissionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    resource: str
    action: str
    description: str | None = None
    assignable: bool
    is_active: bool
    created_at: float
    metadata: dict[str, Any]

    @classmethod
    def from_model(cls, permission: Permission) -> "PermissionRead":
        return cls(
            id=str(permission.id),
            resource=permission.resource,
            action=permission.action,
            description=permission.description,
            assignable=permission.assignable,
            is_active=permission.is_active,
            created_at=permission.created_at,
            metadata=permission.metadata,
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def permission_string(self) -> str:
        return f"{self.resource}:{self.action}"


class EffectiveGrantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    permission: str
    condition: str | None = None
    via: Literal["direct", "group"]
