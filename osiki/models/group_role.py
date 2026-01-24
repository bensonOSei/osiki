import time

from beanie import Document, PydanticObjectId
from pydantic import Field
from pymongo import IndexModel

from osiki.models.base import Scope, SoftDeleteMixin, TimestampMixin


class GroupRole(Document, TimestampMixin, SoftDeleteMixin):
    group_id: PydanticObjectId
    role_id: PydanticObjectId
    scope: Scope = Field(default_factory=Scope)
    assigned_by: str
    assigned_at: float = Field(default_factory=time.time)
    expires_at: float | None = None
    assignment_reason: str | None = None

    class Settings:
        name = "group_roles"
        indexes = [
            IndexModel(
                [
                    ("group_id", 1),
                    ("role_id", 1),
                    ("scope.tenant_id", 1),
                    ("is_active", 1),
                ],
                unique=True,
                sparse=True,
            ),
            IndexModel([("group_id", 1), ("is_active", 1)]),
            IndexModel([("role_id", 1), ("is_active", 1)]),
        ]
