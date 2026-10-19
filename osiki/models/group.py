from beanie import Document
from pymongo import IndexModel

from osiki.models.base import (
    EnvironmentMixin,
    MetadataMixin,
    SoftDeleteMixin,
    TimestampMixin,
)


class Group(Document, EnvironmentMixin, TimestampMixin, SoftDeleteMixin, MetadataMixin):
    name: str
    description: str | None = None

    class Settings:
        name = "groups"
        indexes = [
            IndexModel([("environment_id", 1), ("name", 1)], unique=True),
            IndexModel([("environment_id", 1), ("is_active", 1), ("created_at", -1)]),
        ]
