import random
import time

from fastapi import APIRouter, BackgroundTasks
from loguru import logger

from osiki.api.dependencies import AccessLogRepository, AuthorizationServiceDep
from osiki.configs.settings import get_settings
from osiki.decision.models import FilterResult
from osiki.models.access_log import AccessContext, AccessLog
from osiki.repositories.access_logs.base_access_log_repository import (
    BaseAccessLogRepository,
)
from osiki.schemas.authorization import (
    AuthorizationRequest,
    AuthorizationResponse,
    FilterRequest,
)

router = APIRouter(prefix="/authorization", tags=["authorization"])


async def _record_access(repo: BaseAccessLogRepository, log: AccessLog) -> None:
    """Write one access log; a failure here must never reach the caller."""
    try:
        await repo.create(log)
    except Exception:
        logger.exception("Failed to write access log")


@router.post("/check")
async def check_authorization(
    request: AuthorizationRequest,
    auth_service: AuthorizationServiceDep,
    access_log_repo: AccessLogRepository,
    background_tasks: BackgroundTasks,
) -> AuthorizationResponse:
    scope = request.scope.to_dict() if request.scope else None
    started = time.perf_counter()
    result = await auth_service.authorize(
        user_id=request.user_id,
        resource=request.resource,
        action=request.action,
        scope=scope,
        record=request.record,
    )
    latency_ms = (time.perf_counter() - started) * 1000
    if (
        not result.allowed
        or random.random() < get_settings().access_log_success_sample_rate
    ):
        log = AccessLog(
            user_id=request.user_id,
            resource=request.resource,
            action=request.action,
            scope=scope or {},
            tenant_id=(scope or {}).get("tenant_id"),
            allowed=result.allowed,
            matched_permission=result.matched_permission,
            matched_via=result.matched_via,
            condition=result.condition,
            denial_reason=result.denial_reason,
            latency_ms=latency_ms,
            cache_hit=result.cache_hit,
            context=AccessContext(),
        )
        background_tasks.add_task(_record_access, access_log_repo, log)
    return AuthorizationResponse.model_validate(result)


@router.post("/filter")
async def filter_records(
    request: FilterRequest,
    auth_service: AuthorizationServiceDep,
) -> FilterResult:
    scope = request.scope.to_dict() if request.scope else None
    return await auth_service.filter(
        user_id=request.user_id,
        resource=request.resource,
        action=request.action,
        scope=scope,
    )
