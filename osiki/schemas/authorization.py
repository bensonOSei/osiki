from pydantic import BaseModel, ConfigDict

from osiki.schemas.scope import ScopeSchema


class AuthorizationRequest(BaseModel):
    user_id: str
    resource: str
    action: str
    scope: ScopeSchema | None = None


class AuthorizationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    allowed: bool
    matched_permission: str | None = None
    matched_via: str | None = None
    denial_reason: str | None = None
    cache_hit: bool = False
