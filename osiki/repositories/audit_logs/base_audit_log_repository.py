from abc import ABC, abstractmethod

from pymongo.asynchronous.client_session import AsyncClientSession

from osiki.models.audit_log import AuditLog


def split_actions(actions: list[str]) -> tuple[list[str], list[str]]:
    """Exact actions and prefixes (values ending in ``.``) of an action filter."""
    prefixes = [a for a in actions if a.endswith(".")]
    return [a for a in actions if not a.endswith(".")], prefixes


class BaseAuditLogRepository(ABC):
    @abstractmethod
    async def create(
        self, audit_log: AuditLog, session: AsyncClientSession | None = None
    ) -> AuditLog: ...

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

    @abstractmethod
    async def count(
        self,
        tenant_id: str | None,
        session: AsyncClientSession | None = None,
        actions: list[str] | None = None,
    ) -> int:
        """Entries ``list`` ranges over; ``tenant_id=None`` counts every entry.

        ``actions`` narrows to exact actions, or prefixes when a value ends in
        ``.``; ``None`` or empty keeps every action.
        """

    @abstractmethod
    async def list(
        self,
        tenant_id: str | None,
        skip: int,
        limit: int,
        session: AsyncClientSession | None = None,
        actions: list[str] | None = None,
    ) -> list[AuditLog]:
        """Newest first; ``tenant_id=None`` returns every entry."""
