from typing import Any

from pymongo.asynchronous.client_session import AsyncClientSession

from osiki.api.actor import Actor
from osiki.models.audit_log import AuditContext, AuditLog, Changes
from osiki.repositories.audit_logs.base_audit_log_repository import (
    BaseAuditLogRepository,
)


class AuditWriter:
    """Records who changed what, with the tenant as a top-level field."""

    def __init__(self, repo: BaseAuditLogRepository) -> None:
        self._repo = repo

    async def record(
        self,
        actor: Actor,
        action: str,
        target_type: str,
        target_id: str,
        *,
        tenant_id: str | None,
        before: dict[str, Any] | None,
        after: dict[str, Any] | None,
        session: AsyncClientSession | None = None,
    ) -> AuditLog:
        entry = AuditLog(
            actor_id=actor.id,
            actor_type=actor.type,
            action=action,
            target_type=target_type,
            target_id=target_id,
            tenant_id=tenant_id,
            changes=Changes(before=before, after=after),
            context=AuditContext(),
        )
        return await self._repo.create(entry, session=session)
