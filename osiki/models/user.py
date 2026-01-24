from beanie import Document, Indexed
from pymongo import IndexModel

from osiki.models.base import MetadataMixin, SoftDeleteMixin, TimestampMixin


class User(Document, TimestampMixin, SoftDeleteMixin, MetadataMixin):
    external_id: Indexed(str, unique=True)  # type: ignore[valid-type]
    email: Indexed(str, unique=True, sparse=True) | None = None  # type: ignore[valid-type]

    class Settings:
        name = "users"
        indexes = [
            IndexModel([("is_active", 1), ("created_at", -1)]),
        ]
