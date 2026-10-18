import time
from typing import Any

from beanie import Document
from pydantic import BaseModel, Field
from pymongo import DESCENDING, IndexModel

from osiki.models.base import EnvironmentMixin


class AuditContext(BaseModel):
    ip_address: str | None = None
    user_agent: str | None = None
    request_id: str | None = None
    service: str | None = None
    scope: dict[str, str] | None = None


class Changes(BaseModel):
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None


class AuditLog(Document, EnvironmentMixin):
    timestamp: float = Field(default_factory=time.time)
    actor_id: str
    actor_type: str
    action: str
    target_type: str
    target_id: str
    changes: Changes
    context: AuditContext

    class Settings:
        name = "audit_logs"
        indexes = [
            IndexModel([("environment_id", 1), ("timestamp", DESCENDING)]),
            IndexModel(
                [("environment_id", 1), ("actor_id", 1), ("timestamp", DESCENDING)]
            ),
            IndexModel(
                [
                    ("environment_id", 1),
                    ("target_type", 1),
                    ("target_id", 1),
                    ("timestamp", DESCENDING),
                ]
            ),
            IndexModel(
                [("environment_id", 1), ("action", 1), ("timestamp", DESCENDING)]
            ),
            IndexModel([("timestamp", 1)], expireAfterSeconds=63072000),  # 2 years
        ]
