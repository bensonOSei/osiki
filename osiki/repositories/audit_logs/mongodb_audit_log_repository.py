from loguru import logger

from osiki.models.audit_log import AuditLog
from osiki.repositories.audit_logs.base_audit_log_repository import (
    BaseAuditLogRepository,
)


class MongoDBAuditLogRepository(BaseAuditLogRepository):
    def __init__(self, environment_id: str) -> None:
        self.environment_id = environment_id

    async def create(self, audit_log: AuditLog) -> AuditLog:
        audit_log.environment_id = self.environment_id
        await audit_log.insert()
        logger.debug(
            "Audit log created",
            audit_log_id=str(audit_log.id),
            actor_id=audit_log.actor_id,
            action=audit_log.action,
            target_type=audit_log.target_type,
            target_id=audit_log.target_id,
        )
        return audit_log

    async def get_by_actor(
        self, actor_id: str, skip: int = 0, limit: int = 100
    ) -> list[AuditLog]:
        return (
            await AuditLog.find(
                AuditLog.environment_id == self.environment_id,
                AuditLog.actor_id == actor_id,
            )
            .sort("-timestamp")
            .skip(skip)
            .limit(limit)
            .to_list()
        )

    async def get_by_target(
        self, target_type: str, target_id: str, skip: int = 0, limit: int = 100
    ) -> list[AuditLog]:
        return (
            await AuditLog.find(
                AuditLog.environment_id == self.environment_id,
                AuditLog.target_type == target_type,
                AuditLog.target_id == target_id,
            )
            .sort("-timestamp")
            .skip(skip)
            .limit(limit)
            .to_list()
        )

    async def get_by_action(
        self, action: str, skip: int = 0, limit: int = 100
    ) -> list[AuditLog]:
        return (
            await AuditLog.find(
                AuditLog.environment_id == self.environment_id,
                AuditLog.action == action,
            )
            .sort("-timestamp")
            .skip(skip)
            .limit(limit)
            .to_list()
        )

    async def get_recent(self, skip: int = 0, limit: int = 100) -> list[AuditLog]:
        return (
            await AuditLog.find(
                AuditLog.environment_id == self.environment_id,
            )
            .sort("-timestamp")
            .skip(skip)
            .limit(limit)
            .to_list()
        )
