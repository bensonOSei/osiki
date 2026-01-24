from abc import ABC, abstractmethod

from osiki.models.permission import Permission


class BasePermissionRepository(ABC):
    @abstractmethod
    async def create(self, permission: Permission) -> Permission: ...

    @abstractmethod
    async def get_by_id(self, permission_id: str) -> Permission | None: ...

    @abstractmethod
    async def get_by_ids(self, permission_ids: list[str]) -> list[Permission]: ...

    @abstractmethod
    async def get_by_resource_action(
        self, resource: str, action: str
    ) -> Permission | None: ...

    @abstractmethod
    async def get_by_resource(self, resource: str) -> list[Permission]: ...

    @abstractmethod
    async def deactivate(self, permission_id: str) -> bool: ...

    @abstractmethod
    async def list_active(
        self, skip: int = 0, limit: int = 100
    ) -> list[Permission]: ...
