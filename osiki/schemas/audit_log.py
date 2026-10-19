from typing import Any

from pydantic import BaseModel

from osiki.models.audit_log import AuditLog


class AuditLogCreate(BaseModel):
    """An event a trusted front door logs itself (for example an invite)."""

    action: str
    target_type: str
    target_id: str
    tenant_id: str | None = None
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None


class AuditLogRead(BaseModel):
    id: str
    timestamp: float
    actor_id: str
    actor_type: str
    action: str
    target_type: str
    target_id: str
    tenant_id: str | None
    before: dict[str, Any] | None
    after: dict[str, Any] | None

    @classmethod
    def from_model(cls, log: AuditLog) -> "AuditLogRead":
        return cls(
            id=str(log.id),
            timestamp=log.timestamp,
            actor_id=log.actor_id,
            actor_type=log.actor_type,
            action=log.action,
            target_type=log.target_type,
            target_id=log.target_id,
            tenant_id=log.tenant_id,
            before=log.changes.before,
            after=log.changes.after,
        )
