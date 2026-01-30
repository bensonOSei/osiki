from osiki.schemas.authorization import AuthorizationRequest, AuthorizationResponse
from osiki.schemas.base import PaginatedResponse, TimestampSchema
from osiki.schemas.group import GroupCreate, GroupRead, GroupUpdate
from osiki.schemas.permission import PermissionCreate, PermissionRead
from osiki.schemas.role import RoleCreate, RoleRead, RoleUpdate
from osiki.schemas.role_assignment import (
    GroupRoleAssignmentRequest,
    GroupRoleAssignmentResponse,
    UserGroupRequest,
    UserGroupResponse,
    UserRoleAssignmentRequest,
    UserRoleAssignmentResponse,
)
from osiki.schemas.scope import ScopeSchema
from osiki.schemas.user import UserCreate, UserRead, UserUpdate

__all__ = [
    # Base
    "PaginatedResponse",
    "TimestampSchema",
    # Scope
    "ScopeSchema",
    # User
    "UserCreate",
    "UserRead",
    "UserUpdate",
    # Group
    "GroupCreate",
    "GroupRead",
    "GroupUpdate",
    # Role
    "RoleCreate",
    "RoleRead",
    "RoleUpdate",
    # Permission
    "PermissionCreate",
    "PermissionRead",
    # Role Assignment
    "UserRoleAssignmentRequest",
    "UserRoleAssignmentResponse",
    "GroupRoleAssignmentRequest",
    "GroupRoleAssignmentResponse",
    "UserGroupRequest",
    "UserGroupResponse",
    # Authorization
    "AuthorizationRequest",
    "AuthorizationResponse",
]
