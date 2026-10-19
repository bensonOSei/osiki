from abc import ABC, abstractmethod

from osiki.models.user_role import UserRole


class BaseUserRoleRepository(ABC):
    @abstractmethod
    async def create(self, user_role: UserRole) -> UserRole: ...

    @abstractmethod
    async def get_by_id(self, user_role_id: str) -> UserRole | None: ...

    @abstractmethod
    async def get_user_roles(self, user_id: str) -> list[UserRole]: ...

    @abstractmethod
    async def get_users_with_role(self, role_id: str) -> list[UserRole]: ...

    @abstractmethod
    async def get_by_tenant(
        self, tenant_id: str, role_id: str | None = None
    ) -> list[UserRole]: ...

    @abstractmethod
    async def find_assignment(
        self, user_id: str, role_id: str, tenant_id: str | None = None
    ) -> UserRole | None:
        """The active assignment scoped to ``tenant_id``.

        ``tenant_id=None`` matches only the project-wide assignment (no tenant),
        never a tenant-scoped one.
        """

    @abstractmethod
    async def revoke(self, user_role_id: str) -> bool: ...

    @abstractmethod
    async def get_expired(self, current_time: float) -> list[UserRole]: ...
