from beanie import Document, Indexed, PydanticObjectId
from pymongo import IndexModel

from osiki.models.base import MetadataMixin, SoftDeleteMixin, TimestampMixin


class Role(Document, TimestampMixin, SoftDeleteMixin, MetadataMixin):
    name: Indexed(str, unique=True)  # type: ignore[valid-type]
    description: str | None = None
    parent_role_id: Indexed(PydanticObjectId) | None = None  # type: ignore[valid-type]
    permission_ids: list[PydanticObjectId] = []
    is_system: bool = False

    class Settings:
        name = "roles"
        indexes = [
            IndexModel([("permission_ids", 1)]),
            IndexModel([("is_active", 1), ("created_at", -1)]),
        ]
