from typing import Any

from beanie import Document
from pymongo import IndexModel

from osiki.models.base import EnvironmentMixin, SoftDeleteMixin, TimestampMixin

CONDITION_KEY_PATTERN = r"^[a-z][a-z0-9_]{0,62}$"


class Condition(Document, EnvironmentMixin, TimestampMixin, SoftDeleteMixin):
    key: str
    name: str
    description: str | None = None
    expression: dict[str, Any]

    class Settings:
        name = "conditions"
        indexes = [
            IndexModel([("environment_id", 1), ("key", 1)], unique=True),
            IndexModel([("environment_id", 1), ("is_active", 1)]),
        ]
