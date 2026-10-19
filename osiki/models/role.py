from beanie import Document, PydanticObjectId
from pydantic import BaseModel
from pymongo import IndexModel

from osiki.models.base import (
    EnvironmentMixin,
    MetadataMixin,
    SoftDeleteMixin,
    TimestampMixin,
)


class Grant(BaseModel):
    """A permission held by a role, optionally narrowed by a condition."""

    permission_id: PydanticObjectId
    condition_id: PydanticObjectId | None = None


class Role(Document, EnvironmentMixin, TimestampMixin, SoftDeleteMixin, MetadataMixin):
    name: str
    description: str | None = None
    parent_role_id: PydanticObjectId | None = None
    grants: list[Grant] = []
    is_system: bool = False

    class Settings:
        name = "roles"
        indexes = [
            IndexModel([("environment_id", 1), ("name", 1)], unique=True),
            IndexModel([("environment_id", 1), ("parent_role_id", 1)]),
            IndexModel([("environment_id", 1), ("grants.permission_id", 1)]),
            IndexModel([("environment_id", 1), ("is_active", 1), ("created_at", -1)]),
        ]
