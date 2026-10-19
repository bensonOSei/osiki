from abc import ABC, abstractmethod

from osiki.models.role import Role


class BaseRoleRepository(ABC):
    @abstractmethod
    async def create(self, role: Role) -> Role: ...

    @abstractmethod
    async def get_by_id(self, role_id: str) -> Role | None: ...

    @abstractmethod
    async def get_by_name(self, name: str) -> Role | None: ...

    @abstractmethod
    async def get_by_ids(self, role_ids: list[str]) -> list[Role]: ...

    @abstractmethod
    async def get_all_active(self) -> list[Role]:
        """Every active role in the environment, unpaginated."""

    @abstractmethod
    async def get_children(self, parent_role_id: str) -> list[Role]: ...

    @abstractmethod
    async def update(self, role: Role) -> Role: ...

    @abstractmethod
    async def deactivate(self, role_id: str) -> bool: ...

    @abstractmethod
    async def list_active(self, skip: int = 0, limit: int = 100) -> list[Role]: ...

    @abstractmethod
    async def add_permission(
        self, role_id: str, permission_id: str, condition_id: str | None = None
    ) -> bool: ...

    @abstractmethod
    async def remove_permission(
        self, role_id: str, permission_id: str, condition_id: str | None = None
    ) -> bool: ...

    @abstractmethod
    async def is_condition_in_use(self, condition_id: str) -> bool: ...
