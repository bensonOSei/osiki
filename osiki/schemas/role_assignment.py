from pydantic import BaseModel, ConfigDict

from osiki.schemas.scope import ScopeSchema


class UserRoleAssignmentRequest(BaseModel):
    role_id: str
    scope: ScopeSchema | None = None
    assigned_by: str
    expires_at: float | None = None
    assignment_reason: str | None = None


class UserRoleAssignmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    role_id: str
    scope: ScopeSchema
    assigned_by: str
    assigned_at: float
    expires_at: float | None = None
    assignment_reason: str | None = None
    is_active: bool


class GroupRoleAssignmentRequest(BaseModel):
    role_id: str
    scope: ScopeSchema | None = None
    assigned_by: str
    expires_at: float | None = None
    assignment_reason: str | None = None


class GroupRoleAssignmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    group_id: str
    role_id: str
    scope: ScopeSchema
    assigned_by: str
    assigned_at: float
    expires_at: float | None = None
    assignment_reason: str | None = None
    is_active: bool


class UserGroupRequest(BaseModel):
    group_id: str
    added_by: str
    membership_type: str | None = None


class UserGroupResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    group_id: str
    added_by: str
    added_at: float
    membership_type: str | None = None
    is_active: bool
