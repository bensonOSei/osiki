import time

from beanie import Document, PydanticObjectId
from pydantic import Field
from pymongo import IndexModel

from osiki.models.base import EnvironmentMixin, SoftDeleteMixin, TimestampMixin


class UserGroup(Document, EnvironmentMixin, TimestampMixin, SoftDeleteMixin):
    user_id: PydanticObjectId
    group_id: PydanticObjectId
    added_by: str
    added_at: float = Field(default_factory=time.time)
    membership_type: str | None = None

    class Settings:
        name = "user_groups"
        indexes = [
            IndexModel(
                [
                    ("environment_id", 1),
                    ("user_id", 1),
                    ("group_id", 1),
                ],
                unique=True,
                # Only active rows are unique: removed rows may pile up.
                partialFilterExpression={"is_active": True},
            ),
            IndexModel([("environment_id", 1), ("user_id", 1), ("is_active", 1)]),
            IndexModel([("environment_id", 1), ("group_id", 1), ("is_active", 1)]),
        ]
