from fastapi import APIRouter, Query, status

from osiki.api.actor import ActorDep
from osiki.api.dependencies import AuditLogRepository
from osiki.schemas.audit_log import AuditLogCreate, AuditLogRead
from osiki.schemas.base import PaginatedResponse
from osiki.services.audit.audit_writer import AuditWriter

router = APIRouter(prefix="/audit-logs", tags=["audit-logs"])


@router.get("")
async def list_audit_logs(
    audit_repo: AuditLogRepository,
    tenant_id: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> PaginatedResponse[AuditLogRead]:
    skip = (page - 1) * page_size
    logs = await audit_repo.list(tenant_id=tenant_id, skip=skip, limit=page_size)
    items = [AuditLogRead.from_model(log) for log in logs]
    # No count method on the repository yet; estimate like the other list routes.
    return PaginatedResponse.create(items, len(items) + skip, page, page_size)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_audit_log(
    body: AuditLogCreate,
    actor: ActorDep,
    audit_repo: AuditLogRepository,
) -> AuditLogRead:
    """Record an event with the header actor.

    Trusted-network only: the actor header is taken at face value, so a front
    door must never let outside callers reach this route.
    """
    entry = await AuditWriter(audit_repo).record(
        actor,
        body.action,
        body.target_type,
        body.target_id,
        tenant_id=body.tenant_id,
        before=body.before,
        after=body.after,
    )
    return AuditLogRead.from_model(entry)
