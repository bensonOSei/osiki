import time
from typing import Literal

from beanie import Document
from pydantic import BaseModel, Field
from pymongo import DESCENDING, IndexModel

from osiki.models.base import EnvironmentMixin


class AccessContext(BaseModel):
    request_id: str | None = None
    service: str | None = None
    ip_address: str | None = None


class AccessLog(Document, EnvironmentMixin):
    timestamp: float = Field(default_factory=time.time)
    user_id: str
    resource: str
    action: str
    scope: dict[str, str] = Field(default_factory=dict)
    tenant_id: str | None = None
    allowed: bool
    matched_permission: str | None = None
    matched_via: str | None = None
    condition: str | None = None
    denial_reason: str | None = None
    latency_ms: float
    cache_hit: bool
    context: AccessContext
    source: Literal["server", "sdk"] = "server"

    class Settings:
        name = "access_logs"
        indexes = [
            IndexModel([("environment_id", 1), ("timestamp", DESCENDING)]),
            IndexModel(
                [("environment_id", 1), ("user_id", 1), ("timestamp", DESCENDING)]
            ),
            IndexModel(
                [("environment_id", 1), ("allowed", 1), ("timestamp", DESCENDING)]
            ),
            IndexModel(
                [
                    ("environment_id", 1),
                    ("resource", 1),
                    ("action", 1),
                    ("timestamp", DESCENDING),
                ]
            ),
            IndexModel([("timestamp", 1)], expireAfterSeconds=7776000),  # 90 days
        ]
