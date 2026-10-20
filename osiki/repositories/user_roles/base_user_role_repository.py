from abc import ABC, abstractmethod

from pymongo.asynchronous.client_session import AsyncClientSession

from osiki.models.user_role import UserRole


class BaseUserRoleRepository(ABC):
    @abstractmethod
    async def create(
        self, user_role: UserRole, *, session: AsyncClientSession | None = None
    ) -> UserRole: ...

    @abstractmethod
    async def get_by_id(
        self, user_role_id: str, *, session: AsyncClientSession | None = None
    ) -> UserRole | None: ...

    @abstractmethod
    async def get_user_roles(
        self, user_id: str, *, session: AsyncClientSession | None = None
    ) -> list[UserRole]: ...

    @abstractmethod
    async def get_users_with_role(self, role_id: str) -> list[UserRole]: ...

    @abstractmethod
    async def count_active(
        self,
        role_ids: list[str],
        scope_filter: dict[str, str],
        now: float,
        *,
        exact: bool = False,
        session: AsyncClientSession | None = None,
    ) -> int:
        """Active, unexpired assignments of any of ``role_ids``.

        An assignment counts when its scope carries every ``scope_filter`` key
        with the same value (``{}`` counts every scope). ``exact=True`` also
        requires that it carries no other scope key.
        """

    @abstractmethod
    async def get_by_tenant(
        self,
        tenant_id: str,
        role_id: str | None = None,
        *,
        session: AsyncClientSession | None = None,
    ) -> list[UserRole]: ...

    @abstractmethod
    async def find_assignment(
        self,
        user_id: str,
        role_id: str,
        tenant_id: str | None = None,
        *,
        session: AsyncClientSession | None = None,
    ) -> UserRole | None:
        """The active assignment scoped to ``tenant_id``.

        ``tenant_id=None`` matches only the project-wide assignment (no tenant),
        never a tenant-scoped one.
        """

    @abstractmethod
    async def revoke(
        self, user_role_id: str, *, session: AsyncClientSession | None = None
    ) -> bool: ...

    @abstractmethod
    async def get_expired(self, current_time: float) -> list[UserRole]: ...
