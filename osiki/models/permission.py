import time

from beanie import Document
from pydantic import Field
from pymongo import IndexModel

from osiki.models.base import EnvironmentMixin, MetadataMixin, SoftDeleteMixin


class Permission(Document, EnvironmentMixin, SoftDeleteMixin, MetadataMixin):
    resource: str
    action: str
    description: str | None = None
    created_at: float = Field(default_factory=time.time)

    class Settings:
        name = "permissions"
        indexes = [
            IndexModel(
                [("environment_id", 1), ("resource", 1), ("action", 1)], unique=True
            ),
            IndexModel([("environment_id", 1), ("resource", 1)]),
            IndexModel([("environment_id", 1), ("is_active", 1)]),
        ]

    @property
    def permission_string(self) -> str:
        return f"{self.resource}:{self.action}"
