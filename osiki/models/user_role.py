import time

from beanie import Document, PydanticObjectId
from pydantic import Field
from pymongo import IndexModel

from osiki.models.base import Scope, SoftDeleteMixin, TimestampMixin


class UserRole(Document, TimestampMixin, SoftDeleteMixin):
    user_id: PydanticObjectId
    role_id: PydanticObjectId
    scope: Scope = Field(default_factory=Scope)
    assigned_by: str
    assigned_at: float = Field(default_factory=time.time)
    expires_at: float | None = None
    assignment_reason: str | None = None

    class Settings:
        name = "user_roles"
        indexes = [
            IndexModel(
                [
                    ("user_id", 1),
                    ("role_id", 1),
                    ("scope.tenant_id", 1),
                    ("is_active", 1),
                ],
                unique=True,
                sparse=True,
            ),
            IndexModel([("user_id", 1), ("is_active", 1)]),
            IndexModel([("role_id", 1), ("is_active", 1)]),
            IndexModel([("scope.tenant_id", 1), ("role_id", 1), ("is_active", 1)]),
            IndexModel([("expires_at", 1)], sparse=True),
        ]
