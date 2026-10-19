from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from osiki.schemas.scope import ScopeSchema


class AuthorizationRequest(BaseModel):
    user_id: str = Field(description="The user's external id.")
    resource: str
    action: str
    scope: ScopeSchema | None = None
    record: dict[str, Any] | None = Field(
        default=None,
        description="The record being accessed; conditional grants need it.",
    )


class AuthorizationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    allowed: bool
    matched_permission: str | None = None
    matched_via: str | None = None
    condition: str | None = None
    denial_reason: str | None = None
    cache_hit: bool = False


class FilterRequest(BaseModel):
    user_id: str = Field(description="The user's external id.")
    resource: str
    action: str
    scope: ScopeSchema | None = None
