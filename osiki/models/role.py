from beanie import Document, PydanticObjectId
from pymongo import IndexModel

from osiki.models.base import (
    EnvironmentMixin,
    MetadataMixin,
    SoftDeleteMixin,
    TimestampMixin,
)


class Role(Document, EnvironmentMixin, TimestampMixin, SoftDeleteMixin, MetadataMixin):
    name: str
    description: str | None = None
    parent_role_id: PydanticObjectId | None = None
    permission_ids: list[PydanticObjectId] = []
    is_system: bool = False

    class Settings:
        name = "roles"
        indexes = [
            IndexModel([("environment_id", 1), ("name", 1)], unique=True),
            IndexModel([("environment_id", 1), ("parent_role_id", 1)]),
            IndexModel([("environment_id", 1), ("permission_ids", 1)]),
            IndexModel([("environment_id", 1), ("is_active", 1), ("created_at", -1)]),
        ]
