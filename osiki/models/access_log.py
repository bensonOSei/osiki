import time

from beanie import Document
from pydantic import BaseModel, Field
from pymongo import DESCENDING, IndexModel


class AccessContext(BaseModel):
    request_id: str | None = None
    service: str | None = None
    ip_address: str | None = None


class AccessLog(Document):
    timestamp: float = Field(default_factory=time.time)
    user_id: str
    resource: str
    action: str
    scope: dict[str, str] = Field(default_factory=dict)
    allowed: bool
    matched_permission: str | None = None
    matched_via: str | None = None
    denial_reason: str | None = None
    latency_ms: float
    cache_hit: bool
    context: AccessContext

    class Settings:
        name = "access_logs"
        indexes = [
            IndexModel([("timestamp", DESCENDING)]),
            IndexModel([("user_id", 1), ("timestamp", DESCENDING)]),
            IndexModel([("allowed", 1), ("timestamp", DESCENDING)]),
            IndexModel([("resource", 1), ("action", 1), ("timestamp", DESCENDING)]),
            IndexModel([("timestamp", 1)], expireAfterSeconds=7776000),  # 90 days
        ]
