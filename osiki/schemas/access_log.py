from pydantic import BaseModel, Field


class AccessLogIngest(BaseModel):
    """One decision an SDK made locally."""

    timestamp: float
    user_id: str
    resource: str
    action: str
    scope: dict[str, str] = Field(default_factory=dict)
    allowed: bool
    matched_permission: str | None = None
    condition: str | None = None
    denial_reason: str | None = None
    latency_ms: float


class AccessLogBatch(BaseModel):
    entries: list[AccessLogIngest] = Field(min_length=1, max_length=500)


class AccessLogBatchResponse(BaseModel):
    accepted: int
