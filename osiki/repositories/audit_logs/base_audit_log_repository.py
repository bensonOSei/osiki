from abc import ABC, abstractmethod

from osiki.models.audit_log import AuditLog


class BaseAuditLogRepository(ABC):
    @abstractmethod
    async def create(self, audit_log: AuditLog) -> AuditLog: ...

    @abstractmethod
    async def get_by_actor(
        self, actor_id: str, skip: int = 0, limit: int = 100
    ) -> list[AuditLog]: ...

    @abstractmethod
    async def get_by_target(
        self, target_type: str, target_id: str, skip: int = 0, limit: int = 100
    ) -> list[AuditLog]: ...

    @abstractmethod
    async def get_by_action(
        self, action: str, skip: int = 0, limit: int = 100
    ) -> list[AuditLog]: ...

    @abstractmethod
    async def get_recent(self, skip: int = 0, limit: int = 100) -> list[AuditLog]: ...
