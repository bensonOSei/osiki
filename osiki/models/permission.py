import time

from beanie import Document
from pydantic import Field
from pymongo import IndexModel

from osiki.models.base import MetadataMixin, SoftDeleteMixin


class Permission(Document, SoftDeleteMixin, MetadataMixin):
    resource: str
    action: str
    description: str | None = None
    created_at: float = Field(default_factory=time.time)

    class Settings:
        name = "permissions"
        indexes = [
            IndexModel([("resource", 1), ("action", 1)], unique=True),
            IndexModel([("resource", 1)]),
            IndexModel([("is_active", 1)]),
        ]

    @property
    def permission_string(self) -> str:
        return f"{self.resource}:{self.action}"
