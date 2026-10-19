from beanie import Document
from pydantic import Field
from pymongo import IndexModel

from osiki.models.base import (
    AttributeValue,
    EnvironmentMixin,
    SoftDeleteMixin,
    TimestampMixin,
)


class Tenant(Document, EnvironmentMixin, TimestampMixin, SoftDeleteMixin):
    external_id: str
    name: str
    attributes: dict[str, AttributeValue] = Field(default_factory=dict)

    class Settings:
        name = "tenants"
        indexes = [
            IndexModel([("environment_id", 1), ("external_id", 1)], unique=True),
        ]
