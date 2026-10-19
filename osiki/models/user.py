from beanie import Document
from pydantic import Field
from pymongo import IndexModel

from osiki.models.base import (
    AttributeValue,
    EnvironmentMixin,
    MetadataMixin,
    SoftDeleteMixin,
    TimestampMixin,
)


class User(Document, EnvironmentMixin, TimestampMixin, SoftDeleteMixin, MetadataMixin):
    external_id: str
    name: str | None = None
    email: str | None = None
    attributes: dict[str, AttributeValue] = Field(default_factory=dict)

    class Settings:
        name = "users"
        indexes = [
            IndexModel([("environment_id", 1), ("external_id", 1)], unique=True),
            IndexModel(
                [("environment_id", 1), ("email", 1)],
                unique=True,
                partialFilterExpression={"email": {"$type": "string"}},
            ),
            IndexModel([("environment_id", 1), ("is_active", 1), ("created_at", -1)]),
        ]
