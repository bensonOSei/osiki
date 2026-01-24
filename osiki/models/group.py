from beanie import Document, Indexed
from pymongo import IndexModel

from osiki.models.base import MetadataMixin, SoftDeleteMixin, TimestampMixin


class Group(Document, TimestampMixin, SoftDeleteMixin, MetadataMixin):
    name: Indexed(str, unique=True)  # type: ignore[valid-type]
    description: str | None = None

    class Settings:
        name = "groups"
        indexes = [
            IndexModel([("is_active", 1), ("created_at", -1)]),
        ]
