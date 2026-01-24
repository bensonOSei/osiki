import time

from beanie import Document, PydanticObjectId
from pydantic import Field
from pymongo import IndexModel

from osiki.models.base import SoftDeleteMixin, TimestampMixin


class UserGroup(Document, TimestampMixin, SoftDeleteMixin):
    user_id: PydanticObjectId
    group_id: PydanticObjectId
    added_by: str
    added_at: float = Field(default_factory=time.time)
    membership_type: str | None = None

    class Settings:
        name = "user_groups"
        indexes = [
            IndexModel(
                [("user_id", 1), ("group_id", 1), ("is_active", 1)],
                unique=True,
                sparse=True,
            ),
            IndexModel([("user_id", 1), ("is_active", 1)]),
            IndexModel([("group_id", 1), ("is_active", 1)]),
        ]
