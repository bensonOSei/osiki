from fastapi import APIRouter, status

from osiki.api.dependencies import AccessLogRepository
from osiki.models.access_log import AccessContext, AccessLog
from osiki.schemas.access_log import AccessLogBatch, AccessLogBatchResponse

router = APIRouter(prefix="/access-logs", tags=["access-logs"])


@router.post("/batch", status_code=status.HTTP_202_ACCEPTED)
async def ingest_access_logs(
    batch: AccessLogBatch,
    access_log_repo: AccessLogRepository,
) -> AccessLogBatchResponse:
    logs = [
        AccessLog(
            timestamp=entry.timestamp,
            user_id=entry.user_id,
            resource=entry.resource,
            action=entry.action,
            scope=entry.scope,
            tenant_id=entry.scope.get("tenant_id"),
            allowed=entry.allowed,
            matched_permission=entry.matched_permission,
            condition=entry.condition,
            denial_reason=entry.denial_reason,
            latency_ms=entry.latency_ms,
            cache_hit=False,
            context=AccessContext(),
            source="sdk",
        )
        for entry in batch.entries
    ]
    return AccessLogBatchResponse(accepted=await access_log_repo.create_many(logs))
