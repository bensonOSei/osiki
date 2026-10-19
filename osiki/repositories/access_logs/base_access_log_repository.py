from abc import ABC, abstractmethod

from osiki.models.access_log import AccessLog


class BaseAccessLogRepository(ABC):
    @abstractmethod
    async def create(self, access_log: AccessLog) -> AccessLog: ...

    @abstractmethod
    async def create_many(self, logs: list[AccessLog]) -> int: ...

    @abstractmethod
    async def get_by_user(
        self, user_id: str, skip: int = 0, limit: int = 100
    ) -> list[AccessLog]: ...

    @abstractmethod
    async def get_denials(self, skip: int = 0, limit: int = 100) -> list[AccessLog]: ...

    @abstractmethod
    async def get_by_resource(
        self, resource: str, action: str | None = None, skip: int = 0, limit: int = 100
    ) -> list[AccessLog]: ...

    @abstractmethod
    async def get_recent(self, skip: int = 0, limit: int = 100) -> list[AccessLog]: ...
